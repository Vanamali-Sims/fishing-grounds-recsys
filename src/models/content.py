"""Map vessel metadata onto ALS user factors for vessels with no train history."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
from scipy.sparse import csr_matrix

from src.models.als import recommend_als
from src.models.baselines import UNKNOWN_GEAR
from src.paths import CONTENT_FOLDIN_PATH, VESSELS_PATH

NUMERIC_COLUMNS = ("length_m_gfw", "tonnage_gt_gfw", "engine_power_kw_gfw")
GEAR_COLUMN = "vessel_class_gfw"
FLAG_COLUMN = "flag_gfw"
DEFAULT_RIDGE = 1.0


def load_latest_vessel_table(vessels_path: Path | None = None) -> dict[str, dict]:
    vessels_path = vessels_path or VESSELS_PATH
    if not vessels_path.exists():
        raise FileNotFoundError(
            f"Missing silver vessels ({vessels_path}). Run python -m src.clean.build first."
        )
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        rows = con.execute(
            f"""
            SELECT
              mmsi,
              {GEAR_COLUMN},
              {FLAG_COLUMN},
              length_m_gfw,
              tonnage_gt_gfw,
              engine_power_kw_gfw
            FROM (
              SELECT
                trim(CAST(mmsi AS VARCHAR)) AS mmsi,
                {GEAR_COLUMN},
                {FLAG_COLUMN},
                length_m_gfw,
                tonnage_gt_gfw,
                engine_power_kw_gfw,
                row_number() OVER (
                  PARTITION BY trim(CAST(mmsi AS VARCHAR))
                  ORDER BY year DESC
                ) AS rn
              FROM read_parquet(?)
            )
            WHERE rn = 1
            """,
            [vessels_path.as_posix()],
        ).fetchall()
    finally:
        con.close()
    table: dict[str, dict] = {}
    for mmsi, gear, flag, length, tonnage, power in rows:
        table[str(mmsi)] = {
            "gear": "" if gear is None else str(gear),
            "flag": "" if flag is None else str(flag),
            "length_m_gfw": length,
            "tonnage_gt_gfw": tonnage,
            "engine_power_kw_gfw": power,
        }
    return table


def _levels(table: dict[str, dict], mmsi: np.ndarray, key: str) -> list[str]:
    seen: list[str] = []
    for user in mmsi.tolist():
        value = table.get(str(user), {}).get(key, "")
        if value and value not in seen:
            seen.append(str(value))
    return seen


def _numeric_fill(table: dict[str, dict], mmsi: np.ndarray) -> np.ndarray:
    fills = np.zeros(len(NUMERIC_COLUMNS), dtype=np.float64)
    for j, col in enumerate(NUMERIC_COLUMNS):
        values = []
        for user in mmsi.tolist():
            raw = table.get(str(user), {}).get(col)
            if raw is not None and np.isfinite(float(raw)):
                values.append(np.log1p(max(float(raw), 0.0)))
        fills[j] = float(np.median(values)) if values else 0.0
    return fills


def encode_vessels(
    mmsi: np.ndarray,
    table: dict[str, dict],
    *,
    gear_levels: list[str] | None = None,
    flag_levels: list[str] | None = None,
    numeric_fill: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Rows aligned to ``mmsi``. Intercept + one-hot gear/flag + log numeric."""
    if gear_levels is None:
        gear_levels = _levels(table, mmsi, "gear")
    if flag_levels is None:
        flag_levels = _levels(table, mmsi, "flag")
    if numeric_fill is None:
        numeric_fill = _numeric_fill(table, mmsi)

    n = len(mmsi)
    n_gear = len(gear_levels)
    n_flag = len(flag_levels)
    n_num = len(NUMERIC_COLUMNS)
    width = 1 + n_gear + n_flag + n_num
    features = np.zeros((n, width), dtype=np.float64)
    features[:, 0] = 1.0
    gear_index = {name: 1 + i for i, name in enumerate(gear_levels)}
    flag_index = {name: 1 + n_gear + i for i, name in enumerate(flag_levels)}

    for row, user in enumerate(mmsi.tolist()):
        meta = table.get(str(user), {})
        gear = str(meta.get("gear") or UNKNOWN_GEAR)
        flag = str(meta.get("flag") or "")
        if gear in gear_index:
            features[row, gear_index[gear]] = 1.0
        if flag in flag_index:
            features[row, flag_index[flag]] = 1.0
        for j, col in enumerate(NUMERIC_COLUMNS):
            raw = meta.get(col)
            if raw is None or not np.isfinite(float(raw)):
                features[row, 1 + n_gear + n_flag + j] = numeric_fill[j]
            else:
                features[row, 1 + n_gear + n_flag + j] = np.log1p(max(float(raw), 0.0))

    encoder = {
        "gear_levels": gear_levels,
        "flag_levels": flag_levels,
        "numeric_fill": numeric_fill,
    }
    return features, encoder


def fit_foldin(
    features: np.ndarray,
    user_factors: np.ndarray,
    mask: np.ndarray,
    ridge: float = DEFAULT_RIDGE,
) -> np.ndarray:
    """Ridge: content features → ALS user factors, fit on warm rows only."""
    x = features[mask]
    y = user_factors[mask]
    n_features = x.shape[1]
    gram = x.T @ x
    gram.flat[:: n_features + 1] += ridge
    gram[0, 0] -= ridge
    return np.linalg.solve(gram, x.T @ y)


def predict_foldin(
    weights: np.ndarray,
    features: np.ndarray,
    item_factors: np.ndarray,
    matrix: csr_matrix,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    k: int,
) -> dict[str, list[str]]:
    user_factors = features @ weights
    return recommend_als(user_factors, item_factors, matrix, mmsi, cell_id, k)


def hybrid_rankings(
    als_rankings: dict[str, list[str]],
    content_rankings: dict[str, list[str]],
    matrix: csr_matrix,
    mmsi: np.ndarray,
) -> dict[str, list[str]]:
    """ALS for vessels with train history; content fold-in otherwise."""
    merged: dict[str, list[str]] = {}
    for row in range(matrix.shape[0]):
        user = str(mmsi[row])
        if int(matrix.indptr[row + 1]) > int(matrix.indptr[row]):
            merged[user] = list(als_rankings.get(user, ()))
        else:
            merged[user] = list(content_rankings.get(user, ()))
    return merged


def save_foldin(
    path: Path | None,
    weights: np.ndarray,
    encoder: dict,
    ridge: float,
) -> None:
    path = path or CONTENT_FOLDIN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    if tmp.exists():
        tmp.unlink()
    gear = np.asarray(encoder["gear_levels"], dtype="U64")
    flag = np.asarray(encoder["flag_levels"], dtype="U16")
    with tmp.open("wb") as handle:
        np.savez_compressed(
            handle,
            weights=np.asarray(weights, dtype=np.float64),
            gear_levels=gear,
            flag_levels=flag,
            numeric_fill=np.asarray(encoder["numeric_fill"], dtype=np.float64),
            ridge=np.asarray(ridge),
        )
    if path.exists():
        path.unlink()
    tmp.replace(path)


def load_foldin(path: Path | None = None) -> tuple[np.ndarray, dict, float]:
    path = path or CONTENT_FOLDIN_PATH
    with np.load(path, allow_pickle=False) as payload:
        weights = np.asarray(payload["weights"], dtype=np.float64)
        encoder = {
            "gear_levels": [str(x) for x in payload["gear_levels"].tolist()],
            "flag_levels": [str(x) for x in payload["flag_levels"].tolist()],
            "numeric_fill": np.asarray(payload["numeric_fill"], dtype=np.float64),
        }
        ridge = float(payload["ridge"])
    return weights, encoder, ridge
