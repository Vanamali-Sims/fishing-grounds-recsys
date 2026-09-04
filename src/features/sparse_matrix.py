"""CSR plus string index maps as one ``.npz``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

MMSI_DTYPE = "U16"
CELL_DTYPE = "U32"


def pairs_to_csr(
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    hours: np.ndarray,
    row_keys: np.ndarray,
    col_keys: np.ndarray,
) -> csr_matrix:
    row_index = {key: i for i, key in enumerate(row_keys.tolist())}
    col_index = {key: j for j, key in enumerate(col_keys.tolist())}
    n = len(mmsi)
    rows = np.fromiter((row_index[m] for m in mmsi.tolist()), dtype=np.int32, count=n)
    cols = np.fromiter((col_index[c] for c in cell_id.tolist()), dtype=np.int32, count=n)
    return csr_matrix(
        (np.asarray(hours, dtype=np.float64), (rows, cols)),
        shape=(len(row_keys), len(col_keys)),
    )


def save_csr(
    path: Path,
    matrix: csr_matrix,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    if tmp.exists():
        tmp.unlink()
    with tmp.open("wb") as handle:
        np.savez_compressed(
            handle,
            data=np.asarray(matrix.data, dtype=np.float64),
            indices=np.asarray(matrix.indices, dtype=np.int32),
            indptr=np.asarray(matrix.indptr, dtype=np.int32),
            shape=np.asarray(matrix.shape, dtype=np.int64),
            mmsi=np.asarray(mmsi, dtype=MMSI_DTYPE),
            cell_id=np.asarray(cell_id, dtype=CELL_DTYPE),
        )
    if path.exists():
        path.unlink()
    tmp.replace(path)


def load_csr(path: Path) -> tuple[csr_matrix, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        matrix = csr_matrix(
            (payload["data"], payload["indices"], payload["indptr"]),
            shape=tuple(int(x) for x in payload["shape"]),
        )
        mmsi = np.asarray(payload["mmsi"], dtype=MMSI_DTYPE)
        cell_id = np.asarray(payload["cell_id"], dtype=CELL_DTYPE)
    return matrix, mmsi, cell_id
