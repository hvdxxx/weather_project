"""Общий HTTP-слой внешних погодных API.

Отвечает за timeout, повторные попытки только для временных ошибок,
ограничение частоты запросов и TTL-кэш успешных ответов в памяти.
"""
from __future__ import annotations

import copy
import logging
import random
import threading
import time
from typing import Any

import requests

import weather_api_config as config

logger = logging.getLogger(__name__)


class WeatherAPIError(Exception):
    """Погодный API недоступен или вернул некорректный ответ."""


class TransientWeatherAPIError(WeatherAPIError):
    """Временная ошибка, повторы которой исчерпаны."""


_session = requests.Session()
# Отдельная ссылка, чтобы тесты могли подменить ожидание без патча модуля time.
_sleep = time.sleep
_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_request_at: dict[str, float] = {}


def clear_cache() -> None:
    """Сбрасывает кэш и состояние rate limit (используется в тестах)."""
    with _cache_lock:
        _cache.clear()
    with _rate_lock:
        _last_request_at.clear()


def _cache_key(url: str, params: dict[str, Any] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
    return url, normalized


def _get_cached(key: tuple[str, tuple[tuple[str, str], ...]]) -> dict[str, Any] | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at <= time.monotonic():
            del _cache[key]
            return None
        return copy.deepcopy(payload)


def invalidate_cache(url: str, params: dict[str, Any] | None) -> None:
    """Удаляет ответ из кэша, например после ошибки разбора структуры."""
    with _cache_lock:
        _cache.pop(_cache_key(url, params), None)


def _put_cached(
    key: tuple[str, tuple[tuple[str, str], ...]],
    payload: dict[str, Any],
    ttl_sec: int,
) -> None:
    if ttl_sec <= 0:
        return
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl_sec, copy.deepcopy(payload))


def _throttle(provider: str) -> None:
    """Не даёт обращаться к одному API чаще разрешённого интервала."""
    with _rate_lock:
        now = time.monotonic()
        last = _last_request_at.get(provider)
        if last is not None:
            wait = config.HTTP_MIN_INTERVAL_SEC - (now - last)
            if wait > 0:
                _sleep(wait)
        _last_request_at[provider] = time.monotonic()


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _retry_delay(attempt: int, retry_after: float | None) -> float:
    delay = min(
        config.HTTP_BACKOFF_BASE_SEC * (2 ** (attempt - 1)),
        config.HTTP_BACKOFF_MAX_SEC,
    )
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay + random.uniform(0, 0.2)


def http_get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    provider: str,
    ttl_sec: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET JSON с кэшем, rate limit и повторами для временных ошибок."""
    key = _cache_key(url, params)
    cached = _get_cached(key)
    if cached is not None:
        logger.debug("%s: ответ из кэша", provider)
        return cached

    max_attempts = config.HTTP_MAX_ATTEMPTS
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        retry_after: float | None = None
        _throttle(provider)

        try:
            response = _session.get(
                url,
                params=params,
                headers=headers,
                timeout=(config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT),
            )
        except requests.Timeout as exc:
            last_error = TransientWeatherAPIError(f"{provider}: превышен таймаут запроса")
            logger.warning("%s: таймаут (попытка %d/%d)", provider, attempt, max_attempts)
        except requests.ConnectionError as exc:
            last_error = TransientWeatherAPIError(f"{provider}: ошибка соединения: {exc}")
            logger.warning("%s: ошибка соединения (попытка %d/%d)", provider, attempt, max_attempts)
        except requests.RequestException as exc:
            raise WeatherAPIError(f"{provider}: ошибка запроса: {exc}") from exc
        else:
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = _retry_after_seconds(response)
                last_error = TransientWeatherAPIError(
                    f"{provider}: HTTP {response.status_code}"
                )
                logger.warning(
                    "%s: HTTP %d (попытка %d/%d)",
                    provider,
                    response.status_code,
                    attempt,
                    max_attempts,
                )
            elif response.status_code >= 400:
                raise WeatherAPIError(f"{provider}: HTTP {response.status_code}")

            else:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise WeatherAPIError(f"{provider}: ответ не является корректным JSON") from exc
                if not isinstance(payload, dict):
                    raise WeatherAPIError(f"{provider}: ожидался JSON-объект")

                _put_cached(key, payload, ttl_sec)
                return payload

        if attempt < max_attempts:
            _sleep(_retry_delay(attempt, retry_after))

    raise TransientWeatherAPIError(
        f"{provider}: не удалось получить данные после {max_attempts} попыток"
    ) from last_error
