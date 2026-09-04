"""Checks for A3 helpers that do not need the full GEBCO/EEZ files."""

from __future__ import annotations

import unittest

import numpy as np

from src.features.extract import CELL_STEP, HALF
from src.features.ports import haversine_m
from src.features.schema import CELL_COLUMNS, NULL_POLICY


class CellHelpersTests(unittest.TestCase):
    def test_centroid_is_cell_centre(self) -> None:
        self.assertAlmostEqual(HALF, 0.05)
        self.assertAlmostEqual(-38.5 + HALF, -38.45)

    def test_cell_step(self) -> None:
        self.assertEqual(CELL_STEP, 0.1)

    def test_haversine_one_degree_at_equator(self) -> None:
        metres = float(haversine_m(np.array([0.0]), np.array([0.0]), np.array([0.0]), np.array([1.0]))[0])
        self.assertAlmostEqual(metres, 111_194.9, delta=50)

    def test_schema_has_four_join_attributes(self) -> None:
        self.assertIn("depth_mean_m", CELL_COLUMNS)
        self.assertIn("eez_sovereign", CELL_COLUMNS)
        self.assertIn("distance_to_port_m", CELL_COLUMNS)
        self.assertIn("in_mpa", CELL_COLUMNS)
        self.assertIn("in_mpa", NULL_POLICY)


if __name__ == "__main__":
    unittest.main()
