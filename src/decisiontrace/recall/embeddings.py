"""Optional semantic recall. Off by default: full-text search needs no download.

Enable in ``~/.decisiontrace/config.toml``::

    [recall]
    embeddings = "model2vec"                 # or "model2vec:<hf-model-id>"

and ``pip install 'liquicent-decisiontrace[embeddings]'`` (model2vec + sqlite-vec, no
PyTorch). The first use downloads a small static model (~30 MB) once; after that everything
runs offline. Vectors are derived data kept outside the hash chain; ``dt reindex`` fills them.
"""

from __future__ import annotations

import hashlib
import math
import tomllib
from pathlib import Path
from typing import Any, Protocol

from decisiontrace.model import DecisionTrace
from decisiontrace.recall.text import index_text, tokens

DEFAULT_MODEL2VEC = "minishlab/potion-base-8M"


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic bag-of-words feature hashing. No download; used in tests and as a
    sanity baseline -- it is lexical, so it adds little over full-text search."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in tokens(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "big")
                vec[h % self.dim] += 1.0 if h & 1 else -1.0
            out.append(_normalise(vec))
        return out


class Model2VecEmbedder:
    def __init__(self, model_id: str = DEFAULT_MODEL2VEC) -> None:
        from model2vec import StaticModel  # optional dependency

        self._model = StaticModel.from_pretrained(model_id)
        self.name = f"model2vec:{model_id}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: Any = self._model.encode(texts)
        return [_normalise([float(x) for x in v]) for v in vectors]


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def setting(home: Path) -> str:
    path = home / "config.toml"
    if not path.exists():
        return "none"
    section = tomllib.loads(path.read_text(encoding="utf-8")).get("recall", {})
    return str(section.get("embeddings", "none")).strip() or "none"


def get_embedder(home: Path) -> Embedder | None:
    value = setting(home)
    if value == "none":
        return None
    if value.startswith("hashing"):
        return HashingEmbedder()
    if value.startswith("model2vec"):
        _, _, model_id = value.partition(":")
        return Model2VecEmbedder(model_id or DEFAULT_MODEL2VEC)
    raise ValueError(f"unknown embeddings provider {value!r} (none, model2vec, hashing)")


def embed_missing(store: Any, embedder: Embedder, batch: int = 256) -> int:
    """Compute vectors for decisions that don't have one for this model yet."""
    have = set(store.embeddings(embedder.name))
    todo: list[DecisionTrace] = [
        r
        for r in store.records(record_type="decision", newest_first=False)
        if isinstance(r, DecisionTrace) and r.id not in have
    ]
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        vectors = embedder.embed([index_text(t) for t in chunk])
        store.set_embeddings(
            embedder.name, [(t.id, v) for t, v in zip(chunk, vectors, strict=True)]
        )
    return len(todo)
