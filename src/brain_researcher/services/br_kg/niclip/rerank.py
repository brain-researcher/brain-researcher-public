"""NiCLIP text reranking helpers."""

from __future__ import annotations

from typing import Any

import numpy as np

from brain_researcher.services.br_kg.niclip.engine import NiclipEngine


def _cosine_sim(query_vec: np.ndarray, cand_vecs: np.ndarray) -> np.ndarray:
    if query_vec.ndim != 1:
        query_vec = query_vec.reshape(-1)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return np.zeros((cand_vecs.shape[0],), dtype=np.float32)
    c_norms = np.linalg.norm(cand_vecs, axis=1)
    denom = c_norms * q_norm
    denom[denom == 0] = 1.0
    return (cand_vecs @ query_vec) / denom


def encode_texts(texts: list[str]) -> tuple[np.ndarray | None, str | None]:
    engine = NiclipEngine.get()
    encoder = engine.get_text_encoder()
    if encoder is None or getattr(encoder, "embeddings", None) is None:
        return None, "NiCLIP text encoder unavailable"
    vecs = encoder.encode(texts)
    if vecs is None or not np.any(vecs):
        return None, "NiCLIP embeddings missing for provided texts"
    return vecs, None


def rerank_items(
    query: str,
    items: list[dict[str, Any]],
    *,
    text_key: str = "name",
    top_k: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    texts = [str(item.get(text_key, "")) for item in items]
    if not texts:
        return items, {"status": "skipped", "reason": "empty_items"}

    vecs, err = encode_texts([query] + texts)
    if vecs is None:
        return items, {"status": "unavailable", "reason": err}

    query_vec = vecs[0]
    cand_vecs = vecs[1:]
    scores = _cosine_sim(query_vec, cand_vecs)

    ranked = sorted(
        enumerate(items),
        key=lambda pair: float(scores[pair[0]]),
        reverse=True,
    )
    out = []
    for idx, item in ranked:
        enriched = dict(item)
        enriched["niclip_score"] = float(scores[idx])
        out.append(enriched)

    if top_k is not None:
        out = out[:top_k]

    return out, {"status": "ok", "method": "niclip_cosine", "n_items": len(out)}


__all__ = ["encode_texts", "rerank_items"]
