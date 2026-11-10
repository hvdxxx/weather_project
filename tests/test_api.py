from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import weather_db
import weather_service
from forecast_merge import build_combined_forecast
from weather_common import NUMERIC_FIELDS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(weather_db.config, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(api, "init_storage", lambda: 0)
    weather_db.init_db()
    with TestClient(api.app) as test_client:
        yield test_client


def future_ts(hours=1):
    moment = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (moment + timedelta(hours=hours)).isoformat(timespec="seconds")


def make_point(ts_utc, provider, **overrides):
    point = {"ts_utc": ts_utc, "provider": provider}
    point.update({field: None for field in NUMERIC_FIELDS})
    point.update({"weather_code": None, "weather_symbol": None})
    point.update(overrides)
    return point


def seed_observation(ts_utc=None):
    ts_utc = ts_utc or datetime.now(timezone.utc).isoformat(timespec="seconds")
    weather_db.insert_observation(
        observed_at_utc=ts_utc,
        city="Yakutsk",
        temperature=-14.0,
        humidity=89.5,
        wind_speed=1.1,
        provider="metno",
        source="live",
        fetched_at_utc=ts_utc,
    )


def seed_forecasts():
    ts = future_ts()
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metno = [
        make_point(
            ts,
            "metno",
            temperature=0.0,
            humidity=80.0,
            wind_speed=2.0,
            wind_direction=350.0,
            precipitation=0.1,
            weather_code=3,
        )
    ]
    open_meteo = [
        make_point(
            ts,
            "open_meteo",
            temperature=2.0,
            humidity=90.0,
            wind_speed=4.0,
            wind_direction=10.0,
            precipitation=0.5,
            precipitation_probability=40.0,
            weather_code=3,
        )
    ]
    weather_db.insert_forecast_points("metno", fetched_at, metno)
    weather_db.insert_forecast_points("open_meteo", fetched_at, open_meteo)
    return ts, fetched_at, build_combined_forecast(metno, open_meteo)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_current_weather_404_then_200(client):
    assert client.get("/weather/current").status_code == 404

    seed_observation()
    response = client.get("/weather/current")

    assert response.status_code == 200
    body = response.json()
    assert body["temperature"] == pytest.approx(-14.0)
    assert body["provider"] == "metno"


def test_forecast_requires_data(client):
    assert client.get("/weather/forecast").status_code == 503

    seed_forecasts()
    response = client.get("/weather/forecast")

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["combined"]["temperature"] == pytest.approx(1.0)
    assert body["rows"][0]["availability"] == {"metno": True, "open_meteo": True}


def test_forecast_sources_and_partial_availability(client):
    ts = future_ts()
    weather_db.insert_forecast_points(
        "open_meteo",
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        [make_point(ts, "open_meteo", temperature=-10.0)],
    )

    response = client.get("/weather/forecast/sources")

    assert response.status_code == 200
    sources = response.json()["sources"]
    assert sources["metno"]["status"] == "unavailable"
    assert sources["open_meteo"]["status"] == "ok"
    assert sources["open_meteo"]["count"] == 1


def test_combined_forecast(client):
    _, generated_at, rows = seed_forecasts()
    weather_db.insert_combined_points(generated_at, rows)

    response = client.get("/weather/forecast/combined")

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["temperature"] == pytest.approx(1.0)
    assert rows[0]["derived"] is True


def test_differences_endpoint(client):
    seed_forecasts()

    response = client.get("/weather/forecast/differences")

    assert response.status_code == 200
    body = response.json()
    assert body["intervals"] == 1
    temperature = body["rows"][0]["differences"]["temperature"]
    assert temperature["delta"] == pytest.approx(2.0)
    assert temperature["level"] == "moderate"


def test_history_limit_and_validation(client):
    seed_observation("2026-11-10T11:00:00+00:00")
    seed_observation("2026-11-10T12:00:00+00:00")

    response = client.get("/weather/history", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["observations"][0]["observed_at_utc"] == "2026-11-10T12:00:00+00:00"

    assert client.get("/weather/history", params={"limit": 0}).status_code == 422


def test_statistics_endpoint(client):
    seed_observation("2026-11-10T11:00:00+00:00")
    seed_forecasts()

    response = client.get("/weather/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["observations"]["count"] == 1
    assert body["forecast"]["matched"] == 1
    assert body["forecast"]["temperature"]["mean_abs_delta"] == pytest.approx(2.0)


def test_missing_statistics_are_still_200(client):
    response = client.get("/weather/statistics")

    assert response.status_code == 200
    assert response.json()["observations"] is None


def test_forecast_dependent_endpoints_require_data(client):
    assert client.get("/weather/forecast/sources").status_code == 503
    assert client.get("/weather/forecast/combined").status_code == 503
    assert client.get("/weather/forecast/differences").status_code == 503


def test_current_weather_rejects_stale_observation(client):
    stale = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(timespec="seconds")
    seed_observation(stale)

    response = client.get("/weather/current")

    assert response.status_code == 404


def test_history_since_filter(client):
    seed_observation("2026-11-10T10:00:00+00:00")
    seed_observation("2026-11-10T12:00:00+00:00")

    response = client.get(
        "/weather/history",
        params={"since": "2026-11-10T11:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["observations"][0]["observed_at_utc"] == "2026-11-10T12:00:00+00:00"
