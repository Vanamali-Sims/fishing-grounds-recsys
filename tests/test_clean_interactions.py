"""Synthetic checks for interaction hard-reject rules."""

from __future__ import annotations

import unittest
from datetime import date

import duckdb
import pyarrow as pa

from src.clean.policies import REJECT_REASON_ORDER, REJECT_REASON_SQL


def _table(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                pa.field("date", pa.string()),
                pa.field("cell_ll_lat", pa.float64()),
                pa.field("cell_ll_lon", pa.float64()),
                pa.field("mmsi", pa.string()),
                pa.field("hours", pa.float64()),
                pa.field("fishing_hours", pa.float64()),
                pa.field("file_date", pa.date32()),
            ]
        ),
    )


def _reasons(rows: list[dict]) -> list[str | None]:
    con = duckdb.connect()
    try:
        con.register("t", _table(rows))
        result = con.execute(
            f"SELECT {REJECT_REASON_SQL} AS reject_reason FROM t"
        ).fetchall()
        return [row[0] for row in result]
    finally:
        con.close()


def _valid(**overrides) -> dict:
    row = {
        "date": "2023-01-01",
        "cell_ll_lat": -42.3,
        "cell_ll_lon": 147.1,
        "mmsi": "503000001",
        "hours": 2.0,
        "fishing_hours": 1.0,
        "file_date": date(2023, 1, 1),
    }
    row.update(overrides)
    return row


class InteractionRejectRulesTests(unittest.TestCase):
    def test_valid_row_is_kept(self) -> None:
        self.assertEqual(_reasons([_valid()]), [None])

    def test_null_fishing_hours_is_not_a_reject(self) -> None:
        self.assertEqual(_reasons([_valid(fishing_hours=None)]), [None])

    def test_hours_over_24_is_not_a_reject(self) -> None:
        self.assertEqual(_reasons([_valid(hours=46.5, fishing_hours=0.0)]), [None])

    def test_short_mmsi_is_not_a_reject(self) -> None:
        self.assertEqual(_reasons([_valid(mmsi="57636")]), [None])

    def test_invalid_date(self) -> None:
        self.assertEqual(_reasons([_valid(date="not-a-date")]), ["invalid_date"])

    def test_date_file_mismatch(self) -> None:
        self.assertEqual(_reasons([_valid(date="2023-01-02")]), ["date_file_mismatch"])

    def test_missing_mmsi(self) -> None:
        self.assertEqual(_reasons([_valid(mmsi="  ")]), ["missing_mmsi"])

    def test_missing_hours(self) -> None:
        self.assertEqual(_reasons([_valid(hours=None)]), ["missing_hours"])

    def test_missing_coordinates(self) -> None:
        self.assertEqual(_reasons([_valid(cell_ll_lat=None)]), ["missing_coordinates"])

    def test_mmsi_non_digit(self) -> None:
        self.assertEqual(_reasons([_valid(mmsi="ABC123456")]), ["mmsi_non_digit"])

    def test_lat_out_of_range(self) -> None:
        self.assertEqual(_reasons([_valid(cell_ll_lat=95.0)]), ["lat_out_of_range"])

    def test_lon_out_of_range(self) -> None:
        self.assertEqual(_reasons([_valid(cell_ll_lon=200.0)]), ["lon_out_of_range"])

    def test_off_grid(self) -> None:
        self.assertEqual(_reasons([_valid(cell_ll_lat=-42.35)]), ["off_grid"])

    def test_negative_hours(self) -> None:
        self.assertEqual(_reasons([_valid(hours=-0.1)]), ["negative_hours"])

    def test_fishing_exceeds_presence(self) -> None:
        self.assertEqual(
            _reasons([_valid(hours=1.0, fishing_hours=1.5)]),
            ["fishing_exceeds_presence"],
        )

    def test_reason_catalog_covers_sql_literals(self) -> None:
        for reason in REJECT_REASON_ORDER:
            self.assertIn(reason, REJECT_REASON_SQL)


if __name__ == "__main__":
    unittest.main()
