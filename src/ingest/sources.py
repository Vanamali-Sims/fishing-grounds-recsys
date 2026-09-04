"""Daily GFW CSV sources: zip members (preferred) or an extracted directory."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import BinaryIO, Protocol

from src.paths import DAILY_CSV_NAME, DAILY_DIR, DAILY_ZIP

_CSV_NAME = re.compile(
    r"^mmsi-daily-csvs-10-v3-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\.csv$"
)


@dataclass(frozen=True)
class DailyFile:
    year: int
    month: int
    day: int
    name: str
    member: str

    @property
    def file_date(self) -> date:
        return date(self.year, self.month, self.day)

    @property
    def date_str(self) -> str:
        return self.file_date.isoformat()


class DailySource(Protocol):
    format_name: str

    def iter_days(self) -> list[DailyFile]: ...

    def open_csv(self, day: DailyFile) -> BinaryIO: ...

    def close(self) -> None: ...


def parse_daily_name(name: str, member: str | None = None) -> DailyFile | None:
    filename = Path(name).name
    match = _CSV_NAME.match(filename)
    if match is None:
        return None
    return DailyFile(
        year=int(match["year"]),
        month=int(match["month"]),
        day=int(match["day"]),
        name=filename,
        member=member if member is not None else name,
    )


class ZipDailySource:
    format_name = "zip"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(path)

    def iter_days(self) -> list[DailyFile]:
        days: list[DailyFile] = []
        for info in self._zip.infolist():
            parsed = parse_daily_name(info.filename, member=info.filename)
            if parsed is not None:
                days.append(parsed)
        days.sort(key=lambda d: d.file_date)
        return days

    def open_csv(self, day: DailyFile) -> BinaryIO:
        return self._zip.open(day.member, "r")

    def close(self) -> None:
        self._zip.close()


class DirDailySource:
    format_name = "csv_dir"

    def __init__(self, path: Path) -> None:
        self.path = path

    def iter_days(self) -> list[DailyFile]:
        days: list[DailyFile] = []
        for csv_path in self.path.glob("mmsi-daily-csvs-10-v3-*.csv"):
            parsed = parse_daily_name(csv_path.name)
            if parsed is not None:
                days.append(parsed)
        days.sort(key=lambda d: d.file_date)
        return days

    def open_csv(self, day: DailyFile) -> BinaryIO:
        path = self.path / day.name
        if not path.exists():
            # Zip members are stored as the basename; directories should match.
            expected = DAILY_CSV_NAME.format(year=day.year, month=day.month, day=day.day)
            path = self.path / expected
        return path.open("rb")

    def close(self) -> None:
        return None


def open_daily_source(year: int) -> DailySource:
    zip_path = DAILY_ZIP[year]
    dir_path = DAILY_DIR[year]
    if zip_path.exists():
        return ZipDailySource(zip_path)
    if dir_path.exists():
        return DirDailySource(dir_path)
    raise FileNotFoundError(
        f"No daily source for {year}: missing {zip_path.name} and {dir_path.name}"
    )


def iter_sources(years: tuple[int, ...] | list[int]) -> Iterator[tuple[int, DailySource]]:
    for year in years:
        source = open_daily_source(year)
        try:
            yield year, source
        finally:
            source.close()
