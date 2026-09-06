"""Build a small tarball of gold files the API needs to go live.

cells.parquet is slimed to the ALS catalog plus flagged MPA cells so the
archive stays well under 20 MB and Render's 512 MB instance can load it.
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features.sparse_matrix import load_csr
from src.paths import (
    ALS_FACTORS_PATH,
    CELLS_PATH,
    CONTENT_FOLDIN_PATH,
    FISHING_EVENTS_PATH,
    MATRIX_PATH,
    PROCESSED_DIR,
    TRAIN_MATRIX_PATH,
    VESSELS_PATH,
)

OUT = PROCESSED_DIR / "serve_artefacts.tgz"
SLIM_CELLS = PROCESSED_DIR / "cells_serve.parquet"


def slim_cells() -> Path:
    _, _, cell_id = load_csr(TRAIN_MATRIX_PATH)
    catalog = [str(x) for x in cell_id.tolist()]
    source = CELLS_PATH.as_posix().replace("'", "''")
    dest = SLIM_CELLS.as_posix().replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE catalog (cell_id VARCHAR)")
        if catalog:
            con.executemany(
                "INSERT INTO catalog VALUES (?)", [(cell,) for cell in catalog]
            )
        con.execute(
            f"""
            COPY (
              SELECT *
              FROM read_parquet('{source}')
              WHERE cell_id IN (SELECT cell_id FROM catalog)
                 OR in_mpa IS TRUE
            ) TO '{dest}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    return SLIM_CELLS


def main() -> None:
    missing = [
        path
        for path in (
            ALS_FACTORS_PATH,
            CONTENT_FOLDIN_PATH,
            TRAIN_MATRIX_PATH,
            MATRIX_PATH,
            CELLS_PATH,
            VESSELS_PATH,
            FISHING_EVENTS_PATH,
        )
        if not path.exists()
    ]
    if missing:
        raise SystemExit("missing gold files:\n" + "\n".join(str(p) for p in missing))

    slim = slim_cells()
    members = {
        "als_factors.npz": ALS_FACTORS_PATH,
        "content_foldin.npz": CONTENT_FOLDIN_PATH,
        "matrix.npz": MATRIX_PATH,
        "splits/train.npz": TRAIN_MATRIX_PATH,
        "cells.parquet": slim,
        "vessels.parquet": VESSELS_PATH,
        "fishing_events.parquet": FISHING_EVENTS_PATH,
    }
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT, "w:gz") as archive:
        for name, path in members.items():
            archive.add(path, arcname=name)
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"wrote {OUT} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
