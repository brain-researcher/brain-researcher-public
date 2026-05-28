import importlib
from types import SimpleNamespace

import pytest

from brain_researcher.services.agent.planner.models import ConstraintSpec, PlanRequest
from brain_researcher.services.shared import settings as shared_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    shared_settings.get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    shared_settings.get_settings.cache_clear()  # type: ignore[attr-defined]


def _reload_web_service():
    module = importlib.import_module("brain_researcher.services.agent.web_service")
    importlib.reload(module)
    return module


def test_apply_agent_allowlist_injects_env(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST", "tool.a,tool.b")
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "1")
    monkeypatch.delenv("BR_PLANNER_MODE", raising=False)
    shared_settings.get_settings.cache_clear()  # type: ignore[attr-defined]

    web_service = _reload_web_service()

    request = PlanRequest(
        pipeline="connectivity",
        domain="neuroimaging",
        modality=["fmri"],
        inputs={},
    )

    with web_service.app.app_context():
        response = web_service._apply_agent_allowlist(request)

    assert response is None
    assert request.constraints is not None
    assert "tool.a" in request.constraints.tool_allowlist
    assert "tool.b" in request.constraints.tool_allowlist


def test_collect_disallowed_tools_from_plan_uses_merged_allowlist(monkeypatch):
    web_service = _reload_web_service()
    monkeypatch.setattr(web_service, "_plan_surface_allowset", lambda mode: {"tool.safe"})

    plan = SimpleNamespace(
        dag=SimpleNamespace(
            steps=[
                SimpleNamespace(tool="tool.safe"),
                SimpleNamespace(tool="tool.blocked"),
            ]
        )
    )

    assert web_service._collect_disallowed_tools_from_plan(plan) == ["tool.blocked"]


def test_execute_tool_request_uses_merged_allowlist(monkeypatch):
    web_service = _reload_web_service()
    monkeypatch.setattr(web_service, "_env_tool_allowlist", lambda: ["tool.safe"])
    monkeypatch.setattr(web_service, "_infer_tool_family", lambda tool_id: "unit.family")

    with web_service.app.app_context():
        response, status = web_service._execute_tool_request(
            tool_id="tool.blocked",
            params={},
            work_dir=None,
            output_dir=None,
            preview=False,
        )

    assert status == 403
    data = response.get_json()
    assert data["error"] == "tool_not_allowed"
    assert data["requested_tools"] == ["tool.blocked"]
    assert data["denied_tool_id"] == "tool.blocked"
    assert data["denied_family"] == "unit.family"
    assert data["denial_stage"] == "tool_execute"
    assert data["denial_reason_code"] == "requested_tool_not_permitted"


def test_apply_agent_allowlist_rejects_disallowed_request(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST", "nilearn_connectivity")
    shared_settings.get_settings.cache_clear()  # type: ignore[attr-defined]

    web_service = _reload_web_service()
    monkeypatch.setattr(web_service, "_infer_tool_family", lambda tool_id: "unit.family")

    request = PlanRequest(
        pipeline="connectivity",
        domain="neuroimaging",
        modality=["fmri"],
        inputs={},
        constraints=ConstraintSpec(tool_allowlist=["fsl.bet"]),
    )

    with web_service.app.app_context():
        response = web_service._apply_agent_allowlist(request)

    assert response is not None
    payload, status = response
    assert status == 403
    data = payload.get_json()
    assert data["error"] == "tool_not_allowed"
    assert "fsl.bet" in data["requested_tools"]
    assert data["denied_tool_id"] == "fsl.bet"
    assert data["denied_family"] == "unit.family"
    assert data["denial_stage"] == "request_constraints"
    assert data["denial_reason_code"] == "requested_tools_not_permitted"


def test_apply_agent_allowlist_accepts_equivalent_planner_id(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST", "searchlight_analysis")
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "1")
    shared_settings.get_settings.cache_clear()  # type: ignore[attr-defined]

    web_service = _reload_web_service()

    request = PlanRequest(
        pipeline="searchlight decoding",
        domain="neuroimaging",
        modality=["fmri"],
        inputs={},
        constraints=ConstraintSpec(tool_allowlist=["python.searchlight_fmri.run"]),
    )

    with web_service.app.app_context():
        response = web_service._apply_agent_allowlist(request)

    assert response is None
    assert request.constraints is not None
    assert request.constraints.tool_allowlist == ["searchlight_analysis"]
