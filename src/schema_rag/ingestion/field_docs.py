"""Merges the separately maintained field documentation into a catalog.

The CSVs stay a separate input so a new dump never overwrites them. Rows match on
exact table and column names, and anything that does not match is reported.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from schema_rag.models import GlossaryTerm, SchemaCatalog


@dataclass
class FieldDocsReport:
    documented_tables: int = 0
    documented_columns: int = 0
    glossary_terms: int = 0
    unmatched: list[str] = field(default_factory=list)


def merge_field_docs(
    catalog: SchemaCatalog, docs_dir: Path
) -> tuple[SchemaCatalog, FieldDocsReport]:
    report = FieldDocsReport()
    table_rows: dict[str, dict[str, str]] = {}
    column_rows: dict[str, dict[str, dict[str, str]]] = {}
    known = {table.name: {column.name for column in table.columns} for table in catalog.tables}

    for row in _read_csv(docs_dir / "columns.csv"):
        table, column = row["table_name"].strip(), row["column_name"].strip()
        if table not in known or (column and column not in known[table]):
            report.unmatched.append(f"{table}.{column}" if column else table)
        elif column:
            column_rows.setdefault(table, {})[column] = row
        else:
            table_rows[table] = row

    tables = []
    for table in catalog.tables:
        update = {}
        if row := table_rows.get(table.name):
            update = {
                "description": _clean(row.get("meaning")),
                "caveats": _clean(row.get("caveats")),
            }
            report.documented_tables += 1
        documented = column_rows.get(table.name, {})
        update["columns"] = tuple(
            column.model_copy(
                update={
                    "description": _clean(documented[column.name].get("meaning")),
                    "synonyms": _split(documented[column.name].get("synonyms")),
                    "values_or_format": _clean(documented[column.name].get("values_or_format")),
                    "caveats": _clean(documented[column.name].get("caveats")),
                }
            )
            if column.name in documented
            else column
            for column in table.columns
        )
        report.documented_columns += len(documented)
        tables.append(table.model_copy(update=update))

    glossary = tuple(
        GlossaryTerm(
            term=row["term"].strip(),
            synonyms=_split(row.get("synonyms")),
            definition=row.get("definition", "").strip(),
            calculation_rule=_clean(row.get("calculation_rule")),
            related_columns=_split(row.get("related_columns")),
        )
        for row in _read_csv(docs_dir / "glossary.csv")
    )
    report.glossary_terms = len(glossary)
    return catalog.model_copy(update={"tables": tuple(tables), "glossary": glossary}), report


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split("|") if part.strip())
