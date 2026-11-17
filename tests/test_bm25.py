from schema_rag.retrieval.bm25 import BM25Index
from schema_rag.retrieval.documents import tokenize


def test_tokenize_splits_identifiers():
    assert tokenize("overdue_Amount in FY24") == ["overdue", "amount", "in", "fy24"]


def test_bm25_prefers_rare_term_and_shorter_document():
    index = BM25Index(
        [["red", "fish"], ["red", "red", "cat"], ["red", "fish", "dog", "cow", "pig"]]
    )

    scores = index.scores(["fish"])

    assert scores[0] > scores[2] > scores[1] == 0


def test_bm25_handles_empty_index():
    assert BM25Index([]).scores(["a"]) == []
