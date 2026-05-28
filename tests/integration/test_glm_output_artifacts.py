import json
from pathlib import Path

import pandas as pd

from brain_researcher.services.tools.fmri_tools import GLMAnalysisTool


def _write_minimal_spec(spec_path: Path, task: str) -> None:
    spec = {
        "Name": "unit-test",
        "BIDSModelVersion": "1.0.0",
        "Input": {"task": [task]},
        "Nodes": [
            {
                "Level": "run",
                "Model": {"X": ["cond"]},
                "Transformations": {"Instructions": []},
            }
        ],
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")


def test_glm_outputs_populated_from_existing_outputs(tmp_path):
    dataset_id = "ds000001"
    task = "motor"

    glm_repo = tmp_path / "glmrepo"
    datasets_folder = tmp_path / "datasets"
    tmp_folder = tmp_path / "scratch"
    glm_repo.mkdir()
    datasets_folder.mkdir()
    tmp_folder.mkdir()

    spec_dir = glm_repo / "statsmodel_specs" / dataset_id
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / f"{dataset_id}-{task}_specs.json"
    _write_minimal_spec(spec_path, task)

    path_config = tmp_path / "path_config.json"
    path_config.write_text(
        json.dumps(
            {
                "datasets_folder": str(datasets_folder),
                "openneuro_glmrepo": str(glm_repo),
                "tmp_folder": str(tmp_folder),
            }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    # Dummy stat maps (content not parsed; existence triggers collection)
    (output_dir / "sub-01_contrast-test_stat-z_statmap.nii.gz").write_bytes(b"")
    (output_dir / "sub-01_contrast-test_stat-t_statmap.nii.gz").write_bytes(b"")
    (output_dir / "sub-01_contrast-test_stat-beta_statmap.nii.gz").write_bytes(b"")

    # Design matrix + residuals
    design_df = pd.DataFrame({"cond": [1, 0, 1], "intercept": [1, 1, 1]})
    design_df.to_csv(output_dir / "design_matrix.tsv", sep="\t", index=False)
    (output_dir / "residuals.csv").write_text("residual\n0.1\n-0.2\n0.05\n", encoding="utf-8")

    # ROI mask placeholder (effect-size code will handle missing/invalid data)
    roi_mask = output_dir / "roi_mask.nii.gz"
    roi_mask.write_bytes(b"")

    tool = GLMAnalysisTool()
    result = tool._run(
        dataset_id=dataset_id,
        contrasts={"test": [1]},
        task=task,
        execute=False,
        parse_only=True,
        path_config=str(path_config),
        output_dir=str(output_dir),
        roi_masks={"roi": str(roi_mask)},
    )

    assert result.status == "success"
    data = result.data
    assert data.get("design_matrix") is not None
    assert data.get("residuals") is not None
    effects = data.get("effects", {})
    assert effects.get("roi_summary"), "ROI summary should be populated"
    assert "test" in data.get("beta_maps", {})
    outputs = data.get("outputs", {})
    assert outputs.get("z_maps")
    assert outputs.get("roi_summary_csv")
