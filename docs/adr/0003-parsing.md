# ADR 0003: Custom splitters, sqlglot for MySQL tables, a small parser for Oracle tables

**Status:** Accepted

**Context:** Dumps contain procedures, version comments, and vendor storage clauses. Splitting on semicolons breaks procedures. Oracle's SQL Developer export often has no statement terminators.

**Options:** Regex only; custom splitter plus sqlglot; restoring the dump and reading database metadata.

**Decision:** Use a dialect-specific splitter for each database. MySQL tables go through sqlglot. Oracle tables use a small quote-aware parser, because sqlglot rejects clauses such as `NOT NULL ENABLE` that the export always emits. Procedures are stored as exact text.

**Consequences:** No database needs to run during ingestion. A different Oracle export format may need new rules. Unknown statements are reported by keyword and never silently dropped.
