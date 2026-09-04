"""Hardcoded responses for C1. Replace in C3; do not change schemas."""

from __future__ import annotations

from datetime import date

from api.schemas import (
    Anomaly,
    CellDetail,
    CellEffort,
    HistoryRow,
    Recommendation,
    Stats,
    VesselDetail,
    VesselSummary,
)

VESSELS: list[VesselSummary] = [
    VesselSummary(
        mmsi="503000001",
        name="Southern Pride",
        gear="trawlers",
        flag="AUS",
        length=28.4,
    ),
    VesselSummary(
        mmsi="412334024",
        name=None,
        gear="drifting_longlines",
        flag="CHN",
        length=42.0,
    ),
    VesselSummary(
        mmsi="224123456",
        name="María del Mar",
        gear="fishing",
        flag="ESP",
        length=18.2,
    ),
]

_BY_MMSI = {v.mmsi: v for v in VESSELS}


def list_vessels(*, q: str | None, gear: str | None, limit: int) -> list[VesselSummary]:
    rows = VESSELS
    if q:
        needle = q.lower()
        rows = [
            v
            for v in rows
            if needle in v.mmsi.lower()
            or (v.name is not None and needle in v.name.lower())
        ]
    if gear:
        rows = [v for v in rows if v.gear == gear]
    return rows[:limit]


def get_vessel(mmsi: str) -> VesselDetail | None:
    meta = _BY_MMSI.get(mmsi)
    if meta is None:
        return None
    return VesselDetail(
        metadata=meta,
        active_days=214,
        top_cells=[
            CellEffort(cell_id="-38.5_141.6", lat=-38.5, lon=141.6, fishing_hours=38.2),
            CellEffort(cell_id="-38.4_141.7", lat=-38.4, lon=141.7, fishing_hours=21.0),
        ],
    )


def get_history(mmsi: str) -> list[HistoryRow] | None:
    if mmsi not in _BY_MMSI:
        return None
    return [
        HistoryRow(cell_id="-38.5_141.6", lat=-38.5, lon=141.6, fishing_hours=12.4),
        HistoryRow(cell_id="-38.5_141.5", lat=-38.5, lon=141.5, fishing_hours=4.1),
        HistoryRow(cell_id="-38.4_141.7", lat=-38.4, lon=141.7, fishing_hours=9.8),
    ]


def get_recommendations(
    mmsi: str,
    *,
    k: int,
    exclude_mpa: bool,
    season: str | None,
) -> list[Recommendation] | None:
    if mmsi not in _BY_MMSI:
        return None
    rows = [
        Recommendation(
            cell_id="-38.6_141.4",
            lat=-38.6,
            lon=141.4,
            score=0.91,
            depth=-118.0,
            in_mpa=False,
            distance_to_port=42.0,
            reason="120m depth, 42nm from port, typical for trawlers in autumn",
        ),
        Recommendation(
            cell_id="-39.1_143.2",
            lat=-39.1,
            lon=143.2,
            score=0.74,
            depth=-86.0,
            in_mpa=True,
            distance_to_port=61.0,
            reason="shelf cell inside an MPA; next-best legal alternative is -38.6_141.4",
        ),
        Recommendation(
            cell_id="-37.9_140.1",
            lat=-37.9,
            lon=140.1,
            score=0.68,
            depth=-64.0,
            in_mpa=False,
            distance_to_port=28.0,
            reason="60m depth, 28nm from port, similar gear mix in winter",
        ),
    ]
    if exclude_mpa:
        rows = [r for r in rows if not r.in_mpa]
    if season == "winter":
        rows = list(reversed(rows))
    return rows[:k]


def get_cell(cell_id: str) -> CellDetail | None:
    cells = {
        "-38.5_141.6": CellDetail(
            cell_id=cell_id,
            depth=-121.0,
            eez="Australia",
            in_mpa=False,
            top_gear_types=["trawlers", "fishing"],
        ),
        "-38.6_141.4": CellDetail(
            cell_id=cell_id,
            depth=-118.0,
            eez="Australia",
            in_mpa=False,
            top_gear_types=["trawlers"],
        ),
    }
    return cells.get(cell_id)


def list_anomalies(*, start: date | None, end: date | None, limit: int) -> list[Anomaly]:
    rows = [
        Anomaly(
            mmsi="412334024",
            cell_id="-38.5_141.6",
            date=date(2024, 10, 3),
            score=0.04,
            observed_hours=6.2,
        ),
        Anomaly(
            mmsi="503000001",
            cell_id="35.0_119.3",
            date=date(2024, 4, 18),
            score=0.11,
            observed_hours=3.8,
        ),
    ]
    if start is not None:
        rows = [r for r in rows if r.date >= start]
    if end is not None:
        rows = [r for r in rows if r.date <= end]
    return rows[:limit]


def get_stats() -> Stats:
    return Stats(
        n_vessels=117078,
        n_cells=2040786,
        n_interaction_rows=169587192,
        fishing_hours=226_091_223.7,
        years=[2023, 2024],
        note="C1 stub. Counts are from A2 silver EDA, not live queries.",
    )
