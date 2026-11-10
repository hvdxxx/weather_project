import requests
import pytest

import weather_api_config as config
import weather_http
from weather_http import TransientWeatherAPIError, WeatherAPIError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, json_error=False):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.payload


@pytest.fixture(autouse=True)
def reset_http_state(monkeypatch):
    weather_http.clear_cache()
    delays: list[float] = []
    monkeypatch.setattr(weather_http, "_sleep", delays.append)
    yield delays
    weather_http.clear_cache()


def install_responses(monkeypatch, responses):
    calls = {"count": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        index = min(calls["count"], len(responses) - 1)
        calls["count"] += 1
        item = responses[index]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(weather_http._session, "get", fake_get)
    return calls


def fetch_json(**kwargs):
    return weather_http.http_get_json(
        "https://example.test/api",
        provider="test",
        ttl_sec=60,
        **kwargs,
    )


def test_successful_response_is_returned(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(payload={"ok": True})])

    assert fetch_json() == {"ok": True}
    assert calls["count"] == 1


def test_successful_response_is_cached(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(payload={"ok": True})])

    first = fetch_json()
    second = fetch_json()

    assert first == second == {"ok": True}
    assert calls["count"] == 1


def test_zero_ttl_disables_cache(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(payload={"ok": True})])

    weather_http.http_get_json("https://example.test/api", provider="test", ttl_sec=0)
    weather_http.http_get_json("https://example.test/api", provider="test", ttl_sec=0)

    assert calls["count"] == 2


def test_invalidate_cache_forces_refetch(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(payload={"ok": True})])

    assert fetch_json() == {"ok": True}
    assert fetch_json() == {"ok": True}
    assert calls["count"] == 1

    weather_http.invalidate_cache("https://example.test/api", None)

    assert fetch_json() == {"ok": True}
    assert calls["count"] == 2


def test_server_error_is_retried(monkeypatch):
    calls = install_responses(
        monkeypatch,
        [FakeResponse(status_code=503), FakeResponse(payload={"ok": True})],
    )

    assert fetch_json() == {"ok": True}
    assert calls["count"] == 2


def test_retry_after_is_respected(monkeypatch, reset_http_state):
    delays = reset_http_state
    calls = install_responses(
        monkeypatch,
        [
            FakeResponse(status_code=429, headers={"Retry-After": "2"}),
            FakeResponse(payload={"ok": True}),
        ],
    )

    assert fetch_json() == {"ok": True}
    assert calls["count"] == 2
    assert max(delays) >= 2.0


def test_client_error_is_not_retried(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(status_code=404)])

    with pytest.raises(WeatherAPIError):
        fetch_json()
    assert calls["count"] == 1


def test_timeout_is_retried_then_raised(monkeypatch):
    monkeypatch.setattr(config, "HTTP_MAX_ATTEMPTS", 2)
    calls = install_responses(
        monkeypatch,
        [requests.Timeout("slow"), requests.Timeout("slow")],
    )

    with pytest.raises(TransientWeatherAPIError):
        fetch_json()
    assert calls["count"] == 2


def test_connection_error_is_treated_as_transient(monkeypatch):
    monkeypatch.setattr(config, "HTTP_MAX_ATTEMPTS", 2)
    calls = install_responses(
        monkeypatch,
        [requests.ConnectionError("down"), FakeResponse(payload={"ok": True})],
    )

    assert fetch_json() == {"ok": True}
    assert calls["count"] == 2


def test_invalid_json_raises_without_retry(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(json_error=True)])

    with pytest.raises(WeatherAPIError):
        fetch_json()
    assert calls["count"] == 1


def test_non_object_json_is_rejected(monkeypatch):
    calls = install_responses(monkeypatch, [FakeResponse(payload=[1, 2, 3])])

    with pytest.raises(WeatherAPIError):
        fetch_json()
    assert calls["count"] == 1


def test_non_transient_request_error_is_not_retried(monkeypatch):
    calls = install_responses(monkeypatch, [requests.RequestException("bad url")])

    with pytest.raises(WeatherAPIError):
        fetch_json()
    assert calls["count"] == 1


def test_request_uses_configured_timeout(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse(payload={"ok": True})

    monkeypatch.setattr(weather_http._session, "get", fake_get)

    fetch_json()

    assert captured["timeout"] == (config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT)

