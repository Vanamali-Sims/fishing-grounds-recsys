# Notation — bronze, silver, gold

Bronze and silver are two **layers of the same data**, not two datasets.

They come from the medallion pattern used in data pipelines: raw first, clean second. Landing and cleaning are never mixed in one step, because then you cannot tell what the source said versus what we changed.

```
GFW zip / CSV  ──►  bronze  ──►  silver  ──►  gold
                 as landed      cleaned      modelled artefacts
```

| Layer | Meaning | This repo |
| --- | --- | --- |
| **Bronze** | Faithful copy of the source | `data/processed/bronze/` |
| **Silver** | Validated, repaired, derived | `data/processed/interactions/`, `data/processed/vessels.parquet` |
| **Gold** | Model-ready artefacts | `cells.parquet`, `fishing_events.parquet`, `matrix.npz`, `splits/` |

Commands: `python -m src.ingest.build` writes bronze. `python -m src.clean.build` writes silver. `python -m src.pipeline` runs both. `python -m src.features.matrix` writes the gold matrix. `python -m src.eval.report` writes the temporal split. `python -m src.models.baselines` scores popularity on that split.

---

## Bronze — as landed

This is a copy of the GFW files, just in Parquet instead of CSV or zip.

- Same rows, same values
- MMSI kept as text so identity is not damaged by integer conversion
- Empty fields stay null
- No `cell_id`, no `fishing_ratio`, no filling zeros
- Lineage only: `source_file`, `source_format`, `file_date`

**This is what GFW gave us.** If a later rule is wrong, silver can be re-run from bronze without touching the zips again.

2023 is read from inside the zip (never extracted). 2024 falls back to the extracted daily folder because the zip is not on disk.

---

## Silver — as cleaned

This is the table the rest of the project should use.

- **Hard failures** go to **quarantine** with an explicit reason (invalid date, fishing hours greater than presence hours, coordinates off the 0.1° grid, …)
- **Repairs** are applied only on rows that pass hard rules, and are counted (null `fishing_hours` → 0, duplicate key merge, snap to grid within epsilon)
- **Soft issues** stay in the table and are logged (hours > 24, non-9-digit MMSI). They are GFW behaviour, not pipeline bugs.
- Derived fields are added here: `cell_id`, `fishing_ratio`, `year`, `month`

**This is what we are willing to model on, plus an audit of how we got there.**

Transit filtering (low `fishing_ratio`) is **not** applied in silver. Steaming lanes stay in the table so EDA can see them. Dropping transit belongs in matrix construction (B1).

Quarantine lives at `data/processed/quarantine/`. Counts, repairs, observations, and peak RSS are written to `data/processed/reports/`.

---

## Why both

| If you only had… | Problem |
| --- | --- |
| One ingest that also cleans | Silent mutation. You cannot replay or defend a rule change. |
| Only bronze | Downstream (EDA, matrix, model) would re-implement cleaning ad hoc. |
| Only silver | Original values are gone. |

That is why ingest does not handle empty `fishing_hours` internally and write a cleaned CSV. Ingest writes bronze. The cleaning pipeline writes silver.

---

## Gold — modelled artefacts

Gold is not a third copy of the daily table. It is derived from silver for modelling.

- `cells.parquet` — cell dimension (depth, EEZ, port distance, MPA)
- `fishing_events.parquet` — silver rows that survive the B1 transit filter (and EEZ scope)
- `matrix.npz` — vessel × cell CSR over the full modelling window, plus MMSI/cell index maps
- `splits/train.npz` — same maps, Q4 2024 held out
- `splits/test_relevant.parquet` — Q4 cells per vessel, flagged as new-ground or cold-start

Transit filtering (low `fishing_ratio`) happens here, not in silver. The core matrix is scoped to the Australian EEZ; pass `--scope global` to skip that join.

Commands: `python -m src.features.matrix` writes events + CSR. `python -m src.eval.report` writes the temporal split and protocol counts. `python -m src.models.baselines` scores global popularity and popularity-by-gear. Ranking metrics live in `src.eval`; baselines (B3) and ALS (B4) call the harness.

**Evaluation protocol.** Train on 2023 through 2024-09-30, test on Q4 2024. Relevant items for a warm vessel are cells fished in the test window that the vessel did not fish in train (new grounds). Cold-start vessels (first seen in Q4) are counted separately and excluded from collaborative-filtering metrics. Baselines drop those already-fished cells before ranking.
