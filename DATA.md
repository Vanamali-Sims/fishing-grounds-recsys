# Data guide

Every dataset used in this project, where it came from, what its fields mean, and what's wrong with it.

Nothing under `data/` is committed. Files currently on disk:

```
data/
├── fishing-vessels-v3.csv
├── fishing-vessels-v3.schema.json
├── mmsi-daily-csvs-10-v3-2023.zip
├── named_anchorages_v2_pipe_v4_202608.csv
├── mmsi-daily-csvs-10-v3-2023/          # 365 daily CSVs, 2023-01-01 … 2023-12-31
├── mmsi-daily-csvs-10-v3-2024/          # 366 daily CSVs, 2024-01-01 … 2024-12-31
├── GEBCO_02_Sep_2026_cb6d79a83e83/
│   ├── gebco_2026_n-30.783_s-58.195_w99.967_e159.976.nc
│   ├── gebco_2026_n-30.783_s-58.195_w99.967_e159.976_geotiff.tif
│   ├── GEBCO_Grid_documentation.pdf
│   └── GEBCO_Grid_terms_of_use.pdf
└── World_EEZ_v12_20231025_gpkg/
    └── World_EEZ_v12_20231025_gpkg/
        ├── eez_v12.gpkg
        ├── eez_boundaries_v12.gpkg
        └── LICENSE_EEZ_v12.txt
```

Not present: `mmsi-daily-csvs-10-v3-2024.zip` (2024 is extracted only), GFW README files (`README-known-issues-v3.txt`, `README-mmsi-v3.txt`, `README-fishing-vessels-v3.txt`), WDPA / Protected Planet.

---

## 1. Global Fishing Watch — apparent fishing effort (primary)

**Source:** Zenodo, DOI [10.5281/zenodo.14982712](https://doi.org/10.5281/zenodo.14982712)
**Version:** 3.0, released 11 March 2025
**Licence:** CC BY-NC 4.0 — non-commercial
**Coverage:** 2012–2024 globally; this project uses 2023–2024

Built from AIS positions of more than 190,000 fishing vessels, of which up to ~96,000 are active in any given year. Vessel time is measured in hours by assigning each AIS position the time elapsed since the vessel's previous position. That time counts as *apparent fishing hours* when GFW's neural-network fishing detection model determines the vessel was engaged in fishing behaviour at that position.

Positions are binned into grid cells; coordinates give the **lower-left corner** in decimal degrees (WGS84).

### Files used

| File | On disk | Size | MD5 |
| --- | --- | --- | --- |
| `mmsi-daily-csvs-10-v3-2023.zip` | yes | 739.2 MB | `7b55cca87029903c9becd09b11810455` |
| `mmsi-daily-csvs-10-v3-2024.zip` | **no** — extracted CSVs only | 745.7 MB (Zenodo) | `51b0988ac6258482c1666c113c93f004` |
| `fishing-vessels-v3.csv` | yes | 114.8 MB | `b5ba27cedd5426c0bcb8e6009e911cf0` |
| `fishing-vessels-v3.schema.json` | yes | 4.3 kB | — |
| `mmsi-daily-csvs-10-v3-2023/` | yes | 365 CSVs, ~3.4 GB | — |
| `mmsi-daily-csvs-10-v3-2024/` | yes | 366 CSVs, ~3.4 GB | — |

2023 and 2024 daily folders are complete (every calendar day; 2024 is a leap year). Each daily file is named `mmsi-daily-csvs-10-v3-YYYY-MM-DD.csv`. Both years share the same header. MD5s for the zips and vessel CSV come from the Zenodo record; the 2023 zip and vessel CSV match.

### Interaction schema — `mmsi-daily`, 0.1° resolution

| Field | Type | Meaning | Role in the model |
| --- | --- | --- | --- |
| `date` | DATE | YYYY-MM-DD | Temporal split; seasonality features |
| `cell_ll_lat` | FLOAT | Lower-left latitude of cell, decimal degrees | Half the item key |
| `cell_ll_lon` | FLOAT | Lower-left longitude of cell, decimal degrees | Half the item key |
| `mmsi` | STRING | Maritime Mobile Service Identity | **User key** |
| `hours` | FLOAT | Hours broadcasting on AIS while present in cell | Transit-vs-fishing denominator |
| `fishing_hours` | FLOAT | Of those, hours the model detected as fishing | **Confidence weight** |

**Derived keys and features**

- `cell_id` — `f"{cell_ll_lat}_{cell_ll_lon}"`, the item identifier
- `fishing_ratio` — `fishing_hours / hours`, guarded against division by zero. Low values indicate transit; the pipeline applies a minimum threshold so steaming lanes don't enter the interaction matrix as fishing grounds.

### Vessel schema — `fishing-vessels-v3.csv`

One row per MMSI per year in which the vessel was active (`year` from 2012–2024). Column names match `fishing-vessels-v3.schema.json`.

| Field | Type | Meaning |
| --- | --- | --- |
| `mmsi` | STRING | AIS identifier |
| `year` | INTEGER | Year this row applies to |
| `flag_ais` | STRING | Flag from the MMSI MID (ISO3) |
| `flag_registry` | STRING | Flag as listed on vessel registries |
| `flag_gfw` | STRING | Flag assigned by GFW after all sources |
| `vessel_class_inferred` | STRING | Gear class from GFW's neural net |
| `vessel_class_inferred_score` | FLOAT | Neural-net confidence, 0–1 |
| `vessel_class_registry` | STRING | Gear class from registries |
| `vessel_class_gfw` | STRING | Gear class assigned by GFW after all sources |
| `self_reported_fishing_vessel` | BOOLEAN | AIS ship type is Fishing in >98% of identity messages |
| `length_m_inferred` / `_registry` / `_gfw` | FLOAT | Length in metres |
| `engine_power_kw_inferred` / `_registry` / `_gfw` | FLOAT | Engine power in kW |
| `tonnage_gt_inferred` / `_registry` / `_gfw` | FLOAT | Gross tonnage |
| `registries_listed` | STRING | Registries used for the `_registry` fields |
| `active_hours` | FLOAT | Hours broadcasting AIS and moving faster than 0.1 knots |
| `fishing_hours` | FLOAT | Hours detected as fishing that year |

> **Breaking change in v3 — read this before joining.** In v2, each MMSI had one row with per-year fishing-hours columns. In v3, an MMSI gets **one row per year in which it was active**, with a single `year` column and a single `fishing_hours` column. This was done so vessel classification can change across years as registry information updates.
>
> Consequence: joining vessel metadata to interactions without filtering on `year` will fan out your rows and silently corrupt the matrix. Always constrain the join to the matching year.

Use the `*_gfw` columns (flag, class, length, power, tonnage) unless you specifically need inferred vs registry provenance.

**How the fields are used**

- **Gear type** (`vessel_class_gfw`) — the strongest metadata predictor. Trawlers, drifting longliners and purse seiners target structurally different waters. Also a free model sanity check: if learned latent factors don't roughly separate by gear, something is wrong.
- **Length, tonnage, engine power** (`length_m_gfw`, `tonnage_gt_gfw`, `engine_power_kw_gfw`) — proxies for range and capacity. Primary cold-start features, and a sanity filter on physically implausible recommendations.
- **Flag** (`flag_gfw`) — fleet-level behavioural signal; secondary cold-start feature.

**Caveat on provenance.** Length, tonnage, engine power and class are often model estimates rather than registry facts — the `_registry` columns are sparsely filled. Registry data quality also varies substantially by flag state, which introduces uneven information across fleets.

### Known issues

The GFW `README-known-issues-v3.txt` is not in `data/`. The significant ones from the dataset docs:

1. **2024 is provisional.** Vessel classifications may change as 2025 data arrives.
2. **MMSI is not reliably unique.** It is intended as a unique AIS identifier but this does not always hold in practice — vessels share, reuse, and misconfigure it. Since MMSI is the user key, this is direct noise in the matrix.
3. **Flag state may be wrong.** When a vessel isn't on any registry, flag is derived from the Maritime Identification Digits — the first three digits of the MMSI — which can be entered incorrectly.
4. **AIS reception is uneven and non-stationary.** Coverage varies by region and changes over time. A rise in apparent effort in a region may reflect better satellite reception rather than more fishing. This matters for any temporal comparison and should be stated in results.
5. **Apparent effort, not catch.** Fishing behaviour is inferred from movement patterns. No catch volume or species information exists in this dataset.
6. **Coverage bias.** Vessels without AIS — typically smaller and artisanal — are largely absent, skewing the picture toward industrial fleets.

---

## 2. GEBCO_2026 — seabed depth

**Source:** [download.gebco.net](https://download.gebco.net/) (area-subsetting application)
**Licence:** public domain, free to use with attribution — see `GEBCO_Grid_terms_of_use.pdf`
**Resolution:** 15 arc-second grid, WGS84 (EPSG:4326)
**On disk:** `data/GEBCO_02_Sep_2026_cb6d79a83e83/`

Published April 2026. Regional subset, not the global file:

| File | Size |
| --- | --- |
| `gebco_2026_n-30.783_s-58.195_w99.967_e159.976.nc` | 180.9 MB |
| `gebco_2026_n-30.783_s-58.195_w99.967_e159.976_geotiff.tif` | 180.8 MB |
| `GEBCO_Grid_documentation.pdf` | 260 kB |
| `GEBCO_Grid_terms_of_use.pdf` | 142 kB |

**Bounding box:** 58.195°S–30.783°S, 99.967°E–159.976°E (southern Australia and the Southern Ocean to the south of it). Does not cover northern Australian waters or most external-territory EEZs (Heard & McDonald, Christmas Island, Norfolk, Cocos).

NetCDF and GeoTIFF are the same grid in two formats. GeoTIFF is 14402 × 6579 pixels, 15 arc-second spacing, pixel-centre registered, elevation in metres.

**Use:** aggregate to mean and minimum depth per 0.1° cell. Depth is arguably the strongest physical constraint on which gear can operate where, and it is the single most valuable feature not present in the raw GFW data.

Attribution: *GEBCO Bathymetric Compilation Group 2026 (2026). The GEBCO_2026 Grid — a continuous terrain model for oceans and land at 15 arc-second intervals. NERC EDS British Oceanographic Data Centre NOC. doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa*

---

## 3. Marine Regions — World EEZ v12

**Source:** [marineregions.org](https://www.marineregions.org/)
**Version:** v12, released 25 October 2023
**Licence:** CC BY 4.0 — not for legal, economic-exploration, or navigational use
**On disk:** `data/World_EEZ_v12_20231025_gpkg/World_EEZ_v12_20231025_gpkg/`

| File | Size |
| --- | --- |
| `eez_v12.gpkg` | 156.8 MB |
| `eez_boundaries_v12.gpkg` | 15.1 MB |
| `LICENSE_EEZ_v12.txt` | 2.3 kB |

200-nautical-mile Exclusive Economic Zone polygons. Longitude range is −180…180 (WGS84, EPSG:4326), matching GFW. Layer name in the GeoPackage is `eez_v12` (285 features). Attribute columns include `SOVEREIGN1`, `TERRITORY1`, `GEONAME`, `POL_TYPE`, `ISO_SOV1`, `ISO_TER1`.

Australia has six polygons: mainland, Christmas Island, Cocos Islands, Heard and McDonald Islands, Norfolk Island, and Macquarie Island. Record which you included and why.

**Use:** point-in-polygon join tagging each cell with jurisdiction; also the mechanism for scoping analysis to a single EEZ.

```python
import geopandas as gpd
eez = gpd.read_file(
    "data/World_EEZ_v12_20231025_gpkg/World_EEZ_v12_20231025_gpkg/eez_v12.gpkg"
)
print(eez.columns)
aus = eez[eez["SOVEREIGN1"] == "Australia"]
```

Citation: *Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries and Exclusive Economic Zones (200NM), version 12. https://doi.org/10.14284/632*

---

## 4. GFW Named Anchorages

**Source:** Global Fishing Watch data download portal
**On disk:** `data/named_anchorages_v2_pipe_v4_202608.csv` (18.45 MB)

Locations where vessels congregate and remain stationary — effectively a global port and anchorage registry.

Comma-separated despite `pipe` in the filename. Header:

`s2id,lat,lon,label,sublabel,label_source,iso3,distance_from_shore_m,drift_radius,at_dock`

- **Multiple rows per port.** Anchorages are clustered points, so one port yields many rows. For distance-to-port, take the minimum distance across all anchorage points rather than deduplicating to a single centroid.

**Use:** `distance_to_nearest_port` per cell. Explains range constraints on smaller vessels and materially improves cold-start predictions.

Only this snapshot is needed — port locations are near-static, so there's no value in a time series.

---

## 5. WDPA / Protected Planet — marine protected areas

**Source:** [protectedplanet.net](https://www.protectedplanet.net/)
**Release:** September 2026 (WDPCA)
**Licence:** non-commercial use; attribute UNEP-WCMC and IUCN

On disk:

| File | What it is |
| --- | --- |
| `WDPA_Sep2026_Public_csv/` and `WDPA_WDOECM_Sep2026_Public_AUS_csv.csv` | Attribute tables only (`TYPE=Polygon` is a flag, not geometry) |
| `wdpa/WDPA_WDOECM_Sep2026_Public_AUS.gdb` | Official AUS File Geodatabase — **this is the join source** |
| `wdpa/WDPA_WDOECM_Sep2026_Public_AUS.zip` | 70.9 MB country download from Protected Planet |

The join uses layer `WDPA_WDOECM_poly_Sep2026_AUS`, keeps `REALM` in {Marine, Coastal} and designated/inscribed/established/adopted status, then flags a 0.1° cell if its centroid falls inside a polygon. Terrestrial parks are not used as fishing-ground constraints.

This is a coarse legal filter, not a zoning engine: some WDPA marine polygons still allow fishing in multiple-use zones.

Citation: *UNEP-WCMC and IUCN (2026). Protected Planet: The World Database on Protected and Conserved Areas (WDPCA) [On-line], September 2026, Cambridge, UK. https://doi.org/10.34892/6fwd-af11*

Re-fetch: `python -m src.features.mpa --download` then `python -m src.features.build --refresh-mpa`.

---

## Processed artefacts

Written by the pipeline into `data/processed/`, all gitignored.

| Artefact | Description |
| --- | --- |
| `interactions/` | Partitioned Parquet, one partition per year-month |
| `cells.parquet` | Cell dimension: `cell_id`, centroid, depth, EEZ, distance-to-port, MPA flag |
| `vessels.parquet` | Vessel dimension, filtered to the modelling years |
| `fishing_events.parquet` | Transit-filtered fishing rows used to build the matrix |
| `matrix.npz` | Sparse vessel × cell CSR matrix plus index mappings (full window) |
| `splits/train.npz` | Train CSR, same index maps, Q4 2024 held out |
| `splits/test_relevant.parquet` | Q4 vessel–cell pairs with new-ground / cold-start flags |
| `als_factors.npz` | Implicit ALS user and item factors |
| `content_foldin.npz` | Ridge map from vessel metadata to user factors |

**Partitioning.** Interactions are partitioned by year and month so temporal-split queries read only the partitions they need. This is what makes the train/test split cheap enough to iterate on.

---

## Reproducing

Checksums for the GFW zips and vessel CSV come from the Zenodo record page. A mismatch means a corrupt or truncated download — delete the file and re-fetch rather than proceeding. The 2023 zip and `fishing-vessels-v3.csv` have been checked and match.

2024 daily CSVs are already extracted; the 2024 zip is not on disk. GEBCO and EEZ were downloaded as the regional / GeoPackage products above, not via a project script.

---

## Citations

```bibtex
@dataset{gfw_effort_v3,
  author    = {{Global Fishing Watch}},
  title     = {Global AIS-based Apparent Fishing Effort Dataset},
  version   = {3.0},
  year      = {2025},
  publisher = {Global Fishing Watch},
  doi       = {10.5281/zenodo.14982712}
}

@article{kroodsma2018tracking,
  author  = {Kroodsma, D. A. and Mayorga, J. and Hochberg, T. and Miller, N. A.
             and Boerder, K. and Ferretti, F. and Wilson, A. and Bergman, B.
             and White, T. D. and Block, B. A. and Woods, P. and Sullivan, B.
             and Costello, C. and Worm, B.},
  title   = {Tracking the global footprint of fisheries},
  journal = {Science},
  volume  = {361},
  number  = {6378},
  year    = {2018},
  doi     = {10.1126/science.aao5646}
}

@dataset{gebco_2026,
  author    = {{GEBCO Bathymetric Compilation Group 2026}},
  title     = {The {GEBCO\_2026} Grid -- a continuous terrain model for oceans
               and land at 15 arc-second intervals},
  year      = {2026},
  publisher = {NERC EDS British Oceanographic Data Centre NOC},
  doi       = {10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa}
}

@dataset{marineregions_eez_v12,
  author    = {{Flanders Marine Institute}},
  title     = {Maritime Boundaries Geodatabase: Maritime Boundaries and
               Exclusive Economic Zones (200{NM})},
  version   = {12},
  year      = {2023},
  doi       = {10.14284/632}
}
```
