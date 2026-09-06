"""CLI: ``python -m src.models.baselines`` → popularity vs popularity-by-gear.

Both rank cells by train fishing hours. Seen train cells are dropped
because B2 relevance is new grounds. Missing gear falls back to global.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
from scipy.sparse import csr_matrix

from src.clean.report import utcnow, write_report
from src.eval.harness import evaluate
from src.eval.split import load_new_ground_relevant
from src.features.policy import DEFAULT_KS, TEST_START
from src.features.sparse_matrix import load_csr
from src.paths import REPORTS_DIR, TRAIN_MATRIX_PATH, TEST_RELEVANT_PATH, VESSELS_PATH
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)

UNKNOWN_GEAR = ""
GEAR_COLUMN = "vessel_class_gfw"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score popularity baselines on the B2 new-grounds split."
    )
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_KS))
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def item_hours(matrix: csr_matrix) -> np.ndarray:
    return np.asarray(matrix.sum(axis=0), dtype=np.float64).ravel()


def rank_by_hours(hours: np.ndarray, cell_id: np.ndarray) -> list[str]:
    order = np.argsort(-hours, kind="stable")
    return [str(cell_id[i]) for i in order if hours[i] > 0]


def seen_cells(matrix: csr_matrix, row: int, cell_id: np.ndarray) -> set[str]:
    start = int(matrix.indptr[row])
    end = int(matrix.indptr[row + 1])
    if start == end:
        return set()
    return {str(cell_id[i]) for i in matrix.indices[start:end]}


def drop_seen(ranked: list[str], seen: set[str], k: int) -> list[str]:
    out: list[str] = []
    for cell in ranked:
        if cell in seen:
            continue
        out.append(cell)
        if len(out) >= k:
            break
    return out


def load_latest_gear(vessels_path: Path, mmsi: np.ndarray) -> np.ndarray:
    """Latest-year ``vessel_class_gfw`` per MMSI, aligned to ``mmsi``."""
    gear = np.full(len(mmsi), UNKNOWN_GEAR, dtype=object)
    if not vessels_path.exists():
        raise FileNotFoundError(
            f"Missing silver vessels ({vessels_path}). Run python -m src.clean.build first."
        )
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        rows = con.execute(
            f"""
            SELECT mmsi, {GEAR_COLUMN}
            FROM (
              SELECT
                trim(CAST(mmsi AS VARCHAR)) AS mmsi,
                {GEAR_COLUMN},
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
    lookup = {
        str(user): ("" if klass is None else str(klass))
        for user, klass in rows
    }
    for i, user in enumerate(mmsi.tolist()):
        value = lookup.get(str(user), UNKNOWN_GEAR)
        gear[i] = value if value else UNKNOWN_GEAR
    return gear


def popularity_catalog(matrix: csr_matrix, cell_id: np.ndarray) -> list[str]:
    return rank_by_hours(item_hours(matrix), cell_id)


def popularity_by_gear_catalogs(
    matrix: csr_matrix,
    cell_id: np.ndarray,
    gear: np.ndarray,
) -> dict[str, list[str]]:
    catalogs: dict[str, list[str]] = {}
    for klass in dict.fromkeys(gear.tolist()):
        if klass == UNKNOWN_GEAR:
            continue
        mask = gear == klass
        catalogs[str(klass)] = rank_by_hours(item_hours(matrix[mask]), cell_id)
    return catalogs


def predict_popularity(
    matrix: csr_matrix,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    k: int,
) -> dict[str, list[str]]:
    catalog = popularity_catalog(matrix, cell_id)
    return {
        str(mmsi[row]): drop_seen(catalog, seen_cells(matrix, row, cell_id), k)
        for row in range(matrix.shape[0])
    }


def predict_popularity_by_gear(
    matrix: csr_matrix,
    mmsi: np.ndarray,
    cell_id: np.ndarray,
    gear: np.ndarray,
    k: int,
    *,
    global_catalog: list[str] | None = None,
    gear_catalogs: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    global_catalog = global_catalog or popularity_catalog(matrix, cell_id)
    gear_catalogs = gear_catalogs or popularity_by_gear_catalogs(
        matrix, cell_id, gear
    )
    predictions: dict[str, list[str]] = {}
    for row in range(matrix.shape[0]):
        klass = str(gear[row])
        catalog = gear_catalogs.get(klass) or global_catalog
        predictions[str(mmsi[row])] = drop_seen(
            catalog, seen_cells(matrix, row, cell_id), k
        )
    return predictions


def evaluate_baselines(
    *,
    train_path: Path | None = None,
    test_path: Path | None = None,
    vessels_path: Path | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
    memory: PeakMemory | None = None,
) -> dict:
    train_path = train_path or TRAIN_MATRIX_PATH
    test_path = test_path or TEST_RELEVANT_PATH
    vessels_path = vessels_path or VESSELS_PATH
    if not train_path.exists() or not test_path.exists():
        raise FileNotFoundError(
            "Missing train/test split. Run python -m src.eval.report first."
        )

    train, mmsi, cell_id = load_csr(train_path)
    if memory:
        memory.sample()
    relevant = load_new_ground_relevant(test_path)
    gear = load_latest_gear(vessels_path, mmsi)
    if memory:
        memory.sample()

    rank_k = max(ks)
    catalog_size = int(len(cell_id))
    global_catalog = popularity_catalog(train, cell_id)
    gear_catalogs = popularity_by_gear_catalogs(train, cell_id, gear)

    pop = predict_popularity(train, mmsi, cell_id, rank_k)
    by_gear = predict_popularity_by_gear(
        train,
        mmsi,
        cell_id,
        gear,
        rank_k,
        global_catalog=global_catalog,
        gear_catalogs=gear_catalogs,
    )
    if memory:
        memory.sample()

    n_fallback = int(sum(1 for g in gear.tolist() if g == UNKNOWN_GEAR))
    gear_counts = Counter(str(g) if g else "(unknown)" for g in gear.tolist())
    popularity = evaluate(pop, relevant, catalog_size, ks)
    popularity_by_gear = evaluate(by_gear, relevant, catalog_size, ks)
    LOG.info(
        "popularity P@10=%s  gear P@10=%s  fallback_global=%s/%s",
        popularity["by_k"].get("10", {}).get("precision"),
        popularity_by_gear["by_k"].get("10", {}).get("precision"),
        n_fallback,
        len(mmsi),
    )
    return {
        "protocol": "new_grounds",
        "test_start": TEST_START.isoformat(),
        "n_users": int(len(mmsi)),
        "n_items": catalog_size,
        "rank_k": rank_k,
        "ks": list(ks),
        "n_fallback_global": n_fallback,
        "n_with_gear": int(len(mmsi) - n_fallback),
        "gear_counts": dict(sorted(gear_counts.items())),
        "n_gear_catalogs": len(gear_catalogs),
        "models": {
            "popularity": popularity,
            "popularity_by_gear": popularity_by_gear,
        },
        "note": (
            "Rank by train fishing hours; drop cells the vessel already fished. "
            "Gear is latest-year vessel_class_gfw. Cold-start is out of scope (B5)."
        ),
    }


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    ks = tuple(args.k)
    result = evaluate_baselines(ks=ks, memory=memory)
    result.update(
        {
            "stage": "b3",
            "started_at": started,
            "finished_at": utcnow(),
            "peak_rss_bytes": memory.sample(),
            "peak_rss_mb": round(memory.peak_mb, 2),
        }
    )
    path = write_report(result, REPORTS_DIR / "b3_baselines.json")
    LOG.info("B3 complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return result


if __name__ == "__main__":
    main()
