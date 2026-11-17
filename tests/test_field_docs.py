from schema_rag.ingestion.field_docs import merge_field_docs
from schema_rag.models import Column, SchemaCatalog, Table


def catalog():
    table = Table(
        name="orders",
        columns=(Column(name="id", data_type="int"), Column(name="amt", data_type="int")),
    )
    return SchemaCatalog(database="shop", dialect="mysql", tables=(table,))


def write_docs(path):
    (path / "columns.csv").write_text(
        "table_name,column_name,meaning,synonyms,values_or_format,caveats,evidence,confidence\n"
        'orders,,"One row is one order",,,Soft deleted,a.py,high\n'
        "orders,amt,Net total,price | value,INR,,a.py,high\n"
        "orders,missing,Nope,,,,a.py,high\n"
        "ghost,,Nope,,,,a.py,high\n"
    )
    (path / "glossary.csv").write_text(
        "term,synonyms,definition,calculation_rule,related_columns,evidence,confidence\n"
        "Revenue,sales,Money earned,sum(amt),orders.amt,a.py,high\n"
    )


def test_merges_table_and_column_docs(tmp_path):
    write_docs(tmp_path)

    merged, report = merge_field_docs(catalog(), tmp_path)

    table = merged.tables[0]
    assert table.description == "One row is one order"
    assert table.caveats == "Soft deleted"
    assert table.columns[1].description == "Net total"
    assert table.columns[1].synonyms == ("price", "value")
    assert table.columns[1].values_or_format == "INR"
    assert table.columns[0].description is None
    assert merged.glossary[0].related_columns == ("orders.amt",)
    assert (report.documented_tables, report.documented_columns, report.glossary_terms) == (1, 1, 1)


def test_reports_rows_that_match_nothing(tmp_path):
    write_docs(tmp_path)

    _, report = merge_field_docs(catalog(), tmp_path)

    assert report.unmatched == ["orders.missing", "ghost"]


def test_missing_docs_leave_catalog_unchanged(tmp_path):
    merged, report = merge_field_docs(catalog(), tmp_path)

    assert merged == catalog()
    assert report.unmatched == []
