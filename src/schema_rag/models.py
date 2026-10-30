"""Dialect-neutral description of a database schema.

Parsers produce these models and every later stage reads them, so supporting a
new database means adding a parser, not changing retrieval or generation.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Dialect = Literal["mysql", "oracle"]


class SchemaModel(BaseModel):
    """Base model: catalog entries are immutable once parsed."""

    model_config = ConfigDict(frozen=True)


class Column(SchemaModel):
    name: str
    data_type: str
    nullable: bool = True
    comment: str | None = None


class ColumnPair(SchemaModel):
    """One source-to-target link, the unit a JOIN's ON clause is built from."""

    source: str
    target: str


class ForeignKey(SchemaModel):
    """A single constraint. A composite key has several pairs, and all must apply in one JOIN."""

    name: str | None = None
    referenced_table: str
    column_pairs: tuple[ColumnPair, ...] = Field(min_length=1)


class Table(SchemaModel):
    name: str
    columns: tuple[Column, ...] = Field(min_length=1)
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    comment: str | None = None

    @model_validator(mode="after")
    def check_key_columns_exist(self) -> Self:
        names = {column.name for column in self.columns}
        used = set(self.primary_key)
        for foreign_key in self.foreign_keys:
            used.update(pair.source for pair in foreign_key.column_pairs)
        missing = sorted(used - names)
        if missing:
            raise ValueError(f"table {self.name!r} has keys on unknown columns: {missing}")
        return self


class View(SchemaModel):
    name: str
    definition: str


class Procedure(SchemaModel):
    """Kept as exact text because parsers cannot reliably read procedural code."""

    name: str
    definition: str


class SchemaCatalog(SchemaModel):
    database: str
    dialect: Dialect
    tables: tuple[Table, ...] = ()
    views: tuple[View, ...] = ()
    procedures: tuple[Procedure, ...] = ()

    @model_validator(mode="after")
    def check_table_names_unique(self) -> Self:
        names = [table.name for table in self.tables]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate table names: {duplicates}")
        return self
