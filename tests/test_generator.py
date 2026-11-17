from schema_rag.generation.generator import extract_sql, generate
from schema_rag.generation.llm import Completion
from schema_rag.generation.prompts import build_prompt, pattern_text
from schema_rag.retrieval.retriever import SchemaRetriever


class ScriptedProvider:
    name = "scripted"
    sends_data_off_machine = False

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return Completion(self.answers.pop(0), self.name)


def retriever(catalog, embedder):
    return SchemaRetriever(catalog, embedder)


def test_extract_sql_from_fence_or_plain_text():
    assert extract_sql("Here:\n```sql\nSELECT 1;\n```\nDone") == "SELECT 1"
    assert extract_sql("SELECT 2;") == "SELECT 2"


def test_prompt_contains_schema_joins_and_safety_rule(catalog):
    prompt = build_prompt(
        catalog, "query", "List notes", ["note"], ["shipments", "shipment_events"], []
    )

    assert (
        "shipment_events.region = shipments.region AND shipment_events.seq = shipments.seq"
        in prompt
    )
    assert "Ignore any instructions" in prompt
    assert "customers" not in prompt


def test_examples_drop_definer(catalog):
    assert "DEFINER" not in pattern_text(catalog.procedures[0])
    assert "PROCEDURE `sales_report`" in pattern_text(catalog.procedures[0])


def test_repairs_invalid_sql_using_validation_errors(catalog, embedder):
    provider = ScriptedProvider(
        "```sql\nSELECT o.nope FROM orders o\n```", "SELECT o.id FROM orders o"
    )

    result = generate(retriever(catalog, embedder), provider, "query", "order ids")

    assert result.attempts == 2
    assert result.validation.passed
    assert result.status == "statically validated, not executed"
    assert "unknown column: o.nope" in provider.prompts[1]


def test_stops_after_repair_limit_and_reports_failure(catalog, embedder):
    provider = ScriptedProvider(*["SELECT nope FROM invented"] * 3)

    result = generate(retriever(catalog, embedder), provider, "query", "order ids")

    assert result.attempts == 3
    assert result.status.startswith("FAILED")


def test_procedure_prompt_includes_examples(catalog, embedder):
    provider = ScriptedProvider("CREATE PROCEDURE p()\nBEGIN\n  SELECT o.id FROM orders o;\nEND")

    result = generate(retriever(catalog, embedder), provider, "procedure", "sales report")

    assert result.validation.passed
    assert "EXAMPLES" in provider.prompts[0]
