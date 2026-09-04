"""Transit-filtered fishing events for the interaction matrix."""

from __future__ import annotations

from pathlib import Path

import duckdb

from src.features.policy import DEFAULT_SCOPE, MIN_FISHING_RATIO, SCOPE_AUS, SCOPES
from src.features.schema import AUS_EEZ_SOVEREIGN
from src.parquet_io import copy_query_to_parquet, sql_path
from src.paths import CELLS_PATH, FISHING_EVENTS_PATH, INTERACTIONS_DIR

EVENT_COLUMNS = ("mmsi", "cell_id", "date", "fishing_hours")


def silver_glob() -> str:
    return (INTERACTIONS_DIR / "**" / "*.parquet").as_posix()


def events_select_sql(scope: str) -> str:
    """SQL over views ``silver_interactions`` and, for AUS, ``aus_cells``."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    scope_join = ""
    if scope == SCOPE_AUS:
        scope_join = "INNER JOIN aus_cells c ON i.cell_id = c.cell_id"
    return f"""
    SELECT
      i.mmsi,
      i.cell_id,
      i.date,
      i.fishing_hours
    FROM silver_interactions i
    {scope_join}
    WHERE i.fishing_hours > 0
      AND i.fishing_ratio >= ?
    """


def _parquet_source(path: str | Path) -> str:
    text = path if isinstance(path, str) else path.as_posix()
    return text.replace("\\", "/").replace("'", "''")


def register_silver(con: duckdb.DuckDBPyConnection, glob: str | None = None) -> None:
    path = glob or silver_glob()
    con.execute(
        "CREATE OR REPLACE VIEW silver_interactions AS "
        f"SELECT * FROM read_parquet('{_parquet_source(path)}', hive_partitioning = false)"
    )


def register_aus_cells(
    con: duckdb.DuckDBPyConnection,
    cells_path: Path | None = None,
) -> None:
    path = cells_path or CELLS_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Missing cells.parquet ({path}). Run python -m src.features.build first."
        )
    sovereign = AUS_EEZ_SOVEREIGN.replace("'", "''")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW aus_cells AS
        SELECT cell_id
        FROM read_parquet('{sql_path(path)}')
        WHERE eez_sovereign = '{sovereign}'
        """
    )


def register_views(
    con: duckdb.DuckDBPyConnection,
    *,
    scope: str = DEFAULT_SCOPE,
    silver: str | None = None,
    cells_path: Path | None = None,
) -> None:
    register_silver(con, silver)
    if scope == SCOPE_AUS:
        register_aus_cells(con, cells_path)


def extract_events(
    dest: Path | None = None,
    *,
    scope: str = DEFAULT_SCOPE,
    min_ratio: float = MIN_FISHING_RATIO,
    silver: str | None = None,
    cells_path: Path | None = None,
) -> dict:
    dest = dest or FISHING_EVENTS_PATH
    if silver is None and not INTERACTIONS_DIR.exists():
        raise FileNotFoundError(f"Missing silver interactions: {INTERACTIONS_DIR}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    join = ""
    if scope == SCOPE_AUS:
        join = "INNER JOIN aus_cells c ON i.cell_id = c.cell_id"
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        register_views(con, scope=scope, silver=silver, cells_path=cells_path)
        con.execute(
            f"""
            CREATE TEMP TABLE scoped AS
            SELECT i.mmsi, i.cell_id, i.date, i.fishing_hours, i.fishing_ratio
            FROM silver_interactions i
            {join}
            """
        )
        counts = scope_counts_from_scoped(con, min_ratio)
        n = write_events_from_scoped(con, dest, min_ratio)
    finally:
        con.close()
    if n != counts["event_rows"]:
        raise RuntimeError(
            f"event row mismatch: wrote {n}, counted {counts['event_rows']}"
        )
    counts["output"] = str(dest)
    counts["output_rows"] = n
    return counts


def scope_counts_from_scoped(
    con: duckdb.DuckDBPyConnection, min_ratio: float
) -> dict:
    row = con.execute(
        """
        SELECT
          count(*) AS in_scope_rows,
          count(*) FILTER (
            WHERE fishing_hours > 0 AND fishing_ratio >= ?
          ) AS event_rows,
          coalesce(sum(fishing_hours) FILTER (
            WHERE fishing_hours > 0 AND fishing_ratio >= ?
          ), 0) AS fishing_hours
        FROM scoped
        """,
        [min_ratio, min_ratio],
    ).fetchone()
    in_scope, events, hours = row
    return {
        "in_scope_rows": int(in_scope),
        "event_rows": int(events),
        "fishing_hours": float(hours),
        "transit_or_zero_rows": int(in_scope) - int(events),
    }


def write_events_from_scoped(
    con: duckdb.DuckDBPyConnection,
    dest: Path,
    min_ratio: float,
) -> int:
    copy_query_to_parquet(
        con,
        """
        SELECT mmsi, cell_id, date, fishing_hours
        FROM scoped
        WHERE fishing_hours > 0 AND fishing_ratio >= ?
        """,
        dest,
        [min_ratio],
    )
    n = con.execute(
        "SELECT count(*) FROM read_parquet(?)", [dest.as_posix()]
    ).fetchone()[0]
    return int(n)

