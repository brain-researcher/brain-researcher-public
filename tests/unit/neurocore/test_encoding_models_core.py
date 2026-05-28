from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    EncodingModelParameters,
    run_encoding_model,
)
from brain_researcher.services.tools.params import encoding_models as encoding_models_module


def test_run_encoding_model_marks_full_backend_on_success(tmp_path):
    rng = np.random.default_rng(0)
    brain = rng.normal(size=(50, 4))
    stimulus = rng.normal(size=(50, 6))
    brain_file = tmp_path / "brain.npy"
    stim_file = tmp_path / "stim.npy"
    np.save(brain_file, brain)
    np.save(stim_file, stimulus)

    params = EncodingModelParameters(
        brain_data_file=str(brain_file),
        stimulus_file=str(stim_file),
        output_dir=str(tmp_path / "encoding"),
        model_type="ridge",
        n_folds=3,
        standardize=True,
        add_derivatives=False,
        random_state=0,
        save_models=True,
        save_predictions=True,
        save_weights=True,
    )

    result = run_encoding_model(params)
    assert "mean_r2" in result["summary"]
    assert result["summary"]["used_full_backend"] is True
    assert result["summary"]["backend_name"] == "numpy_solve"


def test_run_encoding_model_marks_fallback_when_solve_fails(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    brain = rng.normal(size=(20, 3))
    stimulus = rng.normal(size=(20, 5))
    brain_file = tmp_path / "brain.npy"
    stim_file = tmp_path / "stim.npy"
    np.save(brain_file, brain)
    np.save(stim_file, stimulus)

    params = EncodingModelParameters(
        brain_data_file=str(brain_file),
        stimulus_file=str(stim_file),
        output_dir=str(tmp_path / "encoding"),
        model_type="ridge",
        n_folds=3,
        standardize=True,
        add_derivatives=False,
        random_state=0,
        save_models=False,
        save_predictions=False,
        save_weights=False,
    )

    def _raise_solve(*args, **kwargs):
        raise np.linalg.LinAlgError("forced failure")

    monkeypatch.setattr(encoding_models_module.np.linalg, "solve", _raise_solve)

    result = run_encoding_model(params)
    assert result["summary"]["used_full_backend"] is False
    assert result["summary"]["backend_name"] == "numpy_fallback"
