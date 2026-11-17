"""Turns catalog entries into the text that retrieval searches."""

import re

from schema_rag.models import Column, Procedure, SchemaCatalog, Table

_TOKEN = re.compile(r"[a-z0-9]+")
_PROCEDURE_SEARCH_CHARS = 4000


def tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumerics, so overdue_amount matches "overdue amount"."""
    return _TOKEN.findall(text.lower())


def _words(identifier: str) -> str:
    return identifier.replace("_", " ").lower()


def column_text(table: Table, column: Column) -> str:
    parts = [f"{_words(table.name)}: {_words(column.name)}"]
    parts += [
        part for part in (column.comment, column.description, column.values_or_format) if part
    ]
    parts += column.synonyms
    return ". ".join(parts)


def table_summary_text(table: Table) -> str:
    """Short enough for the embedding model. Long tables are covered by their column documents."""
    parts = [_words(table.name)]
    parts += [part for part in (table.comment, table.description) if part]
    return ". ".join(parts)


def table_search_text(table: Table) -> str:
    """Everything about a table, for BM25, which has no input length limit."""
    return " ".join(
        [table_summary_text(table), table.name] + [column_text(table, c) for c in table.columns]
    )


def procedure_search_text(procedure: Procedure) -> str:
    return f"{_words(procedure.name)}. {procedure.definition[:_PROCEDURE_SEARCH_CHARS]}"


def without_docs(catalog: SchemaCatalog) -> SchemaCatalog:
    """The catalog as parsed from the dump alone, for measuring what field docs add."""
    tables = tuple(
        table.model_copy(
            update={
                "description": None,
                "caveats": None,
                "columns": tuple(
                    column.model_copy(
                        update={
                            "description": None,
                            "synonyms": (),
                            "values_or_format": None,
                            "caveats": None,
                        }
                    )
                    for column in table.columns
                ),
            }
        )
        for table in catalog.tables
    )
    return catalog.model_copy(update={"tables": tables, "glossary": ()})
