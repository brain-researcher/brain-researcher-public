"""Smoke-level planner tests for new LLM / coding domains.

These tests verify that:
- The PlanRequest model accepts llm_service / code_assistant with modality ["general"].
- The planner capability index includes the curated LLM and coding tools, and they
  are discoverable by capability/modality/package.
"""

import os

import pytest
from pydantic import ValidationError

from brain_researcher.services.shared.planner.models import PlanRequest
from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    search_by_capability,
    search_by_modality,
    search_by_package,
)


class TestPlanRequestDomains:
    def test_plan_request_accepts_llm_and_coding_domains(self):
        # llm_service + general modality should validate
        pr = PlanRequest(
            pipeline="summarize text",
            domain="llm_service",
            modality=["general"],
            inputs={"prompt": "hello"},
        )
        assert pr.domain == "llm_service"

        # code_assistant + general modality should validate
        pr2 = PlanRequest(
            pipeline="coding agent",
            domain="code_assistant",
            modality=["general"],
            inputs={"instruction": "fix bug"},
        )
        assert pr2.domain == "code_assistant"

        # legacy domains still work
        pr3 = PlanRequest(
            pipeline="neuro",
            domain="neuroimaging",
            modality=["fmri"],
            inputs={},
        )
        assert pr3.domain == "neuroimaging"

    def test_plan_request_rejects_unknown_domain(self):
        with pytest.raises(ValidationError):
            PlanRequest(pipeline="x", domain="unknown", modality=["general"], inputs={})


class TestCatalogVisibility:
    def test_llm_tools_present_but_coding_executor_hidden_by_default(self, monkeypatch):
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")
        monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)
        get_capability_index.cache_clear()

        idx = get_capability_index()
        assert "ai.llm.router.chat" in idx.by_id
        assert "code_agent" not in idx.by_id

        llm_tools = search_by_capability("llm_chat")
        assert any(t.id == "ai.llm.router.chat" for t in llm_tools)

        coding_tools = search_by_capability("coding_agent")
        assert not any(t.id == "code_agent" for t in coding_tools)

        general_tools = search_by_modality("general")
        general_ids = {t.id for t in general_tools}
        assert "ai.llm.router.chat" in general_ids

        ai_tools = search_by_package("ai")
        ai_ids = {t.id for t in ai_tools}
        assert "ai.llm.router.chat" in ai_ids

    def test_coding_executor_requires_remote_tool_opt_in(self, monkeypatch):
        monkeypatch.setenv("BR_PLANNER_SOURCE", "catalog")
        monkeypatch.setenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", "1")
        get_capability_index.cache_clear()

        idx = get_capability_index()
        assert "code_agent" in idx.by_id

        coding_tools = search_by_capability("coding_agent")
        assert any(t.id == "code_agent" for t in coding_tools)
