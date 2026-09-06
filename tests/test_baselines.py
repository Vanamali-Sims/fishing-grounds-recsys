"""Synthetic checks for B3 popularity baselines."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from src.eval.harness import evaluate
from src.eval.split import build_split, load_new_ground_relevant
from src.features.matrix import build_csr_from_events
from src.features.sparse_matrix import load_csr, save_csr
from src.models.baselines import (
    UNKNOWN_GEAR,
    drop_seen,
    evaluate_baselines,
    load_latest_gear,
    predict_popularity,
    predict_popularity_by_gear,
)


def _write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _events() -> pa.Table:
    """Trawlers own cell A; longliners own cell B. Each warm vessel has a new ground."""
    return pa.Table.from_pylist(
        [
            {"mmsi": "T1", "cell_id": "A", "date": date(2024, 6, 1), "fishing_hours": 100.0},
            {"mmsi": "T1", "cell_id": "X", "date": date(2024, 6, 2), "fishing_hours": 1.0},
            {"mmsi": "T2", "cell_id": "A", "date": date(2024, 6, 1), "fishing_hours": 80.0},
            {"mmsi": "T2", "cell_id": "C", "date": date(2024, 11, 1), "fishing_hours": 2.0},
            {"mmsi": "L1", "cell_id": "B", "date": date(2024, 6, 1), "fishing_hours": 50.0},
            {"mmsi": "L1", "cell_id": "Y", "date": date(2024, 6, 2), "fishing_hours": 1.0},
            {"mmsi": "L2", "cell_id": "B", "date": date(2024, 6, 1), "fishing_hours": 40.0},
            {"mmsi": "L2", "cell_id": "D", "date": date(2024, 11, 1), "fishing_hours": 2.0},
        ]
    )


def _vessels() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"mmsi": "T1", "year": 2023, "vessel_class_gfw": "trawlers"},
            {"mmsi": "T1", "year": 2024, "vessel_class_gfw": "trawlers"},
            {"mmsi": "T2", "year": 2024, "vessel_class_gfw": "trawlers"},
            {"mmsi": "L1", "year": 2024, "vessel_class_gfw": "drifting_longlines"},
            {"mmsi": "L2", "year": 2023, "vessel_class_gfw": "trawlers"},
            {"mmsi": "L2", "year": 2024, "vessel_class_gfw": "drifting_longlines"},
        ]
    )


class DropSeenTests(unittest.TestCase):
    def test_skips_history_and_stops_at_k(self) -> None:
        ranked = drop_seen(["a", "b", "c", "d"], {"a", "c"}, k=2)
        self.assertEqual(ranked, ["b", "d"])


class GearLookupTests(unittest.TestCase):
    def test_latest_year_wins_and_missing_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vessels.parquet"
            _write_parquet(_vessels(), path)
            mmsi = np.array(["L2", "T1", "ghost"], dtype="U16")
            gear = load_latest_gear(path, mmsi)
        self.assertEqual(list(gear), ["drifting_longlines", "trawlers", UNKNOWN_GEAR])


class PopularityTests(unittest.TestCase):
    def test_global_ranks_busiest_unseen_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.parquet"
            _write_parquet(_events(), events_path)
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
            pop = predict_popularity(train, mmsi, cell_id, k=3)
        # A has 180h, B 90h. T2 already fished A, so first unseen is B.
        self.assertEqual(pop["T2"][0], "B")
        self.assertNotIn("A", pop["T2"])


class GearNewGroundTests(unittest.TestCase):
    def test_gear_mate_hours_surface_the_held_out_cell(self) -> None:
        """T3 holds out A; other trawlers already made A the trawler-popular cell."""
        events = pa.Table.from_pylist(
            [
                {"mmsi": "T1", "cell_id": "A", "date": date(2024, 6, 1), "fishing_hours": 100.0},
                {"mmsi": "T2", "cell_id": "A", "date": date(2024, 6, 1), "fishing_hours": 80.0},
                {"mmsi": "T3", "cell_id": "X", "date": date(2024, 6, 1), "fishing_hours": 1.0},
                {"mmsi": "T3", "cell_id": "A", "date": date(2024, 11, 1), "fishing_hours": 2.0},
                {"mmsi": "L1", "cell_id": "B", "date": date(2024, 6, 1), "fishing_hours": 50.0},
                {"mmsi": "L2", "cell_id": "Y", "date": date(2024, 6, 1), "fishing_hours": 1.0},
                {"mmsi": "L2", "cell_id": "B", "date": date(2024, 11, 1), "fishing_hours": 2.0},
            ]
        )
        vessels = pa.Table.from_pylist(
            [
                {"mmsi": "T1", "year": 2024, "vessel_class_gfw": "trawlers"},
                {"mmsi": "T2", "year": 2024, "vessel_class_gfw": "trawlers"},
                {"mmsi": "T3", "year": 2024, "vessel_class_gfw": "trawlers"},
                {"mmsi": "L1", "year": 2024, "vessel_class_gfw": "drifting_longlines"},
                {"mmsi": "L2", "year": 2024, "vessel_class_gfw": "drifting_longlines"},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_parquet(events, root / "events.parquet")
            _write_parquet(vessels, root / "vessels.parquet")
            matrix, mmsi, cell_id = build_csr_from_events(root / "events.parquet")
            save_csr(root / "matrix.npz", matrix, mmsi, cell_id)
            build_split(
                events_path=root / "events.parquet",
                matrix_path=root / "matrix.npz",
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                force=True,
            )
            train, mmsi, cell_id = load_csr(root / "train.npz")
            gear = load_latest_gear(root / "vessels.parquet", mmsi)
            pop = predict_popularity(train, mmsi, cell_id, k=1)
            by_gear = predict_popularity_by_gear(train, mmsi, cell_id, gear, k=1)
            relevant = load_new_ground_relevant(root / "test.parquet")
            pop_metrics = evaluate(pop, relevant, catalog_size=len(cell_id), ks=(1,))
            gear_metrics = evaluate(by_gear, relevant, catalog_size=len(cell_id), ks=(1,))
        self.assertEqual(relevant, {"T3": {"A"}, "L2": {"B"}})
        self.assertEqual(pop["T3"][0], "A")  # globally busiest too
        self.assertEqual(by_gear["T3"][0], "A")
        self.assertEqual(by_gear["L2"][0], "B")
        self.assertEqual(pop["L2"][0], "A")
        self.assertEqual(pop_metrics["by_k"]["1"]["precision"], 0.5)
        self.assertEqual(gear_metrics["by_k"]["1"]["precision"], 1.0)

    def test_unknown_gear_uses_global_catalog(self) -> None:
        events = pa.Table.from_pylist(
            [
                {"mmsi": "U", "cell_id": "X", "date": date(2024, 6, 1), "fishing_hours": 1.0},
                {"mmsi": "U", "cell_id": "A", "date": date(2024, 11, 1), "fishing_hours": 2.0},
                {"mmsi": "T1", "cell_id": "A", "date": date(2024, 6, 1), "fishing_hours": 100.0},
            ]
        )
        vessels = pa.Table.from_pylist(
            [{"mmsi": "T1", "year": 2024, "vessel_class_gfw": "trawlers"}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_parquet(events, root / "events.parquet")
            _write_parquet(vessels, root / "vessels.parquet")
            matrix, mmsi, cell_id = build_csr_from_events(root / "events.parquet")
            save_csr(root / "matrix.npz", matrix, mmsi, cell_id)
            build_split(
                events_path=root / "events.parquet",
                matrix_path=root / "matrix.npz",
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                force=True,
            )
            result = evaluate_baselines(
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                vessels_path=root / "vessels.parquet",
                ks=(1,),
            )
        self.assertEqual(result["n_fallback_global"], 1)
        self.assertEqual(result["models"]["popularity"]["by_k"]["1"]["precision"], 1.0)
        self.assertEqual(
            result["models"]["popularity_by_gear"]["by_k"]["1"]["precision"], 1.0
        )


if __name__ == "__main__":
    unittest.main()
