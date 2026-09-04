"""CLI: ``python -m src.eval.report`` → train/test split + protocol report.

Does not fit a recommender. B3/B4 plug predictions into ``src.eval.harness``.
This stage writes the split, counts cold-start vessels, and leak-checks that
train history scores zero on the new-grounds protocol.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.clean.report import utcnow, write_report
from src.eval.harness import evaluate
from src.eval.split import (
    build_split,
    history_rankings,
    load_cold_start_relevant,
    load_new_ground_relevant,
)
from src.features.policy import DEFAULT_KS
from src.features.sparse_matrix import load_csr
from src.paths import REPORTS_DIR
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the temporal split and write the B2 protocol report."
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def leak_check(
    train_path: Path,
    test_path: Path,
    catalog_size: int,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict:
    train, mmsi, cell_id = load_csr(train_path)
    relevant = load_new_ground_relevant(test_path)
    predictions = history_rankings(train, mmsi, cell_id)
    result = evaluate(predictions, relevant, catalog_size, ks)
    precisions = [result["by_k"][str(k)]["precision"] for k in ks]
    result["leak_free"] = all(p in (0.0, None) for p in precisions)
    return result


def build_report(*, force: bool = False, memory=None) -> dict:
    split = build_split(force=force)
    if memory:
        memory.sample()
    test_path = Path(split["test_relevant"])
    train_path = Path(split["train"])
    cold = load_cold_start_relevant(test_path)
    leak = leak_check(train_path, test_path, int(split["n_items"]))
    if memory:
        memory.sample()
    if not leak["leak_free"]:
        raise RuntimeError(
            "train history leaked into new-grounds relevance; split is wrong"
        )
    LOG.info(
        "split test_start=%s train_vessels=%s cold_start=%s warm_new_grounds=%s",
        split["test_start"],
        f"{split['train_vessels']:,}",
        f"{split['cold_start_vessels']:,}",
        f"{split['warm_with_new_grounds']:,}",
    )
    return {
        "split": split,
        "n_cold_start_vessels": len(cold),
        "n_cold_start_cells": sum(len(items) for items in cold.values()),
        "history_leak_check": leak,
        "note": (
            "Ranking metrics for models are not in this report. "
            "B3 baselines and B4 ALS call src.eval.harness.evaluate."
        ),
    }


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    result = build_report(force=args.force, memory=memory)
    result.update(
        {
            "stage": "b2",
            "started_at": started,
            "finished_at": utcnow(),
            "peak_rss_bytes": memory.sample(),
            "peak_rss_mb": round(memory.peak_mb, 2),
        }
    )
    path = write_report(result, REPORTS_DIR / "b2_eval.json")
    LOG.info("B2 complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return result


if __name__ == "__main__":
    main()
