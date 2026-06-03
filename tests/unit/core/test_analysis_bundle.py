import json
from pathlib import Path

import brain_researcher.core.analysis_bundle as analysis_bundle
from brain_researcher.core.analysis_bundle import save_analysis_bundle


class DummyJob:
    def __init__(self, run_dir: Path, *, job_id: str = "job-1", run_id: str = "run-1"):
        self.run_dir = str(run_dir)
        self.id = job_id
        self.run_id = run_id


def test_save_analysis_bundle_emits_single_bundle(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    (run_dir / "output.txt").write_text("ok", encoding="utf-8")
    (run_dir / "trajectory.json").write_text(
        '{"schema_version":"ATIF-v1.4"}', encoding="utf-8"
    )
    (run_dir / "inputs_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "inputs-manifest-v1",
                "inputs": [
                    {
                        "key": "payload.plan.steps[0].params.img",
                        "path": "/tmp/input.nii.gz",
                        "resolved_path": "/tmp/input.nii.gz",
                        "checksum_status": "missing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "threshold_summary.json").write_text(
        json.dumps({"n_clusters_surviving": 2}),
        encoding="utf-8",
    )
    (run_dir / "correction_summary.json").write_text(
        json.dumps({"method": "fdr", "alpha": 0.05}),
        encoding="utf-8",
    )
    (run_dir / "design_matrix.csv").write_text(
        "intercept,task\n1,0\n1,1\n",
        encoding="utf-8",
    )
    (run_dir / "contrast_table.csv").write_text(
        "contrast_name,intercept,task\nmain_effect,0,1\n",
        encoding="utf-8",
    )
    (run_dir / "cluster_table.csv").write_text(
        "cluster_id,cluster_size,p_fwe\n1,42,0.01\n2,18,0.03\n",
        encoding="utf-8",
    )
    (run_dir / "peak_table.csv").write_text(
        "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n-24,-60,40,4.4,2\n",
        encoding="utf-8",
    )

    observation = {
        "schema_version": "observation-v1",
        "job_id": "job-1",
        "run_id": "run-1",
        "state": "succeeded",
        "artifacts": [
            {"name": "output.txt", "type": "text", "path": "output.txt", "size": 2}
        ],
        "run_card": {
            "id": "job-1",
            "version": "1.0",
            "parameters": {
                "target_column": "story_score",
                "split_unit": "subject",
                "grouped_split_keys": ["subject"],
                "required_group_keys": ["subject"],
                "best_model": "ridge",
                "model_candidates": ["ridge", "lasso"],
                "nested_cv": True,
            },
        },
        "provenance": {
            "schema_version": "provenance-v1",
            "command": ["python", "analysis.py", "--input", "input.nii.gz"],
            "packages": {"nilearn": "0.11.1", "numpy": "1.26.4"},
            "environment": {"python_version": "3.11.9"},
            "parameters": {
                "tr": 2.0,
                "hrf_model": "spm",
                "correction_summary_path": "correction_summary.json",
                "threshold_summary_path": "threshold_summary.json",
                "design_matrix_path": "design_matrix.csv",
                "contrast_table_path": "contrast_table.csv",
                "cluster_table_path": "cluster_table.csv",
                "peak_table_path": "peak_table.csv",
            },
        },
    }
    (run_dir / "observation.json").write_text(json.dumps(observation), encoding="utf-8")
    (run_dir / "analysis.py").write_text("print('hello')\n", encoding="utf-8")

    job = DummyJob(run_dir, job_id="job-1", run_id="run-1")
    save_analysis_bundle(job, run_dir)

    bundle_path = run_dir / "analysis_bundle.json"
    assert bundle_path.exists()

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "analysis-bundle-v1"
    assert bundle["job_id"] == "job-1"
    assert bundle["run_id"] == "run-1"

    roles = {entry["role"] for entry in bundle.get("file_manifest", [])}
    assert "observation" in roles
    assert "trajectory" in roles
    assert "execution_manifest" in roles
    assert "correction_summary" in roles
    assert "threshold_summary" in roles
    assert "design_matrix" in roles
    assert "contrast_table" in roles
    assert "cluster_table" in roles
    assert "peak_table" in roles
    assert "analysis_script" in roles
    assert "run_script" in roles
    assert "requirements" in roles

    assert bundle["files"]["observation_json"] == "observation.json"
    assert bundle["files"]["trajectory_json"] == "trajectory.json"
    assert bundle["files"]["execution_manifest_json"] == "execution_manifest.json"
    assert bundle["files"]["correction_summary_json"] == "correction_summary.json"
    assert bundle["files"]["threshold_summary_json"] == "threshold_summary.json"
    assert bundle["files"]["design_matrix"] == "design_matrix.csv"
    assert bundle["files"]["contrast_table"] == "contrast_table.csv"
    assert bundle["files"]["cluster_table"] == "cluster_table.csv"
    assert bundle["files"]["peak_table"] == "peak_table.csv"
    assert bundle["files"]["analysis_script_py"] == "analysis.py"
    assert bundle["files"]["run_script_sh"] == "run.sh"
    assert bundle["files"]["requirements_txt"] == "requirements.txt"

    assert bundle.get("observation", {}).get("schema_version") == "observation-v1"
    assert bundle.get("trajectory", {}).get("schema_version") == "ATIF-v1.4"
    execution_manifest = bundle.get("execution_manifest") or {}
    assert execution_manifest.get("schema_version") == "execution-manifest-v1"
    assert execution_manifest.get("execution_mode") == "mixed"
    assert (
        execution_manifest.get("entrypoints", {}).get("python_script") == "analysis.py"
    )
    assert execution_manifest.get("entrypoints", {}).get("shell_script") == "run.sh"
    assert (
        execution_manifest.get("entrypoints", {}).get("environment_file")
        == "requirements.txt"
    )
    assert execution_manifest.get("runtime", {}).get("python_version") == "3.11.9"
    assert execution_manifest.get("parameters", {}).get("tr") == 2.0
    assert (
        execution_manifest.get("inputs", [{}])[0].get("name")
        == "payload.plan.steps[0].params.img"
    )
    assert execution_manifest.get("outputs", [{}])[0].get("path") == "output.txt"
    assert bundle["review_context"]["selection"]["best_model"] == "ridge"
    assert bundle["review_context"]["selection"]["model_candidates"] == [
        "ridge",
        "lasso",
    ]
    assert bundle["review_context"]["selection"]["nested_cv"] is True
    assert bundle["review_context"]["design_model"]["hrf_model"] == "spm"
    assert bundle["review_context"]["design_model"]["tr"] == 2.0
    assert (
        bundle["observation"]["run_card"]["review_context"]["selection"]["best_model"]
        == "ridge"
    )

    artifacts = bundle.get("artifacts") or []
    assert artifacts
    assert artifacts[0]["checksum_status"] == "ok"
    assert artifacts[0]["checksum"].startswith("sha256:")

    run_script = (run_dir / "run.sh").read_text(encoding="utf-8")
    assert "python analysis.py --input input.nii.gz" in run_script
    requirements = (run_dir / "requirements.txt").read_text(encoding="utf-8")
    assert "nilearn==0.11.1" in requirements


def test_save_analysis_bundle_includes_user_distribution_files(
    tmp_path: Path, monkeypatch
):
    repo_root = tmp_path / "repo"
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True)
    (repo_root / "environment.yml").write_text("name: br\n", encoding="utf-8")
    (repo_root / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: br\n",
        encoding="utf-8",
    )
    (repo_root / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    (docs_dir / "index.md").write_text("# Docs\n", encoding="utf-8")
    (docs_dir / "mcp.md").write_text("# MCP\n", encoding="utf-8")
    (docs_dir / "OPERATIONS.md").write_text("# Operations\n", encoding="utf-8")
    monkeypatch.setattr(analysis_bundle, "_find_repo_root", lambda: repo_root)

    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    (run_dir / "trajectory.json").write_text(
        '{"schema_version":"ATIF-v1.4"}',
        encoding="utf-8",
    )
    (run_dir / "observation.json").write_text(
        json.dumps(
            {
                "schema_version": "observation-v1",
                "job_id": "job-2",
                "run_id": "run-2",
                "state": "succeeded",
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )

    job = DummyJob(run_dir, job_id="job-2", run_id="run-2")
    save_analysis_bundle(job, run_dir)

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    files = bundle["files"]
    assert files["user_environment_yml"] == ".bundle_support/environment.yml"
    assert files["user_docker_compose_yml"] == ".bundle_support/docker-compose.yml"
    assert files["user_env_example"] == ".bundle_support/.env.example"
    assert files["user_docs_index_md"] == ".bundle_support/docs_index.md"
    assert files["user_mcp_md"] == ".bundle_support/mcp.md"
    assert files["user_operations_md"] == ".bundle_support/operations.md"

    for relpath in (
        files["user_environment_yml"],
        files["user_docker_compose_yml"],
        files["user_env_example"],
        files["user_docs_index_md"],
        files["user_mcp_md"],
        files["user_operations_md"],
    ):
        assert (run_dir / relpath).exists()

    roles = {entry["role"] for entry in bundle.get("file_manifest", [])}
    assert "user_environment" in roles
    assert "user_docker_compose" in roles
    assert "user_env_example" in roles
    assert "user_docs_index" in roles
    assert "user_mcp" in roles
    assert "user_operations" in roles


def test_save_analysis_bundle_deduplicates_artifacts_before_checksums(tmp_path: Path):
    run_dir = tmp_path / "run-dedupe"
    run_dir.mkdir()
    artifact_path = run_dir / "outputs" / "result.txt"
    artifact_path.parent.mkdir()
    artifact_path.write_text("ok", encoding="utf-8")

    observation = {
        "schema_version": "observation-v1",
        "job_id": "job-dedupe",
        "run_id": "run-dedupe",
        "state": "succeeded",
        "artifacts": [
            {
                "id": "payload-random-id",
                "artifact_id": "payload-random-id",
                "name": "result.txt",
                "uri": str(artifact_path),
                "download_url": "https://stale.example/result.txt",
            },
            {
                "id": "artifact_outputs_result.txt",
                "artifact_id": "artifact_outputs_result.txt",
                "name": "result.txt",
                "path": "outputs/result.txt",
                "download_url": (
                    "/api/jobs/job-dedupe/artifacts/files/outputs/result.txt"
                ),
            },
        ],
    }
    (run_dir / "observation.json").write_text(json.dumps(observation), encoding="utf-8")

    job = DummyJob(run_dir, job_id="job-dedupe", run_id="run-dedupe")
    save_analysis_bundle(job, run_dir)

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    artifacts = bundle.get("artifacts") or []
    assert len(artifacts) == 1
    assert artifacts[0]["path"] == "outputs/result.txt"
    assert "stale.example" not in artifacts[0]["download_url"]
    assert artifacts[0]["checksum_status"] == "ok"
    assert artifacts[0]["checksum"].startswith("sha256:")


def test_save_analysis_bundle_does_not_depend_on_service_settings(tmp_path: Path):
    run_dir = tmp_path / "run-policy"
    run_dir.mkdir()
    (run_dir / "observation.json").write_text(
        json.dumps(
            {
                "schema_version": "observation-v1",
                "policy": {
                    "policy_id": "policy/test",
                    "mode": "advisory",
                },
            }
        ),
        encoding="utf-8",
    )

    job = DummyJob(run_dir, job_id="job-policy", run_id="run-policy")
    save_analysis_bundle(job, run_dir)

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert "policy_snapshot" not in bundle
    assert bundle["policy"]["policy_id"] == "policy/test"
