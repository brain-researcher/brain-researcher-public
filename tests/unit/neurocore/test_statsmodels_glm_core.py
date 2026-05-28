from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    StatsmodelsGLMParameters,
    run_statsmodels_glm,
)


def test_run_statsmodels_glm(tmp_path):
    data_path = tmp_path / "data.csv"
    design_path = tmp_path / "design.csv"
    data_path.write_text("y,x1\n1,0\n2,1\n", encoding="utf-8")
    design_path.write_text("y,x1\n1,0\n2,1\n", encoding="utf-8")

    params = StatsmodelsGLMParameters(
        data_file=str(data_path),
        design_matrix=str(design_path),
        output_dir=str(tmp_path / "out"),
        dependent_var="y",
    )
    result = run_statsmodels_glm(params)
    outputs = result["outputs"]
    assert Path(outputs["summary"]).exists()
    assert Path(outputs["residuals"]).exists()
    assert Path(outputs["fitted"]).exists()
