"""Retrieval metrics. Each takes a ranked list of tables and the set of correct ones."""

import math
from collections.abc import Sequence


def recall(retrieved: Sequence[str], gold: set[str]) -> float:
    return len(set(retrieved) & gold) / len(gold) if gold else 0.0


def precision(retrieved: Sequence[str], gold: set[str]) -> float:
    return len(set(retrieved) & gold) / len(retrieved) if retrieved else 0.0


def all_found(retrieved: Sequence[str], gold: set[str]) -> float:
    """SQL generally needs every table, so partial recall can still mean a failed query."""
    return float(bool(gold) and gold <= set(retrieved))


def reciprocal_rank(retrieved: Sequence[str], gold: set[str]) -> float:
    for rank, name in enumerate(retrieved, start=1):
        if name in gold:
            return 1 / rank
    return 0.0


def ndcg(retrieved: Sequence[str], gold: set[str]) -> float:
    gain = sum(1 / math.log2(rank + 1) for rank, name in enumerate(retrieved, 1) if name in gold)
    ideal_hits = min(len(gold), len(retrieved))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return gain / ideal if ideal else 0.0
