"""Local embeddings. Nothing in this module sends schema text off the machine."""

from pathlib import Path
from typing import Protocol

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    """Runs bge-small through ONNX on the CPU. The model downloads once, then stays cached."""

    def __init__(self, cache_dir: Path) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(MODEL_NAME, cache_dir=str(cache_dir))

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return normalize(np.array(list(self._model.passage_embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(np.array(list(self._model.query_embed(text)), dtype=np.float32))[0]


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Unit length makes the dot product equal cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)
