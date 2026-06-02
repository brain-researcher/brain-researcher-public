"""Compatibility checks for NiCLIP rerank helper relocation."""

from __future__ import annotations

import numpy as np

from brain_researcher.services.br_kg.niclip import rerank as rerank_module
from brain_researcher.services.tools import niclip_tool


def test_tools_niclip_tool_reexports_brkg_rerank_items() -> None:
    assert niclip_tool.rerank_items is rerank_module.rerank_items


def test_rerank_items_orders_by_cosine_similarity(monkeypatch) -> None:
    def fake_encode_texts(texts: list[str]):
        assert texts == ["auditory", "visual", "auditory cortex"]
        return (
            np.array(
                [
                    [1.0, 0.0],
                    [0.0, 1.0],
                    [1.0, 0.0],
                ],
                dtype=np.float32,
            ),
            None,
        )

    monkeypatch.setattr(rerank_module, "encode_texts", fake_encode_texts)

    items = [{"name": "visual"}, {"name": "auditory cortex"}]
    reranked, meta = rerank_module.rerank_items("auditory", items)

    assert meta["status"] == "ok"
    assert [item["name"] for item in reranked] == ["auditory cortex", "visual"]
    assert reranked[0]["niclip_score"] == 1.0
