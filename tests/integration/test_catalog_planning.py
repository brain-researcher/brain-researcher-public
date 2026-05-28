"""Integration tests for catalog-driven planning (PR-2).

Tests the end-to-end flow:
1. API request to /api/agent/plan (orchestrator)
2. Proxy to agent service
3. Catalog-only mode selection
4. Synonym matching
5. Catalog search
6. Preflight checks
7. Tool selection and ranking
8. Response formatting
"""

import pytest
import os
from unittest.mock import patch
import json


class TestOrchestratorModeHandling:
    """Test orchestrator's mode parameter handling."""

    @pytest.mark.integration
    def test_invalid_mode_returns_error(self):
        """Test that retired/invalid planner modes return 422 error."""
        from fastapi.testclient import TestClient
        from brain_researcher.services.orchestrator.main_enhanced import app

        client = TestClient(app)

        for mode in ("invalid_mode", "legacy"):
            response = client.post(
                "/api/agent/plan",
                json={
                    "pipeline": "skull strip",
                    "mode": mode,
                },
            )

            assert response.status_code == 422
            data = response.json()
            assert "error" in data["detail"]
            assert "invalid_mode" in data["detail"]["error"]

    @pytest.mark.integration
    def test_mode_validation_in_orchestrator(self):
        """Test that orchestrator validates and defaults mode parameter."""
        from fastapi.testclient import TestClient
        from brain_researcher.services.orchestrator.main_enhanced import app

        client = TestClient(app)

        # Missing mode should still validate even if BR_PLANNER_SOURCE is pinned to legacy.
        # Note: This will fail to connect to agent, but we're just testing mode validation.
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "legacy", "BR_AGENT_URL": "http://nonexistent:9999"}):
            response = client.post(
                "/api/agent/plan",
                json={
                    "pipeline": "skull strip",
                    # mode not specified - should default to catalog
                },
            )
            # Should fail at agent connection, not at mode validation (502 Bad Gateway)
            assert response.status_code in [200, 502]  # 502 if agent not available


class TestAgentPlannerModeSelection:
    """Test the agent's mode selection logic directly."""

    @pytest.mark.integration
    def test_agent_rejects_legacy_mode(self):
        """Test that agent rejects retired legacy planner mode."""
        from brain_researcher.services.agent.web_service import app

        client = app.test_client()

        response = client.post(
            "/agent/plan",
            data=json.dumps({
                "pipeline": "connectivity",
                "domain": "neuroimaging",
                "modality": ["fmri"],
                "inputs": {},
                "mode": "legacy",
            }),
            content_type='application/json'
        )

        assert response.status_code == 422
        data = json.loads(response.data)
        assert data["error"] == "invalid_mode"

    @pytest.mark.integration
    def test_agent_catalog_mode_uses_catalog_planner(self):
        """Test that agent uses catalog planner when mode=catalog."""
        from brain_researcher.services.agent.web_service import app

        client = app.test_client()

        response = client.post(
            "/agent/plan",
            data=json.dumps({
                "pipeline": "skull strip",
                "domain": "neuroimaging",
                "modality": [],
                "inputs": {},
                "mode": "catalog",
            }),
            content_type='application/json'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["mode"] == "catalog"
        assert "dag" in data
        # Catalog mode may populate selection fields
        # (intent, candidates, chosen_tool, selection_reason)

    @pytest.mark.integration
    def test_agent_defaults_to_catalog_when_mode_omitted(self):
        """Test that agent ignores legacy env override and defaults to catalog."""
        from brain_researcher.services.agent.web_service import app
        from brain_researcher.services.shared.planner.models import Plan, PlanDAG, StepSpec

        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "legacy"}):
            client = app.test_client()
            stub_plan = Plan(
                plan_id="plan-catalog-default",
                domain="neuroimaging",
                modality=["fmri"],
                dag=PlanDAG(
                    steps=[
                        StepSpec(
                            id="001-main",
                            tool="fsl.bet.run",
                            params={},
                            consumes={},
                            produces={},
                        )
                    ],
                    artifacts=[],
                ),
                chosen_tool="fsl.bet.run",
                resolvable=True,
            )

            class _DummyRegistry:
                def get_tool(self, name):  # pragma: no cover - simple test stub
                    return object() if name == "fsl.bet.run" else None

            class _DummyAgent:
                tool_registry = _DummyRegistry()

            with patch(
                "brain_researcher.services.agent.web_service._build_plan_for_request",
                return_value=stub_plan,
            ), patch(
                "brain_researcher.services.agent.web_service.get_agent",
                return_value=_DummyAgent(),
            ), patch(
                "brain_researcher.services.agent.web_service._apply_agent_allowlist",
                return_value=None,
            ), patch(
                "brain_researcher.services.agent.web_service._collect_disallowed_tools_from_plan",
                return_value=[],
            ), patch(
                "brain_researcher.services.agent.preflight.ensure_query_understanding",
                return_value=None,
            ), patch(
                "brain_researcher.services.agent.preflight.ensure_tool_candidates",
                return_value=[],
            ):
                response = client.post(
                    "/agent/plan",
                    data=json.dumps({
                        "pipeline": "connectivity",
                        "domain": "neuroimaging",
                        "modality": ["fmri"],
                        "inputs": {},
                        # mode not specified
                    }),
                    content_type='application/json'
                )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["mode"] == "catalog"

    @pytest.mark.integration
    def test_strict_validation_short_circuit(self):
        """Test that strict validation returns error for unresolvable plan."""
        from brain_researcher.services.agent.web_service import app

        with patch.dict(os.environ, {"BR_STRICT_PLAN_TOOL_VALIDATION": "true"}):
            client = app.test_client()

            # Request a plan that won't resolve
            response = client.post(
                "/agent/plan",
                data=json.dumps({
                    "pipeline": "nonexistent operation xyz123",
                    "domain": "neuroimaging",
                    "modality": [],
                    "inputs": {},
                    "mode": "catalog",
                }),
                content_type='application/json'
            )

            # Should return 422 for unresolvable plan with strict validation
            # (or 200 with resolvable=false if the catalog finds something)
            if response.status_code == 422:
                data = json.loads(response.data)
                assert "error" in data
                assert data["error"] in ["unresolvable_plan", "tools_not_available"]
            else:
                # If it found a plan, it should be marked as potentially unresolvable
                assert response.status_code == 200

    @pytest.mark.integration
    def test_catalog_mode_without_strict_validation(self):
        """Test catalog mode without strict validation allows unresolvable plans."""
        from brain_researcher.services.agent.web_service import app

        with patch.dict(os.environ, {"BR_STRICT_PLAN_TOOL_VALIDATION": "false"}):
            client = app.test_client()

            response = client.post(
                "/agent/plan",
                data=json.dumps({
                    "pipeline": "nonexistent operation xyz123",
                    "domain": "neuroimaging",
                    "modality": [],
                    "inputs": {},
                    "mode": "catalog",
                }),
                content_type='application/json'
            )

            # Should return 200 even if plan is unresolvable
            assert response.status_code == 200
            data = json.loads(response.data)
            assert "plan_id" in data
            assert "dag" in data


class TestRealCatalogSelection:
    """Tests with real catalog selection (no mocks)."""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_real_catalog_skull_strip_selection(self):
        """Test real catalog selection for skull strip query."""
        from brain_researcher.services.agent.planner import select_tools

        # Run real selection
        candidates = select_tools(
            query="skull strip the T1 image",
            max_results=5,
            require_preflight_pass=False,  # Don't filter by preflight in test
        )

        # Should find some candidates
        assert len(candidates) > 0

        # First candidate should be relevant
        best = candidates[0]
        assert (
            "skull" in best.tool.id.lower()
            or "skull" in best.tool.name.lower()
            or "skull" in best.tool.description.lower()
            or "bet" in best.tool.id.lower()
        )

        # Should have scores
        assert 0.0 <= best.final_score <= 1.0
        assert best.intent_match_score > 0.0

    @pytest.mark.integration
    @pytest.mark.slow
    def test_real_catalog_connectivity_with_modality(self):
        """Test real catalog selection for connectivity with modality filter."""
        from brain_researcher.services.agent.planner import select_tools

        # Run real selection with modality
        candidates = select_tools(
            query="compute functional connectivity",
            modality="fmri",
            max_results=5,
            require_preflight_pass=False,
        )

        # Should find candidates (may be 0 if no fmri tools in catalog)
        if candidates:
            # First candidate should be relevant
            best = candidates[0]
            assert (
                "connect" in best.tool.description.lower()
                or "connect" in best.tool.name.lower()
            )
