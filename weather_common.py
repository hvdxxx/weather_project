"""Единая схема нормализованных точек и общие преобразования значений."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

METNO = "metno"
OPEN_METEO = "open_meteo"

# Числовые параметры, которые хранятся для каждого источника.
NUMERIC_FIELDS = (
    "temperature",
    "humidity",
    "apparent_temperature",
    "wind_speed",
    "wind_direction",
    "wind_gusts",
    "precipitation",
    "precipitation_probability",
    "snowfall",
    "cloud_cover",
    "rain",
)

# Полный набор полей нормализованной точки (weather_code не усредняется).
POINT_FIELDS = ("ts_utc", "provider", *NUMERIC_FIELDS, "weather_code", "weather_symbol")


def as_float(value: Any) -> float | None:
    """Число из ответа API; None, строки и bool означают отсутствие данных."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_utc_timestamp(value: Any) -> str:
    """Проверяет временную метку с часовым поясом и возвращает ISO-время UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("пустая временная метка")

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("временная метка без часового пояса")

    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
