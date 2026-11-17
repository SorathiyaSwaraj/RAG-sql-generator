# ADR 0004: Catalog contents and field documentation

**Status:** Accepted

**Decision:** The catalog holds tables, columns, keys, foreign keys, comments, views, and procedures. Field meanings live in separate CSV files and merge by exact table and column name during ingestion. Oracle system tables are excluded using `SHARING=METADATA`.

**Why not a separate search collection?** A description found apart from its column gives the LLM a meaning with no usable name.

**Consequences:** A new dump does not overwrite documentation, and unmatched rows are reported. Triggers and secondary indexes are left out.
