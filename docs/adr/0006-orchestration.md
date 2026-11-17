# ADR 0006: Plain Python, with LangChain only as a comparison

**Status:** Accepted

**Options:** Plain Python, LlamaIndex or LangChain, LangGraph.

**Decision:** The pipeline is plain Python because its valuable parts (schema parsing, graph expansion, static validation) are custom, and the single retry loop does not need a graph framework. LangChain appears only in `experiments/`, as a baseline.

**Consequences:** We own prompt building and provider adapters. The core stays dependency-light and easy to debug.
