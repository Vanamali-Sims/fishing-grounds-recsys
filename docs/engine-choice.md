# Engine choice

This slice is two years of GFW MMSI-daily data (~750 MB compressed per year). The pipeline uses **DuckDB over partitioned Parquet**, with PyArrow for bronze CSV landing. Spark is not used here.

## Why DuckDB

| Job | What happens | Why DuckDB |
| --- | --- | --- |
| Silver clean | Month-wise SQL rejects, repairs, hive write | One process, no cluster |
| Matrix events | Transit + EEZ join over silver glob | Predicate pushdown on Parquet |
| Temporal split | Date filter on `fishing_events.parquet` | Seconds, not a job submit |
| Serving stats / history | Point queries on ~1.8 MB events | In-process |

A year of extracted CSV is ~3.4 GB. Streaming zip → Parquet never materialises that on disk as one table. Peak RSS for A3 MPA refresh on 2.3M cells was ~650 MB. That is laptop-sized.

## Where Spark would pay

The README mentions a Spark path for the **full 2012–2024** history. At that volume you want a cluster, checkpointed joins, and a warehouse. This repository does not contain that branch. Reaching for Spark on 2023–2024 would be cargo-culting: startup and shuffle cost more than the query.

## Pandas

Pandas is used where the table is already small: cell dimension after unique-cell extract, vessel metadata, serving-time store (catalog + MPA cells only). It is not the engine for silver.

## Serving RAM

`cells.parquet` is 49 MB and 2.3M global rows. The API **does not** load all of them. The store keeps catalog cells (the ALS item index) plus `in_mpa=True` rows. Gold artefacts for the AUS model total ~64 MB on disk.

## Reproduction

```bash
python -m src.features.matrix   # DuckDB events + CSR
python -m src.eval.report
```

If you later train on the full GFW record, write a real timed comparison before changing engines. This file is that decision for the 2023–2024 Australian EEZ slice.
