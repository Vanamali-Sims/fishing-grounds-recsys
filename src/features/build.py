"""CLI: ``python -m src.features.build`` → ``data/processed/cells.parquet``."""

from __future__ import annotations

import argparse
import logging

import pyarrow as pa
import pyarrow.parquet as pq

from src.clean.report import utcnow, write_report
from src.features.depth import attach_depth
from src.features.eez import attach_eez
from src.features.extract import extract_cells
from src.features.mpa import attach_mpa, find_mpa_source
from src.features.ports import attach_port_distance
from src.features.schema import AUS_EEZ_SOVEREIGN, CELL_COLUMNS, NULL_POLICY
from src.paths import CELLS_PATH, REPORTS_DIR, WDPA_DIR
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the gold cell dimension (depth, EEZ, port distance, MPA)."
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--refresh-mpa",
        action="store_true",
        help="Re-join MPA polygons onto the existing cells.parquet.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _write_cells(df) -> None:
    missing = [c for c in CELL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"cells missing columns: {missing}")
    table = pa.Table.from_pandas(df.loc[:, list(CELL_COLUMNS)], preserve_index=False)
    CELLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CELLS_PATH.with_suffix(".parquet.tmp")
    if tmp.exists():
        tmp.unlink()
    pq.write_table(table, tmp, compression="zstd")
    if CELLS_PATH.exists():
        CELLS_PATH.unlink()
    tmp.replace(CELLS_PATH)


def _mpa_summary(cells) -> dict:
    source = find_mpa_source()
    aus = cells["eez_sovereign"] == AUS_EEZ_SOVEREIGN
    return {
        "n_in_mpa": int((cells["in_mpa"] == True).sum()),  # noqa: E712
        "n_in_mpa_null": int(cells["in_mpa"].isna().sum()),
        "n_aus_in_mpa": int(((cells["in_mpa"] == True) & aus).sum()),  # noqa: E712
        "mpa_source": None if source is None else source.name,
        "wdpa_present": WDPA_DIR.exists(),
        "null_policy": NULL_POLICY,
    }


def refresh_mpa(*, memory: PeakMemory | None = None) -> dict:
    if not CELLS_PATH.exists():
        raise FileNotFoundError(
            f"Missing cells.parquet ({CELLS_PATH}). Run python -m src.features.build first."
        )
    LOG.info("refreshing in_mpa on %s", CELLS_PATH)
    cells = pq.read_table(CELLS_PATH).to_pandas()
    if memory:
        memory.sample()
    cells = attach_mpa(cells)
    if memory:
        memory.sample()
    _write_cells(cells)
    summary = {
        "skipped": False,
        "refreshed_mpa": True,
        "output": str(CELLS_PATH),
        "n_cells": len(cells),
        **_mpa_summary(cells),
    }
    return summary


def build(*, force: bool = False, memory: PeakMemory | None = None) -> dict:
    if CELLS_PATH.exists() and not force:
        LOG.info("cells already present (%s), skipping", CELLS_PATH)
        return {"skipped": True, "output": str(CELLS_PATH)}

    LOG.info("extracting unique cells from silver interactions")
    cells = extract_cells()
    if memory:
        memory.sample()
    LOG.info("unique cells=%s", f"{len(cells):,}")

    cells = attach_depth(cells)
    if memory:
        memory.sample()
    cells = attach_eez(cells)
    if memory:
        memory.sample()
    cells = attach_port_distance(cells)
    if memory:
        memory.sample()
    cells = attach_mpa(cells)
    if memory:
        memory.sample()

    _write_cells(cells)
    LOG.info("wrote %s", CELLS_PATH)

    n = len(cells)
    aus = cells["eez_sovereign"] == AUS_EEZ_SOVEREIGN
    summary = {
        "skipped": False,
        "output": str(CELLS_PATH),
        "n_cells": n,
        "n_with_depth": int(cells["depth_mean_m"].notna().sum()),
        "n_depth_null": int(cells["depth_mean_m"].isna().sum()),
        "n_with_eez": int(cells["eez_sovereign"].notna().sum()),
        "n_high_seas_or_unmatched": int(cells["eez_sovereign"].isna().sum()),
        "n_aus_eez": int(aus.sum()),
        "aus_eez_territories": (
            cells.loc[aus, "eez_territory"].value_counts(dropna=False).to_dict()
            if aus.any()
            else {}
        ),
        "n_with_port_distance": int(cells["distance_to_port_m"].notna().sum()),
        **_mpa_summary(cells),
    }
    return summary


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    if args.refresh_mpa:
        result = refresh_mpa(memory=memory)
    else:
        result = build(force=args.force, memory=memory)
    result.update(
        {
            "stage": "a3",
            "started_at": started,
            "finished_at": utcnow(),
            "peak_rss_bytes": memory.sample(),
            "peak_rss_mb": round(memory.peak_mb, 2),
        }
    )
    path = write_report(result, REPORTS_DIR / "a3_cells.json")
    LOG.info("A3 complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return result


if __name__ == "__main__":
    main()
