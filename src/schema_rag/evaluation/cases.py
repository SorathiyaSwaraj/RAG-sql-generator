"""Evaluation cases: hand-written questions, and ones derived from stored procedures."""

import json
import re
from pathlib import Path

from pydantic import BaseModel

from schema_rag.generation.prompts import Kind
from schema_rag.models import Procedure, SchemaCatalog

_TABLE_REFERENCE = re.compile(
    r'\b(?:FROM|JOIN|UPDATE|INTO)\s+(?:[`"]?\w+[`"]?\.)?[`"]?(\w+)[`"]?', re.IGNORECASE
)
_DIGIT_SUFFIX = re.compile(r"[_\s]*\d+$")
_OUTPUT_ALIAS = re.compile(r"""\bAS\s+[`'"]([A-Za-z][\w ./%-]*)[`'"]""", re.IGNORECASE)
_MAX_FIELDS = 15


class EvalCase(BaseModel):
    id: str
    kind: Kind = "query"
    request: str
    fields: list[str] = []
    gold_tables: list[str] = []
    unanswerable: bool = False
    exclude_procedure: str | None = None


def load_cases(path: Path) -> list[EvalCase]:
    lines = path.read_text("utf-8").splitlines()
    return [EvalCase.model_validate(json.loads(line)) for line in lines if line.strip()]


def tables_used_by(procedure: Procedure, catalog: SchemaCatalog) -> list[str]:
    names = {table.name.casefold(): table.name for table in catalog.tables}
    found = {match.casefold() for match in _TABLE_REFERENCE.findall(procedure.definition)}
    return sorted(names[name] for name in found if name in names)


def output_fields_of(procedure: Procedure) -> list[str]:
    """The quoted output column labels, which stand in for the fields a developer asks for."""
    labels = dict.fromkeys(_OUTPUT_ALIAS.findall(procedure.definition))
    return list(labels)[:_MAX_FIELDS]


def cases_from_procedures(catalog: SchemaCatalog, with_fields: bool = False) -> list[EvalCase]:
    """Treat each procedure's name as the request and its tables as the right answer.

    This gives a measurable set with no manual labelling. Names are terse and the
    set is small, so it is a useful baseline and not a substitute for real questions.
    with_fields adds the procedure's output labels, closer to how the tool is used.
    """
    cases = []
    for procedure in catalog.procedures:
        gold = tables_used_by(procedure, catalog)
        if gold:
            request = _DIGIT_SUFFIX.sub("", procedure.name).replace("_", " ").lower()
            cases.append(
                EvalCase(
                    id=procedure.name,
                    kind="procedure",
                    request=request,
                    fields=output_fields_of(procedure) if with_fields else [],
                    gold_tables=gold,
                    exclude_procedure=procedure.name,
                )
            )
    return cases
