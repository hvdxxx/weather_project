from datetime import datetime, timedelta, timezone

import pytest

import weather_db
import weather_service
from weather_common import NUMERIC_FIELDS
from weather_http import WeatherAPIError


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(weather_db.config, "DB_PATH", tmp_path / "service.db")
    weather_db.init_db()
    return tmp_path


def future_ts(hours=1):
    moment = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (moment + timedelta(hours=hours)).isoformat(timespec="seconds")


def make_point(ts_utc, provider, **overrides):
    point = {"ts_utc": ts_utc, "provider": provider}
    point.update({field: None for field in NUMERIC_FIELDS})
    point.update({"weather_code": None, "weather_symbol": None})
    point.update(overrides)
    return point


def test_collect_once_continues_when_one_source_fails(isolated_db, monkeypatch):
    def fail():
        raise WeatherAPIError("metno down")

    monkeypatch.setattr(weather_service, "fetch_metno_forecast", fail)
    monkeypatch.setattr(
        weather_service,
        "fetch_open_meteo_forecast",
        lambda: [make_point(future_ts(), "open_meteo", temperature=-10.0)],
    )

    result = weather_service.collect_once()

    assert result["sources"]["metno"]["status"] == "error"
    assert result["sources"]["open_meteo"]["status"] == "ok"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["combined"] is None
    assert weather_db.load_latest_forecast("metno") == []
    assert len(weather_db.load_latest_forecast("open_meteo")) == 1


def test_collect_once_handles_both_sources_down(isolated_db, monkeypatch):
    def fail():
        raise WeatherAPIError("down")

    monkeypatch.setattr(weather_service, "fetch_metno_forecast", fail)
    monkeypatch.setattr(weather_service, "fetch_open_meteo_forecast", fail)

    result = weather_service.collect_once()

    assert result["rows"] == []
    assert result["combined_saved"] == 0
    assert result["sources"]["metno"]["status"] == "error"
    assert result["sources"]["open_meteo"]["status"] == "error"


def test_collect_once_and_read_combined(isolated_db, monkeypatch):
    ts = future_ts()
    monkeypatch.setattr(
        weather_service,
        "fetch_metno_forecast",
        lambda: [
            make_point(
                ts,
                "metno",
                temperature=0.0,
                humidity=80.0,
                weather_code=3,
            )
        ],
    )
    monkeypatch.setattr(
        weather_service,
        "fetch_open_meteo_forecast",
        lambda: [
            make_point(
                ts,
                "open_meteo",
                temperature=2.0,
                humidity=90.0,
                weather_code=3,
            )
        ],
    )

    result = weather_service.collect_once()

    assert result["sources"]["metno"]["status"] == "ok"
    assert result["sources"]["open_meteo"]["status"] == "ok"
    rows = weather_service.get_forecast_rows()
    assert len(rows) == 1
    assert rows[0]["combined"]["temperature"] == pytest.approx(1.0)
    assert rows[0]["differences"]["temperature"]["delta"] == pytest.approx(2.0)

    sources = weather_service.get_sources()
    assert sources["sources"]["metno"]["count"] == 1
    assert sources["sources"]["open_meteo"]["count"] == 1

    combined = weather_service.get_combined_rows()
    assert len(combined) == 1
    assert combined[0]["temperature"] == pytest.approx(1.0)


def test_get_statistics_without_forecasts(isolated_db):
    stats = weather_service.get_statistics()

    assert stats["city"]
    assert stats["observations"] is None
    assert stats["forecast"]["matched"] == 0
