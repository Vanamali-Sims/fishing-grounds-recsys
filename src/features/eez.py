"""Point-in-polygon EEZ join on cell centroids."""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree, points

from src.features.schema import EEZ_LAYER
from src.paths import EEZ_GPKG

LOG = logging.getLogger(__name__)


def attach_eez(cells: pd.DataFrame) -> pd.DataFrame:
    if not EEZ_GPKG.exists():
        raise FileNotFoundError(f"Missing EEZ GeoPackage: {EEZ_GPKG}")

    eez = gpd.read_file(EEZ_GPKG, layer=EEZ_LAYER, engine="pyogrio")
    eez = eez.to_crs(4326)
    LOG.info("EEZ polygons loaded: %s", f"{len(eez):,}")

    pts = points(cells["centroid_lon"].to_numpy(), cells["centroid_lat"].to_numpy())
    tree = STRtree(eez.geometry.values)
    result = np.asarray(tree.query(pts, predicate="within"))
    # Shapely 2.1 array query: row 0 = input (point) indices, row 1 = tree indices.
    pt_idx = result[0]
    tree_idx = result[1]

    n_hits = len(pt_idx)
    n_multi = int(len(pt_idx) - len(np.unique(pt_idx))) if len(pt_idx) else 0
    LOG.info("EEZ within-hits=%s duplicate-matches=%s", f"{n_hits:,}", f"{n_multi:,}")

    n = len(cells)
    sovereign = np.empty(n, dtype=object)
    territory = np.empty(n, dtype=object)
    iso = np.empty(n, dtype=object)
    sovereign[:] = None
    territory[:] = None
    iso[:] = None

    if len(pt_idx):
        areas = eez["AREA_KM2"].to_numpy()[tree_idx]
        order = np.argsort(areas, kind="stable")
        tree_idx = tree_idx[order]
        pt_idx = pt_idx[order]
        _, first = np.unique(pt_idx, return_index=True)
        tree_idx = tree_idx[first]
        pt_idx = pt_idx[first]
        sovereign[pt_idx] = eez["SOVEREIGN1"].to_numpy()[tree_idx]
        territory[pt_idx] = eez["TERRITORY1"].to_numpy()[tree_idx]
        iso[pt_idx] = eez["ISO_SOV1"].to_numpy()[tree_idx]

    out = cells.copy()
    out["eez_sovereign"] = sovereign
    out["eez_territory"] = territory
    out["eez_iso"] = iso
    return out
