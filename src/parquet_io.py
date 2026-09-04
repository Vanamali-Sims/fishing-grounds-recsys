"""DuckDB COPY helpers. Destination paths must be literals — mixed ``?``
placeholders bind ``COPY TO`` before ``read_csv``, which lands on a missing tmp file.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def copy_query_to_parquet(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    dest: Path,
    params: list | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    if tmp.exists():
        tmp.unlink()
    con.execute(
        f"COPY ({sql}) TO '{sql_path(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        params or [],
    )
    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
