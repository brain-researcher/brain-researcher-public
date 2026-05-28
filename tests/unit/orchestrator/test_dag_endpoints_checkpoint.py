import json
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import dag_endpoints
from brain_researcher.services.agent.dag_executor import DAGExecution, ExecutionStatus, NodeExecution
from brain_researcher.services.agent.dag_language import DAGDefinition, DAGNode, NodeType


def setup_mock_execution(exec_id: str):
    dag = DAGDefinition(name="demo")
    dag.add_node(DAGNode(id="n1", type=NodeType.TOOL, tool="t1"))

    execution = DAGExecution(
        execution_id=exec_id,
        dag=dag,
        status=ExecutionStatus.SUCCESS,
        start_time=datetime.now() - timedelta(seconds=5),
        end_time=datetime.now(),
        global_context={},
    )
    execution.node_executions["n1"] = NodeExecution(
        node_id="n1", status=ExecutionStatus.SUCCESS, start_time=datetime.now(), end_time=datetime.now()
    )
    execution.completed_nodes.add("n1")
    execution.last_checkpoint_id = "ckpt-test"
    dag_endpoints.dag_executor.active_executions[exec_id] = execution


def test_status_returns_checkpoint_id():
    app = FastAPI()
    app.include_router(dag_endpoints.router)
    client = TestClient(app)

    exec_id = "exec-123"
    setup_mock_execution(exec_id)

    resp = client.get(f"/api/dag/status/{exec_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == exec_id
    assert data["checkpoint_id"] == "ckpt-test"
    assert "last_checkpoint_id" not in data


def test_execute_normalizes_legacy_resume_checkpoint_id():
    app = FastAPI()
    app.include_router(dag_endpoints.router)
    client = TestClient(app)

    dag_def = {
        "name": "demo",
        "nodes": {"n1": {"id": "n1", "type": "tool", "tool": "noop"}},
        "edges": [],
    }
    payload = {
        "dag_definition": json.dumps(dag_def),
        "resume_checkpoint_id": "ckpt-prev",
    }
    resp = client.post("/api/dag/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("checkpoint_id") == "ckpt-prev"
    assert "resume_checkpoint_id" not in data


def test_execute_accepts_canonical_checkpoint_id():
    app = FastAPI()
    app.include_router(dag_endpoints.router)
    client = TestClient(app)

    dag_def = {
        "name": "demo",
        "nodes": {"n1": {"id": "n1", "type": "tool", "tool": "noop"}},
        "edges": [],
    }
    payload = {
        "dag_definition": json.dumps(dag_def),
        "checkpoint_id": "ckpt-canonical",
    }
    resp = client.post("/api/dag/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("checkpoint_id") == "ckpt-canonical"
