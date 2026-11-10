"""Хранение наблюдений: CSV (исторические данные) + SQLite (основное хранилище).

CSV не удаляется и не перезаписывается: старые записи один раз переносятся
в SQLite с идемпотентным флагом миграции. Новые наблюдения пишутся в оба места.
"""
from __future__ import annotations

import csv
import logging
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import weather_api_config as config
import weather_db
from weather_common import METNO

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "weather_history.csv")
HEADERS = ["timestamp", "city", "temp", "humidity", "wind"]


def save_weather(city, weather):
    """Добавляет одну запись о погоде в CSV и SQLite."""
    if weather is None:
        return

    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(HEADERS)

        writer.writerow(
            [
                datetime.now().isoformat(timespec="seconds"),
                city,
                weather["temp"],
                weather["humidity"],
                weather["wind"],
            ]
        )

    _save_observation_to_db(city, weather)


def load_weather():
    """Читает CSV и возвращает список словарей с числами (не строками)."""
    if not os.path.isfile(CSV_FILE):
        return []

    records = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                records.append(
                    {
                        "timestamp": row["timestamp"],
                        "city": row["city"],
                        "temp": float(row["temp"]),
                        "humidity": float(row["humidity"]),
                        "wind": float(row["wind"]),
                    }
                )
            except (KeyError, ValueError):
                # пропускаем битые строки, чтобы не падать на всём файле
                continue

    return records


def _local_to_utc(timestamp: str) -> str:
    """Наивное локальное время CSV трактуется в часовом поясе из конфига."""
    try:
        local_tz = ZoneInfo(config.TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"не найдена таймзона {config.TIMEZONE!r}; установите пакет tzdata"
        ) from exc

    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _save_observation_to_db(city, weather) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        weather_db.init_db()
        weather_db.insert_observation(
            observed_at_utc=now,
            city=city,
            temperature=weather["temp"],
            humidity=weather["humidity"],
            wind_speed=weather["wind"],
            provider=METNO,
            source="live",
            fetched_at_utc=now,
        )
    except (sqlite3.Error, OSError) as exc:
        # CSV уже сохранён, поэтому сбор данных не прерываем, но ошибку не скрываем.
        logger.exception("Не удалось сохранить наблюдение в SQLite: %s", exc)


def migrate_csv_to_db() -> int:
    """Переносит старый CSV в SQLite; повторный запуск ничего не дублирует."""
    if not os.path.isfile(CSV_FILE):
        return 0
    if weather_db.get_meta("csv_migrated") == "1":
        return 0

    records = load_weather()
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    skipped = 0
    for record in records:
        try:
            observed_at = _local_to_utc(record["timestamp"])
        except ValueError:
            skipped += 1
            logger.warning(
                "CSV: пропущена строка с некорректным временем %r",
                record["timestamp"],
            )
            continue

        rows.append(
            {
                "observed_at_utc": observed_at,
                "city": record["city"],
                "temperature": record["temp"],
                "humidity": record["humidity"],
                "wind_speed": record["wind"],
                "provider": METNO,
                "source": "csv",
                "fetched_at_utc": fetched_at,
            }
        )

    inserted = weather_db.insert_observations(rows)
    weather_db.set_meta("csv_migrated", "1")
    weather_db.set_meta("csv_migrated_at", fetched_at)
    weather_db.log_update(
        "csv_migration",
        {"records": len(records), "inserted": inserted, "skipped": skipped},
    )
    logger.info(
        "Миграция CSV -> SQLite: записей %d, вставлено %d, пропущено %d",
        len(records),
        inserted,
        skipped,
    )
    return inserted


def init_storage() -> int:
    """Инициализирует SQLite и при необходимости переносит CSV."""
    weather_db.init_db()
    return migrate_csv_to_db()
