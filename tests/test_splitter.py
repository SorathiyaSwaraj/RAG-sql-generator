import pytest

from schema_rag.ingestion.splitter import SplitError, split_mysql_statements


def test_splits_on_default_delimiter():
    assert split_mysql_statements("SELECT 1;\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_keeps_final_statement_without_delimiter():
    assert split_mysql_statements("SELECT 1;\nSELECT 2") == ["SELECT 1", "SELECT 2"]


def test_procedure_stays_whole_and_delimiter_is_restored():
    sql = """DELIMITER ;;
CREATE PROCEDURE p()
BEGIN
  SELECT 1;
  SELECT 2;
END ;;
DELIMITER ;
SELECT 3;
"""
    assert split_mysql_statements(sql) == [
        "CREATE PROCEDURE p()\nBEGIN\n  SELECT 1;\n  SELECT 2;\nEND",
        "SELECT 3",
    ]


def test_delimiter_lines_keep_two_procedures_separate():
    sql = "DELIMITER ;;\nCREATE PROCEDURE a() SELECT 1 ;;\nCREATE PROCEDURE b() SELECT 2 ;;\n"

    assert split_mysql_statements(sql) == [
        "CREATE PROCEDURE a() SELECT 1",
        "CREATE PROCEDURE b() SELECT 2",
    ]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 'a;b'",
        'SELECT "a;b"',
        "SELECT `a;b`",
        "SELECT 'it''s;here'",
        r"SELECT 'it\'s;here'",
    ],
)
def test_ignores_delimiter_inside_quotes(statement):
    assert split_mysql_statements(f"{statement};SELECT 2;") == [statement, "SELECT 2"]


def test_drops_comments_between_statements():
    sql = "-- first; note\n/* second; note */\n# third; note\nSELECT 1;"

    assert split_mysql_statements(sql) == ["SELECT 1"]


def test_keeps_comments_inside_statement_and_ignores_their_contents():
    sql = "SELECT 1 -- don't; stop\n, 2 /* it's; fine */;SELECT 3;"

    assert split_mysql_statements(sql) == [
        "SELECT 1 -- don't; stop\n, 2 /* it's; fine */",
        "SELECT 3",
    ]


def test_double_dash_without_space_is_not_a_comment():
    assert split_mysql_statements("SELECT 1--1;SELECT 2;") == ["SELECT 1--1", "SELECT 2"]


def test_keeps_version_comments():
    assert split_mysql_statements("/*!40101 SET NAMES utf8 */;") == ["/*!40101 SET NAMES utf8 */"]


@pytest.mark.parametrize("sql", ["SELECT 'oops;", "SELECT /* oops;", "/*!40101 oops;"])
def test_unterminated_quote_or_comment_raises(sql):
    with pytest.raises(SplitError, match="unterminated"):
        split_mysql_statements(sql)


def test_backslash_is_ordinary_when_escapes_are_off():
    sql = "SELECT 'C:\\';SELECT 2;"

    assert split_mysql_statements(sql, backslash_escapes=False) == ["SELECT 'C:\\'", "SELECT 2"]
