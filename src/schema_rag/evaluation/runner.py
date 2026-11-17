"""Runs retrieval and generation evaluations and records raw results."""

import csv
import re
import statistics
import time
from collections.abc import Sequence
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from schema_rag.evaluation.cases import EvalCase
from schema_rag.evaluation.metrics import all_found, ndcg, precision, recall, reciprocal_rank
from schema_rag.generation.generator import generate, retrieve_context
from schema_rag.generation.llm import LLMProvider
from schema_rag.retrieval.retriever import MODES, Mode, SchemaRetriever

_TABLE_REFERENCE = re.compile(r'\b(?:FROM|JOIN)\s+[`"]?(\w+)[`"]?', re.IGNORECASE)


def evaluate_retrieval(
    retriever: SchemaRetriever,
    cases: Sequence[EvalCase],
    top_ks: Sequence[int] = (5, 10, 20),
    modes: Sequence[Mode] = MODES,
) -> list[dict]:
    rows = []
    usable = [case for case in cases if case.gold_tables]
    for mode in modes:
        for k in top_ks:
            scores: dict[str, list[float]] = {
                "recall": [],
                "precision": [],
                "all_found": [],
                "mrr": [],
                "ndcg": [],
                "tables_returned": [],
            }
            for case in usable:
                gold = set(case.gold_tables)
                tables = retriever.retrieve(
                    case.request, case.fields, mode=mode, top_k=k, procedure_k=0
                ).tables
                scores["recall"].append(recall(tables, gold))
                scores["precision"].append(precision(tables, gold))
                scores["all_found"].append(all_found(tables, gold))
                scores["mrr"].append(reciprocal_rank(tables, gold))
                scores["ndcg"].append(ndcg(tables, gold))
                scores["tables_returned"].append(len(tables))
            rows.append(
                {"mode": mode, "k": k, "cases": len(usable)}
                | {name: round(statistics.mean(values), 3) for name, values in scores.items()}
            )
    return rows


def format_table(rows: Sequence[dict]) -> str:
    if not rows:
        return "(no results)"
    headers = list(rows[0])
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    lines += ["| " + " | ".join(str(row[h]) for h in headers) + " |" for row in rows]
    return "\n".join(lines)


def tables_in_sql(sql: str, dialect: str) -> set[str]:
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
        derived = {cte.alias.casefold() for cte in tree.find_all(exp.CTE)}
        return {t.name.casefold() for t in tree.find_all(exp.Table)} - derived
    except (ParseError, TokenError):
        # Procedural code usually does not parse, so fall back to a text search.
        return {name.casefold() for name in _TABLE_REFERENCE.findall(sql)}


def evaluate_generation(
    retriever: SchemaRetriever,
    provider: LLMProvider,
    cases: Sequence[EvalCase],
    output_csv: Path,
) -> dict:
    """Writes one row per case. manual_correct is blank for a person who ran the SQL."""
    rows = []
    for case in cases:
        retrieval = retrieve_context(
            retriever,
            case.kind,
            case.request,
            case.fields,
            exclude_procedure=case.exclude_procedure,
        )
        started = time.perf_counter()
        result = generate(
            retriever, provider, case.kind, case.request, case.fields, retrieval=retrieval
        )
        used = tables_in_sql(result.sql, retriever.catalog.dialect)
        gold = {name.casefold() for name in case.gold_tables}
        rows.append(
            {
                "id": case.id,
                "kind": case.kind,
                "request": case.request,
                "provider": result.provider,
                "passed_static_checks": result.validation.passed,
                "attempts": result.attempts,
                "errors": " | ".join(result.validation.errors),
                "warnings": " | ".join(result.validation.warnings),
                "gold_table_recall": round(recall(list(used), gold), 3) if gold else "",
                "seconds": round(time.perf_counter() - started, 1),
                "unanswerable": case.unanswerable,
                "sql": result.sql,
                "manual_correct": "",
            }
        )
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["id"])
        writer.writeheader()
        writer.writerows(rows)
    scored = [row["gold_table_recall"] for row in rows if row["gold_table_recall"] != ""]
    return {
        "cases": len(rows),
        "passed_first_attempt": sum(r["passed_static_checks"] and r["attempts"] == 1 for r in rows),
        "passed_after_repair": sum(r["passed_static_checks"] for r in rows),
        "mean_gold_table_recall": round(statistics.mean(scored), 3) if scored else None,
        "mean_seconds": round(statistics.mean(r["seconds"] for r in rows), 1) if rows else None,
    }
