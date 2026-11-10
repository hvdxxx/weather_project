"""SQLite-хранилище Weather Collector.

Таблицы: наблюдения, прогнозы источников, объединённые прогнозы,
история обновлений и метаданные (включая флаг миграции CSV).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import weather_api_config as config
from weather_common import METNO, NUMERIC_FIELDS

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

FORECAST_COLUMNS = (*NUMERIC_FIELDS, "weather_code", "weather_symbol")
COMBINED_COLUMNS = (*NUMERIC_FIELDS, "weather_code", "weather_code_agreement")

_COLUMN_TYPES = {
    "weather_code": "INTEGER",
    "weather_symbol": "TEXT",
    "weather_code_agreement": "INTEGER",
}


def _columns_sql(columns: tuple[str, ...]) -> str:
    return ",\n    ".join(
        f"{column} {_COLUMN_TYPES.get(column, 'REAL')}" for column in columns
    )


SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at_utc TEXT NOT NULL,
    city TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    wind_speed REAL,
    provider TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'live',
    fetched_at_utc TEXT NOT NULL,
    UNIQUE (provider, observed_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_observations_time
    ON observations (observed_at_utc);
CREATE INDEX IF NOT EXISTS idx_observations_provider_time
    ON observations (provider, observed_at_utc);

CREATE TABLE IF NOT EXISTS forecast_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    valid_at_utc TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    {_columns_sql(FORECAST_COLUMNS)},
    UNIQUE (provider, valid_at_utc, fetched_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_forecast_provider_time
    ON forecast_points (provider, valid_at_utc);
CREATE INDEX IF NOT EXISTS idx_forecast_fetched
    ON forecast_points (fetched_at_utc);

CREATE TABLE IF NOT EXISTS combined_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valid_at_utc TEXT NOT NULL,
    generated_at_utc TEXT NOT NULL,
    {_columns_sql(COMBINED_COLUMNS)},
    metno_available INTEGER NOT NULL,
    open_meteo_available INTEGER NOT NULL,
    UNIQUE (valid_at_utc, generated_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_combined_time
    ON combined_points (valid_at_utc);

CREATE TABLE IF NOT EXISTS update_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_update_log_time
    ON update_log (ts_utc);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Соединение с БД на время одной операции."""
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Создаёт схему и служебные записи; повторный вызов безопасен."""
    with connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def get_meta(key: str, default: str | None = None) -> str | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row is not None else default


def set_meta(key: str, value: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )


def log_update(
    event: str,
    details: Any = None,
    level: str = "info",
    ts_utc: str | None = None,
) -> None:
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)
    with connect() as connection:
        connection.execute(
            "INSERT INTO update_log (ts_utc, level, event, details) VALUES (?, ?, ?, ?)",
            (ts_utc or _utc_now(), level, event, details),
        )


def insert_observations(rows: Iterable[dict[str, Any]]) -> int:
    """Вставляет наблюдения, пропуская дубликаты; возвращает число новых строк."""
    rows = list(rows)
    if not rows:
        return 0

    now = _utc_now()
    params = [
        (
            row["observed_at_utc"],
            row["city"],
            row.get("temperature"),
            row.get("humidity"),
            row.get("wind_speed"),
            row.get("provider", METNO),
            row.get("source", "live"),
            row.get("fetched_at_utc") or now,
        )
        for row in rows
    ]

    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT OR IGNORE INTO observations (
                observed_at_utc, city, temperature, humidity, wind_speed,
                provider, source, fetched_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )
        return connection.total_changes - before


def insert_observation(**observation: Any) -> bool:
    """Вставляет одно наблюдение; False — если такая запись уже есть."""
    return insert_observations([observation]) > 0


def load_observations(
    limit: int | None = None,
    since_utc: str | None = None,
) -> list[dict[str, Any]]:
    """Наблюдения в хронологическом порядке (limit — последние N)."""
    if limit is not None and limit <= 0:
        return []

    conditions = []
    params: list[Any] = []
    if since_utc is not None:
        conditions.append("observed_at_utc >= ?")
        params.append(since_utc)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    with connect() as connection:
        if limit is None:
            rows = connection.execute(
                f"""
                SELECT observed_at_utc, city, temperature, humidity, wind_speed,
                       provider, source, fetched_at_utc
                FROM observations{where} ORDER BY observed_at_utc
                """,
                params,
            ).fetchall()
        else:
            rows = connection.execute(
                f"""
                SELECT observed_at_utc, city, temperature, humidity, wind_speed,
                       provider, source, fetched_at_utc
                FROM observations{where}
                ORDER BY observed_at_utc DESC LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            rows = list(reversed(rows))

    return [dict(row) for row in rows]


def insert_forecast_points(
    provider: str,
    fetched_at_utc: str,
    points: Iterable[dict[str, Any]],
) -> int:
    """Сохраняет снимок прогноза источника; дубликаты пропускаются."""
    points = list(points)
    if not points:
        return 0

    columns = ", ".join(("provider", "valid_at_utc", "fetched_at_utc", *FORECAST_COLUMNS))
    placeholders = ", ".join("?" for _ in range(3 + len(FORECAST_COLUMNS)))
    params = [
        (
            provider,
            point["ts_utc"],
            fetched_at_utc,
            *(point.get(column) for column in FORECAST_COLUMNS),
        )
        for point in points
    ]

    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            f"INSERT OR IGNORE INTO forecast_points ({columns}) VALUES ({placeholders})",
            params,
        )
        return connection.total_changes - before


def load_latest_forecast(provider: str) -> list[dict[str, Any]]:
    """Последний сохранённый снимок прогноза указанного источника."""
    with connect() as connection:
        row = connection.execute(
            "SELECT MAX(fetched_at_utc) AS fetched_at FROM forecast_points WHERE provider = ?",
            (provider,),
        ).fetchone()
        fetched_at = row["fetched_at"] if row is not None else None
        if fetched_at is None:
            return []

        rows = connection.execute(
            """
            SELECT * FROM forecast_points
            WHERE provider = ? AND fetched_at_utc = ?
            ORDER BY valid_at_utc
            """,
            (provider, fetched_at),
        ).fetchall()

    points = []
    for row in rows:
        point = dict(row)
        point.pop("id", None)
        point["ts_utc"] = point.pop("valid_at_utc")
        points.append(point)
    return points


def load_latest_fetch_event(provider: str) -> dict[str, Any] | None:
    """Последняя попытка сбора прогноза из update_log (без новой таблицы)."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT ts_utc, level, details FROM update_log
            WHERE event = 'forecast_fetch'
            ORDER BY id DESC LIMIT 50
            """
        ).fetchall()

    for row in rows:
        try:
            details = json.loads(row["details"] or "{}")
        except (TypeError, ValueError):
            continue
        if details.get("provider") != provider:
            continue
        return {
            "ts_utc": row["ts_utc"],
            "level": row["level"],
            "status": details.get("status"),
            "error": details.get("error"),
        }
    return None


def insert_combined_points(
    generated_at_utc: str,
    rows: Iterable[dict[str, Any]],
) -> int:
    """Сохраняет строки, для которых объединённый прогноз доступен."""
    params = []
    for row in rows:
        combined = row.get("combined")
        if not combined:
            continue
        availability = row.get("availability", {})
        params.append(
            (
                row["ts_utc"],
                generated_at_utc,
                *(combined.get(column) for column in COMBINED_COLUMNS),
                int(bool(availability.get("metno"))),
                int(bool(availability.get("open_meteo"))),
            )
        )

    if not params:
        return 0

    columns = ", ".join(
        (
            "valid_at_utc",
            "generated_at_utc",
            *COMBINED_COLUMNS,
            "metno_available",
            "open_meteo_available",
        )
    )
    placeholders = ", ".join("?" for _ in range(2 + len(COMBINED_COLUMNS) + 2))

    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            f"INSERT OR IGNORE INTO combined_points ({columns}) VALUES ({placeholders})",
            params,
        )
        return connection.total_changes - before


def load_latest_combined() -> list[dict[str, Any]]:
    """Последний сохранённый объединённый прогноз."""
    with connect() as connection:
        row = connection.execute(
            "SELECT MAX(generated_at_utc) AS generated_at FROM combined_points"
        ).fetchone()
        generated_at = row["generated_at"] if row is not None else None
        if generated_at is None:
            return []

        rows = connection.execute(
            """
            SELECT * FROM combined_points
            WHERE generated_at_utc = ?
            ORDER BY valid_at_utc
            """,
            (generated_at,),
        ).fetchall()

    points = []
    for row in rows:
        point = dict(row)
        point.pop("id", None)
        point["ts_utc"] = point.pop("valid_at_utc")
        point["metno_available"] = bool(point["metno_available"])
        point["open_meteo_available"] = bool(point["open_meteo_available"])
        if point["weather_code_agreement"] is not None:
            point["weather_code_agreement"] = bool(point["weather_code_agreement"])
        points.append(point)
    return points
