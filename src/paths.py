"""Filesystem locations used by the pipeline.

Raw inputs live under ``data/`` (gitignored). Processed artefacts go in
``data/processed/``.

Layout (medallion):

- ``bronze/`` — as-landed Parquet. Types preserved; no repairs, no drops.
- ``interactions/`` — silver (clean) interactions, year/month partitioned.
- ``vessels.parquet`` — silver vessel dimension, modelling years only.
- ``cells.parquet`` — gold cell dimension (A3: depth, EEZ, port distance, MPA).
- ``quarantine/`` — rows that failed a hard validation rule.
- ``reports/`` — row counts, repairs, observations, peak memory.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = PROCESSED_DIR / "reports"

BRONZE_DIR = PROCESSED_DIR / "bronze"
BRONZE_INTERACTIONS_DIR = BRONZE_DIR / "interactions"
BRONZE_VESSELS_PATH = BRONZE_DIR / "vessels.parquet"

INTERACTIONS_DIR = PROCESSED_DIR / "interactions"
VESSELS_PATH = PROCESSED_DIR / "vessels.parquet"
CELLS_PATH = PROCESSED_DIR / "cells.parquet"

# A3 spatial inputs (raw, gitignored)
GEBCO_DIR = DATA_DIR / "GEBCO_02_Sep_2026_cb6d79a83e83"
GEBCO_NC = GEBCO_DIR / "gebco_2026_n-30.783_s-58.195_w99.967_e159.976.nc"
GEBCO_TIF = GEBCO_DIR / "gebco_2026_n-30.783_s-58.195_w99.967_e159.976_geotiff.tif"
EEZ_DIR = DATA_DIR / "World_EEZ_v12_20231025_gpkg" / "World_EEZ_v12_20231025_gpkg"
EEZ_GPKG = EEZ_DIR / "eez_v12.gpkg"
ANCHORAGES_CSV = DATA_DIR / "named_anchorages_v2_pipe_v4_202608.csv"
WDPA_DIR = DATA_DIR / "wdpa"  # not downloaded yet

QUARANTINE_DIR = PROCESSED_DIR / "quarantine"
QUARANTINE_INTERACTIONS_DIR = QUARANTINE_DIR / "interactions"
QUARANTINE_VESSELS_PATH = QUARANTINE_DIR / "vessels.parquet"

VESSELS_CSV = DATA_DIR / "fishing-vessels-v3.csv"

DAILY_ZIP = {
    2023: DATA_DIR / "mmsi-daily-csvs-10-v3-2023.zip",
    2024: DATA_DIR / "mmsi-daily-csvs-10-v3-2024.zip",
}
DAILY_DIR = {
    2023: DATA_DIR / "mmsi-daily-csvs-10-v3-2023",
    2024: DATA_DIR / "mmsi-daily-csvs-10-v3-2024",
}

YEARS = (2023, 2024)

DAILY_CSV_NAME = "mmsi-daily-csvs-10-v3-{year:04d}-{month:02d}-{day:02d}.csv"


def hive_month_dir(root: Path, year: int, month: int) -> Path:
    return root / f"year={year}" / f"month={month:02d}"


def bronze_day_path(year: int, month: int, day: int) -> Path:
    date = f"{year:04d}-{month:02d}-{day:02d}"
    return hive_month_dir(BRONZE_INTERACTIONS_DIR, year, month) / f"{date}.parquet"


def silver_month_path(year: int, month: int) -> Path:
    return hive_month_dir(INTERACTIONS_DIR, year, month) / "part.parquet"


def quarantine_month_path(year: int, month: int) -> Path:
    return hive_month_dir(QUARANTINE_INTERACTIONS_DIR, year, month) / "part.parquet"
