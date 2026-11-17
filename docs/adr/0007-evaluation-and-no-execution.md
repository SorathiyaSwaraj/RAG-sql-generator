# ADR 0007: The tool never executes SQL

**Status:** Accepted

**Decision:** The tool only generates SQL and checks it statically: parsing, table and column existence, read-only queries, and foreign-key join patterns. Developers run the output themselves and record correctness in the evaluation CSV.

**Consequences:** It cannot detect valid SQL that returns wrong data, so output is labelled "statically validated, not executed". Procedure checks are partial: inner statements that use dynamic SQL cannot be parsed, and the validator reports how many it skipped.
