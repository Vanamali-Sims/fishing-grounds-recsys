"""B1 matrix construction policy.

Transit stays in silver (EDA needs steaming lanes). It is dropped here.
The README example of 6 presence hours and 0.2 fishing hours is ratio
≈ 0.033 — below MIN_FISHING_RATIO, so it never enters the matrix.

Scope is the Australian EEZ (all six Marine Regions polygons tagged
Australia in A3). Silver stays global; the join happens at matrix time.
"""

from __future__ import annotations

from datetime import date

from src.features.schema import AUS_EEZ_SOVEREIGN

# Drop fishing_ratio = 0 (59% of silver rows) and the EDA (0, 0.05] tail.
MIN_FISHING_RATIO = 0.05

SCOPE_AUS = "aus"
SCOPE_GLOBAL = "global"
SCOPES = (SCOPE_AUS, SCOPE_GLOBAL)
DEFAULT_SCOPE = SCOPE_AUS

# README evaluation protocol: train 2023 through Q3 2024, test Q4 2024.
TEST_START = date(2024, 10, 1)

DEFAULT_KS = (10, 50)
