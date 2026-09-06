"""Southern-hemisphere seasons and serving-time seasonal weights.

Summer DJF, autumn MAM, winter JJA, spring SON. Hours in a season are a
prior on the ALS score — not a second model. Cells with no hours in that
season are down-weighted, not dropped.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

SOUTHERN_SEASONS: dict[str, frozenset[int]] = {
    "summer": frozenset({12, 1, 2}),
    "autumn": frozenset({3, 4, 5}),
    "winter": frozenset({6, 7, 8}),
    "spring": frozenset({9, 10, 11}),
}

SEASON_SQL = """
CASE
  WHEN month(date) IN (12, 1, 2) THEN 'summer'
  WHEN month(date) IN (3, 4, 5) THEN 'autumn'
  WHEN month(date) IN (6, 7, 8) THEN 'winter'
  ELSE 'spring'
END
"""

DEFAULT_FLOOR = 0.25


def normalize_season(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    return key if key in SOUTHERN_SEASONS else None


def season_multiplier(hours: float, peak: float, floor: float = DEFAULT_FLOOR) -> float:
    if peak <= 0:
        return 1.0
    share = min(1.0, max(0.0, hours / peak))
    return floor + (1.0 - floor) * share


def load_season_climatology(events_path: Path) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Mean yearly fishing hours per cell per season, plus the season peak."""
    if not events_path.exists():
        empty = {name: {} for name in SOUTHERN_SEASONS}
        return empty, {name: 0.0 for name in SOUTHERN_SEASONS}

    con = duckdb.connect()
    try:
        con.execute("SET enable_progress_bar = false")
        rows = con.execute(
            f"""
            WITH yearly AS (
              SELECT
                cell_id,
                year(date) AS yr,
                {SEASON_SQL} AS season,
                sum(fishing_hours)::DOUBLE AS hours
              FROM read_parquet(?)
              GROUP BY 1, 2, 3
            )
            SELECT cell_id, season, avg(hours)::DOUBLE AS predicted
            FROM yearly
            GROUP BY 1, 2
            """,
            [events_path.as_posix()],
        ).fetchall()
    finally:
        con.close()

    hours: dict[str, dict[str, float]] = {name: {} for name in SOUTHERN_SEASONS}
    peak = {name: 0.0 for name in SOUTHERN_SEASONS}
    for cell_id, season, value in rows:
        if season not in hours:
            continue
        predicted = float(value)
        hours[season][str(cell_id)] = predicted
        if predicted > peak[season]:
            peak[season] = predicted
    return hours, peak
