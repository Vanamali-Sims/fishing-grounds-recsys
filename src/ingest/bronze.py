"""Land daily CSVs as bronze Parquet.

No repairs, no derived columns, no row drops (except physically unparseable
CSV lines, which are written to a sidecar and counted). MMSI is read as text
so identity is not coerced through an integer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from src.ingest.sources import DailyFile, DailySource, open_daily_source
from src.paths import BRONZE_INTERACTIONS_DIR, REPORTS_DIR, bronze_day_path
from src.runtime import PeakMemory

LOG = logging.getLogger(__name__)

BRONZE_SCHEMA = pa.schema(
    [
        pa.field("date", pa.string()),
        pa.field("cell_ll_lat", pa.float64()),
        pa.field("cell_ll_lon", pa.float64()),
        pa.field("mmsi", pa.string()),
        pa.field("hours", pa.float64()),
        pa.field("fishing_hours", pa.float64()),
        pa.field("source_file", pa.string()),
        pa.field("source_format", pa.string()),
        pa.field("file_date", pa.date32()),
    ]
)

_CONVERT = pacsv.ConvertOptions(
    column_types={
        "date": pa.string(),
        "cell_ll_lat": pa.float64(),
        "cell_ll_lon": pa.float64(),
        "mmsi": pa.string(),
        "hours": pa.float64(),
        "fishing_hours": pa.float64(),
    },
    include_columns=[
        "date",
        "cell_ll_lat",
        "cell_ll_lon",
        "mmsi",
        "hours",
        "fishing_hours",
    ],
    null_values=["", "NA", "NaN", "null", "NULL"],
    strings_can_be_null=True,
)


def _read_daily_csv(
    handle,
    source_file: str,
    source_format: str,
    file_date,
    invalid_rows: list[dict],
) -> pa.Table:
    def _on_invalid(row: pacsv.InvalidRow) -> str:
        invalid_rows.append(
            {
                "source_file": source_file,
                "row_number": row.row_number,
                "text": row.text,
            }
        )
        return "skip"

    parse_options = pacsv.ParseOptions(invalid_row_handler=_on_invalid)
    table = pacsv.read_csv(handle, parse_options=parse_options, convert_options=_CONVERT)
    n = table.num_rows
    table = table.append_column("source_file", pa.array([source_file] * n, pa.string()))
    table = table.append_column("source_format", pa.array([source_format] * n, pa.string()))
    table = table.append_column("file_date", pa.array([file_date] * n, pa.date32()))
    return table.cast(BRONZE_SCHEMA)


def land_year(
    year: int,
    *,
    force: bool = False,
    memory: PeakMemory | None = None,
    on_progress: Callable[[DailyFile, int, bool], None] | None = None,
) -> dict:
    source: DailySource = open_daily_source(year)
    invalid_rows: list[dict] = []
    files_written = 0
    files_skipped = 0
    rows = 0
    try:
        days = source.iter_days()
        if not days:
            raise FileNotFoundError(f"No daily CSV files found for {year}")
        expected = 366 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 365
        if len(days) != expected:
            LOG.warning(
                "year %s: expected %s daily files, found %s",
                year,
                expected,
                len(days),
            )
        for day in days:
            out = bronze_day_path(day.year, day.month, day.day)
            if out.exists() and not force:
                files_skipped += 1
                if memory is not None:
                    memory.sample()
                if on_progress is not None:
                    on_progress(day, 0, True)
                continue
            with source.open_csv(day) as handle:
                table = _read_daily_csv(
                    handle,
                    source_file=day.name,
                    source_format=source.format_name,
                    file_date=day.file_date,
                    invalid_rows=invalid_rows,
                )
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".parquet.tmp")
            pq.write_table(table, tmp, compression="zstd")
            tmp.replace(out)
            files_written += 1
            rows += table.num_rows
            if memory is not None:
                memory.sample()
            if on_progress is not None:
                on_progress(day, table.num_rows, False)
            LOG.info(
                "bronze %s %s rows=%s source=%s",
                day.date_str,
                source.format_name,
                f"{table.num_rows:,}",
                day.name,
            )
    finally:
        source.close()

    if invalid_rows:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        sidecar = REPORTS_DIR / f"bronze_invalid_csv_rows_{year}.jsonl"
        with sidecar.open("w", encoding="utf-8") as fh:
            for item in invalid_rows:
                fh.write(json.dumps(item) + "\n")
        LOG.warning(
            "year %s: skipped %s physically invalid CSV rows; wrote %s",
            year,
            len(invalid_rows),
            sidecar,
        )

    return {
        "year": year,
        "source_format": source.format_name,
        "files_seen": files_written + files_skipped,
        "files_written": files_written,
        "files_skipped": files_skipped,
        "rows_written": rows,
        "invalid_csv_rows": len(invalid_rows),
        "output": str(BRONZE_INTERACTIONS_DIR / f"year={year}"),
    }


def land_interactions(
    years: tuple[int, ...] | list[int],
    *,
    force: bool = False,
    memory: PeakMemory | None = None,
) -> dict[int, dict]:
    BRONZE_INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[int, dict] = {}
    for year in years:
        LOG.info("bronze landing year %s", year)
        summary[year] = land_year(year, force=force, memory=memory)
        LOG.info(
            "bronze year %s written=%s skipped=%s rows=%s invalid_csv=%s",
            year,
            summary[year]["files_written"],
            summary[year]["files_skipped"],
            f"{summary[year]['rows_written']:,}",
            summary[year]["invalid_csv_rows"],
        )
    return summary
