"""Compares a typical LangChain document-RAG setup with our retrieval, on the same cases.

The baseline chunks raw DDL as plain text and runs vector search, which is how a
general tutorial pipeline would treat a schema. It shares our embedding model, so
the comparison measures the retrieval design and not the model.

Run: pip install -e '.[comparison]' && python experiments/langchain_baseline.py mysql
"""

import re
import statistics
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from schema_rag.config import load_settings
from schema_rag.evaluation.cases import cases_from_procedures
from schema_rag.evaluation.metrics import all_found, recall
from schema_rag.evaluation.runner import evaluate_retrieval, format_table
from schema_rag.ingestion.pipeline import load_catalog
from schema_rag.ingestion.splitter import split_mysql_statements, split_oracle_statements
from schema_rag.retrieval.embeddings import FastEmbedEmbedder
from schema_rag.retrieval.retriever import SchemaRetriever

_TABLE_NAME = re.compile(r'CREATE\s+TABLE\s+(?:"\w+"\.)?[`"](\w+)[`"]', re.IGNORECASE)
TOP_KS = (5, 10, 20)


class SharedEmbeddings(Embeddings):
    def __init__(self, embedder: FastEmbedEmbedder) -> None:
        self.embedder = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed_passages(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embedder.embed_query(text).tolist()


def build_store(dump_text: str, dialect: str, tables: set[str], embeddings: Embeddings):
    split = split_mysql_statements if dialect == "mysql" else split_oracle_statements
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    documents = []
    for statement in split(dump_text):
        match = _TABLE_NAME.match(statement)
        if match and match.group(1) in tables:
            documents += splitter.create_documents(
                [statement], metadatas=[{"table": match.group(1)}]
            )
    store = InMemoryVectorStore(embeddings)
    store.add_documents(documents)
    return store, documents


def top_tables(results: list[Document], k: int) -> list[str]:
    """Several chunks can belong to one table, so count each table once."""
    return list(dict.fromkeys(document.metadata["table"] for document in results))[:k]


def main(database: str) -> None:
    settings = load_settings(Path("config/databases.yaml"))
    directory = settings.database_dir(database)
    catalog = load_catalog(directory)
    config = settings.database(database)
    embedder = FastEmbedEmbedder(settings.data_dir / "models")
    cases = [case for case in cases_from_procedures(catalog) if case.gold_tables]

    store, documents = build_store(
        config.dump_path.read_text("utf-8", errors="replace"),
        catalog.dialect,
        {table.name for table in catalog.tables},
        SharedEmbeddings(embedder),
    )
    print(f"LangChain baseline: {len(documents)} DDL chunks, {len(cases)} cases")
    rows = []
    for k in TOP_KS:
        recalls, complete = [], []
        for case in cases:
            found = top_tables(store.similarity_search(case.request, k=k * 5), k)
            recalls.append(recall(found, set(case.gold_tables)))
            complete.append(all_found(found, set(case.gold_tables)))
        rows.append(
            {
                "mode": "langchain_baseline",
                "k": k,
                "recall": round(statistics.mean(recalls), 3),
                "all_found": round(statistics.mean(complete), 3),
            }
        )
    ours = evaluate_retrieval(
        SchemaRetriever(catalog, embedder, directory / "vectors"),
        cases,
        top_ks=TOP_KS,
        modes=("hybrid_graph",),
    )
    rows += [
        {"mode": row["mode"], "k": row["k"], "recall": row["recall"], "all_found": row["all_found"]}
        for row in ours
    ]
    print(format_table(rows))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mysql")
