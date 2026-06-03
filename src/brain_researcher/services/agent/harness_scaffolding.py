"""Scaffold draft HARNESS tasks from recurring autoresearch incidents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised in tests
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from brain_researcher.services.agent.autoresearch import (
    DEFAULT_BENCHMARK_ROOT,
    HARBOR_INDEX_PRIORITY,
    MOTIF_FAMILIES,
    load_failure_motifs,
)

DEFAULT_OUTPUT_DIR = "/task/output"
_TASK_ID_RE = re.compile(r"^HARNESS-\d{3}$")

_FAMILY_DEFAULTS: dict[str, dict[str, Any]] = {
    "trace_or_bundle_corruption": {
        "title": "TODO: Define trace or bundle corruption invariant",
        "expected_capability_list": ["trace_bundle_integrity_contracts"],
        "acceptance_metrics_list": ["trace_or_bundle_corruption_explicit"],
        "tags": ["harness", "mcp", "trace", "bundle-integrity", "scaffold"],
    },
    "runtime_stall_or_incomplete_bundle": {
        "title": "TODO: Define runtime stall or incomplete bundle invariant",
        "expected_capability_list": ["runtime_terminalization_contracts"],
        "acceptance_metrics_list": ["runtime_stall_explicit"],
        "tags": ["harness", "mcp", "runtime", "terminalization", "scaffold"],
    },
    "preflight_contract_failure": {
        "title": "TODO: Define preflight contract invariant",
        "expected_capability_list": ["preflight_contracts"],
        "acceptance_metrics_list": ["preflight_contract_explicit"],
        "tags": ["harness", "mcp", "preflight", "contracts", "scaffold"],
    },
    "tool_param_fill_failure": {
        "title": "TODO: Define tool parameter fill invariant",
        "expected_capability_list": ["tool_param_contracts"],
        "acceptance_metrics_list": ["tool_param_fill_explicit"],
        "tags": ["harness", "mcp", "params", "contracts", "scaffold"],
    },
    "workflow_discoverability_mismatch": {
        "title": "TODO: Define workflow discoverability invariant",
        "expected_capability_list": ["workflow_discoverability_contracts"],
        "acceptance_metrics_list": ["workflow_discoverability_explicit"],
        "tags": ["harness", "mcp", "workflow-routing", "discoverability", "scaffold"],
    },
    "artifact_contract_miss": {
        "title": "TODO: Define artifact contract completeness invariant",
        "expected_capability_list": ["artifact_contracts"],
        "acceptance_metrics_list": ["artifact_contract_explicit"],
        "tags": ["harness", "mcp", "artifacts", "contracts", "scaffold"],
    },
    "step_skipped_without_useful_result": {
        "title": "TODO: Define skipped-step usefulness invariant",
        "expected_capability_list": ["skipped_step_usefulness_contracts"],
        "acceptance_metrics_list": ["skipped_step_usefulness_explicit"],
        "tags": ["harness", "mcp", "skipped-step", "contracts", "scaffold"],
    },
    "tool_execution_failure": {
        "title": "TODO: Define tool execution failure invariant",
        "expected_capability_list": ["tool_execution_failure_contracts"],
        "acceptance_metrics_list": ["tool_execution_failure_explicit"],
        "tags": ["harness", "mcp", "tool-execution", "failed-step", "scaffold"],
    },
    "wrong_tool_or_workflow_routing": {
        "title": "TODO: Define wrong tool or workflow routing invariant",
        "expected_capability_list": ["routing_rejection_contracts"],
        "acceptance_metrics_list": ["wrong_route_explicit"],
        "tags": ["harness", "mcp", "tool-routing", "workflow-routing", "scaffold"],
    },
}


@dataclass
class HarnessScaffoldResult:
    """Result of scaffolding a draft or active HARNESS task."""

    task_id: str
    motif_family: str
    title: str
    profile: str
    benchmark_root: str
    task_root: str
    activation_mode: str
    created_paths: list[str] = field(default_factory=list)
    updated_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to scaffold HARNESS tasks")
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping at {path}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to scaffold HARNESS tasks")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _family_defaults(motif_family: str) -> dict[str, Any]:
    normalized = _slug(motif_family)
    defaults = dict(_FAMILY_DEFAULTS.get(motif_family) or {})
    defaults.setdefault(
        "title",
        f"TODO: Define {motif_family.replace('_', ' ')} invariant",
    )
    defaults.setdefault("expected_capability_list", [f"{normalized}_contracts"])
    defaults.setdefault("acceptance_metrics_list", [f"{normalized}_explicit"])
    defaults.setdefault("tags", ["harness", "mcp", normalized, "scaffold"])
    defaults["slug"] = normalized
    defaults["profile"] = f"harness_{normalized}_scaffold_v0"
    defaults["placeholder_case_id"] = "TODO_CASE_001"
    return defaults


def _candidate_motif_summary(
    motif_family: str, *, autoresearch_root: Path | None
) -> dict[str, Any]:
    if autoresearch_root is None:
        return {}
    try:
        motifs = load_failure_motifs(autoresearch_root=autoresearch_root)
    except Exception:
        return {}
    for card in motifs:
        if card.motif_family != motif_family:
            continue
        return {
            "motif_id": card.motif_id,
            "severity": card.severity,
            "frequency": card.frequency,
            "suspected_surface": card.suspected_surface,
            "representative_runs": list(card.representative_runs),
            "affected_tools_workflows": list(card.affected_tools_workflows),
        }
    return {}


def _next_harness_task_id(benchmark_root: Path) -> str:
    harbor_root = benchmark_root / "harbor"
    highest = 0
    if harbor_root.exists():
        for child in harbor_root.iterdir():
            match = re.fullmatch(r"HARNESS-(\d{3})", child.name)
            if child.is_dir() and match:
                highest = max(highest, int(match.group(1)))
    return f"HARNESS-{highest + 1:03d}"


def _task_card_regression_name(task_id: str, motif_family: str) -> str:
    return (
        f"test_build_task_card_prefers_real_harbor_entry_for_"
        f"{_slug(motif_family)}_harness_task"
    )


def _task_scaffold_templates(
    *,
    task_id: str,
    motif_family: str,
    title: str,
    profile: str,
    source_summary: dict[str, Any],
) -> dict[str, str]:
    family = _family_defaults(motif_family)
    placeholder_case_id = family["placeholder_case_id"]
    summary_hint = ""
    if source_summary:
        summary_hint = (
            f"- Recent incident summary: severity `{source_summary.get('severity')}`, "
            f"frequency `{source_summary.get('frequency')}`, surface "
            f"`{source_summary.get('suspected_surface')}`.\n"
        )

    instruction = f"""Task: {title} ({task_id})

Scope
- This is a Brain Researcher `{motif_family}` HARNESS scaffold.
- Dataset source: `Provided`.
- Dataset identifier: `brain_researcher_mcp_runtime`.
- This scaffold is `draft` until the placeholder probe and verifier are replaced with deterministic real cases.

Goal
- Compress recurrent `{motif_family}` incidents into a native HARNESS probe.
- Replace the placeholder case list with one or more deterministic invariant checks.
{summary_hint}- Ensure the final implementation uses real public MCP or runtime surfaces and fails loudly if the invariant is violated.

Execution Contract
- Use the local `brain_researcher` runtime available in the benchmark environment.
- Replace placeholder setup with deterministic probes before activation.
- Do not activate this task in motif/canary routing until `solve.sh` and `tests/test_outputs.py` are fully implemented.

Output Location
- Write deliverables to `${{OUTPUT_DIR}}`.
- If `OUTPUT_DIR` is unset, default to `{DEFAULT_OUTPUT_DIR}`.

Required Outputs
1. `family_summary.json`
2. `input_manifest.csv`
3. `cases/{placeholder_case_id}/case_summary.json`
4. `cases/{placeholder_case_id}/response.json`

Pass Criteria
- Replace this section with deterministic family-specific pass criteria.

Expected Result
- A correct harness turns `{motif_family}` incidents into explicit machine-readable evidence instead of relying on ad hoc log inspection.
"""

    task_toml = f"""version = "1.0"

[metadata]
task_id = "{task_id}"
title = "{title}"
category = "Workflow"
difficulty = "medium"
dataset_source = "Provided"
dataset_id = "brain_researcher_mcp_runtime"

[verifier]
timeout_sec = 900.0

[agent]
timeout_sec = 900.0

[environment]
build_timeout_sec = 900.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0
allow_internet = false

[verifier.env]

[solution.env]
"""

    dockerfile = """FROM ubuntu:24.04

RUN apt-get update && \\
    apt-get install -y --no-install-recommends \\
      ca-certificates \\
      python3 \\
      python3-pip \\
      python3-venv \\
      curl && \\
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
"""

    solve_sh = f"""#!/bin/bash

set -euo pipefail

echo "HARNESS scaffold {task_id} is not implemented yet." >&2
echo "Replace solution/solve.sh with deterministic probe logic before activation." >&2
exit 2
"""

    test_sh = """#!/bin/bash

set -euo pipefail

apt-get update
apt-get install -y curl

curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh

source $HOME/.local/bin/env

if uvx \\
  --with pytest==8.4.1 \\
  --with pytest-json-ctrf==0.3.5 \\
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA

then
  echo 1 > /logs/verifier/reward.txt
  exit 0
else
  test_exit=$?
  echo 0 > /logs/verifier/reward.txt
  exit $test_exit
fi
"""

    test_outputs = f"""import pytest


def test_harness_scaffold_not_implemented() -> None:
    pytest.fail(
        "HARNESS scaffold {task_id} for {motif_family} is still draft. "
        "Replace solve.sh, semantic_contract.json, and this verifier before activation."
    )
"""

    semantic_contract = {
        "version": "2.0",
        "task_id": task_id,
        "dataset_source": "Provided",
        "dataset_id": "brain_researcher_mcp_runtime",
        "profile": profile,
        "checks": [
            {
                "id": "contract_task_id_matches_task_meta",
                "left": {"source": "input_task_id"},
                "op": "eq_if_present",
                "right": {"literal": task_id},
            },
            {
                "id": "contract_dataset_source_matches_task_meta",
                "left": {"source": "input_task_dataset_source"},
                "op": "eq_if_present",
                "right": {"literal": "Provided"},
            },
            {
                "id": "contract_dataset_id_matches_task_meta",
                "left": {"source": "input_task_dataset_id"},
                "op": "eq_if_present",
                "right": {"literal": "brain_researcher_mcp_runtime"},
            },
        ],
    }

    scaffold_manifest = {
        "task_id": task_id,
        "motif_family": motif_family,
        "title": title,
        "profile": profile,
        "status": "draft_scaffold",
        "created_at": _utc_iso(),
        "source_motif_summary": source_summary,
        "next_steps": [
            "Replace placeholder cases in instruction.md with deterministic invariant probes.",
            "Implement solution/solve.sh using real public MCP or runtime surfaces.",
            "Replace tests/test_outputs.py with a machine-checkable verifier.",
            "Promote scaffold_task_ids -> task_ids only after native probe verification passes.",
        ],
    }

    return {
        "task.toml": task_toml,
        "instruction.md": instruction,
        "environment/Dockerfile": dockerfile,
        "solution/solve.sh": solve_sh,
        "tests/test.sh": test_sh,
        "tests/test_outputs.py": test_outputs,
        "tests/semantic_contract.json": json.dumps(
            semantic_contract,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        "scaffold_manifest.json": json.dumps(
            scaffold_manifest,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    }


def _required_outputs_for_scaffold(motif_family: str) -> list[str]:
    placeholder_case_id = _family_defaults(motif_family)["placeholder_case_id"]
    return [
        "family_summary.json",
        "input_manifest.csv",
        f"cases/{placeholder_case_id}/case_summary.json",
        f"cases/{placeholder_case_id}/response.json",
    ]


def _pass_criteria_for_scaffold(motif_family: str) -> str:
    metrics = _family_defaults(motif_family)["acceptance_metrics_list"]
    return json.dumps(
        {
            "must_exist": _required_outputs_for_scaffold(motif_family),
            "acceptance_metrics": metrics,
            "compare_metric_keys": [
                "artifact_completeness_ratio",
                "policy_issue_count",
                "duration_s",
            ],
            "scaffold_status": "draft",
        },
        indent=2,
    )


def _harbor_entry_for_scaffold(
    *,
    task_id: str,
    motif_family: str,
    title: str,
    profile: str,
    instruction: str,
) -> dict[str, Any]:
    family = _family_defaults(motif_family)
    required_outputs = _required_outputs_for_scaffold(motif_family)
    pass_criteria = _pass_criteria_for_scaffold(motif_family)
    placeholder_case_id = family["placeholder_case_id"]
    solve_sha = sha256(
        (
            f'#!/bin/bash\n\nset -euo pipefail\n\necho "HARNESS scaffold {task_id} is not implemented yet." >&2\n'
            'echo "Replace solution/solve.sh with deterministic probe logic before activation." >&2\n'
            "exit 2\n"
        ).encode()
    ).hexdigest()
    return {
        "id": task_id,
        "title": title,
        "input": {
            "instruction": instruction,
            "dataset_source": "Provided",
            "dataset_id": "brain_researcher_mcp_runtime",
            "task_root": f"harbor/{task_id}",
            "output_dir": DEFAULT_OUTPUT_DIR,
            "required_outputs": required_outputs,
            "time_limit_s": 180,
        },
        "expected_outputs": [
            {"required_outputs": required_outputs},
            {
                "output_schema": {
                    "family_summary.json": {
                        "type": "json",
                        "required_keys": [
                            "task_id",
                            "dataset_source",
                            "dataset_id",
                        ],
                    },
                    "input_manifest.csv": {
                        "type": "csv",
                        "required_columns": [
                            "dataset_id",
                            "case_id",
                            "source_path",
                            "bytes",
                            "sha256",
                            "file_role",
                        ],
                    },
                    f"cases/{placeholder_case_id}/case_summary.json": {
                        "type": "json",
                        "required_keys": ["case_id"],
                    },
                    f"cases/{placeholder_case_id}/response.json": {"type": "json"},
                }
            },
            {"pass_criteria": pass_criteria},
        ],
        "metadata": {
            "source_schema": "task_ops_v2_csv",
            "category": "Workflow",
            "difficulty": "medium",
            "dataset_source": "Provided",
            "dataset_id": "brain_researcher_mcp_runtime",
            "output_dir": DEFAULT_OUTPUT_DIR,
            "verifier_entrypoint": "tests/test_outputs.py",
            "pass_criteria": pass_criteria,
            "expected_results": (
                f"Draft scaffold for {motif_family}. Replace placeholder probes "
                "with deterministic invariant checks before activation."
            ),
            "metric_validation": {
                "scaffold_status": {"expected": "draft"},
            },
            "semantic_contract_version": "2.0",
            "semantic_contract_path": f"harbor/{task_id}/tests/semantic_contract.json",
            "semantic_contract_checks": 3,
            "semantic_contract_profile": profile,
            "gt_solution_embedded": True,
            "gt_visibility": "authenticated",
            "gt_solution_sha256": solve_sha,
            "gt_authenticity_class": "scaffold",
            "gt_solution_created_by": "codex",
            "gt_solution_created_at": _utc_iso()[:10],
            "gt_solution_verified_by": "codex",
            "gt_solution_verified_at": _utc_iso()[:10],
            "gt_solution_verification_method": (
                "draft scaffold only; replace solve.sh + tests/test_outputs.py before activation"
            ),
            "benchmark_origin": "harbor_json",
            "harbor_source_file": HARBOR_INDEX_PRIORITY[0],
            "scaffold_status": "draft",
        },
        "category": "Workflow",
        "difficulty": "medium",
        "source": "BrainResearcherBenchmark - Tooling-Python-V2.csv",
        "tags": list(family["tags"]),
        "created_by": "codex",
    }


def _microtooling_entry_for_scaffold(
    *,
    task_id: str,
    motif_family: str,
    title: str,
) -> dict[str, Any]:
    family = _family_defaults(motif_family)
    required_outputs = _required_outputs_for_scaffold(motif_family)
    return {
        "task_id": task_id,
        "task_category": "Workflow",
        "mode": "Full-Stack",
        "user_prompt": title,
        "input_data_ref": "Local brain_researcher MCP runtime",
        "data_key": (
            "brain_researcher incident compression; replace with the real MCP or runtime "
            "surfaces exercised by this harness family"
        ),
        "context_block": (
            f"Draft scaffold for the {motif_family} incident family. Replace placeholder "
            "cases with deterministic invariant probes before activation."
        ),
        "expected_capability": "; ".join(family["expected_capability_list"]),
        "acceptance_metrics": "; ".join(family["acceptance_metrics_list"]),
        "evidence_required": "; ".join(required_outputs),
        "gold_ref": None,
        "seed": None,
        "time_limit_s": 180,
        "notes": (
            "Draft HARNESS scaffold generated automatically from incident-to-harness "
            "automation. Do not activate until solve.sh and verifier are implemented."
        ),
        "expected_tool_chain": None,
        "expected_capability_list": list(family["expected_capability_list"]),
        "acceptance_metrics_list": list(family["acceptance_metrics_list"]),
        "evidence_required_list": required_outputs,
    }


def _upsert_harbor_registry(
    *,
    benchmark_root: Path,
    task_id: str,
    entry: dict[str, Any],
) -> str:
    path = benchmark_root / "harbor_json" / HARBOR_INDEX_PRIORITY[0]
    payload = _read_json(path)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"Invalid Harbor registry at {path}")
    for idx, task in enumerate(tasks):
        if isinstance(task, dict) and str(task.get("id") or "").strip() == task_id:
            tasks[idx] = entry
            _write_json(path, payload)
            return str(path)
    tasks.append(entry)
    _write_json(path, payload)
    return str(path)


def _upsert_microtooling_registry(
    *,
    benchmark_root: Path,
    task_id: str,
    entry: dict[str, Any],
) -> str:
    path = benchmark_root / "BrainRearcherBenchmark_MicroTooling.json"
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Invalid microtooling registry at {path}")
    for idx, row in enumerate(payload):
        if isinstance(row, dict) and str(row.get("task_id") or "").strip() == task_id:
            payload[idx] = entry
            _write_json(path, payload)
            return str(path)
    payload.append(entry)
    _write_json(path, payload)
    return str(path)


def _update_motif_slice_config(
    *,
    benchmark_root: Path,
    motif_family: str,
    task_id: str,
    activate: bool,
) -> str:
    path = benchmark_root / "configs" / "autoresearch" / "motif_slices.yaml"
    payload = _load_yaml(path)
    motifs = payload.setdefault("motifs", {})
    if not isinstance(motifs, dict):
        raise ValueError(f"Invalid motif slice config at {path}")
    entry = motifs.setdefault(motif_family, {})
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid motif entry for {motif_family}")
    task_key = "task_ids" if activate else "scaffold_task_ids"
    canary_key = "canary_task_ids" if activate else "scaffold_canary_task_ids"
    task_ids = [
        str(item).strip()
        for item in list(entry.get(task_key) or [])
        if str(item).strip()
    ]
    if task_id in task_ids:
        task_ids.remove(task_id)
    entry[task_key] = [task_id, *task_ids]
    canary_ids = [
        str(item).strip()
        for item in list(entry.get(canary_key) or [])
        if str(item).strip()
    ]
    if task_id in canary_ids:
        canary_ids.remove(task_id)
    entry[canary_key] = [task_id, *canary_ids]
    _write_yaml(path, payload)
    return str(path)


def _update_canary_slice_config(
    *,
    benchmark_root: Path,
    task_id: str,
    activate: bool,
) -> str:
    path = benchmark_root / "configs" / "autoresearch" / "canary_slice.yaml"
    payload = _load_yaml(path)
    key = "task_ids" if activate else "scaffold_task_ids"
    task_ids = [
        str(item).strip() for item in list(payload.get(key) or []) if str(item).strip()
    ]
    if task_id in task_ids:
        task_ids.remove(task_id)
    payload[key] = [task_id, *task_ids]
    _write_yaml(path, payload)
    return str(path)


def _ensure_task_card_regression(
    *,
    benchmark_root: Path,
    task_id: str,
    motif_family: str,
    title: str,
    profile: str,
) -> str:
    path = benchmark_root / "tests" / "test_benchmark_task_cards.py"
    text = path.read_text(encoding="utf-8")
    test_name = _task_card_regression_name(task_id, motif_family)
    if f"def {test_name}(" in text:
        return str(path)

    family = _family_defaults(motif_family)
    block = f"""

def {test_name}():
    task = {{
        "task_id": "{task_id}",
        "task_category": "Workflow",
        "mode": "Full-Stack",
        "user_prompt": "{title}",
        "input_data_ref": None,
        "data_key": "brain_researcher incident compression scaffold",
        "context_block": "Draft scaffold for the {motif_family} incident family.",
        "expected_capability_list": {family["expected_capability_list"]!r},
        "acceptance_metrics_list": {family["acceptance_metrics_list"]!r},
        "evidence_required_list": { _required_outputs_for_scaffold(motif_family)!r},
        "expected_tool_chain": None,
        "notes": None,
        "gold_ref": None,
        "seed": None,
        "time_limit_s": 180,
    }}

    card = build_task_card(task, default_time_limit_s=600)

    assert card["id"] == "{task_id}"
    assert card["source"] == "BrainResearcherBenchmark - Tooling-Python-V2.csv"
    assert card["metadata"]["benchmark_origin"] == "harbor_json"
    assert card["metadata"]["harbor_source_file"] == "neuroimage-code-bench.harbor.json"
    assert card["metadata"]["semantic_contract_profile"] == "{profile}"
    assert card["input"]["dataset_id"] == "brain_researcher_mcp_runtime"
    json.dumps(card)
"""
    path.write_text(text.rstrip() + block + "\n", encoding="utf-8")
    return str(path)


def scaffold_harness_task(
    motif_family: str,
    *,
    task_id: str | None = None,
    title: str | None = None,
    benchmark_root: Path | str | None = None,
    autoresearch_root: Path | str | None = None,
    activate: bool = False,
) -> HarnessScaffoldResult:
    """Scaffold a draft or active HARNESS task plus benchmark registrations."""

    motif_family = str(motif_family).strip()
    if not motif_family:
        raise ValueError("motif_family must be non-empty")

    benchmark_root_path = (
        Path(benchmark_root).expanduser().resolve()
        if benchmark_root is not None
        else DEFAULT_BENCHMARK_ROOT
    )
    autoresearch_root_path = (
        Path(autoresearch_root).expanduser().resolve()
        if autoresearch_root is not None
        else None
    )
    family = _family_defaults(motif_family)
    chosen_task_id = (
        task_id.strip().upper()
        if task_id
        else _next_harness_task_id(benchmark_root_path)
    )
    if not _TASK_ID_RE.match(chosen_task_id):
        raise ValueError("task_id must match HARNESS-XXX")
    chosen_title = str(title or family["title"]).strip()
    profile = family["profile"]
    warnings: list[str] = []
    if motif_family not in MOTIF_FAMILIES:
        warnings.append(
            "motif_family is not in the current MOTIF_FAMILIES taxonomy; scaffold will "
            "be created, but repo_repair_context will not count it until the taxonomy is extended."
        )
    source_summary = _candidate_motif_summary(
        motif_family,
        autoresearch_root=autoresearch_root_path,
    )
    if not source_summary:
        warnings.append(
            "No recent persisted failure motif card found for this motif_family."
        )
    if not activate:
        warnings.append(
            "Scaffold was registered in draft fields only. Promote scaffold_task_ids to task_ids after implementing the native probe."
        )

    task_root = benchmark_root_path / "harbor" / chosen_task_id
    templates = _task_scaffold_templates(
        task_id=chosen_task_id,
        motif_family=motif_family,
        title=chosen_title,
        profile=profile,
        source_summary=source_summary,
    )

    created_paths: list[str] = []
    for relpath, content in templates.items():
        path = task_root / relpath
        if not path.exists():
            created_paths.append(str(path))
        _write_text(path, content)
    (task_root / "solution" / "solve.sh").chmod(0o755)
    (task_root / "tests" / "test.sh").chmod(0o755)

    updated_paths = [
        _update_motif_slice_config(
            benchmark_root=benchmark_root_path,
            motif_family=motif_family,
            task_id=chosen_task_id,
            activate=activate,
        ),
        _update_canary_slice_config(
            benchmark_root=benchmark_root_path,
            task_id=chosen_task_id,
            activate=activate,
        ),
    ]

    instruction = templates["instruction.md"]
    updated_paths.append(
        _upsert_harbor_registry(
            benchmark_root=benchmark_root_path,
            task_id=chosen_task_id,
            entry=_harbor_entry_for_scaffold(
                task_id=chosen_task_id,
                motif_family=motif_family,
                title=chosen_title,
                profile=profile,
                instruction=instruction,
            ),
        )
    )
    updated_paths.append(
        _upsert_microtooling_registry(
            benchmark_root=benchmark_root_path,
            task_id=chosen_task_id,
            entry=_microtooling_entry_for_scaffold(
                task_id=chosen_task_id,
                motif_family=motif_family,
                title=chosen_title,
            ),
        )
    )
    updated_paths.append(
        _ensure_task_card_regression(
            benchmark_root=benchmark_root_path,
            task_id=chosen_task_id,
            motif_family=motif_family,
            title=chosen_title,
            profile=profile,
        )
    )

    return HarnessScaffoldResult(
        task_id=chosen_task_id,
        motif_family=motif_family,
        title=chosen_title,
        profile=profile,
        benchmark_root=str(benchmark_root_path),
        task_root=str(task_root),
        activation_mode="active" if activate else "draft",
        created_paths=sorted({str(path) for path in created_paths}),
        updated_paths=sorted({str(path) for path in updated_paths}),
        warnings=warnings,
    )


__all__ = [
    "HarnessScaffoldResult",
    "scaffold_harness_task",
]
