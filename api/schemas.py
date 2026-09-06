"""Pydantic contract for the serving API. C3 must keep these shapes."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class VesselSummary(BaseModel):
    mmsi: str
    name: str | None = None
    gear: str
    flag: str
    length: float | None = Field(default=None, description="Length in metres")


class CellEffort(BaseModel):
    cell_id: str
    lat: float
    lon: float
    fishing_hours: float


class VesselDetail(BaseModel):
    metadata: VesselSummary
    active_days: int
    top_cells: list[CellEffort]


class HistoryRow(BaseModel):
    cell_id: str
    lat: float
    lon: float
    fishing_hours: float


class Recommendation(BaseModel):
    cell_id: str
    lat: float
    lon: float
    score: float
    depth: float | None = None
    in_mpa: bool | None = None
    distance_to_port: float | None = Field(
        default=None, description="Nautical miles to nearest named anchorage"
    )
    reason: str


class CellDetail(BaseModel):
    cell_id: str
    depth: float | None = None
    eez: str | None = None
    in_mpa: bool | None = None
    top_gear_types: list[str]


class Anomaly(BaseModel):
    mmsi: str
    cell_id: str
    date: date
    score: float
    observed_hours: float


class MpaCell(BaseModel):
    cell_id: str
    lat: float
    lon: float


class Stats(BaseModel):
    n_vessels: int
    n_cells: int
    n_interaction_rows: int
    fishing_hours: float
    years: list[int]
    note: str
    n_mpa_cells: int | None = None
    mpa_ready: bool = False
