"""Track A P0a: cheap, dependency-free liveness/readiness probes.

The deployed orchestrator is intentionally single-replica (SQLite + in-process
locks). Pointing k8s liveness at the deep `/health` endpoint (which fans out
httpx to agent+br_kg) risks restarting the only pod on a slow dependency or a
momentarily busy event loop. `/livez` must be a constant 200; `/readyz` gates
on startup completion only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.app_factory import create_app


@pytest.fixture(autouse=True)
def _disable_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    # create_app registers prometheus collectors in the global registry; disable
    # metrics so building the app per-test doesn't raise "Duplicated timeseries".
    monkeypatch.setenv("BR_METRICS_ENABLED", "false")


def _app():
    return create_app(
        title="probe-test",
        description="probe-test",
        version="0",
        allowed_origins=["*"],
    )


def test_livez_is_constant_200_without_startup_or_dependencies():
    app = _app()
    # No lifespan, no studio runtime, no agent/br_kg reachable: /livez must still
    # answer a fast constant 200 (it does no awaits and no downstream calls).
    with TestClient(app) as client:
        resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_readyz_is_503_before_ready_then_200():
    app = _app()
    # create_app initializes app.state.ready = False; lifespan flips it True.
    with TestClient(app) as client:
        before = client.get("/readyz")
        assert before.status_code == 503

        app.state.ready = True
        after = client.get("/readyz")
        assert after.status_code == 200
        assert after.json() == {"status": "ready"}
