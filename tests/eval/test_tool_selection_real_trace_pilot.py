"""Regression tests for the real-trace tool-selection pilot runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "run_tool_selection_real_trace_pilot.py"
SPEC = importlib.util.spec_from_file_location("run_tool_selection_real_trace_pilot", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)

RESCORE_SCRIPT_PATH = ROOT / "scripts" / "eval" / "rescore_tool_selection_real_trace_run.py"
RESCORE_SPEC = importlib.util.spec_from_file_location(
    "rescore_tool_selection_real_trace_run", RESCORE_SCRIPT_PATH
)
assert RESCORE_SPEC is not None
assert RESCORE_SPEC.loader is not None
rescorer = importlib.util.module_from_spec(RESCORE_SPEC)
sys.modules[RESCORE_SPEC.name] = rescorer
RESCORE_SPEC.loader.exec_module(rescorer)

SUMMARY_SCRIPT_PATH = ROOT / "scripts" / "eval" / "summarize_tool_selection_model_matrix.py"
SUMMARY_SPEC = importlib.util.spec_from_file_location(
    "summarize_tool_selection_model_matrix", SUMMARY_SCRIPT_PATH
)
assert SUMMARY_SPEC is not None
assert SUMMARY_SPEC.loader is not None
matrix_summary = importlib.util.module_from_spec(SUMMARY_SPEC)
sys.modules[SUMMARY_SPEC.name] = matrix_summary
SUMMARY_SPEC.loader.exec_module(matrix_summary)


def test_prompt_preserves_br_mode_boundary() -> None:
    task = {
        "task_id": "DATA-001",
        "category": "Data Management",
        "query": "Fetch and validate BIDS structure",
    }

    without = runner.build_prompt(task, runner.condition_by_id()["codex_cli_gpt55_without_br"])
    with_br = runner.build_prompt(task, runner.condition_by_id()["codex_cli_gpt55_with_br"])
    claude_with_br = runner.build_prompt(task, runner.condition_by_id()["claude_code_opus47_with_br"])

    assert "BR MCP/tools are disabled" in without
    assert "Do not call Brain Researcher" in without
    assert "BR MCP/tools are enabled" in with_br
    assert "Use at most three non-neutral tool-selection actions" in with_br
    assert "Do not run repo searches" in with_br
    assert "selection_mode=true" in with_br
    assert "recommended_next_calls" in with_br
    assert "actual MCP tool calls" in with_br
    assert "do not fall back to a local route target" in with_br
    assert "printed JSON route dictionaries" in with_br
    assert "Do not call generic BR `tool_search` as an early action" in with_br
    assert "dataset_get_resources" in with_br
    assert "pybids.BIDSLayout(validate=True)" in with_br
    assert "Do not call Claude `ToolSearch` as an early action" in claude_with_br


def test_summary_marks_all_failed_no_action_condition_invalid() -> None:
    rows = [
        {
            "condition": "claude_code_opus47_with_br",
            "task_id": "WF-001",
            "status": "failed",
            "scored": True,
            "no_action": True,
            "needs_human_adjudication": True,
        },
        {
            "condition": "claude_code_opus47_with_br",
            "task_id": "WF-002",
            "status": "failed",
            "scored": True,
            "no_action": True,
            "needs_human_adjudication": True,
        },
    ]

    summary = matrix_summary.summarize_condition(rows)

    assert summary[0]["provider_failure_like"] is True
    assert summary[0]["valid_condition"] is False


def test_matrix_summary_exposes_strict_br_usage_diagnostics() -> None:
    rows = [
        {
            "condition": "codex_cli_gpt55_with_br",
            "task_id": "WF-001",
            "status": "succeeded",
            "scored": True,
            "correct": True,
            "capability_score": 1.0,
            "ungated_capability_score": 1.0,
            "br_usage_ok": True,
            "br_direct_plan_preflight_count": 1,
            "br_direct_concrete_route_count": 1,
        },
        {
            "condition": "codex_cli_gpt55_with_br",
            "task_id": "WF-013",
            "status": "succeeded",
            "scored": True,
            "correct": False,
            "capability_score": 0.0,
            "ungated_capability_score": 1.0,
            "br_usage_ok": False,
            "br_direct_plan_preflight_count": 0,
            "br_direct_concrete_route_count": 0,
        },
    ]

    condition_summary = matrix_summary.summarize_condition(rows)
    pair_summary = matrix_summary.summarize_pairs(condition_summary)
    task_summary = matrix_summary.summarize_tasks(rows)

    assert condition_summary[0]["mean_capability_score"] == 0.5
    assert condition_summary[0]["mean_ungated_capability_score"] == 1.0
    assert condition_summary[0]["br_usage_ok_rate"] == 0.5
    assert condition_summary[0]["mean_br_direct_plan_preflight_count"] == 0.5
    assert condition_summary[0]["mean_br_direct_concrete_route_count"] == 0.5
    assert pair_summary[0]["ungated_capability_with_br"] == 1.0
    assert pair_summary[0]["br_usage_ok_with_br"] == 0.5
    assert task_summary[1]["br_usage_ok_with_br"] == 0.0


def test_prompt_uses_task_json_route_hints() -> None:
    task = {
        "task_id": "WF-001",
        "category": "Workflow Family - Diffusion",
        "query": "Select QSIPrep route",
        "route_hints": [
            "workflow_qsiprep via get_execution_recipe",
            "QSIPrep command route with eddy/topup options",
        ],
    }

    prompt = runner.build_prompt(task, runner.condition_by_id()["codex_cli_gpt55_with_br"])

    assert "workflow_qsiprep via get_execution_recipe" in prompt
    assert "QSIPrep command route with eddy/topup options" in prompt


def test_dry_run_materializes_episode_commands(tmp_path: Path) -> None:
    args = argparse.Namespace(
        tasks_jsonl=ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "capability_pilot"
        / "microtooling_capability_pilot.v1.jsonl",
        output_root=tmp_path,
        run_name="dryrun",
        task=["DATA-001"],
        condition=["codex_cli_gpt55_without_br"],
        limit_tasks=None,
        stop_after_actions=3,
        timeout_s=5,
        execute=False,
        codex_bin="codex",
        claude_bin="claude",
        opencode_bin="opencode",
        claude_mcp_config=ROOT / ".mcp.json",
        br_mcp_surface="prod",
        br_mcp_http_url="https://${PUBLIC_HOSTNAME}/mcp",
        allow_opencode_with_br_without_mcp=False,
    )

    payload = runner.run_matrix(args)
    episode_dir = tmp_path / "dryrun" / "episodes" / "codex_cli_gpt55_without_br" / "DATA-001"

    assert payload["scale_readiness"]["decision"] == "materialized_only_not_scale_ready"
    assert (episode_dir / "prompt.txt").exists()
    command = json.loads((episode_dir / "command.json").read_text())
    assert command["dry_run"] is True
    assert command["condition_id"] == "codex_cli_gpt55_without_br"


def test_claude_with_br_disallows_generic_tool_search(tmp_path: Path) -> None:
    condition = runner.condition_by_id()["claude_code_opus47_with_br"]
    prod_config = tmp_path / "prod.mcp.json"
    prod_config.write_text('{"mcpServers":{}}\n', encoding="utf-8")
    command, stdin_text, skip_reason = runner.build_command(
        condition=condition,
        prompt="route task",
        run_dir=tmp_path,
        codex_bin="codex",
        claude_bin="claude",
        opencode_bin="opencode",
        claude_mcp_config=ROOT / ".mcp.json",
        allow_opencode_with_br=False,
        br_mcp_surface="prod",
        prod_claude_mcp_config=prod_config,
    )

    assert stdin_text is None
    if skip_reason and skip_reason.startswith("missing_binary:"):
        return
    assert skip_reason is None
    assert "--disallowedTools" in command
    denied = command[command.index("--disallowedTools") + 1]
    assert "ToolSearch" in denied
    assert "mcp__brain-researcher-local__tool_search" in denied
    assert "mcp__brain_researcher_prod__tool_search" in denied


def test_runner_counts_stop_budget_by_non_neutral_actions() -> None:
    tasks_path = (
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "capability_pilot"
        / "microtooling_capability_pilot.v1.jsonl"
    )
    data_task = next(
        json.loads(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["task_id"] == "DATA-001"
    )
    actions = [
        {"index": 1, "action_type": "mcp_tool", "target": "tool_search", "task_id": None},
        {
            "index": 2,
            "action_type": "mcp_tool",
            "target": "dataset_get_resources",
            "task_id": None,
        },
        {
            "index": 3,
            "action_type": "bash_cmd",
            "target": "python -c \"import shutil; print(shutil.which('bids-validator'))\"",
            "task_id": None,
        },
    ]

    assert runner._raw_relevant_action_count(actions, "DATA-001") == 3
    assert runner._non_neutral_action_count(actions, data_task) == 1


def test_json_error_event_detection() -> None:
    lines = [
        '{"type":"error","error":{"name":"APIError","data":{"statusCode":401}}}',
    ]

    assert runner._has_json_error_event(lines) is True


def test_skip_existing_records_reuses_and_scores_frozen_stdout(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    tasks_jsonl.write_text(
        json.dumps(
            {
                "task_id": "T1",
                "query": "Select Haxby dataset and BIDS validation route",
                "category": "Data",
                "required_capabilities": ["dataset_access"],
                "acceptable_patterns": [
                    {
                        "capability": "dataset_access",
                        "action_type": "mcp_tool",
                        "pattern": "dataset_get_resources",
                        "match": "exact",
                    }
                ],
                "neutral_patterns": [],
                "disqualifying_patterns": [],
                "canonical_br_tools": ["dataset_get_resources"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    episode_dir = tmp_path / "resume" / "episodes" / "codex_cli_gpt55_with_br" / "T1"
    episode_dir.mkdir(parents=True)
    (episode_dir / "record.json").write_text(
        json.dumps(
            {
                "condition_id": "codex_cli_gpt55_with_br",
                "task_id": "T1",
                "status": "succeeded",
                "wall_time_s": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (episode_dir / "stdout.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "plan_preflight",
                        "arguments": {
                            "query": "T1 Haxby dataset and BIDS validation route",
                            "selection_mode": True,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "dataset_get_resources",
                        "arguments": {"dataset_ref": "haxby"},
                    }
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        tasks_jsonl=tasks_jsonl,
        output_root=tmp_path,
        run_name="resume",
        task=[],
        condition=["codex_cli_gpt55_with_br"],
        limit_tasks=None,
        stop_after_actions=3,
        timeout_s=5,
        execute=True,
        skip_existing_records=True,
        codex_bin="definitely_missing_codex_binary",
        claude_bin="claude",
        opencode_bin="opencode",
        claude_mcp_config=ROOT / ".mcp.json",
        br_mcp_surface="prod",
        br_mcp_http_url="https://${PUBLIC_HOSTNAME}/mcp",
        allow_opencode_with_br_without_mcp=False,
    )

    payload = runner.run_matrix(args)

    assert payload["records"][0]["status"] == "succeeded"
    assert payload["summary"]["codex_cli_gpt55_with_br"]["n_tasks"] == 1
    assert payload["summary"]["codex_cli_gpt55_with_br"]["tool_selection_accuracy"] == 1.0


def test_skip_existing_records_scores_empty_action_trace_as_failure(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    tasks_jsonl.write_text(
        json.dumps(
            {
                "task_id": "T1",
                "query": "Select Haxby dataset and BIDS validation route",
                "category": "Data",
                "required_capabilities": ["dataset_access"],
                "acceptable_patterns": [
                    {
                        "capability": "dataset_access",
                        "action_type": "mcp_tool",
                        "pattern": "dataset_get_resources",
                        "match": "exact",
                    }
                ],
                "neutral_patterns": [],
                "disqualifying_patterns": [],
                "canonical_br_tools": ["dataset_get_resources"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    episode_dir = tmp_path / "resume" / "episodes" / "codex_cli_gpt55_with_br" / "T1"
    episode_dir.mkdir(parents=True)
    (episode_dir / "record.json").write_text(
        json.dumps(
            {
                "condition_id": "codex_cli_gpt55_with_br",
                "task_id": "T1",
                "status": "succeeded",
                "wall_time_s": 1.0,
                "parsed_action_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (episode_dir / "stdout.jsonl").write_text("", encoding="utf-8")

    args = argparse.Namespace(
        tasks_jsonl=tasks_jsonl,
        output_root=tmp_path,
        run_name="resume",
        task=[],
        condition=["codex_cli_gpt55_with_br"],
        limit_tasks=None,
        stop_after_actions=3,
        timeout_s=5,
        execute=True,
        skip_existing_records=True,
        codex_bin="definitely_missing_codex_binary",
        claude_bin="claude",
        opencode_bin="opencode",
        claude_mcp_config=ROOT / ".mcp.json",
        br_mcp_surface="prod",
        br_mcp_http_url="https://${PUBLIC_HOSTNAME}/mcp",
        allow_opencode_with_br_without_mcp=False,
    )

    payload = runner.run_matrix(args)
    score_rows = (tmp_path / "resume" / "score_rows.jsonl").read_text(encoding="utf-8")

    assert len(score_rows.splitlines()) == 1
    assert payload["summary"]["codex_cli_gpt55_with_br"]["n_tasks"] == 1
    assert payload["summary"]["codex_cli_gpt55_with_br"]["no_action_rate"] == 1.0
    assert payload["summary"]["codex_cli_gpt55_with_br"]["br_usage_ok_rate"] == 0.0
    assert payload["summary"]["codex_cli_gpt55_with_br"]["mean_capability_score"] == 0.0


def test_default_conditions_cover_experiment_setup_models() -> None:
    condition_ids = set(runner.condition_by_id())

    assert {
        "codex_cli_gpt55_without_br",
        "codex_cli_gpt55_with_br",
        "claude_code_opus47_without_br",
        "claude_code_opus47_with_br",
        "opencode_gemini_pro_without_br",
        "opencode_gemini_pro_with_br",
        "opencode_glm51_without_br",
        "opencode_glm51_with_br",
        "opencode_kimi_k25_without_br",
        "opencode_kimi_k25_with_br",
        "opencode_qwen36_plus_without_br",
        "opencode_qwen36_plus_with_br",
        "opencode_deepseek_v4_pro_without_br",
        "opencode_deepseek_v4_pro_with_br",
    } <= condition_ids
    assert (
        runner.condition_by_id()["opencode_gemini_pro_without_br"].model
        == "google/gemini-3.1-pro-preview"
    )
    assert (
        runner.condition_by_id()["opencode_gemini_pro_with_br"].model
        == "google/gemini-3.1-pro-preview"
    )
    assert (
        runner.condition_by_id()["opencode_glm51_without_br"].model
        == "zai-coding-plan/glm-5.1"
    )
    assert (
        runner.condition_by_id()["opencode_glm51_with_br"].model
        == "zai-coding-plan/glm-5.1"
    )
    assert (
        runner.condition_by_id()["opencode_kimi_k25_without_br"].model
        == "opencode/kimi-k2.5"
    )
    assert (
        runner.condition_by_id()["opencode_kimi_k25_with_br"].model
        == "opencode/kimi-k2.5"
    )
    assert (
        runner.condition_by_id()["opencode_qwen36_plus_without_br"].model
        == "opencode/qwen3.6-plus"
    )
    assert (
        runner.condition_by_id()["opencode_qwen36_plus_with_br"].model
        == "opencode/qwen3.6-plus"
    )
    assert (
        runner.condition_by_id()["opencode_deepseek_v4_pro_without_br"].model
        == "deepseek/deepseek-v4-pro"
    )
    assert (
        runner.condition_by_id()["opencode_deepseek_v4_pro_with_br"].model
        == "deepseek/deepseek-v4-pro"
    )


def test_episode_env_loads_repo_dotenv_without_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=from_dotenv\nGOOGLE_API_KEY='quoted_value'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "from_environment")

    env = runner.episode_env(runner.condition_by_id()["opencode_gemini_pro_without_br"])

    assert env["GEMINI_API_KEY"] == "from_dotenv"
    assert env["GOOGLE_API_KEY"] == "from_environment"
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"


def test_write_prod_mcp_runtime_uses_temp_remote_configs(tmp_path: Path) -> None:
    opencode_home, claude_config = runner.write_prod_mcp_runtime(
        tmp_path,
        token="secret-token",
        http_url="https://${PUBLIC_HOSTNAME}/mcp",
    )

    opencode_config = json.loads((opencode_home / "opencode" / "opencode.json").read_text())
    claude_payload = json.loads(claude_config.read_text())

    assert opencode_home == tmp_path / "xdg"
    prod = opencode_config["mcp"]["brain-researcher-prod"]
    assert prod["type"] == "remote"
    assert prod["url"] == "https://${PUBLIC_HOSTNAME}/mcp"
    assert prod["headers"]["Authorization"] == "Bearer secret-token"
    assert (
        claude_payload["mcpServers"]["brain-researcher-prod"]["headers"]["Authorization"]
        == "Bearer secret-token"
    )


def test_rescore_reparses_stdout_events_before_cached_actions(tmp_path: Path) -> None:
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "stdout.jsonl").write_text(
        json.dumps(
            {
                "type": "tool_call",
                "name": "shell",
                "arguments": {
                    "cmd": (
                        "python - <<'PY'\n"
                        "from brain_researcher.services.tools.execution_recipes import get_execution_recipe\n"
                        "get_execution_recipe(tool_id=\"workflow_qsiprep\")\n"
                        "PY"
                    )
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (episode_dir / "parsed_actions.jsonl").write_text(
        json.dumps(
            {
                "action_type": "bash_cmd",
                "target": "stale cached action",
                "task_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    actions = rescorer._actions_for_episode(episode_dir)

    assert any(
        action["action_type"] == "recipe_tool" and action["target"] == "workflow_qsiprep"
        for action in actions
    )
    assert all(action["target"] != "stale cached action" for action in actions)


def test_rescore_synthesizes_missing_run_summary_from_episodes(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    task_rows = [
        {
            "task_id": "T1",
            "query": "Select dataset resource route",
            "category": "Data",
            "required_capabilities": ["dataset_access"],
            "acceptable_patterns": [
                {
                    "capability": "dataset_access",
                    "action_type": "mcp_tool",
                    "pattern": "dataset_get_resources",
                    "match": "exact",
                }
            ],
            "neutral_patterns": [],
            "disqualifying_patterns": [],
            "canonical_br_tools": ["dataset_get_resources"],
        },
        {
            "task_id": "T2",
            "query": "Second task, intentionally not recorded",
            "category": "Data",
            "required_capabilities": ["dataset_access"],
            "acceptable_patterns": [],
            "neutral_patterns": [],
            "disqualifying_patterns": [],
            "canonical_br_tools": [],
        },
    ]
    tasks_jsonl.write_text(
        "".join(json.dumps(row) + "\n" for row in task_rows),
        encoding="utf-8",
    )
    episode_dir = tmp_path / "run" / "episodes" / "opencode_gemini_pro_with_br" / "T1"
    episode_dir.mkdir(parents=True)
    (episode_dir / "record.json").write_text(
        json.dumps(
            {
                "condition_id": "opencode_gemini_pro_with_br",
                "task_id": "T1",
                "status": "succeeded",
                "wall_time_s": 1.0,
                "parsed_action_count": 1,
            }
        ),
        encoding="utf-8",
    )
    action = {
        "index": 1,
        "action_type": "mcp_tool",
        "target": "dataset_get_resources",
        "task_id": None,
    }
    (episode_dir / "stdout.jsonl").write_text(
        json.dumps({"type": "function_call", "name": "dataset_get_resources"}) + "\n",
        encoding="utf-8",
    )
    (episode_dir / "parsed_actions.jsonl").write_text(
        json.dumps(action) + "\n",
        encoding="utf-8",
    )

    payload = rescorer.rescore_run(
        tmp_path / "run",
        tasks_jsonl,
        "score_rows_rescored_stdout_parser_v2.jsonl",
    )
    synthetic = json.loads((tmp_path / "run" / "run_summary.json").read_text())

    assert synthetic["synthetic"] is True
    assert synthetic["conditions"] == ["opencode_gemini_pro_with_br"]
    assert synthetic["tasks"] == ["T1", "T2"]
    assert payload["rows"] == 1
    assert payload["audit"]["expected_record_count"] == 2
    assert payload["audit"]["observed_record_count"] == 1
    assert payload["audit"]["complete_execution_matrix"] is False
    assert payload["audit"]["missing_condition_task_pairs"] == [
        "opencode_gemini_pro_with_br/T2"
    ]
