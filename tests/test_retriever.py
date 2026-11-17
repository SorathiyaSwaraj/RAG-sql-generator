import numpy as np

from schema_rag.retrieval.documents import table_search_text, without_docs
from schema_rag.retrieval.retriever import SchemaRetriever, reciprocal_rank_fusion


def test_rrf_rewards_agreement_between_rankings():
    assert reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]])[0] == "b"


def test_modes_differ_as_designed(catalog, embedder):
    retriever = SchemaRetriever(catalog, embedder)
    request = "customers full name and product price"

    assert "customers" in retriever.retrieve(request, mode="bm25", top_k=2).seeds
    assert retriever.retrieve(request, mode="hybrid", top_k=2).connectors == []


def test_hybrid_graph_adds_connecting_tables(catalog, embedder, monkeypatch):
    retriever = SchemaRetriever(catalog, embedder)
    monkeypatch.setattr(retriever, "_dense_table_ranking", lambda _: ["customers", "order_items"])
    monkeypatch.setattr(
        "schema_rag.retrieval.retriever._bm25_ranking",
        lambda index, tokens, names: (
            ["customers", "order_items"] if names == retriever.table_names else names
        ),
    )

    result = retriever.retrieve("anything", mode="hybrid_graph", top_k=2)

    assert result.tables == ["customers", "order_items", "orders"]


def test_requested_fields_influence_retrieval(catalog, embedder):
    retriever = SchemaRetriever(catalog, embedder)

    result = retriever.retrieve("report", fields=["quantity"], mode="bm25", top_k=1)

    assert result.seeds == ["order_items"]


def test_procedure_can_be_excluded_for_leave_one_out(catalog, embedder):
    retriever = SchemaRetriever(catalog, embedder)

    result = retriever.retrieve("sales report", exclude_procedure="sales_report", top_k=1)

    assert [procedure.name for procedure in result.procedures] == ["stock_dump"]


def test_field_docs_reach_search_text_and_can_be_removed(catalog):
    products = catalog.tables[3]

    assert "selling" in table_search_text(products)
    assert "selling" not in table_search_text(without_docs(catalog).tables[3])


def test_vectors_are_cached_by_exact_text(catalog, embedder, tmp_path):
    SchemaRetriever(catalog, embedder, tmp_path)
    saved = sorted(tmp_path.glob("*.npy"))

    class Unusable:
        embed_query = embedder.embed_query

        def embed_passages(self, texts):
            raise AssertionError("should have used the cache")

    retriever = SchemaRetriever(catalog, Unusable(), tmp_path)

    assert len(saved) == 2
    assert np.isclose(np.linalg.norm(retriever.vectors[0]), 1.0)
