"""CLI: ``python -m src.models.train`` → ALS + content fold-in, scored on B2.

Tune on Q3 2024 new-grounds (not Q4). Refit on the full train window.
Warm vessels get ALS; cold-start vessels get content → factor fold-in.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from src.clean.report import utcnow, write_report
from src.eval.harness import evaluate
from src.eval.split import (
    load_cold_start_relevant,
    load_new_ground_relevant,
    new_ground_relevant_window,
    train_pairs,
)
from src.features.policy import DEFAULT_KS, TEST_START, VAL_START
from src.features.sparse_matrix import load_csr, pairs_to_csr
from src.models.als import (
    DEFAULT_ALPHA,
    DEFAULT_FACTORS,
    DEFAULT_ITERATIONS,
    DEFAULT_REGULARIZATION,
    fit_als,
    recommend_als,
    save_factors,
)
from src.models.baselines import load_latest_gear, predict_popularity_by_gear
from src.models.content import (
    encode_vessels,
    fit_foldin,
    hybrid_rankings,
    load_latest_vessel_table,
    predict_foldin,
    save_foldin,
)
from src.paths import (
    ALS_FACTORS_PATH,
    CONTENT_FOLDIN_PATH,
    FISHING_EVENTS_PATH,
    REPORTS_DIR,
    TEST_RELEVANT_PATH,
    TRAIN_MATRIX_PATH,
    VESSELS_PATH,
)
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)

ALS_GRID = (
    {
        "factors": 32,
        "regularization": 0.1,
        "alpha": 10.0,
        "iterations": DEFAULT_ITERATIONS,
    },
    {
        "factors": 32,
        "regularization": 0.1,
        "alpha": 40.0,
        "iterations": DEFAULT_ITERATIONS,
    },
    {
        "factors": 64,
        "regularization": 0.1,
        "alpha": 10.0,
        "iterations": DEFAULT_ITERATIONS,
    },
    {
        "factors": 64,
        "regularization": 0.1,
        "alpha": 40.0,
        "iterations": DEFAULT_ITERATIONS,
    },
    {
        "factors": 64,
        "regularization": 0.01,
        "alpha": 20.0,
        "iterations": DEFAULT_ITERATIONS,
    },
    {
        "factors": 64,
        "regularization": 1.0,
        "alpha": 20.0,
        "iterations": DEFAULT_ITERATIONS,
    },
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit implicit ALS and a content fold-in; score on B2 protocols."
    )
    parser.add_argument("--skip-tune", action="store_true")
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_KS))
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _matrix_before(events_path: Path, mmsi, cell_id, before):
    pair_mmsi, pair_cell, hours = train_pairs(events_path, before=before)
    if len(pair_mmsi) == 0:
        raise RuntimeError(f"no events before {before.isoformat()} in {events_path}")
    return pairs_to_csr(pair_mmsi, pair_cell, hours, mmsi, cell_id)


def _precision10(result: dict) -> float:
    value = result.get("by_k", {}).get("10", {}).get("precision")
    return float(value) if value is not None else -1.0


def tune_als(
    events_path: Path,
    mmsi,
    cell_id,
    catalog_size: int,
    ks: tuple[int, ...],
) -> tuple[dict, list[dict]]:
    fit_matrix = _matrix_before(events_path, mmsi, cell_id, VAL_START)
    relevant = new_ground_relevant_window(events_path, VAL_START, TEST_START)
    LOG.info(
        "tune window %s..%s val_users=%s",
        VAL_START.isoformat(),
        TEST_START.isoformat(),
        f"{len(relevant):,}",
    )
    trials: list[dict] = []
    best_params = dict(ALS_GRID[0])
    best_score = -1.0
    rank_k = max(ks)
    for params in ALS_GRID:
        users, items = fit_als(fit_matrix, **params)
        predictions = recommend_als(users, items, fit_matrix, mmsi, cell_id, rank_k)
        metrics = evaluate(predictions, relevant, catalog_size, ks)
        score = _precision10(metrics)
        trial = {"params": params, "val": metrics}
        trials.append(trial)
        LOG.info(
            "val factors=%s alpha=%s reg=%s P@10=%s",
            params["factors"],
            params["alpha"],
            params["regularization"],
            score,
        )
        if score > best_score:
            best_score = score
            best_params = dict(params)
    return best_params, trials


def train_and_evaluate(
    *,
    train_path: Path | None = None,
    test_path: Path | None = None,
    events_path: Path | None = None,
    vessels_path: Path | None = None,
    factors_path: Path | None = None,
    foldin_path: Path | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
    skip_tune: bool = False,
    memory=None,
) -> dict:
    train_path = train_path or TRAIN_MATRIX_PATH
    test_path = test_path or TEST_RELEVANT_PATH
    events_path = events_path or FISHING_EVENTS_PATH
    vessels_path = vessels_path or VESSELS_PATH
    factors_path = factors_path or ALS_FACTORS_PATH
    foldin_path = foldin_path or CONTENT_FOLDIN_PATH
    if not train_path.exists() or not test_path.exists():
        raise FileNotFoundError(
            "Missing train/test split. Run python -m src.eval.report first."
        )

    train, mmsi, cell_id = load_csr(train_path)
    if memory:
        memory.sample()
    catalog_size = int(len(cell_id))
    rank_k = max(ks)
    new_grounds = load_new_ground_relevant(test_path)
    cold = load_cold_start_relevant(test_path)

    trials: list[dict] = []
    if skip_tune:
        params = {
            "factors": DEFAULT_FACTORS,
            "regularization": DEFAULT_REGULARIZATION,
            "alpha": DEFAULT_ALPHA,
            "iterations": DEFAULT_ITERATIONS,
        }
    else:
        params, trials = tune_als(
            events_path, mmsi, cell_id, catalog_size, ks
        )
    if memory:
        memory.sample()

    LOG.info("fitting ALS on full train %s", params)
    user_factors, item_factors = fit_als(train, **params)
    save_factors(
        factors_path,
        user_factors,
        item_factors,
        mmsi,
        cell_id,
        {**params, "seed": 0},
    )
    if memory:
        memory.sample()

    als_rankings = recommend_als(
        user_factors, item_factors, train, mmsi, cell_id, rank_k
    )
    als_warm = evaluate(als_rankings, new_grounds, catalog_size, ks)

    table = load_latest_vessel_table(vessels_path)
    warm_mask = np.diff(train.indptr) > 0
    features, encoder = encode_vessels(mmsi, table)
    weights = fit_foldin(features, user_factors, warm_mask)
    save_foldin(foldin_path, weights, encoder, ridge=1.0)
    content_rankings = predict_foldin(
        weights, features, item_factors, train, mmsi, cell_id, rank_k
    )
    gear = load_latest_gear(vessels_path, mmsi)
    gear_rankings = predict_popularity_by_gear(train, mmsi, cell_id, gear, rank_k)
    hybrid = hybrid_rankings(als_rankings, content_rankings, train, mmsi)

    content_warm = evaluate(content_rankings, new_grounds, catalog_size, ks)
    content_cold = evaluate(content_rankings, cold, catalog_size, ks)
    gear_cold = evaluate(gear_rankings, cold, catalog_size, ks)
    hybrid_warm = evaluate(hybrid, new_grounds, catalog_size, ks)
    hybrid_cold = evaluate(hybrid, cold, catalog_size, ks)
    als_cold = evaluate(als_rankings, cold, catalog_size, ks)

    LOG.info(
        "ALS P@10=%s  gear-cold P@10=%s  content-cold P@10=%s",
        als_warm["by_k"].get("10", {}).get("precision"),
        gear_cold["by_k"].get("10", {}).get("precision"),
        content_cold["by_k"].get("10", {}).get("precision"),
    )
    return {
        "protocol": {
            "warm": "new_grounds",
            "cold": "cold_start",
            "val_start": VAL_START.isoformat(),
            "test_start": TEST_START.isoformat(),
        },
        "n_users": int(len(mmsi)),
        "n_items": catalog_size,
        "n_warm": int(warm_mask.sum()),
        "n_cold_eval": hybrid_cold["n_eval_users"],
        "als_params": params,
        "tune": {"skipped": skip_tune or not trials, "trials": trials},
        "models": {
            "als_warm": als_warm,
            "als_cold": als_cold,
            "content_warm": content_warm,
            "content_cold": content_cold,
            "popularity_by_gear_cold": gear_cold,
            "hybrid_warm": hybrid_warm,
            "hybrid_cold": hybrid_cold,
        },
        "outputs": {
            "als_factors": str(factors_path),
            "content_foldin": str(foldin_path),
        },
        "note": (
            "ALS is Hu-Koren implicit CF; hours are log-confidence. "
            "Hyperparameters chosen on Q3 2024 new-grounds, then refit through Q3. "
            "Cold-start uses ridge fold-in from gear/flag/size onto user factors. "
            "Hybrid is ALS for warm vessels and fold-in for Q4-first vessels."
        ),
    }


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    result = train_and_evaluate(
        ks=tuple(args.k), skip_tune=args.skip_tune, memory=memory
    )
    result.update(
        {
            "stage": "b4_b5",
            "started_at": started,
            "finished_at": utcnow(),
            "peak_rss_bytes": memory.sample(),
            "peak_rss_mb": round(memory.peak_mb, 2),
        }
    )
    path = write_report(result, REPORTS_DIR / "b4_b5_als.json")
    LOG.info("B4/B5 complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return result


if __name__ == "__main__":
    main()
