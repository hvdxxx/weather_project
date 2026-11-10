import pytest

import open_meteo_api
import weather_api_config as config
import weather_http
from weather_http import WeatherAPIError


def make_payload() -> dict:
    return {
        "latitude": 62.0,
        "longitude": 129.75,
        "utc_offset_seconds": 32400,
        "timezone": "Asia/Yakutsk",
        "hourly": {
            "time": ["2026-11-10T00:00", "2026-11-10T01:00"],
            "temperature_2m": [-15.9, -15.6],
            "relative_humidity_2m": [86, 86],
            "apparent_temperature": [-20.3, -20.0],
            "precipitation_probability": [10, 11],
            "precipitation": [0.0, 0.1],
            "rain": [0.0, 0.0],
            "snowfall": [0.0, 0.07],
            "weather_code": [3, 71],
            "cloud_cover": [100, 100],
            "wind_speed_10m": [1.22, 1.39],
            "wind_direction_10m": [19, 26],
            "wind_gusts_10m": [2.2, 2.7],
        },
    }


def test_normalize_maps_fields_and_converts_to_utc():
    points = open_meteo_api.normalize_open_meteo(make_payload())

    assert len(points) == 2
    first, second = points
    assert first["ts_utc"] == "2026-11-09T15:00:00+00:00"
    assert second["ts_utc"] == "2026-11-09T16:00:00+00:00"
    assert first["provider"] == "open_meteo"
    assert first["temperature"] == pytest.approx(-15.9)
    assert first["humidity"] == pytest.approx(86.0)
    assert first["wind_speed"] == pytest.approx(1.22)
    assert first["wind_direction"] == pytest.approx(19.0)
    assert first["weather_code"] == pytest.approx(3.0)

    expected = {"ts_utc", "provider", "weather_symbol"} | set(
        open_meteo_api.FIELD_MAP.values()
    )
    assert set(first) == expected
    assert first["weather_symbol"] is None


def test_normalize_keeps_missing_values_as_none():
    payload = make_payload()
    payload["hourly"]["snowfall"] = [None, 0.07]
    payload["hourly"]["precipitation"] = [0.0, None]
    payload["hourly"]["temperature_2m"] = [None, "n/a"]

    points = open_meteo_api.normalize_open_meteo(payload)

    assert points[0]["snowfall"] is None
    assert points[0]["precipitation"] == 0.0
    assert points[1]["precipitation"] is None
    assert points[0]["temperature"] is None
    assert points[1]["temperature"] is None


def test_normalize_allows_missing_optional_column():
    payload = make_payload()
    del payload["hourly"]["wind_gusts_10m"]

    points = open_meteo_api.normalize_open_meteo(payload)

    assert len(points) == 2
    assert all(point["wind_gusts"] is None for point in points)


def test_normalize_respects_timestamps_with_explicit_offset():
    payload = make_payload()
    payload["hourly"]["time"] = [
        "2026-11-10T00:00:00+03:00",
        "2026-11-10T01:00:00+03:00",
    ]

    points = open_meteo_api.normalize_open_meteo(payload)

    assert points[0]["ts_utc"] == "2026-11-09T21:00:00+00:00"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.pop("hourly"),
        lambda payload: payload["hourly"].update(time=[]),
        lambda payload: payload["hourly"].update(time=["not-a-date"]),
        lambda payload: payload["hourly"].update(temperature_2m=[1.0]),
        lambda payload: payload.pop("utc_offset_seconds"),
    ],
)
def test_normalize_rejects_invalid_payload(mutator):
    payload = make_payload()
    mutator(payload)

    with pytest.raises(WeatherAPIError):
        open_meteo_api.normalize_open_meteo(payload)


def test_build_params_uses_central_config():
    params = open_meteo_api.build_params()

    assert params["latitude"] == config.LATI
    assert params["longitude"] == config.LONG
    assert params["timezone"] == "auto"
    assert params["forecast_days"] == 7
    assert params["temperature_unit"] == "celsius"
    assert params["wind_speed_unit"] == "ms"
    assert params["precipitation_unit"] == "mm"
    assert set(params["hourly"].split(",")) == set(config.OPEN_METEO_HOURLY_PARAMS)


def test_field_map_covers_every_requested_parameter():
    assert set(open_meteo_api.FIELD_MAP) == set(config.OPEN_METEO_HOURLY_PARAMS)


def test_fetch_open_meteo_forecast_passes_config_to_http_layer(monkeypatch):
    captured = {}

    def fake_get_json(url, *, params, provider, ttl_sec, headers):
        captured.update(url=url, params=params, provider=provider, ttl_sec=ttl_sec, headers=headers)
        return make_payload()

    monkeypatch.setattr(open_meteo_api, "http_get_json", fake_get_json)

    points = open_meteo_api.fetch_open_meteo_forecast()

    assert len(points) == 2
    assert captured["url"] == config.OPEN_METEO_URL
    assert captured["provider"] == "open_meteo"
    assert captured["ttl_sec"] == config.OPEN_METEO_CACHE_TTL_SEC
    assert captured["headers"] == {"User-Agent": config.USER_AGENT}
    assert captured["params"] == open_meteo_api.build_params()


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = {}
        self.payload = payload

    def json(self):
        return self.payload


def test_fetch_open_meteo_forecast_through_http_layer(monkeypatch):
    weather_http.clear_cache()
    monkeypatch.setattr(
        weather_http._session,
        "get",
        lambda *args, **kwargs: FakeResponse(make_payload()),
    )

    try:
        points = open_meteo_api.fetch_open_meteo_forecast()
    finally:
        weather_http.clear_cache()

    assert len(points) == 2
    assert points[0]["provider"] == "open_meteo"
    assert points[0]["temperature"] == pytest.approx(-15.9)


def test_fetch_open_meteo_forecast_rejects_broken_payload(monkeypatch):
    weather_http.clear_cache()
    monkeypatch.setattr(
        weather_http._session,
        "get",
        lambda *args, **kwargs: FakeResponse({"hourly": {}}),
    )

    try:
        with pytest.raises(WeatherAPIError):
            open_meteo_api.fetch_open_meteo_forecast()
    finally:
        weather_http.clear_cache()
