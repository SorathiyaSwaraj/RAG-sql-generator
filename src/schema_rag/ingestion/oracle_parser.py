"""Turns split Oracle export statements into schema models.

sqlglot rejects clauses that SQL Developer always emits (NOT NULL ENABLE, USING
INDEX, storage options). The export layout is regular, so a small quote-aware
parser for the column list is simpler and easier to verify than cleaning the DDL.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from schema_rag.models import Column, ColumnPair, ForeignKey, Procedure, Table, View

_NAME = r'(?:"[^"]+"\.)?"?([\w$#]+)"?'
_CREATE_TABLE = re.compile(rf"CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+{_NAME}", re.I)
_PROCEDURE = re.compile(
    rf"CREATE\s+OR\s+REPLACE\s+(?:(?:NON)?EDITIONABLE\s+)?PROCEDURE\s+{_NAME}", re.I
)
_VIEW = re.compile(
    rf"CREATE\s+OR\s+REPLACE\s+(?:FORCE\s+)?(?:(?:NON)?EDITIONABLE\s+)?VIEW\s+{_NAME}", re.I
)
_IGNORED = re.compile(
    r"(DROP|GRANT|ALTER\s+TRIGGER|CREATE\s+(UNIQUE\s+)?INDEX|CREATE\s+SEQUENCE"
    r"|CREATE\s+OR\s+REPLACE\s+(?:(?:NON)?EDITIONABLE\s+)?"
    r"(?:PUBLIC\s+)?(TYPE|SYNONYM|TRIGGER|FUNCTION|PACKAGE))\b",
    re.I,
)
_COLUMN = re.compile(
    r'^"([^"]+)"\s+(.+?)(?=\s+DEFAULT\b|\s+NOT\s+NULL\b|\s+GENERATED\b|\s+COLLATE\b|\s+CONSTRAINT\b|$)',
    re.I | re.S,
)
_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.I)
_COLUMNS = r"\(([^)]*)\)"
_PRIMARY_KEY = re.compile(rf"(?:CONSTRAINT\s+{_NAME}\s+)?PRIMARY\s+KEY\s*{_COLUMNS}", re.I)
_FOREIGN_KEY = re.compile(
    rf"(?:CONSTRAINT\s+{_NAME}\s+)?FOREIGN\s+KEY\s*{_COLUMNS}\s*REFERENCES\s+{_NAME}\s*{_COLUMNS}",
    re.I,
)
_ALTER_TABLE = re.compile(rf"ALTER\s+TABLE\s+{_NAME}\s+(.*)", re.I | re.S)
_MODIFY_NOT_NULL = re.compile(r'MODIFY\s*\(\s*"([^"]+)"\s+NOT\s+NULL', re.I)
_TABLE_COMMENT = re.compile(rf"COMMENT\s+ON\s+TABLE\s+{_NAME}\s+IS\s+'(.*)'$", re.I | re.S)
_COLUMN_COMMENT = re.compile(
    r'COMMENT\s+ON\s+COLUMN\s+(?:"[^"]+"\.)?"?([\w$#]+)"?\."?([\w$#]+)"?\s+IS\s+\'(.*)\'$',
    re.I | re.S,
)
_LABEL = re.compile(r"[A-Za-z]+(?:\s+[A-Za-z]+)?")
# Oracle's own objects, for the few the export does not mark SHARING=METADATA.
_SYSTEM_VIEW = re.compile(r"^(MVIEW_|LOGMNR|LOGSTDBY|AQ\$|PRODUCT_|SCHEDULER_)", re.I)


@dataclass
class _TableDraft:
    name: str
    columns: dict[str, Column]
    primary_key: tuple[str, ...] = ()
    foreign_keys: dict[str, ForeignKey] = field(default_factory=dict)
    comment: str | None = None


@dataclass
class ParsedOracleDump:
    tables: list[Table] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    # Short keyword labels only, so nothing else from the dump reaches the report.
    unrecognized: list[str] = field(default_factory=list)
    excluded_system_tables: int = 0


def parse_oracle_statements(statements: Iterable[str]) -> ParsedOracleDump:
    parsed = ParsedOracleDump()
    drafts: dict[str, _TableDraft] = {}
    excluded: set[str] = set()

    for statement in statements:
        if match := _CREATE_TABLE.match(statement):
            if re.search(r"\bSHARING\s*=\s*METADATA\b", statement, re.I):
                excluded.add(match.group(1))
                continue
            draft = _parse_table(match.group(1), statement)
            if draft is None:
                parsed.unrecognized.append("CREATE TABLE (parse failed)")
            else:
                drafts[draft.name] = draft
        elif match := _ALTER_TABLE.match(statement):
            if match.group(1) not in excluded:
                _apply_alter(drafts, match.group(1), match.group(2), parsed)
        elif statement.upper().startswith("COMMENT ON"):
            _apply_comment(drafts, excluded, statement, parsed)
        elif match := _PROCEDURE.match(statement):
            parsed.procedures.append(Procedure(name=match.group(1), definition=statement))
        elif match := _VIEW.match(statement):
            if not _SYSTEM_VIEW.match(match.group(1)):
                parsed.views.append(View(name=match.group(1), definition=statement))
        elif not _IGNORED.match(statement):
            parsed.unrecognized.append(_label(statement))

    parsed.excluded_system_tables = len(excluded)
    parsed.tables = [
        Table(
            name=draft.name,
            columns=tuple(draft.columns.values()),
            primary_key=draft.primary_key,
            foreign_keys=tuple(draft.foreign_keys.values()),
            comment=draft.comment,
        )
        for draft in drafts.values()
    ]
    return parsed


def _label(statement: str) -> str:
    match = _LABEL.match(statement)
    return " ".join(match.group().upper().split()) if match else "UNKNOWN"


def _parse_table(name: str, statement: str) -> _TableDraft | None:
    items = _column_list_items(statement)
    if items is None:
        return None
    draft = _TableDraft(name=name, columns={})
    for item in items:
        if constraint := _PRIMARY_KEY.match(item):
            draft.primary_key = _names(constraint.group(2))
        elif constraint := _FOREIGN_KEY.match(item):
            _add_foreign_key(draft, constraint)
        elif item.upper().startswith(("CONSTRAINT", "SUPPLEMENTAL", "CHECK", "UNIQUE")):
            continue
        elif column := _COLUMN.match(item):
            draft.columns[column.group(1)] = Column(
                name=column.group(1),
                data_type=" ".join(column.group(2).split()),
                nullable=_NOT_NULL.search(item) is None,
            )
        else:
            return None
    return draft if draft.columns else None


def _column_list_items(statement: str) -> list[str] | None:
    """Return the top-level comma-separated items of the first parenthesized list."""
    start = statement.find("(")
    if start == -1:
        return None
    items, depth, item_start, i = [], 0, start + 1, start
    while i < len(statement):
        char = statement[i]
        if char in "'\"":
            i = statement.find(char, i + 1)
            if i == -1:
                return None
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                items.append(statement[item_start:i].strip())
                return [item for item in items if item]
        elif char == "," and depth == 1:
            items.append(statement[item_start:i].strip())
            item_start = i + 1
        i += 1
    return None


def _names(columns: str) -> tuple[str, ...]:
    return tuple(name.strip().strip('"') for name in columns.split(","))


def _add_foreign_key(draft: _TableDraft, match: re.Match) -> None:
    name, sources, referenced_table, targets = match.groups()
    source_names, target_names = _names(sources), _names(targets)
    if len(source_names) != len(target_names):
        raise ValueError(f"foreign key {name!r} has mismatched column counts")
    foreign_key = ForeignKey(
        name=name,
        referenced_table=referenced_table,
        column_pairs=tuple(
            ColumnPair(source=source, target=target)
            for source, target in zip(source_names, target_names, strict=True)
        ),
    )
    # The export can repeat a constraint, so the name is the identity.
    draft.foreign_keys[name or match.group()] = foreign_key


def _apply_alter(
    drafts: dict[str, _TableDraft], table: str, action: str, parsed: ParsedOracleDump
) -> None:
    draft = drafts.get(table)
    if draft is None:
        parsed.unrecognized.append("ALTER TABLE (unknown table)")
        return
    if modify := _MODIFY_NOT_NULL.match(action):
        column = draft.columns.get(modify.group(1))
        if column:
            draft.columns[column.name] = column.model_copy(update={"nullable": False})
        return
    constraint = action.removeprefix("ADD ").strip()
    if match := _PRIMARY_KEY.match(constraint):
        draft.primary_key = _names(match.group(2))
    elif match := _FOREIGN_KEY.match(constraint):
        _add_foreign_key(draft, match)
    elif not re.match(
        r"(CONSTRAINT\s+\S+\s+(UNIQUE|CHECK)\b|UNIQUE\b|CHECK\b|MODIFY\b|ENABLE\b)",
        constraint,
        re.I,
    ):
        parsed.unrecognized.append("ALTER TABLE (other)")


def _apply_comment(
    drafts: dict[str, _TableDraft],
    excluded: set[str],
    statement: str,
    parsed: ParsedOracleDump,
) -> None:
    if match := _COLUMN_COMMENT.match(statement):
        table, column_name, text = match.groups()
        if table in excluded:
            return
        draft = drafts.get(table)
        column = draft.columns.get(column_name) if draft else None
        if column is None:
            parsed.unrecognized.append("COMMENT ON (unknown column)")
            return
        draft.columns[column_name] = column.model_copy(update={"comment": text})
    elif match := _TABLE_COMMENT.match(statement):
        table, text = match.groups()
        if table in excluded:
            return
        if table in drafts:
            drafts[table].comment = text
        else:
            parsed.unrecognized.append("COMMENT ON (unknown table)")
    else:
        parsed.unrecognized.append("COMMENT ON")
