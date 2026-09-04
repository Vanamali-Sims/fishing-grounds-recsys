"""Unique 0.1° cells observed in silver interactions."""

from __future__ import annotations

import duckdb
import pandas as pd

from src.paths import INTERACTIONS_DIR

CELL_STEP = 0.1
HALF = CELL_STEP / 2.0


def extract_cells() -> pd.DataFrame:
    if not INTERACTIONS_DIR.exists():
        raise FileNotFoundError(f"Missing silver interactions: {INTERACTIONS_DIR}")
    glob = (INTERACTIONS_DIR / "**" / "*.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        df = con.execute(
            """
            SELECT
              cell_id,
              any_value(cell_ll_lat) AS cell_ll_lat,
              any_value(cell_ll_lon) AS cell_ll_lon
            FROM read_parquet(?, hive_partitioning = false)
            GROUP BY cell_id
            """,
            [glob],
        ).df()
    finally:
        con.close()
    df["centroid_lat"] = df["cell_ll_lat"] + HALF
    df["centroid_lon"] = df["cell_ll_lon"] + HALF
    return df
