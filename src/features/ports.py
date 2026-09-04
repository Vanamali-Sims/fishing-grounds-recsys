"""Minimum geodesic distance from each cell centroid to a GFW named anchorage."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src.paths import ANCHORAGES_CSV

LOG = logging.getLogger(__name__)
EARTH_RADIUS_M = 6_371_000.0


def _unit_xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    latr = np.radians(lat)
    lonr = np.radians(lon)
    cos_lat = np.cos(latr)
    return np.column_stack(
        (cos_lat * np.cos(lonr), cos_lat * np.sin(lonr), np.sin(latr))
    )


def haversine_m(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def attach_port_distance(cells: pd.DataFrame) -> pd.DataFrame:
    if not ANCHORAGES_CSV.exists():
        raise FileNotFoundError(f"Missing named anchorages: {ANCHORAGES_CSV}")

    ports = pd.read_csv(ANCHORAGES_CSV, usecols=["lat", "lon"])
    ports = ports.dropna(subset=["lat", "lon"])
    LOG.info("anchorages=%s", f"{len(ports):,}")

    tree = cKDTree(_unit_xyz(ports["lat"].to_numpy(), ports["lon"].to_numpy()))
    cell_xyz = _unit_xyz(
        cells["centroid_lat"].to_numpy(), cells["centroid_lon"].to_numpy()
    )
    _, nn = tree.query(cell_xyz, k=1, workers=-1)
    nn = nn.astype(np.int64)
    dist = haversine_m(
        cells["centroid_lat"].to_numpy(),
        cells["centroid_lon"].to_numpy(),
        ports["lat"].to_numpy()[nn],
        ports["lon"].to_numpy()[nn],
    )
    out = cells.copy()
    out["distance_to_port_m"] = dist
    return out
