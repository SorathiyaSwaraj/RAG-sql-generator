"""Splits a mysqldump file into individual SQL statements.

Splitting on ";" breaks procedure bodies, so this scans the text the way the
mysql client does: it follows DELIMITER changes and ignores delimiters inside
quotes and comments.
"""

import re

_DELIMITER_LINE = re.compile(r"DELIMITER[ \t]+(\S+)[ \t]*(?:\r?\n|$)", re.IGNORECASE)
_QUOTES = "'\"`"


class SplitError(ValueError):
    """The dump ends inside a quote or comment, so statements cannot be trusted."""


def split_mysql_statements(sql: str) -> list[str]:
    """Return statements in file order, without their delimiters.

    Comments inside a statement are kept so procedures stay exact. Comments
    between statements are dropped. Version comments such as /*!40101 ... */ are
    kept because MySQL executes them.
    """
    statements: list[str] = []
    delimiter = ";"
    start: int | None = None
    i = 0

    while i < len(sql):
        if start is None:
            if sql[i].isspace():
                i += 1
                continue
            if match := _DELIMITER_LINE.match(sql, i):
                delimiter = match.group(1)
                i = match.end()
                continue
            if _is_line_comment(sql, i):
                i = _skip_line_comment(sql, i)
                continue
            if sql.startswith("/*", i) and not sql.startswith("/*!", i):
                i = _skip_block_comment(sql, i)
                continue
            start = i

        if sql.startswith(delimiter, i):
            statements.append(sql[start:i].strip())
            start = None
            i += len(delimiter)
        elif sql[i] in _QUOTES:
            i = _skip_quoted(sql, i)
        elif _is_line_comment(sql, i):
            i = _skip_line_comment(sql, i)
        elif sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
        else:
            i += 1

    if start is not None:
        statements.append(sql[start:].strip())
    return [statement for statement in statements if statement]


def _is_line_comment(sql: str, i: int) -> bool:
    if sql[i] == "#":
        return True
    # MySQL only treats "--" as a comment when whitespace follows, so a--1 stays an expression.
    return sql.startswith("--", i) and (i + 2 == len(sql) or sql[i + 2].isspace())


def _skip_line_comment(sql: str, i: int) -> int:
    end = sql.find("\n", i)
    return len(sql) if end == -1 else end + 1


def _skip_block_comment(sql: str, i: int) -> int:
    end = sql.find("*/", i + 2)
    if end == -1:
        raise SplitError(f"unterminated comment starting at offset {i}")
    return end + 2


def _skip_quoted(sql: str, i: int) -> int:
    quote = sql[i]
    j = i + 1
    while j < len(sql):
        if sql[j] == "\\" and quote != "`":
            j += 2
        elif sql[j] != quote:
            j += 1
        elif sql.startswith(quote, j + 1):
            j += 2
        else:
            return j + 1
    raise SplitError(f"unterminated {quote} quote starting at offset {i}")
