"""MPA join: null until a source exists; True/False after a polygon hit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.features.mpa import attach_mpa, find_mpa_source


def _square(lon: float, lat: float, half: float = 0.2) -> dict:
    return {
        "type": "Feature",
        "properties": {"NAME": "Test Park", "ENVIRON": "M"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon - half, lat - half],
                    [lon + half, lat - half],
                    [lon + half, lat + half],
                    [lon - half, lat + half],
                    [lon - half, lat - half],
                ]
            ],
        },
    }


class MpaJoinTests(unittest.TestCase):
    def test_empty_directory_has_no_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_mpa_source(Path(tmp)))

    def test_centroid_inside_polygon_is_true(self) -> None:
        cells = pd.DataFrame(
            {
                "cell_id": ["inside", "outside"],
                "centroid_lat": [-38.45, -30.0],
                "centroid_lon": [141.65, 110.0],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "park.geojson"
            path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [_square(141.65, -38.45)],
                    }
                ),
                encoding="utf-8",
            )
            out = attach_mpa(cells, source=path)
            flagged = out.set_index("cell_id")["in_mpa"]
            self.assertTrue(bool(flagged.loc["inside"]))
            self.assertFalse(bool(flagged.loc["outside"]))
            self.assertFalse(out["in_mpa"].isna().any())


if __name__ == "__main__":
    unittest.main()
