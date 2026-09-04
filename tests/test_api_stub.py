"""C1 stub contract checks. Bodies are fake; shapes must survive into C3."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class ApiStubTests(unittest.TestCase):
    def test_stats(self) -> None:
        res = client.get("/stats")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["years"], [2023, 2024])
        self.assertIn("n_vessels", body)

    def test_list_vessels_filter(self) -> None:
        res = client.get("/vessels", params={"gear": "trawlers"})
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(rows)
        self.assertTrue(all(v["gear"] == "trawlers" for v in rows))

    def test_vessel_404(self) -> None:
        self.assertEqual(client.get("/vessels/000").status_code, 404)

    def test_recommendations_exclude_mpa(self) -> None:
        res = client.get(
            "/vessels/503000001/recommendations",
            params={"k": 10, "exclude_mpa": True},
        )
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        self.assertTrue(rows)
        self.assertTrue(all(r["in_mpa"] is not True for r in rows))
        self.assertTrue(all("reason" in r for r in rows))

    def test_recommendations_include_mpa(self) -> None:
        res = client.get(
            "/vessels/503000001/recommendations",
            params={"exclude_mpa": False},
        )
        self.assertTrue(any(r["in_mpa"] is True for r in res.json()))

    def test_history_and_cell(self) -> None:
        hist = client.get("/vessels/503000001/history")
        self.assertEqual(hist.status_code, 200)
        self.assertTrue(hist.json())
        cell = client.get("/cells/-38.5_141.6")
        self.assertEqual(cell.status_code, 200)
        self.assertEqual(cell.json()["eez"], "Australia")

    def test_anomalies_date_filter(self) -> None:
        res = client.get("/anomalies", params={"start": "2024-10-01"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(row["date"] >= "2024-10-01" for row in res.json()))


if __name__ == "__main__":
    unittest.main()
