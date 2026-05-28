from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.services.tools.grandmaster_tools import HarmonizeDataTool


def test_harmonize_data_tool_writes_report_and_provenance(tmp_path: Path):
    features = pd.DataFrame(
        {
            "sample_id": ["s1", "s2", "s3", "s4"],
            "f1": [1.0, 1.5, 5.0, 5.5],
            "f2": [2.0, 2.5, 6.0, 6.5],
        }
    )
    features_path = tmp_path / "features.csv"
    covars_path = tmp_path / "covars.csv"
    features.to_csv(features_path, index=False)
    pd.DataFrame({"age": [10, 11, 10, 11]}).to_csv(covars_path, index=False)

    tool = HarmonizeDataTool()
    result = tool._run(
        features=str(features_path),
        batch=[0, 0, 1, 1],
        covars=str(covars_path),
        output_file=str(tmp_path / "harmonized.csv"),
        report_file=str(tmp_path / "harmonization_report.json"),
        provenance_file=str(tmp_path / "provenance.json"),
        method="combat",
    )

    assert result.status == "success", result.error
    outputs = result.data["outputs"]
    assert Path(outputs["harmonized_file"]).exists()
    assert Path(outputs["report_json"]).exists()
    assert Path(outputs["provenance_json"]).exists()

    report = json.loads(Path(outputs["report_json"]).read_text(encoding="utf-8"))
    assert report["method"] == "combat"
    assert report["n_batches"] == 2

    provenance = json.loads(
        Path(outputs["provenance_json"]).read_text(encoding="utf-8")
    )
    assert provenance["tool"] == "harmonize_data"
    assert provenance["outputs"]["harmonized_file"] == outputs["harmonized_file"]


def test_harmonize_data_tool_external_backend_requires_entrypoint(tmp_path: Path):
    features_path = tmp_path / "features.npy"
    np.save(features_path, np.random.default_rng(0).normal(size=(4, 3)))

    tool = HarmonizeDataTool()
    result = tool._run(
        features=str(features_path),
        batch=[0, 0, 1, 1],
        output_file=str(tmp_path / "harmonized.csv"),
        method="deepresbat_external",
    )

    assert result.status == "error"
    assert "BR_DEEPRESBAT_ENTRYPOINT" in (result.error or "")
