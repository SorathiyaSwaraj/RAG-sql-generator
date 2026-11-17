import hashlib

import numpy as np
import pytest

from schema_rag.models import Column, ColumnPair, ForeignKey, Procedure, SchemaCatalog, Table
from schema_rag.retrieval.documents import tokenize
from schema_rag.retrieval.embeddings import normalize


class FakeEmbedder:
    """Deterministic bag-of-words vectors, so tests need no model download."""

    def _vector(self, text):
        vector = np.zeros(64, dtype=np.float32)
        for token in tokenize(text):
            vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % 64] += 1
        return vector

    def embed_passages(self, texts):
        return normalize(np.array([self._vector(text) for text in texts]))

    def embed_query(self, text):
        return normalize(np.array([self._vector(text)]))[0]


def column(name, data_type="int", **kwargs):
    return Column(name=name, data_type=data_type, **kwargs)


def key(table, *pairs):
    return ForeignKey(
        referenced_table=table,
        column_pairs=tuple(ColumnPair(source=s, target=t) for s, t in pairs),
    )


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def catalog():
    return SchemaCatalog(
        database="shop",
        dialect="mysql",
        tables=(
            Table(name="customers", columns=(column("id"), column("full_name", "text"))),
            Table(
                name="orders",
                columns=(column("id"), column("customer_id"), column("placed_on", "date")),
                foreign_keys=(key("customers", ("customer_id", "id")),),
            ),
            Table(
                name="order_items",
                columns=(column("order_id"), column("product_id"), column("quantity")),
                foreign_keys=(
                    key("orders", ("order_id", "id")),
                    key("products", ("product_id", "id")),
                ),
            ),
            Table(
                name="products",
                columns=(
                    column("id"),
                    column("price", "decimal(8,2)", description="Unit selling cost"),
                ),
            ),
            Table(
                name="shipments",
                columns=(column("region"), column("seq"), column("status")),
                primary_key=("region", "seq"),
            ),
            Table(
                name="shipment_events",
                columns=(column("region"), column("seq"), column("note", "text")),
                foreign_keys=(key("shipments", ("region", "region"), ("seq", "seq")),),
            ),
        ),
        procedures=(
            Procedure(
                name="sales_report",
                definition=(
                    "CREATE DEFINER=`app`@`localhost` PROCEDURE `sales_report`(IN p_from date)\n"
                    "BEGIN\n  SELECT o.id FROM orders o WHERE o.placed_on >= p_from;\nEND"
                ),
            ),
            Procedure(
                name="stock_dump",
                definition=(
                    "CREATE DEFINER=`app`@`localhost` PROCEDURE `stock_dump`()\n"
                    "BEGIN\n  SELECT p.id FROM products p;\nEND"
                ),
            ),
        ),
    )
