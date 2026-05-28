"""Tests for brain_researcher.sdk.models."""

from __future__ import annotations

import pytest

from brain_researcher.sdk.models import JobHandle, ToolCard, ToolResult


class TestToolCard:
    def test_from_mcp_card_minimal(self):
        card = ToolCard.from_mcp_card({"name": "fsl.bet", "description": "Skull stripping"})
        assert card.name == "fsl.bet"
        assert card.description == "Skull stripping"
        assert card.backend == "python"
        assert card.modalities == []

    def test_from_mcp_card_full(self):
        data = {
            "name": "fsl.bet",
            "description": "Brain extraction",
            "backend": "niwrap",
            "modalities": ["smri"],
            "kind": "imaging",
            "category": "preprocessing",
            "tags": ["skull_strip"],
            "cost_hint": "normal",
            "requires_runtime": "container",
            "implementation_level": "production",
        }
        card = ToolCard.from_mcp_card(data)
        assert card.backend == "niwrap"
        assert card.modalities == ["smri"]
        assert card.kind == "imaging"
        assert card.cost_hint == "normal"
        assert card.requires_runtime == "container"

    def test_from_mcp_card_missing_fields(self):
        card = ToolCard.from_mcp_card({})
        assert card.name == ""
        assert card.description == ""

    def test_model_dump_roundtrip(self):
        card = ToolCard(name="test", description="a test tool")
        d = card.model_dump()
        assert d["name"] == "test"
        card2 = ToolCard(**d)
        assert card2 == card


class TestToolResult:
    def test_from_mcp_response_ok(self):
        raw = {
            "ok": True,
            "resolved_tool_id": "fsl.bet",
            "result": {"output_path": "/tmp/out.nii.gz"},
            "run_id": "run_001",
            "warnings": ["low contrast"],
        }
        result = ToolResult.from_mcp_response(raw)
        assert result.ok is True
        assert result.tool_id == "fsl.bet"
        assert result.output_path == "/tmp/out.nii.gz"
        assert result.run_id == "run_001"
        assert result.warnings == ["low contrast"]

    def test_from_mcp_response_failure(self):
        raw = {"ok": False, "error": "tool_not_found"}
        result = ToolResult.from_mcp_response(raw)
        assert result.ok is False
        assert result.output_path is None

    def test_output_path_fallbacks(self):
        r1 = ToolResult(ok=True, output={"output_file": "/a.nii"})
        assert r1.output_path == "/a.nii"

        r2 = ToolResult(ok=True, output={"output": "/b.nii"})
        assert r2.output_path == "/b.nii"

        r3 = ToolResult(ok=True, output={})
        assert r3.output_path is None


class TestJobHandle:
    def test_content_hash_deterministic(self):
        h1 = JobHandle.compute_content_hash("fsl.bet", {"input": "a.nii"})
        h2 = JobHandle.compute_content_hash("fsl.bet", {"input": "a.nii"})
        assert h1 == h2

    def test_content_hash_differs_on_params(self):
        h1 = JobHandle.compute_content_hash("fsl.bet", {"input": "a.nii"})
        h2 = JobHandle.compute_content_hash("fsl.bet", {"input": "b.nii"})
        assert h1 != h2

    def test_content_hash_differs_on_tool_id(self):
        h1 = JobHandle.compute_content_hash("fsl.bet", {})
        h2 = JobHandle.compute_content_hash("fsl.flirt", {})
        assert h1 != h2
