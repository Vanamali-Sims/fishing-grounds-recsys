"""CLI: land GFW sources as bronze Parquet. No cleaning.

    python -m src.ingest.build
    python -m src.ingest.build --years 2023 --force
"""

from __future__ import annotations

import argparse
import logging

from src.clean.report import utcnow, write_report
from src.ingest.bronze import land_interactions
from src.ingest.vessels import land_vessels
from src.paths import REPORTS_DIR, YEARS
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Land GFW daily CSVs and vessel metadata as bronze Parquet."
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(YEARS),
        help="Calendar years to land (default: 2023 2024).",
    )
    parser.add_argument(
        "--skip-vessels",
        action="store_true",
        help="Do not land fishing-vessels-v3.csv.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing bronze files.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    summary = {
        "stage": "bronze",
        "started_at": utcnow(),
        "years": list(args.years),
        "interactions": land_interactions(args.years, force=args.force, memory=memory),
        "vessels": None if args.skip_vessels else land_vessels(force=args.force, memory=memory),
        "peak_rss_bytes": memory.sample(),
        "peak_rss_mb": round(memory.peak_mb, 2),
    }
    summary["finished_at"] = utcnow()
    path = write_report(summary, REPORTS_DIR / "bronze.json")
    LOG.info("bronze complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return summary


if __name__ == "__main__":
    main()
