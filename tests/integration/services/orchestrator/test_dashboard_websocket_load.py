from __future__ import annotations

import time
from contextlib import ExitStack
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import websocket_endpoints
from brain_researcher.services.orchestrator.dashboard_endpoints import (
    DashboardMetricsResponse,
    JobMetricsModel,
    QueueStatusModel,
    ResourceMetricsModel,
    StorageMetricsModel,
)
from brain_researcher.services.orchestrator.websocket_manager import WebSocketPool


@pytest.fixture
def dashboard_ws_client(monkeypatch) -> TestClient:
    """Spin up a lightweight app serving the dashboard WebSocket endpoint."""

    # Use a fresh pool for each test to avoid cross-test leakage.
    test_pool = WebSocketPool()
    monkeypatch.setattr(websocket_endpoints, 'websocket_pool', test_pool)

    async def fake_metrics_response() -> DashboardMetricsResponse:
        queue = QueueStatusModel(running=1, queued=2, completed=3, failed=0)
        job_metrics = JobMetricsModel(queue=queue, queueSource='job_store')
        resource_metrics = ResourceMetricsModel(gpuSamples=[], cluster=None)
        storage_metrics = StorageMetricsModel()
        return DashboardMetricsResponse(
            timestamp=datetime.utcnow(),
            jobMetrics=job_metrics,
            resourceMetrics=resource_metrics,
            projects=[],
            activity=[],
            storageMetrics=storage_metrics,
            outputs=[],
            metadata={'status': 'healthy', 'source': 'test'},
        )

    monkeypatch.setattr(
        websocket_endpoints,
        'build_dashboard_metrics_response',
        fake_metrics_response,
    )

    # Speed up the broadcast loop so the test doesn't wait 3s between updates.
    monkeypatch.setattr(websocket_endpoints, 'DASHBOARD_WS_INTERVAL_SECONDS', 0.05)

    app = FastAPI()
    app.include_router(websocket_endpoints.router)

    with TestClient(app) as client:
        yield client


def _receive_snapshot(ws) -> dict:
    while True:
        message = ws.receive_json()
        if message.get('type') != 'data':
            continue
        if message.get('channel') != 'dashboard':
            continue
        if message.get('data', {}).get('type') != 'snapshot':
            continue
        return message


def test_dashboard_websocket_handles_many_clients(dashboard_ws_client: TestClient):
    """Ensure the dashboard WebSocket remains stable with 20 concurrent listeners."""

    target_clients = 20

    with ExitStack() as stack:
        sessions = [
            stack.enter_context(dashboard_ws_client.websocket_connect('/ws/dashboard'))
            for _ in range(target_clients)
        ]
        for ws in sessions:
            _receive_snapshot(ws)

        # Allow the periodic broadcast loop to run at least once.
        time.sleep(0.2)
        follow_up = sessions[0].receive_json()
        assert follow_up['type'] == 'data'
        assert follow_up['data']['type'] == 'snapshot'
