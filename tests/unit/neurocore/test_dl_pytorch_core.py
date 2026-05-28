from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    DLPyTorchParameters,
    run_dl_pytorch,
)


def test_run_dl_pytorch(tmp_path):
    data = np.random.randn(5, 4)
    data_file = tmp_path / "data.npy"
    np.save(data_file, data)

    params = DLPyTorchParameters(
        data_file=str(data_file),
        output_dir=str(tmp_path / "out"),
        model_type="3dcnn",
        task="classification",
        n_classes=2,
        mode="train",
        epochs=2,
        batch_size=2,
        learning_rate=0.001,
        use_pretrained=False,
        seed=42,
        labels_file=None,
        save_model=True,
        save_predictions=True,
        save_features=False,
    )

    result = run_dl_pytorch(params)
    assert "metrics" in result
