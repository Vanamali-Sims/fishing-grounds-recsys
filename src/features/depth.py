"""Zonal mean/min GEBCO depth per 0.1° cell. Null outside the file bbox."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import rasterio

from src.features.extract import CELL_STEP
from src.features.schema import GEBCO_BBOX
from src.paths import GEBCO_TIF

LOG = logging.getLogger(__name__)


def _in_gebco_bbox(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    # Cell must lie entirely inside the raster (ll + 0.1 still inside).
    return (
        (lat >= GEBCO_BBOX["south"])
        & (lat + CELL_STEP <= GEBCO_BBOX["north"])
        & (lon >= GEBCO_BBOX["west"])
        & (lon + CELL_STEP <= GEBCO_BBOX["east"])
    )


def attach_depth(cells: pd.DataFrame) -> pd.DataFrame:
    if not GEBCO_TIF.exists():
        raise FileNotFoundError(f"Missing GEBCO GeoTIFF: {GEBCO_TIF}")

    n = len(cells)
    mean = np.full(n, np.nan, dtype=np.float64)
    minimum = np.full(n, np.nan, dtype=np.float64)
    mask = _in_gebco_bbox(
        cells["cell_ll_lat"].to_numpy(), cells["cell_ll_lon"].to_numpy()
    )
    idx = np.flatnonzero(mask)
    LOG.info("GEBCO zonal stats for %s / %s cells inside file bbox", f"{len(idx):,}", f"{n:,}")

    with rasterio.open(GEBCO_TIF) as src:
        band = src.read(1)
        nodata = src.nodata
        if nodata is not None:
            band = np.where(band == nodata, np.nan, band.astype(np.float64))
        else:
            band = band.astype(np.float64)
        height, width = band.shape
        lats = cells["cell_ll_lat"].to_numpy()
        lons = cells["cell_ll_lon"].to_numpy()
        for i in idx:
            lon0 = float(lons[i])
            lat0 = float(lats[i])
            r0, c0 = src.index(lon0, lat0 + CELL_STEP)
            r1, c1 = src.index(lon0 + CELL_STEP, lat0)
            rmin, rmax = sorted((r0, r1))
            cmin, cmax = sorted((c0, c1))
            rmin = max(rmin, 0)
            cmin = max(cmin, 0)
            rmax = min(rmax, height)
            cmax = min(cmax, width)
            if rmax <= rmin or cmax <= cmin:
                continue
            patch = band[rmin:rmax, cmin:cmax]
            if not np.isfinite(patch).any():
                continue
            mean[i] = float(np.nanmean(patch))
            minimum[i] = float(np.nanmin(patch))

    out = cells.copy()
    out["depth_mean_m"] = mean
    out["depth_min_m"] = minimum
    return out
