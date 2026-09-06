"""Temporal train/test split: 2023–Q3 2024 train, Q4 2024 test."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.parquet as pq

from src.features.policy import TEST_START
from src.features.sparse_matrix import load_csr, pairs_to_csr, save_csr
from src.parquet_io import copy_query_to_parquet
from src.paths import (
    FISHING_EVENTS_PATH,
    MATRIX_PATH,
    TEST_RELEVANT_PATH,
    TRAIN_MATRIX_PATH,
)

TEST_COLUMNS = (
    "mmsi",
    "cell_id",
    "fishing_hours",
    "is_new_ground",
    "is_cold_start",
)


def _date_param() -> str:
    return TEST_START.isoformat()


def write_test_relevant(events_path: Path, dest: Path) -> int:
    cutoff = _date_param()
    sql = """
    WITH train AS (
      SELECT mmsi, cell_id
      FROM read_parquet(?)
      WHERE date < CAST(? AS DATE)
      GROUP BY 1, 2
    ),
    train_users AS (
      SELECT DISTINCT mmsi FROM train
    ),
    test AS (
      SELECT
        mmsi,
        cell_id,
        sum(fishing_hours)::DOUBLE AS fishing_hours
      FROM read_parquet(?)
      WHERE date >= CAST(? AS DATE)
      GROUP BY 1, 2
    )
    SELECT
      t.mmsi,
      t.cell_id,
      t.fishing_hours,
      (tr.cell_id IS NULL) AS is_new_ground,
      (tu.mmsi IS NULL) AS is_cold_start
    FROM test t
    LEFT JOIN train tr
      ON t.mmsi = tr.mmsi AND t.cell_id = tr.cell_id
    LEFT JOIN train_users tu
      ON t.mmsi = tu.mmsi
    """
    events = events_path.as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        copy_query_to_parquet(
            con, sql, dest, [events, cutoff, events, cutoff]
        )
        n = con.execute(
            "SELECT count(*) FROM read_parquet(?)", [dest.as_posix()]
        ).fetchone()[0]
    finally:
        con.close()
    return int(n)


def train_pairs(
    events_path: Path, before: date | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cutoff = (before or TEST_START).isoformat()
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        result = con.execute(
            """
            SELECT
              mmsi,
              cell_id,
              sum(fishing_hours)::DOUBLE AS fishing_hours
            FROM read_parquet(?)
            WHERE date < CAST(? AS DATE)
            GROUP BY 1, 2
            """,
            [events_path.as_posix(), cutoff],
        ).fetchnumpy()
    finally:
        con.close()
    if len(result["mmsi"]) == 0:
        return (
            np.array([], dtype="U16"),
            np.array([], dtype="U32"),
            np.array([], dtype=np.float64),
        )
    return result["mmsi"], result["cell_id"], result["fishing_hours"]


def protocol_stats(test_path: Path, train_users: int, train_nnz: int) -> dict:
    con = duckdb.connect()
    try:
        row = con.execute(
            """
            SELECT
              count(*) AS test_pairs,
              count(*) FILTER (WHERE is_new_ground) AS new_ground_pairs,
              count(*) FILTER (WHERE NOT is_new_ground) AS revisit_pairs,
              count(DISTINCT mmsi) AS test_vessels,
              count(DISTINCT mmsi) FILTER (WHERE is_cold_start) AS cold_start_vessels,
              count(DISTINCT mmsi) FILTER (WHERE NOT is_cold_start) AS warm_test_vessels,
              count(DISTINCT mmsi) FILTER (
                WHERE is_new_ground AND NOT is_cold_start
              ) AS warm_with_new_grounds,
              count(DISTINCT cell_id) AS test_cells
            FROM read_parquet(?)
            """,
            [test_path.as_posix()],
        ).fetchone()
    finally:
        con.close()
    keys = (
        "test_pairs",
        "new_ground_pairs",
        "revisit_pairs",
        "test_vessels",
        "cold_start_vessels",
        "warm_test_vessels",
        "warm_with_new_grounds",
        "test_cells",
    )
    stats = {key: int(value) for key, value in zip(keys, row, strict=True)}
    stats["train_vessels"] = train_users
    stats["train_nnz"] = train_nnz
    stats["test_start"] = _date_param()
    return stats


def new_ground_relevant_window(
    events_path: Path, history_end: date, window_end: date
) -> dict[str, set[str]]:
    """Warm vessels → cells first fished in ``[history_end, window_end)``."""
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        rows = con.execute(
            """
            WITH history AS (
              SELECT mmsi, cell_id
              FROM read_parquet(?)
              WHERE date < CAST(? AS DATE)
              GROUP BY 1, 2
            ),
            history_users AS (
              SELECT DISTINCT mmsi FROM history
            ),
            holdout AS (
              SELECT mmsi, cell_id
              FROM read_parquet(?)
              WHERE date >= CAST(? AS DATE) AND date < CAST(? AS DATE)
              GROUP BY 1, 2
            )
            SELECT w.mmsi, w.cell_id
            FROM holdout w
            LEFT JOIN history h
              ON w.mmsi = h.mmsi AND w.cell_id = h.cell_id
            LEFT JOIN history_users u
              ON w.mmsi = u.mmsi
            WHERE h.cell_id IS NULL AND u.mmsi IS NOT NULL
            """,
            [
                events_path.as_posix(),
                history_end.isoformat(),
                events_path.as_posix(),
                history_end.isoformat(),
                window_end.isoformat(),
            ],
        ).fetchall()
    finally:
        con.close()
    relevant: dict[str, set[str]] = {}
    for user, item in rows:
        relevant.setdefault(str(user), set()).add(str(item))
    return relevant


def load_new_ground_relevant(test_path: Path) -> dict[str, set[str]]:
    """Warm vessels → cells fished in Q4 that they did not fish in train."""
    table = pq.read_table(
        test_path,
        columns=["mmsi", "cell_id", "is_new_ground", "is_cold_start"],
    )
    relevant: dict[str, set[str]] = {}
    mmsi = table.column("mmsi").to_pylist()
    cell_id = table.column("cell_id").to_pylist()
    is_new = table.column("is_new_ground").to_pylist()
    is_cold = table.column("is_cold_start").to_pylist()
    for user, item, new_ground, cold in zip(mmsi, cell_id, is_new, is_cold, strict=True):
        if cold or not new_ground:
            continue
        relevant.setdefault(str(user), set()).add(str(item))
    return relevant


def load_cold_start_relevant(test_path: Path) -> dict[str, set[str]]:
    table = pq.read_table(
        test_path,
        columns=["mmsi", "cell_id", "is_cold_start"],
    )
    relevant: dict[str, set[str]] = {}
    mmsi = table.column("mmsi").to_pylist()
    cell_id = table.column("cell_id").to_pylist()
    is_cold = table.column("is_cold_start").to_pylist()
    for user, item, cold in zip(mmsi, cell_id, is_cold, strict=True):
        if not cold:
            continue
        relevant.setdefault(str(user), set()).add(str(item))
    return relevant


def history_rankings(matrix, mmsi: np.ndarray, cell_id: np.ndarray) -> dict[str, list[str]]:
    """Each vessel's train cells, strongest fishing hours first."""
    rankings: dict[str, list[str]] = {}
    for row in range(matrix.shape[0]):
        start = int(matrix.indptr[row])
        end = int(matrix.indptr[row + 1])
        if start == end:
            continue
        idx = matrix.indices[start:end]
        hours = matrix.data[start:end]
        order = np.argsort(-hours, kind="stable")
        rankings[str(mmsi[row])] = [str(cell_id[i]) for i in idx[order]]
    return rankings


def build_split(
    *,
    events_path: Path | None = None,
    matrix_path: Path | None = None,
    train_path: Path | None = None,
    test_path: Path | None = None,
    force: bool = False,
) -> dict:
    events_path = events_path or FISHING_EVENTS_PATH
    matrix_path = matrix_path or MATRIX_PATH
    train_path = train_path or TRAIN_MATRIX_PATH
    test_path = test_path or TEST_RELEVANT_PATH

    if not events_path.exists():
        raise FileNotFoundError(
            f"Missing fishing events ({events_path}). Run python -m src.features.matrix first."
        )
    if not matrix_path.exists():
        raise FileNotFoundError(
            f"Missing matrix ({matrix_path}). Run python -m src.features.matrix first."
        )

    if train_path.exists() and test_path.exists() and not force:
        _, mmsi, cell_id = load_csr(matrix_path)
        train, _, _ = load_csr(train_path)
        stats = protocol_stats(
            test_path, int((np.diff(train.indptr) > 0).sum()), int(train.nnz)
        )
        stats.update(
            {
                "skipped": True,
                "train": str(train_path),
                "test_relevant": str(test_path),
                "n_users": int(len(mmsi)),
                "n_items": int(len(cell_id)),
            }
        )
        return stats

    _, mmsi, cell_id = load_csr(matrix_path)
    pair_mmsi, pair_cell, hours = train_pairs(events_path)
    train = pairs_to_csr(pair_mmsi, pair_cell, hours, mmsi, cell_id)
    save_csr(train_path, train, mmsi, cell_id)
    write_test_relevant(events_path, test_path)

    train_users = int((np.diff(train.indptr) > 0).sum())
    stats = protocol_stats(test_path, train_users, int(train.nnz))
    stats.update(
        {
            "skipped": False,
            "train": str(train_path),
            "test_relevant": str(test_path),
            "n_users": int(len(mmsi)),
            "n_items": int(len(cell_id)),
            "train_sparsity": (
                1.0 - train.nnz / (len(mmsi) * len(cell_id))
                if len(mmsi) and len(cell_id)
                else 1.0
            ),
        }
    )
    return stats
