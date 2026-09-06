"""MPA flag from a polygon layer on cell centroids.

The Sep 2026 WDPA public CSV under ``data/WDPA_Sep2026_Public_csv/`` is the
attribute table only — no geometries. The join needs polygons. Those are
fetched from the official WDPCA polygon service (same SITE_ID schema) and
written to ``data/wdpa/``.

Until a vector file is on disk, ``in_mpa`` stays null — never False.
Once a source exists, centroids inside a marine/coastal polygon are True
and the rest are False.
"""

from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path
from urllib.request import urlopen

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely import STRtree, points

from src.paths import DATA_DIR, WDPA_CSV_DIR, WDPA_DIR, WDPA_GDB, WDPA_ZIP

LOG = logging.getLogger(__name__)

VECTOR_SUFFIXES = (".gpkg", ".shp", ".geojson", ".json")
WDPA_AUS_URL = (
    "https://d1gam3xoknrgr2.cloudfront.net/current/"
    "WDPA_WDOECM_Sep2026_Public_AUS.zip"
)
WDPA_MARINE = {1, 2}
WDPA_REALM_KEEP = {"MARINE", "COASTAL"}
WDPA_STATUS_KEEP = {"designated", "inscribed", "adopted", "established"}


def find_mpa_source(root: Path | None = None) -> Path | None:
    if root is None and WDPA_GDB.exists():
        return WDPA_GDB
    roots = (root,) if root is not None else (WDPA_DIR, WDPA_CSV_DIR, DATA_DIR)
    found: list[Path] = []
    for base in roots:
        if base is None or not base.exists():
            continue
        if base.is_file() and base.suffix.lower() in VECTOR_SUFFIXES:
            found.append(base)
            continue
        if base.is_dir() and base.suffix.lower() == ".gdb":
            found.append(base)
            continue
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_dir() and path.suffix.lower() == ".gdb":
                found.append(path)
            elif path.is_file() and path.suffix.lower() in VECTOR_SUFFIXES:
                found.append(path)
    if not found:
        return None
    rank = {".gdb": 0, ".gpkg": 1, ".shp": 2, ".geojson": 3, ".json": 4}
    found.sort(key=lambda path: (rank.get(path.suffix.lower(), 9), len(path.name)))
    return found[0]


def _filter_polygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if out.empty:
        return out
    columns = {name.upper(): name for name in out.columns}

    marine_col = columns.get("MARINE")
    if marine_col is not None:
        marine = pd.to_numeric(out[marine_col], errors="coerce")
        out = out[marine.isin(WDPA_MARINE)]

    realm_col = columns.get("REALM")
    if realm_col is not None and marine_col is None:
        realm = out[realm_col].astype(str).str.strip().str.upper()
        out = out[realm.isin(WDPA_REALM_KEEP)]

    status_col = columns.get("STATUS")
    if status_col is not None:
        status = out[status_col].astype(str).str.strip().str.lower()
        keep = status.isin(WDPA_STATUS_KEEP) | status.isin({"", "nan", "none"})
        out = out[keep]

    environ_col = columns.get("ENVIRON")
    if environ_col is not None and marine_col is None and realm_col is None:
        environ = out[environ_col].astype(str).str.strip().str.upper()
        marine_like = environ.isin({"M", "MARINE", "B", "BOTH"})
        if marine_like.any():
            out = out[marine_like]
    return out


def _polygon_layer(path: Path) -> str | None:
    if path.suffix.lower() != ".gdb":
        return None
    for name, geom in pyogrio.list_layers(path):
        if geom and "Polygon" in str(geom):
            return str(name)
    raise ValueError(f"No polygon layer in {path}")


def load_mpa_polygons(path: Path) -> gpd.GeoDataFrame:
    layer = _polygon_layer(path)
    gdf = gpd.read_file(path, layer=layer, engine="pyogrio")
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    else:
        gdf = gdf.to_crs(4326)
    gdf = _filter_polygons(gdf)
    if gdf.empty:
        raise ValueError(f"MPA source has no usable marine polygons: {path}")
    LOG.info("MPA polygons loaded: %s from %s", f"{len(gdf):,}", path.name)
    return gdf


def _flag_centroids(cells: pd.DataFrame, polygons: gpd.GeoDataFrame) -> pd.Series:
    pts = points(cells["centroid_lon"].to_numpy(), cells["centroid_lat"].to_numpy())
    tree = STRtree(polygons.geometry.values)
    result = np.asarray(tree.query(pts, predicate="within"))
    flagged = np.zeros(len(cells), dtype=bool)
    if result.size:
        pt_idx = result[0] if result.ndim == 2 else result
        flagged[np.unique(pt_idx)] = True
    n_hit = int(flagged.sum())
    LOG.info("MPA centroid hits=%s / %s", f"{n_hit:,}", f"{len(cells):,}")
    return pd.Series(flagged, index=cells.index, dtype="boolean")


def attach_mpa(cells: pd.DataFrame, source: Path | None = None) -> pd.DataFrame:
    out = cells.copy()
    path = source or find_mpa_source()
    if path is None:
        out["in_mpa"] = pd.Series([pd.NA] * len(out), dtype="boolean")
        return out
    polygons = load_mpa_polygons(path)
    out["in_mpa"] = _flag_centroids(out, polygons)
    return out


def download_wdpa_aus_polygons(dest: Path | None = None, *, force: bool = False) -> Path:
    """Official Sep 2026 AUS File Geodatabase from Protected Planet."""
    dest = dest or WDPA_ZIP
    gdb = WDPA_GDB
    if gdb.exists() and not force:
        LOG.info("WDPA geodatabase already present (%s)", gdb)
        return gdb

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or force:
        LOG.info("downloading %s", WDPA_AUS_URL)
        with urlopen(WDPA_AUS_URL, timeout=180) as response:  # noqa: S310
            dest.write_bytes(response.read())
    with zipfile.ZipFile(dest) as archive:
        archive.extractall(WDPA_DIR)
    if not gdb.exists():
        raise FileNotFoundError(f"zip extracted but missing {gdb.name}")
    LOG.info("extracted %s", gdb)
    return gdb


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Australian marine/coastal WDPA polygons."
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> Path | None:
    from src.runtime import setup_logging

    args = parse_args(argv)
    setup_logging(args.log_level)
    if args.download:
        return download_wdpa_aus_polygons(force=args.force)
    raise SystemExit("pass --download to fetch WDPA marine/coastal polygons for Australia")


if __name__ == "__main__":
    main()
