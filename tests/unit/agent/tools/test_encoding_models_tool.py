from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.encoding_models_tool import EncodingModelsTool


def test_agent_encoding_models(tmp_path):
    tool = EncodingModelsTool()
    rng = np.random.default_rng(0)
    brain = rng.normal(size=(25, 4))
    stimulus = rng.normal(size=(25, 5))
    brain_file = tmp_path / "brain.npy"
    stim_file = tmp_path / "stim.npy"
    np.save(brain_file, brain)
    np.save(stim_file, stimulus)

    result = tool._run(
        brain_data_file=str(brain_file),
        stimulus_file=str(stim_file),
        output_dir=str(tmp_path / "encoding"),
        model_type="ridge",
    )

    assert result.status == "success"
    assert result.data["summary"]["used_full_backend"] is True
    assert result.data["summary"]["backend_name"] == "numpy_solve"
