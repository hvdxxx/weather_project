import pytest

import weather_db
from weather_common import NUMERIC_FIELDS

TS1 = "2026-11-10T11:00:00+00:00"
TS2 = "2026-11-10T12:00:00+00:00"
GENERATED = "2026-11-10T11:05:00+00:00"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "weather.db"
    monkeypatch.setattr(weather_db.config, "DB_PATH", path)
    weather_db.init_db()
    return path


def make_point(ts_utc, provider, **overrides):
    point = {"ts_utc": ts_utc, "provider": provider}
    point.update({field: None for field in NUMERIC_FIELDS})
    point.update({"weather_code": None, "weather_symbol": None})
    point.update(overrides)
    return point


def make_combined_row(ts_utc, **overrides):
    combined = {field: None for field in NUMERIC_FIELDS}
    combined.update({"weather_code": None, "weather_code_agreement": None, "derived": True})
    combined.update(overrides)
    return {
        "ts_utc": ts_utc,
        "combined": combined,
        "availability": {"metno": True, "open_meteo": True},
    }


def test_schema_is_created_and_init_is_idempotent(isolated_db):
    with weather_db.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "observations",
        "forecast_points",
        "combined_points",
        "update_log",
        "meta",
    } <= tables
    assert weather_db.get_meta("schema_version") == weather_db.SCHEMA_VERSION

    weather_db.init_db()
    assert weather_db.get_meta("schema_version") == weather_db.SCHEMA_VERSION


def test_observation_is_saved_and_deduplicated(isolated_db):
    observation = {
        "observed_at_utc": TS1,
        "city": "Yakutsk",
        "temperature": -14.0,
        "humidity": 89.5,
        "wind_speed": 1.1,
        "provider": "metno",
        "source": "live",
        "fetched_at_utc": TS1,
    }

    assert weather_db.insert_observation(**observation) is True
    assert weather_db.insert_observation(**observation) is False

    rows = weather_db.load_observations()
    assert len(rows) == 1
    assert rows[0]["observed_at_utc"] == TS1
    assert rows[0]["city"] == "Yakutsk"
    assert rows[0]["temperature"] == pytest.approx(-14.0)
    assert rows[0]["humidity"] == pytest.approx(89.5)
    assert rows[0]["wind_speed"] == pytest.approx(1.1)
    assert rows[0]["provider"] == "metno"


def test_bulk_observations_count_only_new_rows(isolated_db):
    base = {
        "city": "Yakutsk",
        "temperature": -14.0,
        "humidity": 89.5,
        "wind_speed": 1.1,
        "provider": "metno",
        "source": "csv",
    }
    rows = [
        dict(base, observed_at_utc=TS1, fetched_at_utc=TS2),
        dict(base, observed_at_utc=TS2, fetched_at_utc=TS2),
        dict(base, observed_at_utc=TS1, fetched_at_utc=TS2),
    ]

    assert weather_db.insert_observations(rows) == 2
    assert [row["observed_at_utc"] for row in weather_db.load_observations()] == [
        TS1,
        TS2,
    ]
    assert weather_db.load_observations(limit=1)[0]["observed_at_utc"] == TS2


def test_forecast_snapshot_is_saved_and_latest_is_returned(isolated_db):
    first = [
        make_point(TS1, "metno", temperature=-14.0, weather_code=3.0, weather_symbol="cloudy"),
        make_point(TS2, "metno", temperature=-13.5, weather_code=3.0),
    ]
    assert weather_db.insert_forecast_points("metno", "2026-11-10T11:05:00+00:00", first) == 2
    assert weather_db.insert_forecast_points("metno", "2026-11-10T11:05:00+00:00", first) == 0

    newer = [make_point(TS1, "metno", temperature=-15.0)]
    assert weather_db.insert_forecast_points("metno", "2026-11-10T12:05:00+00:00", newer) == 1

    latest = weather_db.load_latest_forecast("metno")
    assert len(latest) == 1
    assert latest[0]["ts_utc"] == TS1
    assert latest[0]["temperature"] == pytest.approx(-15.0)
    assert "valid_at_utc" not in latest[0]
    assert weather_db.load_latest_forecast("open_meteo") == []


def test_combined_forecast_is_saved(isolated_db):
    rows = [
        make_combined_row(TS1, temperature=-13.85, weather_code=3, weather_code_agreement=True),
        {"ts_utc": TS2, "combined": None, "availability": {"metno": True, "open_meteo": False}},
    ]

    assert weather_db.insert_combined_points(GENERATED, rows) == 1

    latest = weather_db.load_latest_combined()
    assert len(latest) == 1
    assert latest[0]["ts_utc"] == TS1
    assert latest[0]["temperature"] == pytest.approx(-13.85)
    assert latest[0]["weather_code_agreement"] is True
    assert latest[0]["metno_available"] is True


def test_meta_and_update_log(isolated_db):
    assert weather_db.get_meta("missing", "fallback") == "fallback"

    weather_db.set_meta("csv_migrated", "1")
    assert weather_db.get_meta("csv_migrated") == "1"

    weather_db.log_update("test_event", {"records": 3})
    with weather_db.connect() as connection:
        row = connection.execute(
            "SELECT level, event, details FROM update_log WHERE event = 'test_event'"
        ).fetchone()

    assert row["level"] == "info"
    assert row["details"] == '{"records": 3}'
