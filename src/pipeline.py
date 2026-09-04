"""Run bronze landing then silver cleaning (A1).

    python -m src.pipeline
    python -m src.pipeline --years 2023 --force
"""

from __future__ import annotations

import argparse
import logging

from src.clean.interactions import clean_interactions
from src.clean.report import utcnow, write_report
from src.clean.vessels import clean_vessels
from src.ingest.bronze import land_interactions
from src.ingest.vessels import land_vessels
from src.paths import YEARS
from src.runtime import PeakMemory, setup_logging

LOG = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Land bronze GFW Parquet, then clean to silver."
    )
    parser.add_argument("--years", type=int, nargs="+", default=list(YEARS))
    parser.add_argument("--skip-vessels", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    setup_logging(args.log_level)
    memory = PeakMemory()
    started = utcnow()

    bronze_interactions = land_interactions(args.years, force=args.force, memory=memory)
    bronze_vessels = None
    if not args.skip_vessels:
        bronze_vessels = land_vessels(force=args.force, memory=memory)

    silver_interactions = clean_interactions(args.years, force=args.force, memory=memory)
    silver_vessels = None
    if not args.skip_vessels:
        silver_vessels = clean_vessels(args.years, force=args.force, memory=memory)

    summary = {
        "stage": "a1",
        "started_at": started,
        "finished_at": utcnow(),
        "years": list(args.years),
        "bronze": {"interactions": bronze_interactions, "vessels": bronze_vessels},
        "silver": {"interactions": silver_interactions, "vessels": silver_vessels},
        "peak_rss_bytes": memory.sample(),
        "peak_rss_mb": round(memory.peak_mb, 2),
    }
    path = write_report(summary)
    LOG.info(
        "A1 complete; peak RSS %.1f MB; report %s",
        memory.peak_mb,
        path,
    )
    return summary


if __name__ == "__main__":
    main()
