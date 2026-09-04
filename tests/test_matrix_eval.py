"""Synthetic checks for B1 matrix construction and B2 evaluation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from src.eval.harness import evaluate
from src.eval.metrics import average_precision_at_k, precision_at_k, recall_at_k
from src.eval.split import (
    build_split,
    history_rankings,
    load_cold_start_relevant,
    load_new_ground_relevant,
)
from src.features.events import events_select_sql, register_aus_cells
from src.features.matrix import build, build_csr_from_events
from src.features.policy import MIN_FISHING_RATIO, TEST_START
from src.features.sparse_matrix import load_csr, save_csr


def _silver_table(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                pa.field("date", pa.date32()),
                pa.field("cell_ll_lat", pa.float64()),
                pa.field("cell_ll_lon", pa.float64()),
                pa.field("mmsi", pa.string()),
                pa.field("hours", pa.float64()),
                pa.field("fishing_hours", pa.float64()),
                pa.field("cell_id", pa.string()),
                pa.field("fishing_ratio", pa.float64()),
                pa.field("year", pa.int32()),
                pa.field("month", pa.int32()),
            ]
        ),
    )


def _row(**overrides) -> dict:
    row = {
        "date": date(2024, 6, 1),
        "cell_ll_lat": -42.3,
        "cell_ll_lon": 147.1,
        "mmsi": "503000001",
        "hours": 4.0,
        "fishing_hours": 2.0,
        "cell_id": "-42.3_147.1",
        "fishing_ratio": 0.5,
        "year": 2024,
        "month": 6,
    }
    row.update(overrides)
    if "hours" in overrides or "fishing_hours" in overrides:
        hours = row["hours"]
        fishing = row["fishing_hours"]
        row["fishing_ratio"] = (fishing / hours) if hours else 0.0
    return row


def _write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _cells_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"cell_id": "-42.3_147.1", "eez_sovereign": "Australia"},
            {"cell_id": "35.0_139.0", "eez_sovereign": "Japan"},
        ]
    )


class TransitFilterTests(unittest.TestCase):
    def test_zero_and_low_ratio_dropped(self) -> None:
        table = _silver_table(
            [
                _row(fishing_hours=0.0, hours=6.0),
                _row(
                    mmsi="503000002",
                    fishing_hours=0.2,
                    hours=6.0,
                    fishing_ratio=0.2 / 6.0,
                ),
                _row(mmsi="503000003", fishing_hours=2.0, hours=4.0),
            ]
        )
        con = duckdb.connect()
        try:
            con.register("silver_interactions", table)
            kept = con.execute(
                events_select_sql("global"), [MIN_FISHING_RATIO]
            ).fetchall()
        finally:
            con.close()
        self.assertEqual([row[0] for row in kept], ["503000003"])

    def test_aus_scope_drops_foreign_eez(self) -> None:
        table = _silver_table(
            [
                _row(),
                _row(
                    mmsi="503000009",
                    cell_id="35.0_139.0",
                    cell_ll_lat=35.0,
                    cell_ll_lon=139.0,
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            cells = Path(tmp) / "cells.parquet"
            _write_parquet(_cells_table(), cells)
            con = duckdb.connect()
            try:
                con.register("silver_interactions", table)
                register_aus_cells(con, cells)
                kept = con.execute(
                    events_select_sql("aus"), [MIN_FISHING_RATIO]
                ).fetchall()
            finally:
                con.close()
        self.assertEqual([row[1] for row in kept], ["-42.3_147.1"])


class CsrTests(unittest.TestCase):
    def test_hours_sum_and_roundtrip(self) -> None:
        events = pa.Table.from_pylist(
            [
                {
                    "mmsi": "1",
                    "cell_id": "a",
                    "date": date(2023, 1, 1),
                    "fishing_hours": 1.5,
                },
                {
                    "mmsi": "1",
                    "cell_id": "a",
                    "date": date(2023, 1, 2),
                    "fishing_hours": 2.5,
                },
                {
                    "mmsi": "2",
                    "cell_id": "b",
                    "date": date(2023, 1, 1),
                    "fishing_hours": 4.0,
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.parquet"
            matrix_path = Path(tmp) / "matrix.npz"
            _write_parquet(events, path)
            matrix, mmsi, cell_id = build_csr_from_events(path)
            save_csr(matrix_path, matrix, mmsi, cell_id)
            loaded, m2, c2 = load_csr(matrix_path)
        self.assertEqual(list(mmsi), ["1", "2"])
        self.assertEqual(list(cell_id), ["a", "b"])
        self.assertEqual(matrix.shape, (2, 2))
        self.assertAlmostEqual(matrix[0, 0], 4.0)
        self.assertAlmostEqual(matrix[1, 1], 4.0)
        self.assertEqual(loaded.nnz, matrix.nnz)
        self.assertEqual(list(m2), list(mmsi))
        self.assertEqual(list(c2), list(cell_id))


class SplitTests(unittest.TestCase):
    def test_new_grounds_and_cold_start(self) -> None:
        events = pa.Table.from_pylist(
            [
                {
                    "mmsi": "warm",
                    "cell_id": "old",
                    "date": date(2024, 6, 1),
                    "fishing_hours": 3.0,
                },
                {
                    "mmsi": "warm",
                    "cell_id": "old",
                    "date": date(2024, 11, 1),
                    "fishing_hours": 1.0,
                },
                {
                    "mmsi": "warm",
                    "cell_id": "new",
                    "date": date(2024, 11, 2),
                    "fishing_hours": 2.0,
                },
                {
                    "mmsi": "cold",
                    "cell_id": "new",
                    "date": date(2024, 12, 1),
                    "fishing_hours": 5.0,
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.parquet"
            matrix_path = root / "matrix.npz"
            _write_parquet(events, events_path)
            matrix, mmsi, cell_id = build_csr_from_events(events_path)
            save_csr(matrix_path, matrix, mmsi, cell_id)
            split = build_split(
                events_path=events_path,
                matrix_path=matrix_path,
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                force=True,
            )
            relevant = load_new_ground_relevant(root / "test.parquet")
            cold = load_cold_start_relevant(root / "test.parquet")
            train, _, _ = load_csr(root / "train.npz")
        self.assertEqual(split["test_start"], TEST_START.isoformat())
        self.assertEqual(split["cold_start_vessels"], 1)
        self.assertEqual(split["warm_with_new_grounds"], 1)
        self.assertEqual(relevant, {"warm": {"new"}})
        self.assertEqual(cold, {"cold": {"new"}})
        self.assertEqual(train.nnz, 1)


class MetricsTests(unittest.TestCase):
    def test_perfect_ranking(self) -> None:
        ranked = ["a", "b", "c"]
        relevant = {"a", "b"}
        self.assertEqual(precision_at_k(ranked, relevant, 2), 1.0)
        self.assertEqual(recall_at_k(ranked, relevant, 2), 1.0)
        self.assertEqual(average_precision_at_k(ranked, relevant, 2), 1.0)

    def test_misses_and_map(self) -> None:
        ranked = ["x", "a", "y"]
        relevant = {"a"}
        self.assertEqual(precision_at_k(ranked, relevant, 2), 0.5)
        self.assertEqual(recall_at_k(ranked, relevant, 2), 1.0)
        # hit at rank 2 → AP@2 = (1/2) / min(1, 2) = 0.5
        self.assertEqual(average_precision_at_k(ranked, relevant, 2), 0.5)

    def test_empty_predictions_are_zero(self) -> None:
        relevant = {"u": {"a"}}
        result = evaluate({}, relevant, catalog_size=10, ks=(10,))
        self.assertEqual(result["n_eval_users"], 1)
        self.assertEqual(result["by_k"]["10"]["precision"], 0.0)
        self.assertEqual(result["by_k"]["10"]["recall"], 0.0)
        self.assertEqual(result["by_k"]["10"]["coverage"], 0.0)

    def test_skips_users_with_no_heldout(self) -> None:
        result = evaluate(
            {"u": ["a"]},
            {"u": set(), "v": {"b"}},
            catalog_size=2,
            ks=(1,),
        )
        self.assertEqual(result["n_eval_users"], 1)
        self.assertEqual(result["n_skipped_empty_relevant"], 1)

    def test_history_rankings_zero_on_new_grounds(self) -> None:
        events = pa.Table.from_pylist(
            [
                {
                    "mmsi": "warm",
                    "cell_id": "old",
                    "date": date(2024, 6, 1),
                    "fishing_hours": 3.0,
                },
                {
                    "mmsi": "warm",
                    "cell_id": "new",
                    "date": date(2024, 11, 1),
                    "fishing_hours": 2.0,
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.parquet"
            _write_parquet(events, events_path)
            matrix, mmsi, cell_id = build_csr_from_events(events_path)
            save_csr(root / "matrix.npz", matrix, mmsi, cell_id)
            build_split(
                events_path=events_path,
                matrix_path=root / "matrix.npz",
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                force=True,
            )
            train, mmsi, cell_id = load_csr(root / "train.npz")
            relevant = load_new_ground_relevant(root / "test.parquet")
            predictions = history_rankings(train, mmsi, cell_id)
        result = evaluate(predictions, relevant, catalog_size=2, ks=(10,))
        self.assertEqual(predictions["warm"], ["old"])
        self.assertEqual(result["by_k"]["10"]["precision"], 0.0)


class BuildSkipTests(unittest.TestCase):
    def test_end_to_end_temp_silver(self) -> None:
        silver = _silver_table(
            [
                _row(),
                _row(
                    mmsi="503000002",
                    date=date(2024, 11, 15),
                    year=2024,
                    month=11,
                    cell_id="-42.3_147.2",
                    cell_ll_lat=-42.3,
                    cell_ll_lon=147.2,
                ),
                _row(mmsi="503000003", fishing_hours=0.0, hours=5.0),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            silver_path = root / "silver.parquet"
            cells_path = root / "cells.parquet"
            _write_parquet(silver, silver_path)
            _write_parquet(
                pa.Table.from_pylist(
                    [
                        {"cell_id": "-42.3_147.1", "eez_sovereign": "Australia"},
                        {"cell_id": "-42.3_147.2", "eez_sovereign": "Australia"},
                    ]
                ),
                cells_path,
            )
            result = build(
                scope="aus",
                force=True,
                events_path=root / "events.parquet",
                matrix_path=root / "matrix.npz",
                silver=silver_path.as_posix(),
                cells_path=cells_path,
            )
        self.assertEqual(result["n_users"], 2)
        self.assertEqual(result["nnz"], 2)
        self.assertEqual(result["events"]["transit_or_zero_rows"], 1)


if __name__ == "__main__":
    unittest.main()
