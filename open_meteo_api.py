"""Клиент Open-Meteo: почасовой прогноз по координатам из общей конфигурации.

Единицы нормализованных данных: температура — °C, ветер — м/с,
осадки — мм, снег — см (так отдаёт Open-Meteo), влажность и облачность — %,
направление ветра — градусы. MET Norway снег в compact-ответе не отдаёт,
поэтому смешивания единиц не возникает.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import weather_api_config as config
from weather_common import OPEN_METEO, as_float
from weather_http import WeatherAPIError, http_get_json, invalidate_cache

logger = logging.getLogger(__name__)

PROVIDER = OPEN_METEO

# Поля Open-Meteo -> единые имена Weather Collector.
FIELD_MAP = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "apparent_temperature": "apparent_temperature",
    "precipitation_probability": "precipitation_probability",
    "precipitation": "precipitation",
    "rain": "rain",
    "snowfall": "snowfall",
    "weather_code": "weather_code",
    "cloud_cover": "cloud_cover",
    "wind_speed_10m": "wind_speed",
    "wind_direction_10m": "wind_direction",
    "wind_gusts_10m": "wind_gusts",
}


def build_params() -> dict[str, Any]:
    """Параметры запроса к Open-Meteo."""
    return {
        "latitude": config.LATI,
        "longitude": config.LONG,
        "hourly": ",".join(config.OPEN_METEO_HOURLY_PARAMS),
        "timezone": "auto",
        "forecast_days": config.OPEN_METEO_FORECAST_DAYS,
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }


def fetch_open_meteo_forecast() -> list[dict[str, Any]]:
    """Запрашивает прогноз и возвращает нормализованные почасовые точки."""
    params = build_params()
    payload = http_get_json(
        config.OPEN_METEO_URL,
        params=params,
        provider=PROVIDER,
        ttl_sec=config.OPEN_METEO_CACHE_TTL_SEC,
        headers={"User-Agent": config.USER_AGENT},
    )
    try:
        return normalize_open_meteo(payload)
    except WeatherAPIError:
        invalidate_cache(config.OPEN_METEO_URL, params)
        raise


def normalize_open_meteo(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Приводит ответ Open-Meteo к единой структуре с временем в UTC."""
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherAPIError("open_meteo: в ответе отсутствует блок hourly")

    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise WeatherAPIError("open_meteo: в ответе нет почасовых временных меток")

    offset = payload.get("utc_offset_seconds")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise WeatherAPIError("open_meteo: не удалось определить часовой пояс (utc_offset_seconds)")

    local_tz = timezone(timedelta(seconds=offset))
    columns: dict[str, list[Any]] = {}

    for source_name, target_name in FIELD_MAP.items():
        values = hourly.get(source_name)
        if not isinstance(values, list):
            logger.warning("open_meteo: поле %s отсутствует в ответе", source_name)
            values = [None] * len(times)
        elif len(values) != len(times):
            raise WeatherAPIError(
                f"open_meteo: длина поля {source_name} не совпадает с числом временных меток"
            )
        columns[target_name] = values

    points: list[dict[str, Any]] = []
    for index, raw_time in enumerate(times):
        if not isinstance(raw_time, str):
            raise WeatherAPIError("open_meteo: некорректная временная метка в ответе")
        try:
            local_time = datetime.fromisoformat(raw_time)
        except ValueError as exc:
            raise WeatherAPIError(
                f"open_meteo: некорректная временная метка {raw_time!r}"
            ) from exc

        if local_time.tzinfo is None:
            local_time = local_time.replace(tzinfo=local_tz)
        utc_time = local_time.astimezone(timezone.utc)

        point: dict[str, Any] = {
            "ts_utc": utc_time.isoformat(timespec="seconds"),
            "provider": PROVIDER,
        }
        for target_name, values in columns.items():
            point[target_name] = as_float(values[index])
        point["weather_symbol"] = None
        points.append(point)

    return points
