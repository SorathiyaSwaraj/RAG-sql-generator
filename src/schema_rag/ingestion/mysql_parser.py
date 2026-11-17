"""Turns split mysqldump statements into schema models.

Statements fall into three groups: ones we extract, ones known to be irrelevant,
and everything else. The last group is reported, never silently dropped, so a
dump containing something new (say ALTER TABLE ... ADD FOREIGN KEY) gets noticed.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from schema_rag.models import Column, ColumnPair, ForeignKey, Procedure, Table, View

_VERSION_COMMENT = re.compile(r"^/\*!\d*\s*(.*?)\s*\*/$", re.DOTALL)
_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\b", re.IGNORECASE)
_IGNORED = re.compile(
    r"(DROP|SET|USE|LOCK|UNLOCK|INSERT|CREATE\s+DATABASE|ALTER\s+TABLE\s+\S+\s+(DISABLE|ENABLE)\s+KEYS)\b",
    re.IGNORECASE,
)
_PROCEDURE = re.compile(r"CREATE\s+(?:DEFINER\s*=\s*\S+\s+)?PROCEDURE\s+`?(\w+)`?", re.IGNORECASE)
_VIEW = re.compile(r"CREATE\b.*?\bVIEW\s+`?(\w+)`?\s+AS\b", re.IGNORECASE | re.DOTALL)
_INNER_VERSION_MARKER = re.compile(r"/\*!\d*\s*|\s*\*/")
_LABEL = re.compile(r"[A-Za-z]+(?:\s+[A-Za-z]+)?")


@dataclass
class ParsedDump:
    tables: list[Table] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    # Short keyword labels only, so row data can never reach the ingestion report.
    unrecognized: list[str] = field(default_factory=list)


def parse_mysql_statements(statements: Iterable[str]) -> ParsedDump:
    parsed = ParsedDump()
    for statement in statements:
        body = _unwrap_version_comment(statement)
        if _CREATE_TABLE.match(body):
            try:
                parsed.tables.append(_parse_table(body))
            except (ParseError, TokenError):
                parsed.unrecognized.append("CREATE TABLE (parse failed)")
        elif match := _PROCEDURE.match(body):
            parsed.procedures.append(Procedure(name=match.group(1), definition=body))
        elif match := _VIEW.match(_INNER_VERSION_MARKER.sub(" ", statement).strip()):
            definition = _INNER_VERSION_MARKER.sub(" ", statement).strip()
            parsed.views.append(View(name=match.group(1), definition=definition))
        elif not _IGNORED.match(body):
            parsed.unrecognized.append(_label(body))
    return parsed


def _unwrap_version_comment(statement: str) -> str:
    match = _VERSION_COMMENT.match(statement)
    return match.group(1) if match else statement


def _label(statement: str) -> str:
    match = _LABEL.match(statement)
    return " ".join(match.group().upper().split()) if match else "UNKNOWN"


def _parse_table(statement: str) -> Table:
    create = sqlglot.parse_one(statement, dialect="mysql")
    schema = create.this
    items = schema.expressions
    comment = create.find(exp.SchemaCommentProperty)

    columns = []
    primary_key: list[str] = []
    for item in items:
        if isinstance(item, exp.ColumnDef):
            columns.append(_parse_column(item))
            if item.find(exp.PrimaryKeyColumnConstraint):
                primary_key.append(item.name)
        elif isinstance(item, exp.PrimaryKey):
            primary_key.extend(column.name for column in item.expressions)

    return Table(
        name=schema.this.name,
        columns=tuple(columns),
        primary_key=tuple(primary_key),
        foreign_keys=tuple(_parse_foreign_key(item) for item in items if _holds_foreign_key(item)),
        comment=comment.this.name if comment else None,
    )


def _parse_column(definition: exp.ColumnDef) -> Column:
    comment = definition.find(exp.CommentColumnConstraint)
    not_null = definition.find(exp.NotNullColumnConstraint)
    return Column(
        name=definition.name,
        data_type=definition.args["kind"].sql(dialect="mysql"),
        nullable=not_null is None or bool(not_null.args.get("allow_null")),
        comment=comment.this.name if comment else None,
    )


def _holds_foreign_key(item: exp.Expression) -> bool:
    return isinstance(item, exp.ForeignKey) or (
        isinstance(item, exp.Constraint) and item.find(exp.ForeignKey) is not None
    )


def _parse_foreign_key(item: exp.Expression) -> ForeignKey:
    foreign_key = item if isinstance(item, exp.ForeignKey) else item.find(exp.ForeignKey)
    reference = foreign_key.args["reference"].this
    sources = [column.name for column in foreign_key.expressions]
    targets = [column.name for column in reference.expressions]
    if len(sources) != len(targets):
        raise ValueError(f"foreign key has {len(sources)} source and {len(targets)} target columns")
    return ForeignKey(
        name=item.name if isinstance(item, exp.Constraint) else None,
        referenced_table=reference.this.name,
        column_pairs=tuple(
            ColumnPair(source=source, target=target)
            for source, target in zip(sources, targets, strict=True)
        ),
    )
