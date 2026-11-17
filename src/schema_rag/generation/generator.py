"""Retrieve, generate, validate, and retry when static checks find errors."""

import re
from dataclasses import dataclass

from schema_rag.generation.llm import LLMProvider
from schema_rag.generation.prompts import Kind, build_prompt
from schema_rag.retrieval.retriever import RetrievalResult, SchemaRetriever
from schema_rag.validation import ValidationResult, validate_procedure, validate_query

_FENCE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)
MAX_REPAIRS = 2


@dataclass
class GenerationResult:
    sql: str
    validation: ValidationResult
    attempts: int
    provider: str
    retrieval: RetrievalResult

    @property
    def status(self) -> str:
        if self.validation.passed:
            return "statically validated, not executed"
        return "FAILED static validation, do not run without fixing"


def extract_sql(text: str) -> str:
    match = _FENCE.search(text)
    return (match.group(1) if match else text).strip().rstrip(";").strip()


def retrieve_context(
    retriever: SchemaRetriever, kind: Kind, request: str, fields: list[str], **kwargs
) -> RetrievalResult:
    return retriever.retrieve(
        request, fields, procedure_k=3 if kind == "procedure" else 1, **kwargs
    )


def generate(
    retriever: SchemaRetriever,
    provider: LLMProvider,
    kind: Kind,
    request: str,
    fields: list[str] | None = None,
    retrieval: RetrievalResult | None = None,
    max_repairs: int = MAX_REPAIRS,
) -> GenerationResult:
    fields = fields or []
    catalog = retriever.catalog
    retrieval = retrieval or retrieve_context(retriever, kind, request, fields)
    validate = validate_query if kind == "query" else validate_procedure

    previous, errors = None, None
    for attempt in range(1, max_repairs + 2):
        prompt = build_prompt(
            catalog,
            kind,
            request,
            fields,
            retrieval.tables,
            retrieval.procedures,
            previous_sql=previous,
            errors=errors,
        )
        completion = provider.complete(prompt)
        sql = extract_sql(completion.text)
        validation = validate(sql, catalog)
        if validation.passed or attempt == max_repairs + 1:
            return GenerationResult(sql, validation, attempt, completion.provider, retrieval)
        previous, errors = sql, validation.errors
    raise AssertionError("unreachable")
