from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.virtual_brain.api import create_app


@pytest.fixture()
def api_client(tmp_path: Path) -> TestClient:
    db = FakeGraphDB()

    weights = np.eye(1, dtype=float)
    weights_path = tmp_path / "weights.npy"
    np.save(weights_path, weights)

    fc_path = tmp_path / "fc.npy"
    np.save(fc_path, np.ones((1, 1), dtype=float))

    db.create_node(
        "SCMatrix",
        {
            "id": "sc:demo",
            "weights_uri": str(weights_path),
            "parcellation": "schaefer100",
            "regions": ["region:0"],
        },
    )
    db.create_node(
        "TargetFC",
        {
            "id": "fc:demo",
            "uri": str(fc_path),
            "parcellation": "schaefer100",
        },
    )
    db.create_node("Task", {"id": "task:simple", "name": "Simple Task"})
    db.create_node("Region", {"id": "region:0", "parcellation": "schaefer100"})
    db.create_relationship(
        "task:simple",
        "region:0",
        "ACTIVATES",
        {"strength": 1.0, "source": "unit-test"},
    )

    config = {
        "parcellation": "schaefer100",
        "sc_matrix_id": "sc:demo",
        "target_fc_id": "fc:demo",
        "cache_dir": str(tmp_path / "cache"),
    }

    app = create_app(config, db=db)
    client = TestClient(app)
    return client


def test_suggest_params_endpoint(api_client: TestClient) -> None:
    response = api_client.post(
        "/vb/suggest_params",
        json={"task_id": "task:simple", "parcellation": "schaefer100"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parcellation"] == "schaefer100"
    assert payload["priors"]


def test_simulate_endpoint(api_client: TestClient) -> None:
    response = api_client.post(
        "/vb/simulate",
        json={
            "task_id": "task:simple",
            "parcellation": "schaefer100",
            "duration": 0.5,
            "dt": 0.01,
            "persist": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["bold_mean"] is not None
