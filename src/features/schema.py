"""Gold cell dimension built in A3.

Centroid is the 0.1° cell centre (lower-left + 0.05°). Depth is only defined
inside the GEBCO subset bbox (southern Australia). EEZ is global. MPA is
null until WDPA is downloaded. High-seas cells have null EEZ — that is a
real attribute, not a join failure.
"""

from __future__ import annotations

# GEBCO file coverage (not the Australian EEZ).
GEBCO_BBOX = {
    "south": -58.195,
    "north": -30.783,
    "west": 99.967,
    "east": 159.976,
}

AUS_EEZ_SOVEREIGN = "Australia"
EEZ_LAYER = "eez_v12"

# Coarse mainland-ish box used in A2 EDA. A3 should replace this with polygons.
AUS_EDA_BBOX = {
    "south": -50.0,
    "north": -10.0,
    "west": 110.0,
    "east": 160.0,
}

CELL_COLUMNS = (
    "cell_id",
    "cell_ll_lat",
    "cell_ll_lon",
    "centroid_lat",
    "centroid_lon",
    "depth_mean_m",
    "depth_min_m",
    "eez_sovereign",
    "eez_territory",
    "eez_iso",
    "distance_to_port_m",
    "in_mpa",
)

NULL_POLICY = {
    "depth_mean_m": "null outside GEBCO_BBOX (file is a southern-Australia subset)",
    "depth_min_m": "same as depth_mean_m",
    "eez_sovereign": "null on high seas / unmatched (expected, not a join bug)",
    "distance_to_port_m": "null only if anchorage file is missing",
    "in_mpa": "null until WDPA is on disk; do not treat as False",
}
