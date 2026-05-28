from typer.testing import CliRunner

from brain_researcher.cli.main import app


runner = CliRunner()


def test_cli_act_monkeypatch(monkeypatch):
    # Monkeypatch agent_act_core to avoid heavy dependencies / real execution
    from brain_researcher.services.agent import agent_core as agent_core_mod

    def fake_agent_act_core(payload, trace_id=None, run_id=None):
        return {
            "message": {"role": "assistant", "content": "ok"},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {
                "id": "run_test",
                "ids": {
                    "job_id": "job_test",
                    "run_id": "run_test",
                    "analysis_id": "job_test",
                },
                "provenance": {
                    "run_dir": "data/runs/20260131/run_test",
                    "trace_jsonl": "data/runs/20260131/run_test/trace.jsonl",
                    "trajectory_json": "data/runs/20260131/run_test/trajectory.json",
                    "observation_json": "data/runs/20260131/run_test/observation.json",
                    "analysis_bundle_json": "data/runs/20260131/run_test/analysis_bundle.json",
                },
            },
        }

    monkeypatch.setattr(agent_core_mod, "agent_act_core", fake_agent_act_core)

    res = runner.invoke(
        app, ["act", "Run GLM for dsXXX", "--json"], catch_exceptions=False
    )
    assert res.exit_code == 0
    assert '"schema_version": "br-act-v1"' in res.stdout
    assert '"run_dir": "data/runs/20260131/run_test"' in res.stdout
    assert '"analysis_bundle_json": "analysis_bundle.json"' in res.stdout


def test_cli_act_preview(monkeypatch):
    from brain_researcher.cli.agent import act as act_mod

    def fake_act_in_process(
        query,
        model=None,
        tools_whitelist=None,
        budget_ms=90000,
        preview=False,
        progress_callback=None,
    ):
        return {
            "selection": {
                "tool": "nilearn_glm",
                "params": {"ds": "dsX"},
                "reasoning": "fits",
            },
            "execution": {
                "provider": "google",
                "model": model or "gemini-3.1-flash-lite-preview",
                "route": "primary",
                "fallback_reason": None,
                "usage": {},
            },
            "preview": {"estimated_runtime": "5-10 minutes"},
        }

    monkeypatch.setattr(act_mod, "act_in_process", fake_act_in_process)
    res = runner.invoke(
        app, ["act", "Run GLM", "--preview", "--json"], catch_exceptions=False
    )
    assert res.exit_code == 0
    assert '"preview": {' in res.stdout
