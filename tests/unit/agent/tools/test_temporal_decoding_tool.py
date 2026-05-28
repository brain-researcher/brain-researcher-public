from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.temporal_decoding_tool import TemporalDecodingTool


def test_agent_temporal_decoding(tmp_path):
    tool = TemporalDecodingTool()
    rng = np.random.default_rng(0)
    labels = np.array([0] * 10 + [1] * 10, dtype=int)
    data = np.vstack(
        [
            -1.5 + rng.normal(scale=0.1, size=(10, 5)),
            1.5 + rng.normal(scale=0.1, size=(10, 5)),
        ]
    )
    data_file = tmp_path / "data.npy"
    labels_file = tmp_path / "labels.npy"
    np.save(data_file, data)
    np.save(labels_file, labels)

    result = tool._run(
        data_file=str(data_file),
        labels_file=str(labels_file),
        output_dir=str(tmp_path / "decoding"),
        window_size=6,
    )

    assert result.status == "success"
    assert 0.0 <= result.data["summary"]["mean_accuracy"] <= 1.0
    assert result.data["summary"]["backend_name"] in {
        "sklearn_cv",
        "numpy_nearest_centroid_cv",
    }
