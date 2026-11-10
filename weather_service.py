"""Сервисный слой: сбор прогнозов, чтение истории и подготовка данных для API."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import weather_api_config as config
import weather_db
from forecast_merge import build_combined_forecast
from open_meteo_api import fetch_open_meteo_forecast
from weather_api import fetch_metno_forecast
from weather_calc import calculate_stats, compare_forecasts
from weather_common import METNO, OPEN_METEO
from weather_http import WeatherAPIError

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hour_floor(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    return (
        moment.astimezone(timezone.utc)
        .replace(minute=0, second=0, microsecond=0)
        .isoformat(timespec="seconds")
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _age_hours(value: Any) -> float | None:
    moment = _parse_utc(value)
    if moment is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - moment).total_seconds() / 3600)


def _source_status(provider: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    """Свежесть последнего снимка и результат последней попытки сбора."""
    fetched_at = points[0].get("fetched_at_utc") if points else None
    event = weather_db.load_latest_fetch_event(provider)

    error = None
    last_attempt_at = None
    if event is not None:
        last_attempt_at = event.get("ts_utc")
        if event.get("status") == "error":
            error = event.get("error") or "ошибка сбора прогноза"

    age = _age_hours(fetched_at) if points else None
    stale = bool(points) and (
        age is None or age > config.FORECAST_MAX_AGE_HOURS
    )

    if not points:
        status = "error" if error else "unavailable"
    elif error:
        status = "error"
    elif stale:
        status = "stale"
    else:
        status = "ok"

    return {
        "status": status,
        "count": len(points),
        "fetched_at_utc": fetched_at,
        "age_hours": round(age, 2) if age is not None else None,
        "stale": stale,
        "error": error,
        "last_attempt_at_utc": last_attempt_at,
    }


def _load_snapshots() -> dict[str, list[dict[str, Any]]]:
    return {
        provider: weather_db.load_latest_forecast(provider)
        for provider in (METNO, OPEN_METEO)
    }


def _statuses_for(
    snapshots: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        provider: _source_status(provider, snapshots[provider])
        for provider in (METNO, OPEN_METEO)
    }


def collect_once(generate_plots: bool = False) -> dict[str, Any]:
    """Один цикл сбора двух прогнозов; источники работают независимо."""
    weather_db.init_db()
    generated_at = _utc_now()
    sources: dict[str, dict[str, Any]] = {}
    points: dict[str, list[dict[str, Any]]] = {}

    fetchers = {
        METNO: fetch_metno_forecast,
        OPEN_METEO: fetch_open_meteo_forecast,
    }

    for provider, fetcher in fetchers.items():
        try:
            source_points = fetcher()
        except WeatherAPIError as exc:
            sources[provider] = {
                "status": "error",
                "count": 0,
                "fetched_at_utc": None,
                "error": str(exc),
            }
            weather_db.log_update(
                "forecast_fetch",
                {"provider": provider, "status": "error", "error": str(exc)},
                level="warning",
            )
            logger.warning("%s: прогноз недоступен: %s", provider, exc)
        else:
            weather_db.insert_forecast_points(provider, generated_at, source_points)
            points[provider] = source_points
            sources[provider] = {
                "status": "ok",
                "count": len(source_points),
                "fetched_at_utc": generated_at,
                "error": None,
            }
            weather_db.log_update(
                "forecast_fetch",
                {"provider": provider, "status": "ok", "points": len(source_points)},
            )

    rows = build_combined_forecast(
        points.get(METNO, []),
        points.get(OPEN_METEO, []),
        start_utc=_hour_floor(),
    )
    combined_saved = weather_db.insert_combined_points(generated_at, rows)
    weather_db.log_update(
        "forecast_collection",
        {
            "matched": sum(1 for row in rows if row["combined"]),
            "combined_saved": combined_saved,
            "sources": {name: info["status"] for name, info in sources.items()},
        },
    )

    result: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "sources": sources,
        "rows": rows,
        "combined_saved": combined_saved,
    }

    if generate_plots and rows:
        from plotter import make_forecast_plots

        result["plots"] = make_forecast_plots(rows, output_dir=str(config.PLOTS_DIR))
    else:
        result["plots"] = {}

    return result


def get_current() -> dict[str, Any] | None:
    """Последнее наблюдение, если оно не старше CURRENT_MAX_AGE_HOURS."""
    rows = weather_db.load_observations(limit=1)
    if not rows:
        return None

    latest = rows[-1]
    try:
        observed_at = datetime.fromisoformat(latest["observed_at_utc"])
    except (TypeError, ValueError):
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    max_age = timedelta(hours=config.CURRENT_MAX_AGE_HOURS)
    if datetime.now(timezone.utc) - observed_at > max_age:
        return None
    return latest


def get_history(limit: int = 100, since: datetime | None = None) -> list[dict[str, Any]]:
    since_utc = None
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        since_utc = since.astimezone(timezone.utc).isoformat(timespec="seconds")
    return weather_db.load_observations(limit=limit, since_utc=since_utc)


def get_forecast_data() -> dict[str, Any]:
    """Строки сравнения, статусы источников и общий признак устаревания."""
    snapshots = _load_snapshots()
    statuses = _statuses_for(snapshots)

    rows: list[dict[str, Any]] = []
    if snapshots[METNO] or snapshots[OPEN_METEO]:
        rows = build_combined_forecast(
            snapshots[METNO],
            snapshots[OPEN_METEO],
            start_utc=_hour_floor(),
        )

    return {
        "rows": rows,
        "sources": statuses,
        "stale": any(info["stale"] for info in statuses.values() if info["count"]),
    }


def get_forecast_rows() -> list[dict[str, Any]]:
    """Сравнение последних сохранённых прогнозов, начиная с текущего часа."""
    return get_forecast_data()["rows"]


def get_sources() -> dict[str, Any]:
    """Последние снимки каждого источника с признаком доступности/свежести."""
    snapshots = _load_snapshots()
    sources = {}
    for provider in (METNO, OPEN_METEO):
        info = _source_status(provider, snapshots[provider])
        info["points"] = snapshots[provider]
        sources[provider] = info

    return {
        "generated_at_utc": _utc_now(),
        "city": config.CITY,
        "sources": sources,
    }


def get_combined_data() -> dict[str, Any]:
    """Сохранённый combined-снимок, его время и статусы источников."""
    threshold = _hour_floor()
    rows = [
        row
        for row in weather_db.load_latest_combined()
        if row["ts_utc"] >= threshold
    ]

    snapshots = _load_snapshots()
    statuses = _statuses_for(snapshots)
    generated_at = rows[0].get("generated_at_utc") if rows else None
    combined_age = _age_hours(generated_at) if rows else None
    stale = bool(rows) and (
        combined_age is None
        or combined_age > config.FORECAST_MAX_AGE_HOURS
        or any(info["stale"] for info in statuses.values() if info["count"])
    )

    return {
        "rows": rows,
        "sources": statuses,
        "stale": stale,
        "generated_at_utc": generated_at,
    }


def get_combined_rows() -> list[dict[str, Any]]:
    """Сохранённые объединённые прогнозы, начиная с текущего часа."""
    return get_combined_data()["rows"]


def get_differences_data() -> dict[str, Any]:
    """Расхождения по последним прогнозам и метаданные свежести."""
    data = get_forecast_data()
    rows = [
        {
            "ts_utc": row["ts_utc"],
            "differences": row["differences"],
            "availability": row["availability"],
        }
        for row in data["rows"]
        if row["differences"] is not None
    ]
    return {
        "available": bool(data["rows"]),
        "rows": rows,
        "sources": data["sources"],
        "stale": data["stale"],
    }


def get_differences_rows() -> list[dict[str, Any]] | None:
    """Расхождения по последним прогнозам; None — если прогнозов нет."""
    data = get_differences_data()
    return data["rows"] if data["available"] else None


def get_statistics() -> dict[str, Any]:
    """Статистика наблюдений и сравнение последних прогнозов."""
    history = get_history(limit=10000)
    observations = calculate_stats(
        [
            {
                "temp": record["temperature"],
                "humidity": record["humidity"],
                "wind": record["wind_speed"],
            }
            for record in history
            if record["temperature"] is not None
            and record["humidity"] is not None
            and record["wind_speed"] is not None
        ]
    )
    rows = get_forecast_rows()
    return {
        "city": config.CITY,
        "observations": observations,
        "forecast": compare_forecasts(rows),
    }
