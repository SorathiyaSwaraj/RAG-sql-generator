import csv
from pathlib import Path

import pytest

from schema_rag.evaluation.cases import cases_from_procedures, load_cases, tables_used_by
from schema_rag.evaluation.metrics import all_found, ndcg, precision, recall, reciprocal_rank
from schema_rag.evaluation.runner import (
    evaluate_generation,
    evaluate_retrieval,
    format_table,
    tables_in_sql,
)
from schema_rag.generation.llm import Completion
from schema_rag.retrieval.retriever import SchemaRetriever


def test_metrics_by_hand():
    retrieved, gold = ["x", "a", "b", "y"], {"a", "b", "c"}

    assert recall(retrieved, gold) == pytest.approx(2 / 3)
    assert precision(retrieved, gold) == pytest.approx(2 / 4)
    assert reciprocal_rank(retrieved, gold) == pytest.approx(1 / 2)
    assert all_found(retrieved, gold) == 0.0
    assert all_found(retrieved, {"a", "b"}) == 1.0
    assert ndcg(["a", "b"], {"a", "b"}) == pytest.approx(1.0)
    assert 0 < ndcg(["x", "a"], {"a"}) < 1


def test_metrics_with_nothing():
    assert recall([], set()) == 0.0
    assert precision([], {"a"}) == 0.0
    assert ndcg([], {"a"}) == 0.0


def test_load_example_questions():
    cases = load_cases(Path("eval/questions.example.jsonl"))

    assert cases[0].fields == ["customer name", "order total"]
    assert cases[2].unanswerable is True
    assert cases[3].kind == "procedure"


def test_procedure_cases_use_only_catalog_tables(catalog):
    procedure = catalog.procedures[0].model_copy(
        update={"definition": "SELECT 1 FROM orders JOIN `products` JOIN dual_temp"}
    )

    assert tables_used_by(procedure, catalog) == ["orders", "products"]
    case = cases_from_procedures(catalog)[0]
    assert (case.request, case.exclude_procedure) == ("sales report", "sales_report")


def test_retrieval_evaluation_reports_every_mode_and_k(catalog, embedder):
    rows = evaluate_retrieval(
        SchemaRetriever(catalog, embedder), cases_from_procedures(catalog), top_ks=(1, 3)
    )

    assert len(rows) == 8
    assert all(0 <= row["recall"] <= 1 for row in rows)
    assert "| mode |" in format_table(rows)


def test_tables_in_sql_ignores_cte_names():
    sql = "WITH a AS (SELECT 1 FROM orders) SELECT * FROM a JOIN customers"

    assert tables_in_sql(sql, "mysql") == {"orders", "customers"}


def test_generation_evaluation_records_results_for_manual_review(catalog, embedder, tmp_path):
    class Provider:
        name = "scripted"
        sends_data_off_machine = False

        def complete(self, prompt):
            return Completion(
                "CREATE PROCEDURE p()\nBEGIN\n  SELECT o.id FROM orders o;\nEND", "scripted"
            )

    cases = cases_from_procedures(catalog)
    output = tmp_path / "generation.csv"

    summary = evaluate_generation(SchemaRetriever(catalog, embedder), Provider(), cases, output)

    rows = list(csv.DictReader(output.open()))
    assert summary["cases"] == len(rows) == 2
    assert summary["passed_after_repair"] == 2
    assert rows[0]["manual_correct"] == ""
    assert rows[0]["gold_table_recall"] == "1.0"


def test_procedure_cases_can_include_output_labels(catalog):
    procedure = catalog.procedures[0].model_copy(
        update={"definition": "SELECT o.id AS 'Order No', o.id AS `Order No`, 1 AS x FROM orders o"}
    )
    updated = catalog.model_copy(update={"procedures": (procedure,)})

    assert cases_from_procedures(updated)[0].fields == []
    assert cases_from_procedures(updated, with_fields=True)[0].fields == ["Order No"]
