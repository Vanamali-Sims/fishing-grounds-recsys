"""MPA flag. WDPA is not on disk — leave null, never coerce to False."""

from __future__ import annotations

import pandas as pd

from src.paths import WDPA_DIR


def attach_mpa(cells: pd.DataFrame) -> pd.DataFrame:
    out = cells.copy()
    if WDPA_DIR.exists():
        raise NotImplementedError(
            f"WDPA is present at {WDPA_DIR} but the MPA join is not implemented yet."
        )
    out["in_mpa"] = pd.Series([pd.NA] * len(out), dtype="boolean")
    return out
