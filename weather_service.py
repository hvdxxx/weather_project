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


def get_forecast_rows() -> list[dict[str, Any]]:
    """Сравнение последних сохранённых прогнозов, начиная с текущего часа."""
    metno_points = weather_db.load_latest_forecast(METNO)
    open_meteo_points = weather_db.load_latest_forecast(OPEN_METEO)
    if not metno_points and not open_meteo_points:
        return []
    return build_combined_forecast(
        metno_points,
        open_meteo_points,
        start_utc=_hour_floor(),
    )


def get_sources() -> dict[str, Any]:
    """Последние снимки каждого источника с признаком доступности."""
    sources = {}
    for provider in (METNO, OPEN_METEO):
        points = weather_db.load_latest_forecast(provider)
        sources[provider] = {
            "status": "ok" if points else "unavailable",
            "count": len(points),
            "fetched_at_utc": points[0].get("fetched_at_utc") if points else None,
            "error": None,
            "points": points,
        }

    return {
        "generated_at_utc": _utc_now(),
        "city": config.CITY,
        "sources": sources,
    }


def get_combined_rows() -> list[dict[str, Any]]:
    """Сохранённые объединённые прогнозы, начиная с текущего часа."""
    threshold = _hour_floor()
    return [
        row
        for row in weather_db.load_latest_combined()
        if row["ts_utc"] >= threshold
    ]


def get_differences_rows() -> list[dict[str, Any]] | None:
    """Расхождения по последним прогнозам; None — если прогнозов нет."""
    rows = get_forecast_rows()
    if not rows:
        return None
    return [
        {
            "ts_utc": row["ts_utc"],
            "differences": row["differences"],
            "availability": row["availability"],
        }
        for row in rows
        if row["differences"] is not None
    ]


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
