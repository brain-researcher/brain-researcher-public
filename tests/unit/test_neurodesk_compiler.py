"""Unit tests for NeurodeskCompiler, NeurodeskDispatcher, and NeurodeskToolExecutor."""
from __future__ import annotations

import json
import shlex
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.orchestrator.dag_runtime import WorkflowStep
from brain_researcher.services.tools.neurodesk_compiler import (
    DispatchResult,
    NeurodeskCompiler,
    NeurodeskDispatcher,
    NeurodeskExecutionPack,
    NeurodeskToolExecutor,
    _infer_resource_defaults,
    _minutes_to_slurm,
    _render_command_template,
    _resolve_package,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(
    tool_name: str,
    params: dict | None = None,
    metadata: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=f"step-{tool_name}",
        tool_name=tool_name,
        parameters=params or {},
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# _resolve_package
# ---------------------------------------------------------------------------

class TestResolvePackage:
    def test_exact_match(self):
        assert _resolve_package("fsl_bet", {}) == "fsl"

    def test_prefix_match(self):
        assert _resolve_package("fsl_flirt", {}) == "fsl"

    def test_metadata_override(self):
        assert _resolve_package("fsl_bet", {"neurodesk_package": "ants"}) == "ants"

    def test_unknown_falls_back_to_tool_name(self):
        assert _resolve_package("my_custom_tool", {}) == "my_custom_tool"


# ---------------------------------------------------------------------------
# _infer_resource_defaults
# ---------------------------------------------------------------------------

class TestInferResourceDefaults:
    def test_fmriprep(self):
        r = _infer_resource_defaults("fmriprep", "fmriprep")
        assert r.cpu == 16
        assert r.memory_gb == 64

    def test_freesurfer(self):
        r = _infer_resource_defaults("freesurfer", "recon-all")
        assert r.walltime_minutes == 720

    def test_dcm2niix(self):
        r = _infer_resource_defaults("dcm2niix", "dcm2niix")
        assert r.cpu == 2

    def test_fsl_heavy_command(self):
        r = _infer_resource_defaults("fsl_feat", "feat")
        assert r.cpu == 8
        assert r.walltime_minutes == 240

    def test_fsl_light_command(self):
        r = _infer_resource_defaults("fsl_bet", "bet")
        assert r.cpu == 4
        assert r.memory_gb == 16

    def test_default(self):
        r = _infer_resource_defaults("unknown_tool", "")
        assert r.cpu == 4


# ---------------------------------------------------------------------------
# _minutes_to_slurm
# ---------------------------------------------------------------------------

def test_minutes_to_slurm():
    assert _minutes_to_slurm(60)  == "01:00:00"
    assert _minutes_to_slurm(90)  == "01:30:00"
    assert _minutes_to_slurm(480) == "08:00:00"
    assert _minutes_to_slurm(720) == "12:00:00"


# ---------------------------------------------------------------------------
# NeurodeskCompiler
# ---------------------------------------------------------------------------

@pytest.fixture()
def compiler(tmp_path):
    """Return a NeurodeskCompiler with a mocked profile lookup."""
    with patch(
        "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
    ) as mock_profile:
        mock_profile.return_value = {
            "module_name": "fsl",
            "version": "6.0.7.18",
            "env": {"FSLOUTPUTTYPE": "NIFTI_GZ"},
        }
        yield NeurodeskCompiler(tmp_path, conda_env_name="brain_researcher")


class TestNeurodeskCompiler:
    def test_compile_returns_pack(self, compiler, tmp_path):
        step = _make_step(
            "fsl_bet",
            params={"input_file": "/data/T1w.nii.gz", "output_file": "/out/brain.nii.gz"},
        )
        pack = compiler.compile(step, step_index=1)
        assert isinstance(pack, NeurodeskExecutionPack)
        assert pack.module_spec == "fsl/6.0.7.18"

    def test_script_file_created(self, compiler, tmp_path):
        step = _make_step("fsl_bet", params={"input_file": "/data/T1.nii.gz", "output_file": "/out/brain.nii.gz"})
        pack = compiler.compile(step, step_index=1)
        assert pack.script_path.exists()
        assert pack.script_path.name == "analysis_01_fsl_bet.sh"

    def test_script_has_shebang(self, compiler):
        step = _make_step("fsl_bet")
        pack = compiler.compile(step, step_index=1)
        assert pack.script_text.startswith("#!/bin/bash\n")

    def test_script_has_module_load(self, compiler):
        step = _make_step("fsl_bet")
        pack = compiler.compile(step, step_index=1)
        assert "module load fsl/6.0.7.18" in pack.script_text

    def test_script_has_sbatch_header(self, compiler):
        step = _make_step("fsl_bet")
        pack = compiler.compile(step, step_index=1)
        assert "#SBATCH --job-name=" in pack.script_text
        assert "#SBATCH --cpus-per-task=4" in pack.script_text
        assert "#SBATCH --mem=16G" in pack.script_text
        assert "#SBATCH --time=01:00:00" in pack.script_text

    def test_script_has_env_var(self, compiler):
        step = _make_step("fsl_bet")
        pack = compiler.compile(step, step_index=1)
        assert "FSLOUTPUTTYPE" in pack.script_text

    def test_script_no_conda_for_cli_tool(self, compiler):
        step = _make_step("fsl_bet", metadata={"runtime_kind": "neurodesk"})
        pack = compiler.compile(step, step_index=1)
        assert "conda activate" not in pack.script_text

    def test_script_has_conda_for_python_wrapper(self, compiler):
        step = _make_step(
            "my_python_analysis",
            metadata={"runtime_kind": "python", "neurodesk_package": "fsl"},
        )
        pack = compiler.compile(step, step_index=2)
        assert "conda activate brain_researcher" in pack.script_text

    def test_script_executable(self, compiler, tmp_path):
        step = _make_step("fsl_bet")
        pack = compiler.compile(step, step_index=1)
        import stat
        mode = pack.script_path.stat().st_mode
        assert mode & stat.S_IEXEC

    def test_fmriprep_resource_defaults(self, tmp_path):
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile:
            mock_profile.return_value = {"module_name": "fmriprep", "version": "23.2.3", "env": {}}
            c = NeurodeskCompiler(tmp_path)
            step = _make_step("fmriprep", params={"bids_dir": "/data", "output_dir": "/out"})
            pack = c.compile(step, step_index=1)
        assert "#SBATCH --cpus-per-task=16" in pack.script_text
        assert "#SBATCH --mem=64G" in pack.script_text

    def test_custom_command_builder(self, tmp_path):
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile:
            mock_profile.return_value = {"module_name": "fsl", "version": "6.0.7.18", "env": {}}
            c = NeurodeskCompiler(tmp_path, command_builder=lambda s: ["bet", "custom_arg"])
            step = _make_step("fsl_bet")
            pack = c.compile(step, step_index=1)
        assert "bet custom_arg" in pack.script_text

    def test_cli_command_from_metadata(self, compiler):
        step = _make_step("fsl_bet", metadata={"cli_command": "bet /in.nii.gz /out.nii.gz -f 0.5"})
        pack = compiler.compile(step, step_index=1)
        assert "bet /in.nii.gz /out.nii.gz -f 0.5" in pack.script_text

    def test_expected_outputs_from_params(self, compiler):
        step = _make_step(
            "fsl_bet",
            params={"input_file": "/data/T1w.nii.gz", "output_file": "/out/brain.nii.gz"},
        )
        pack = compiler.compile(step, step_index=1)
        assert "/out/brain.nii.gz" in pack.expected_outputs

    def test_cluster_config_injected(self, tmp_path):
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile:
            mock_profile.return_value = {"module_name": "fsl", "version": "6.0.7.18", "env": {}}
            c = NeurodeskCompiler(tmp_path, cluster_config={"partition": "gpu", "account": "mylab"})
            step = _make_step("fsl_bet")
            pack = c.compile(step, step_index=1)
        assert "#SBATCH --partition=gpu" in pack.script_text
        assert "#SBATCH --account=mylab" in pack.script_text

    def test_template_used_in_default_command(self, tmp_path):
        """When execution_recipes has a template, _default_command renders it."""
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile, patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_command_template"
        ) as mock_tmpl:
            mock_profile.return_value = {"module_name": "fsl", "version": "6.0.7.18", "env": {}}
            mock_tmpl.return_value = "bet {input_file} {output_file} {-f fractional_intensity}"
            c = NeurodeskCompiler(tmp_path)
            step = _make_step(
                "fsl_bet",
                params={"input_file": "/data/T1.nii.gz", "output_file": "/out/brain.nii.gz",
                        "fractional_intensity": "0.5"},
            )
            pack = c.compile(step, step_index=1)
        assert "bet /data/T1.nii.gz /out/brain.nii.gz -f 0.5" in pack.script_text


# ---------------------------------------------------------------------------
# _render_command_template
# ---------------------------------------------------------------------------

class TestRenderCommandTemplate:
    def test_required_params_substituted(self):
        tokens = _render_command_template(
            "bet {input_file} {output_file}",
            {"input_file": "/data/T1.nii.gz", "output_file": "/out/brain.nii.gz"},
        )
        assert tokens == ["bet", "/data/T1.nii.gz", "/out/brain.nii.gz"]

    def test_optional_flag_present(self):
        tokens = _render_command_template(
            "bet {input_file} {output_file} {-f fractional_intensity}",
            {"input_file": "/d/T1.nii.gz", "output_file": "/o/b.nii.gz", "fractional_intensity": 0.5},
        )
        assert "-f" in tokens
        assert "0.5" in tokens

    def test_optional_flag_absent(self):
        tokens = _render_command_template(
            "bet {input_file} {output_file} {-f fractional_intensity}",
            {"input_file": "/d/T1.nii.gz", "output_file": "/o/b.nii.gz"},
        )
        assert "-f" not in tokens
        assert tokens == ["bet", "/d/T1.nii.gz", "/o/b.nii.gz"]

    def test_double_dash_flag_present(self):
        tokens = _render_command_template(
            "fmriprep {bids_dir} {output_dir} participant {--participant-label participant_label}",
            {"bids_dir": "/bids", "output_dir": "/out", "participant_label": "sub-01"},
        )
        assert "--participant-label" in tokens
        assert "sub-01" in tokens

    def test_double_dash_flag_absent(self):
        tokens = _render_command_template(
            "fmriprep {bids_dir} {output_dir} participant {--fs-license-file fs_license_file}",
            {"bids_dir": "/bids", "output_dir": "/out"},
        )
        assert "--fs-license-file" not in tokens

    def test_unresolved_required_placeholder_dropped(self):
        tokens = _render_command_template("bet {input_file} {missing_param}", {"input_file": "/x.nii.gz"})
        assert "{missing_param}" not in " ".join(tokens)

    def test_empty_template_returns_empty(self):
        assert _render_command_template("", {}) == []


# ---------------------------------------------------------------------------
# NeurodeskDispatcher — handoff mode
# ---------------------------------------------------------------------------

class TestNeurodeskDispatcherHandoff:
    def test_handoff_returns_dispatch_result(self, tmp_path):
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        script = tmp_path / "scripts" / "analysis_01_fsl_bet.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\necho hello\n")
        from brain_researcher.services.agent.backends.base_backend import ResourceRequirements
        pack = NeurodeskExecutionPack(
            step_id="step-1",
            script_path=script,
            script_text="#!/bin/bash\necho hello\n",
            job_name="br-01-fsl_bet",
            module_spec="fsl/6.0.7.18",
            resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
        )
        result = dispatcher.dispatch(pack)
        assert isinstance(result, DispatchResult)
        assert result.mode == "handoff"
        assert result.ref.startswith("nd-script-")
        assert result.script_path == str(script)

    def test_handoff_writes_artifact_index(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_artifacts"))
        # Reload cached path helpers by re-importing the module-level function
        import importlib
        import brain_researcher.services.tools.neurodesk_compiler as _mod
        importlib.reload(_mod)  # ensure _REPO_ROOT and env are re-evaluated
        from brain_researcher.services.tools.neurodesk_compiler import NeurodeskDispatcher, NeurodeskExecutionPack

        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        script = tmp_path / "scripts" / "analysis_01_fsl_bet.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\n")
        from brain_researcher.services.agent.backends.base_backend import ResourceRequirements
        pack = NeurodeskExecutionPack(
            step_id="step-1",
            script_path=script,
            script_text="#!/bin/bash\n",
            job_name="br-01-fsl_bet",
            module_spec="fsl/6.0.7.18",
            resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
        )
        result = dispatcher.dispatch(pack)
        index_path = tmp_path / "nd_artifacts" / "index.json"
        assert index_path.exists(), f"Expected global index at {index_path}"
        index = json.loads(index_path.read_text())
        assert any(e["artifact_id"] == result.ref for e in index)

    def test_handoff_instructions_contain_sbatch(self, tmp_path):
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        script = tmp_path / "scripts" / "s.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\n")
        from brain_researcher.services.agent.backends.base_backend import ResourceRequirements
        pack = NeurodeskExecutionPack(
            step_id="s1", script_path=script, script_text="#!/bin/bash\n",
            job_name="br-01-x", module_spec="fsl/6.0.7.18",
            resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
        )
        result = dispatcher.dispatch(pack)
        assert "sbatch" in result.instructions

    def test_unknown_mode_raises(self, tmp_path):
        dispatcher = NeurodeskDispatcher(mode="warp9", config={})
        script = tmp_path / "s.sh"
        script.write_text("#!/bin/bash\n")
        from brain_researcher.services.agent.backends.base_backend import ResourceRequirements
        pack = NeurodeskExecutionPack(
            step_id="s1", script_path=script, script_text="#!/bin/bash\n",
            job_name="br-01-x", module_spec="fsl/6.0.7.18",
            resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
        )
        with pytest.raises(ValueError, match="Unknown dispatch mode"):
            dispatcher.dispatch(pack)


# ---------------------------------------------------------------------------
# NeurodeskDispatcher — confirm_before_dispatch (pending_dispatch flow)
# ---------------------------------------------------------------------------

def _make_pack(tmp_path: Path) -> "NeurodeskExecutionPack":
    from brain_researcher.services.agent.backends.base_backend import ResourceRequirements
    script = tmp_path / "scripts" / "analysis_01_fsl_bet.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\nbet /in.nii.gz /out.nii.gz\n")
    return NeurodeskExecutionPack(
        step_id="step-1",
        script_path=script,
        script_text="#!/bin/bash\nbet /in.nii.gz /out.nii.gz\n",
        job_name="br-01-fsl_bet",
        module_spec="fsl/6.0.7.18",
        resources=ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
    )


class TestNeurodeskDispatcherConfirm:
    def test_confirm_returns_pending_dispatch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={}, confirm_before_dispatch=True)
        pack = _make_pack(tmp_path)
        result = dispatcher.dispatch(pack)
        assert result.mode == "pending_dispatch"
        assert result.ref.startswith("nd-script-")
        assert result.script_content is not None
        assert "Where would you like to run" in result.instructions

    def test_confirm_stages_artifact_as_pending(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={}, confirm_before_dispatch=True)
        pack = _make_pack(tmp_path)
        result = dispatcher.dispatch(pack)
        from brain_researcher.services.tools.neurodesk_compiler import _find_in_global_index
        record = _find_in_global_index(result.ref)
        assert record is not None
        assert record["status"] == "pending"

    def test_execute_dispatch_after_confirmation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={}, confirm_before_dispatch=True)
        pack = _make_pack(tmp_path)
        pending = dispatcher.dispatch(pack)
        # User confirms: run as handoff
        executed = dispatcher.execute_dispatch(pending.ref, "handoff")
        assert executed.mode == "handoff"
        assert executed.ref.startswith("nd-script-")

    def test_execute_dispatch_updates_status_to_dispatched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={}, confirm_before_dispatch=True)
        pack = _make_pack(tmp_path)
        pending = dispatcher.dispatch(pack)
        dispatcher.execute_dispatch(pending.ref, "handoff")
        from brain_researcher.services.tools.neurodesk_compiler import _find_in_global_index
        record = _find_in_global_index(pending.ref)
        assert record["status"] == "dispatched"
        assert record["dispatch_mode"] == "handoff"

    def test_execute_dispatch_unknown_artifact_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        with pytest.raises(ValueError, match="not found"):
            dispatcher.execute_dispatch("nd-script-doesnotexist", "handoff")

    def test_run_tool_confirm_returns_pending_dispatch_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile:
            mock_profile.return_value = {"module_name": "fsl", "version": "6.0.7.18", "env": {}}
            compiler = NeurodeskCompiler(tmp_path)
        dispatcher = NeurodeskDispatcher(mode="handoff", config={}, confirm_before_dispatch=True)
        executor = NeurodeskToolExecutor(dispatcher=dispatcher, compiler=compiler)
        result = executor.run_tool(
            "fsl_bet",
            _execution_context={"runtime_kind": "neurodesk", "step_id": "s1"},
            input_file="/data/T1.nii.gz",
            output_file="/out/brain.nii.gz",
        )
        assert result["status"] == "pending_dispatch"
        assert "artifact_id" in result["data"]
        assert "script_content" in result["data"]
        assert "available_modes" in result["data"]


# ---------------------------------------------------------------------------
# NeurodeskDispatcher — register_completion
# ---------------------------------------------------------------------------

class TestNeurodeskRegisterCompletion:
    def test_register_completion_sets_completed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        pack = _make_pack(tmp_path)
        dispatched = dispatcher.dispatch(pack)
        record = dispatcher.register_completion(
            dispatched.ref,
            output_paths=["/out/brain.nii.gz"],
            exit_code=0,
        )
        assert record["status"] == "completed"
        assert "/out/brain.nii.gz" in record["output_paths"]

    def test_register_completion_failed_on_nonzero_exit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        pack = _make_pack(tmp_path)
        dispatched = dispatcher.dispatch(pack)
        record = dispatcher.register_completion(dispatched.ref, exit_code=1)
        assert record["status"] == "failed"
        assert record["exit_code"] == 1

    def test_register_completion_unknown_artifact_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BR_NEURODESK_ARTIFACTS_DIR", str(tmp_path / "nd_a"))
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        with pytest.raises(ValueError, match="not found"):
            dispatcher.register_completion("nd-script-ghost", output_paths=[])


# ---------------------------------------------------------------------------
# NeurodeskToolExecutor with handoff dispatcher
# ---------------------------------------------------------------------------

class TestNeurodeskToolExecutorHandoff:
    def test_run_tool_handoff_returns_dispatched(self, tmp_path):
        """run_tool() with handoff dispatcher returns status='dispatched'."""
        with patch(
            "brain_researcher.services.tools.neurodesk_compiler.get_neurodesk_package_profile"
        ) as mock_profile:
            mock_profile.return_value = {"module_name": "fsl", "version": "6.0.7.18", "env": {}}
            compiler = NeurodeskCompiler(tmp_path)
        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        executor = NeurodeskToolExecutor(dispatcher=dispatcher, compiler=compiler)
        result = executor.run_tool(
            "fsl_bet",
            _execution_context={"runtime_kind": "neurodesk", "step_id": "s1"},
            input_file="/data/T1.nii.gz",
            output_file="/out/brain.nii.gz",
        )
        assert result["status"] == "dispatched"
        assert result["data"]["mode"] == "handoff"
        assert result["data"]["artifact_id"].startswith("nd-script-")
        assert result["error"] is None
