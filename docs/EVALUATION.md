# Evaluation

All numbers below were measured on the private dumps on 2026-11-01. Questions and table names stay private.

## Method

There is no hand-labelled question set yet, so cases come from stored procedures:

- **Request:** the procedure's name. The "with fields" variant adds up to 15 of its quoted output labels.
- **Correct answer:** the catalog tables that the procedure's text references.
- **Size:** 28 MySQL and 40 Oracle cases, with a mean of about 7 correct tables per case.

**k** is the number of tables taken from search. `hybrid_graph` then adds connecting tables, so it returns more than k.

## Ingestion

| Check | MySQL | Oracle |
| --- | --- | --- |
| Tables | 266 | 212, plus 131 system tables excluded |
| Columns | 4,183 | 3,708 |
| Foreign keys (composite) | 552 (18) | 425 (12) |
| Procedures | 28 | 40 |
| Unrecognized statements | 0 | 0 |
| Unresolved foreign-key targets | 0 | 0 |

MySQL table, foreign-key, primary-key, `NOT NULL`, and comment counts also match independent text searches of the dump.

## Retrieval: MySQL with fields and field docs

| Mode | k | Recall | Precision | All tables found | MRR | Tables returned |
| --- | --- | --- | --- | --- | --- | --- |
| Vector only | 10 | 0.316 | 0.175 | 0.036 | 0.386 | 10 |
| BM25 only | 10 | 0.490 | 0.304 | 0.071 | 0.838 | 10 |
| Hybrid | 10 | 0.435 | 0.261 | 0.071 | 0.684 | 10 |
| Hybrid + graph | 10 | 0.510 | 0.237 | 0.071 | 0.684 | 13.6 |
| Vector only | 20 | 0.438 | 0.134 | 0.036 | 0.400 | 20 |
| BM25 only | 20 | 0.651 | 0.211 | 0.179 | 0.838 | 20 |
| Hybrid | 20 | 0.601 | 0.191 | 0.107 | 0.684 | 20 |
| Hybrid + graph | 20 | 0.693 | 0.187 | 0.143 | 0.684 | 24.8 |

## Effect of field docs (MySQL, hybrid + graph, k=20, with fields)

| Field docs | Recall | MRR |
| --- | --- | --- |
| Without | 0.639 | 0.454 |
| With | 0.693 | 0.684 |

## Retrieval: Oracle with fields (no field docs)

| Mode | k | Recall | All tables found | MRR |
| --- | --- | --- | --- | --- |
| Vector only | 20 | 0.354 | 0.000 | 0.330 |
| BM25 only | 20 | 0.432 | 0.025 | 0.450 |
| Hybrid | 20 | 0.465 | 0.025 | 0.367 |
| Hybrid + graph | 20 | 0.634 | 0.100 | 0.368 |

## LangChain baseline (procedure name only, no fields)

The baseline uses recursive chunks of raw DDL and vector search, with the same embedding model.

| Database | k | LangChain recall | Hybrid + graph recall |
| --- | --- | --- | --- |
| MySQL | 10 | 0.160 | 0.337 |
| MySQL | 20 | 0.253 | 0.488 |
| Oracle | 10 | 0.110 | 0.339 |
| Oracle | 20 | 0.183 | 0.483 |

## Static validator on real procedures

| | MySQL | Oracle |
| --- | --- | --- |
| Procedures with no errors | 28 of 28 | 38 of 40 |
| Inner statements checked | 8 | 16 |
| Inner statements not parseable | 27 | 30 |

Oracle's two flags: one procedure references tables missing from the dump, and the other is a quote-tracking failure in our splitter that has not been investigated.

## What this does and does not show

- **Foreign-key expansion helped:** it raised recall in every comparison above, while also returning more tables.
- **Field docs helped, but the size is uncertain:** they were written using the procedures as evidence, so this test likely overstates the benefit.
- **Hybrid did not beat BM25 everywhere:** on MySQL with fields, BM25 alone had better recall and MRR than hybrid without the graph. Output labels resemble column names, which favours keyword search, so real questions may differ.
- **Complete retrieval is rare:** all correct tables were found in at most 18% of cases. These procedures are complex reports, so simple queries may do better, but this has not been measured.
- **Small sample:** with 28 to 40 cases, small differences may be noise.
- **The validator covers little of procedural code:** most inner statements in these procedures could not be checked.

## Not measured yet

- **LLM generation has never run against a real provider.** No API key or Ollama install was available. Provider code is tested only against local fake HTTP servers.
- Answer correctness, static pass rate of generated SQL, latency, token use, and repair-loop benefit.
- Unanswerable, ambiguous, and adversarial queries, which need a hand-written question set.
