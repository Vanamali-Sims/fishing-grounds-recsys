"""CLI: bronze Parquet → silver interactions/vessels + quarantine + report.

    python -m src.clean.build
    python -m src.clean.build --years 2023 --force
"""

from __future__ import annotations

import argparse
import logging

from src.clean.interactions import clean_interactions
from src.clean.report import utcnow, write_report
from src.clean.vessels import clean_vessels
from src.paths import YEARS
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and clean bronze GFW Parquet into silver tables."
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(YEARS),
        help="Calendar years to clean (default: 2023 2024).",
    )
    parser.add_argument(
        "--skip-vessels",
        action="store_true",
        help="Do not clean vessel metadata.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing silver/quarantine files.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()
    interactions = clean_interactions(args.years, force=args.force, memory=memory)
    vessels = None if args.skip_vessels else clean_vessels(
        args.years, force=args.force, memory=memory
    )
    summary = {
        "stage": "silver",
        "started_at": started,
        "finished_at": utcnow(),
        "years": list(args.years),
        "interactions": interactions,
        "vessels": vessels,
        "peak_rss_bytes": memory.sample(),
        "peak_rss_mb": round(memory.peak_mb, 2),
    }
    path = write_report(summary)
    LOG.info("silver complete; peak RSS %.1f MB; report %s", memory.peak_mb, path)
    return summary


if __name__ == "__main__":
    main()
