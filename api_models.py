"""Pydantic-модели ответов FastAPI."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    city: str
    time_utc: str
    database: str


class Observation(BaseModel):
    observed_at_utc: str
    city: str
    temperature: float | None = None
    humidity: float | None = None
    wind_speed: float | None = None
    provider: str
    source: str
    fetched_at_utc: str


class ForecastPoint(BaseModel):
    ts_utc: str
    provider: str
    temperature: float | None = None
    humidity: float | None = None
    apparent_temperature: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gusts: float | None = None
    precipitation: float | None = None
    precipitation_probability: float | None = None
    snowfall: float | None = None
    cloud_cover: float | None = None
    rain: float | None = None
    weather_code: float | None = None
    weather_symbol: str | None = None
    fetched_at_utc: str | None = None


class CombinedPoint(BaseModel):
    ts_utc: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    apparent_temperature: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gusts: float | None = None
    precipitation: float | None = None
    precipitation_probability: float | None = None
    snowfall: float | None = None
    cloud_cover: float | None = None
    rain: float | None = None
    weather_code: float | None = None
    weather_code_agreement: bool | None = None
    derived: bool = True


class Difference(BaseModel):
    delta: float
    abs_delta: float
    level: Literal["small", "moderate", "large"]


class Availability(BaseModel):
    metno: bool
    open_meteo: bool


class ForecastRow(BaseModel):
    ts_utc: str
    metno: ForecastPoint | None = None
    open_meteo: ForecastPoint | None = None
    combined: CombinedPoint | None = None
    differences: dict[str, Difference | None] | None = None
    availability: Availability


class ForecastResponse(BaseModel):
    generated_at_utc: str
    city: str
    rows: list[ForecastRow]
    stale: bool = False
    sources: "SourceStatusPayload"


class CombinedResponse(BaseModel):
    generated_at_utc: str
    city: str
    rows: list[CombinedPoint]
    stale: bool = False
    snapshot_generated_at_utc: str | None = None
    sources: "SourceStatusPayload"


class DifferenceRow(BaseModel):
    ts_utc: str
    differences: dict[str, Difference | None]
    availability: Availability


class DifferencesResponse(BaseModel):
    generated_at_utc: str
    city: str
    intervals: int
    rows: list[DifferenceRow]
    stale: bool = False
    sources: "SourceStatusPayload"


class SourceStatusInfo(BaseModel):
    status: Literal["ok", "stale", "unavailable", "error"]
    count: int = 0
    fetched_at_utc: str | None = None
    age_hours: float | None = None
    stale: bool = False
    error: str | None = None
    last_attempt_at_utc: str | None = None


class SourceInfo(SourceStatusInfo):
    points: list[ForecastPoint] = Field(default_factory=list)


class SourcesPayload(BaseModel):
    metno: SourceInfo
    open_meteo: SourceInfo


class SourceStatusPayload(BaseModel):
    metno: SourceStatusInfo
    open_meteo: SourceStatusInfo


class SourcesResponse(BaseModel):
    generated_at_utc: str
    city: str
    sources: SourcesPayload


class HistoryResponse(BaseModel):
    count: int
    observations: list[Observation]


class StatisticsResponse(BaseModel):
    city: str
    observations: dict[str, Any] | None = None
    forecast: dict[str, Any]
