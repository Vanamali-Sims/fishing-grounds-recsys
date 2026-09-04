"""Evaluate ranked lists against held-out relevant cells."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import AbstractSet

from src.eval.metrics import (
    average_precision_at_k,
    coverage_at_k,
    mean_or_none,
    precision_at_k,
    recall_at_k,
)
from src.features.policy import DEFAULT_KS


def evaluate(
    predictions: Mapping[str, Sequence[str]],
    relevant: Mapping[str, AbstractSet[str]],
    catalog_size: int,
    ks: Sequence[int] = DEFAULT_KS,
) -> dict:
    """Mean ranking metrics over users with a non-empty relevant set.

    Users with no held-out cells are counted in ``n_skipped_empty_relevant``
    and excluded from the means. Missing predictions are empty rankings.
    """
    eval_users = [user for user, items in relevant.items() if items]
    skipped = len(relevant) - len(eval_users)
    rankings = {user: list(predictions.get(user, ())) for user in eval_users}

    by_k: dict[str, dict[str, float]] = {}
    for k in ks:
        precs = [
            precision_at_k(rankings[user], relevant[user], k) for user in eval_users
        ]
        recs = [recall_at_k(rankings[user], relevant[user], k) for user in eval_users]
        aps = [
            average_precision_at_k(rankings[user], relevant[user], k)
            for user in eval_users
        ]
        by_k[str(k)] = {
            "precision": mean_or_none(precs),
            "recall": mean_or_none(recs),
            "map": mean_or_none(aps),
            "coverage": coverage_at_k(rankings, catalog_size, k),
        }

    return {
        "n_eval_users": len(eval_users),
        "n_skipped_empty_relevant": skipped,
        "n_users_in_relevant": len(relevant),
        "ks": list(ks),
        "by_k": by_k,
    }
