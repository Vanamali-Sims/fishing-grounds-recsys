"""Clean bronze daily interactions into silver Parquet.

Hard-rule failures go to quarantine with an explicit reason. Accepted rows
receive documented repairs (null fishing hours → 0, duplicate key merge,
grid snap within epsilon). Soft issues stay in silver and are counted.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from src.clean.policies import REJECT_REASON_SQL
from src.paths import (
    BRONZE_INTERACTIONS_DIR,
    INTERACTIONS_DIR,
    QUARANTINE_INTERACTIONS_DIR,
    hive_month_dir,
    quarantine_month_path,
    silver_month_path,
)
from src.runtime import PeakMemory

LOG = logging.getLogger(__name__)

_MONTHS = range(1, 13)


def _parquet_glob(directory: Path) -> str:
    return (directory / "*.parquet").as_posix()


def _write_parquet(con: duckdb.DuckDBPyConnection, sql: str, dest: Path, params: list) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    if tmp.exists():
        tmp.unlink()
    con.execute(
        f"COPY ({sql}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
        [*params, tmp.as_posix()],
    )
    n = con.execute("SELECT count(*) FROM read_parquet(?)", [tmp.as_posix()]).fetchone()[0]
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
    return int(n)


def _existing_count(path: Path) -> int:
    if not path.exists():
        return 0
    con = duckdb.connect()
    try:
        return int(con.execute("SELECT count(*) FROM read_parquet(?)", [path.as_posix()]).fetchone()[0])
    finally:
        con.close()


def clean_month(
    year: int,
    month: int,
    *,
    force: bool = False,
    memory: PeakMemory | None = None,
) -> dict:
    bronze_dir = hive_month_dir(BRONZE_INTERACTIONS_DIR, year, month)
    bronze_glob = _parquet_glob(bronze_dir)
    silver_path = silver_month_path(year, month)
    quarantine_path = quarantine_month_path(year, month)

    if not bronze_dir.exists() or not any(bronze_dir.glob("*.parquet")):
        raise FileNotFoundError(f"No bronze partition for {year}-{month:02d}: {bronze_dir}")

    if silver_path.exists() and not force:
        n = _existing_count(silver_path)
        q = _existing_count(quarantine_path)
        LOG.info("silver %s-%02d already present (%s rows), skipping", year, month, f"{n:,}")
        if memory is not None:
            memory.sample()
        return {
            "year": year,
            "month": month,
            "skipped": True,
            "input_rows": None,
            "output_rows": n,
            "quarantined_rows": q,
        }

    con = duckdb.connect()
    try:
        con.execute(
            f"""
            CREATE OR REPLACE TABLE staged AS
            SELECT
              *,
              {REJECT_REASON_SQL} AS reject_reason
            FROM read_parquet(?, hive_partitioning=false, union_by_name=true)
            """,
            [bronze_glob],
        )
        input_rows = con.execute("SELECT count(*) FROM staged").fetchone()[0]

        reason_rows = con.execute(
            """
            SELECT reject_reason, count(*) AS n
            FROM staged
            WHERE reject_reason IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchall()
        reasons = {str(reason): int(n) for reason, n in reason_rows}
        quarantined = int(sum(reasons.values()))

        if quarantined:
            _write_parquet(
                con,
                "SELECT * FROM staged WHERE reject_reason IS NOT NULL",
                quarantine_path,
                [],
            )
        elif quarantine_path.exists():
            quarantine_path.unlink()

        repairs = con.execute(
            """
            SELECT
              count(*) FILTER (WHERE fishing_hours IS NULL) AS null_fishing_hours_to_zero,
              count(*) FILTER (WHERE hours > 24) AS hours_exceed_calendar_day,
              count(*) FILTER (WHERE coalesce(fishing_hours, 0) > 24) AS fishing_hours_exceed_calendar_day,
              count(*) FILTER (WHERE length(trim(CAST(mmsi AS VARCHAR))) <> 9) AS mmsi_not_9_digit
            FROM staged
            WHERE reject_reason IS NULL
            """
        ).fetchone()

        con.execute(
            """
            CREATE OR REPLACE TABLE silver AS
            SELECT
              date,
              cell_ll_lat,
              cell_ll_lon,
              mmsi,
              sum(hours) AS hours,
              sum(fishing_hours) AS fishing_hours,
              cell_id,
              CASE
                WHEN sum(hours) > 0 THEN sum(fishing_hours) / sum(hours)
                ELSE 0.0
              END AS fishing_ratio,
              year(date) AS year,
              month(date) AS month,
              sum(n_source_rows) AS n_source_rows
            FROM (
              SELECT
                try_cast(date AS DATE) AS date,
                round(cell_ll_lat * 10) / 10.0 AS cell_ll_lat,
                round(cell_ll_lon * 10) / 10.0 AS cell_ll_lon,
                trim(CAST(mmsi AS VARCHAR)) AS mmsi,
                hours,
                coalesce(fishing_hours, 0.0) AS fishing_hours,
                printf(
                  '%.1f_%.1f',
                  round(cell_ll_lat * 10) / 10.0,
                  round(cell_ll_lon * 10) / 10.0
                ) AS cell_id,
                1 AS n_source_rows
              FROM staged
              WHERE reject_reason IS NULL
            )
            GROUP BY date, cell_ll_lat, cell_ll_lon, mmsi, cell_id
            """
        )
        dup_stats = con.execute(
            """
            SELECT
              count(*) FILTER (WHERE n_source_rows > 1) AS duplicate_groups,
              coalesce(sum(n_source_rows - 1) FILTER (WHERE n_source_rows > 1), 0) AS duplicate_rows_merged
            FROM silver
            """
        ).fetchone()

        output_rows = _write_parquet(
            con,
            """
            SELECT
              date,
              cell_ll_lat,
              cell_ll_lon,
              mmsi,
              hours,
              fishing_hours,
              cell_id,
              fishing_ratio,
              year,
              month
            FROM silver
            """,
            silver_path,
            [],
        )
    finally:
        con.close()
        if memory is not None:
            memory.sample()

    LOG.info(
        "silver %s-%02d in=%s out=%s quarantined=%s",
        year,
        month,
        f"{input_rows:,}",
        f"{output_rows:,}",
        f"{quarantined:,}",
    )
    return {
        "year": year,
        "month": month,
        "skipped": False,
        "input_rows": int(input_rows),
        "output_rows": output_rows,
        "quarantined_rows": quarantined,
        "quarantine_reasons": reasons,
        "repairs": {
            "null_fishing_hours_to_zero": int(repairs[0]),
            "duplicate_groups": int(dup_stats[0]),
            "duplicate_rows_merged": int(dup_stats[1]),
        },
        "observations": {
            "hours_exceed_calendar_day": int(repairs[1]),
            "fishing_hours_exceed_calendar_day": int(repairs[2]),
            "mmsi_not_9_digit": int(repairs[3]),
        },
        "output": str(silver_path),
    }


def _merge_month_summaries(months: list[dict]) -> dict:
    input_rows = 0
    output_rows = 0
    quarantined = 0
    reasons: dict[str, int] = {}
    repairs = {
        "null_fishing_hours_to_zero": 0,
        "duplicate_groups": 0,
        "duplicate_rows_merged": 0,
    }
    observations = {
        "hours_exceed_calendar_day": 0,
        "fishing_hours_exceed_calendar_day": 0,
        "mmsi_not_9_digit": 0,
    }
    skipped = 0
    for month in months:
        if month.get("skipped"):
            skipped += 1
            output_rows += month.get("output_rows") or 0
            quarantined += month.get("quarantined_rows") or 0
            continue
        input_rows += month["input_rows"]
        output_rows += month["output_rows"]
        quarantined += month["quarantined_rows"]
        for reason, n in month.get("quarantine_reasons", {}).items():
            reasons[reason] = reasons.get(reason, 0) + n
        for key in repairs:
            repairs[key] += month["repairs"][key]
        for key in observations:
            observations[key] += month["observations"][key]
    return {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "quarantined_rows": quarantined,
        "months_skipped": skipped,
        "quarantine_reasons": reasons,
        "repairs": repairs,
        "observations": observations,
        "output": str(INTERACTIONS_DIR),
    }


def clean_interactions(
    years: tuple[int, ...] | list[int],
    *,
    force: bool = False,
    memory: PeakMemory | None = None,
) -> dict[int, dict]:
    INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[int, dict] = {}
    for year in years:
        LOG.info("silver cleaning year %s", year)
        months = [
            clean_month(year, month, force=force, memory=memory) for month in _MONTHS
        ]
        summary[year] = _merge_month_summaries(months)
        summary[year]["months"] = months
        LOG.info(
            "silver year %s in=%s out=%s quarantined=%s",
            year,
            f"{summary[year]['input_rows']:,}",
            f"{summary[year]['output_rows']:,}",
            f"{summary[year]['quarantined_rows']:,}",
        )
    return summary
