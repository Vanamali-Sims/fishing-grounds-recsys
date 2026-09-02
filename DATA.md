# Data guide

Every dataset used in this project, where it came from, what its fields mean, and what's wrong with it.

Nothing under `data/` is committed. `scripts/download_data.sh` fetches and checksum-verifies everything described here.

---

## 1. Global Fishing Watch — apparent fishing effort (primary)

**Source:** Zenodo, DOI [10.5281/zenodo.14982712](https://doi.org/10.5281/zenodo.14982712)
**Version:** 3.0, released 11 March 2025
**Licence:** CC BY-NC 4.0 — non-commercial
**Coverage:** 2012–2024 globally; this project uses 2023–2024

Built from AIS positions of more than 190,000 fishing vessels, of which up to ~96,000 are active in any given year. Vessel time is measured in hours by assigning each AIS position the time elapsed since the vessel's previous position. That time counts as *apparent fishing hours* when GFW's neural-network fishing detection model determines the vessel was engaged in fishing behaviour at that position.

Positions are binned into grid cells; coordinates give the **lower-left corner** in decimal degrees (WGS84).

### Files used

| File | Size | MD5 |
| --- | --- | --- |
| `mmsi-daily-csvs-10-v3-2023.zip` | 739.2 MB | `7b55cca87029903c9becd09b11810455` |
| `mmsi-daily-csvs-10-v3-2024.zip` | 745.7 MB | `51b0988ac6258482c1666c113c93f004` |
| `fishing-vessels-v3.csv` | 114.8 MB | `b5ba27cedd5426c0bcb8e6009e911cf0` |
| `README-known-issues-v3.txt` | 11.1 kB | — |
| `README-mmsi-v3.txt` | 3.4 kB | — |

Each zip contains one CSV per day. They are read from inside the archive and never extracted.

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

Provides flag state, gear type, length, tonnage, engine power, and activity per year.

> **Breaking change in v3 — read this before joining.** In v2, each MMSI had one row with per-year fishing-hours columns. In v3, an MMSI gets **one row per year in which it was active**, with a single `year` column and a single `fishing_hours` column. This was done so vessel classification can change across years as registry information updates.
>
> Consequence: joining vessel metadata to interactions without filtering on `year` will fan out your rows and silently corrupt the matrix. Always constrain the join to the matching year.

Inspect column names on first load rather than assuming them; confirm against `README-fishing-vessels-v3.txt`.

**How the fields are used**

- **Gear type** — the strongest metadata predictor. Trawlers, drifting longliners and purse seiners target structurally different waters. Also a free model sanity check: if learned latent factors don't roughly separate by gear, something is wrong.
- **Length, tonnage, engine power** — proxies for range and capacity. Primary cold-start features, and a sanity filter on physically implausible recommendations.
- **Flag** — fleet-level behavioural signal; secondary cold-start feature.

**Caveat on provenance.** GFW's vessel characterisation model assigns every active MMSI to one of 40 vessel classes and *infers* length, tonnage and engine power. Many vessels have no registry record, so these attributes are model estimates, not verified facts. Registry data quality also varies substantially by flag state, which introduces uneven information across fleets.

### Known issues

Read `README-known-issues-v3.txt` in full before modelling. The significant ones:

1. **2024 is provisional.** Vessel classifications may change as 2025 data arrives.
2. **MMSI is not reliably unique.** It is intended as a unique AIS identifier but this does not always hold in practice — vessels share, reuse, and misconfigure it. Since MMSI is the user key, this is direct noise in the matrix.
3. **Flag state may be wrong.** When a vessel isn't on any registry, flag is derived from the Maritime Identification Digits — the first three digits of the MMSI — which can be entered incorrectly.
4. **AIS reception is uneven and non-stationary.** Coverage varies by region and changes over time. A rise in apparent effort in a region may reflect better satellite reception rather than more fishing. This matters for any temporal comparison and should be stated in results.
5. **Apparent effort, not catch.** Fishing behaviour is inferred from movement patterns. No catch volume or species information exists in this dataset.
6. **Coverage bias.** Vessels without AIS — typically smaller and artisanal — are largely absent, skewing the picture toward industrial fleets.

---

## 2. GEBCO_2026 — seabed depth

**Source:** [download.gebco.net](https://download.gebco.net/) (area-subsetting application)
**Licence:** public domain, free to use with attribution
**Resolution:** 15 arc-second global grid

Published April 2026, the eighth grid produced through the Nippon Foundation–GEBCO Seabed 2030 Project. Provides elevation in metres for ocean and land. Available as netCDF, GeoTIFF or Esri ASCII raster.

**Download a regional subset, not the global file.** The subsetting app lets you request a bounding box, which keeps this to tens of megabytes.

**Use:** aggregate to mean and minimum depth per 0.1° cell. Depth is arguably the strongest physical constraint on which gear can operate where, and it is the single most valuable feature not present in the raw GFW data.

Attribution: *GEBCO Bathymetric Compilation Group 2026, GEBCO_2026 Grid.*

---

## 3. Marine Regions — World EEZ v12

**Source:** [marineregions.org](https://www.marineregions.org/)
**Version:** v12, released 25 October 2023, 122 MB
**Format used:** GeoPackage — a single `.gpkg` file rather than the shapefile's multi-file bundle

200-nautical-mile Exclusive Economic Zone polygons.

Use the standard −180…180 longitude version, not the 0–360 variant, to match GFW's convention. Use the full-resolution version, not low-res.

**Use:** point-in-polygon join tagging each cell with jurisdiction; also the mechanism for scoping analysis to a single EEZ.

```python
import geopandas as gpd
eez = gpd.read_file("data/raw/eez_v12.gpkg")
print(eez.columns)                       # inspect before filtering
aus = eez[eez["SOVEREIGN1"] == "Australia"]
```

Note Australia has several disjoint EEZ polygons — mainland plus external territories such as Heard & McDonald, Norfolk and Christmas Island. Record which you included and why.

---

## 4. GFW Named Anchorages

**Source:** Global Fishing Watch data download portal
**File used:** `named_anchorages_v2_pipe_v4_202608` (18.45 MB, dated 9 January 2026)

Locations where vessels congregate and remain stationary — effectively a global port and anchorage registry.

Two handling notes:

- **Check the delimiter before parsing.** Recent releases carry no `.csv` extension and `pipe` appears in the filename. `head -3` the file and set the separator accordingly. `named_anchorages_v2_20221206.csv` is a plain-CSV fallback with substantially the same port locations.
- **Multiple rows per port.** Anchorages are clustered points, so one port yields many rows. For distance-to-port, take the minimum distance across all anchorage points rather than deduplicating to a single centroid.

**Use:** `distance_to_nearest_port` per cell. Explains range constraints on smaller vessels and materially improves cold-start predictions.

Only the latest snapshot is needed — port locations are near-static, so there's no value in a time series.

---

## 5. WDPA / Protected Planet — marine protected areas *(planned)*

**Source:** [protectedplanet.net](https://www.protectedplanet.net/)

The constraint layer. Recommendations are filtered against MPA polygons at serving time so the system cannot suggest a closed area, and the UI shows the next-best legal alternative instead.

Check the current terms of use before redistributing any derived layer.

---

## Processed artefacts

Written by the pipeline into `data/processed/`, all gitignored.

| Artefact | Description |
| --- | --- |
| `interactions/` | Partitioned Parquet, one partition per year-month |
| `cells.parquet` | Cell dimension: `cell_id`, centroid, depth, EEZ, distance-to-port, MPA flag |
| `vessels.parquet` | Vessel dimension, filtered to the modelling years |
| `matrix.npz` | Sparse vessel × cell CSR matrix plus index mappings |

**Partitioning.** Interactions are partitioned by year and month so temporal-split queries read only the partitions they need. This is what makes the train/test split cheap enough to iterate on.

---

## Reproducing

```bash
./scripts/download_data.sh     # idempotent; skips verified files, checks MD5
python -m src.ingest.build     # zips → partitioned Parquet
python -m src.features.spatial # joins depth, EEZ, port distance
```

Checksums above come from the Zenodo record page. A mismatch means a corrupt or truncated download — delete the file and re-run rather than proceeding.

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
```

Also cite GEBCO Bathymetric Compilation Group 2026, Marine Regions World EEZ v12, and UNEP-WCMC/IUCN Protected Planet where those layers are used.
