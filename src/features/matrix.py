"""CLI: ``python -m src.features.matrix`` → fishing events + ``matrix.npz``."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
import numpy as np

from src.clean.report import utcnow, write_report
from src.features.events import extract_events
from src.features.policy import DEFAULT_SCOPE, MIN_FISHING_RATIO, SCOPES
from src.features.sparse_matrix import load_csr, pairs_to_csr, save_csr
from src.paths import FISHING_EVENTS_PATH, MATRIX_PATH, REPORTS_DIR
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the gold vessel×cell matrix (transit filtered)."
    )
    parser.add_argument("--scope", choices=SCOPES, default=DEFAULT_SCOPE)
    parser.add_argument("--min-ratio", type=float, default=MIN_FISHING_RATIO)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _aggregate_pairs(events_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
            GROUP BY 1, 2
            """,
            [events_path.as_posix()],
        ).fetchnumpy()
    finally:
        con.close()
    return result["mmsi"], result["cell_id"], result["fishing_hours"]


def build_csr_from_events(events_path: Path):
    mmsi, cell_id, hours = _aggregate_pairs(events_path)
    if len(mmsi) == 0:
        raise RuntimeError(f"no fishing events in {events_path}")
    row_keys = np.unique(mmsi)
    col_keys = np.unique(cell_id)
    matrix = pairs_to_csr(mmsi, cell_id, hours, row_keys, col_keys)
    return matrix, row_keys, col_keys


def sparsity(n_users: int, n_items: int, nnz: int) -> float:
    denom = n_users * n_items
    if denom == 0:
        return 1.0
    return 1.0 - (nnz / denom)


def build(
    *,
    scope: str = DEFAULT_SCOPE,
    min_ratio: float = MIN_FISHING_RATIO,
    force: bool = False,
    memory: PeakMemory | None = None,
    events_path: Path | None = None,
    matrix_path: Path | None = None,
    silver: str | None = None,
    cells_path: Path | None = None,
) -> dict:
    events_path = events_path or FISHING_EVENTS_PATH
    matrix_path = matrix_path or MATRIX_PATH
    if matrix_path.exists() and events_path.exists() and not force:
        LOG.info("matrix already present (%s), skipping", matrix_path)
        matrix, mmsi, cell_id = load_csr(matrix_path)
        return {
            "skipped": True,
            "output": str(matrix_path),
            "events": str(events_path),
            "n_users": int(matrix.shape[0]),
            "n_items": int(matrix.shape[1]),
            "nnz": int(matrix.nnz),
        }

    LOG.info("extracting fishing events scope=%s min_ratio=%s", scope, min_ratio)
    events = extract_events(
        events_path,
        scope=scope,
        min_ratio=min_ratio,
        silver=silver,
        cells_path=cells_path,
    )
    if memory:
        memory.sample()
    LOG.info(
        "events=%s (dropped %s transit/zero of %s in-scope rows)",
        f"{events['event_rows']:,}",
        f"{events['transit_or_zero_rows']:,}",
        f"{events['in_scope_rows']:,}",
    )

    matrix, mmsi, cell_id = build_csr_from_events(events_path)
    if memory:
        memory.sample()
    save_csr(matrix_path, matrix, mmsi, cell_id)
    LOG.info(
        "wrote %s users=%s items=%s nnz=%s",
        matrix_path,
        f"{matrix.shape[0]:,}",
        f"{matrix.shape[1]:,}",
        f"{matrix.nnz:,}",
    )

    n_users, n_items = (int(matrix.shape[0]), int(matrix.shape[1]))
    nnz = int(matrix.nnz)
    return {
        "skipped": False,
        "scope": scope,
        "min_fishing_ratio": min_ratio,
        "events": events,
        "output": str(matrix_path),
        "n_users": n_users,
        "n_items": n_items,
        "nnz": nnz,
        "sparsity": sparsity(n_users, n_items, nnz),
        "fishing_hours": float(matrix.data.sum()),
    }


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    result = build(
        scope=args.scope,
        min_ratio=args.min_ratio,
        force=args.force,
        memory=memory,
    )
    result.update(
        {
            "stage": "b1",
            "started_at": started,
            "finished_at": utcnow(),
            "peak_rss_bytes": memory.sample(),
            "peak_rss_mb": round(memory.peak_mb, 2),
        }
    )
    path = write_report(result, REPORTS_DIR / "b1_matrix.json")
    LOG.info("B1 complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return result


if __name__ == "__main__":
    main()
