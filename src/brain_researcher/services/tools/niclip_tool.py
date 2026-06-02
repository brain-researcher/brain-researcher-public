"""NiCLIP helper tools: text embedding and reranking."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from brain_researcher.services.br_kg.niclip.rerank import encode_texts, rerank_items
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class NiclipEmbedArgs(BaseModel):
    texts: list[str] = Field(
        ...,
        description="Texts to embed via NiCLIP vocabulary encoder",
    )


class NiclipRerankArgs(BaseModel):
    query: str = Field(..., description="Query text to compare against candidates")
    candidates: list[str] = Field(..., description="Candidate strings to rerank")
    top_k: int | None = Field(default=None, description="Optional max results")


class NiclipEmbedTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "niclip.embed_text"

    def get_tool_description(self) -> str:
        return "Embed text using NiCLIP vocabulary encoder (returns vectors when available)."

    def get_args_schema(self):
        return NiclipEmbedArgs

    def _run(self, texts: list[str]) -> ToolResult:
        vecs, err = encode_texts(texts)
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

    def _run(
        self,
        query: str,
        candidates: list[str],
        top_k: int | None = None,
    ) -> ToolResult:
        items = [{"name": c} for c in candidates]
        reranked, meta = rerank_items(query, items, text_key="name", top_k=top_k)
        return ToolResult(
            status="success" if meta.get("status") == "ok" else "error",
            data={"outputs": {"reranked": reranked, "meta": meta}},
            error=None if meta.get("status") == "ok" else meta.get("reason"),
        )


class NiclipTools:
    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [NiclipEmbedTool(), NiclipRerankTool()]


__all__ = [
    "NiclipEmbedTool",
    "NiclipRerankTool",
    "NiclipTools",
    "rerank_items",
]
