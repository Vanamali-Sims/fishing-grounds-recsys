"""Fetch checksummed GFW zips and the official WDPA AUS geodatabase.

GEBCO, Marine Regions EEZ, and GFW Named Anchorages need a browser login
or an interactive subsetter — those URLs are printed, not fetched.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.paths import DATA_DIR, DAILY_ZIP, VESSELS_CSV, WDPA_DIR, WDPA_GDB, WDPA_ZIP

WDPA_AUS_URL = (
    "https://d1gam3xoknrgr2.cloudfront.net/current/"
    "WDPA_WDOECM_Sep2026_Public_AUS.zip"
)

ZENODO = "https://zenodo.org/records/14982712/files"
VESSELS_MD5 = "b5ba27cedd5426c0bcb8e6009e911cf0"
DAILY_MD5 = {
    2023: "7b55cca87029903c9becd09b11810455",
    2024: "51b0988ac6258482c1666c113c93f004",
}
SCHEMA_URL = f"{ZENODO}/fishing-vessels-v3.schema.json?download=1"
VESSELS_URL = f"{ZENODO}/fishing-vessels-v3.csv?download=1"
DAILY_URL = {
    year: f"{ZENODO}/mmsi-daily-csvs-10-v3-{year}.zip?download=1" for year in (2023, 2024)
}


def md5sum(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, dest: Path, expected: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (expected is None or md5sum(dest) == expected):
        print(f"skip {dest.relative_to(ROOT)} (already verified)")
        return
    print(f"download {dest.name}")
    with urlopen(url, timeout=180) as src, dest.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    if expected and md5sum(dest) != expected:
        dest.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {dest.name}; deleted, retry")


def fetch_wdpa() -> None:
    if WDPA_GDB.exists():
        print(f"skip {WDPA_GDB.relative_to(ROOT)}")
        return
    fetch(WDPA_AUS_URL, WDPA_ZIP)
    WDPA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(WDPA_ZIP) as archive:
        archive.extractall(WDPA_DIR)
    if not WDPA_GDB.exists():
        raise SystemExit(f"WDPA zip extracted but missing {WDPA_GDB.name}")


def print_manual() -> None:
    print(
        """
Manual downloads (browser / login):

  GEBCO 2026 southern-Australia subset
    https://download.gebco.net/
    box 58.195S–30.783S, 99.967E–159.976E → data/GEBCO_02_Sep_2026_cb6d79a83e83/

  Marine Regions World EEZ v12 GeoPackage
    https://www.marineregions.org/downloads.php
    → data/World_EEZ_v12_20231025_gpkg/World_EEZ_v12_20231025_gpkg/eez_v12.gpkg

  GFW Named Anchorages
    https://globalfishingwatch.org/data-download/
    → data/named_anchorages_v2_pipe_v4_202608.csv

Checksums and field notes: DATA.md
"""
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download GFW + WDPA inputs.")
    parser.add_argument("--skip-wdpa", action="store_true")
    parser.add_argument("--years", nargs="*", type=int, default=[2023, 2024])
    args = parser.parse_args(argv)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetch(VESSELS_URL, VESSELS_CSV, VESSELS_MD5)
    fetch(SCHEMA_URL, DATA_DIR / "fishing-vessels-v3.schema.json")
    for year in args.years:
        if year not in DAILY_URL:
            raise SystemExit(f"unsupported year {year}")
        fetch(DAILY_URL[year], DAILY_ZIP[year], DAILY_MD5[year])
    if not args.skip_wdpa:
        fetch_wdpa()
    print_manual()
    return 0


if __name__ == "__main__":
    sys.exit(main())
