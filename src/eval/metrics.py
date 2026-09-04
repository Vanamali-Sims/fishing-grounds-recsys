"""Ranking metrics for implicit top-N evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import AbstractSet

import numpy as np


def _require_positive_k(k: int) -> None:
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")


def precision_at_k(ranked: Sequence[str], relevant: AbstractSet[str], k: int) -> float:
    _require_positive_k(k)
    hits = sum(1 for item in ranked[:k] if item in relevant)
    return hits / k


def recall_at_k(ranked: Sequence[str], relevant: AbstractSet[str], k: int) -> float:
    _require_positive_k(k)
    if not relevant:
        raise ValueError("relevant must be non-empty")
    hits = sum(1 for item in ranked[:k] if item in relevant)
    return hits / len(relevant)


def average_precision_at_k(
    ranked: Sequence[str], relevant: AbstractSet[str], k: int
) -> float:
    _require_positive_k(k)
    if not relevant:
        raise ValueError("relevant must be non-empty")
    hits = 0
    score = 0.0
    for i, item in enumerate(ranked[:k], start=1):
        if item in relevant:
            hits += 1
            score += hits / i
    return score / min(len(relevant), k)


def coverage_at_k(
    rankings: Mapping[str, Sequence[str]], catalog_size: int, k: int
) -> float:
    _require_positive_k(k)
    if catalog_size <= 0:
        return 0.0
    recommended: set[str] = set()
    for ranked in rankings.values():
        recommended.update(ranked[:k])
    return len(recommended) / catalog_size


def mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.mean(values))
