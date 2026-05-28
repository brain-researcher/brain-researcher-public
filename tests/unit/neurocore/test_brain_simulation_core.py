from __future__ import annotations

from brain_researcher.services.tools.params import (
    BrainSimulationParameters,
    run_brain_simulation,
)


def test_run_brain_simulation(tmp_path):
    params = BrainSimulationParameters(
        model_type="neural_mass",
        duration=1.0,
        dt=0.01,
        noise_level=0.0,
        connectivity_strength=1.0,
        seed=42,
        output_dir=str(tmp_path / "sim"),
    )
    result = run_brain_simulation(params)
    assert "outputs" in result
