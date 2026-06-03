from __future__ import annotations

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.mcp import slurm_tools as st


def test_sherlock_get_guide_wrapper_returns_batch_commands():
    result = srv.sherlock_guide(action="guide", topic="batch", pi_group="russpold")

    assert result["ok"] is True
    assert result["topic"] == "batch"
    assert any("sbatch" in row["command"] for row in result["commands"])


def test_tool_search_discovers_sherlock_mcp_tools():
    result = srv.tool_search(query="sherlock sbatch", limit=20, exposed_only=True)

    assert result["ok"] is True
    names = [tool["name"] for tool in result["tools"]]
    assert "mcp.sherlock_guide" in names
    assert "mcp.sherlock_slurm" in names


def test_tool_search_discovers_sherlock_slurm_for_patch_queries():
    result = srv.tool_search(query="patch sbatch script", limit=20, exposed_only=True)

    assert result["ok"] is True
    names = [tool["name"] for tool in result["tools"]]
    assert "mcp.sherlock_slurm" in names


def test_tool_search_discovers_sherlock_slurm_for_diagnose_queries():
    result = srv.tool_search(query="diagnose job failure", limit=20, exposed_only=True)

    assert result["ok"] is True
    names = [tool["name"] for tool in result["tools"]]
    assert "mcp.sherlock_slurm" in names


def test_sherlock_slurm_wrapper_renders_script():
    result = srv.sherlock_slurm(
        action="render_script",
        template_kind="cpu_single",
        job_name="analysis",
        command="python run_analysis.py",
    )

    assert result["ok"] is True
    assert "#SBATCH --job-name=analysis" in result["script_text"]


def test_sherlock_slurm_wrapper_requires_change_request_for_patch_script():
    result = srv.sherlock_slurm(
        action="patch_script",
        script_text="#!/bin/bash\npython run.py\n",
    )

    assert result["ok"] is False
    assert result["error"] == "missing_change_request"
    assert result["message"] == "Provide change_request when action='patch_script'."


def test_sherlock_render_sbatch_script_gpu_multinode_contains_expected_directives():
    result = st.sherlock_render_sbatch_script(
        template_kind="gpu_multinode",
        job_name="train",
        nodes=2,
        ntasks_per_node=1,
        gpus_per_node=2,
        launcher="srun torchrun train.py",
    )

    assert result["ok"] is True
    script_text = result["script_text"]
    assert "#SBATCH --nodes=2" in script_text
    assert "#SBATCH --ntasks-per-node=1" in script_text
    assert "#SBATCH --gpus-per-node=2" in script_text
    assert "srun torchrun train.py" in script_text


def test_sherlock_patch_sbatch_script_updates_memory_and_cpu():
    original = (
        "#!/bin/bash\n#SBATCH --mem=32G\n#SBATCH --cpus-per-task=8\npython run.py\n"
    )

    result = st.sherlock_patch_sbatch_script(
        change_request="increase memory to 64G and set cpus-per-task to 16",
        script_text=original,
    )

    assert result["ok"] is True
    assert "#SBATCH --mem=64G" in result["patched_text"]
    assert "#SBATCH --cpus-per-task=16" in result["patched_text"]
    assert "Set mem=64G" in result["change_summary"]


def test_sherlock_validate_sbatch_script_flags_missing_partition_and_qos():
    script_text = "#!/bin/bash\n#SBATCH --time=04:00:00\npython run.py\n"

    result = st.sherlock_validate_sbatch_script(script_text=script_text)

    assert result["ok"] is True
    assert "Missing --partition directive." in result["warnings"]
    assert "Missing --qos directive." in result["warnings"]


def test_sherlock_job_inspect_parses_local_command_outputs(monkeypatch):
    def fake_run(args: list[str], timeout: int = 15):
        if args[0] == "squeue":
            return {
                "ok": True,
                "stdout": "123|RUNNING|None|00:10:00|01:00:00|1|node001\n",
                "stderr": "",
                "returncode": 0,
                "command": args,
            }
        if args[0] == "sacct":
            return {
                "ok": True,
                "stdout": (
                    "JobID|JobName|Partition|State|ExitCode|Elapsed|MaxRSS|NodeList|AllocCPUS\n"
                    "123|test|russpold|COMPLETED|0:0|00:10:00|2G|node001|8\n"
                ),
                "stderr": "",
                "returncode": 0,
                "command": args,
            }
        if args[0] == "scontrol":
            return {
                "ok": True,
                "stdout": "JobId=123 StdOut=/tmp/slurm-123.out StdErr=/tmp/slurm-123.err\n",
                "stderr": "",
                "returncode": 0,
                "command": args,
            }
        raise AssertionError(args)

    monkeypatch.setattr(st, "_run_local_command", fake_run)

    result = st.sherlock_job_inspect("123")

    assert result["ok"] is True
    assert result["squeue"]["state"] == "RUNNING"
    assert result["sacct"][0]["State"] == "COMPLETED"
    assert result["log_paths"]["stdout"] == "/tmp/slurm-123.out"


def test_sherlock_diagnose_job_failure_detects_oom():
    result = st.sherlock_diagnose_job_failure(
        sacct_state="OUT_OF_MEMORY",
        stderr_text="slurmstepd: error: Detected 1 oom-kill event(s) in step 123.batch",
    )

    assert result["ok"] is True
    assert result["likely_cause"] == "oom"
    assert result["confidence"] == "high"
