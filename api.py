"""FastAPI-интерфейс Weather Collector 2.0.

Обработчики не содержат бизнес-логики: сбор, хранение и расчёты выполняет
weather_service / weather_db / forecast_merge.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

import weather_api_config as config
import weather_db
import weather_service
from api_models import (
    CombinedResponse,
    DifferencesResponse,
    ForecastResponse,
    HealthResponse,
    HistoryResponse,
    Observation,
    SourcesResponse,
    StatisticsResponse,
)
from weather_storage import init_storage

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_storage()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.exception("Не удалось инициализировать SQLite: %s", exc)
    yield


app = FastAPI(
    title="Weather Collector 2.0",
    version=config.APP_VERSION,
    description="Локальный backend: прогнозы MET Norway и Open-Meteo, сравнение и история.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        with weather_db.connect() as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"SQLite недоступен: {exc}") from exc

    return HealthResponse(
        status="ok",
        city=config.CITY,
        time_utc=_utc_now(),
        database="ok",
    )


@app.get("/weather/current", response_model=Observation)
def current_weather():
    record = weather_service.get_current()
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Наблюдений пока нет или последнее наблюдение устарело",
        )
    return record


@app.get("/weather/forecast", response_model=ForecastResponse)
def forecast():
    rows = weather_service.get_forecast_rows()
    if not rows:
        raise HTTPException(
            status_code=503,
            detail="Прогноз недоступен: данные ещё не собраны или устарели",
        )
    return ForecastResponse(
        generated_at_utc=_utc_now(),
        city=config.CITY,
        rows=rows,
    )


@app.get("/weather/forecast/sources", response_model=SourcesResponse)
def forecast_sources():
    data = weather_service.get_sources()
    if all(source["status"] == "unavailable" for source in data["sources"].values()):
        raise HTTPException(status_code=503, detail="Нет сохранённых прогнозов источников")
    return data


@app.get("/weather/forecast/combined", response_model=CombinedResponse)
def forecast_combined():
    rows = weather_service.get_combined_rows()
    if not rows:
        raise HTTPException(status_code=503, detail="Объединённый прогноз пока недоступен")
    return CombinedResponse(
        generated_at_utc=_utc_now(),
        city=config.CITY,
        rows=rows,
    )


@app.get("/weather/forecast/differences", response_model=DifferencesResponse)
def forecast_differences():
    rows = weather_service.get_differences_rows()
    if rows is None:
        raise HTTPException(status_code=503, detail="Нет прогнозов для сравнения")
    return DifferencesResponse(
        generated_at_utc=_utc_now(),
        city=config.CITY,
        intervals=len(rows),
        rows=rows,
    )


@app.get("/weather/history", response_model=HistoryResponse)
def history(
    limit: int = Query(default=100, ge=1, le=5000, description="Последние N наблюдений"),
    since: datetime | None = Query(default=None, description="Начало периода (ISO 8601)"),
):
    observations = weather_service.get_history(limit=limit, since=since)
    return HistoryResponse(count=len(observations), observations=observations)


@app.get("/weather/statistics", response_model=StatisticsResponse)
def statistics():
    return weather_service.get_statistics()
