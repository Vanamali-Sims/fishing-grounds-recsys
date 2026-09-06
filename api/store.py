"""Gold artefacts loaded once for the C3 serving layer."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.sparse import csr_matrix

from src.features.sparse_matrix import load_csr
from src.models.als import load_factors
from src.models.content import load_foldin, load_latest_vessel_table
from src.paths import (
    ALS_FACTORS_PATH,
    CELLS_PATH,
    CONTENT_FOLDIN_PATH,
    FISHING_EVENTS_PATH,
    MATRIX_PATH,
    TRAIN_MATRIX_PATH,
    VESSELS_PATH,
)

NM_METRES = 1852.0


def artefacts_ready() -> bool:
    return all(
        path.exists()
        for path in (
            ALS_FACTORS_PATH,
            CONTENT_FOLDIN_PATH,
            TRAIN_MATRIX_PATH,
            MATRIX_PATH,
            CELLS_PATH,
            VESSELS_PATH,
            FISHING_EVENTS_PATH,
        )
    )


@dataclass
class Store:
    train: csr_matrix
    full: csr_matrix
    mmsi: np.ndarray
    cell_id: np.ndarray
    user_factors: np.ndarray
    item_factors: np.ndarray
    foldin_weights: np.ndarray
    encoder: dict
    vessels: dict[str, dict]
    cells: pd.DataFrame
    mmsi_index: dict[str, int]
    cell_index: dict[str, int]


_STORE: Store | None = None


def load_store() -> Store:
    train, train_mmsi, train_cell = load_csr(TRAIN_MATRIX_PATH)
    full, full_mmsi, full_cell = load_csr(MATRIX_PATH)
    users, items, factor_mmsi, factor_cell, _params = load_factors(ALS_FACTORS_PATH)
    if list(train_mmsi) != list(factor_mmsi) or list(train_cell) != list(factor_cell):
        raise RuntimeError("ALS factors and train matrix index maps do not match")
    if list(full_mmsi) != list(factor_mmsi) or list(full_cell) != list(factor_cell):
        raise RuntimeError("ALS factors and full matrix index maps do not match")
    weights, encoder, _ridge = load_foldin(CONTENT_FOLDIN_PATH)
    vessels = load_latest_vessel_table(VESSELS_PATH)
    cells = pq.read_table(CELLS_PATH).to_pandas().set_index("cell_id", drop=False)
    mmsi_list = [str(x) for x in train_mmsi.tolist()]
    cell_list = [str(x) for x in train_cell.tolist()]
    return Store(
        train=train,
        full=full,
        mmsi=train_mmsi,
        cell_id=train_cell,
        user_factors=users,
        item_factors=items,
        foldin_weights=weights,
        encoder=encoder,
        vessels=vessels,
        cells=cells,
        mmsi_index={key: i for i, key in enumerate(mmsi_list)},
        cell_index={key: i for i, key in enumerate(cell_list)},
    )


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = load_store()
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = None


def metres_to_nm(metres: object) -> float | None:
    if metres is None or (isinstance(metres, float) and not np.isfinite(metres)):
        return None
    try:
        value = float(metres)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return value / NM_METRES


def nullable_bool(value: object) -> bool | None:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def nullable_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number
