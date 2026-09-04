"""Land fishing-vessels-v3.csv as bronze Parquet with no filters or repairs."""

from __future__ import annotations

import logging

import duckdb

from src.parquet_io import copy_query_to_parquet
from src.paths import BRONZE_VESSELS_PATH, VESSELS_CSV
from src.runtime import PeakMemory

LOG = logging.getLogger(__name__)


def land_vessels(*, force: bool = False, memory: PeakMemory | None = None) -> dict:
    if not VESSELS_CSV.exists():
        raise FileNotFoundError(f"Missing vessel CSV: {VESSELS_CSV}")
    if BRONZE_VESSELS_PATH.exists() and not force:
        LOG.info("bronze vessels already present, skipping (%s)", BRONZE_VESSELS_PATH)
        if memory is not None:
            memory.sample()
        return {
            "skipped": True,
            "output": str(BRONZE_VESSELS_PATH),
            "rows_written": None,
        }

    csv_path = VESSELS_CSV.as_posix()
    con = duckdb.connect()
    try:
        copy_query_to_parquet(
            con,
            """
            SELECT
              CAST(mmsi AS VARCHAR) AS mmsi,
              CAST(year AS INTEGER) AS year,
              flag_ais,
              flag_registry,
              flag_gfw,
              vessel_class_inferred,
              CAST(vessel_class_inferred_score AS DOUBLE) AS vessel_class_inferred_score,
              vessel_class_registry,
              vessel_class_gfw,
              CAST(self_reported_fishing_vessel AS BOOLEAN) AS self_reported_fishing_vessel,
              CAST(length_m_inferred AS DOUBLE) AS length_m_inferred,
              CAST(length_m_registry AS DOUBLE) AS length_m_registry,
              CAST(length_m_gfw AS DOUBLE) AS length_m_gfw,
              CAST(engine_power_kw_inferred AS DOUBLE) AS engine_power_kw_inferred,
              CAST(engine_power_kw_registry AS DOUBLE) AS engine_power_kw_registry,
              CAST(engine_power_kw_gfw AS DOUBLE) AS engine_power_kw_gfw,
              CAST(tonnage_gt_inferred AS DOUBLE) AS tonnage_gt_inferred,
              CAST(tonnage_gt_registry AS DOUBLE) AS tonnage_gt_registry,
              CAST(tonnage_gt_gfw AS DOUBLE) AS tonnage_gt_gfw,
              CAST(registries_listed AS VARCHAR) AS registries_listed,
              CAST(active_hours AS DOUBLE) AS active_hours,
              CAST(fishing_hours AS DOUBLE) AS fishing_hours
            FROM read_csv(?, header=true, sample_size=-1)
            """,
            BRONZE_VESSELS_PATH,
            [csv_path],
        )
        n = con.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [BRONZE_VESSELS_PATH.as_posix()],
        ).fetchone()[0]
    finally:
        con.close()
        if memory is not None:
            memory.sample()

    LOG.info("bronze vessels rows=%s -> %s", f"{n:,}", BRONZE_VESSELS_PATH)
    return {
        "skipped": False,
        "output": str(BRONZE_VESSELS_PATH),
        "rows_written": int(n),
    }
