"""Turns a configured dump into a saved catalog and an ingestion report."""

import json
from pathlib import Path

from pydantic import BaseModel

from schema_rag.config import DatabaseConfig
from schema_rag.ingestion.field_docs import merge_field_docs
from schema_rag.ingestion.mysql_parser import parse_mysql_statements
from schema_rag.ingestion.oracle_parser import parse_oracle_statements
from schema_rag.ingestion.splitter import split_mysql_statements, split_oracle_statements
from schema_rag.models import SchemaCatalog


class IngestionReport(BaseModel):
    tables: int
    columns: int
    foreign_keys: int
    composite_foreign_keys: int
    views: int
    procedures: int
    excluded_tables: int
    unrecognized: dict[str, int]
    unresolved_references: list[str]
    documented_tables: int = 0
    documented_columns: int = 0
    glossary_terms: int = 0
    unmatched_docs: list[str] = []


def ingest(name: str, config: DatabaseConfig) -> tuple[SchemaCatalog, IngestionReport]:
    text = config.dump_path.read_text(encoding="utf-8", errors="replace")
    if config.dialect == "mysql":
        parsed = parse_mysql_statements(split_mysql_statements(text))
        excluded = 0
    else:
        parsed = parse_oracle_statements(split_oracle_statements(text))
        excluded = parsed.excluded_system_tables

    tables = [table for table in parsed.tables if table.name not in config.exclude_tables]
    excluded += len(parsed.tables) - len(tables)
    # Sorted so re-ingesting the same inputs produces identical bytes.
    catalog = SchemaCatalog(
        database=name,
        dialect=config.dialect,
        tables=tuple(sorted(tables, key=lambda table: table.name)),
        views=tuple(sorted(parsed.views, key=lambda view: view.name)),
        procedures=tuple(sorted(parsed.procedures, key=lambda procedure: procedure.name)),
    )

    docs_report = None
    if config.field_docs_dir:
        catalog, docs_report = merge_field_docs(catalog, config.field_docs_dir)

    foreign_keys = [key for table in catalog.tables for key in table.foreign_keys]
    known = {table.name for table in catalog.tables}
    unrecognized: dict[str, int] = {}
    for label in parsed.unrecognized:
        unrecognized[label] = unrecognized.get(label, 0) + 1

    report = IngestionReport(
        tables=len(catalog.tables),
        columns=sum(len(table.columns) for table in catalog.tables),
        foreign_keys=len(foreign_keys),
        composite_foreign_keys=sum(len(key.column_pairs) > 1 for key in foreign_keys),
        views=len(catalog.views),
        procedures=len(catalog.procedures),
        excluded_tables=excluded,
        unrecognized=dict(sorted(unrecognized.items())),
        unresolved_references=sorted({key.referenced_table for key in foreign_keys} - known),
        documented_tables=docs_report.documented_tables if docs_report else 0,
        documented_columns=docs_report.documented_columns if docs_report else 0,
        glossary_terms=docs_report.glossary_terms if docs_report else 0,
        unmatched_docs=docs_report.unmatched if docs_report else [],
    )
    return catalog, report


def save_catalog(catalog: SchemaCatalog, report: IngestionReport, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "catalog.json").write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
    (directory / "ingestion_report.json").write_text(
        json.dumps(report.model_dump(), indent=2), encoding="utf-8"
    )


def load_catalog(directory: Path) -> SchemaCatalog:
    return SchemaCatalog.model_validate_json((directory / "catalog.json").read_text("utf-8"))
