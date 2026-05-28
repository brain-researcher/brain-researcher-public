from __future__ import annotations

import numpy as np
import tempfile
from pathlib import Path

from brain_researcher.services.tools.dl_pytorch_tool import PyTorchDeepLearningTool


def test_dl_pytorch_tool_basic(tmp_path):
    tool = PyTorchDeepLearningTool()
    assert tool.get_tool_name() == "dl_pytorch"

    data = np.random.randn(8, 10)
    data_file = tmp_path / "data.npy"
    np.save(data_file, data)

    result = tool._run(
        data_file=str(data_file),
        output_dir=str(tmp_path / "out"),
        model_type="3dcnn",
        task="classification",
        epochs=1,
        batch_size=2,
        learning_rate=0.001,
        save_model=True,
        save_predictions=True,
        verbose=False,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["summary"]).exists()
    assert Path(outputs["model"]).exists()
    assert Path(outputs["predictions"]).exists()
