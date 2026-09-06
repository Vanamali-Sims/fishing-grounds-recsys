"""API contract checks. Works against C1 stubs or C3 live artefacts."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vessels = client.get("/vessels", params={"limit": 20}).json()

    def test_stats(self) -> None:
        res = client.get("/stats")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["years"], [2023, 2024])
        self.assertIn("n_vessels", body)
        self.assertGreater(body["n_vessels"], 0)

    def test_list_vessels_filter(self) -> None:
        self.assertTrue(self.vessels)
        gear = self.vessels[0]["gear"]
        res = client.get("/vessels", params={"gear": gear})
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(rows)
        self.assertTrue(all(v["gear"] == gear for v in rows))
        for row in rows:
            self.assertIn("mmsi", row)
            self.assertIn("flag", row)

    def test_vessel_404(self) -> None:
        self.assertEqual(client.get("/vessels/000").status_code, 404)

    def test_recommendations_exclude_mpa(self) -> None:
        mmsi = self.vessels[0]["mmsi"]
        res = client.get(
            f"/vessels/{mmsi}/recommendations",
            params={"k": 10, "exclude_mpa": True},
        )
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(rows)
        self.assertTrue(all(r["in_mpa"] is not True for r in rows))
        self.assertTrue(all("reason" in r and r["reason"] for r in rows))
        self.assertTrue(all("lat" in r and "lon" in r for r in rows))

    def test_recommendations_include_mpa_keeps_shape(self) -> None:
        mmsi = self.vessels[0]["mmsi"]
        res = client.get(
            f"/vessels/{mmsi}/recommendations",
            params={"exclude_mpa": False, "k": 10},
        )
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(rows)
        self.assertTrue(all("in_mpa" in r for r in rows))
        flagged = [r for r in rows if r["in_mpa"] is True]
        if flagged:
            excluded = client.get(
                f"/vessels/{mmsi}/recommendations",
                params={"exclude_mpa": True, "k": 10},
            ).json()
            self.assertTrue(all(r["in_mpa"] is not True for r in excluded))

    def test_history_and_cell(self) -> None:
        mmsi = self.vessels[0]["mmsi"]
        hist = client.get(f"/vessels/{mmsi}/history")
        self.assertEqual(hist.status_code, 200)
        rows = hist.json()
        self.assertTrue(rows)
        cell_id = rows[0]["cell_id"]
        cell = client.get(f"/cells/{cell_id}")
        self.assertEqual(cell.status_code, 200)
        self.assertEqual(cell.json()["cell_id"], cell_id)

    def test_mpa_cells_shape(self) -> None:
        res = client.get("/mpa-cells", params={"limit": 20})
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIn("cell_id", row)
            self.assertIn("lat", row)
            self.assertIn("lon", row)
        stats = client.get("/stats").json()
        self.assertIn("mpa_ready", stats)
        self.assertIn("n_mpa_cells", stats)

    def test_anomalies_date_filter(self) -> None:
        res = client.get("/anomalies", params={"start": "2024-10-01", "limit": 10})
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(all(row["date"] >= "2024-10-01" for row in rows))
        for row in rows:
            self.assertIn("mmsi", row)
            self.assertIn("score", row)
            self.assertIn("observed_hours", row)


if __name__ == "__main__":
    unittest.main()
