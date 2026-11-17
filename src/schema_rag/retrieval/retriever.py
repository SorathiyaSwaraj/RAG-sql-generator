"""Hybrid retrieval over tables and procedures, plus foreign-key expansion."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from schema_rag.models import Procedure, SchemaCatalog
from schema_rag.retrieval.bm25 import BM25Index
from schema_rag.retrieval.documents import (
    column_text,
    procedure_search_text,
    table_search_text,
    table_summary_text,
    tokenize,
)
from schema_rag.retrieval.embeddings import Embedder
from schema_rag.retrieval.graph import SchemaGraph

Mode = Literal["dense", "bm25", "hybrid", "hybrid_graph"]
MODES: tuple[Mode, ...] = ("dense", "bm25", "hybrid", "hybrid_graph")
_RRF_K = 60


@dataclass
class RetrievalResult:
    seeds: list[str]
    connectors: list[str]
    procedures: list[Procedure]

    @property
    def tables(self) -> list[str]:
        return self.seeds + self.connectors


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = _RRF_K) -> list[str]:
    """Merge rankings using positions only, because BM25 and cosine scores are not comparable."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, name in enumerate(ranking, start=1):
            scores[name] = scores.get(name, 0.0) + 1 / (k + rank)
    return [name for name, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


class SchemaRetriever:
    """Each table gets one summary vector and one vector per column.

    The embedding model only reads about 512 tokens, so one vector for a 97-column
    table would lose most of it. A table scores as its best-matching vector.
    """

    def __init__(
        self, catalog: SchemaCatalog, embedder: Embedder, cache_dir: Path | None = None
    ) -> None:
        self.catalog = catalog
        self.embedder = embedder
        self.graph = SchemaGraph(catalog)
        self.table_names = [table.name for table in catalog.tables]

        self.vector_owners: list[str] = []
        texts: list[str] = []
        for table in catalog.tables:
            self.vector_owners.append(table.name)
            texts.append(table_summary_text(table))
            for column in table.columns:
                self.vector_owners.append(table.name)
                texts.append(column_text(table, column))
        self.vectors = _embed_cached(embedder, texts, cache_dir)
        self.table_bm25 = BM25Index([tokenize(table_search_text(t)) for t in catalog.tables])

        procedure_texts = [procedure_search_text(p) for p in catalog.procedures]
        self.procedure_vectors = _embed_cached(embedder, procedure_texts, cache_dir)
        self.procedure_bm25 = BM25Index([tokenize(text) for text in procedure_texts])

    def retrieve(
        self,
        request: str,
        fields: list[str] | None = None,
        mode: Mode = "hybrid_graph",
        top_k: int = 10,
        procedure_k: int = 3,
        exclude_procedure: str | None = None,
    ) -> RetrievalResult:
        query = " ".join([request, *(fields or [])])
        query_vector = self.embedder.embed_query(query)
        query_tokens = tokenize(query)

        rankings = []
        if mode != "bm25":
            rankings.append(self._dense_table_ranking(query_vector))
        if mode != "dense":
            rankings.append(_bm25_ranking(self.table_bm25, query_tokens, self.table_names))
        seeds = reciprocal_rank_fusion(rankings)[:top_k]

        connectors = self.graph.connectors(seeds) if mode == "hybrid_graph" else []
        procedures = self._procedures(query_vector, query_tokens, procedure_k, exclude_procedure)
        return RetrievalResult(seeds=seeds, connectors=connectors, procedures=procedures)

    def _dense_table_ranking(self, query_vector: np.ndarray) -> list[str]:
        similarities = self.vectors @ query_vector
        best: dict[str, float] = {}
        for owner, similarity in zip(self.vector_owners, similarities, strict=True):
            if owner not in best or similarity > best[owner]:
                best[owner] = float(similarity)
        return [name for name, _ in sorted(best.items(), key=lambda item: (-item[1], item[0]))]

    def _procedures(
        self,
        query_vector: np.ndarray,
        query_tokens: list[str],
        procedure_k: int,
        exclude: str | None,
    ) -> list[Procedure]:
        procedures = self.catalog.procedures
        if not procedures or procedure_k == 0:
            return []
        names = [procedure.name for procedure in procedures]
        dense_order = np.argsort(-(self.procedure_vectors @ query_vector))
        fused = reciprocal_rank_fusion(
            [
                [names[i] for i in dense_order],
                _bm25_ranking(self.procedure_bm25, query_tokens, names),
            ]
        )
        by_name = {procedure.name: procedure for procedure in procedures}
        return [by_name[name] for name in fused if name != exclude][:procedure_k]


def _bm25_ranking(index: BM25Index, tokens: list[str], names: list[str]) -> list[str]:
    scored = [(s, name) for s, name in zip(index.scores(tokens), names, strict=True) if s > 0]
    return [name for _, name in sorted(scored, key=lambda item: (-item[0], item[1]))]


def _embed_cached(embedder: Embedder, texts: list[str], cache_dir: Path | None) -> np.ndarray:
    """Reuse saved vectors while the exact texts are unchanged, since CPU embedding is slow."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if cache_dir is None:
        return embedder.embed_passages(texts)
    key = hashlib.sha256(json.dumps(texts).encode()).hexdigest()[:16]
    path = cache_dir / f"vectors-{key}.npy"
    if path.exists():
        return np.load(path)
    vectors = embedder.embed_passages(texts)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors
