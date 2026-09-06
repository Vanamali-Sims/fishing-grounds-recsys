"""Synthetic checks for B4 ALS and B5 content fold-in."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from src.eval.harness import evaluate
from src.eval.split import (
    build_split,
    load_cold_start_relevant,
    load_new_ground_relevant,
    new_ground_relevant_window,
)
from src.features.matrix import build_csr_from_events
from src.features.policy import TEST_START, VAL_START
from src.features.sparse_matrix import load_csr, save_csr
from src.models.als import fit_als, recommend_als
from src.models.content import (
    encode_vessels,
    fit_foldin,
    hybrid_rankings,
)
from src.models.train import train_and_evaluate


def _write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _cluster_events() -> pa.Table:
    """Two gear clusters. Held-out cells are the cluster-mate grounds."""
    return pa.Table.from_pylist(
        [
            {"mmsi": "T1", "cell_id": "shelf", "date": date(2024, 6, 1), "fishing_hours": 20.0},
            {"mmsi": "T2", "cell_id": "shelf", "date": date(2024, 6, 1), "fishing_hours": 18.0},
            {"mmsi": "T2", "cell_id": "slope", "date": date(2024, 6, 2), "fishing_hours": 15.0},
            {"mmsi": "T3", "cell_id": "shelf", "date": date(2024, 6, 1), "fishing_hours": 12.0},
            {"mmsi": "T3", "cell_id": "slope", "date": date(2024, 11, 1), "fishing_hours": 4.0},
            {"mmsi": "L1", "cell_id": "gyre", "date": date(2024, 6, 1), "fishing_hours": 20.0},
            {"mmsi": "L2", "cell_id": "gyre", "date": date(2024, 6, 1), "fishing_hours": 18.0},
            {"mmsi": "L2", "cell_id": "ridge", "date": date(2024, 6, 2), "fishing_hours": 15.0},
            {"mmsi": "L3", "cell_id": "gyre", "date": date(2024, 6, 1), "fishing_hours": 12.0},
            {"mmsi": "L3", "cell_id": "ridge", "date": date(2024, 11, 1), "fishing_hours": 4.0},
            {"mmsi": "C1", "cell_id": "shelf", "date": date(2024, 11, 2), "fishing_hours": 3.0},
        ]
    )


def _cluster_vessels() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "mmsi": "T1",
                "year": 2024,
                "vessel_class_gfw": "trawlers",
                "flag_gfw": "AUS",
                "length_m_gfw": 40.0,
                "tonnage_gt_gfw": 200.0,
                "engine_power_kw_gfw": 500.0,
            },
            {
                "mmsi": "T2",
                "year": 2024,
                "vessel_class_gfw": "trawlers",
                "flag_gfw": "AUS",
                "length_m_gfw": 42.0,
                "tonnage_gt_gfw": 210.0,
                "engine_power_kw_gfw": 520.0,
            },
            {
                "mmsi": "T3",
                "year": 2024,
                "vessel_class_gfw": "trawlers",
                "flag_gfw": "AUS",
                "length_m_gfw": 38.0,
                "tonnage_gt_gfw": 190.0,
                "engine_power_kw_gfw": 480.0,
            },
            {
                "mmsi": "L1",
                "year": 2024,
                "vessel_class_gfw": "drifting_longlines",
                "flag_gfw": "FJI",
                "length_m_gfw": 25.0,
                "tonnage_gt_gfw": 80.0,
                "engine_power_kw_gfw": 200.0,
            },
            {
                "mmsi": "L2",
                "year": 2024,
                "vessel_class_gfw": "drifting_longlines",
                "flag_gfw": "FJI",
                "length_m_gfw": 26.0,
                "tonnage_gt_gfw": 85.0,
                "engine_power_kw_gfw": 210.0,
            },
            {
                "mmsi": "L3",
                "year": 2024,
                "vessel_class_gfw": "drifting_longlines",
                "flag_gfw": "FJI",
                "length_m_gfw": 24.0,
                "tonnage_gt_gfw": 75.0,
                "engine_power_kw_gfw": 190.0,
            },
            {
                "mmsi": "C1",
                "year": 2024,
                "vessel_class_gfw": "trawlers",
                "flag_gfw": "AUS",
                "length_m_gfw": 41.0,
                "tonnage_gt_gfw": 205.0,
                "engine_power_kw_gfw": 510.0,
            },
        ]
    )


class WindowTests(unittest.TestCase):
    def test_q3_window_excludes_history_and_q4(self) -> None:
        events = pa.Table.from_pylist(
            [
                {"mmsi": "w", "cell_id": "old", "date": date(2024, 6, 1), "fishing_hours": 2.0},
                {"mmsi": "w", "cell_id": "val", "date": date(2024, 8, 1), "fishing_hours": 2.0},
                {"mmsi": "w", "cell_id": "test", "date": date(2024, 11, 1), "fishing_hours": 2.0},
                {"mmsi": "c", "cell_id": "val", "date": date(2024, 8, 1), "fishing_hours": 2.0},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.parquet"
            _write_parquet(events, path)
            relevant = new_ground_relevant_window(path, VAL_START, TEST_START)
        self.assertEqual(relevant, {"w": {"val"}})


class AlsTests(unittest.TestCase):
    def test_cluster_mates_rank_above_the_other_fleet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.parquet"
            _write_parquet(_cluster_events(), events_path)
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
            users, items = fit_als(
                train, factors=8, regularization=0.1, alpha=20.0, iterations=12
            )
            pred = recommend_als(users, items, train, mmsi, cell_id, k=1)
            relevant = load_new_ground_relevant(root / "test.parquet")
        self.assertEqual(relevant["T3"], {"slope"})
        self.assertEqual(relevant["L3"], {"ridge"})
        self.assertEqual(pred["T3"][0], "slope")
        self.assertEqual(pred["L3"][0], "ridge")
        result = evaluate(pred, relevant, catalog_size=len(cell_id), ks=(1,))
        self.assertEqual(result["by_k"]["1"]["precision"], 1.0)


class ColdStartTests(unittest.TestCase):
    def test_foldin_serves_unseen_trawler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_parquet(_cluster_events(), root / "events.parquet")
            _write_parquet(_cluster_vessels(), root / "vessels.parquet")
            matrix, mmsi, cell_id = build_csr_from_events(root / "events.parquet")
            save_csr(root / "matrix.npz", matrix, mmsi, cell_id)
            build_split(
                events_path=root / "events.parquet",
                matrix_path=root / "matrix.npz",
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                force=True,
            )
            result = train_and_evaluate(
                train_path=root / "train.npz",
                test_path=root / "test.parquet",
                events_path=root / "events.parquet",
                vessels_path=root / "vessels.parquet",
                factors_path=root / "als.npz",
                foldin_path=root / "foldin.npz",
                ks=(1,),
                skip_tune=True,
            )
            cold = load_cold_start_relevant(root / "test.parquet")
        self.assertEqual(cold, {"C1": {"shelf"}})
        self.assertEqual(result["models"]["als_warm"]["by_k"]["1"]["precision"], 1.0)
        self.assertEqual(result["models"]["hybrid_cold"]["n_eval_users"], 1)
        self.assertEqual(result["models"]["content_cold"]["by_k"]["1"]["precision"], 1.0)
        self.assertEqual(result["models"]["hybrid_cold"]["by_k"]["1"]["precision"], 1.0)

    def test_hybrid_uses_als_for_warm_and_content_for_cold(self) -> None:
        als = {"warm": ["a"], "cold": ["wrong"]}
        content = {"warm": ["b"], "cold": ["right"]}
        events = pa.Table.from_pylist(
            [
                {"mmsi": "warm", "cell_id": "x", "date": date(2024, 6, 1), "fishing_hours": 1.0},
                {"mmsi": "cold", "cell_id": "y", "date": date(2024, 11, 1), "fishing_hours": 1.0},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.parquet"
            _write_parquet(events, path)
            matrix, mmsi, cell_id = build_csr_from_events(path)
            save_csr(Path(tmp) / "matrix.npz", matrix, mmsi, cell_id)
            build_split(
                events_path=path,
                matrix_path=Path(tmp) / "matrix.npz",
                train_path=Path(tmp) / "train.npz",
                test_path=Path(tmp) / "test.parquet",
                force=True,
            )
            train, mmsi, _ = load_csr(Path(tmp) / "train.npz")
        merged = hybrid_rankings(als, content, train, mmsi)
        self.assertEqual(merged["warm"], ["a"])
        self.assertEqual(merged["cold"], ["right"])


class FoldinMathTests(unittest.TestCase):
    def test_encoder_one_hot_and_intercept(self) -> None:
        table = {
            "1": {
                "gear": "trawlers",
                "flag": "AUS",
                "length_m_gfw": np.e - 1,
                "tonnage_gt_gfw": None,
                "engine_power_kw_gfw": 0.0,
            }
        }
        mmsi = np.array(["1"], dtype="U16")
        features, encoder = encode_vessels(mmsi, table)
        self.assertEqual(features[0, 0], 1.0)
        self.assertEqual(encoder["gear_levels"], ["trawlers"])
        self.assertAlmostEqual(features[0, -3], 1.0)

    def test_ridge_recovers_constant_factor(self) -> None:
        features = np.array([[1.0, 1.0], [1.0, 0.0]])
        user_factors = np.array([[2.0], [2.0]])
        weights = fit_foldin(features, user_factors, np.array([True, True]), ridge=0.0)
        pred = features @ weights
        np.testing.assert_allclose(pred, user_factors, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
