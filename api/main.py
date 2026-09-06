"""Serving API. C3 uses live gold artefacts when present; otherwise C1 stubs."""

from __future__ import annotations

import os
import tarfile
from contextlib import asynccontextmanager
from datetime import date
from types import ModuleType
from pathlib import Path
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.schemas import (
    Anomaly,
    CellDetail,
    ForecastRow,
    HistoryRow,
    MpaCell,
    Recommendation,
    Stats,
    VesselDetail,
    VesselSummary,
)
from api.store import artefacts_ready, get_store
from src.paths import PROCESSED_DIR, ROOT

FRONTEND_DIST = ROOT / "frontend" / "dist"


def _download(url: str, dest: Path) -> None:
    request = Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "github.com" in url:
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/octet-stream")
    with urlopen(request, timeout=180) as src, dest.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def fetch_artefacts() -> None:
    url = os.environ.get("ARTEFACT_URL")
    if not url or artefacts_ready():
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    archive = PROCESSED_DIR / "serve_artefacts.tgz"
    _download(url, archive)
    with tarfile.open(archive) as handle:
        try:
            handle.extractall(PROCESSED_DIR, filter="data")
        except TypeError:
            handle.extractall(PROCESSED_DIR)
    archive.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    fetch_artefacts()
    if artefacts_ready():
        get_store()
    yield


app = FastAPI(
    title="Fishing grounds recsys",
    version="0.4.0",
    description="ALS + fold-in + seasonal climatology when gold artefacts exist.",
    lifespan=lifespan,
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


@app.get("/mpa-cells", response_model=list[MpaCell])
def mpa_cells(
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    limit: int = Query(default=4000, ge=1, le=12000),
) -> list[MpaCell]:
    return _backend().list_mpa_cells(
        west=west, south=south, east=east, north=north, limit=limit
    )


@app.get("/anomalies", response_model=list[Anomaly])
def anomalies(
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[Anomaly]:
    return _backend().list_anomalies(start=start, end=end, limit=limit)


@app.get("/forecast", response_model=list[ForecastRow])
def forecast(
    season: str | None = None,
    exclude_mpa: bool = True,
    k: int = Query(default=80, ge=1, le=400),
) -> list[ForecastRow]:
    return _backend().list_forecast(season=season, exclude_mpa=exclude_mpa, k=k)


@app.get("/stats", response_model=Stats)
def stats() -> Stats:
    return _backend().get_stats()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "live": artefacts_ready()}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
