"""Silver-layer policies for daily interaction rows.

Hard rules reject a row into quarantine. Soft observations stay in silver
and are counted in the quality report. Repairs are applied only on rows that
pass hard rules, and are counted separately so nothing is silent.

Transit filtering (low fishing_ratio) is NOT applied here — that belongs in
matrix construction (B1). This stage must not drop steaming lanes; EDA needs them.
"""

from __future__ import annotations

# Grid is 0.1°. Distances larger than this from a grid line are rejects, not snaps.
GRID_STEP = 0.1
OFF_GRID_EPS = 1e-4

# fishing_hours may exceed hours by float noise; anything larger is a reject.
FISHING_EXCEEDS_EPS = 1e-6

# Calendar-day observations (GFW attributes elapsed time since the previous
# AIS ping, so presence in a cell-day can exceed 24h). Do not reject.
HOURS_IN_DAY = 24.0

ITU_MMSI_LENGTH = 9

REJECT_REASON_ORDER = (
    "invalid_date",
    "date_file_mismatch",
    "missing_mmsi",
    "mmsi_non_digit",
    "missing_coordinates",
    "lat_out_of_range",
    "lon_out_of_range",
    "off_grid",
    "missing_hours",
    "negative_hours",
    "negative_fishing_hours",
    "fishing_exceeds_presence",
)

# DuckDB CASE evaluated in this order (first match wins).
REJECT_REASON_SQL = """
CASE
  WHEN try_cast(date AS DATE) IS NULL THEN 'invalid_date'
  WHEN try_cast(date AS DATE) IS DISTINCT FROM file_date THEN 'date_file_mismatch'
  WHEN mmsi IS NULL OR trim(CAST(mmsi AS VARCHAR)) = '' THEN 'missing_mmsi'
  WHEN regexp_matches(trim(CAST(mmsi AS VARCHAR)), '[^0-9]') THEN 'mmsi_non_digit'
  WHEN cell_ll_lat IS NULL OR cell_ll_lon IS NULL THEN 'missing_coordinates'
  WHEN cell_ll_lat < -90 OR cell_ll_lat > 90 THEN 'lat_out_of_range'
  WHEN cell_ll_lon < -180 OR cell_ll_lon > 180 THEN 'lon_out_of_range'
  WHEN abs(cell_ll_lat * 10 - round(cell_ll_lat * 10)) > 1e-4
    OR abs(cell_ll_lon * 10 - round(cell_ll_lon * 10)) > 1e-4 THEN 'off_grid'
  WHEN hours IS NULL THEN 'missing_hours'
  WHEN hours < 0 THEN 'negative_hours'
  WHEN fishing_hours IS NOT NULL AND fishing_hours < 0 THEN 'negative_fishing_hours'
  WHEN fishing_hours IS NOT NULL AND fishing_hours > hours + 1e-6 THEN 'fishing_exceeds_presence'
  ELSE NULL
END
"""

SILVER_SELECT_SQL = """
SELECT
  try_cast(date AS DATE) AS date,
  round(cell_ll_lat * 10) / 10.0 AS cell_ll_lat,
  round(cell_ll_lon * 10) / 10.0 AS cell_ll_lon,
  trim(CAST(mmsi AS VARCHAR)) AS mmsi,
  hours,
  coalesce(fishing_hours, 0.0) AS fishing_hours,
  printf('%.1f_%.1f', round(cell_ll_lat * 10) / 10.0, round(cell_ll_lon * 10) / 10.0) AS cell_id,
  CASE
    WHEN hours > 0 THEN coalesce(fishing_hours, 0.0) / hours
    ELSE 0.0
  END AS fishing_ratio
FROM accepted
"""
