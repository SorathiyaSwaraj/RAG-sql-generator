# ADR 0005: Hybrid retrieval with foreign-key expansion and NumPy storage

**Status:** Accepted

**Context:** About 4,000 columns per database is small enough for exact search. Requests mix business language and exact field names. Joins may need tables that sound unrelated.

**Options:** Vector search only; BM25 only; hybrid plus graph. For storage: NumPy, FAISS, Chroma, Qdrant, pgvector.

**Decision:** Combine local `bge-small-en-v1.5` vectors and BM25 using reciprocal rank fusion, then add tables on short foreign-key paths between results. Each table gets one summary vector and one vector per column, because the model reads about 512 tokens. Vectors are stored in `.npy` files. The model runs through `fastembed` (ONNX) to avoid installing PyTorch.

**Consequences:** See `docs/EVALUATION.md`. Foreign-key expansion clearly raised recall. Fusing in vector search lowered ranking quality compared with BM25 alone on the with-fields MySQL test, so fusion weights are worth testing on real questions. Scaling to millions of vectors would require an approximate index.
