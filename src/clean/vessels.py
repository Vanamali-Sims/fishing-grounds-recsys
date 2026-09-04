"""Clean bronze vessel metadata into the modelling-year dimension table."""

from __future__ import annotations

import logging

import duckdb

from src.paths import BRONZE_VESSELS_PATH, QUARANTINE_VESSELS_PATH, VESSELS_PATH, YEARS
from src.runtime import PeakMemory

LOG = logging.getLogger(__name__)


def _copy_parquet(con: duckdb.DuckDBPyConnection, sql: str, dest, params: list) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    if tmp.exists():
        tmp.unlink()
    con.execute(
        f"COPY ({sql}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
        [*params, tmp.as_posix()],
    )
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)


def clean_vessels(
    years: tuple[int, ...] | list[int] = YEARS,
    *,
    force: bool = False,
    memory: PeakMemory | None = None,
) -> dict:
    if not BRONZE_VESSELS_PATH.exists():
        raise FileNotFoundError(f"No bronze vessels at {BRONZE_VESSELS_PATH}")

    if VESSELS_PATH.exists() and not force:
        con = duckdb.connect()
        try:
            n = int(
                con.execute(
                    "SELECT count(*) FROM read_parquet(?)",
                    [VESSELS_PATH.as_posix()],
                ).fetchone()[0]
            )
        finally:
            con.close()
        LOG.info("silver vessels already present (%s rows), skipping", f"{n:,}")
        if memory is not None:
            memory.sample()
        return {"skipped": True, "output_rows": n, "output": str(VESSELS_PATH)}

    in_years = ", ".join(str(int(y)) for y in years)
    bronze = BRONZE_VESSELS_PATH.as_posix()
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE OR REPLACE TABLE staged AS
            SELECT
              *,
              CASE
                WHEN mmsi IS NULL OR trim(CAST(mmsi AS VARCHAR)) = '' THEN 'missing_mmsi'
                WHEN regexp_matches(trim(CAST(mmsi AS VARCHAR)), '[^0-9]') THEN 'mmsi_non_digit'
                WHEN year IS NULL THEN 'missing_year'
                ELSE NULL
              END AS reject_reason
            FROM read_parquet(?)
            """,
            [bronze],
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE ranked AS
            SELECT
              * EXCLUDE (reject_reason),
              row_number() OVER (
                PARTITION BY trim(CAST(mmsi AS VARCHAR)), year
                ORDER BY registries_listed DESC NULLS LAST, fishing_hours DESC NULLS LAST
              ) AS rn
            FROM staged
            WHERE reject_reason IS NULL
            """
        )

        input_rows = int(con.execute("SELECT count(*) FROM staged").fetchone()[0])
        n_invalid = int(
            con.execute("SELECT count(*) FROM staged WHERE reject_reason IS NOT NULL").fetchone()[0]
        )
        n_dup = int(con.execute("SELECT count(*) FROM ranked WHERE rn > 1").fetchone()[0])
        out_of_window = int(
            con.execute(
                f"SELECT count(*) FROM ranked WHERE rn = 1 AND year NOT IN ({in_years})"
            ).fetchone()[0]
        )
        n_mmsi_not_9 = int(
            con.execute(
                f"""
                SELECT count(*) FROM ranked
                WHERE rn = 1
                  AND year IN ({in_years})
                  AND length(trim(CAST(mmsi AS VARCHAR))) <> 9
                """
            ).fetchone()[0]
        )

        _copy_parquet(
            con,
            f"""
            SELECT
              trim(CAST(mmsi AS VARCHAR)) AS mmsi,
              year,
              flag_ais,
              flag_registry,
              flag_gfw,
              vessel_class_inferred,
              vessel_class_inferred_score,
              vessel_class_registry,
              vessel_class_gfw,
              self_reported_fishing_vessel,
              length_m_inferred,
              length_m_registry,
              length_m_gfw,
              engine_power_kw_inferred,
              engine_power_kw_registry,
              engine_power_kw_gfw,
              tonnage_gt_inferred,
              tonnage_gt_registry,
              tonnage_gt_gfw,
              registries_listed,
              active_hours,
              fishing_hours
            FROM ranked
            WHERE rn = 1 AND year IN ({in_years})
            """,
            VESSELS_PATH,
            [],
        )
        output_rows = int(
            con.execute(
                "SELECT count(*) FROM read_parquet(?)", [VESSELS_PATH.as_posix()]
            ).fetchone()[0]
        )

        quarantined = n_invalid + n_dup
        if quarantined:
            _copy_parquet(
                con,
                """
                SELECT * FROM staged WHERE reject_reason IS NOT NULL
                UNION ALL BY NAME
                SELECT
                  * EXCLUDE (rn),
                  'duplicate_mmsi_year' AS reject_reason
                FROM ranked
                WHERE rn > 1
                """,
                QUARANTINE_VESSELS_PATH,
                [],
            )
        elif QUARANTINE_VESSELS_PATH.exists():
            QUARANTINE_VESSELS_PATH.unlink()
    finally:
        con.close()
        if memory is not None:
            memory.sample()

    LOG.info(
        "silver vessels in=%s modelled=%s excluded_years=%s quarantined=%s",
        f"{input_rows:,}",
        f"{output_rows:,}",
        f"{out_of_window:,}",
        f"{quarantined:,}",
    )
    return {
        "skipped": False,
        "input_rows": input_rows,
        "output_rows": output_rows,
        "excluded_out_of_window": out_of_window,
        "quarantined_rows": quarantined,
        "quarantine_reasons": {
            "invalid": n_invalid,
            "duplicate_mmsi_year": n_dup,
        },
        "observations": {"mmsi_not_9_digit": n_mmsi_not_9},
        "output": str(VESSELS_PATH),
    }
