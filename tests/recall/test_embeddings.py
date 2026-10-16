from __future__ import annotations

from typing import Any

import pytest

from decisiontrace.recall.embeddings import HashingEmbedder, embed_missing, get_embedder
from decisiontrace.recall.precedent import search
from decisiontrace.store import Store
from tests.conftest import example_records


def test_off_by_default(config: Any) -> None:
    assert get_embedder(config.home) is None


def test_hashing_provider_from_config(config: Any) -> None:
    path = config.home / "config.toml"
    path.write_text(path.read_text() + '\n[recall]\nembeddings = "hashing"\n')
    assert get_embedder(config.home) is not None


def test_embed_and_hybrid_search(store: Store) -> None:
    store.append_many(example_records())
    emb = HashingEmbedder()
    assert embed_missing(store, emb) == 10
    assert embed_missing(store, emb) == 0
    hits = search(store, "refund limit exception", limit=3, embedder=emb)
    assert hits[0].trace.decision_kind == "refund.approve"


def test_sqlite_vec_and_python_paths_agree(store: Store) -> None:
    pytest.importorskip("sqlite_vec")
    store.append_many(example_records())
    emb = HashingEmbedder()
    embed_missing(store, emb)
    q = emb.embed(["refund damaged parcel"])[0]
    with_vec = store.nearest(emb.name, q, k=5)
    store._vec = False  # force the pure-Python fallback
    without = store.nearest(emb.name, q, k=5)
    assert [r for r, _ in with_vec] == [r for r, _ in without]
    for (_, a), (_, b) in zip(with_vec, without, strict=True):
        assert a == pytest.approx(b, abs=1e-5)
