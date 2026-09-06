"""Southern-hemisphere season helpers."""

from __future__ import annotations

import unittest

from src.features.season import normalize_season, season_multiplier


class SeasonTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_season("Winter"), "winter")
        self.assertIsNone(normalize_season("monsoon"))
        self.assertIsNone(normalize_season(""))

    def test_multiplier_is_not_a_list_reverse(self) -> None:
        self.assertGreater(season_multiplier(10.0, 10.0), season_multiplier(0.0, 10.0))
        self.assertAlmostEqual(season_multiplier(0.0, 10.0), 0.25)
        self.assertAlmostEqual(season_multiplier(10.0, 10.0), 1.0)


if __name__ == "__main__":
    unittest.main()
