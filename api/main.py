"""Serving API. C3 uses live gold artefacts when present; otherwise C1 stubs."""

from __future__ import annotations

from datetime import date
from types import ModuleType

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    Anomaly,
    CellDetail,
    HistoryRow,
    Recommendation,
    Stats,
    VesselDetail,
    VesselSummary,
)
from api.store import artefacts_ready

app = FastAPI(
    title="Fishing grounds recsys",
    version="0.3.0",
    description="Contract from C1. Bodies are ALS + fold-in when gold artefacts exist.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _backend() -> ModuleType:
    if artefacts_ready():
        from api import live

        return live
    from api import stubs

    return stubs


@app.get("/vessels", response_model=list[VesselSummary])
def vessels(
    q: str | None = None,
    gear: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[VesselSummary]:
    return _backend().list_vessels(q=q, gear=gear, limit=limit)


@app.get("/vessels/{mmsi}", response_model=VesselDetail)
def vessel(mmsi: str) -> VesselDetail:
    row = _backend().get_vessel(mmsi)
    if row is None:
        raise HTTPException(status_code=404, detail="vessel not found")
    return row


@app.get("/vessels/{mmsi}/history", response_model=list[HistoryRow])
def vessel_history(mmsi: str) -> list[HistoryRow]:
    rows = _backend().get_history(mmsi)
    if rows is None:
        raise HTTPException(status_code=404, detail="vessel not found")
    return rows


@app.get("/vessels/{mmsi}/recommendations", response_model=list[Recommendation])
def vessel_recommendations(
    mmsi: str,
    k: int = Query(default=50, ge=1, le=200),
    exclude_mpa: bool = True,
    season: str | None = None,
) -> list[Recommendation]:
    rows = _backend().get_recommendations(
        mmsi, k=k, exclude_mpa=exclude_mpa, season=season
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="vessel not found")
    return rows


@app.get("/cells/{cell_id}", response_model=CellDetail)
def cell(cell_id: str) -> CellDetail:
    row = _backend().get_cell(cell_id)
    if row is None:
        raise HTTPException(status_code=404, detail="cell not found")
    return row


@app.get("/anomalies", response_model=list[Anomaly])
def anomalies(
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[Anomaly]:
    return _backend().list_anomalies(start=start, end=end, limit=limit)


@app.get("/stats", response_model=Stats)
def stats() -> Stats:
    return _backend().get_stats()
