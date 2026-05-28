"""Ensure every declarative workflow has at least one smoke test.

These smoke tests are typically marked `realdata` and live under
`tests/integration/realdata/`. This check is data-independent: it only verifies
that each `workflow_*` id in the catalog is referenced by at least one test.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from brain_researcher.services.tools.reference_asset_registry import (
    load_reference_asset_index,
)

_PROMOTED_STABLE_PACKS = {
    "workflow_data_harmonization",
    "workflow_precision_parcellation",
    "workflow_longitudinal_lme",
    "workflow_subtype_discovery",
}

_PROVENANCE_FREE_STABLE_PACKS = {
    "workflow_precision_parcellation",
    "workflow_longitudinal_lme",
    "workflow_subtype_discovery",
}

_EXTERNAL_REPO_CANDIDATE_PACKS = {
    "workflow_fmriprep_preprocessing",
    "workflow_mriqc",
    "workflow_qsiprep",
    "workflow_smriprep",
    "workflow_qsirecon",
    "workflow_fastsurfer",
    "workflow_dwi_connectome",
}

_EXTERNAL_REPO_EXECUTE_GATE_PACKS = {
    "workflow_fmriprep_preprocessing",
    "workflow_mriqc",
    "workflow_qsiprep",
    "workflow_smriprep",
    "workflow_qsirecon",
    "workflow_fastsurfer",
}

_ACTIVE_CONNECTIVITY_WORKFLOWS = {
    "workflow_rest_connectome_e2e": {
        "smoke_test": "tests/integration/realdata/test_workflow_rest_connectome_ds000114_smoke.py",
        "required_outputs": [
            "timeseries/timeseries.npy",
            "timeseries/timeseries.csv",
            "connectivity_matrix.npy",
            "feature_contract.json",
        ],
        "runbook": "docs/runbooks/workflow_rest_connectome_e2e.md",
        "recipe_family": "rest_connectome",
    },
    "workflow_seed_based_connectivity": {
        "smoke_test": "tests/integration/realdata/test_workflow_seed_based_connectivity_ds000114_smoke.py",
        "required_outputs": ["seed_based_fc.nii.gz"],
        "runbook": "docs/runbooks/workflow_seed_based_connectivity.md",
        "recipe_family": "seed_based_connectivity",
    },
    "workflow_network_based_statistics": {
        "smoke_test": "tests/integration/realdata/test_workflow_network_based_statistics_ds000114_smoke.py",
        "required_outputs": [
            "group_connectivity.npy",
            "nbs.npy",
            "nbs.mask.npy",
            "nbs.components.json",
        ],
        "runbook": "docs/runbooks/workflow_network_based_statistics.md",
        "recipe_family": "network_based_statistics",
    },
    "workflow_connectivity_gradients": {
        "smoke_test": "tests/integration/realdata/test_workflow_connectivity_gradients_ds000114_smoke.py",
        "required_outputs": [
            "connectivity.npy",
            "gradients/graph_metrics.json",
            "gradients/graph_summary.json",
        ],
        "runbook": "docs/runbooks/workflow_connectivity_gradients.md",
        "recipe_family": "connectivity_gradients",
    },
    "workflow_group_ica": {
        "smoke_test": "tests/integration/realdata/test_workflow_group_ica_ds000114_smoke.py",
        "required_outputs": [
            "group_ica/canica_components.nii.gz",
            "group_ica/canica_timecourses.npy",
            "group_ica/connectivity.npy",
            "group_ica/nbs.npy",
        ],
        "runbook": "docs/runbooks/workflow_group_ica.md",
        "recipe_family": "group_ica",
    },
}


def _load_workflow_ids(repo_root: Path) -> set[str]:
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    workflows = data.get("workflows") or []
    return {wf["id"] for wf in workflows if "id" in wf}


def _load_workflows(repo_root: Path) -> dict[str, dict]:
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    workflows = data.get("workflows") or []
    return {
        wf["id"]: wf
        for wf in workflows
        if isinstance(wf, dict) and isinstance(wf.get("id"), str)
    }


def _collect_test_references(realdata_tests_dir: Path) -> set[str]:
    refs: set[str] = set()
    pattern = re.compile(r"\bworkflow_[a-zA-Z0-9_]+\b")
    for path in realdata_tests_dir.rglob("test_*.py"):
        text = path.read_text(errors="ignore")
        refs.update(pattern.findall(text))
    return refs


def test_workflow_catalog_has_smoke_test():
    repo_root = Path(__file__).resolve().parents[3]
    wf_ids = _load_workflow_ids(repo_root)

    realdata_tests_dir = repo_root / "tests" / "integration" / "realdata"
    if not realdata_tests_dir.exists():
        raise AssertionError(f"Missing directory: {realdata_tests_dir}")

    covered = _collect_test_references(realdata_tests_dir)
    missing = sorted(wf_ids - covered)
    assert not missing, f"Workflows missing smoke tests: {missing}"


def test_promoted_stable_workflow_packs_have_required_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)
    assets = load_reference_asset_index()

    missing = sorted(_PROMOTED_STABLE_PACKS - set(workflows))
    assert not missing, f"Promoted stable packs missing from catalog: {missing}"

    for workflow_id in sorted(_PROMOTED_STABLE_PACKS):
        wf = workflows[workflow_id]
        assert wf.get("stable_workflow_pack") is True
        assert wf.get("lifecycle") == "stable_pack"
        if workflow_id in _PROVENANCE_FREE_STABLE_PACKS:
            assert "source_repo" not in wf
            assert "source_paper" not in wf
            assert "tested_release" not in wf
        else:
            assert wf.get("source_repo")
            assert wf.get("source_paper")
            assert wf.get("tested_release")
        assert wf.get("runbook")

        runbook = repo_root / str(wf["runbook"])
        assert runbook.exists(), f"{workflow_id} runbook missing: {runbook}"

        example_dataset = wf.get("example_dataset") or {}
        assert example_dataset.get("dataset_id")
        smoke_test = example_dataset.get("smoke_test")
        assert smoke_test, f"{workflow_id} missing example smoke_test"
        assert (
            repo_root / smoke_test
        ).exists(), f"{workflow_id} smoke test missing: {smoke_test}"

        acceptance_gate = wf.get("acceptance_gate") or {}
        gate_script = acceptance_gate.get("script")
        gate_smoke = acceptance_gate.get("smoke_test")
        assert gate_script and (repo_root / gate_script).exists()
        assert gate_smoke and (repo_root / gate_smoke).exists()

        artifact_contract = wf.get("artifact_contract") or {}
        required_outputs = artifact_contract.get("required_outputs") or []
        assert (
            required_outputs
        ), f"{workflow_id} missing artifact_contract.required_outputs"

        if workflow_id == "workflow_precision_parcellation":
            assert set(required_outputs) >= {
                "parcellation.npz",
                "parcellation_labels.npy",
                "parcellation_stability_report.json",
                "parcellation_provenance.json",
            }
            assert artifact_contract.get("report_files") == [
                "parcellation_stability_report.json"
            ]
            assert artifact_contract.get("provenance_files") == [
                "parcellation_provenance.json"
            ]
            runbook_text = runbook.read_text(encoding="utf-8")
            assert "parcellation_stability_report.json" in runbook_text
            assert "parcellation_provenance.json" in runbook_text

        for asset_id in wf.get("reference_assets") or []:
            assert (
                asset_id in assets
            ), f"{workflow_id} references unknown asset: {asset_id}"


def test_external_repo_candidate_workflows_have_sources_and_runbooks():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    missing = sorted(_EXTERNAL_REPO_CANDIDATE_PACKS - set(workflows))
    assert not missing, f"Candidate repo workflows missing from catalog: {missing}"

    for workflow_id in sorted(_EXTERNAL_REPO_CANDIDATE_PACKS):
        wf = workflows[workflow_id]
        assert wf.get("lifecycle") == "candidate_pack"
        assert wf.get("source_repo")
        assert wf.get("source_paper")
        assert wf.get("tested_release")
        assert wf.get("backend_options")
        assert wf.get("runbook")

        runbook = repo_root / str(wf["runbook"])
        assert runbook.exists(), f"{workflow_id} runbook missing: {runbook}"
        runbook_text = runbook.read_text(encoding="utf-8")
        assert "Minimal BR invocation:" in runbook_text
        assert "MCP recipe:" in runbook_text

        example_dataset = wf.get("example_dataset") or {}
        smoke_test = example_dataset.get("smoke_test")
        assert smoke_test
        assert (repo_root / smoke_test).exists()

        artifact_contract = wf.get("artifact_contract") or {}
        required_outputs = artifact_contract.get("required_outputs") or []
        assert (
            required_outputs
        ), f"{workflow_id} missing artifact_contract.required_outputs"

        acceptance_gate = wf.get("acceptance_gate") or {}
        gate_script = acceptance_gate.get("script")
        gate_smoke = acceptance_gate.get("smoke_test")
        assert gate_script and (repo_root / gate_script).exists()
        assert gate_smoke and (repo_root / gate_smoke).exists()
        if workflow_id in _EXTERNAL_REPO_EXECUTE_GATE_PACKS:
            execute_gate_script = acceptance_gate.get("execute_gate_script")
            execute_gate_test = acceptance_gate.get("execute_gate_test")
            assert execute_gate_script and (repo_root / execute_gate_script).exists()
            assert execute_gate_test and (repo_root / execute_gate_test).exists()
            assert "Minimal execute gate:" in runbook_text
        else:
            assert "Minimal gate invocation:" in runbook_text


def test_workflow_preprocessing_qc_is_execute_capable_but_preview_by_default():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    wf = workflows["workflow_preprocessing_qc"]
    assert wf.get("execution_story_kind") == "composite_workflow"

    example_dataset = wf.get("example_dataset") or {}
    assert example_dataset == {
        "dataset_id": "ds000114",
        "source": "OpenNeuro",
        "smoke_test": (
            "tests/integration/realdata/"
            "test_workflow_preprocessing_qc_ds000114_smoke.py"
        ),
    }

    acceptance_gate = wf.get("acceptance_gate") or {}
    assert (
        acceptance_gate.get("script")
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert acceptance_gate.get("smoke_test") == (
        "tests/integration/realdata/test_workflow_preprocessing_qc_ds000114_smoke.py"
    )
    assert acceptance_gate.get("execute_gate_script") == (
        "scripts/workflows/run_external_repo_minimal_execute_gate.py"
    )
    assert acceptance_gate.get("execute_gate_test") == (
        "tests/integration/realdata/test_workflow_external_repo_minimal_execute_gate.py"
    )
    assert wf.get("runbook") == "docs/runbooks/workflow_preprocessing_qc.md"
    assert (repo_root / str(wf.get("runbook"))).exists()

    artifact_contract = wf.get("artifact_contract") or {}
    assert artifact_contract.get("required_outputs") == [
        "qc_table.csv",
        "qc_outliers.csv",
        "qc_summary.json",
        "index.html",
    ]
    assert artifact_contract.get("optional_outputs") == [
        "fmriprep_dir",
        "mriqc_dir",
    ]

    params = wf.get("params") or {}
    defaults = params.get("defaults") or {}
    schema = params.get("schema") or {}
    properties = schema.get("properties") or {}
    assert defaults.get("dry_run") is True
    assert defaults.get("analysis_level") == "participant"
    assert defaults.get("modalities") == ["bold"]
    assert defaults.get("outlier_metric") == "fd_mean"
    assert properties.get("dry_run", {}).get("type") == "boolean"
    assert properties.get("participant_label", {}).get("type") == "array"

    steps = {step["id"]: step for step in wf["runtime"]["steps"]}
    assert steps["fmriprep"]["params"]["dry_run"] == "${inputs.dry_run:-true}"
    assert steps["mriqc"]["params"]["dry_run"] == "${inputs.dry_run:-true}"
    assert steps["fmriprep"]["params"]["participant_label"] == (
        "${inputs.participant_label}"
    )
    assert steps["mriqc"]["params"]["modalities"] == "${inputs.modalities}"
    assert steps["dashboard"]["params"]["title"] == (
        "${inputs.dashboard_title:-QC Summary}"
    )


def test_workflow_dwi_connectome_has_mature_composite_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    wf = workflows["workflow_dwi_connectome"]
    assert wf.get("execution_story_kind") == "composite_workflow"
    assert wf.get("supported_recipe_targets") == ["neurodesk", "container", "slurm"]
    assert wf.get("primary_target") == "neurodesk"
    assert wf.get("recipe_family") == "dwi_connectome"
    assert wf.get("lifecycle") == "candidate_pack"
    assert wf.get("source_repo") == "https://github.com/MRtrix3/mrtrix3"
    assert wf.get("tested_release")
    backend_options = wf.get("backend_options") or {}
    assert backend_options.get("default") == "qsirecon_derivatives"
    assert backend_options.get("available") == [
        "qsirecon_derivatives",
        "qsiprep_to_qsirecon",
        "raw_tractography_fallback",
    ]
    assert wf.get("modalities") == ["dmri"]

    example_dataset = wf.get("example_dataset") or {}
    assert example_dataset == {
        "dataset_id": "ds000117",
        "source": "OpenNeuro",
        "smoke_test": (
            "tests/integration/realdata/test_workflow_dwi_connectome_ds000117_smoke.py"
        ),
    }

    acceptance_gate = wf.get("acceptance_gate") or {}
    assert (
        acceptance_gate.get("script")
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert acceptance_gate.get("smoke_test") == (
        "tests/integration/realdata/test_workflow_dwi_connectome_ds000117_smoke.py"
    )
    assert "execute_gate_script" not in acceptance_gate
    assert wf.get("runbook") == "docs/runbooks/workflow_dwi_connectome.md"
    runbook = repo_root / str(wf.get("runbook"))
    assert runbook.exists()
    runbook_text = runbook.read_text(encoding="utf-8")
    assert "Minimal BR invocation:" in runbook_text
    assert "Minimal gate invocation:" in runbook_text
    assert "MCP recipe:" in runbook_text

    artifact_contract = wf.get("artifact_contract") or {}
    assert artifact_contract.get("required_outputs") == [
        "sc/connectivity_matrix.csv",
        "sc/connectivity_matrix.npy",
        "sc/graph_metrics.json",
        "sc/connectome_manifest.json",
    ]
    assert artifact_contract.get("optional_outputs") == [
        "qsirecon_dir",
        "tractogram",
        "source_connectome",
        "tracts/streamlines.npy",
        "tracts/tractography_summary.json",
        "tracts/tractography_provenance.json",
        "tracts/fa_map.npy",
        "tracts/md_map.npy",
        "tracts/rd_map.npy",
        "tracts/ad_map.npy",
        "tracts/connectivity.npy",
    ]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    defaults = params.get("defaults") or {}
    properties = schema.get("properties") or {}
    assert schema.get("required") == ["atlas", "output_dir"]
    assert properties.get("qsirecon_dir", {}).get("type") == "string"
    assert properties.get("qsiprep_dir", {}).get("type") == "string"
    assert properties.get("tractogram", {}).get("type") == "string"
    assert properties.get("connectome_file", {}).get("type") == "string"
    assert properties.get("participant_label", {}).get("type") == "array"
    assert properties.get("session_label", {}).get("type") == "string"
    assert defaults.get("output_dir") == "/tmp/brain-researcher/workflow_dwi_connectome"
    assert defaults.get("recon_spec") == "mrtrix_multishell_msmt_ACT-hsvs"
    assert defaults.get("dry_run") is False

    steps = {step["id"]: step for step in wf["runtime"]["steps"]}
    assert steps["tracts"]["tool"] == "run_tractography"
    assert steps["tracts"]["params"]["qsiprep_dir"] == "${inputs.qsiprep_dir}"
    assert steps["tracts"]["params"]["participant_label"] == (
        "${inputs.participant_label}"
    )
    assert steps["tracts"]["params"]["bval"] == "${inputs.bvals}"
    assert steps["tracts"]["params"]["bvec"] == "${inputs.bvecs}"
    assert steps["sc"]["tool"] == "build_structural_connectome"
    assert steps["sc"]["params"]["streamlines"] == (
        "${steps.tracts.data.outputs.streamlines}"
    )


def test_workflow_task_glm_group_has_mature_workflow_contract():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    wf = workflows["workflow_task_glm_group"]
    assert wf.get("execution_story_kind") == "composite_workflow"
    assert wf.get("supported_recipe_targets") == ["python"]
    assert wf.get("primary_target") == "python"
    assert wf.get("recipe_family") == "task_glm_group"
    assert wf.get("modalities") == ["fmri"]

    example_dataset = wf.get("example_dataset") or {}
    assert example_dataset == {
        "dataset_id": "ds000114",
        "source": "OpenNeuro",
        "smoke_test": (
            "tests/integration/realdata/test_workflow_task_glm_group_ds000114_smoke.py"
        ),
    }

    acceptance_gate = wf.get("acceptance_gate") or {}
    assert (
        acceptance_gate.get("script")
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert acceptance_gate.get("smoke_test") == (
        "tests/integration/realdata/test_workflow_task_glm_group_ds000114_smoke.py"
    )
    assert "execute_gate_script" not in acceptance_gate

    assert wf.get("runbook") == "docs/runbooks/workflow_task_glm_group.md"
    runbook = repo_root / str(wf.get("runbook"))
    assert runbook.exists()
    runbook_text = runbook.read_text(encoding="utf-8")
    assert "Minimal BR invocation:" in runbook_text
    assert "Minimal gate invocation:" in runbook_text
    assert "MCP recipe:" in runbook_text
    assert 'target_runtime="python"' in runbook_text

    artifact_contract = wf.get("artifact_contract") or {}
    assert artifact_contract.get("required_outputs") == [
        "first_level_dirs",
        "selected_zmaps",
        "second_level/group_zmap.nii.gz",
        "second_level/glm_second_level_summary.json",
    ]
    assert artifact_contract.get("optional_outputs") == [
        "first_level/<subject>/glm_first_level_summary.json",
        "first_level/<subject>/<contrast_name>_zmap.nii.gz",
    ]
    assert artifact_contract.get("report_files") == [
        "second_level/glm_second_level_summary.json"
    ]

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    defaults = params.get("defaults") or {}
    properties = schema.get("properties") or {}
    assert schema.get("required") == ["output_dir"]
    assert properties.get("img", {}).get("type") == "array"
    assert properties.get("events", {}).get("type") == "array"
    assert properties.get("bids_dir", {}).get("type") == "string"
    assert properties.get("fmriprep_dir", {}).get("type") == "string"
    assert properties.get("task", {}).get("type") == "string"
    assert properties.get("contrast_name", {}).get("type") == "string"
    assert properties.get("t_r", {}).get("type") == "number"
    assert defaults.get("output_dir") == (
        "/tmp/brain-researcher/workflow_task_glm_group"
    )

    steps = {step["id"]: step for step in wf["runtime"]["steps"]}
    assert steps["first_level"]["tool"] == "glm_first_level_batch"
    assert steps["first_level"]["params"]["contrast_name"] == (
        "${inputs.contrast_name}"
    )
    assert steps["second_level"]["tool"] == "run_glm_second_level"
    assert steps["second_level"]["params"]["contrast_maps"] == (
        "${steps.first_level.data.outputs.selected_zmaps}"
    )
    assert steps["second_level"]["params"]["contrast"] == "intercept"


def test_active_connectivity_workflows_have_mature_contracts():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    for workflow_id, expected in sorted(_ACTIVE_CONNECTIVITY_WORKFLOWS.items()):
        wf = workflows[workflow_id]
        assert wf.get("execution_story_kind") in {
            "portable_python_compute",
            "composite_workflow",
        }
        assert wf.get("supported_recipe_targets") == ["python"]
        assert wf.get("primary_target") == "python"
        assert wf.get("recipe_family") == expected["recipe_family"]
        assert wf.get("lifecycle") == "active"
        assert wf.get("modalities") == ["fmri"]

        example_dataset = wf.get("example_dataset") or {}
        assert example_dataset.get("dataset_id") == "ds000114"
        assert example_dataset.get("smoke_test") == expected["smoke_test"]

        acceptance_gate = wf.get("acceptance_gate") or {}
        assert (
            acceptance_gate.get("script")
            == "scripts/workflows/run_workflow_realdata_gate.py"
        )
        assert acceptance_gate.get("smoke_test") == expected["smoke_test"]

        runbook_path = expected["runbook"]
        assert wf.get("runbook") == runbook_path
        runbook = repo_root / runbook_path
        assert runbook.exists()
        runbook_text = runbook.read_text(encoding="utf-8")
        assert "Primary entrypoint:" in runbook_text
        assert "Example dataset:" in runbook_text
        assert "Expected outputs:" in runbook_text
        assert "Minimal BR invocation:" in runbook_text
        assert "Minimal gate invocation:" in runbook_text
        assert "MCP recipe:" in runbook_text
        assert 'target_runtime="python"' in runbook_text
        for output_name in expected["required_outputs"]:
            assert output_name in runbook_text

        artifact_contract = wf.get("artifact_contract") or {}
        assert artifact_contract.get("required_outputs") == expected["required_outputs"]
        assert isinstance(artifact_contract.get("report_files"), list)

        params = wf.get("params") or {}
        schema = params.get("schema") or {}
        defaults = params.get("defaults") or {}
        properties = schema.get("properties") or {}
        assert "output_dir" in schema.get("required", [])
        assert properties.get("output_dir", {}).get("type") == "string"
        assert defaults.get("output_dir", "").startswith("/tmp/brain-researcher/")

        if workflow_id == "workflow_rest_connectome_e2e":
            assert schema.get("required") == ["img", "output_dir"]
            assert properties.get("img", {}).get("type") == "string"
            assert defaults.get("connectivity_kind") == "correlation"
        elif workflow_id == "workflow_seed_based_connectivity":
            assert schema.get("required") == ["img", "output_dir"]
            assert properties.get("seed_coords", {}).get("type") == "array"
            assert defaults.get("radius") == 8.0
        elif workflow_id == "workflow_network_based_statistics":
            assert schema.get("required") == ["timeseries", "labels", "output_dir"]
            assert properties.get("timeseries", {}).get("type") == "string"
            assert defaults.get("threshold") == 1.0
        elif workflow_id == "workflow_connectivity_gradients":
            assert schema.get("required") == ["timeseries", "output_dir"]
            assert properties.get("timeseries", {}).get("type") == "string"
            assert defaults.get("connectivity_kind") == "correlation"
        elif workflow_id == "workflow_group_ica":
            assert schema.get("required") == ["img", "labels", "output_dir"]
            assert defaults.get("n_components") == 20
            assert defaults.get("n_permutations") == 100


def test_workflow_fitlins_direct_has_mature_workflow_contract():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    wf = workflows["workflow_fitlins_direct"]
    assert wf.get("execution_story_kind") == "composite_workflow"
    assert wf.get("supported_recipe_targets") == ["python"]
    assert wf.get("primary_target") == "python"
    assert wf.get("recipe_family") == "fitlins_direct"
    assert wf.get("lifecycle") == "candidate_pack"
    assert wf.get("source_repo") == "https://github.com/poldracklab/fitlins"
    assert wf.get("runbook") == "docs/runbooks/workflow_fitlins_direct.md"

    runbook = repo_root / str(wf.get("runbook"))
    assert runbook.exists()
    runbook_text = runbook.read_text(encoding="utf-8")
    assert "Minimal BR invocation:" in runbook_text
    assert "Minimal gate invocation:" in runbook_text
    assert "MCP recipe:" in runbook_text

    example_dataset = wf.get("example_dataset") or {}
    assert example_dataset.get("dataset_id") == "ds000114"
    assert example_dataset.get("smoke_test") == (
        "tests/integration/realdata/test_workflow_fitlins_direct_ds000114_smoke.py"
    )

    artifact_contract = wf.get("artifact_contract") or {}
    assert artifact_contract.get("required_outputs") == [
        "fitlins/dataset_description.json"
    ]
    assert "fitlins/*_stat-*_statmap.nii.gz" in (
        artifact_contract.get("optional_outputs") or []
    )

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    defaults = params.get("defaults") or {}
    properties = schema.get("properties") or {}
    assert schema.get("required") == ["bids_dir", "fmriprep_dir", "output_dir"]
    assert properties.get("runtime", {}).get("type") == "string"
    assert properties.get("dry_run", {}).get("type") == "boolean"
    assert defaults.get("runtime") == "apptainer"
    assert defaults.get("dry_run") is True

    steps = {step["id"]: step for step in wf["runtime"]["steps"]}
    assert steps["fitlins_direct"]["tool"] == "run_bids_app"
    assert (
        steps["fitlins_direct"]["params"]["runtime"] == "${inputs.runtime:-apptainer}"
    )
    assert steps["fitlins_direct"]["params"]["derivatives"] == (
        "${inputs.fmriprep_dir}"
    )


def test_workflow_fitlins_multiverse_yeo17_has_mature_workflow_contract():
    repo_root = Path(__file__).resolve().parents[3]
    workflows = _load_workflows(repo_root)

    wf = workflows["workflow_fitlins_multiverse_yeo17"]
    assert wf.get("execution_story_kind") == "composite_workflow"
    assert wf.get("supported_recipe_targets") == ["python"]
    assert wf.get("primary_target") == "python"
    assert wf.get("recipe_family") == "fitlins_multiverse"
    assert wf.get("lifecycle") == "candidate_pack"
    assert wf.get("source_repo") == "https://github.com/poldracklab/fitlins"
    assert wf.get("runbook") == "docs/runbooks/workflow_fitlins_multiverse_yeo17.md"

    runbook = repo_root / str(wf.get("runbook"))
    assert runbook.exists()
    runbook_text = runbook.read_text(encoding="utf-8")
    assert "Minimal BR invocation:" in runbook_text
    assert "Minimal gate invocation:" in runbook_text
    assert "MCP recipe:" in runbook_text

    example_dataset = wf.get("example_dataset") or {}
    assert example_dataset.get("dataset_id") == "ds000114"
    assert example_dataset.get("smoke_test") == (
        "tests/integration/realdata/test_workflow_fitlins_multiverse_yeo17_smoke.py"
    )

    artifact_contract = wf.get("artifact_contract") or {}
    assert artifact_contract.get("required_outputs") == [
        "fitlins_multiverse/run_manifest.json"
    ]
    assert "fitlins_multiverse/fitlins/robustness_yeo17.json" in (
        artifact_contract.get("optional_outputs") or []
    )

    params = wf.get("params") or {}
    schema = params.get("schema") or {}
    defaults = params.get("defaults") or {}
    properties = schema.get("properties") or {}
    assert schema.get("required") == ["bids_dir", "fmriprep_dir", "output_dir"]
    assert properties.get("participant_label_csv", {}).get("type") == "string"
    assert properties.get("k", {}).get("type") == "integer"
    assert defaults.get("task") == "linebisection"
    assert defaults.get("runtime") == "apptainer"
    assert defaults.get("no_priors") is True

    steps = {step["id"]: step for step in wf["runtime"]["steps"]}
    assert steps["multiverse_execute"]["tool"] == "run_local_script"
    assert "--runtime=${inputs.runtime:-apptainer}" in (
        steps["multiverse_execute"]["params"]["args"]
    )
    assert steps["multiverse_execute"]["params"]["script"] == (
        "scripts/workflows/run_fitlins_multiverse_execute.py"
    )
