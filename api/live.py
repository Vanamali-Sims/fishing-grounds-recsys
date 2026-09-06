"""C3 live bodies. Same function names as ``api.stubs``; swap in ``api.main``."""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd

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
from api.store import (
    artefacts_ready,
    get_store,
    metres_to_nm,
    nullable_bool,
    nullable_float,
)
from src.features.season import normalize_season, season_multiplier
from src.models.als import recommend_user
from src.models.content import encode_vessels
from src.paths import FISHING_EVENTS_PATH, YEARS

HISTORY_CAP = 400


def _summary(mmsi: str) -> VesselSummary | None:
    store = get_store()
    if mmsi not in store.mmsi_index:
        return None
    meta = store.vessels.get(mmsi, {})
    gear = str(meta.get("gear") or "unknown")
    flag = str(meta.get("flag") or "UNK")
    return VesselSummary(
        mmsi=mmsi,
        name=None,
        gear=gear,
        flag=flag,
        length=nullable_float(meta.get("length_m_gfw")),
    )


def _cell_lat_lon(cell_id: str) -> tuple[float, float] | None:
    store = get_store()
    if cell_id in store.cells.index:
        row = store.cells.loc[cell_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return float(row["cell_ll_lat"]), float(row["cell_ll_lon"])
    parts = cell_id.split("_")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _reason(cell_id: str, gear: str) -> str:
    store = get_store()
    bits: list[str] = []
    if cell_id in store.cells.index:
        row = store.cells.loc[cell_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        depth = nullable_float(row["depth_mean_m"])
        dist = metres_to_nm(row["distance_to_port_m"])
        if depth is not None:
            bits.append(f"{abs(depth):.0f}m depth")
        if dist is not None:
            bits.append(f"{dist:.0f}nm from port")
        if nullable_bool(row["in_mpa"]) is True:
            bits.append("inside a marine protected area")
    label = gear.replace("_", " ")
    if label and label != "unknown":
        bits.append(f"typical for {label}")
    return ", ".join(bits) or "scored from vessels with similar grounds"


def list_vessels(*, q: str | None, gear: str | None, limit: int) -> list[VesselSummary]:
    store = get_store()
    rows: list[tuple[VesselSummary, int]] = []
    needle = q.lower() if q else None
    nnz = np.diff(store.train.indptr)
    for mmsi, idx in store.mmsi_index.items():
        summary = _summary(mmsi)
        if summary is None:
            continue
        if needle and needle not in summary.mmsi.lower():
            continue
        if gear and summary.gear != gear:
            continue
        rows.append((summary, int(nnz[idx])))
    rows.sort(key=lambda item: (-item[1], item[0].mmsi))
    return [item[0] for item in rows[:limit]]


def get_vessel(mmsi: str) -> VesselDetail | None:
    summary = _summary(mmsi)
    if summary is None:
        return None
    history = get_history(mmsi) or []
    top = sorted(history, key=lambda row: row.fishing_hours, reverse=True)[:5]
    con = duckdb.connect()
    try:
        active = con.execute(
            """
            SELECT count(DISTINCT date)
            FROM read_parquet(?)
            WHERE mmsi = ?
            """,
            [FISHING_EVENTS_PATH.as_posix(), mmsi],
        ).fetchone()[0]
    finally:
        con.close()
    return VesselDetail(
        metadata=summary,
        active_days=int(active or 0),
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
    store = get_store()
    if mmsi not in store.mmsi_index:
        return None
    con = duckdb.connect()
    try:
        pairs = con.execute(
            """
            SELECT cell_id, sum(fishing_hours)::DOUBLE AS fishing_hours
            FROM read_parquet(?)
            WHERE mmsi = ?
            GROUP BY 1
            ORDER BY fishing_hours DESC
            LIMIT ?
            """,
            [FISHING_EVENTS_PATH.as_posix(), mmsi, HISTORY_CAP],
        ).fetchall()
    finally:
        con.close()
    rows: list[HistoryRow] = []
    for cell_id, hours in pairs:
        coords = _cell_lat_lon(str(cell_id))
        if coords is None:
            continue
        lat, lon = coords
        rows.append(
            HistoryRow(
                cell_id=str(cell_id),
                lat=lat,
                lon=lon,
                fishing_hours=float(hours),
            )
        )
    return rows


def _user_vector(mmsi: str) -> np.ndarray | None:
    store = get_store()
    idx = store.mmsi_index.get(mmsi)
    if idx is None:
        return None
    start = int(store.train.indptr[idx])
    end = int(store.train.indptr[idx + 1])
    if end > start:
        return store.user_factors[idx]
    keys = np.array([mmsi], dtype=store.mmsi.dtype)
    features, _encoder = encode_vessels(
        keys,
        store.vessels,
        gear_levels=store.encoder["gear_levels"],
        flag_levels=store.encoder["flag_levels"],
        numeric_fill=store.encoder["numeric_fill"],
    )
    return features[0] @ store.foldin_weights


def get_recommendations(
    mmsi: str,
    *,
    k: int,
    exclude_mpa: bool,
    season: str | None,
) -> list[Recommendation] | None:
    store = get_store()
    idx = store.mmsi_index.get(mmsi)
    if idx is None:
        return None
    user_vec = _user_vector(mmsi)
    if user_vec is None:
        return None
    start = int(store.train.indptr[idx])
    end = int(store.train.indptr[idx + 1])
    seen = store.train.indices[start:end]
    season_key = normalize_season(season)
    fetch_k = min(max(k * 8 if season_key else k * 3, k), len(store.cell_id))
    ranked = recommend_user(
        user_vec, store.item_factors, seen, store.cell_id, fetch_k
    )
    if season_key:
        peak = store.season_peak.get(season_key, 0.0)
        table = store.season_hours.get(season_key, {})
        ranked = sorted(
            (
                (
                    cell_id,
                    score * season_multiplier(table.get(cell_id, 0.0), peak),
                )
                for cell_id, score in ranked
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    gear = str(store.vessels.get(mmsi, {}).get("gear") or "unknown")
    rows: list[Recommendation] = []
    for cell_id, score in ranked:
        coords = _cell_lat_lon(cell_id)
        if coords is None:
            continue
        lat, lon = coords
        depth = None
        dist_nm = None
        in_mpa = None
        if cell_id in store.cells.index:
            cell = store.cells.loc[cell_id]
            if isinstance(cell, pd.DataFrame):
                cell = cell.iloc[0]
            depth = nullable_float(cell["depth_mean_m"])
            dist_nm = metres_to_nm(cell["distance_to_port_m"])
            in_mpa = nullable_bool(cell["in_mpa"])
        if exclude_mpa and in_mpa is True:
            continue
        reason = _reason(cell_id, gear)
        if season_key:
            hours = store.season_hours.get(season_key, {}).get(cell_id, 0.0)
            reason = f"{season_key} climatology {hours:.1f}h/yr, {reason}"
        rows.append(
            Recommendation(
                cell_id=cell_id,
                lat=lat,
                lon=lon,
                score=score,
                depth=depth,
                in_mpa=in_mpa,
                distance_to_port=dist_nm,
                reason=reason,
            )
        )
        if len(rows) >= k:
            break
    return rows


def list_forecast(
    *,
    season: str | None,
    exclude_mpa: bool,
    k: int,
) -> list[ForecastRow]:
    store = get_store()
    season_key = normalize_season(season) or "winter"
    table = store.season_hours.get(season_key, {})
    ranked = sorted(table.items(), key=lambda item: item[1], reverse=True)
    rows: list[ForecastRow] = []
    for cell_id, hours in ranked:
        coords = _cell_lat_lon(cell_id)
        if coords is None:
            continue
        in_mpa = None
        if cell_id in store.cells.index:
            cell = store.cells.loc[cell_id]
            if isinstance(cell, pd.DataFrame):
                cell = cell.iloc[0]
            in_mpa = nullable_bool(cell["in_mpa"])
        if exclude_mpa and in_mpa is True:
            continue
        lat, lon = coords
        rows.append(
            ForecastRow(
                cell_id=cell_id,
                lat=lat,
                lon=lon,
                predicted_hours=float(hours),
                season=season_key,
                reason=(
                    f"mean {season_key} fishing hours per year in 2023–2024 "
                    "(climatology, not a dynamical forecast)"
                ),
            )
        )
        if len(rows) >= k:
            break
    return rows


def get_cell(cell_id: str) -> CellDetail | None:
    store = get_store()
    if cell_id not in store.cells.index:
        return None
    row = store.cells.loc[cell_id]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    eez = row["eez_sovereign"]
    return CellDetail(
        cell_id=cell_id,
        depth=nullable_float(row["depth_mean_m"]),
        eez=None if eez is None or pd.isna(eez) else str(eez),
        in_mpa=nullable_bool(row["in_mpa"]),
        top_gear_types=_top_gear(cell_id),
    )


def _top_gear(cell_id: str) -> list[str]:
    from src.paths import VESSELS_PATH

    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            SELECT gear FROM (
              SELECT coalesce(v.vessel_class_gfw, 'unknown') AS gear,
                     sum(e.fishing_hours) AS hours
              FROM read_parquet(?) e
              LEFT JOIN read_parquet(?) v
                ON e.mmsi = v.mmsi AND year(e.date) = v.year
              WHERE e.cell_id = ?
              GROUP BY 1
            )
            ORDER BY hours DESC
            LIMIT 3
            """,
            [FISHING_EVENTS_PATH.as_posix(), VESSELS_PATH.as_posix(), cell_id],
        ).fetchall()
    finally:
        con.close()
    return [str(gear) for (gear,) in rows if gear]


def list_anomalies(*, start: date | None, end: date | None, limit: int) -> list[Anomaly]:
    store = get_store()
    coo = store.full.tocoo()
    if coo.nnz == 0:
        return []
    scores = np.einsum(
        "ij,ij->i",
        store.user_factors[coo.row],
        store.item_factors[coo.col],
    )
    order = np.argsort(scores, kind="stable")[: max(limit * 8, limit)]
    candidates = [
        (
            str(store.mmsi[int(coo.row[i])]),
            str(store.cell_id[int(coo.col[i])]),
            float(scores[i]),
            float(coo.data[i]),
        )
        for i in order
    ]
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        con.execute(
            """
            CREATE TEMP TABLE cand (mmsi VARCHAR, cell_id VARCHAR, score DOUBLE, observed_hours DOUBLE)
            """
        )
        con.executemany("INSERT INTO cand VALUES (?, ?, ?, ?)", candidates)
        where = ["1=1"]
        params: list[object] = [FISHING_EVENTS_PATH.as_posix()]
        if start is not None:
            where.append("e.date >= CAST(? AS DATE)")
            params.append(start.isoformat())
        if end is not None:
            where.append("e.date <= CAST(? AS DATE)")
            params.append(end.isoformat())
        params.append(limit)
        sql = f"""
            SELECT c.mmsi, c.cell_id, min(e.date) AS day, c.score, c.observed_hours
            FROM cand c
            JOIN read_parquet(?) e
              ON c.mmsi = e.mmsi AND c.cell_id = e.cell_id
            WHERE {' AND '.join(where)}
            GROUP BY c.mmsi, c.cell_id, c.score, c.observed_hours
            ORDER BY c.score ASC
            LIMIT ?
        """
        fetched = con.execute(sql, params).fetchall()
    finally:
        con.close()
    return [
        Anomaly(
            mmsi=str(mmsi),
            cell_id=str(cell_id),
            date=day if isinstance(day, date) else date.fromisoformat(str(day)[:10]),
            score=float(score),
            observed_hours=float(hours),
        )
        for mmsi, cell_id, day, score, hours in fetched
    ]


def list_mpa_cells(
    *,
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
    limit: int,
) -> list[MpaCell]:
    store = get_store()
    flagged = store.cells[store.cells["in_mpa"] == True]  # noqa: E712
    if flagged.empty:
        return []
    if None not in (west, south, east, north):
        flagged = flagged[
            (flagged["cell_ll_lon"] >= west)
            & (flagged["cell_ll_lon"] <= east)
            & (flagged["cell_ll_lat"] >= south)
            & (flagged["cell_ll_lat"] <= north)
        ]
    rows: list[MpaCell] = []
    for cell_id, row in flagged.head(limit).iterrows():
        rows.append(
            MpaCell(
                cell_id=str(cell_id),
                lat=float(row["cell_ll_lat"]),
                lon=float(row["cell_ll_lon"]),
            )
        )
    return rows


def get_stats() -> Stats:
    con = duckdb.connect()
    try:
        n_rows, hours, n_vessels, n_cells = con.execute(
            """
            SELECT
              count(*)::BIGINT,
              coalesce(sum(fishing_hours), 0)::DOUBLE,
              count(DISTINCT mmsi)::BIGINT,
              count(DISTINCT cell_id)::BIGINT
            FROM read_parquet(?)
            """,
            [FISHING_EVENTS_PATH.as_posix()],
        ).fetchone()
    finally:
        con.close()
    store = get_store()
    n_mpa = int((store.cells["in_mpa"] == True).sum())  # noqa: E712
    return Stats(
        n_vessels=int(n_vessels),
        n_cells=int(n_cells),
        n_interaction_rows=int(n_rows),
        fishing_hours=float(hours),
        years=list(YEARS),
        note="C3 live. Australian EEZ gold artefacts; ALS + fold-in + seasonal climatology.",
        n_mpa_cells=n_mpa,
        mpa_ready=n_mpa > 0,
    )


def ready() -> bool:
    return artefacts_ready()
