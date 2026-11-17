# ADR 0001: Build on private dumps and publish only code

**Status:** Accepted

**Context:** The project targets a real MySQL and Oracle schema. Other engineers should be able to read the code, but the schema should stay private.

**Options:** Public code with a private schema; publish everything; public code plus a public sample database.

**Decision:** Publish code and made-up test fixtures. Dumps, generated catalogs, field documents, and real evaluation questions are gitignored.

**Consequences:** Others cannot reproduce the real results without their own dump. A public sample database could be added later to fix this.
