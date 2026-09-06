"""Hardcoded responses for C1. Replace in C3; do not change schemas."""

from __future__ import annotations

from datetime import date

from api.schemas import (
    Anomaly,
    CellDetail,
    CellEffort,
    ForecastRow,
    HistoryRow,
    MpaCell,
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
    VesselSummary(
        mmsi="503900112",
        name="Cape Otway",
        gear="trawlers",
        flag="AUS",
        length=31.6,
    ),
    VesselSummary(
        mmsi="512000883",
        name="Te Moana",
        gear="set_longlines",
        flag="NZL",
        length=22.0,
    ),
]

_BY_MMSI = {v.mmsi: v for v in VESSELS}


def _cell_id(lat: float, lon: float) -> str:
    return f"{lat:.1f}_{lon:.1f}"


def _grid(lat0: float, lon0: float, rows: int, cols: int, peak: float) -> list[tuple[float, float, float]]:
    cells: list[tuple[float, float, float]] = []
    for i in range(rows):
        for j in range(cols):
            lat = round(lat0 + 0.1 * i, 1)
            lon = round(lon0 + 0.1 * j, 1)
            hours = peak / (1.0 + 0.35 * (i + 0.6 * j))
            if hours < 0.8:
                continue
            cells.append((lat, lon, round(hours, 2)))
    return cells


_HISTORY: dict[str, list[HistoryRow]] = {
    "503000001": [
        HistoryRow(cell_id="-38.5_141.6", lat=-38.5, lon=141.6, fishing_hours=12.4),
        HistoryRow(cell_id="-38.5_141.5", lat=-38.5, lon=141.5, fishing_hours=4.1),
        HistoryRow(cell_id="-38.4_141.7", lat=-38.4, lon=141.7, fishing_hours=9.8),
        *[
            HistoryRow(cell_id=_cell_id(lat, lon), lat=lat, lon=lon, fishing_hours=hours)
            for lat, lon, hours in _grid(-38.8, 141.2, 5, 6, 22.0)
            if _cell_id(lat, lon) not in {"-38.5_141.6", "-38.5_141.5", "-38.4_141.7"}
        ],
    ],
    "412334024": [
        HistoryRow(cell_id=_cell_id(lat, lon), lat=lat, lon=lon, fishing_hours=hours)
        for lat, lon, hours in _grid(-41.3, 148.3, 4, 6, 16.0)
    ],
    "224123456": [
        HistoryRow(cell_id=_cell_id(lat, lon), lat=lat, lon=lon, fishing_hours=hours)
        for lat, lon, hours in _grid(-35.1, 136.0, 4, 5, 11.0)
    ],
    "503900112": [
        HistoryRow(cell_id=_cell_id(lat, lon), lat=lat, lon=lon, fishing_hours=hours)
        for lat, lon, hours in _grid(-38.9, 141.0, 4, 5, 18.0)
    ],
    "512000883": [
        HistoryRow(cell_id=_cell_id(lat, lon), lat=lat, lon=lon, fishing_hours=hours)
        for lat, lon, hours in _grid(-40.6, 173.8, 4, 5, 9.5)
    ],
}

_RECS: dict[str, list[Recommendation]] = {
    "503000001": [
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
        Recommendation(
            cell_id="-38.9_141.0",
            lat=-38.9,
            lon=141.0,
            score=0.63,
            depth=-95.0,
            in_mpa=False,
            distance_to_port=38.0,
            reason="95m depth, 38nm from port, typical for trawlers in autumn",
        ),
        Recommendation(
            cell_id="-38.3_142.1",
            lat=-38.3,
            lon=142.1,
            score=0.57,
            depth=-72.0,
            in_mpa=False,
            distance_to_port=24.0,
            reason="72m depth, 24nm from port, adjacent to observed Otway effort",
        ),
        Recommendation(
            cell_id="-39.0_141.8",
            lat=-39.0,
            lon=141.8,
            score=0.51,
            depth=-140.0,
            in_mpa=False,
            distance_to_port=55.0,
            reason="140m depth, 55nm from port, slope cells used by similar hulls",
        ),
    ],
    "412334024": [
        Recommendation(
            cell_id="-41.0_148.9",
            lat=-41.0,
            lon=148.9,
            score=0.82,
            depth=-210.0,
            in_mpa=False,
            distance_to_port=48.0,
            reason="210m depth, 48nm from port, typical for drifting longliners",
        ),
        Recommendation(
            cell_id="-41.6_148.2",
            lat=-41.6,
            lon=148.2,
            score=0.61,
            depth=-180.0,
            in_mpa=True,
            distance_to_port=66.0,
            reason="MPA on the Tasman shelf; next-best legal alternative is -41.0_148.9",
        ),
        Recommendation(
            cell_id="-40.8_148.5",
            lat=-40.8,
            lon=148.5,
            score=0.54,
            depth=-155.0,
            in_mpa=False,
            distance_to_port=41.0,
            reason="155m depth, 41nm from port, similar longline sets in spring",
        ),
    ],
    "224123456": [
        Recommendation(
            cell_id="-34.7_136.4",
            lat=-34.7,
            lon=136.4,
            score=0.77,
            depth=-42.0,
            in_mpa=False,
            distance_to_port=18.0,
            reason="42m depth, 18nm from port, gulf mix typical for this class",
        ),
        Recommendation(
            cell_id="-35.4_136.6",
            lat=-35.4,
            lon=136.6,
            score=0.49,
            depth=-38.0,
            in_mpa=False,
            distance_to_port=22.0,
            reason="38m depth, 22nm from port, inshore cells used by similar length",
        ),
    ],
    "503900112": [
        Recommendation(
            cell_id="-38.6_141.4",
            lat=-38.6,
            lon=141.4,
            score=0.88,
            depth=-118.0,
            in_mpa=False,
            distance_to_port=42.0,
            reason="120m depth, 42nm from port, typical for trawlers in autumn",
        ),
        Recommendation(
            cell_id="-39.1_143.2",
            lat=-39.1,
            lon=143.2,
            score=0.58,
            depth=-86.0,
            in_mpa=True,
            distance_to_port=61.0,
            reason="shelf cell inside an MPA; next-best legal alternative is -38.6_141.4",
        ),
    ],
    "512000883": [
        Recommendation(
            cell_id="-40.3_174.1",
            lat=-40.3,
            lon=174.1,
            score=0.71,
            depth=-90.0,
            in_mpa=False,
            distance_to_port=31.0,
            reason="90m depth, 31nm from port, typical for set longlines",
        ),
        Recommendation(
            cell_id="-40.9_174.4",
            lat=-40.9,
            lon=174.4,
            score=0.44,
            depth=-110.0,
            in_mpa=False,
            distance_to_port=39.0,
            reason="110m depth, 39nm from port, Cook Strait sets by similar gear",
        ),
    ],
}

_CELLS: dict[str, CellDetail] = {
    "-38.5_141.6": CellDetail(
        cell_id="-38.5_141.6",
        depth=-121.0,
        eez="Australia",
        in_mpa=False,
        top_gear_types=["trawlers", "fishing"],
    ),
    "-38.6_141.4": CellDetail(
        cell_id="-38.6_141.4",
        depth=-118.0,
        eez="Australia",
        in_mpa=False,
        top_gear_types=["trawlers"],
    ),
}


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
    history = _HISTORY.get(mmsi, [])
    top = sorted(history, key=lambda row: row.fishing_hours, reverse=True)[:3]
    return VesselDetail(
        metadata=meta,
        active_days=214 if mmsi == "503000001" else 96 + len(history),
        top_cells=[
            CellEffort(
                cell_id=row.cell_id,
                lat=row.lat,
                lon=row.lon,
                fishing_hours=row.fishing_hours,
            )
            for row in top
        ],
    )


def get_history(mmsi: str) -> list[HistoryRow] | None:
    if mmsi not in _BY_MMSI:
        return None
    return list(_HISTORY.get(mmsi, []))


def get_recommendations(
    mmsi: str,
    *,
    k: int,
    exclude_mpa: bool,
    season: str | None,
) -> list[Recommendation] | None:
    if mmsi not in _BY_MMSI:
        return None
    rows = list(_RECS.get(mmsi, []))
    if exclude_mpa:
        rows = [r for r in rows if not r.in_mpa]
    if season:
        # Stub prior: keep higher-score shelf cells first in winter-like seasons.
        reverse = season.lower() == "summer"
        rows = sorted(rows, key=lambda row: row.score, reverse=not reverse)
    return rows[:k]


def list_forecast(
    *,
    season: str | None,
    exclude_mpa: bool,
    k: int,
) -> list[ForecastRow]:
    key = (season or "winter").lower()
    seen: dict[str, ForecastRow] = {}
    for recs in _RECS.values():
        for rec in recs:
            if exclude_mpa and rec.in_mpa is True:
                continue
            hours = rec.score * (18.0 if key == "spring" else 9.0)
            seen[rec.cell_id] = ForecastRow(
                cell_id=rec.cell_id,
                lat=rec.lat,
                lon=rec.lon,
                predicted_hours=round(hours, 2),
                season=key,
                reason="C1 stub climatology from hardcoded southern-Australia cells.",
            )
    return list(seen.values())[:k]


def get_cell(cell_id: str) -> CellDetail | None:
    if cell_id in _CELLS:
        return _CELLS[cell_id]
    parts = cell_id.split("_")
    if len(parts) != 2:
        return None
    try:
        float(parts[0])
        float(parts[1])
    except ValueError:
        return None
    in_mpa = any(
        rec.cell_id == cell_id and rec.in_mpa for recs in _RECS.values() for rec in recs
    )
    return CellDetail(
        cell_id=cell_id,
        depth=None,
        eez="Australia",
        in_mpa=in_mpa or None,
        top_gear_types=["trawlers"] if in_mpa is False else [],
    )


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


def list_mpa_cells(
    *,
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
    limit: int,
) -> list[MpaCell]:
    seen: dict[str, MpaCell] = {}
    for recs in _RECS.values():
        for rec in recs:
            if rec.in_mpa is not True:
                continue
            if west is not None and rec.lon < west:
                continue
            if east is not None and rec.lon > east:
                continue
            if south is not None and rec.lat < south:
                continue
            if north is not None and rec.lat > north:
                continue
            seen[rec.cell_id] = MpaCell(cell_id=rec.cell_id, lat=rec.lat, lon=rec.lon)
    return list(seen.values())[:limit]


def get_stats() -> Stats:
    n_mpa = len(
        {
            rec.cell_id
            for recs in _RECS.values()
            for rec in recs
            if rec.in_mpa is True
        }
    )
    return Stats(
        n_vessels=117078,
        n_cells=2040786,
        n_interaction_rows=169587192,
        fishing_hours=226_091_223.7,
        years=[2023, 2024],
        note="C1 stub. Counts are from A2 silver EDA, not live queries.",
        n_mpa_cells=n_mpa,
        mpa_ready=n_mpa > 0,
    )
