"""Okapi BM25 keyword ranking, small enough to read in one sitting."""

import math
from collections import Counter
from collections.abc import Sequence


class BM25Index:
    def __init__(self, documents: Sequence[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.term_counts = [Counter(document) for document in documents]
        self.lengths = [len(document) for document in documents]
        self.average_length = sum(self.lengths) / len(documents) if documents else 0.0
        document_frequency: Counter[str] = Counter()
        for counts in self.term_counts:
            document_frequency.update(counts.keys())
        total = len(documents)
        # The +1 inside the log keeps scores positive for very common terms.
        self.idf = {
            term: math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def scores(self, query: Sequence[str]) -> list[float]:
        terms = set(query)
        results = []
        for counts, length in zip(self.term_counts, self.lengths, strict=True):
            score = 0.0
            # Long documents need more occurrences of a term to earn the same score.
            norm = self.k1 * (1 - self.b + self.b * length / (self.average_length or 1.0))
            for term in terms:
                frequency = counts.get(term, 0)
                if frequency:
                    score += self.idf[term] * frequency * (self.k1 + 1) / (frequency + norm)
            results.append(score)
        return results
