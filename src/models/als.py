"""Hu, Koren & Volinsky (2008) implicit ALS.

Fishing hours are confidence, not ratings. Unobserved cells stay preference 0
with confidence 1. Rankings drop cells the vessel already fished (B2 new grounds).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from src.features.sparse_matrix import CELL_DTYPE, MMSI_DTYPE
from src.paths import ALS_FACTORS_PATH

DEFAULT_FACTORS = 64
DEFAULT_REGULARIZATION = 0.1
DEFAULT_ALPHA = 20.0
DEFAULT_ITERATIONS = 12
DEFAULT_SEED = 0


def confidence_matrix(matrix: csr_matrix, alpha: float) -> csr_matrix:
    conf = matrix.copy()
    conf.data = 1.0 + alpha * np.log1p(np.maximum(conf.data, 0.0))
    return conf


def _least_squares(
    gram: np.ndarray,
    factors: np.ndarray,
    indices: np.ndarray,
    conf: np.ndarray,
    regularization: float,
) -> np.ndarray:
    """Solve for one user or item given the opposite factor matrix."""
    n_factors = gram.shape[0]
    observed = factors[indices]
    delta = conf - 1.0
    a = gram + observed.T * delta @ observed
    a.flat[:: n_factors + 1] += regularization
    b = observed.T @ conf
    return np.linalg.solve(a, b)


def fit_als(
    matrix: csr_matrix,
    *,
    factors: int = DEFAULT_FACTORS,
    regularization: float = DEFAULT_REGULARIZATION,
    alpha: float = DEFAULT_ALPHA,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> tuple[np.ndarray, np.ndarray]:
    n_users, n_items = matrix.shape
    rank = max(1, min(int(factors), n_users, n_items))
    rng = np.random.default_rng(seed)
    users = rng.normal(0.0, 0.01, size=(n_users, rank))
    items = rng.normal(0.0, 0.01, size=(n_items, rank))

    conf = confidence_matrix(matrix, alpha)
    conf_t = conf.T.tocsr()
    user_nnz = np.diff(conf.indptr)
    item_nnz = np.diff(conf_t.indptr)
    users[user_nnz == 0] = 0.0
    items[item_nnz == 0] = 0.0

    for _ in range(iterations):
        gram = items.T @ items
        for u in range(n_users):
            start = int(conf.indptr[u])
            end = int(conf.indptr[u + 1])
            if start == end:
                continue
            users[u] = _least_squares(
                gram,
                items,
                conf.indices[start:end],
                conf.data[start:end],
                regularization,
            )
        gram = users.T @ users
        for i in range(n_items):
            start = int(conf_t.indptr[i])
            end = int(conf_t.indptr[i + 1])
            if start == end:
                continue
            items[i] = _least_squares(
                gram,
                users,
                conf_t.indices[start:end],
                conf_t.data[start:end],
                regularization,
            )
        users[user_nnz == 0] = 0.0
        items[item_nnz == 0] = 0.0

    return users, items


def recommend_als(
    user_factors: np.ndarray,
    item_factors: np.ndarray,
    matrix: csr_matrix,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    k: int,
) -> dict[str, list[str]]:
    scores = user_factors @ item_factors.T
    coo = matrix.tocoo()
    scores[coo.row, coo.col] = -np.inf
    n_users, n_items = scores.shape
    k_eff = min(max(k, 1), n_items)
    predictions: dict[str, list[str]] = {}
    for row in range(n_users):
        ranked_idx = np.argpartition(scores[row], -k_eff)[-k_eff:]
        ranked_idx = ranked_idx[np.argsort(-scores[row, ranked_idx], kind="stable")]
        ranked = [
            str(cell_id[i]) for i in ranked_idx if np.isfinite(scores[row, i])
        ]
        predictions[str(mmsi[row])] = ranked[:k]
    return predictions


def save_factors(
    path: Path,
    user_factors: np.ndarray,
    item_factors: np.ndarray,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    params: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    if tmp.exists():
        tmp.unlink()
    payload = {
        "user_factors": np.asarray(user_factors, dtype=np.float64),
        "item_factors": np.asarray(item_factors, dtype=np.float64),
        "mmsi": np.asarray(mmsi, dtype=MMSI_DTYPE),
        "cell_id": np.asarray(cell_id, dtype=CELL_DTYPE),
    }
    for key, value in params.items():
        payload[key] = np.asarray(value)
    with tmp.open("wb") as handle:
        np.savez_compressed(handle, **payload)
    if path.exists():
        path.unlink()
    tmp.replace(path)


def load_factors(
    path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    path = path or ALS_FACTORS_PATH
    with np.load(path, allow_pickle=False) as payload:
        users = np.asarray(payload["user_factors"], dtype=np.float64)
        items = np.asarray(payload["item_factors"], dtype=np.float64)
        mmsi = np.asarray(payload["mmsi"], dtype=MMSI_DTYPE)
        cell_id = np.asarray(payload["cell_id"], dtype=CELL_DTYPE)
        params = {
            key: payload[key].item() if payload[key].shape == () else payload[key]
            for key in payload.files
            if key not in {"user_factors", "item_factors", "mmsi", "cell_id"}
        }
    return users, items, mmsi, cell_id, params
