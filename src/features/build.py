"""Entry point: ``python -m src.features.build``.

A3 writes ``data/processed/cells.parquet``: one row per 0.1° cell with
depth, EEZ, distance-to-port, and MPA flag. Not implemented yet.

Inputs (see ``src.paths``): GEBCO GeoTIFF/NetCDF, World EEZ v12 GeoPackage,
GFW named anchorages. WDPA is not on disk — ``in_mpa`` stays null until it is.
"""

from __future__ import annotations

from src.features.schema import CELL_COLUMNS, NULL_POLICY
from src.paths import (
    ANCHORAGES_CSV,
    CELLS_PATH,
    EEZ_GPKG,
    GEBCO_TIF,
    WDPA_DIR,
)


def main() -> None:
    missing = [
        path
        for path, label in (
            (GEBCO_TIF, "GEBCO GeoTIFF"),
            (EEZ_GPKG, "World EEZ GeoPackage"),
            (ANCHORAGES_CSV, "named anchorages CSV"),
        )
        if not path.exists()
    ]
    wdpa_note = (
        "WDPA missing; in_mpa will be null"
        if not WDPA_DIR.exists()
        else f"WDPA present at {WDPA_DIR}"
    )
    raise NotImplementedError(
        "A3 spatial join is not implemented yet. "
        f"target={CELLS_PATH} columns={list(CELL_COLUMNS)} "
        f"missing_inputs={[str(p) for p in missing]} {wdpa_note} "
        f"null_policy={NULL_POLICY}"
    )


if __name__ == "__main__":
    main()
