"""Static checks on generated SQL. Nothing is ever executed.

These catch invented tables and columns, wrong dialect syntax, and suspect joins.
They cannot catch valid SQL that returns the wrong data, such as a wrong filter.
"""

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from schema_rag.ingestion.splitter import SplitError, split_mysql_statements
from schema_rag.models import SchemaCatalog

_ORACLE_PSEUDO_COLUMNS = {"rownum", "rowid", "sysdate", "systimestamp", "level", "user"}
_PROCEDURE_START = re.compile(r"^\s*CREATE\b.*?\bPROCEDURE\b", re.IGNORECASE | re.DOTALL)
_QUERY_START = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)
_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER)\b", re.IGNORECASE)
_SELECT_INTO = re.compile(r"\bINTO\s+[\w@.,\s]+?(?=\bFROM\b)", re.IGNORECASE)
_TEMP_TABLE = re.compile(
    r"CREATE\s+(?:GLOBAL\s+)?TEMPORARY\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)",
    re.IGNORECASE,
)
_TRAILING_BLOCK = re.compile(r"\b(END\s*(IF|LOOP|WHILE|CASE)?|CLOSE\s+\w+)\s*$", re.IGNORECASE)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    statements_checked: int = 0
    statements_unparsed: int = 0

    @property
    def passed(self) -> bool:
        return not self.errors


class _SchemaIndex:
    """Case-insensitive lookup: Oracle folds names and MySQL columns ignore case."""

    def __init__(self, catalog: SchemaCatalog) -> None:
        self.dialect = catalog.dialect
        self.columns = {
            table.name.casefold(): {column.name.casefold() for column in table.columns}
            for table in catalog.tables
        }
        self.views = {view.name.casefold() for view in catalog.views}
        self.foreign_keys: dict[frozenset[str], list[set[frozenset[str]]]] = {}
        for table in catalog.tables:
            for key in table.foreign_keys:
                pair = frozenset({table.name.casefold(), key.referenced_table.casefold()})
                self.foreign_keys.setdefault(pair, []).append(
                    {
                        frozenset({p.source.casefold(), p.target.casefold()})
                        for p in key.column_pairs
                    }
                )


def validate_query(sql: str, catalog: SchemaCatalog) -> ValidationResult:
    result = ValidationResult()
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=catalog.dialect) if s is not None]
    except (ParseError, TokenError) as error:
        result.errors.append(f"syntax error: {_first_line(error)}")
        return result
    if len(statements) != 1:
        result.errors.append(f"expected one statement, found {len(statements)}")
        return result
    if not isinstance(statements[0], exp.Query):
        result.errors.append("only read-only SELECT queries are allowed")
        return result
    _check_tree(statements[0], _SchemaIndex(catalog), result, check_unqualified=True)
    result.statements_checked = 1
    return result


def validate_procedure(sql: str, catalog: SchemaCatalog) -> ValidationResult:
    """Check the queries inside a procedure, since parsers cannot read procedural code."""
    result = ValidationResult()
    if not _PROCEDURE_START.match(sql):
        result.errors.append("output is not a CREATE PROCEDURE statement")
        return result
    if re.search(r"\bDEFINER\s*=", sql, re.IGNORECASE):
        result.warnings.append("remove DEFINER: it ties the procedure to one account")

    try:
        statements = split_mysql_statements(sql, backslash_escapes=catalog.dialect == "mysql")
    except SplitError as error:
        result.errors.append(f"syntax error: {error}")
        return result
    index = _SchemaIndex(catalog)
    temporary = {name.casefold() for name in _TEMP_TABLE.findall(sql)}
    for statement in statements:
        if _WRITE.search(statement):
            result.warnings.append("procedure changes data: review before running")
        start = _QUERY_START.search(statement)
        if start is None:
            continue
        fragment = _SELECT_INTO.sub("", statement[start.start() :])
        fragment = _TRAILING_BLOCK.sub("", fragment.strip()).strip()
        try:
            tree = sqlglot.parse_one(fragment, dialect=catalog.dialect)
        except (ParseError, TokenError):
            result.statements_unparsed += 1
            continue
        result.statements_checked += 1
        # Unqualified names inside a procedure may be parameters or variables.
        _check_tree(tree, index, result, check_unqualified=False, temporary=temporary)
    if result.statements_unparsed:
        result.warnings.append(
            f"{result.statements_unparsed} inner statements could not be checked, "
            "for example dynamic SQL built from strings: review them by hand"
        )
    return result


def _check_tree(
    tree: exp.Expression,
    index: _SchemaIndex,
    result: ValidationResult,
    check_unqualified: bool,
    temporary: set[str] | None = None,
) -> None:
    derived = {cte.alias.casefold() for cte in tree.find_all(exp.CTE)} | (temporary or set())
    opaque = derived | {
        subquery.alias.casefold() for subquery in tree.find_all(exp.Subquery) if subquery.alias
    }

    aliases: dict[str, set[str]] = {}
    real_tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.casefold()
        if not name or name == "dual":
            continue
        if name in derived:
            if table.alias:
                opaque.add(table.alias.casefold())
            continue
        if name not in index.columns and name not in index.views:
            result.errors.append(f"unknown table: {table.name}")
            continue
        real_tables.add(name)
        aliases.setdefault(name, set()).add(name)
        if table.alias:
            aliases.setdefault(table.alias.casefold(), set()).add(name)

    select_aliases = {alias.alias.casefold() for alias in tree.find_all(exp.Alias)}
    has_opaque_source = bool(opaque)
    for column in tree.find_all(exp.Column):
        name = column.name.casefold()
        if not name or isinstance(column.this, exp.Star):
            continue
        qualifier = column.table.casefold()
        if qualifier:
            if qualifier in opaque:
                continue
            owners = aliases.get(qualifier)
            if owners is None:
                result.errors.append(f"unknown table alias: {column.table}")
            elif not any(_has_column(index, owner, name) for owner in owners):
                result.errors.append(f"unknown column: {column.table}.{column.name}")
        elif check_unqualified and not has_opaque_source and name not in select_aliases:
            if name in _ORACLE_PSEUDO_COLUMNS and index.dialect == "oracle":
                continue
            if not any(_has_column(index, owner, name) for owner in real_tables):
                result.errors.append(f"unknown column: {column.name}")

    _check_joins(tree, aliases, index, result)


def _has_column(index: _SchemaIndex, table: str, column: str) -> bool:
    # Views keep their column lists inside query text, so they cannot be checked here.
    return table in index.views or column in index.columns.get(table, set())


def _check_joins(
    tree: exp.Expression,
    aliases: dict[str, set[str]],
    index: _SchemaIndex,
    result: ValidationResult,
) -> None:
    used: dict[frozenset[str], set[frozenset[str]]] = {}
    for equality in tree.find_all(exp.EQ):
        left, right = equality.left, equality.right
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            continue
        for left_table in aliases.get(left.table.casefold(), ()):
            for right_table in aliases.get(right.table.casefold(), ()):
                if left_table != right_table:
                    used.setdefault(frozenset({left_table, right_table}), set()).add(
                        frozenset({left.name.casefold(), right.name.casefold()})
                    )
    for pair, columns in used.items():
        keys = index.foreign_keys.get(pair)
        if not keys:
            continue
        if not any(key <= columns for key in keys):
            names = " and ".join(sorted(pair))
            if any(columns & key for key in keys):
                result.warnings.append(f"join between {names} uses only part of a composite key")
            else:
                result.warnings.append(f"join between {names} does not follow its foreign key")


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0][:200]
