"""Command line interface. Run `schema-rag --help` for the commands."""

import argparse
import json
import sys
from pathlib import Path

from schema_rag.config import Settings, load_settings
from schema_rag.evaluation.cases import cases_from_procedures, load_cases
from schema_rag.evaluation.runner import evaluate_generation, evaluate_retrieval, format_table
from schema_rag.generation.generator import generate, retrieve_context
from schema_rag.generation.llm import LLMError, LLMProvider, build_provider
from schema_rag.generation.prompts import build_prompt
from schema_rag.ingestion.pipeline import ingest, load_catalog, save_catalog
from schema_rag.retrieval.documents import without_docs
from schema_rag.retrieval.embeddings import FastEmbedEmbedder
from schema_rag.retrieval.retriever import MODES, RetrievalResult, SchemaRetriever
from schema_rag.validation import validate_procedure, validate_query


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings(args.config)
    try:
        return args.handler(args, settings)
    except (LLMError, FileNotFoundError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="schema-rag", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/databases.yaml"))
    commands = parser.add_subparsers(required=True)

    command = commands.add_parser("ingest", help="parse a dump and save its catalog")
    command.add_argument("database")
    command.set_defaults(handler=_ingest)

    command = commands.add_parser("retrieve", help="show what retrieval finds")
    _add_request_arguments(command)
    command.add_argument("--mode", choices=MODES, default="hybrid_graph")
    command.add_argument("--top-k", type=int, default=10)
    command.set_defaults(handler=_retrieve)

    command = commands.add_parser("generate", help="generate SQL without executing it")
    command.add_argument("kind", choices=["query", "procedure"])
    _add_request_arguments(command)
    command.add_argument("--top-k", type=int, default=10)
    command.add_argument("--provider", choices=["auto", "gemini", "ollama"], default="auto")
    command.add_argument("--dry-run", action="store_true", help="print the prompt and send nothing")
    command.add_argument("--yes", action="store_true", help="skip the data sharing confirmation")
    command.set_defaults(handler=_generate)

    command = commands.add_parser("validate", help="statically check a SQL file")
    command.add_argument("kind", choices=["query", "procedure"])
    command.add_argument("database")
    command.add_argument("file", type=Path)
    command.set_defaults(handler=_validate)

    command = commands.add_parser("eval-retrieval", help="measure retrieval quality")
    command.add_argument("database")
    command.add_argument("--cases", type=Path, help="JSONL questions (default: from procedures)")
    command.add_argument("--with-fields", action="store_true", help="add output labels to cases")
    command.set_defaults(handler=_eval_retrieval)

    command = commands.add_parser("eval-generation", help="generate for every case into a CSV")
    command.add_argument("database")
    command.add_argument("--cases", type=Path, help="JSONL questions (default: from procedures)")
    command.add_argument("--provider", choices=["auto", "gemini", "ollama"], default="auto")
    command.add_argument("--yes", action="store_true", help="skip the data sharing confirmation")
    command.set_defaults(handler=_eval_generation)
    return parser


def _add_request_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("database")
    command.add_argument("request")
    command.add_argument("--fields", default="", help="comma-separated fields wanted in the output")


def _fields(args: argparse.Namespace) -> list[str]:
    return [name.strip() for name in args.fields.split(",") if name.strip()]


def _retriever(settings: Settings, name: str, use_docs: bool = True) -> SchemaRetriever:
    directory = settings.database_dir(name)
    catalog = load_catalog(directory)
    embedder = FastEmbedEmbedder(settings.data_dir / "models")
    catalog = catalog if use_docs else without_docs(catalog)
    return SchemaRetriever(catalog, embedder, directory / "vectors")


def _confirm_sharing(provider: LLMProvider, detail: str, assume_yes: bool) -> None:
    """Schema text only leaves the machine after the user has seen where it is going."""
    if not provider.sends_data_off_machine or assume_yes:
        return
    print(f"This sends {detail} to {provider.name}.", file=sys.stderr)
    print(
        "Unpaid Gemini API use may be used to improve Google's products and read by reviewers.",
        file=sys.stderr,
    )
    if input("Continue? [y/N] ").strip().lower() != "y":
        raise LLMError("cancelled, nothing was sent")


def _ingest(args: argparse.Namespace, settings: Settings) -> int:
    catalog, report = ingest(args.database, settings.database(args.database))
    save_catalog(catalog, report, settings.database_dir(args.database))
    print(json.dumps(report.model_dump(), indent=2))
    return 0


def _print_retrieval(result: RetrievalResult) -> None:
    print("tables:", ", ".join(result.seeds) or "(none)")
    print("connecting tables:", ", ".join(result.connectors) or "(none)")
    print("example procedures:", ", ".join(p.name for p in result.procedures) or "(none)")


def _retrieve(args: argparse.Namespace, settings: Settings) -> int:
    retriever = _retriever(settings, args.database)
    _print_retrieval(
        retriever.retrieve(args.request, _fields(args), mode=args.mode, top_k=args.top_k)
    )
    return 0


def _generate(args: argparse.Namespace, settings: Settings) -> int:
    retriever = _retriever(settings, args.database)
    fields = _fields(args)
    retrieval = retrieve_context(retriever, args.kind, args.request, fields, top_k=args.top_k)
    if args.dry_run:
        print(
            build_prompt(
                retriever.catalog,
                args.kind,
                args.request,
                fields,
                retrieval.tables,
                retrieval.procedures,
            )
        )
        return 0

    provider = build_provider(args.provider)
    _confirm_sharing(
        provider,
        f"the schema of {len(retrieval.tables)} tables ({', '.join(retrieval.tables)}) and "
        f"{len(retrieval.procedures)} procedures",
        args.yes,
    )
    result = generate(retriever, provider, args.kind, args.request, fields, retrieval=retrieval)
    print(result.sql)
    print(f"\n-- status: {result.status}")
    print(f"-- provider: {result.provider}, attempts: {result.attempts}")
    for message in result.validation.errors:
        print(f"-- error: {message}")
    for message in result.validation.warnings:
        print(f"-- warning: {message}")
    return 0 if result.validation.passed else 2


def _validate(args: argparse.Namespace, settings: Settings) -> int:
    catalog = load_catalog(settings.database_dir(args.database))
    check = validate_query if args.kind == "query" else validate_procedure
    result = check(args.file.read_text("utf-8"), catalog)
    print(
        json.dumps(
            {
                "passed": result.passed,
                "errors": result.errors,
                "warnings": result.warnings,
                "statements_checked": result.statements_checked,
                "statements_unparsed": result.statements_unparsed,
                "note": "static checks only, the SQL was not executed",
            },
            indent=2,
        )
    )
    return 0 if result.passed else 2


def _cases(args: argparse.Namespace, settings: Settings):
    if args.cases:
        return load_cases(args.cases)
    catalog = load_catalog(settings.database_dir(args.database))
    return cases_from_procedures(catalog, getattr(args, "with_fields", False))


def _eval_retrieval(args: argparse.Namespace, settings: Settings) -> int:
    cases = _cases(args, settings)
    results = {}
    catalog = load_catalog(settings.database_dir(args.database))
    variants = {"with_docs": True, "without_docs": False} if catalog.glossary else {"schema": True}
    for label, use_docs in variants.items():
        rows = evaluate_retrieval(_retriever(settings, args.database, use_docs), cases)
        results[label] = rows
        print(f"\n{args.database}, {label}\n{format_table(rows)}")
    suffix = "_with_fields" if args.with_fields else ""
    output = settings.database_dir(args.database) / "eval" / f"retrieval{suffix}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


def _eval_generation(args: argparse.Namespace, settings: Settings) -> int:
    cases = _cases(args, settings)
    provider = build_provider(args.provider)
    _confirm_sharing(provider, f"retrieved schema for {len(cases)} evaluation cases", args.yes)
    output = settings.database_dir(args.database) / "eval" / "generation.csv"
    summary = evaluate_generation(_retriever(settings, args.database), provider, cases, output)
    print(json.dumps(summary, indent=2))
    print(f"Results: {output}. Run the SQL yourself and fill in manual_correct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
