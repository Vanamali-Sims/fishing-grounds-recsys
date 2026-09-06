# Fishing Grounds Recsys — full project guide

This document is the complete walkthrough of the repository: what it is, why it is built this way, every method, the data pipeline, the API, the website, and how the pieces connect. After reading it you should be able to explain the project without opening another file.

Companion docs (detail, not narrative):

- [README.md](../README.md) — short pitch, results table, quickstart
- [DATA.md](../DATA.md) — schemas, provenance, checksums, caveats
- [notation.md](notation.md) — bronze / silver / gold layers
- [engine-choice.md](engine-choice.md) — why DuckDB at this volume
- [model-card.md](model-card.md) — intended use and failure modes
- [deploy.md](deploy.md) — Render free + artefact tarball
- [context/plan.MD](../context/plan.MD) — original phased plan (A/B/C/D)

The UI is called **Sea Anchor**. The repo is `fishing-grounds-recsys`.

---

## 1. What this project is

A recommender system trained on two years of Global Fishing Watch AIS apparent-fishing-effort data (2023–2024). It models **where commercial fishing vessels operate**, then uses that model for three things:

1. **Ground recommendation** — score ocean cells a vessel has never fished, filtered so closed / protected areas are not suggested.
2. **Anomaly detection** — flag vessels operating where the model thinks they are very unlikely to be, given how similar vessels behave. This is a candidate signal for unusual or potentially IUU (illegal, unreported, unregulated) activity, not a verdict.
3. **Effort forecasting** — southern-hemisphere climatology of fishing hours by cell and season (`GET /forecast`). This is a prior from 2023–2024, not a dynamical or weather model.

The core model is implicit collaborative filtering (Hu, Koren & Volinsky 2008 ALS) over a sparse vessel × grid-cell matrix. Warm vessels get ALS. Unseen vessels get a content fold-in from gear, flag, and size onto the same latent space. Serving is a FastAPI contract with a React + deck.gl map.

This is a portfolio / research project. It is not validated for enforcement decisions.

---

## 2. The unusual nouns

| Classic recsys | Here |
| --- | --- |
| user | fishing vessel, keyed by MMSI |
| item | 0.1° ocean grid cell (`{lat}_{lon}` of the lower-left corner) |
| rating | apparent fishing hours in that cell |

A vessel that fishes like you also fishes *here*. The matrix is huge and extremely sparse: any single hull works a tiny fraction of the ocean. Matrix factorisation learns latent factors from co-occurrence, so the model can score cells a vessel has never visited.

MMSI is the Maritime Mobile Service Identity broadcast on AIS. It is intended to be unique per vessel. In practice vessels share, reuse, and misconfigure it, so the user key is noisy. That is a data limitation, not a bug we “fixed.”

---

## 3. Why this is harder than MovieLens

MovieLens gives explicit ratings. A 2-star review is a stated negative. Here there are **no negatives**. Zero hours in a cell can mean:

- out of range for that hull
- wrong season
- a closed or protected area
- fished by competitors and avoided
- simply never tried

Treating absence as dislike would be wrong. This is **implicit feedback**. Fishing hours are a *confidence weight* on a binary preference (the vessel would fish there), not a rating.

A second wrinkle with no analogue in standard recsys: GFW records **presence hours** and **fishing hours** separately. A cell with 6 presence hours and 0.2 fishing hours is a transit corridor, not a fishing ground. The pipeline uses `fishing_ratio = fishing_hours / hours` to drop steaming lanes from the interaction matrix. EDA found ~59% of silver rows have `fishing_ratio = 0`. Those stay in silver so you can still see them; they never enter the model.

---

## 4. What we actually built (vs the plan)

The plan in `context/plan.MD` sequenced work so evaluation existed before the model, and the API contract existed before the frontend. That is still how the repo is organised.

| Phase | Stage | What it is | Status |
| --- | --- | --- | --- |
| A | A1 ingest | Streamed zip/CSV → bronze Parquet, then silver clean | Done |
| A | A2 EDA | Notebook only — gear, seasonality, regions, quality | Done (`notebooks/01_eda.ipynb`) |
| A | A3 spatial | Cell dimension: depth, EEZ, port distance, MPA flag | Done (WDPA AUS gdb, marine/coastal) |
| B | B1 matrix | Transit-filtered fishing events + sparse CSR | Done, scoped to Australian EEZ |
| B | B2 eval | Temporal split, ranking metrics, leak check | Done |
| B | B3 baselines | Global popularity, popularity-by-gear | Done |
| B | B4 ALS | Implicit ALS, tuned on Q3, scored on Q4 | Done |
| B | B5 hybrid | Content fold-in for cold-start vessels | Done |
| C | C1 API stub | FastAPI contract with hardcoded bodies | Done |
| C | C2 frontend | Sea Anchor map UI wired to the contract | Done |
| C | C3 live API | Same contract, gold artefacts + ALS | Done (auto-swaps when artefacts exist) |
| C | C4 polish | MPA overlay, comparison view, loading states | Done |
| D | D1 anomalies | Low-score-but-observed events | Serving-time implementation exists |
| D | D2 engine benchmark | `docs/engine-choice.md` | Done (DuckDB vs Spark at ~750 MB/year; no fake cluster timing) |
| D | D3 model card | `docs/model-card.md` | Done |
| D | D4 deploy setup | Dockerfile + Render free + artefact pack | Wired, not deployed |

The thin working slice the plan wanted (real data → baseline → map) is in place. The live path is: silver → cells → matrix → split → ALS + fold-in → FastAPI → Sea Anchor.

---

## 5. Data

Nothing under `data/` is committed. Raw files are fetched locally. Full field lists and citations live in [DATA.md](../DATA.md).

### 5.1 Global Fishing Watch v3 (primary)

Source: Zenodo DOI `10.5281/zenodo.14982712`, licence CC BY-NC 4.0. Coverage 2012–2024 globally; this project uses 2023–2024.

GFW takes AIS positions from ~190k fishing vessels, assigns each ping the time since the previous ping, and labels a subset as *apparent fishing* with a neural net on movement patterns. Positions are binned into 0.1° cells. Coordinates are the **lower-left corner**.

**Daily interactions** (`mmsi-daily-csvs-10-v3-YYYY-MM-DD.csv`):

| Field | Role |
| --- | --- |
| `date` | Temporal split and seasonality |
| `cell_ll_lat`, `cell_ll_lon` | Half the item key each |
| `mmsi` | User key (kept as text) |
| `hours` | AIS presence in the cell that day |
| `fishing_hours` | Confidence weight |

Derived in silver: `cell_id = "{lat}_{lon}"`, `fishing_ratio`, `year`, `month`.

**Vessel metadata** (`fishing-vessels-v3.csv`): one row per MMSI **per year**. Joining on MMSI alone fans the table out and silently corrupts the matrix. Always join `(mmsi, year)`. Use the `*_gfw` columns (flag, class, length, power, tonnage) unless you need inferred-vs-registry provenance.

Gear (`vessel_class_gfw`) is the strongest metadata signal. Trawlers, drifting longliners and purse seiners target structurally different water. Length / tonnage / engine power are range and capacity proxies, used for cold-start. Flag is a secondary fleet signal.

### 5.2 GEBCO_2026 (depth)

15-arc-second bathymetry, public domain. The file on disk is a **southern-Australia subset** (58.195°S–30.783°S, 99.967°E–159.976°E). It does not cover northern Australian waters or most external-territory EEZs. Depth is aggregated to mean and minimum per 0.1° cell. Cells outside the file bbox get null depth — that is expected.

### 5.3 Marine Regions World EEZ v12

200-nautical-mile Exclusive Economic Zone polygons. Used for two jobs: tag every cell with jurisdiction, and **scope the model to Australia**. Australia has six polygons (mainland plus Christmas, Cocos, Heard & McDonald, Norfolk, Macquarie). High-seas cells have null EEZ; that is a real attribute, not a join failure.

### 5.4 GFW Named Anchorages

Global port / anchorage points. Multiple rows per port. Distance-to-port is the **minimum** geodesic distance from the cell centroid to any anchorage, not distance to a port centroid. Explains range constraints on smaller vessels.

### 5.5 WDPA / Protected Planet

The constraint layer for MPAs. Australian File Geodatabase is on disk (`data/wdpa/WDPA_WDOECM_Sep2026_Public_AUS.gdb`). Cells whose centroid falls in a marine or coastal WDPA polygon are `in_mpa=True`; the rest are `False`. The public CSVs are attributes only.

### 5.6 Important caveats (do not skip)

- Apparent effort, not catch. No species, no landed weight.
- 2024 classifications are provisional.
- AIS reception is uneven and non-stationary. A rise in apparent effort can be better satellites, not more fishing.
- MMSI is not reliably unique.
- Length, tonnage, power and class are often model-inferred.
- Small and non-AIS vessels are largely invisible. Coverage is biased toward industrial fleets.

---

## 6. Architecture

```
Zenodo zips / daily CSVs
        │
        ▼
  bronze Parquet          ← as landed (src.ingest)
        │
        ▼
  silver Parquet          ← validated, repaired, derived (src.clean)
        │                   interactions/ (year/month) + vessels.parquet
        │
        ├─► notebooks/01_eda.ipynb     (read-only exploration)
        │
        ▼
  gold artefacts
        ├─ cells.parquet               depth, EEZ, port, MPA
        ├─ fishing_events.parquet      transit filtered, AUS-scoped
        ├─ matrix.npz                  full-window vessel × cell CSR
        ├─ splits/train.npz            Q4 2024 held out
        └─ splits/test_relevant.parquet
                │
                ▼
        implicit ALS + content fold-in
                │
                ├─ als_factors.npz
                └─ content_foldin.npz
                        │
                        ▼
              FastAPI (api.main)
                live if gold exists, else stubs
                        │
                        ▼
              Sea Anchor (React + deck.gl + MapLibre)
```

**Engine choice.** One year of the MMSI-daily zip is ~750 MB compressed. The pipeline uses DuckDB over partitioned Parquet (and PyArrow for CSV landing). Spark is not used on this 2023–2024 slice. The write-up is [engine-choice.md](engine-choice.md).

**Why medallion layers.** Landing and cleaning are never mixed. If a cleaning rule is wrong, silver can be rebuilt from bronze without touching the zips again. Transit filtering is deliberately *not* a silver rule — steaming lanes belong in EDA.

---

## 7. Pipeline, stage by stage

Every stage is a `python -m …` module. Most are idempotent: existing outputs are skipped unless you pass `--force`. Peak RSS is logged into `data/processed/reports/`.

### 7.1 A1 — bronze landing (`src.ingest`)

Command: `python -m src.ingest.build` or `python -m src.pipeline` (bronze then silver).

**Daily interactions.** `src.ingest.sources` prefers the year zip and falls back to an extracted daily folder (2024 is extracted-only on disk). Zips are never extracted by the pipeline. Each daily CSV is read with PyArrow, MMSI forced to text, empty fields left null, and three lineage columns added: `source_file`, `source_format`, `file_date`. Physically unparseable CSV lines are skipped and written to a sidecar JSONL. No `cell_id`, no `fishing_ratio`, no zero-fills.

Output: `data/processed/bronze/interactions/year=YYYY/month=MM/YYYY-MM-DD.parquet`.

**Vessels.** DuckDB `read_csv` → `data/processed/bronze/vessels.parquet`. Types cast, no year filter, no repairs.

### 7.2 A1 — silver cleaning (`src.clean`)

Command: `python -m src.clean.build`.

Hard-rule failures go to **quarantine** with an explicit reason. Repairs are applied only on accepted rows and counted. Soft issues stay in silver and are logged.

Hard rejects (`src.clean.policies`):

- invalid date, or date ≠ file date
- missing / non-digit MMSI
- missing or out-of-range coordinates
- off the 0.1° grid by more than `1e-4`
- missing / negative hours
- negative fishing hours, or fishing hours > presence + `1e-6`

Repairs on accepted rows:

- null `fishing_hours` → 0
- snap lat/lon to the 0.1° grid
- merge duplicate `(date, cell, mmsi)` keys by summing hours
- add `cell_id`, `fishing_ratio`, `year`, `month`

Soft observations (kept): `hours > 24` (GFW attributes elapsed time since the previous ping, so a parked vessel can dump more than a calendar day into one cell-day), non-9-digit MMSI.

Output: `data/processed/interactions/year=YYYY/month=MM/part.parquet` and `data/processed/vessels.parquet` (modelling years only; duplicate MMSI-year rows quarantined).

Vessels: reject missing/non-digit MMSI and missing year; keep one row per `(mmsi, year)` preferring richer registry listings; drop years outside 2023–2024 from the modelling table (they are not quarantined, just out of window).

### 7.3 A2 — EDA (`notebooks/01_eda.ipynb`)

Exploration only. No pipeline logic. Reads silver. Findings that drove later decisions:

- Two full years, ~84.8M rows each. ~117k distinct MMSIs across both years. Fishing is ~38–39% of presence.
- **~59% of rows have `fishing_ratio = 0`.** That is why B1 uses a 0.05 ratio threshold.
- **Trawlers are 53% of fishing hours** (120.4M of 226.1M) from 48k vessels. A global-popularity baseline is just “recommend the trawl shelf.” Popularity-by-gear is the baseline that matters.
- Seasonality: May–July trough, September–October peak. A Q4 test window is the *busy* season, not a random month.
- Hottest cells are East Asian shelves. A coarse Australian bbox is **0.57% of global fishing hours**. Scoping to the Australian EEZ is a deliberate small, fast, locally relevant matrix — not “where the world’s effort is.”
- `hours > 24` is common (2.1% of rows, max ~48h) and mostly sitting, not frantic fishing. No MMSI is active more days than the calendar. ~1,435 non-9-digit MMSIs remain as user-key noise.

### 7.4 A3 — cell dimension (`src.features.build`)

Command: `python -m src.features.build`.

Unique cells from silver, then four attaches:

1. **Depth** (`depth.py`) — zonal mean/min from the GEBCO GeoTIFF for cells entirely inside the file bbox. Null outside.
2. **EEZ** (`eez.py`) — point-in-polygon on cell centroids with a Shapely STRtree. If a point hits multiple polygons, the smallest `AREA_KM2` wins.
3. **Port distance** (`ports.py`) — unit-sphere KD-tree nearest anchorage, then haversine in metres.
4. **MPA** (`mpa.py`) — WDPA AUS geodatabase, marine/coastal polygons only. Null only if no vector source exists.

Output: `data/processed/cells.parquet`.

### 7.5 B1 — interaction matrix (`src.features.matrix`)

Command: `python -m src.features.matrix` (default `--scope aus`).

From silver:

- inner-join Australian EEZ cells (`eez_sovereign = 'Australia'`)
- keep rows with `fishing_hours > 0` and `fishing_ratio >= 0.05`

The README example of 6 presence / 0.2 fishing is ratio ≈ 0.033 and is dropped. Silver stays global; the join happens here.

Events are written to `fishing_events.parquet` (`mmsi, cell_id, date, fishing_hours`), then aggregated to vessel–cell totals and packed as a SciPy CSR plus string index maps in `matrix.npz`.

### 7.6 B2 — evaluation harness (`src.eval`)

Command: `python -m src.eval.report`.

**Protocol (never a random split):**

- Train: 2023-01-01 through 2024-09-30
- Test: Q4 2024 (from 2024-10-01)
- ALS hyperparameters are chosen on **Q3 2024 new-grounds** (`VAL_START = 2024-07-01`), then the model is refit on the full train window. Q4 is not used for tuning.

**Relevance definitions:**

- **Warm / new grounds:** cells a vessel fished in the test window that it did **not** fish in train. Revisiting last year’s grounds does not count.
- **Cold start:** vessels first seen in Q4. Their Q4 cells are the relevant set. Collaborative filtering alone cannot serve them.

The report writes `splits/train.npz` (same index maps as the full matrix, Q4 hours removed) and `splits/test_relevant.parquet` with `is_new_ground` / `is_cold_start` flags. It also leak-checks: ranking each vessel’s own train cells against new-grounds relevance must score precision 0. If it does not, the split is wrong and the stage raises.

**Metrics** (`src.eval.metrics`, `src.eval.harness`): Precision@k, Recall@k, MAP@k, catalog Coverage@k. Means are over users with a non-empty relevant set. Default k ∈ {10, 50}. Rankings always drop already-fished train cells.

### 7.7 B3 — baselines (`src.models.baselines`)

Command: `python -m src.models.baselines`.

Both rank cells by **train fishing hours** and drop cells the vessel already fished.

- **Popularity** — one global ranking.
- **Popularity-by-gear** — one ranking per latest-year `vessel_class_gfw`. Missing gear falls back to global.

These exist so ALS has to beat “trawlers fish the shelf,” not a straw man.

### 7.8 B4 / B5 — ALS and content fold-in (`src.models.train`)

Command: `python -m src.models.train`.

See §8 for the maths. This stage:

1. Optionally grids ALS on Q3 new-grounds (factors ∈ {32, 64}, α ∈ {10, 20, 40}, reg ∈ {0.01, 0.1, 1.0}).
2. Refits the winner on the full train CSR.
3. Fits a ridge map from vessel metadata → ALS user factors on warm rows only.
4. Scores ALS, content, popularity-by-gear, and a hybrid (ALS if the vessel has train history, fold-in otherwise) on both warm and cold protocols.
5. Writes `als_factors.npz` and `content_foldin.npz`.

Reported README numbers (Australian EEZ, 177 warm vessels with Q4 new grounds; 9 cold-start vessels):

| Model | Precision@10 | Recall@10 | MAP@10 | Coverage |
| --- | --- | --- | --- | --- |
| Popularity | 0.0011 | 0.0013 | 0.0011 | 0.0012 |
| Popularity-by-gear | 0.0040 | 0.0043 | 0.0021 | 0.0068 |
| Implicit ALS (32 factors, α=10) | 0.0814 | 0.1149 | 0.0798 | 0.0630 |
| Content fold-in (warm) | 0.0192 | 0.0179 | 0.0132 | 0.0193 |

ALS is ~20× popularity-by-gear on the same protocol. Content is weaker for warm vessels (expected — they already have collaborative signal) and is the fallback for unseen ones.

Cold-start: popularity-by-gear P@10 = 0.000; content fold-in P@10 = 0.0556, MAP@10 = 0.0671.

---

## 8. Methods

### 8.1 Implicit ALS (Hu, Koren & Volinsky 2008)

Preference is binary: 1 if the vessel fished the cell in train, 0 otherwise. Fishing hours become **confidence**, not a rating:

```
c_ui = 1 + α · log(1 + hours_ui)
```

Unobserved cells stay preference 0 with confidence 1. The default implementation uses `α = 20` if you skip tuning; the reported model used `α = 10`, 32 factors, regularisation 0.1, 12 iterations.

ALS alternates least-squares updates. For each user (then each item), solve a small dense system using the Gram matrix of the opposite factors plus a confidence-weighted correction on the observed columns. Users or items with no observations stay at the zero vector.

Implemented in `src.models.als` — no `implicit` / `lightfm` dependency. Recommendation is `user_vec · item_factors.T`, already-fished columns set to −∞, then top-k.

### 8.2 Content fold-in (cold start)

ALS cannot score a vessel with no train row. Fold-in learns a linear map from metadata to the ALS user-factor space, fit only on warm vessels:

**Features** (one row per MMSI):

- intercept
- one-hot `vessel_class_gfw`
- one-hot `flag_gfw`
- `log1p` of length, tonnage, engine power (median fill if missing)

**Fit:** ridge regression `X_warm W ≈ U_warm`. The intercept column is not ridged. Default ridge = 1.0.

**Predict:** `u_hat = x W`, then the same item-factor inner product as ALS.

**Hybrid serving:** if the train CSR row is non-empty, use ALS factors; otherwise use `x W`.

### 8.3 Anomaly scoring

Same factors, opposite question. For every observed vessel–cell pair in the **full-window** matrix, score `u_v · i_c`. The lowest scores are “this vessel fished here, but vessels like it do not.” Dates are joined back from fishing events. This is a ranked prompt for a human, not evidence of illegal activity.

### 8.4 Serving-time reason strings

Each recommendation carries a `reason` built from cell attributes, e.g. `"118m depth, 42nm from port, typical for trawlers"`. When attributes are missing it falls back to `"scored from vessels with similar grounds"`. The field is what turns a heatmap into something a person can trust.

### 8.5 Season and forecast

Southern-hemisphere seasons (summer DJF, autumn MAM, winter JJA, spring SON). Mean yearly fishing hours per cell per season are computed from `fishing_events.parquet` at store load (`src.features.season`).

- **Seasonal ranking.** ALS scores are multiplied by a 0.25–1.0 weight from that cell’s share of the season peak. Cells unused in the season are down-weighted, not dropped. The stub sorts hardcoded scores; it does not reverse the list as a “winter” trick.
- **Effort forecast.** `GET /forecast` ranks the same climatology as `predicted_hours`. The UI checkbox swaps the right-hand map to those cells. This is last-year’s seasonal map, not a weather or stock forecast.
- **MPA exclusion.** `exclude_mpa=true` drops `in_mpa is True`. Overlay cells come from `GET /mpa-cells` so the shade layer still shows when the filter is on.

---

## 9. Serving API

`uvicorn api.main:app --reload` on port 8000. CORS is open. Version 0.4.0. If `ARTEFACT_URL` is set and gold is missing, the process downloads a tarball on boot (see [deploy.md](deploy.md)).

`api.main` is a thin router. If every gold artefact exists (`als_factors.npz`, `content_foldin.npz`, train + full matrices, cells, vessels, fishing events), it delegates to `api.live`. Otherwise it delegates to `api.stubs`. **The Pydantic shapes in `api.schemas` do not change** between those two backends. That is the C1→C3 contract.

`api.store` loads artefacts once into a process-wide `Store`: train CSR, full CSR, factors, fold-in weights, vessel table, catalog + MPA cells only (not the 2.3M global rows), season climatology, MMSI/cell indexes.

### Endpoints

| Method | Path | Body |
| --- | --- | --- |
| GET | `/vessels?q=&gear=&limit=` | `[{mmsi, name, gear, flag, length}]` |
| GET | `/vessels/{mmsi}` | `{metadata, active_days, top_cells}` |
| GET | `/vessels/{mmsi}/history` | `[{cell_id, lat, lon, fishing_hours}]` |
| GET | `/vessels/{mmsi}/recommendations?k=50&exclude_mpa=true&season=` | `[{cell_id, lat, lon, score, depth, in_mpa, distance_to_port, reason}]` |
| GET | `/cells/{cell_id}` | `{depth, eez, in_mpa, top_gear_types}` |
| GET | `/anomalies?start=&end=&limit=` | `[{mmsi, cell_id, date, score, observed_hours}]` |
| GET | `/mpa-cells?west=&south=&east=&north=` | flagged cells in view |
| GET | `/forecast?season=&exclude_mpa=&k=` | climatology hours |
| GET | `/stats` | dashboard aggregates |
| GET | `/health` | `{ok, live}` |

**Live behaviour worth knowing:**

- Vessel list is every MMSI in the train index, filterable by MMSI substring and gear, sorted by train nnz (most-fished first). Names are always null — GFW has no vessel names in this extract.
- History is the vessel’s fishing-event cells, top 400 by hours.
- Recommendations: warm vessels use stored user factors; cold vessels encode metadata and fold in. Already-fished cells are excluded. Over-fetch, apply season weight if asked, then apply MPA filter.
- Cell detail joins fishing events to vessels on `(mmsi, year)` for top-3 gears.
- Anomalies: lowest inner products on observed pairs, then the earliest event date in the optional window.
- Stats are live counts from `fishing_events.parquet` (AUS-scoped gold), not the global silver totals the stub still quotes.

The stub (`api.stubs`) has five fake vessels around southern Australia / Cook Strait so the frontend could be built before gold existed. Contract tests in `tests/test_api_stub.py` work against whichever backend is live.

---

## 10. The website (Sea Anchor)

`frontend/` is a Vite + React 18 + TypeScript app. Maps are **deck.gl `PolygonLayer`** on a **MapLibre** dark CARTO basemap. Leaflet was rejected in the plan because thousands of grid cells need GPU layers.

Dev server: `npm run dev` on port 5173. Vite proxies `/api` → `http://127.0.0.1:8000`. The client calls `/api/...` (`VITE_API_BASE` defaults to `/api`).

### Layout

```
┌────────────┬──────────────────────────┬──────────────────────────┐
│ Dock       │ Observed                 │ Recommended              │
│            │ (history cells, teak)    │ (scores, foam; MPA red)  │
│ brand      │                          │                          │
│ stats      │     maps locked together │                          │
│ search     │                          │                          │
│ gear/season│                          │                          │
│ MPA toggles│                          │                          │
│ vessel list│                          │                          │
│ detail +   │                          │                          │
│ anomalies  │                          │                          │
└────────────┴──────────────────────────┴──────────────────────────┘
```

The lede on the dock is the product in one sentence: *Same vessel, two questions. Left: where it actually fished. Right: where the model would send it next. Maps stay locked together.*

### Client flow

1. On load: `GET /stats`, `GET /anomalies?limit=8`.
2. Vessel list: `GET /vessels?q=&gear=&limit=50`. Search is debounced 250 ms. Selecting a vessel (or the first in the list) loads detail, history, and recommendations in parallel.
3. Changing `excludeMpa` or `season` refetches recommendations and the climatology forecast. The forecast checkbox swaps the right pane to `GET /forecast`.
4. Both map panes share one `viewState`. Pan/zoom on either side moves the other.
5. Hover/click a cell highlights it on both panes and shows the recommendation `reason` in the dock. Tooltips show hours (left) or score + reason (right).
6. Clicking an anomaly row selects that MMSI and pins its cell.

Cells are drawn as 0.1° squares from the lower-left corner (`cellSquare` in `types.ts`). Fill alpha scales with fishing hours (observed) or model score (recommended). MPA shade is `GET /mpa-cells` for the current map bbox, not the recommendation payload.

Visual language: deep navy dock, teak observed cells, foam recommended cells, red MPA, brass brand. Fonts: Cormorant Garamond + Source Sans 3.

---

## 11. End-to-end flow (data → screen)

What happens when you pick a vessel on the site, assuming gold artefacts exist:

1. Browser `GET /vessels/503…/recommendations?k=50&exclude_mpa=true`.
2. FastAPI sees artefacts, calls `api.live.get_recommendations`.
3. Store looks up the MMSI row. If that row has train hours, the user vector is the ALS factor. If not, metadata is one-hot/log-encoded with the saved encoder and multiplied by the fold-in weights.
4. `recommend_user` scores every catalog cell, blanks out train cells, returns top ~150.
5. Each cell is enriched from `cells.parquet` (depth, distance-to-port in nautical miles, MPA). A reason string is built. MPA rows are dropped if requested. First `k` survive.
6. The right-hand map paints those squares. The left-hand map has already painted `GET /history` hours. Shared camera centres on the history centroid.

Nothing is scored in the browser. The frontend is a contract client.

---

## 12. Repository structure

```
Fisheries/
├── README.md                 short pitch + results + quickstart
├── DATA.md                   every dataset, fields, caveats, citations
├── requirements.txt          Python deps (DuckDB, PyArrow, spatial, FastAPI)
├── docs/
│   ├── project.md            this file
│   ├── notation.md           bronze / silver / gold
│   ├── engine-choice.md
│   ├── model-card.md
│   └── deploy.md
├── scripts/
│   ├── download_data.py      GFW zips + WDPA, MD5 checked
│   └── pack_serve_artefacts.py
├── Dockerfile
├── render.yaml
├── context/                  gitignored — planning notes (plan.MD)
├── data/                     gitignored
│   ├── mmsi-daily-csvs-…     raw GFW (zip and/or extracted)
│   ├── fishing-vessels-v3.csv
│   ├── GEBCO_…/              southern-Australia bathymetry
│   ├── World_EEZ_v12_…/      EEZ GeoPackage
│   ├── named_anchorages_….csv
│   ├── wdpa/                 official AUS File GDB
│   └── processed/            pipeline outputs (also gitignored)
│       ├── bronze/
│       ├── interactions/     silver, hive year=/month=
│       ├── vessels.parquet
│       ├── cells.parquet
│       ├── fishing_events.parquet
│       ├── matrix.npz
│       ├── splits/
│       ├── als_factors.npz
│       ├── content_foldin.npz
│       ├── quarantine/
│       └── reports/          JSON run logs + peak RSS
├── src/
│   ├── paths.py              all filesystem locations
│   ├── runtime.py            logging + PeakMemory
│   ├── parquet_io.py         atomic DuckDB COPY TO parquet
│   ├── pipeline.py           A1: bronze then silver
│   ├── ingest/               bronze landing
│   │   ├── sources.py        zip vs directory daily CSVs
│   │   ├── bronze.py         daily → parquet
│   │   ├── vessels.py        vessel CSV → parquet
│   │   └── build.py          CLI
│   ├── clean/                silver
│   │   ├── policies.py       reject SQL + grid constants
│   │   ├── interactions.py   month-wise clean + quarantine
│   │   ├── vessels.py        year window + dedupe
│   │   ├── report.py         write JSON reports
│   │   └── build.py          CLI
│   ├── features/             A3 + B1
│   │   ├── extract.py        unique cells from silver
│   │   ├── depth.py / eez.py / ports.py / mpa.py / season.py
│   │   ├── schema.py         cell columns + null policy
│   │   ├── policy.py         transit threshold, AUS/global, dates
│   │   ├── events.py         transit + EEZ filter
│   │   ├── sparse_matrix.py  CSR + npz maps
│   │   ├── matrix.py         B1 CLI
│   │   └── build.py          A3 CLI
│   ├── eval/                 B2
│   │   ├── split.py          temporal split + relevance loaders
│   │   ├── metrics.py        P/R/MAP/coverage
│   │   ├── harness.py        mean metrics over users
│   │   └── report.py         CLI + leak check
│   └── models/               B3–B5
│       ├── baselines.py
│       ├── als.py
│       ├── content.py
│       └── train.py
├── api/
│   ├── schemas.py            Pydantic contract
│   ├── stubs.py              C1 hardcoded bodies
│   ├── store.py              load gold once
│   ├── live.py               C3 ALS + fold-in bodies
│   └── main.py               FastAPI router
├── frontend/
│   ├── src/
│   │   ├── App.tsx           dock + dual maps + data loading
│   │   ├── MapPane.tsx       DeckGL + MapLibre
│   │   ├── layers.ts         observed / recommended / MPA polygons
│   │   ├── api.ts            fetch wrappers
│   │   ├── types.ts          shared TS types + cellSquare
│   │   ├── styles.css
│   │   ├── AnchorMark.tsx
│   │   └── main.tsx
│   └── vite.config.ts        /api proxy → :8000
├── notebooks/
│   └── 01_eda.ipynb          A2 only
└── tests/
    ├── test_clean_interactions.py
    ├── test_features_cells.py
    ├── test_matrix_eval.py
    ├── test_baselines.py
    ├── test_als.py
    ├── test_api_stub.py
    └── test_season.py
```

**Convention:** notebooks do not own pipeline logic. The moment cleaning or matrix code lives in a notebook, reproducibility dies. Tests use synthetic tables, not the 1.7 GB raw dump.

`python scripts/download_data.py` fetches GFW zips (MD5 from Zenodo) and the WDPA AUS geodatabase. GEBCO, EEZ, and named anchorages stay manual.

---

## 13. How to run it

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt

# after raw files are in data/
python -m src.ingest.build          # bronze
python -m src.clean.build           # silver
# or: python -m src.pipeline

python -m src.features.build        # cells.parquet
python -m src.features.matrix       # events + CSR (AUS)
python -m src.eval.report           # temporal split + leak check
python -m src.models.baselines      # popularity vs by-gear
python -m src.models.train          # ALS + fold-in

uvicorn api.main:app --reload       # :8000
cd frontend && npm install && npm run dev   # :5173
```

Useful flags: `--force` to rebuild, `--years 2023`, `--scope global` on the matrix, `--skip-tune` on train.

Tests: `python -m unittest discover -s tests`.

---

## 14. Design decisions (the interview versions)

**Eval before model.** The ruler (`src.eval`) was written before ALS. Baselines are scored on it first. That stops unconscious metric-shopping and is the answer to “how did you validate?”

**Temporal split, never random.** A random split leaks future behaviour into training and inflates every number. Q4 is also the busy season, so the test is not an easy winter lull.

**New grounds, not revisits.** Predicting that a trawler returns to last year’s cell is trivial and not useful. Relevance is cells first fished in the holdout window.

**Popularity-by-gear is the real baseline.** Trawlers really do all fish the same shelf. If ALS only tied it, that would be a finding, not a failure.

**Silver keeps transit.** Dropping steaming lanes at clean time would make EDA lie. The ratio cut belongs at matrix construction.

**Australian EEZ on purpose.** Faster iteration, locally relevant, and the global silver table still exists so you can say the pipeline scales and the scope was a choice. A3’s EEZ join is global; B1 is where the cut happens.

**DuckDB, not Spark, at this volume.** ~750 MB/year compressed does not repay a cluster. Streaming ingest never materialises the ~10 GB of raw CSV.

**API stub before frontend.** The contract was frozen in C1. The map was built against fake vessels. C3 swapped bodies without changing shapes.

**Same model, opposite question.** Anomalies reuse ALS factors. That is the monitoring story, and it is why the project is not only “help boats catch more fish.”

**Null MPA, never false.** Coercing missing WDPA to `in_mpa=false` would silently recommend closed areas later. Null means unknown.

---

## 15. Limitations and responsible use

A naive reading is “help boats catch more fish.” Two design choices push against that: recommendations are meant to be filtered against protected areas and jurisdictions at serving time, and the same model is used to detect anomalous activity.

The MPA filter uses WDPA marine/coastal polygons for Australia. It is a coarse constraint: some multiple-use zones still allow fishing. Low model scores remain a prompt, not evidence.

Low model scores are **not evidence of illegal activity**. They are a prompt for a human to look closer. This project is not an enforcement tool.

Licence: code MIT. GFW data CC BY-NC 4.0 (non-commercial). Attribute GFW, Kroodsma et al. 2018, GEBCO 2026, and Flanders Marine Institute EEZ v12 as in DATA.md.

---

## 16. Open gaps (so you do not claim them)

- Fine-grained MPA zoning (no-take vs multiple-use). The WDPA flag treats multiple-use marine parks as closed.
- Season is a climatology prior on ALS scores, not a second latent model or a weather forecast.
- Vessel names (not in the GFW extract)
- Global model (pipeline supports `--scope global`; reported numbers are AUS)
- Spark full-history path (not this tree; see engine-choice.md)

---

## 17. Command cheat sheet

| Command | Writes |
| --- | --- |
| `python -m src.ingest.build` | bronze interactions + vessels |
| `python -m src.clean.build` | silver + quarantine + report |
| `python -m src.pipeline` | both of the above |
| `python -m src.features.build` | `cells.parquet` |
| `python -m src.features.matrix` | `fishing_events.parquet`, `matrix.npz` |
| `python -m src.eval.report` | `splits/`, leak check |
| `python -m src.models.baselines` | `reports/b3_baselines.json` |
| `python -m src.models.train` | `als_factors.npz`, `content_foldin.npz` |
| `python scripts/download_data.py` | GFW zips + WDPA AUS gdb |
| `python scripts/pack_serve_artefacts.py` | `data/processed/serve_artefacts.tgz` |
| `uvicorn api.main:app --reload` | HTTP :8000 |
| `npm run dev` (in `frontend/`) | HTTP :5173 |

If you can walk from a daily GFW CSV to a teal square on the right-hand map, and explain why that square is not a MovieLens rating, you know the project.
