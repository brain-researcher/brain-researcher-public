from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.virtual_brain.config import VirtualBrainConfig
from brain_researcher.services.virtual_brain.models import (
    SimulateRequest,
    SuggestParamsRequest,
)
from brain_researcher.services.virtual_brain.simulator import VirtualBrainSimulator


@pytest.fixture()
def demo_db(tmp_path: Path) -> tuple[FakeGraphDB, VirtualBrainConfig]:
    db = FakeGraphDB()

    weights = np.array([[0.0, 0.8], [0.6, 0.0]], dtype=float)
    weights_path = tmp_path / "sc_weights.npy"
    np.save(weights_path, weights)

    delays = np.zeros_like(weights)
    delays_path = tmp_path / "sc_delays.npy"
    np.save(delays_path, delays)

    fc = np.array([[1.0, 0.3], [0.3, 1.0]], dtype=float)
    fc_path = tmp_path / "target_fc.npy"
    np.save(fc_path, fc)

    db.create_node(
        "SCMatrix",
        {
            "id": "sc:schaefer100:demo",
            "weights_uri": str(weights_path),
            "delays_uri": str(delays_path),
            "parcellation": "schaefer100",
            "regions": ["region:0", "region:1"],
        },
    )
    db.create_node(
        "TargetFC",
        {
            "id": "fc:schaefer100:demo",
            "uri": str(fc_path),
            "parcellation": "schaefer100",
        },
    )
    db.create_node(
        "Task",
        {
            "id": "task:n-back",
            "name": "N-Back Working Memory",
        },
    )
    for idx in range(2):
        db.create_node(
            "Region",
            {
                "id": f"region:{idx}",
                "name": f"Region {idx}",
                "parcellation": "schaefer100",
            },
        )

    db.create_relationship(
        "task:n-back",
        "region:0",
        "ACTIVATES",
        {"strength": 0.9, "source": "neurosynth"},
    )
    db.create_relationship(
        "task:n-back",
        "region:1",
        "ACTIVATES",
        {"strength": 0.6, "source": "brainmap"},
    )

    cfg = VirtualBrainConfig(
        parcellation="schaefer100",
        sc_matrix_id="sc:schaefer100:demo",
        target_fc_id="fc:schaefer100:demo",
        cache_dir=tmp_path / "vb_cache",
    )
    return db, cfg


def test_suggest_params_normalizes_strength(
    demo_db: tuple[FakeGraphDB, VirtualBrainConfig],
) -> None:
    db, cfg = demo_db
    simulator = VirtualBrainSimulator(db, cfg, repository_root=Path("."))

    response = simulator.suggest_params(
        SuggestParamsRequest(task_id="task:n-back", parcellation="schaefer100")
    )

    assert len(response.priors) == 2
    assert response.priors[0].weight == pytest.approx(1.0)
    assert response.summary["n_regions"] == 2.0


def test_simulate_persists_results(
    tmp_path: Path, demo_db: tuple[FakeGraphDB, VirtualBrainConfig]
) -> None:
    db, cfg = demo_db
    simulator = VirtualBrainSimulator(db, cfg, repository_root=Path("."))

    result = simulator.simulate(
        SimulateRequest(
            task_id="task:n-back",
            parcellation="schaefer100",
            duration=1.0,
            dt=0.01,
            persist=True,
            include_metrics=True,
            seed=42,
        )
    )

    assert result.persisted is True
    assert result.metrics.bold_mean is not None
    assert result.simulation_id is not None
    report = simulator.report(result.simulation_id)
    assert report.status == "completed"
    assert report.metrics.bold_mean is not None
    assert report.parcellation == "schaefer100"
    assert any(art.uri.endswith("metrics.json") for art in report.artifacts)
