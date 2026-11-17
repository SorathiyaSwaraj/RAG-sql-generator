import pytest

from schema_rag.validation import validate_procedure, validate_query


def test_accepts_valid_join(catalog):
    sql = "SELECT c.full_name, o.placed_on FROM customers c JOIN orders o ON o.customer_id = c.id"

    result = validate_query(sql, catalog)

    assert result.errors == []
    assert result.warnings == []


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("SELECT id FROM invented", "unknown table: invented"),
        ("SELECT o.invented FROM orders o", "unknown column: o.invented"),
        ("SELECT invented FROM orders", "unknown column: invented"),
        ("SELECT x.id FROM orders o", "unknown table alias: x"),
        ("SELECT FROM WHERE", "syntax error"),
        ("DELETE FROM orders", "only read-only"),
        ("DROP TABLE orders", "only read-only"),
        ("SELECT 1; SELECT 2", "expected one statement"),
    ],
)
def test_rejects_bad_queries(catalog, sql, error):
    result = validate_query(sql, catalog)

    assert not result.passed
    assert error in result.errors[0]


def test_names_are_case_insensitive(catalog):
    assert validate_query("SELECT O.ID FROM ORDERS O", catalog).passed


def test_cte_columns_are_not_checked_against_schema(catalog):
    sql = "WITH recent AS (SELECT id AS rid FROM orders) SELECT r.rid FROM recent r"

    assert validate_query(sql, catalog).passed


def test_invented_column_inside_cte_is_still_caught(catalog):
    sql = "WITH recent AS (SELECT o.nope FROM orders o) SELECT r.nope FROM recent r"

    assert "unknown column: o.nope" in validate_query(sql, catalog).errors


def test_order_by_select_alias_is_allowed(catalog):
    assert validate_query("SELECT id AS n FROM orders ORDER BY n", catalog).passed


def test_warns_on_partial_composite_join(catalog):
    sql = "SELECT e.note FROM shipment_events e JOIN shipments s ON e.region = s.region"

    result = validate_query(sql, catalog)

    assert result.passed
    assert "only part of a composite key" in result.warnings[0]


def test_full_composite_join_has_no_warning(catalog):
    sql = (
        "SELECT e.note FROM shipment_events e "
        "JOIN shipments s ON e.region = s.region AND e.seq = s.seq"
    )

    assert validate_query(sql, catalog).warnings == []


def test_warns_when_join_ignores_foreign_key(catalog):
    sql = "SELECT 1 FROM orders o JOIN customers c ON o.id = c.id"

    assert "does not follow its foreign key" in validate_query(sql, catalog).warnings[0]


def test_procedure_checks_inner_statements(catalog):
    sql = (
        "CREATE PROCEDURE p(IN d date)\nBEGIN\n"
        "  SELECT o.nope FROM orders o WHERE o.placed_on >= d;\n"
        "  SELECT c.id FROM customers c;\nEND"
    )

    result = validate_procedure(sql, catalog)

    assert result.statements_checked >= 1
    assert "unknown column: o.nope" in result.errors


def test_procedure_allows_parameters_as_unqualified_names(catalog):
    sql = "CREATE PROCEDURE p(IN d date)\nBEGIN\n  SELECT o.id FROM orders o WHERE d = o.id;\nEND"

    assert validate_procedure(sql, catalog).passed


def test_procedure_warns_on_definer_and_writes(catalog):
    sql = "CREATE DEFINER=`a`@`b` PROCEDURE p()\nBEGIN\n  DELETE FROM orders;\nEND"

    result = validate_procedure(sql, catalog)

    assert any("DEFINER" in warning for warning in result.warnings)


def test_rejects_output_that_is_not_a_procedure(catalog):
    assert not validate_procedure("SELECT 1", catalog).passed


def test_procedure_temporary_tables_are_known(catalog):
    sql = (
        "CREATE PROCEDURE p()\nBEGIN\n"
        "  CREATE TEMPORARY TABLE Temp_X (id int);\n"
        "  SELECT t.id FROM Temp_X t;\nEND"
    )

    assert validate_procedure(sql, catalog).passed


def test_procedure_reports_statements_it_cannot_check(catalog):
    sql = "CREATE PROCEDURE p()\nBEGIN\n  SET @q = CONCAT('SELECT id ', 'FROM orders');\nEND"

    result = validate_procedure(sql, catalog)

    assert result.statements_unparsed == 1
    assert any("could not be checked" in warning for warning in result.warnings)
