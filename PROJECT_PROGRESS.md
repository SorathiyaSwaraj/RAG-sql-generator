# Project progress

**Objective:** Generate accurate SQL queries and stored procedures from natural language, grounded in a large schema and existing procedure patterns.

**Status on 2026-11-01:** All planned sections are built. LLM generation has not run against a real provider.

## Decisions

| Decision | Choice | Record |
| --- | --- | --- |
| Publishing | Public code, private schema | ADR 0001 |
| LLM | Gemini free tier, Ollama fallback | ADR 0002 |
| Parsing | Custom splitters, sqlglot for MySQL, small Oracle parser | ADR 0003 |
| Catalog | Core objects, merged field docs | ADR 0004 |
| Retrieval | Hybrid, foreign-key expansion, NumPy | ADR 0005 |
| Orchestration | Plain Python, LangChain as a baseline | ADR 0006 |
| Correctness | Static checks plus manual runs, no execution | ADR 0007 |

## Completed

- Ingestion for MySQL and Oracle, with field-doc merging
- BM25, local vectors, fusion, and foreign-key expansion
- Static validation, provider fallback, prompt building, repair loop
- Retrieval evaluation and LangChain comparison, both measured
- CLI, docs, and 125+ passing tests

## Next steps, in priority order

1. Get a free Gemini key at Google AI Studio, then generate a few queries and read the results.
2. Write 30 real questions in `eval/questions.jsonl`, including unanswerable ones.
3. Run `eval-generation`, execute the SQL on the sandbox, and fill in `manual_correct`.
4. Add the measured results to `docs/EVALUATION.md`.
5. Test weighted fusion that favours BM25, using those real questions.
6. Investigate the Oracle quote-tracking failure on one procedure.

## Known issues

- Generation is untested against a real LLM, and the default model names may need changing.
- Most inner statements of dynamic-SQL procedures cannot be validated.
- Oracle field docs do not exist yet.

## Interview topics to revise

From the exercises so far: how `DELIMITER` works, classifying unknown statements, and why `DEFINER` should not be copied.
