import json
import logging
import os
import time

from brain_researcher.services.agent.plan_memory import PlanMemory
from brain_researcher.services.agent import web_service
from brain_researcher.services.agent.error_taxonomy import (
    ErrorTaxonomyCategory,
    ErrorTaxonomyResult,
    RecoveryAction,
)
from brain_researcher.services.agent.planner import failure_neo4j
from brain_researcher.services.agent.planner.models import Plan, PlanDAG, StepSpec
from brain_researcher.services.tools.demo_passthrough_tool import DemoPassthroughTool


class DummyFailureWriter:
    def __init__(self, sink):
        self.sink = sink

    def write(self, records):
        self.sink.extend(records)


class SlowFailureWriter:
    def __init__(self, delay_s):
        self.delay_s = delay_s

    def write(self, records):
        time.sleep(self.delay_s)


class DummyToolRegistry:
    def __init__(self, tool):
        self._tool = tool

    def get_tool(self, tool_id):
        if tool_id == self._tool.get_tool_name():
            return self._tool
        return None


class DummyAgent:
    def __init__(self, tool):
        self.tool_registry = DummyToolRegistry(tool)


def _reset_agent_state():
    web_service._agent = None
    web_service._plan_memory = None
    web_service._recovery_router = None
    web_service._PLAN_CACHE.clear()

def _reset_failure_warn_state():
    web_service._failure_write_warned["plan_memory"].clear()
    web_service._failure_write_warned["kg"].clear()

def _reset_metric(name):
    metric = web_service._metrics.metrics.get(name)
    if metric:
        metric.data_points.clear()

def _metric_value(name):
    metric = web_service._metrics.metrics.get(name)
    if not metric:
        return 0
    latest = metric.get_latest()
    return latest or 0


def _plan(client, *, plan_payload):
    plan_resp = client.post("/agent/plan", json=plan_payload)
    assert plan_resp.status_code == 200
    plan_data = plan_resp.get_json()
    assert plan_data and plan_data.get("plan_id")
    assert plan_data.get("por_token")
    return plan_data


def _run_plan(client, *, plan_data):
    run_resp = client.post(
        "/agent/run_plan?stream=1",
        json={
            "plan_id": plan_data["plan_id"],
            "version": plan_data.get("version", 1),
            "por_token": plan_data["por_token"],
        },
        headers={"Accept": "text/event-stream"},
    )
    payload = b"".join(run_resp.response)
    return payload


def _plan_and_run(client, *, plan_payload):
    plan_data = _plan(client, plan_payload=plan_payload)
    payload = _run_plan(client, plan_data=plan_data)
    return plan_data, payload


def test_plan_failure_writeback_to_memory_and_kg(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "true")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "true")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    # Reset cached globals to respect env in this test.
    _reset_agent_state()

    captured = []
    monkeypatch.setattr(
        failure_neo4j,
        "get_default_failure_writer",
        lambda: DummyFailureWriter(captured),
    )

    client = web_service.app.test_client()
    plan_payload, payload = _plan_and_run(
        client,
        plan_payload={
            "pipeline": "connectivity",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert b"step_failed" in payload

    plan_memory = PlanMemory(db_path=str(db_path))
    failures = plan_memory.list_failures(plan_id=plan_payload["plan_id"])
    assert failures, "Failure should be recorded in PlanMemory"
    assert failures[0].plan_id == plan_payload["plan_id"]

    assert captured, "KG writeback should be invoked"
    assert captured[0].plan_id == plan_payload["plan_id"]


def test_plan_failure_writeback_memory_only(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "true")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "false")
    monkeypatch.setenv("BR_KG_WRITEBACK", "false")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    captured = []
    monkeypatch.setattr(
        failure_neo4j,
        "get_default_failure_writer",
        lambda: DummyFailureWriter(captured),
    )

    client = web_service.app.test_client()
    plan_payload, payload = _plan_and_run(
        client,
        plan_payload={
            "pipeline": "connectivity",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert b"step_failed" in payload

    plan_memory = PlanMemory(db_path=str(db_path))
    failures = plan_memory.list_failures(plan_id=plan_payload["plan_id"])
    assert failures, "Failure should be recorded in PlanMemory"
    assert not captured, "KG writeback should be disabled"


def test_plan_failure_writeback_kg_only(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "false")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "true")
    monkeypatch.setenv("BR_KG_WRITEBACK", "false")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    captured = []
    monkeypatch.setattr(
        failure_neo4j,
        "get_default_failure_writer",
        lambda: DummyFailureWriter(captured),
    )

    client = web_service.app.test_client()
    plan_payload, payload = _plan_and_run(
        client,
        plan_payload={
            "pipeline": "connectivity",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert b"step_failed" in payload

    plan_memory = PlanMemory(db_path=str(db_path))
    failures = plan_memory.list_failures(plan_id=plan_payload["plan_id"])
    assert not failures, "PlanMemory should not log failures when disabled"
    assert captured, "KG writeback should be invoked"
    assert captured[0].plan_id == plan_payload["plan_id"]


def test_plan_success_does_not_log_failures(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "true")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "true")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    captured = []
    monkeypatch.setattr(
        failure_neo4j,
        "get_default_failure_writer",
        lambda: DummyFailureWriter(captured),
    )
    monkeypatch.setattr(
        web_service,
        "get_tool_by_id",
        lambda tool_id: {"id": tool_id} if tool_id == "demo_passthrough" else None,
    )
    web_service._agent = DummyAgent(DemoPassthroughTool())

    client = web_service.app.test_client()
    plan_payload, payload = _plan_and_run(
        client,
        plan_payload={
            "pipeline": "demo_stub",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {"message": "ok"},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert b"step_failed" not in payload

    plan_memory = PlanMemory(db_path=str(db_path))
    failures = plan_memory.list_failures(plan_id=plan_payload["plan_id"])
    assert not failures, "No failure records should be written for successful runs"
    assert not captured, "KG writeback should not be invoked on success"


def test_plan_memory_unavailable_metrics_and_warn_once(monkeypatch, caplog):
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "true")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "false")
    monkeypatch.setenv("BR_KG_WRITEBACK", "false")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()
    _reset_failure_warn_state()
    _reset_metric("plan_memory_failure_write_errors_total")

    monkeypatch.setattr(web_service, "_get_plan_memory", lambda: None)

    client = web_service.app.test_client()
    plan_data = _plan(
        client,
        plan_payload={
            "pipeline": "connectivity",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )

    caplog.set_level(logging.WARNING, logger=web_service.logger.name)
    before = _metric_value("plan_memory_failure_write_errors_total")
    payload = _run_plan(client, plan_data=plan_data)
    assert b"step_failed" in payload
    after = _metric_value("plan_memory_failure_write_errors_total")
    assert after > before

    warn_msg = (
        "PlanMemory unavailable; failure record not persisted for plan "
        f"{plan_data['plan_id']}."
    )
    warnings = [rec for rec in caplog.records if warn_msg in rec.getMessage()]
    assert len(warnings) == 1

    caplog.clear()
    payload = _run_plan(client, plan_data=plan_data)
    assert b"step_failed" in payload
    warnings = [rec for rec in caplog.records if warn_msg in rec.getMessage()]
    assert len(warnings) == 0
    assert _metric_value("plan_memory_failure_write_errors_total") >= after


def test_kg_write_timeout_metrics_and_warn_once(monkeypatch, caplog):
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "false")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "true")
    monkeypatch.setenv("BR_KG_WRITEBACK", "false")
    monkeypatch.setenv("BR_KG_FAILURE_WRITE_TIMEOUT_S", "0.1")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()
    _reset_failure_warn_state()
    _reset_metric("kg_failure_write_errors_total")

    monkeypatch.setattr(
        failure_neo4j,
        "get_default_failure_writer",
        lambda: SlowFailureWriter(0.25),
    )

    client = web_service.app.test_client()
    plan_data = _plan(
        client,
        plan_payload={
            "pipeline": "connectivity",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )

    caplog.set_level(logging.WARNING, logger=web_service.logger.name)
    before = _metric_value("kg_failure_write_errors_total")
    payload = _run_plan(client, plan_data=plan_data)
    assert b"step_failed" in payload
    after = _metric_value("kg_failure_write_errors_total")
    assert after > before

    warn_prefix = "KG failure writeback timed out after"
    warnings = [
        rec
        for rec in caplog.records
        if warn_prefix in rec.getMessage()
        and plan_data["plan_id"] in rec.getMessage()
    ]
    assert len(warnings) == 1

    caplog.clear()
    payload = _run_plan(client, plan_data=plan_data)
    assert b"step_failed" in payload
    warnings = [
        rec
        for rec in caplog.records
        if warn_prefix in rec.getMessage()
        and plan_data["plan_id"] in rec.getMessage()
    ]
    assert len(warnings) == 0
    assert _metric_value("kg_failure_write_errors_total") >= after


def test_recovery_map_container_family_match(monkeypatch):
    monkeypatch.setenv("BR_PLAN_MEMORY_LOG_FAILURES", "false")
    monkeypatch.setenv("BR_KG_FAILURE_WRITEBACK", "false")
    monkeypatch.setenv("BR_KG_WRITEBACK", "false")
    monkeypatch.setenv("BR_RECOVERY_PARAM_RETRY", "true")
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    def fake_classify_failure(status, error_message):
        return ErrorTaxonomyResult(
            category=ErrorTaxonomyCategory.INFRA,
            is_retryable=True,
            recovery_action=RecoveryAction.RETRY_BACKOFF,
        )

    monkeypatch.setattr(
        "brain_researcher.services.agent.error_taxonomy.classify_failure",
        fake_classify_failure,
    )
    monkeypatch.setattr(web_service, "get_tool_by_id", lambda tool_id: {"id": tool_id})

    web_service._agent = DummyAgent(DemoPassthroughTool())

    plan = Plan(
        plan_id="plan_container_recovery",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(
            steps=[
                StepSpec(
                    id="step_1",
                    tool="container.bidsapp.fmriprep.run",
                    params={"n_jobs": 2},
                    metadata={"fallback_tools": ["demo_passthrough"]},
                )
            ]
        ),
    )
    web_service._register_plan(plan)

    client = web_service.app.test_client()
    payload = _run_plan(
        client,
        plan_data={
            "plan_id": plan.plan_id,
            "version": plan.version,
            "por_token": plan.por_token,
        },
    )

    assert b"substitute tool after failure" in payload
    assert b"param_adjustment_retry" not in payload


def test_plan_memory_persists_tool_family(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    def _fake_build_plan(plan_request):
        return Plan(
            plan_id="plan_family_persist",
            domain=plan_request.domain,
            modality=plan_request.modality,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="step_container",
                        tool="container.bidsapp.fmriprep.run",
                        params={},
                    )
                ]
            ),
        )

    monkeypatch.setattr(web_service, "_build_plan_for_request", _fake_build_plan)

    client = web_service.app.test_client()
    resp = client.post(
        "/agent/plan",
        json={
            "pipeline": "container_stub",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert resp.status_code == 200
    plan_data = resp.get_json()
    assert plan_data and plan_data.get("plan_id")

    plan_memory = PlanMemory(db_path=str(db_path))
    record = plan_memory.get_plan(plan_data["plan_id"])
    assert record is not None

    stored = json.loads(record.plan_json)
    steps = []
    dag = stored.get("dag") if isinstance(stored, dict) else None
    if isinstance(dag, dict) and isinstance(dag.get("steps"), list):
        steps = dag.get("steps")
    if not steps and isinstance(stored.get("steps"), list):
        steps = stored.get("steps")
    assert steps, "Plan JSON should contain steps"

    step_meta = steps[0].get("metadata") or {}
    assert step_meta.get("tool_family") == "container"


def test_plan_memory_persists_download_family(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_memory.db"
    monkeypatch.setenv("BR_PLAN_MEMORY_DB", str(db_path))
    monkeypatch.setenv("DISABLE_TOOL_DISCOVERY", "1")

    _reset_agent_state()

    def _fake_build_plan(plan_request):
        return Plan(
            plan_id="plan_download_family_persist",
            domain=plan_request.domain,
            modality=plan_request.modality,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="step_download",
                        tool="openneuro_download",
                        params={},
                    )
                ]
            ),
        )

    monkeypatch.setattr(web_service, "_build_plan_for_request", _fake_build_plan)

    client = web_service.app.test_client()
    resp = client.post(
        "/agent/plan",
        json={
            "pipeline": "download_stub",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "user_id": "user_test",
            "workspace_id": "ws_test",
        },
    )
    assert resp.status_code == 200
    plan_data = resp.get_json()
    assert plan_data and plan_data.get("plan_id")

    plan_memory = PlanMemory(db_path=str(db_path))
    record = plan_memory.get_plan(plan_data["plan_id"])
    assert record is not None

    stored = json.loads(record.plan_json)
    steps = []
    dag = stored.get("dag") if isinstance(stored, dict) else None
    if isinstance(dag, dict) and isinstance(dag.get("steps"), list):
        steps = dag.get("steps")
    if not steps and isinstance(stored.get("steps"), list):
        steps = stored.get("steps")
    assert steps, "Plan JSON should contain steps"

    step_meta = steps[0].get("metadata") or {}
    assert step_meta.get("tool_family") == "download"
