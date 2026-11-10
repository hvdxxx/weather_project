"""Синхронизация прогнозов по UTC и расчёт объединённого прогноза.

Правила:
- источники сопоставляются только по точному времени UTC, не по порядку;
- числовые значения усредняются только при наличии обоих значений;
- направление ветра усредняется как круговая величина;
- коды погоды не усредняются: совпали — общий код, иначе None;
- отсутствующие значения остаются None, нулями не подменяются.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import weather_api_config as config
from weather_common import NUMERIC_FIELDS, as_float, parse_utc_timestamp

logger = logging.getLogger(__name__)

DIFF_FIELDS = (
    "temperature",
    "humidity",
    "wind_speed",
    "precipitation",
    "precipitation_probability",
)

# Направление ветра обрабатывается отдельно, поэтому в обычное среднее не входит.
COMBINED_NUMERIC_FIELDS = tuple(
    field for field in NUMERIC_FIELDS if field != "wind_direction"
)


def _mean_if_both(metno_value: Any, open_meteo_value: Any) -> float | None:
    metno = as_float(metno_value)
    open_meteo = as_float(open_meteo_value)
    if metno is None or open_meteo is None:
        return None
    return (metno + open_meteo) / 2


def circular_mean(metno_direction: Any, open_meteo_direction: Any) -> float | None:
    """Круговое среднее направлений ветра через векторное представление."""
    metno = as_float(metno_direction)
    open_meteo = as_float(open_meteo_direction)
    if metno is None or open_meteo is None:
        return None

    first = math.radians(metno % 360)
    second = math.radians(open_meteo % 360)
    x = math.cos(first) + math.cos(second)
    y = math.sin(first) + math.sin(second)

    # Почти противоположные направления: среднее не имеет физического смысла.
    if math.hypot(x, y) / 2 < config.WIND_DIRECTION_MIN_RESULTANT:
        return None

    angle = math.degrees(math.atan2(y, x)) % 360.0
    # Для направлений чуть меньше 0 градусов Python даёт 360.0.
    if math.isclose(angle, 360.0, abs_tol=1e-9):
        return 0.0
    return angle


def classify_difference(field: str, abs_delta: float) -> str:
    """Категория расхождения по порогам из конфигурации."""
    limits = config.DIFF_THRESHOLDS[field]
    if abs_delta <= limits["moderate"]:
        return "small"
    if abs_delta <= limits["large"]:
        return "moderate"
    return "large"


def _combine_point(
    metno_point: dict[str, Any],
    open_meteo_point: dict[str, Any],
) -> dict[str, Any]:
    combined: dict[str, Any] = {
        field: _mean_if_both(metno_point.get(field), open_meteo_point.get(field))
        for field in COMBINED_NUMERIC_FIELDS
    }
    combined["wind_direction"] = circular_mean(
        metno_point.get("wind_direction"),
        open_meteo_point.get("wind_direction"),
    )

    metno_code = metno_point.get("weather_code")
    open_meteo_code = open_meteo_point.get("weather_code")
    if metno_code is None or open_meteo_code is None:
        combined["weather_code"] = None
        combined["weather_code_agreement"] = None
    else:
        agreement = metno_code == open_meteo_code
        combined["weather_code"] = metno_code if agreement else None
        combined["weather_code_agreement"] = agreement

    combined["derived"] = True
    return combined


def _differences(
    metno_point: dict[str, Any],
    open_meteo_point: dict[str, Any],
) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    for field in DIFF_FIELDS:
        metno = as_float(metno_point.get(field))
        open_meteo = as_float(open_meteo_point.get(field))
        if metno is None or open_meteo is None:
            differences[field] = None
            continue

        delta = open_meteo - metno
        differences[field] = {
            "delta": delta,
            "abs_delta": abs(delta),
            "level": classify_difference(field, abs(delta)),
        }
    return differences


def _index_points(
    points: list[dict[str, Any]],
    provider: str,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for point in points:
        ts_utc = point.get("ts_utc")
        if not isinstance(ts_utc, str) or not ts_utc:
            raise ValueError(f"{provider}: точка прогноза без ts_utc")
        if ts_utc in index:
            logger.warning("%s: дубликат времени %s, оставлена последняя точка", provider, ts_utc)
        index[ts_utc] = point
    return index


def build_combined_forecast(
    metno_points: list[dict[str, Any]],
    open_meteo_points: list[dict[str, Any]],
    start_utc: str | None = None,
) -> list[dict[str, Any]]:
    """Строит построчное сравнение источников и объединённый прогноз.

    Строки с единственным источником сохраняются для показа доступности,
    но combined и differences у них None: объединённый прогноз недоступен.
    """
    if start_utc is not None:
        start_utc = parse_utc_timestamp(start_utc)

    metno_index = _index_points(metno_points, "metno")
    open_meteo_index = _index_points(open_meteo_points, "open_meteo")

    rows: list[dict[str, Any]] = []
    for ts_utc in sorted(set(metno_index) | set(open_meteo_index)):
        if start_utc is not None and ts_utc < start_utc:
            continue

        metno_point = metno_index.get(ts_utc)
        open_meteo_point = open_meteo_index.get(ts_utc)
        both_available = metno_point is not None and open_meteo_point is not None

        rows.append(
            {
                "ts_utc": ts_utc,
                "metno": metno_point,
                "open_meteo": open_meteo_point,
                "combined": (
                    _combine_point(metno_point, open_meteo_point)
                    if both_available
                    else None
                ),
                "differences": (
                    _differences(metno_point, open_meteo_point)
                    if both_available
                    else None
                ),
                "availability": {
                    "metno": metno_point is not None,
                    "open_meteo": open_meteo_point is not None,
                },
            }
        )

    return rows
