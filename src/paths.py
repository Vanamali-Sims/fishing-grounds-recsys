"""Filesystem locations used by the pipeline.

Raw inputs live under ``data/`` (gitignored). Processed artefacts go in
``data/processed/``. 2024 currently has extracted daily CSVs but no zip;
ingest should prefer the zip when present and fall back to the daily folder.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
INTERACTIONS_DIR = PROCESSED_DIR / "interactions"

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
