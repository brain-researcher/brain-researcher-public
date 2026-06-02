#!/usr/bin/env python3
"""Run a real-trace tool-selection pilot for coding-agent CLIs.

The capability scorer is intentionally separate from this runner. This script
only launches agent CLIs, captures their streamed JSON traces, stops after the
first few parsed actions, and writes score rows using the existing capability
templates.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.tool_selection_capability_pilot import (  # noqa: E402
    DEFAULT_PILOT_DIR,
    DEFAULT_TASKS,
    count_non_neutral_task_actions,
    load_tasks,
    parse_events,
    score_task,
    summarize_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = DEFAULT_PILOT_DIR / "real_trace_runs"
DEFAULT_RUN_NAME = "real_trace_pilot_10task_2system_2condition"
DEFAULT_CLAUDE_MCP_CONFIG = REPO_ROOT / ".mcp.json"
BR_MODE_WITH = "with_br_mcp"
BR_MODE_WITHOUT = "without_br"
# When True, +BR prompts omit the gold-route hint block and the "fall back to local
# route target" instruction. Used for the symmetric (leak-free) ablation rerun.
LEAK_FREE_BR_HINTS = False
BR_MCP_SURFACE_LOCAL = "local"
BR_MCP_SURFACE_PROD = "prod"
DEFAULT_BR_MCP_SURFACE = BR_MCP_SURFACE_PROD
DEFAULT_BR_MCP_HTTP_URL = "https://brain-researcher.com/mcp"
STOP_AFTER_ACTIONS = 3
OPENCODE_MCP_MISSING_STATUS = "skipped_missing_opencode_br_mcp"
PROD_MCP_MISSING_TOKEN_STATUS = "skipped_missing_br_mcp_token_for_prod"


@dataclass(frozen=True)
class Condition:
    condition_id: str
    runner: str
    model: str
    br_mode: str


DEFAULT_CONDITIONS = (
    Condition("codex_cli_gpt55_without_br", "codex", "gpt-5.5", BR_MODE_WITHOUT),
    Condition("codex_cli_gpt55_with_br", "codex", "gpt-5.5", BR_MODE_WITH),
    Condition("claude_code_opus47_without_br", "claude", "opus", BR_MODE_WITHOUT),
    Condition("claude_code_opus47_with_br", "claude", "opus", BR_MODE_WITH),
    Condition(
        "opencode_gemini_pro_without_br",
        "opencode",
        "google/gemini-3.1-pro-preview",
        BR_MODE_WITHOUT,
    ),
    Condition(
        "opencode_gemini_pro_with_br",
        "opencode",
        "google/gemini-3.1-pro-preview",
        BR_MODE_WITH,
    ),
    Condition(
        "opencode_glm51_without_br",
        "opencode",
        "zai-coding-plan/glm-5.1",
        BR_MODE_WITHOUT,
    ),
    Condition(
        "opencode_glm51_with_br",
        "opencode",
        "zai-coding-plan/glm-5.1",
        BR_MODE_WITH,
    ),
    Condition(
        "opencode_kimi_k25_without_br",
        "opencode",
        "opencode/kimi-k2.5",
        BR_MODE_WITHOUT,
    ),
    Condition(
        "opencode_kimi_k25_with_br",
        "opencode",
        "opencode/kimi-k2.5",
        BR_MODE_WITH,
    ),
    Condition(
        "opencode_qwen36_plus_without_br",
        "opencode",
        "opencode/qwen3.6-plus",
        BR_MODE_WITHOUT,
    ),
    Condition(
        "opencode_qwen36_plus_with_br",
        "opencode",
        "opencode/qwen3.6-plus",
        BR_MODE_WITH,
    ),
    Condition(
        "opencode_deepseek_v4_pro_without_br",
        "opencode",
        "deepseek/deepseek-v4-pro",
        BR_MODE_WITHOUT,
    ),
    Condition(
        "opencode_deepseek_v4_pro_with_br",
        "opencode",
        "deepseek/deepseek-v4-pro",
        BR_MODE_WITH,
    ),
)


TASK_ROUTE_HINTS: dict[str, tuple[str, ...]] = {
    "DATA-001": (
        "dataset_get_resources for the Haxby/OpenNeuro dataset route",
        "a BIDS validation route such as validate_bids_structure, pybids.BIDSLayout(validate=True), or bids-validator",
    ),
    "PREP-001": (
        "fMRIPrep for BIDS fMRI preprocessing",
        "FreeSurfer recon-all/surface output via fMRIPrep surface options",
    ),
    "QC-001": (
        "MRIQC or equivalent image-quality metric extraction",
        "a QC report/artifact route such as MRIQC reports or explicit QC summary outputs",
    ),
    "STAT-001": (
        "nilearn FirstLevelModel or an equivalent first-level GLM API",
        "HRF/design-matrix construction",
        "contrast estimation via compute_contrast or equivalent",
    ),
    "CONN-001": (
        "atlas/ROI timeseries extraction such as NiftiMapsMasker/NiftiLabelsMasker",
        "confound cleaning/regression",
        "connectivity extraction such as ConnectivityMeasure",
    ),
    "ML-001": (
        "ROI or mask-based feature extraction",
        "a supervised decoder/classifier route",
        "cross-validation through sklearn/nilearn rather than a single fit",
    ),
    "META-001": (
        "study search or corpus selection for coordinate studies",
        "coordinate meta-analysis such as NiMARE ALE",
    ),
    "STATINF-001": (
        "permutation inference such as randomise, permuted_ols, or permutation_test_score",
        "multiple-comparison control such as TFCE/FWE/FDR/max-stat correction",
    ),
    "HARM-001": (
        "site harmonization such as neuroCombat/neuroHarmonize/ComBat",
        "site-effect diagnostics before or after harmonization",
    ),
    "SPEC-001": (
        "multi-echo denoising such as tedana",
        "confound cleaning/regression after denoising",
    ),
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def condition_by_id() -> dict[str, Condition]:
    return {condition.condition_id: condition for condition in DEFAULT_CONDITIONS}


def task_route_hint_block(task: Mapping[str, Any]) -> str:
    if LEAK_FREE_BR_HINTS:
        return ""
    task_id = str(task.get("task_id") or "")
    task_hints = task.get("route_hints")
    if isinstance(task_hints, list):
        hints = tuple(str(item).strip() for item in task_hints if str(item).strip())
    else:
        hints = TASK_ROUTE_HINTS.get(task_id, ())
    if not hints:
        return ""
    rendered = "\n".join(f"- {hint}" for hint in hints)
    return f"""Task-specific concrete route targets:
{rendered}
"""


def br_instruction_for_task(task: Mapping[str, Any], condition: Condition) -> str:
    hints = task_route_hint_block(task)
    if condition.condition_id == "codex_cli_gpt55_with_br":
        return f"""BR MCP/tools are enabled and mandatory for this Codex condition.

Use actual MCP tool calls. Do not satisfy this condition with shell `br` commands,
Python imports, printed JSON route dictionaries, markdown snippets, or plain-text
mentions of `get_execution_recipe(...)`.

Required Codex +BR routing contract:
1. First call the real BR MCP `plan_preflight` tool with `selection_mode=true`
   and a query that includes the task id plus required capabilities.
2. Then call one concrete MCP route from `recommended_next_calls`, such as
   `get_execution_recipe(tool_id=...)`, `dataset_get_resources`, or another
   task-specific BR route tool.
3. If BR does not return a concrete next call, stop and report
   `BR_UNROUTABLE_FOR_TASK`; do not fall back to a local route target.

Do not call generic BR `tool_search` as an early action. The task-specific
targets below are only hints for the BR query and route choice; they are not
substitutes for direct MCP calls.

Do not stop after `plan_preflight`; the scorer needs the concrete BR route that
follows it.

{hints.rstrip()}
"""
    return f"""BR MCP/tools are enabled, but generic discovery is not a valid first action.

Use exactly this BR routing pattern:
1. If you use BR, call `plan_preflight` directly with `selection_mode=true` and a
   query that includes the task id plus required capabilities.
2. Then make one concrete route-selection action from `recommended_next_calls`,
   `dataset_get_resources`, `get_execution_recipe(tool_id=...)`, or a local
   scientific API/command that covers the capabilities below.
3. If BR returns generic advice or no concrete next call, stop and report
   `BR_UNROUTABLE_FOR_TASK`; do not fall back to a local route target.

Do not call Claude `ToolSearch` as an early action.
Do not call generic BR `tool_search` as an early action.
Do not stop after `plan_preflight`; the scorer needs the concrete route that
follows it.

{hints.rstrip()}
"""


def build_prompt(task: Mapping[str, Any], condition: Condition) -> str:
    task_id = str(task.get("task_id") or "")
    strict_codex_br = condition.condition_id == "codex_cli_gpt55_with_br"
    br_instruction = (
        br_instruction_for_task(task, condition)
        if condition.br_mode == BR_MODE_WITH
        else "BR MCP/tools are disabled. Do not call Brain Researcher or BRKG MCP tools."
    )
    route_instruction = (
        "- Use direct BR MCP calls only. Shell `br`, Python wrappers, printed route "
        "strings, and local scientific API calls do not satisfy this strict +BR condition."
        if strict_codex_br
        else (
            "- Use BR MCP calls or local library/API calls that directly select the\n"
            "  scientific route. If BR returns recommended_next_calls, make one of those\n"
            "  concrete calls next."
        )
    )
    fallback_instruction = (
        "- If BR does not provide a concrete route, stop and report `BR_UNROUTABLE_FOR_TASK`; do not use a local fallback."
        if strict_codex_br
        else (
            "- If the first BR call does not provide a concrete route, immediately emit the\n"
            "  local route from the task-specific target list above."
        )
    )
    with_br_action_instruction = (
        "- with BR: direct BR MCP `plan_preflight(selection_mode=true)` followed by a direct concrete BR route call."
        if strict_codex_br
        else (
            "- with BR: a BR MCP lookup/call when useful, followed by the concrete local or\n"
            "  BR-selected tool direction if needed."
        )
    )
    return f"""You are in a non-executing tool-selection benchmark.

Task id: {task_id}
Category: {task.get("category")}
Task: {task.get("query")}

Goal: expose the first actions you would take to route this task to the right
scientific toolchain. Do not complete the workflow, do not download datasets,
do not run heavy neuroimaging jobs, and do not write benchmark answers by hand.

{br_instruction}

Scoring contract:
- The benchmark scores concrete route/tool selection, not environment discovery.
- Do not run repo searches, package probes, version/help checks, or generic
  environment checks.
- Non-scoring examples: rg/find/ls/grep/fd/which/command -v/pip show/
  importlib.util.find_spec/--version/--help.
{route_instruction}
- For BR `plan_preflight`, pass `selection_mode=true` when available so BR
  returns route-selection next calls instead of execution diagnostics.
- In BR-on runs, do not spend early actions on generic discovery tools such as
  Claude `ToolSearch`, BR `tool_search`, repo search, or package probing.
{fallback_instruction}

Use at most three non-neutral tool-selection actions. Prefer concrete early actions:
- without BR: a shell command or short Python import/call showing the local
  library or command family you would use;
{with_br_action_instruction}

The harness will stop after it observes the first three non-neutral parsed
actions, so keep the first actions task-relevant.
"""


def empty_mcp_config(run_dir: Path) -> Path:
    path = run_dir / "empty_mcp.json"
    write_json(path, {"mcpServers": {}})
    return path


def load_episode_env_base() -> dict[str, str]:
    env = os.environ.copy()
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key or key in env:
                continue
            value = value.strip().strip("'\"")
            env[key] = value
    return env


def write_prod_mcp_runtime(
    runtime_dir: Path,
    *,
    token: str,
    http_url: str,
) -> tuple[Path, Path]:
    """Write temporary prod MCP configs for OpenCode and Claude.

    The generated files contain a bearer token. Keep ``runtime_dir`` outside the
    repo and run artifact tree, and let the caller clean it up.
    """

    opencode_config_dir = runtime_dir / "xdg" / "opencode"
    opencode_config_dir.mkdir(parents=True, exist_ok=True)
    opencode_config_home = opencode_config_dir.parent
    write_json(
        opencode_config_dir / "opencode.json",
        {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "brain-researcher-prod": {
                    "type": "remote",
                    "url": http_url,
                    "headers": {
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json, text/event-stream",
                    },
                    "enabled": True,
                    "timeout": 30000,
                }
            },
        },
    )

    claude_mcp_config = runtime_dir / "claude.prod.mcp.json"
    write_json(
        claude_mcp_config,
        {
            "mcpServers": {
                "brain-researcher-prod": {
                    "type": "http",
                    "url": http_url,
                    "headers": {
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json, text/event-stream",
                    },
                }
            }
        },
    )
    return opencode_config_home, claude_mcp_config


def opencode_has_mcp(opencode_bin: str, env: Mapping[str, str] | None = None) -> bool:
    if shutil.which(opencode_bin) is None:
        return False
    try:
        result = subprocess.run(
            [opencode_bin, "mcp", "list"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            env=dict(env) if env is not None else None,
        )
    except Exception:
        return False
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "no mcp servers configured" not in combined


def build_command(
    *,
    condition: Condition,
    prompt: str,
    run_dir: Path,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    claude_mcp_config: Path,
    allow_opencode_with_br: bool,
    br_mcp_surface: str,
    prod_claude_mcp_config: Path | None = None,
    opencode_prod_config_home: Path | None = None,
    prod_mcp_skip_reason: str | None = None,
) -> tuple[list[str], str | None, str | None]:
    if condition.runner == "codex":
        if shutil.which(codex_bin) is None:
            return [], None, f"missing_binary:{codex_bin}"
        br_enabled = "true" if condition.br_mode == BR_MODE_WITH else "false"
        return (
            [
                codex_bin,
                "--ask-for-approval",
                "never",
                "-c",
                f"mcp_servers.brain-researcher-prod.enabled={br_enabled}",
                "-m",
                condition.model,
                "exec",
                "--cd",
                str(REPO_ROOT),
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--json",
                "-",
            ],
            prompt,
            None,
        )

    if condition.runner == "claude":
        if shutil.which(claude_bin) is None:
            return [], None, f"missing_binary:{claude_bin}"
        if condition.br_mode == BR_MODE_WITH and br_mcp_surface == BR_MCP_SURFACE_PROD:
            if prod_mcp_skip_reason:
                return [], None, prod_mcp_skip_reason
            if prod_claude_mcp_config is None:
                return [], None, "missing_prod_claude_mcp_config"
            mcp_config = prod_claude_mcp_config
        else:
            mcp_config = (
                claude_mcp_config
                if condition.br_mode == BR_MODE_WITH
                else empty_mcp_config(run_dir)
            )
        if condition.br_mode == BR_MODE_WITH and not mcp_config.exists():
            return [], None, f"missing_claude_mcp_config:{mcp_config}"
        return (
            [
                claude_bin,
                "-p",
                "--model",
                condition.model,
                "--permission-mode",
                "bypassPermissions",
                "--disallowedTools",
                (
                    "ToolSearch,"
                    "mcp__brain-researcher-local__tool_search,"
                    "mcp__brain_researcher_local__tool_search,"
                    "mcp__brain-researcher-prod__tool_search,"
                    "mcp__brain_researcher_prod__tool_search"
                ),
                "--output-format",
                "stream-json",
                "--verbose",
                "--add-dir",
                str(REPO_ROOT),
                "--mcp-config",
                str(mcp_config),
                "--strict-mcp-config",
                prompt,
            ],
            None,
            None,
        )

    if condition.runner == "opencode":
        if shutil.which(opencode_bin) is None:
            return [], None, f"missing_binary:{opencode_bin}"
        opencode_mcp_env = None
        if condition.br_mode == BR_MODE_WITH and br_mcp_surface == BR_MCP_SURFACE_PROD:
            if prod_mcp_skip_reason:
                return [], None, prod_mcp_skip_reason
            if opencode_prod_config_home is None:
                return [], None, "missing_opencode_prod_config_home"
            opencode_mcp_env = load_episode_env_base()
            opencode_mcp_env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
            opencode_mcp_env["XDG_CONFIG_HOME"] = str(opencode_prod_config_home)
        if (
            condition.br_mode == BR_MODE_WITH
            and not allow_opencode_with_br
            and not opencode_has_mcp(opencode_bin, env=opencode_mcp_env)
        ):
            return [], None, OPENCODE_MCP_MISSING_STATUS
        return (
            [
                opencode_bin,
                "run",
                "--dir",
                str(REPO_ROOT),
                "--model",
                condition.model,
                "--format",
                "json",
                "--dangerously-skip-permissions",
                prompt,
            ],
            None,
            None,
        )

    return [], None, f"unsupported_runner:{condition.runner}"


def episode_env(
    condition: Condition,
    *,
    br_mcp_surface: str = BR_MCP_SURFACE_LOCAL,
    opencode_prod_config_home: Path | None = None,
) -> dict[str, str]:
    env = load_episode_env_base()
    if condition.runner == "opencode" and condition.br_mode != BR_MODE_WITH:
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    if (
        condition.runner == "opencode"
        and condition.br_mode == BR_MODE_WITH
        and br_mcp_surface == BR_MCP_SURFACE_PROD
        and opencode_prod_config_home is not None
    ):
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
        env["XDG_CONFIG_HOME"] = str(opencode_prod_config_home)
    return env


def _reader_thread(stream: Any, stream_name: str, out: queue.Queue[tuple[str, str]]) -> None:
    try:
        for line in iter(stream.readline, ""):
            out.put((stream_name, line))
    finally:
        out.put((stream_name, ""))


def _json_events_from_lines(lines: Sequence[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _has_json_error_event(lines: Sequence[str]) -> bool:
    for event in _json_events_from_lines(lines):
        if event.get("type") == "error" or event.get("error"):
            return True
    return False


def episode_actions(episode_dir: Path) -> list[dict[str, Any]]:
    lines: list[str] = []
    for filename in ("stdout.jsonl", "stderr.txt"):
        path = episode_dir / filename
        if path.exists():
            lines.extend(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    events = _json_events_from_lines(lines)
    if events:
        return parse_events(events)
    parsed_actions = episode_dir / "parsed_actions.jsonl"
    if parsed_actions.exists():
        return read_jsonl(parsed_actions)
    return []


def _non_neutral_action_count(
    actions: Sequence[Mapping[str, Any]],
    task: Mapping[str, Any],
) -> int:
    return count_non_neutral_task_actions(task, actions)


def _raw_relevant_action_count(actions: Sequence[Mapping[str, Any]], task_id: str) -> int:
    return sum(
        1
        for action in actions
        if action.get("task_id") in {None, task_id}
        and str(action.get("target") or "").strip()
    )


def run_episode(
    *,
    condition: Condition,
    task: Mapping[str, Any],
    episode_dir: Path,
    command: Sequence[str],
    stdin_text: str | None,
    timeout_s: int,
    stop_after_actions: int,
    dry_run: bool,
    skip_reason: str | None,
    br_mcp_surface: str,
    opencode_prod_config_home: Path | None,
) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    prompt = build_prompt(task, condition)
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(
        episode_dir / "command.json",
        {
            "condition_id": condition.condition_id,
            "runner": condition.runner,
            "model": condition.model,
            "br_mode": condition.br_mode,
            "br_mcp_surface": br_mcp_surface,
            "task_id": task_id,
            "command": list(command),
            "dry_run": dry_run,
            "skip_reason": skip_reason,
        },
    )

    record: dict[str, Any] = {
        "condition_id": condition.condition_id,
        "runner": condition.runner,
        "model": condition.model,
        "br_mode": condition.br_mode,
        "br_mcp_surface": br_mcp_surface,
        "task_id": task_id,
        "started_at": utc_now(),
        "dry_run": dry_run,
        "skip_reason": skip_reason,
        "status": "dry_run" if dry_run else "pending",
    }
    if dry_run or skip_reason:
        if skip_reason:
            record["status"] = "skipped"
        write_json(episode_dir / "record.json", record)
        return record

    q: queue.Queue[tuple[str, str]] = queue.Queue()
    proc = subprocess.Popen(
        list(command),
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=episode_env(
            condition,
            br_mcp_surface=br_mcp_surface,
            opencode_prod_config_home=opencode_prod_config_home,
        ),
        bufsize=1,
    )
    if stdin_text is not None and proc.stdin is not None:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    assert proc.stdout is not None
    assert proc.stderr is not None
    threads = [
        threading.Thread(target=_reader_thread, args=(proc.stdout, "stdout", q), daemon=True),
        threading.Thread(target=_reader_thread, args=(proc.stderr, "stderr", q), daemon=True),
    ]
    for thread in threads:
        thread.start()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stopped_after_actions = False
    start = time.monotonic()
    while True:
        if time.monotonic() - start > timeout_s:
            proc.kill()
            record["status"] = "timed_out"
            break
        try:
            stream_name, line = q.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is not None and q.empty():
                break
            continue
        if line:
            if stream_name == "stdout":
                stdout_lines.append(line)
            else:
                stderr_lines.append(line)
            events = _json_events_from_lines(stdout_lines + stderr_lines)
            actions = parse_events(events)
            if _non_neutral_action_count(actions, task) >= stop_after_actions:
                stopped_after_actions = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                record["status"] = "captured_stop"
                break
        if proc.poll() is not None and q.empty():
            break

    for thread in threads:
        thread.join(timeout=1)
    returncode = proc.poll()
    if "status" not in record or record["status"] == "pending":
        record["status"] = "succeeded" if returncode == 0 else "failed"
    (episode_dir / "stdout.jsonl").write_text("".join(stdout_lines), encoding="utf-8")
    (episode_dir / "stderr.txt").write_text("".join(stderr_lines), encoding="utf-8")
    events = _json_events_from_lines(stdout_lines + stderr_lines)
    actions = parse_events(events)
    json_error_event = _has_json_error_event(stdout_lines + stderr_lines)
    if record["status"] == "succeeded" and json_error_event:
        record["status"] = "failed"
    write_jsonl(episode_dir / "parsed_actions.jsonl", actions)
    record.update(
        {
            "ended_at": utc_now(),
            "returncode": returncode,
            "json_error_event": json_error_event,
            "wall_time_s": round(time.monotonic() - start, 3),
            "stopped_after_actions": stopped_after_actions,
            "parsed_action_count": len(actions),
            "relevant_action_count": _raw_relevant_action_count(actions, task_id),
            "non_neutral_action_count": _non_neutral_action_count(actions, task),
        }
    )
    write_json(episode_dir / "record.json", record)
    return record


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    global LEAK_FREE_BR_HINTS
    LEAK_FREE_BR_HINTS = bool(getattr(args, "leak_free_br", False))
    tasks = load_tasks(args.tasks_jsonl)
    if args.task:
        wanted_tasks = set(args.task)
        tasks = [task for task in tasks if task.get("task_id") in wanted_tasks]
    if args.limit_tasks is not None:
        tasks = tasks[: args.limit_tasks]
    conditions = list(DEFAULT_CONDITIONS)
    if args.condition:
        wanted_conditions = set(args.condition)
        conditions = [
            condition for condition in conditions if condition.condition_id in wanted_conditions
        ]
    if not tasks:
        raise SystemExit("No matching tasks.")
    if not conditions:
        raise SystemExit("No matching conditions.")

    run_dir = args.output_root / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    prod_temp: tempfile.TemporaryDirectory[str] | None = None
    opencode_prod_config_home: Path | None = None
    prod_claude_mcp_config: Path | None = None
    prod_mcp_skip_reason: str | None = None
    needs_prod_runtime = (
        args.br_mcp_surface == BR_MCP_SURFACE_PROD
        and any(
            condition.br_mode == BR_MODE_WITH and condition.runner in {"claude", "opencode"}
            for condition in conditions
        )
    )
    if needs_prod_runtime:
        env = load_episode_env_base()
        token = env.get("BR_MCP_TOKEN")
        if token:
            prod_temp = tempfile.TemporaryDirectory(prefix="br-prod-mcp-")
            opencode_prod_config_home, prod_claude_mcp_config = write_prod_mcp_runtime(
                Path(prod_temp.name),
                token=token,
                http_url=args.br_mcp_http_url,
            )
        else:
            prod_mcp_skip_reason = PROD_MCP_MISSING_TOKEN_STATUS
    try:
        for condition in conditions:
            for task in tasks:
                episode_dir = run_dir / "episodes" / condition.condition_id / str(task["task_id"])
                record_path = episode_dir / "record.json"
                if getattr(args, "skip_existing_records", False) and record_path.exists():
                    record = read_json(record_path)
                    records.append(record)
                    actions = episode_actions(episode_dir)
                    if record.get("status") not in {"dry_run", "skipped"}:
                        rows.append(
                            score_task(
                                task,
                                actions,
                                condition=condition.condition_id,
                                max_actions=args.stop_after_actions,
                            )
                        )
                    continue
                prompt = build_prompt(task, condition)
                command, stdin_text, skip_reason = build_command(
                    condition=condition,
                    prompt=prompt,
                    run_dir=run_dir,
                    codex_bin=args.codex_bin,
                    claude_bin=args.claude_bin,
                    opencode_bin=args.opencode_bin,
                    claude_mcp_config=args.claude_mcp_config,
                    allow_opencode_with_br=args.allow_opencode_with_br_without_mcp,
                    br_mcp_surface=args.br_mcp_surface,
                    prod_claude_mcp_config=prod_claude_mcp_config,
                    opencode_prod_config_home=opencode_prod_config_home,
                    prod_mcp_skip_reason=prod_mcp_skip_reason,
                )
                record = run_episode(
                    condition=condition,
                    task=task,
                    episode_dir=episode_dir,
                    command=command,
                    stdin_text=stdin_text,
                    timeout_s=args.timeout_s,
                    stop_after_actions=args.stop_after_actions,
                    dry_run=not args.execute,
                    skip_reason=skip_reason,
                    br_mcp_surface=args.br_mcp_surface,
                    opencode_prod_config_home=opencode_prod_config_home,
                )
                records.append(record)
                actions = episode_actions(episode_dir)
                if record.get("status") not in {"dry_run", "skipped"}:
                    rows.append(
                        score_task(
                            task,
                            actions,
                            condition=condition.condition_id,
                            max_actions=args.stop_after_actions,
                        )
                    )
    finally:
        if prod_temp is not None:
            prod_temp.cleanup()

    summary = summarize_rows(rows)
    payload = {
        "schema_version": "br.tool_selection_real_trace_pilot.v1",
        "run_dir": str(run_dir),
        "created_at": utc_now(),
        "dry_run": not args.execute,
        "execute": args.execute,
        "br_mcp_surface": args.br_mcp_surface,
        "br_mcp_http_url": args.br_mcp_http_url if args.br_mcp_surface == BR_MCP_SURFACE_PROD else None,
        "n_tasks": len(tasks),
        "n_conditions": len(conditions),
        "stop_after_actions": args.stop_after_actions,
        "tasks": [task.get("task_id") for task in tasks],
        "conditions": [condition.condition_id for condition in conditions],
        "records": records,
        "summary": summary,
        "scale_readiness": {
            "decision": (
                "ready_for_manual_real_trace_adjudication"
                if args.execute and rows
                else "materialized_only_not_scale_ready"
            ),
            "reason": (
                "Real traces were captured and scored; manually adjudicate parser FP/FN before scaling."
                if args.execute and rows
                else "Runner prompts/commands were materialized but no real traces were executed."
            ),
        },
    }
    write_json(run_dir / "run_summary.json", payload)
    if rows:
        write_jsonl(run_dir / "score_rows.jsonl", rows)
    print(json.dumps(payload["scale_readiness"], indent=2, sort_keys=True))
    if rows:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-jsonl", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--limit-tasks", type=int)
    parser.add_argument("--stop-after-actions", type=int, default=STOP_AFTER_ACTIONS)
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--skip-existing-records",
        action="store_true",
        help=(
            "Reuse existing episodes/<condition>/<task>/record.json rows and rescore "
            "their frozen stdout/actions instead of rerunning them."
        ),
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--claude-mcp-config", type=Path, default=DEFAULT_CLAUDE_MCP_CONFIG)
    parser.add_argument(
        "--br-mcp-surface",
        choices=[BR_MCP_SURFACE_PROD, BR_MCP_SURFACE_LOCAL],
        default=DEFAULT_BR_MCP_SURFACE,
        help=(
            "BR MCP surface for with_br rows. prod creates temporary HTTP MCP "
            "configs from BR_MCP_TOKEN; local uses repo-local MCP config."
        ),
    )
    parser.add_argument(
        "--br-mcp-http-url",
        default=os.getenv("BR_MCP_HTTP_URL", DEFAULT_BR_MCP_HTTP_URL),
        help="Hosted BR MCP URL used when --br-mcp-surface=prod.",
    )
    parser.add_argument(
        "--allow-opencode-with-br-without-mcp",
        action="store_true",
        help="Run OpenCode with_br rows even if `opencode mcp list` reports no configured MCP server.",
    )
    parser.add_argument(
        "--leak-free-br",
        action="store_true",
        help=(
            "Symmetric ablation: drop the gold-route hint block and the local-fallback "
            "instruction from +BR prompts. Use for the leakage-control rerun."
        ),
    )
    return parser.parse_args()


def main() -> int:
    run_matrix(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
