import sqlite3

import pytest

import weather_db
import weather_storage

CSV_TEXT = (
    "timestamp,city,temp,humidity,wind\n"
    "2026-10-16T10:40:28,Yakutsk,-3.6,85.0,4.3\n"
    "2026-10-16T10:45:54,Yakutsk,-3.7,84.0,4.1\n"
)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    csv_path = tmp_path / "weather_history.csv"
    monkeypatch.setattr(weather_storage, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(weather_db.config, "DB_PATH", tmp_path / "weather.db")
    weather_db.init_db()
    return csv_path


def test_csv_is_migrated_once_and_kept_intact(storage):
    storage.write_text(CSV_TEXT, encoding="utf-8")

    assert weather_storage.migrate_csv_to_db() == 2

    rows = weather_db.load_observations()
    assert len(rows) == 2
    # Наивное локальное время Якутска (UTC+9) переведено в UTC.
    assert rows[0]["observed_at_utc"] == "2026-10-16T01:40:28+00:00"
    assert rows[0]["source"] == "csv"
    assert rows[0]["provider"] == "metno"

    assert weather_db.get_meta("csv_migrated") == "1"
    assert weather_storage.migrate_csv_to_db() == 0
    assert len(weather_db.load_observations()) == 2
    assert storage.read_text(encoding="utf-8") == CSV_TEXT


def test_invalid_csv_timestamp_is_skipped(storage):
    storage.write_text(
        "timestamp,city,temp,humidity,wind\n"
        "not-a-date,Yakutsk,-3.6,85.0,4.3\n"
        "2026-10-16T10:45:54,Yakutsk,-3.7,84.0,4.1\n",
        encoding="utf-8",
    )

    assert weather_storage.migrate_csv_to_db() == 1
    assert len(weather_db.load_observations()) == 1

    with weather_db.connect() as connection:
        row = connection.execute(
            "SELECT details FROM update_log WHERE event = 'csv_migration'"
        ).fetchone()
    assert '"skipped": 1' in row["details"]


def test_init_storage_initializes_and_migrates(storage):
    storage.write_text(CSV_TEXT, encoding="utf-8")

    assert weather_storage.init_storage() == 2
    assert weather_db.get_meta("csv_migrated") == "1"
    assert len(weather_db.load_observations()) == 2


def test_save_weather_writes_csv_and_sqlite(storage):
    weather_storage.save_weather("Yakutsk", {"temp": -5.0, "humidity": 80.0, "wind": 2.0})

    rows = weather_db.load_observations()
    assert len(rows) == 1
    assert rows[0]["temperature"] == pytest.approx(-5.0)
    assert rows[0]["source"] == "live"

    csv_text = storage.read_text(encoding="utf-8")
    assert csv_text.startswith("timestamp,city,temp,humidity,wind")
    assert "Yakutsk,-5.0,80.0,2.0" in csv_text


def test_save_weather_survives_sqlite_failure(storage, monkeypatch):
    def fail(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(weather_db, "insert_observation", fail)

    weather_storage.save_weather("Yakutsk", {"temp": -5.0, "humidity": 80.0, "wind": 2.0})

    assert "Yakutsk,-5.0,80.0,2.0" in storage.read_text(encoding="utf-8")
    assert weather_db.load_observations() == []
