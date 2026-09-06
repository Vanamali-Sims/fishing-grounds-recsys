# fishing-grounds-recsys

Collaborative filtering on two years of AIS vessel tracking data to model where commercial fishing vessels operate — with recommendations constrained by marine protected areas, anomaly detection for potential illegal activity, and seasonal effort forecasting.

Built on the Global Fishing Watch public apparent-fishing-effort dataset (2023–2024).

---

## The idea

This is a recommender system with unusual nouns.

| Classic recsys | Here |
| --- | --- |
| user | fishing vessel (MMSI) |
| item | 0.1° ocean grid cell |
| rating | apparent fishing hours logged in that cell |

Vessels × grid cells forms a large, very sparse matrix — any single vessel works a tiny fraction of the ocean. Matrix factorisation learns latent factors from the co-occurrence structure, so the model can score cells a vessel has never visited. *Vessels that fish like you also fish here.*

### Why this is harder than MovieLens

MovieLens gives you explicit ratings: a 2-star review is a stated negative. Here there are no negatives at all. A vessel logging zero hours in a cell might mean:

- out of range for that hull size
- wrong season
- a closed or protected area
- fished by competitors and avoided
- simply never tried

This is **implicit feedback**, and treating absence as dislike would be wrong. The model uses fishing hours as a *confidence weight* on a binary preference rather than as a rating, following the Hu, Koren & Volinsky (2008) formulation.

A second wrinkle specific to this data: presence hours and fishing hours are recorded separately. A cell with 6 presence hours and 0.2 fishing hours is a transit corridor, not a fishing ground. The ingest pipeline uses that ratio to filter transit noise out of the interaction matrix — a domain correction with no analogue in standard recsys.

## Three applications, one model

1. **Ground recommendation** — score unvisited cells for a given vessel, filtered against marine protected areas so recommendations are legal by construction.
2. **Anomaly detection** — flag vessels operating where the model assigns very low probability given their gear type, size and fleet. Low-scoring observed activity is a candidate signal for IUU (illegal, unreported and unregulated) fishing.
3. **Effort forecasting** — project how fishing pressure shifts across regions and seasons.

Application 2 is the interesting one: the same latent factors that generate recommendations also identify activity that doesn't fit the learned patterns.

## Data

| Source | What it provides |
| --- | --- |
| Global Fishing Watch v3 (Zenodo) | Vessel × cell × day fishing hours, 2023–2024; vessel metadata |
| GEBCO_2026 grid | Seabed depth per cell |
| Marine Regions World EEZ v12 | Jurisdiction per cell |
| GFW Named Anchorages | Port locations → distance-to-port per cell |
| WDPA / Protected Planet (Sep 2026 AUS gdb) | Marine/coastal protected-area constraint layer |

Full schemas, provenance, checksums and known caveats: **[DATA.md](DATA.md)**.

Raw data is not committed. Run `scripts/download_data.sh` to fetch and verify it.

## Results

Report against the popularity baseline — a recommender that can't beat "recommend the busiest cells" isn't doing anything.

| Model | Precision@10 | Recall@10 | MAP@10 | Coverage |
| --- | --- | --- | --- | --- |
| Popularity baseline | 0.0011 | 0.0013 | 0.0011 | 0.0012 |
| Popularity by gear type | 0.0040 | 0.0043 | 0.0021 | 0.0068 |
| Implicit ALS | 0.0814 | 0.1149 | 0.0798 | 0.0630 |
| Content fold-in | 0.0192 | 0.0179 | 0.0132 | 0.0193 |

Australian EEZ, 177 warm vessels with Q4 2024 new grounds. ALS (32 factors, α=10) was tuned on Q3 2024 new-grounds, then refit through Q3; it is ~20× popularity-by-gear on the same protocol. Content fold-in (gear, flag, size → user factors) is weaker for warm vessels — that is expected — and is the fallback when a vessel has no train history.

**Cold-start protocol** (9 vessels first seen in Q4): popularity-by-gear P@10 = 0.000; content fold-in P@10 = 0.0556, MAP@10 = 0.0671. Hybrid serving is ALS for warm vessels and fold-in for unseen ones.

**Evaluation protocol.** Temporal split, never random: train on 2023 through Q3 2024, test on Q4 2024. A random split would leak future behaviour into training and inflate every metric. Cold-start vessels (first appearing in the test window) are evaluated separately, since collaborative filtering alone cannot serve them.

## Architecture

```
Zenodo zips ──► ingest (streamed, chunked) ──► partitioned Parquet
                                                     │
                          spatial joins ─────────────┤  depth, EEZ, port distance
                                                     ▼
                                          vessel × cell sparse matrix
                                                     │
                                                     ▼
                                    implicit ALS  ──►  factors + eval
                                                     │
                                          FastAPI ───┴──► React + map UI
```

## Quickstart

```bash
git clone https://github.com/<you>/fishing-grounds-recsys.git
cd fishing-grounds-recsys

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

./scripts/download_data.sh        # ~1.7 GB, verifies checksums
python -m src.ingest.build        # zips → partitioned Parquet
python -m src.features.matrix     # → sparse interaction matrix
python -m src.eval.report         # temporal split + leak check
python -m src.models.baselines    # popularity vs popularity-by-gear
python -m src.models.train        # ALS + content fold-in

uvicorn api.main:app --reload     # API on :8000 (ALS if gold artefacts exist)
cd frontend && npm install && npm run dev
```

## Repository layout

```
├── data/                 # gitignored — fetched via script
├── scripts/
│   └── download_data.sh  # idempotent, checksum-verified
├── src/
│   ├── ingest/           # zip → Parquet, streamed
│   ├── features/         # spatial joins, matrix construction
│   ├── models/           # baselines + ALS
│   └── eval/             # ranking metrics, temporal split
├── api/                  # FastAPI serving layer
├── frontend/             # React + map
├── notebooks/            # EDA only — pipeline logic lives in src/
└── docs/
    ├── engine-choice.md  # benchmark: pandas vs DuckDB vs Spark
    └── model-card.md     # intended use, limitations, failure modes
```

## Engineering notes

**Why DuckDB and not Spark.** One year of the MMSI-daily file is roughly 750 MB compressed. Spark's overhead isn't repaid at this scale, and reaching for it would be cargo-culting. The pipeline uses DuckDB over partitioned Parquet, with a benchmark in `docs/engine-choice.md` establishing where the crossover actually sits. A Spark implementation over the full 2012–2024 history lives on `feature/spark-fullhistory`, where the data volume genuinely justifies it.

**Streaming ingest.** The zips are never extracted. Each daily CSV is read from inside the archive, filtered, and appended to Parquet, so the ~10 GB of raw CSV never touches disk. Peak memory stays bounded regardless of input size.

**Idempotence.** Downloads skip existing verified files; ingest is safe to re-run and adding a year does not require reprocessing prior years.

## Limitations

- **Apparent** fishing effort, not observed catch. Fishing behaviour is inferred by a neural network from AIS movement patterns.
- AIS reception varies geographically and over time; apparent increases in effort may reflect improved satellite coverage rather than more fishing.
- MMSI is not reliably unique per vessel, so vessel identity carries noise.
- Vessel length, tonnage, engine power and class are partly model-inferred rather than registry-confirmed.
- 2024 data is provisional; classifications may shift as later data arrives.
- Small and non-AIS-equipped vessels are largely invisible, biasing coverage toward industrial fleets.

See [DATA.md](DATA.md) and GFW's own `README-known-issues-v3.txt` for the full list.

## Responsible use

A naive reading of this project is "help boats catch more fish," which would be a bad thing to build. Two design choices push against that:

Recommendations are filtered against protected areas and jurisdictional boundaries at serving time, so the system cannot surface a closed area as a suggestion. And the same model is used to *detect* anomalous activity, which is a monitoring capability rather than an extraction one.

This is a portfolio and research project. It is not validated for enforcement decisions, and low model scores are not evidence of illegal activity — they are a prompt for a human to look closer.

## Licence and attribution

Code: MIT.

Data: the Global Fishing Watch apparent fishing effort dataset is licensed **CC BY-NC 4.0** (non-commercial). This project is non-commercial and attributes as follows:

> Global Fishing Watch. *Global AIS-based Apparent Fishing Effort Dataset*, v3.0 (2025). https://doi.org/10.5281/zenodo.14982712

> Kroodsma, D.A., Mayorga, J., Hochberg, T., Miller, N.A., Boerder, K., Ferretti, F., Wilson, A., Bergman, B., White, T.D., Block, B.A., Woods, P., Sullivan, B., Costello, C., & Worm, B. (2018). Tracking the global footprint of fisheries. *Science*, 361(6378).

GEBCO, Marine Regions and WDPA attributions in [DATA.md](DATA.md).