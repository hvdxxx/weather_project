"""Клиент MET Norway: текущая погода и прогноз.

Compact-ответ не содержит apparent_temperature, порывов ветра, снега и
вероятности осадков — эти поля остаются None. Код погоды MET (symbol_code)
приблизительно переводится в WMO для сравнения с Open-Meteo; исходный
symbol_code сохраняется в weather_symbol.
"""
from __future__ import annotations

import logging
from typing import Any

import weather_api_config as config
from weather_common import METNO, as_float, parse_utc_timestamp
from weather_http import WeatherAPIError, http_get_json, invalidate_cache

logger = logging.getLogger(__name__)

PROVIDER = METNO

# Приблизительное соответствие symbol_code MET Norway кодам WMO.
# Для сравнения прогнозов; исходный symbol_code сохраняется отдельно.
SYMBOL_TO_WMO: dict[str, int] = {
    "clearsky": 0,
    "fair": 1,
    "partlycloudy": 2,
    "cloudy": 3,
    "fog": 45,
    "lightdrizzle": 51,
    "drizzle": 53,
    "heavydrizzle": 55,
    "lightrain": 61,
    "rain": 63,
    "heavyrain": 65,
    "lightsleet": 68,
    "sleet": 68,
    "heavysleet": 69,
    "lightsnow": 71,
    "snow": 73,
    "heavysnow": 75,
    "lightrainshowers": 80,
    "rainshowers": 81,
    "heavyrainshowers": 82,
    "lightsleetshowers": 85,
    "sleetshowers": 85,
    "heavysleetshowers": 86,
    "lightsnowshowers": 85,
    "snowshowers": 85,
    "heavysnowshowers": 86,
    "lightrainandthunder": 95,
    "rainandthunder": 95,
    "heavyrainandthunder": 95,
    "lightsleetandthunder": 95,
    "sleetandthunder": 95,
    "heavysleetandthunder": 95,
    "lightsnowandthunder": 95,
    "snowandthunder": 95,
    "heavysnowandthunder": 95,
    "thunderstorm": 95,
}

_TIME_SUFFIXES = ("_day", "_night", "_polartwilight")


def symbol_to_wmo(symbol: Any) -> int | None:
    """Переводит symbol_code (с суффиксом времени суток) в код WMO."""
    if not isinstance(symbol, str) or not symbol:
        return None

    base = symbol
    for suffix in _TIME_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    code = SYMBOL_TO_WMO.get(base)
    if code is None:
        logger.debug("metno: неизвестный symbol_code %r", symbol)
    return code


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_metno(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Приводит ответ MET Norway к единой структуре с временем в UTC."""
    properties = _as_dict(payload.get("properties"))
    timeseries = properties.get("timeseries")
    if not isinstance(timeseries, list) or not timeseries:
        raise WeatherAPIError("metno: в ответе отсутствует properties.timeseries")

    points: list[dict[str, Any]] = []

    for entry in timeseries:
        if not isinstance(entry, dict):
            raise WeatherAPIError("metno: некорректная запись timeseries")

        try:
            ts_utc = parse_utc_timestamp(entry.get("time"))
        except ValueError as exc:
            raise WeatherAPIError(f"metno: некорректная временная метка: {exc}") from exc

        data = entry.get("data")
        if not isinstance(data, dict):
            raise WeatherAPIError("metno: у точки прогноза отсутствует data")

        instant = _as_dict(data.get("instant"))
        details = instant.get("details")
        if not isinstance(details, dict):
            raise WeatherAPIError("metno: у точки прогноза отсутствуют instant.details")

        next_1h = _as_dict(data.get("next_1_hours"))
        next_6h = _as_dict(data.get("next_6_hours"))
        period = next_1h or next_6h

        symbol = _as_dict(period.get("summary")).get("symbol_code")
        period_details = _as_dict(period.get("details"))

        # Осадки берём только за часовой интервал: 6-часовую сумму нельзя
        # сравнивать с почасовыми значениями Open-Meteo.
        precipitation = (
            as_float(period_details.get("precipitation_amount")) if next_1h else None
        )
        probability = (
            as_float(period_details.get("probability_of_precipitation"))
            if next_1h
            else None
        )

        points.append(
            {
                "ts_utc": ts_utc,
                "provider": PROVIDER,
                "temperature": as_float(details.get("air_temperature")),
                "humidity": as_float(details.get("relative_humidity")),
                "apparent_temperature": None,
                "wind_speed": as_float(details.get("wind_speed")),
                "wind_direction": as_float(details.get("wind_from_direction")),
                "wind_gusts": None,
                "precipitation": precipitation,
                "precipitation_probability": probability,
                "snowfall": None,
                "cloud_cover": as_float(details.get("cloud_area_fraction")),
                "rain": None,
                "weather_code": symbol_to_wmo(symbol),
                "weather_symbol": symbol if isinstance(symbol, str) else None,
            }
        )

    return points


def fetch_metno_forecast() -> list[dict[str, Any]]:
    """Запрашивает прогноз MET Norway и возвращает нормализованные точки."""
    params = {"lat": config.LATI, "lon": config.LONG}
    payload = http_get_json(
        config.URL,
        params=params,
        provider=PROVIDER,
        ttl_sec=config.MET_CACHE_TTL_SEC,
        headers={"User-Agent": config.USER_AGENT},
    )
    try:
        return normalize_metno(payload)
    except WeatherAPIError:
        invalidate_cache(config.URL, params)
        raise


def take_weather():
    """Текущая погода для обратной совместимости с main.py."""
    try:
        points = fetch_metno_forecast()
    except WeatherAPIError as exc:
        logger.warning("MET Norway: %s", exc)
        return None

    if not points:
        return None

    first = points[0]
    if (
        first["temperature"] is None
        or first["humidity"] is None
        or first["wind_speed"] is None
    ):
        logger.warning("MET Norway: в первой точке нет температуры, влажности или ветра")
        return None

    return {
        "temp": first["temperature"],
        "humidity": first["humidity"],
        "wind": first["wind_speed"],
    }
