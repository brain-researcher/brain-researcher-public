"""NiCLIP helper tools: text embedding and reranking."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.neurokg.niclip.engine import NiclipEngine

logger = logging.getLogger(__name__)


def _cosine_sim(query_vec: np.ndarray, cand_vecs: np.ndarray) -> np.ndarray:
    if query_vec.ndim != 1:
        query_vec = query_vec.reshape(-1)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return np.zeros((cand_vecs.shape[0],), dtype=np.float32)
    c_norms = np.linalg.norm(cand_vecs, axis=1)
    denom = (c_norms * q_norm)
    denom[denom == 0] = 1.0
    return (cand_vecs @ query_vec) / denom


def _encode_texts(texts: List[str]) -> Tuple[Optional[np.ndarray], Optional[str]]:
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
    items: List[Dict[str, Any]],
    *,
    text_key: str = "name",
    top_k: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    texts = [str(item.get(text_key, "")) for item in items]
    if not texts:
        return items, {"status": "skipped", "reason": "empty_items"}

    vecs, err = _encode_texts([query] + texts)
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


class NiclipEmbedArgs(BaseModel):
    texts: List[str] = Field(..., description="Texts to embed via NiCLIP vocabulary encoder")


class NiclipRerankArgs(BaseModel):
    query: str = Field(..., description="Query text to compare against candidates")
    candidates: List[str] = Field(..., description="Candidate strings to rerank")
    top_k: Optional[int] = Field(default=None, description="Optional max results")


class NiclipEmbedTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "niclip.embed_text"

    def get_tool_description(self) -> str:
        return "Embed text using NiCLIP vocabulary encoder (returns vectors when available)."

    def get_args_schema(self):
        return NiclipEmbedArgs

    def _run(self, texts: List[str]) -> ToolResult:
        vecs, err = _encode_texts(texts)
        if vecs is None:
            return ToolResult(status="error", error=err or "NiCLIP unavailable")
        return ToolResult(
            status="success",
            data={"outputs": {"embeddings": vecs.tolist(), "dimension": vecs.shape[1]}},
        )


class NiclipRerankTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "niclip.rerank"

    def get_tool_description(self) -> str:
        return "Re-rank candidate strings using NiCLIP text embeddings (cosine similarity)."

    def get_args_schema(self):
        return NiclipRerankArgs

    def _run(self, query: str, candidates: List[str], top_k: Optional[int] = None) -> ToolResult:
        items = [{"name": c} for c in candidates]
        reranked, meta = rerank_items(query, items, text_key="name", top_k=top_k)
        return ToolResult(
            status="success" if meta.get("status") == "ok" else "error",
            data={"outputs": {"reranked": reranked, "meta": meta}},
            error=None if meta.get("status") == "ok" else meta.get("reason"),
        )


class NiclipTools:
    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [NiclipEmbedTool(), NiclipRerankTool()]


__all__ = [
    "NiclipEmbedTool",
    "NiclipRerankTool",
    "NiclipTools",
    "rerank_items",
]
