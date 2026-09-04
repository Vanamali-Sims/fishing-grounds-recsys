"""Shared process helpers: logging and peak-RSS tracking."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import psutil


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@dataclass
class PeakMemory:
    """Track peak resident set size for the current process."""

    process: psutil.Process
    peak_rss: int = 0

    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
        self.peak_rss = 0
        self.sample()

    def sample(self) -> int:
        rss = int(self.process.memory_info().rss)
        if rss > self.peak_rss:
            self.peak_rss = rss
        return rss

    @property
    def peak_mb(self) -> float:
        return self.peak_rss / (1024 * 1024)
