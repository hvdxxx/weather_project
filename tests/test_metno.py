import pytest

import weather_api
import weather_api_config as config
import weather_http
from weather_common import POINT_FIELDS
from weather_http import WeatherAPIError


def make_payload() -> dict:
    instant = {
        "air_temperature": -14.0,
        "relative_humidity": 89.5,
        "wind_speed": 1.1,
        "wind_from_direction": 350.0,
        "cloud_area_fraction": 100.0,
    }
    return {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-11-10T11:00:00Z",
                    "data": {
                        "instant": {"details": dict(instant)},
                        "next_1_hours": {
                            "summary": {"symbol_code": "cloudy"},
                            "details": {"precipitation_amount": 0.2},
                        },
                    },
                },
                {
                    "time": "2026-11-10T17:00:00Z",
                    "data": {
                        "instant": {"details": dict(instant, air_temperature=-16.0)},
                        "next_6_hours": {
                            "summary": {"symbol_code": "partlycloudy_night"},
                            "details": {"precipitation_amount": 1.2},
                        },
                    },
                },
            ]
        }
    }


def test_normalize_maps_fields_and_converts_to_utc():
    points = weather_api.normalize_metno(make_payload())

    assert len(points) == 2
    first, second = points

    assert first["ts_utc"] == "2026-11-10T11:00:00+00:00"
    assert first["provider"] == "metno"
    assert first["temperature"] == pytest.approx(-14.0)
    assert first["humidity"] == pytest.approx(89.5)
    assert first["wind_speed"] == pytest.approx(1.1)
    assert first["wind_direction"] == pytest.approx(350.0)
    assert first["cloud_cover"] == pytest.approx(100.0)
    assert first["precipitation"] == pytest.approx(0.2)
    assert first["precipitation_probability"] is None
    assert first["apparent_temperature"] is None
    assert first["wind_gusts"] is None
    assert first["snowfall"] is None
    assert first["rain"] is None
    assert first["weather_code"] == 3
    assert first["weather_symbol"] == "cloudy"
    assert set(first) == set(POINT_FIELDS)

    # 6-часовую сумму осадков нельзя сравнивать с почасовой.
    assert second["precipitation"] is None
    assert second["weather_code"] == 2
    assert second["weather_symbol"] == "partlycloudy_night"


def test_normalize_keeps_missing_parameters_as_none():
    payload = make_payload()
    details = payload["properties"]["timeseries"][0]["data"]["instant"]["details"]
    del details["air_temperature"]
    del details["relative_humidity"]

    points = weather_api.normalize_metno(payload)

    assert points[0]["temperature"] is None
    assert points[0]["humidity"] is None
    assert points[0]["wind_speed"] == pytest.approx(1.1)


def test_normalize_accepts_point_without_forecast_period():
    payload = make_payload()
    data = payload["properties"]["timeseries"][0]["data"]
    del data["next_1_hours"]

    points = weather_api.normalize_metno(payload)

    assert points[0]["weather_code"] is None
    assert points[0]["weather_symbol"] is None
    assert points[0]["precipitation"] is None


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.clear(),
        lambda payload: payload["properties"].pop("timeseries"),
        lambda payload: payload["properties"].update(timeseries=[]),
        lambda payload: payload["properties"]["timeseries"][0].update(time="not-a-date"),
        lambda payload: payload["properties"]["timeseries"][0].update(
            time="2026-11-10T11:00:00"
        ),
        lambda payload: payload["properties"]["timeseries"][0].pop("data"),
        lambda payload: payload["properties"]["timeseries"][0]["data"].pop("instant"),
    ],
)
def test_normalize_rejects_invalid_payload(mutator):
    payload = make_payload()
    mutator(payload)

    with pytest.raises(WeatherAPIError):
        weather_api.normalize_metno(payload)


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("clearsky_day", 0),
        ("fair_night", 1),
        ("partlycloudy_night", 2),
        ("cloudy", 3),
        ("fog", 45),
        ("heavyrain", 65),
        ("lightrainshowers_day", 80),
        ("heavysnowshowers_night", 86),
        ("rainandthunder", 95),
        ("unknown_symbol", None),
        (None, None),
        ("", None),
    ],
)
def test_symbol_to_wmo(symbol, expected):
    assert weather_api.symbol_to_wmo(symbol) == expected


def test_fetch_metno_forecast_passes_config_to_http_layer(monkeypatch):
    captured = {}

    def fake_get_json(url, *, params, provider, ttl_sec, headers):
        captured.update(url=url, params=params, provider=provider, ttl_sec=ttl_sec, headers=headers)
        return make_payload()

    monkeypatch.setattr(weather_api, "http_get_json", fake_get_json)

    points = weather_api.fetch_metno_forecast()

    assert len(points) == 2
    assert captured == {
        "url": config.URL,
        "params": {"lat": config.LATI, "lon": config.LONG},
        "provider": "metno",
        "ttl_sec": config.MET_CACHE_TTL_SEC,
        "headers": {"User-Agent": config.USER_AGENT},
    }


def test_take_weather_returns_first_point(monkeypatch):
    point = weather_api.normalize_metno(make_payload())[0]
    monkeypatch.setattr(weather_api, "fetch_metno_forecast", lambda: [point])

    assert weather_api.take_weather() == {
        "temp": -14.0,
        "humidity": 89.5,
        "wind": 1.1,
    }


def test_take_weather_returns_none_on_api_error(monkeypatch):
    def raise_error():
        raise WeatherAPIError("unavailable")

    monkeypatch.setattr(weather_api, "fetch_metno_forecast", raise_error)

    assert weather_api.take_weather() is None


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = {}
        self.payload = payload

    def json(self):
        return self.payload


def test_fetch_metno_forecast_through_http_layer(monkeypatch):
    weather_http.clear_cache()
    monkeypatch.setattr(
        weather_http._session,
        "get",
        lambda *args, **kwargs: FakeResponse(make_payload()),
    )

    try:
        points = weather_api.fetch_metno_forecast()
    finally:
        weather_http.clear_cache()

    assert len(points) == 2
    assert points[0]["provider"] == "metno"
    assert points[0]["temperature"] == pytest.approx(-14.0)


def test_fetch_metno_forecast_rejects_empty_timeseries(monkeypatch):
    weather_http.clear_cache()
    monkeypatch.setattr(
        weather_http._session,
        "get",
        lambda *args, **kwargs: FakeResponse({"properties": {"timeseries": []}}),
    )

    try:
        with pytest.raises(WeatherAPIError):
            weather_api.fetch_metno_forecast()
    finally:
        weather_http.clear_cache()
