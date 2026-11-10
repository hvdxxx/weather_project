"""Централизованная конфигурация Weather Collector.

Значения можно переопределить через переменные окружения или файл .env
в корне проекта (образец — .env.example). Секреты в коде не хранятся.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Загружает KEY=VALUE из .env, не перезаписывая уже заданные переменные."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: ожидается целое число, получено {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: ожидается число, получено {raw!r}") from exc


# --- Место и время ---------------------------------------------------------
CITY = os.getenv("WEATHER_CITY", "Yakutsk").strip() or "Yakutsk"
LATI = _env_float("WEATHER_LAT", 62.01436)
LONG = _env_float("WEATHER_LON", 129.7124)
TIMEZONE = os.getenv("WEATHER_TIMEZONE", "Asia/Yakutsk").strip() or "Asia/Yakutsk"

INTERVAL_MIN = _env_int("WEATHER_INTERVAL_MIN", 30)
PLOT_EVERY = _env_int("WEATHER_PLOT_EVERY", 5)

# --- Хранилище -------------------------------------------------------------
# SQLite — основное хранилище; CSV остаётся историческим источником.
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("WEATHER_DB_PATH", str(DATA_DIR / "weather.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

# Наблюдение считается актуальным не дольше этого срока.
CURRENT_MAX_AGE_HOURS = _env_int("WEATHER_CURRENT_MAX_AGE_HOURS", 6)

PLOTS_DIR = Path(os.getenv("WEATHER_PLOTS_DIR", str(DATA_DIR / "plots")))
if not PLOTS_DIR.is_absolute():
    PLOTS_DIR = BASE_DIR / PLOTS_DIR

# --- Идентификация приложения ---------------------------------------------
# MET Norway требует User-Agent с названием приложения и контактом.
APP_NAME = "weather-collector"
APP_VERSION = "2.0"
CONTACT_EMAIL = os.getenv("WEATHER_CONTACT_EMAIL", "").strip()
USER_AGENT = f"{APP_NAME}/{APP_VERSION} {CONTACT_EMAIL}".strip()
if not CONTACT_EMAIL:
    USER_AGENT += " (contact not configured)"

# --- Источники данных ------------------------------------------------------
URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

OPEN_METEO_FORECAST_DAYS = 7
OPEN_METEO_HOURLY_PARAMS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)

# --- HTTP и кэш ------------------------------------------------------------
TIMEOUT = _env_int("WEATHER_TIMEOUT_SEC", 15)
HTTP_CONNECT_TIMEOUT = 5
HTTP_READ_TIMEOUT = TIMEOUT
HTTP_MAX_ATTEMPTS = 3
HTTP_BACKOFF_BASE_SEC = 0.5
HTTP_BACKOFF_MAX_SEC = 8.0
HTTP_MIN_INTERVAL_SEC = 1.0

# MET обновляет прогноз примерно раз в час, Open-Meteo — чаще.
MET_CACHE_TTL_SEC = 1800
OPEN_METEO_CACHE_TTL_SEC = 900

# --- Сравнение прогнозов ---------------------------------------------------
# Границы расхождений: <= moderate — небольшое, <= large — умеренное,
# больше large — существенное. Значения в единицах параметра.
DIFF_THRESHOLDS = {
    "temperature": {"moderate": 1.0, "large": 3.0},
    "humidity": {"moderate": 10.0, "large": 25.0},
    "wind_speed": {"moderate": 1.5, "large": 4.0},
    "precipitation": {"moderate": 0.5, "large": 2.0},
    "precipitation_probability": {"moderate": 20.0, "large": 50.0},
}

# Если направления ветра почти противоположны, круговое среднее не имеет
# физического смысла: модуль результирующего вектора меньше порога -> None.
WIND_DIRECTION_MIN_RESULTANT = 0.2
