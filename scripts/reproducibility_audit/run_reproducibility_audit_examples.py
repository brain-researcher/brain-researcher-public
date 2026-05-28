#!/usr/bin/env python3
"""Run or materialize reproducibility-audit example episodes.

This runner supports dry-run prompt materialization and coding-agent execution
for every reproducibility-audit case shape. Grounded-recommendation cases have
task-specific canonical-convergence scoring; other case shapes currently receive
contract-level JSON/schema scoring until their scientific scorers are added.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import signal
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_ROOT = REPO_ROOT / "benchmarks" / "reproducibility_audit_examples"
DEFAULT_OUT_ROOT = DEFAULT_CASES_ROOT / "runs"
DEFAULT_AGENT_CONDITIONS_PATH = (
    REPO_ROOT / "benchmarks" / "neurometabench" / "agent_conditions.v1.jsonl"
)
DEFAULT_CONDITIONS = ["codex_without_br", "codex_with_br_gated"]
SUPPORTED_EXECUTION_TASK_SHAPES = {
    "artifact_report",
    "executable_pipeline",
    "grounded_recommendation",
    "literature_audit",
    "statistical_validation",
}
FAST_GFS_STORE = "fileSearchStores/papers-fmri-oa-20152025-uni-aqus07ky5cos"
BR_MODE_WITH = "with_br_mcp"
BR_MODE_WITH_REQUIRED = "with_br_required"
OPENCODE_MCP_MISSING_STATUS = "skipped_missing_opencode_br_mcp"
PROCESS_GROUP_SHUTDOWN_GRACE_S = 5
REPORT_TABLES_DIRNAME = "report_tables"
MATERIALIZED_STATUSES = {"materialized", "dry_run"}
FAILED_STATUSES = {
    "failed",
    "failed_error_event",
    "failed_output_capture",
    "skipped_execution_unavailable_agent",
    "skipped_execution_unsupported_task_shape",
}
QUALITY_NUMERIC_FIELDS = (
    "required_field_coverage",
    "rubric_axis_score",
    "required_family_recall",
    "claim_support_precision",
    "final_anchor_from_retrieval_rate",
    "retrieved_anchor_utilization_rate",
    "retrieval_success_rate",
    "grounding_quality_score",
)
EVIDENCE_BEARING_BASIS_TYPES = {
    "specific_citation",
    "retrieved_document",
    "kg_fact",
    "session_memory",
}
BR_TOOL_PREFIXES = ("brain-researcher-prod", "brain-researcher-local")
BR_RETRIEVAL_TOOL_NAME = "google_file_search"
VALID_ANCHOR_PATTERNS = {
    "doi": re.compile(r"\bdoi\s*:\s*(10\.\d{4,9}/[^\s;|,\]\)\"'}]+)", re.IGNORECASE),
    "pmid": re.compile(r"\bpmid\s*:\s*(\d{6,9})\b", re.IGNORECASE),
    "doc": re.compile(r"\bdoc\s*:\s*([A-Za-z0-9_.:/-]+)", re.IGNORECASE),
    "kg": re.compile(r"\bkg\s*:\s*([A-Za-z0-9_.:/-]+)", re.IGNORECASE),
    "session": re.compile(r"\bsession\s*:\s*([A-Za-z0-9_.:/-]+)", re.IGNORECASE),
}
ANCHOR_LABEL_RE = re.compile(r"\b(?:doi|pmid|doc|kg|session)\s*:", re.IGNORECASE)
BARE_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s;|,\]\)\"'}]+)", re.IGNORECASE)
PMID_LABEL_RE = re.compile(r"\bPMID\s*:?\s*(\d{6,9})\b", re.IGNORECASE)
REQUIRED_FAMILY_ALIASES = {
    "murphy 2009": [
        "10.1016/j.neuroimage.2008.09.036",
        "10.1016/j.neuroimage.2009.05.036",
        "18976716",
        "19472080",
        "murphy",
    ],
    "murphy and fox 2017": [
        "10.1016/j.neuroimage.2016.11.052",
        "28011061",
        "murphy and fox",
        "murphy & fox",
    ],
    "saad 2012": [
        "10.1016/j.neuroimage.2012.01.052",
        "22357320",
        "saad",
    ],
    "power 2014": [
        "10.1016/j.neuroimage.2013.08.048",
        "23994314",
        "power",
    ],
    "yang 2014": [
        "10.1073/pnas.1405289111",
        "24799682",
        "yang",
        "altered global brain signal",
    ],
    "satterthwaite 2013": [
        "satterthwaite",
    ],
    "ciric 2017": [
        "10.1016/j.neuroimage.2017.03.020",
        "28302591",
        "ciric",
    ],
    "parkes 2018": [
        "10.1016/j.neuroimage.2017.12.073",
        "29278773",
        "parkes",
    ],
    "esteban 2019": [
        "10.1038/s41592-018-0235-4",
        "30532080",
        "esteban",
        "fmriprep",
    ],
    "behzadi 2007": [
        "10.1016/j.neuroimage.2007.04.042",
        "17560126",
        "behzadi",
        "acompcor",
        "compcor",
    ],
    "pruim 2015": [
        "pruim",
        "ica-aroma",
        "aroma",
    ],
}
ACTION_KEYWORD_ALIASES = {
    "sensitivity_analysis": [
        "sensitivity",
        "robustness",
        "rerun",
        "with and without",
        "compare pipelines",
        "alternative pipeline",
    ],
    "motion_qc": [
        "motion",
        "framewise displacement",
        "mean fd",
        " fd",
        "dvars",
        "retained frames",
    ],
    "scrubbing_censoring": [
        "scrubbing",
        "censoring",
        "censor",
        "exclude high-motion",
        "high-motion",
    ],
    "nuisance_regression": [
        "nuisance",
        "confound",
        "regressor",
        "regression",
        "white matter",
        "csf",
        "acompcor",
        "compcor",
    ],
    "ica_aroma": [
        "ica-aroma",
        "aroma",
        "component",
        "non-aggressive",
        "nonaggressive",
    ],
    "gsr_sensitivity": [
        "global signal",
        "gsr",
        "with-gsr",
        "without-gsr",
        "without gsr",
        "with gsr",
    ],
    "group_balance": [
        "case-control",
        "patient",
        "control",
        "group balance",
        "between-group",
        "matched",
    ],
    "transparent_reporting": [
        "report",
        "methods text",
        "table",
        "transparent",
        "qc",
        "quality control",
    ],
    "bids_fmriprep": [
        "bids",
        "fmriprep",
        "derivatives",
        "confounds_timeseries",
        "confounds",
    ],
    "validation_testing": [
        "cross-validation",
        "nested cv",
        "external validation",
        "permutation",
        "null",
        "calibration",
        "held-out",
        "holdout",
    ],
    "leakage_guard": [
        "leakage",
        "family",
        "site",
        "train",
        "test",
        "feature selection",
        "model selection",
    ],
    "preregistration": [
        "preregister",
        "pre-register",
        "preregistration",
        "exclusion criteria",
        "a priori",
    ],
}
DECISION_KEYWORD_ALIASES = {
    "clinical_rsfmri_fc": [
        "clinical",
        "case-control",
        "patient",
        "control",
        "rsfmri",
        "resting-state",
        "functional connectivity",
        "rsfc",
    ],
    "conditional_recommendation": [
        "conditional",
        "depends",
        "not categorical",
        "not universal",
        "rather than",
        "not as the sole",
    ],
    "sensitivity_required": ACTION_KEYWORD_ALIASES["sensitivity_analysis"],
    "motion_confound_risk": ACTION_KEYWORD_ALIASES["motion_qc"],
    "denoising_tradeoff": [
        "tradeoff",
        "trade-off",
        "residual motion",
        "data loss",
        "anti-correlation",
        "negative correlation",
        "physiology",
    ],
    "validation_or_preregistration": (
        ACTION_KEYWORD_ALIASES["validation_testing"]
        + ACTION_KEYWORD_ALIASES["preregistration"]
        + ACTION_KEYWORD_ALIASES["leakage_guard"]
    ),
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(payload)
    return rows


def load_env_file(path: Path) -> list[str]:
    """Load simple KEY=VALUE entries from an env file without overriding env."""

    if not path.exists():
        return []
    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        loaded.append(key)
    return loaded


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_case_index(cases_root: Path) -> dict[str, dict[str, Any]]:
    index_path = cases_root / "case_index.json"
    index = read_json(index_path)
    rows = index.get("cases") or []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            by_id[case_id] = row
    return by_id


def resolve_case_paths(cases_root: Path, selectors: list[str]) -> list[Path]:
    by_id = load_case_index(cases_root)
    if not selectors:
        selectors = list(by_id)
    paths: list[Path] = []
    for selector in selectors:
        if selector in by_id:
            path = cases_root / str(by_id[selector]["file"])
        else:
            candidate = Path(selector)
            path = candidate if candidate.is_absolute() else cases_root / candidate
        if not path.exists():
            raise FileNotFoundError(f"Case selector did not resolve to an existing file: {selector}")
        paths.append(path)
    return paths


def load_cases(cases_root: Path, selectors: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in resolve_case_paths(cases_root, selectors):
        case = read_json(path)
        case["_case_path"] = str(path)
        cases.append(case)
    return cases


def selected_variants(case: dict[str, Any], variant_ids: set[str] | None) -> list[dict[str, Any]]:
    variants = case.get("prompt_variants") or []
    if variant_ids is None:
        return list(variants)
    return [variant for variant in variants if str(variant.get("variant_id")) in variant_ids]


def load_episode_manifest(path: Path) -> list[dict[str, str]]:
    """Load an exact episode manifest with case_id, variant_id, and condition."""

    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"case_id", "variant_id", "condition"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Episode manifest {path} is missing required column(s): "
                f"{', '.join(sorted(missing))}"
            )
        seen: set[tuple[str, str, str]] = set()
        for line_no, raw_row in enumerate(reader, 2):
            case_id = str(raw_row.get("case_id") or "").strip()
            variant_id = str(raw_row.get("variant_id") or "").strip()
            condition = str(raw_row.get("condition") or "").strip()
            if not case_id or not variant_id or not condition:
                raise ValueError(f"Episode manifest {path}:{line_no} has an empty key field")
            key = (case_id, variant_id, condition)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "case_id": case_id,
                    "variant_id": variant_id,
                    "condition": condition,
                    "source_status": str(raw_row.get("status") or "").strip(),
                    "source_run": str(raw_row.get("source_run") or "").strip(),
                    "task_shape": str(raw_row.get("task_shape") or "").strip(),
                }
            )
    if not rows:
        raise ValueError(f"Episode manifest {path} did not contain any rows")
    return rows


def _variant_by_id(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(variant.get("variant_id")): variant for variant in case.get("prompt_variants") or []}


def case_required_fields(case: dict[str, Any]) -> list[str]:
    output_contract = case.get("output_contract") or {}
    fields = output_contract.get("required_fields") or output_contract.get("expected_outputs") or []
    return [str(field) for field in fields]


def canonical_validation_status(case: dict[str, Any] | None) -> str:
    if not isinstance(case, dict):
        return "case_not_loaded"
    validation = case.get("canonical_validation") or {}
    status = validation.get("status") if isinstance(validation, dict) else None
    return str(status or "missing")


def canonical_validation_tier(case: dict[str, Any] | None) -> str:
    if not isinstance(case, dict):
        return "unknown"
    validation = case.get("canonical_validation") or {}
    if not isinstance(validation, dict):
        return "draft"
    tier = str(validation.get("tier") or "").strip().lower()
    if tier in {"draft", "reviewed", "locked"}:
        return tier
    status = str(validation.get("status") or "").strip().lower()
    if status in {"locked", "passed", "canonical_locked"}:
        return "locked"
    if "locked" in status:
        return "locked"
    if "reviewed" in status or "accepted" in status:
        return "reviewed"
    return "draft"


def canonical_validation_blocking(case: dict[str, Any] | None) -> bool | None:
    if not isinstance(case, dict):
        return None
    validation = case.get("canonical_validation") or {}
    if not isinstance(validation, dict):
        return True
    blocking = validation.get("blocking")
    return bool(blocking) if isinstance(blocking, bool) else canonical_validation_tier(case) != "locked"


def format_required_fields(case: dict[str, Any]) -> str:
    fields = case_required_fields(case)
    if not fields:
        return "- No case-specific fields declared."
    return "\n".join(f"- {field}" for field in fields)


def format_scoring_axes(case: dict[str, Any]) -> str:
    axes = case.get("scoring_axes") or []
    if not axes:
        return "- No case-specific scoring axes declared."
    lines: list[str] = []
    for axis in axes:
        name = axis.get("axis", "axis")
        expectation = axis.get("canonical_expectation", "")
        lines.append(f"- {name}: {expectation}")
    return "\n".join(lines)


def load_agent_conditions(path: Path) -> dict[str, dict[str, Any]]:
    conditions: dict[str, dict[str, Any]] = {}
    for row in read_jsonl_rows(path):
        if row.get("record_type") != "condition":
            continue
        if row.get("execution_mode") != "coding_agent":
            continue
        condition_id = str(row.get("condition_id") or "").strip()
        runner = str(row.get("runner") or "").strip()
        model_target = str(row.get("model_target") or "").strip()
        br_mode = str(row.get("br_mode") or "").strip()
        if not condition_id or not runner or not model_target or not br_mode:
            raise ValueError(f"Malformed coding-agent condition row in {path}: {row}")
        conditions[condition_id] = row
    return conditions


def select_conditions(
    *,
    requested: list[str],
    all_coding_agents: bool,
    agent_conditions: dict[str, dict[str, Any]],
) -> list[str]:
    if all_coding_agents:
        if requested:
            missing = [condition for condition in requested if condition not in agent_conditions]
            if missing:
                raise ValueError(f"Unknown coding-agent condition(s): {', '.join(missing)}")
            return requested
        return list(agent_conditions)
    return requested or DEFAULT_CONDITIONS


def condition_instructions(
    condition: str,
    agent_condition: dict[str, Any] | None = None,
) -> tuple[list[str], bool]:
    """Return prompt instructions and whether BR MCP should be enabled."""

    if agent_condition is not None:
        runner = agent_condition.get("runner")
        model_target = agent_condition.get("model_target")
        br_mode = agent_condition.get("br_mode")
        if _br_mcp_enabled(br_mode):
            if _br_mcp_required(br_mode):
                retrieval_instruction = (
                    "You must make one fast Brain Researcher retrieval call before finalizing the answer."
                )
            else:
                retrieval_instruction = (
                    "Use one fast Brain Researcher retrieval call before finalizing the answer when that tool is available."
                )
            return (
                [
                    f"Coding-agent runner: {runner}; model target: {model_target}.",
                    "Brain Researcher MCP/tools are enabled for this episode.",
                    retrieval_instruction,
                    (
                        "For literature support, call Brain Researcher google_file_search with "
                        f"operation=\"query\", store_name=\"{FAST_GFS_STORE}\", and top_k<=3 when that tool is available."
                    ),
                    "Do not call Brain Researcher research logging, session snapshot, run-management, or memory-write tools in this benchmark episode.",
                    "Only cite DOI/PMID/doc/KG anchors that are explicitly returned or otherwise verifiable.",
                    "If retrieval is unavailable, irrelevant, or anchor-free, demote the evidence basis to general_principle or uncertain.",
                    (
                        "When retrieval returns usable anchors, copy the anchors you rely on into evidence_basis "
                        "and include a retrieved_evidence_used mapping for every retrieved source family you used or omitted."
                    ),
                    "Include optional tool_trace with tool names and one-line purposes if you use tools.",
                ],
                True,
            )
        return (
            [
                f"Coding-agent runner: {runner}; model target: {model_target}.",
                "Brain Researcher MCP/tools are disabled for this episode.",
                "Use only the scenario, provided files, repository-visible context, and general scientific knowledge.",
                "Do not fabricate papers, DOIs, PMIDs, KG nodes, session memories, tool calls, or retrieved documents.",
                "If a specific source anchor is unavailable, mark the evidence basis as general_principle or uncertain.",
            ],
            False,
        )

    if condition == "codex_without_br":
        return (
            [
                "Brain Researcher MCP is disabled for this episode.",
                "Use only the scenario, provided files, and general scientific knowledge.",
                "Do not fabricate papers, DOIs, PMIDs, KG nodes, session memories, tool calls, or retrieved documents.",
                "If a specific source anchor is unavailable, mark the evidence basis as general_principle or uncertain.",
            ],
            False,
        )
    if condition == "codex_with_br_gated":
        return (
            [
                "Brain Researcher MCP is enabled for this episode.",
                "Use at most one fast Brain Researcher retrieval call before answering.",
                "Do not call brain-researcher-prod/kg_probe in this benchmark episode.",
                (
                    "For literature support, prefer google_file_search with "
                    f"operation=\"query\", store_name=\"{FAST_GFS_STORE}\", top_k<=3."
                ),
                "Do not call Brain Researcher research logging, session snapshot, run-management, or memory-write tools in this benchmark episode.",
                "Only cite DOI/PMID/doc anchors that are explicitly returned or otherwise verifiable.",
                "If retrieval is unavailable, irrelevant, or anchor-free, demote the evidence basis to general_principle or uncertain.",
                (
                    "When retrieval returns usable anchors, copy the anchors you rely on into evidence_basis "
                    "and include a retrieved_evidence_used mapping for every retrieved source family you used or omitted."
                ),
                "Include optional tool_trace with tool names and one-line purposes if you use tools.",
            ],
            True,
        )
    if condition == "codex_with_br_answer_first":
        return (
            [
                "Brain Researcher MCP is enabled for this episode.",
                "First form a provisional answer from the prompt and canonical scientific constraints.",
                "Then use at most one fast Brain Researcher retrieval call to verify or correct source anchors.",
                "Do not call brain-researcher-prod/kg_probe in this benchmark episode.",
                (
                    "For literature support, prefer google_file_search with "
                    f"operation=\"query\", store_name=\"{FAST_GFS_STORE}\", top_k<=3."
                ),
                "Do not call Brain Researcher research logging, session snapshot, run-management, or memory-write tools in this benchmark episode.",
                "Only preserve claims whose source support can be stated honestly.",
                (
                    "When retrieval returns usable anchors, copy the anchors you rely on into evidence_basis "
                    "and include a retrieved_evidence_used mapping for every retrieved source family you used or omitted."
                ),
                "Include optional tool_trace with tool names and one-line purposes if you use tools.",
            ],
            True,
        )
    return (
        [
            f"Condition label: {condition}",
            "No built-in condition instructions are available for this label.",
            "Answer conservatively and do not fabricate source anchors or tool results.",
        ],
        False,
    )


def response_shape_instructions(
    case: dict[str, Any],
    *,
    require_retrieval_mapping: bool = False,
    diagnostic_contract: bool = False,
) -> str:
    task_shape = str(case.get("task_shape") or "unknown")
    if task_shape == "grounded_recommendation":
        retrieval_mapping = (
            """

For BR-enabled episodes where retrieval returned usable anchors, also include:
{
  "retrieved_evidence_used": [
    {
      "retrieved_family": "retrieved source family or agent-inferred evidence family name",
      "anchor": "doi:...|pmid:...|doc:...|kg:...",
      "final_claim": "the final-answer claim this retrieved anchor supports",
      "used_in_evidence_basis": true,
      "omitted_reason": ""
    }
  ]
}
For retrieved source families you intentionally do not use, include an entry with
used_in_evidence_basis=false, an empty anchor if needed, and a short
omitted_reason. If retrieval is unavailable or irrelevant, use an empty array.
Do not expect hidden canonical family names; use only source labels visible in
the prompt, retrieval result, or final answer.
""".rstrip()
            if require_retrieval_mapping
            else ""
        )
        diagnostic_mapping = (
            """

Diagnostic-only family mapping:
{
  "diagnostic_family_mapping": [
    {
      "evidence_family": "visible source family or citation label, not a hidden benchmark key",
      "retrieved": true,
      "used_in_evidence_basis": true,
      "anchor": "doi:...|pmid:...|doc:...|kg:...",
      "evidence_basis_index": 0,
      "omitted_reason": ""
    }
  ]
}
This diagnostic field is for calibration runs only. Do not invent benchmark
canonical targets. Label evidence from visible retrieval/citation evidence; the
scorer may map those visible labels to canonical families post hoc.
""".rstrip()
            if diagnostic_contract
            else ""
        )
        base_contract = """
Return one JSON object only. Your final assistant message must be the JSON object itself, not Markdown, not a fenced code block, not prose, and not a pointer to a file you wrote.
Do not write the response to a repository file unless a later tool call absolutely requires it; if you do write an intermediate file, still return the complete JSON object as the final answer.
Use this shape:
{
  "answer": "short recommendation",
  "key_points": ["..."],
  "risks_or_failure_modes": ["..."],
  "recommended_actions": ["..."],
  "evidence_needed": ["..."],
  "evidence_basis": [
    {
      "claim": "...",
      "basis_type": "specific_citation|retrieved_document|kg_fact|session_memory|general_principle|uncertain",
      "reference": "doi:...|pmid:...|doc:...|kg:...|session:...|",
      "support_span": "short span or rationale, if available",
      "verifiable": true
    }
  ],
  "confidence": "low|medium|high",
  "tool_trace": []
}

If the case declares additional required response fields, include them as
extra top-level JSON fields. Do not omit a declared field just because it is
not shown in the generic shape above.
""".strip()
        return f"{base_contract}{retrieval_mapping}{diagnostic_mapping}".strip()
    required_fields = case_required_fields(case)
    required_note = (
        "Also include these case-declared top-level fields exactly: "
        + ", ".join(f"`{field}`" for field in required_fields)
        + "."
        if required_fields
        else (
            "No case-specific top-level fields are declared, so include at least "
            "`answer`, `status`, `key_points`, `risks_or_failure_modes`, "
            "`recommended_actions`, `evidence_needed`, `evidence_basis`, "
            "`artifacts`, `validation`, `confidence`, and `tool_trace`."
        )
    )
    return f"""
Return one JSON object only. Your final assistant message must be the JSON
object itself, not Markdown, not a fenced code block, not prose, and not a
pointer to a file you wrote.

This is an executable benchmark episode, not a handoff packet. Complete the
requested audit or validation as far as the visible inputs permit. If required
inputs are absent, do not invent them; mark the result as blocked or uncertain
and state the exact missing input.

If you create files, write them only under the episode artifact directory named
in the prompt. Always summarize any created files in the final JSON `artifacts`
array with relative or absolute paths.

Use this generic shape:
{{
  "answer": "short task result or blocked/uncertain status",
  "status": "completed|blocked|uncertain",
  "key_points": ["..."],
  "risks_or_failure_modes": ["..."],
  "recommended_actions": ["..."],
  "evidence_needed": ["..."],
  "evidence_basis": [
    {{
      "claim": "...",
      "basis_type": "specific_citation|retrieved_document|kg_fact|session_memory|general_principle|artifact|uncertain",
      "reference": "doi:...|pmid:...|doc:...|kg:...|session:...|artifact:path|",
      "support_span": "short span or rationale, if available",
      "verifiable": true
    }}
  ],
  "artifacts": [
    {{
      "path": "path/to/artifact-or-empty",
      "description": "what this artifact contains",
      "created": true
    }}
  ],
  "validation": {{
    "checks_run": ["..."],
    "passed": true,
    "limitations": ["..."]
  }},
  "confidence": "low|medium|high",
  "tool_trace": []
}}

{required_note}

For now, non-grounded task shapes are scored at contract level: valid JSON,
declared field coverage, and availability. Do not expose or guess hidden
canonical answers.
""".strip()


def build_prompt(
    case: dict[str, Any],
    variant: dict[str, Any],
    condition: str,
    agent_condition: dict[str, Any] | None = None,
    diagnostic_contract: bool = False,
    episode_dir: Path | None = None,
) -> str:
    instructions, enable_br = condition_instructions(condition, agent_condition)
    canonical = case.get("canonical_task") or {}
    canonical_description = canonical.get("description") or ""
    study_context = canonical.get("study_context") or {}
    context_lines = "\n".join(f"- {key}: {value}" for key, value in study_context.items())
    instruction_lines = "\n".join(f"- {line}" for line in instructions)
    agent_lines = ""
    if agent_condition is not None:
        agent_lines = f"""

Coding-agent condition:
- condition_id: {agent_condition.get("condition_id")}
- runner: {agent_condition.get("runner")}
- model_target: {agent_condition.get("model_target")}
- model_source: {agent_condition.get("model_source")}
- br_mode: {agent_condition.get("br_mode")}
""".rstrip()
    artifact_dir = (episode_dir / "artifacts") if episode_dir is not None else None
    workspace_lines = (
        f"- episode_dir: {episode_dir}\n- artifact_dir: {artifact_dir}\n"
        "- If files are needed for this episode, create them only under artifact_dir."
        if episode_dir is not None
        else "- No episode artifact directory declared."
    )
    return f"""
You are running a reproducibility-audit benchmark episode.

Case:
- case_id: {case.get("case_id")}
- title: {case.get("title")}
- task_shape: {case.get("task_shape")}
- variant_id: {variant.get("variant_id")}
- variant_type: {variant.get("variant_type")}
- condition: {condition}
{agent_lines}

User prompt variant:
{variant.get("prompt")}

Canonical task description:
{canonical_description}

Study/context fields:
{context_lines or "- No structured context fields declared."}

Episode workspace:
{workspace_lines}

Condition instructions:
{instruction_lines}

Required response fields:
{format_required_fields(case)}

Scoring axes:
{format_scoring_axes(case)}

Response contract:
{response_shape_instructions(case, require_retrieval_mapping=enable_br, diagnostic_contract=diagnostic_contract)}
""".strip() + "\n"


def codex_command(
    output_path: Path,
    condition: str,
    reasoning_effort: str,
    codex_bin: str,
    model: str | None,
    agent_condition: dict[str, Any] | None = None,
) -> list[str]:
    _, enable_br = condition_instructions(condition, agent_condition)
    model_target = str(agent_condition.get("model_target") or "") if agent_condition else model
    args = [
        codex_bin,
        "--ask-for-approval",
        "never",
        "-c",
        f"model_reasoning_effort={json.dumps(reasoning_effort)}",
        "-c",
        "mcp_servers.chrome-devtools.enabled=false",
        "-c",
        "mcp_servers.playwright.enabled=false",
        "-c",
        "mcp_servers.sequential-thinking.enabled=false",
        "-c",
        "mcp_servers.paperbanana.enabled=false",
        "-c",
        f"mcp_servers.brain-researcher-prod.enabled={'true' if enable_br else 'false'}",
    ]
    if model_target:
        args.extend(["--model", model_target])
    args.extend(
        [
        "exec",
        "--cd",
        str(REPO_ROOT),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--json",
        "--output-last-message",
        str(output_path),
        "-",
        ]
    )
    # ``codex exec --json`` writes event JSONL to stdout; callers redirect it.
    return args


def _command_exists(binary: str) -> bool:
    return shutil.which(binary) is not None


def _br_mcp_enabled(br_mode: Any) -> bool:
    return str(br_mode or "") in {BR_MODE_WITH, BR_MODE_WITH_REQUIRED}


def _br_mcp_required(br_mode: Any) -> bool:
    return str(br_mode or "") == BR_MODE_WITH_REQUIRED


@lru_cache(maxsize=1)
def opencode_has_mcp() -> bool:
    if not _command_exists("opencode"):
        return False
    try:
        result = subprocess.run(
            ["opencode", "mcp", "list"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return (
        result.returncode == 0
        and "no mcp servers configured" not in combined
        and "brain-researcher" in combined
    )


def empty_mcp_config(run_dir: Path) -> Path:
    path = run_dir / "empty_mcp.json"
    write_json(path, {"mcpServers": {}})
    return path


def command_for_episode(
    *,
    output_path: Path,
    condition: str,
    prompt: str,
    run_dir: Path,
    reasoning_effort: str,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    model: str | None,
    agent_condition: dict[str, Any] | None,
    claude_br_mcp_config: Path,
    allow_opencode_with_br: bool,
) -> tuple[list[str], bool, str | None]:
    """Return command, whether prompt is passed on stdin, and optional skip reason."""

    if agent_condition is None:
        if not _command_exists(codex_bin):
            return [], True, f"missing_binary:{codex_bin}"
        return (
            codex_command(output_path, condition, reasoning_effort, codex_bin, model),
            True,
            None,
        )

    runner = str(agent_condition.get("runner") or "")
    br_mode = str(agent_condition.get("br_mode") or "")
    model_target = str(agent_condition.get("model_target") or "")

    if runner == "codex_cli":
        if not _command_exists(codex_bin):
            return [], True, f"missing_binary:{codex_bin}"
        return (
            codex_command(
                output_path,
                condition,
                reasoning_effort,
                codex_bin,
                model,
                agent_condition,
            ),
            True,
            None,
        )

    if runner == "claude_code":
        if not _command_exists(claude_bin):
            return [], False, f"missing_binary:{claude_bin}"
        mcp_config = claude_br_mcp_config if _br_mcp_enabled(br_mode) else empty_mcp_config(run_dir)
        if _br_mcp_enabled(br_mode) and not mcp_config.exists():
            return [], False, f"missing_claude_br_mcp_config:{mcp_config}"
        return (
            [
                claude_bin,
                "-p",
                "--model",
                model_target,
                "--permission-mode",
                "bypassPermissions",
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
            False,
            None,
        )

    if runner == "opencode":
        if not _command_exists(opencode_bin):
            return [], False, f"missing_binary:{opencode_bin}"
        if _br_mcp_enabled(br_mode) and not allow_opencode_with_br and not opencode_has_mcp():
            return [], False, OPENCODE_MCP_MISSING_STATUS
        return (
            [
                opencode_bin,
                "run",
                "--dir",
                str(REPO_ROOT),
                "--model",
                model_target,
                "--format",
                "json",
                "--print-logs",
                "--log-level",
                "ERROR",
                "--dangerously-skip-permissions",
                prompt,
            ],
            False,
            None,
        )

    return [], False, f"unsupported_runner:{runner}"


def episode_env(agent_condition: dict[str, Any] | None) -> dict[str, str]:
    env = os.environ.copy()
    if (
        agent_condition is not None
        and agent_condition.get("runner") == "opencode"
        and not _br_mcp_enabled(agent_condition.get("br_mode"))
    ):
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    return env


def command_for_record(command: list[str], prompt: str) -> list[str]:
    if command and command[-1] == prompt:
        return [*command[:-1], "<prompt from prompt.txt>"]
    return command


PROVIDER_ACCOUNT_LIMIT_MARKERS = (
    "out of extra usage",
    "quota",
    "rate limit",
    "rate_limit",
    "insufficient_quota",
    "billing",
    "provider rejected",
    "subscriptionusagelimiterror",
    "subscription quota exceeded",
    "creditserror",
    "insufficient balance",
)


def _has_provider_or_account_limit(text: str) -> bool:
    searchable_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                searchable_lines.append(line)
                continue
            if isinstance(event, dict):
                event_type = event.get("type")
                if event_type == "rate_limit_event":
                    rate_limit_info = event.get("rate_limit_info")
                    if isinstance(rate_limit_info, dict):
                        status = str(rate_limit_info.get("status") or "").lower()
                        if status == "allowed":
                            continue
                        if status:
                            return True
                    continue
                if event_type == "error" or event.get("is_error") is True:
                    searchable_lines.append(line)
                    continue
                result = event.get("result")
                if isinstance(result, dict) and result.get("is_error"):
                    searchable_lines.append(line)
                    continue
                if (
                    isinstance(result, str)
                    and event.get("is_error") is True
                ):
                    searchable_lines.append(line)
                    continue
                # Tool output and assistant text often contain historical provider
                # errors as data being audited; those are not current-run failures.
                continue
        else:
            searchable_lines.append(line)

    text_lower = "\n".join(searchable_lines).lower()
    return any(marker in text_lower for marker in PROVIDER_ACCOUNT_LIMIT_MARKERS)


def _read_recent_text(path: Path, max_chars: int = 24000) -> str:
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_chars:
                handle.seek(size - max_chars)
            return handle.read(max_chars).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _terminate_process_group(process: subprocess.Popen[Any]) -> bool:
    if process.poll() is not None:
        return False
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        except OSError:
            process.terminate()
        try:
            process.wait(timeout=PROCESS_GROUP_SHUTDOWN_GRACE_S)
            return True
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                process.kill()
            return True
    process.terminate()
    try:
        process.wait(timeout=PROCESS_GROUP_SHUTDOWN_GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
    return True


def run_command_to_files(
    *,
    command: list[str],
    prompt_path: Path,
    prompt_on_stdin: bool,
    events_path: Path,
    stderr_path: Path,
    timeout_s: int,
    env: dict[str, str],
) -> tuple[int | None, bool, str | None]:
    with events_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE if prompt_on_stdin else None,
            stdout=stdout,
            stderr=stderr,
            env=env,
            start_new_session=(os.name == "posix"),
        )
        if prompt_on_stdin:
            try:
                process.communicate(input=prompt_path.read_bytes(), timeout=timeout_s)
                return process.returncode, False, None
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                return None, True, None
        deadline = time.monotonic() + timeout_s
        while process.poll() is None:
            recent_diagnostics = "\n".join(
                [_read_recent_text(stderr_path), _read_recent_text(events_path)]
            )
            if _has_provider_or_account_limit(recent_diagnostics):
                _terminate_process_group(process)
                return process.returncode, False, "provider_or_account_limit"
            if time.monotonic() >= deadline:
                _terminate_process_group(process)
                return None, True, None
            time.sleep(1.0)
        return process.returncode, False, None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {None, "text", "output_text"} and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "result", "output"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    return ""


def extract_last_message(events_path: Path) -> str:
    last_text = ""
    if not events_path.is_file():
        return last_text
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            if stripped:
                last_text = stripped
            continue

        if isinstance(payload.get("result"), str):
            last_text = payload["result"]
            continue
        if isinstance(payload.get("output"), str):
            last_text = payload["output"]
            continue

        message = payload.get("message")
        if isinstance(message, dict):
            role = message.get("role")
            text = _content_text(message.get("content"))
            if role in {None, "assistant"} and text:
                last_text = text
                continue

        part = payload.get("part")
        if isinstance(part, dict):
            text = _content_text(part)
            if part.get("type") in {None, "text", "output_text"} and text:
                last_text = text
                continue

        role = payload.get("role")
        text = _content_text(payload.get("content"))
        if role in {None, "assistant"} and text:
            last_text = text
            continue
        if isinstance(payload.get("text"), str) and role in {None, "assistant"}:
            last_text = payload["text"]
    return last_text.strip()


def has_error_event(events_path: Path) -> bool:
    if not events_path.is_file():
        return False
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "error" or payload.get("error"):
            return True
        result = payload.get("result")
        if isinstance(result, dict) and result.get("is_error"):
            return True
        if payload.get("is_error") is True:
            return True
    return False


def count_tool_events(events_path: Path) -> tuple[int, list[str]]:
    call_ids: set[str] = set()
    fallback_count = 0
    tools: set[str] = set()
    if not events_path.exists():
        return 0, []
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            part = event.get("part") if isinstance(event, dict) else None
            if isinstance(part, dict) and part.get("type") == "tool":
                tool = str(part.get("tool") or "")
                if tool:
                    tools.add(_normalize_tool_label(tool))
                call_id = str(part.get("callID") or part.get("id") or event.get("id") or "")
                if call_id:
                    call_ids.add(call_id)
                else:
                    fallback_count += 1
                continue
            continue
        if item.get("type") == "mcp_tool_call":
            item_id = str(item.get("id") or "")
            if item_id:
                call_ids.add(item_id)
            elif event.get("type") == "item.completed":
                fallback_count += 1
            server = item.get("server")
            tool = item.get("tool")
            label = _normalize_tool_label(str(tool or ""), str(server or "") or None)
            if label:
                tools.add(label)
            continue
        event_text = json.dumps(event, sort_keys=True)
        if "mcp_tool_call" in event_text or "tool_use" in event_text or "tool_call" in event_text:
            event_id = str(event.get("id") or event.get("tool_use_id") or event.get("call_id") or "")
            if event_id:
                call_ids.add(event_id)
            else:
                fallback_count += 1
        for key in ("tool", "name"):
            value = event.get(key)
            if isinstance(value, str) and ("tool" in key or "mcp" in event_text.lower()):
                tools.add(value)
    return len(call_ids) if call_ids else fallback_count, sorted(tools)


def parse_response_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse an agent response as a JSON object, tolerating fenced wrappers."""

    stripped = text.strip()
    if not stripped:
        return None, "empty_response"
    candidates = [stripped]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    first = stripped.find("{")
    last = stripped.rfind("}")
    if 0 <= first < last:
        candidates.append(stripped[first : last + 1])

    errors: list[str] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(payload, dict):
            return payload, None
        errors.append("parsed_json_not_object")
    return None, "; ".join(errors[-2:]) if errors else "json_parse_failed"


def _json_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_tool_label(tool: str, server: str | None = None) -> str:
    tool = str(tool or "").strip()
    server = str(server or "").strip()
    if server:
        return f"{server}.{tool}"
    for prefix in BR_TOOL_PREFIXES:
        underscored = f"{prefix}_"
        if tool.startswith(underscored):
            return f"{prefix}.{tool[len(underscored):]}"
    return tool


def _is_br_tool_label(label: str) -> bool:
    return any(str(label).startswith(prefix) for prefix in BR_TOOL_PREFIXES)


def _is_br_retrieval_tool_label(label: str) -> bool:
    return _is_br_tool_label(label) and str(label).endswith(f".{BR_RETRIEVAL_TOOL_NAME}")


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _valid_anchor_atoms(text: str) -> list[str]:
    anchors: list[str] = []
    for label, pattern in VALID_ANCHOR_PATTERNS.items():
        anchors.extend(f"{label}:{match.group(1).strip()}" for match in pattern.finditer(text))
    return anchors


def _normal_anchor(anchor: str) -> str:
    return anchor.strip().rstrip(".,;:)]}\"'").lower()


def _all_anchor_atoms(text: str, *, include_bare: bool = False) -> list[str]:
    anchors = [_normal_anchor(anchor) for anchor in _valid_anchor_atoms(text)]
    if include_bare:
        anchors.extend(f"doi:{_normal_anchor(match.group(1))}" for match in BARE_DOI_RE.finditer(text))
        for match in PMID_LABEL_RE.finditer(text):
            pmid = match.group(1)
            anchors.append(f"pmid:{pmid}")
    return sorted(set(anchor for anchor in anchors if anchor))


def _anchor_counts(text: str) -> tuple[int, int]:
    valid_count = len(_valid_anchor_atoms(text))
    label_count = len(ANCHOR_LABEL_RE.findall(text))
    invalid_count = max(0, label_count - valid_count)
    return valid_count, invalid_count


def _looks_like_retrieval_error(payload: Any) -> bool:
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status.lower() == "error":
            return True
        if payload.get("error"):
            return True
        return any(_looks_like_retrieval_error(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_looks_like_retrieval_error(value) for value in payload)
    if isinstance(payload, str):
        lowered = payload.lower()
        return '"status": "error"' in lowered or '"status":"error"' in lowered
    return False


def extract_retrieval_provenance(events_path: Path) -> dict[str, Any]:
    call_ids: set[str] = set()
    success_count = 0
    error_count = 0
    retrieved_anchors: set[str] = set()
    retrieved_text_parts: list[str] = []
    if not events_path.is_file():
        return {
            "retrieval_tool_call_count": 0,
            "retrieval_success_count": 0,
            "retrieval_error_count": 0,
            "retrieved_anchor_count": 0,
            "retrieved_anchors": [],
        }
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict) and item.get("type") == "mcp_tool_call":
            label = _normalize_tool_label(str(item.get("tool") or ""), str(item.get("server") or ""))
            if not _is_br_retrieval_tool_label(label):
                continue
            item_id = str(item.get("id") or "")
            if item_id:
                call_ids.add(item_id)
            result = item.get("result")
            if event.get("type") == "item.completed":
                if _looks_like_retrieval_error(result):
                    error_count += 1
                elif result is not None:
                    success_count += 1
                result_text = _json_text(result)
                retrieved_text_parts.append(result_text)
                retrieved_anchors.update(_all_anchor_atoms(result_text, include_bare=True))
            continue

        part = event.get("part") if isinstance(event, dict) else None
        if isinstance(part, dict) and part.get("type") == "tool":
            label = _normalize_tool_label(str(part.get("tool") or ""))
            if not _is_br_retrieval_tool_label(label):
                continue
            call_id = str(part.get("callID") or part.get("id") or "")
            if call_id:
                call_ids.add(call_id)
            state = part.get("state")
            if isinstance(state, dict) and str(state.get("status") or "").lower() in {
                "completed",
                "error",
            }:
                output = state.get("output")
                if _looks_like_retrieval_error(state) or str(state.get("status") or "").lower() == "error":
                    error_count += 1
                elif output is not None:
                    success_count += 1
                output_text = _json_text(output)
                retrieved_text_parts.append(output_text)
                retrieved_anchors.update(_all_anchor_atoms(output_text, include_bare=True))
    return {
        "retrieval_tool_call_count": len(call_ids),
        "retrieval_success_count": success_count,
        "retrieval_error_count": error_count,
        "retrieved_anchor_count": len(retrieved_anchors),
        "retrieved_anchors": sorted(retrieved_anchors),
        "_retrieved_text": "\n".join(retrieved_text_parts)[:200000],
    }


def _family_aliases(family: str) -> list[str]:
    normalized = family.strip().lower()
    aliases = REQUIRED_FAMILY_ALIASES.get(normalized)
    if aliases:
        return aliases
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 4]
    return tokens or [normalized]


def _family_hit(family: str, text: str) -> bool:
    normalized_family = family.strip().lower()
    if normalized_family == "murphy and fox 2017":
        return (
            "murphy and fox" in text
            or "murphy & fox" in text
            or "10.1016/j.neuroimage.2016.11.052" in text
            or "28011061" in text
        )
    if normalized_family == "murphy 2009":
        return any(alias in text for alias in _family_aliases(family)) and "murphy and fox" not in text
    return any(alias in text for alias in _family_aliases(family))


def _family_key(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", family.strip().lower()).strip()


def _family_hits(families: list[str], text: str) -> list[str]:
    lowered = text.lower()
    return sorted({str(family) for family in families if _family_hit(str(family), lowered)})


def _known_evidence_families(required_families: list[str]) -> list[str]:
    families = {_family_key(family): str(family) for family in required_families}
    for family in REQUIRED_FAMILY_ALIASES:
        families.setdefault(_family_key(family), family)
    return [families[key] for key in sorted(families)]


def _family_prf(
    required_families: list[str],
    required_hits: list[str],
    predicted_families: list[str],
) -> dict[str, Any]:
    required = {_family_key(family) for family in required_families}
    hits = {_family_key(family) for family in required_hits}
    predicted = {_family_key(family) for family in predicted_families}
    recall = _safe_rate(len(hits), len(required))
    precision = _safe_rate(len(hits), len(predicted))
    if required and not predicted:
        precision = 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0 if precision == 0.0 and recall == 0.0 else None
    )
    return {
        "required_family_precision": precision,
        "required_family_f1": f1,
        "detected_evidence_family_count": len(predicted),
    }


def _retrieved_evidence_used_stats(
    response: dict[str, Any],
    required_families: list[str],
    retrieved_anchors: set[str],
) -> dict[str, Any]:
    raw_entries = response.get("retrieved_evidence_used")
    entries = raw_entries if isinstance(raw_entries, list) else []
    dict_entries = [entry for entry in entries if isinstance(entry, dict)]
    used_entries: list[dict[str, Any]] = []
    omitted_count = 0
    for entry in dict_entries:
        omitted_reason = str(entry.get("omitted_reason") or "").strip()
        used = entry.get("used_in_evidence_basis")
        if used is False or omitted_reason:
            omitted_count += 1
            continue
        used_entries.append(entry)

    used_text = _json_text(used_entries)
    used_anchors = set(_all_anchor_atoms(used_text, include_bare=True))
    used_anchor_from_retrieval = used_anchors & retrieved_anchors
    used_family_hits = _family_hits(required_families, used_text)
    return {
        "retrieved_evidence_used_count": len(used_entries),
        "retrieved_evidence_omitted_count": omitted_count,
        "retrieved_evidence_used_anchor_count": len(used_anchors),
        "retrieved_evidence_used_anchor_from_retrieval_count": len(used_anchor_from_retrieval),
        "retrieved_evidence_used_anchor_from_retrieval_rate": _safe_rate(
            len(used_anchor_from_retrieval),
            len(used_anchors),
        ),
        "retrieved_evidence_used_required_family_hits": used_family_hits,
        "retrieved_evidence_used_required_family_recall": (
            len(used_family_hits) / len(required_families)
            if required_families
            else None
        ),
    }


def _diagnostic_family_mapping_stats(
    response: dict[str, Any],
    required_families: list[str],
    retrieved_anchors: set[str],
) -> dict[str, Any]:
    raw_entries = response.get("diagnostic_family_mapping")
    entries = raw_entries if isinstance(raw_entries, list) else []
    dict_entries = [entry for entry in entries if isinstance(entry, dict)]
    used_entries = [
        entry
        for entry in dict_entries
        if entry.get("used_in_evidence_basis") is not False
        and not str(entry.get("omitted_reason") or "").strip()
    ]
    omitted_entries = [
        entry
        for entry in dict_entries
        if entry.get("used_in_evidence_basis") is False
        or str(entry.get("omitted_reason") or "").strip()
    ]
    used_text = _json_text(used_entries)
    used_anchors = set(_all_anchor_atoms(used_text, include_bare=True))
    family_hits = _family_hits(required_families, used_text)
    return {
        "diagnostic_family_mapping_count": len(dict_entries),
        "diagnostic_family_mapping_used_count": len(used_entries),
        "diagnostic_family_mapping_omitted_count": len(omitted_entries),
        "diagnostic_family_mapping_anchor_count": len(used_anchors),
        "diagnostic_family_mapping_anchor_from_retrieval_count": len(used_anchors & retrieved_anchors),
        "diagnostic_family_mapping_anchor_from_retrieval_rate": _safe_rate(
            len(used_anchors & retrieved_anchors),
            len(used_anchors),
        ),
        "diagnostic_family_mapping_required_family_hits": family_hits,
        "diagnostic_family_mapping_required_family_recall": (
            len(family_hits) / len(required_families)
            if required_families
            else None
        ),
    }


def _keyword_hits(text: str, aliases: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return sorted(
        key
        for key, values in aliases.items()
        if any(value.lower() in lowered for value in values)
    )


def _set_prf(required: list[str], predicted: list[str]) -> dict[str, Any]:
    required_set = set(required)
    predicted_set = set(predicted)
    hits = required_set & predicted_set
    recall = _safe_rate(len(hits), len(required_set))
    precision = _safe_rate(len(hits), len(predicted_set))
    if required_set and not predicted_set:
        precision = 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0 if precision == 0.0 and recall == 0.0 else None
    )
    return {"recall": recall, "precision": precision, "f1": f1, "hits": sorted(hits)}


def _case_expectation_text(case: dict[str, Any]) -> str:
    canonical = case.get("canonical_task") or {}
    parts = [
        canonical.get("description"),
        canonical.get("study_context"),
        canonical.get("hidden_answer_scaffold"),
    ]
    parts.extend(axis.get("canonical_expectation") for axis in case.get("scoring_axes") or [])
    return _json_text(parts)


def _response_action_text(response: dict[str, Any]) -> str:
    action_fields = [
        "answer",
        "key_points",
        "recommended_actions",
        "analysis_plan",
        "decision_table",
        "tradeoff_table",
        "methods_text",
        "checklist.md",
        "risk_table.csv",
        "evidence_needed",
        "risks_or_failure_modes",
    ]
    return _json_text({field: response.get(field) for field in action_fields if field in response})


def _mean_score_payload(scores: list[dict[str, Any]]) -> float | None:
    values = [
        float(payload["score"])
        for payload in scores
        if isinstance(payload, dict) and isinstance(payload.get("score"), (int, float))
    ]
    return _mean(values)


def _decision_axis_score(axes: dict[str, Any]) -> float | None:
    decision_axes = [
        payload
        for axis, payload in axes.items()
        if "evidence" not in axis.lower() and "anchor" not in axis.lower()
    ]
    return _mean_score_payload(decision_axes)


def _mean_available(values: list[Any]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    return _mean(clean)


def _canonical_convergence_score(metric: dict[str, Any]) -> float | None:
    return _mean_available(
        [
            metric.get("decision_field_macro_f1"),
            metric.get("required_action_f1"),
            metric.get("required_family_f1"),
        ]
    )


def _score_axis(
    axis: str,
    expectation: str,
    response_text: str,
    required_family_hits: list[str],
    valid_anchor_count: int,
    required_family_count: int,
) -> dict[str, Any]:
    axis_name = axis.strip().lower()
    text = response_text.lower()
    if axis_name in {"intent", "intent_match"}:
        ok = (
            _contains_any(text, ["case-control", "patient-control", "patients and controls", "clinical", "病例对照"])
            and _contains_any(
                text,
                [
                    "rsfmri",
                    "resting-state",
                    "rsfc",
                    "functional-connectivity",
                    "functional connectivity",
                    " fc ",
                    "功能连接",
                ],
            )
        )
        return {"score": int(ok), "reason": "case-control rsfMRI/FC context recognized" if ok else "missing case-control rsfMRI/FC context"}
    if axis_name in {"recommendation", "conditional_recommendation"}:
        ok = (
            _contains_any(text, ["gsr", "global signal", "denoising", "去噪", "scrubbing", "ica-aroma"])
            and _contains_any(
                text,
                [
                    "sensitivity",
                    "conditional",
                    "depends",
                    "not categorical",
                    "not as the sole",
                    "not as the only",
                    "not make gsr the sole",
                    "not make gsr a single",
                    "with and without",
                    "敏感性",
                    "条件",
                    "取决于",
                    "不要",
                ],
            )
        )
        return {"score": int(ok), "reason": "conditional recommendation present" if ok else "missing conditional recommendation"}
    if axis_name == "tradeoff_coverage":
        method_tradeoff = _contains_any(text, ["scrubbing", "censoring", "ica-aroma", "compcor", "nuisance regression"])
        artifact_tradeoff = _contains_any(text, ["anti-correlation", "anti-correlations", "negative correlations", "motion", "respiration", "physiology"])
        conditional = _contains_any(text, ["sensitivity", "depends", "conditional", "trade-off", "敏感性", "取决于"])
        ok = method_tradeoff and artifact_tradeoff and conditional
        return {
            "score": int(ok),
            "reason": f"method_tradeoff={method_tradeoff}; artifact_tradeoff={artifact_tradeoff}; conditional={conditional}",
        }
    if axis_name in {"evidence_anchors", "evidence_anchor_validity"}:
        ok = valid_anchor_count > 0 and (bool(required_family_hits) or required_family_count == 0)
        return {
            "score": int(ok),
            "reason": "valid evidence anchor present" if ok else "missing valid evidence anchor",
        }
    if axis_name == "caveat_presence":
        ok = _contains_any(
            text,
            [
                "with and without gsr",
                "without-gsr and gsr",
                "non-gsr and gsr",
                "gsr and non-gsr",
                "sensitivity analysis",
                "sensitivity pipeline",
                "with-gsr",
                "without-gsr",
                "使用 gsr",
                "不使用 gsr",
                "有 gsr",
                "无 gsr",
                "with-gsr 与 without-gsr",
                "with-gsr 和 without-gsr",
                "敏感性分析",
            ],
        )
        return {"score": int(ok), "reason": "with/without-GSR caveat present" if ok else "missing with/without-GSR caveat"}
    if axis_name in {"scope_hygiene", "overclaim_avoidance", "claim_calibration"}:
        overgeneralized = _contains_any(
            text,
            [
                "always use gsr",
                "never use gsr",
                "gsr is always",
                "gsr is never",
                "all fmri",
                "any fmri",
                "definitive proof",
                "guarantees",
            ],
        )
        scoped = _contains_any(text, ["case-control", "clinical", "resting-state", "rsfmri", "rsfc", "病例对照", "功能连接"])
        calibrated = _contains_any(text, ["sensitivity", "caveat", "limitation", "uncertain", "depends", "robust", "敏感性", "限制", "谨慎"])
        ok = scoped and calibrated and not overgeneralized
        return {"score": int(ok), "reason": "scoped and calibrated" if ok else "overgeneralized, underspecified, or missing calibration"}
    if axis_name == "motion_metric_coverage":
        metrics = _contains_any(text, ["framewise displacement", " fd", "mean fd", "dvars", "censor", "scrub", "motion"])
        group_check = _contains_any(text, ["group", "case", "control", "patient", "between-group", "组"])
        ok = metrics and group_check
        return {"score": int(ok), "reason": f"motion_metrics={metrics}; group_check={group_check}"}
    if axis_name == "sensitivity_plan_completeness":
        branches = _contains_any(text, ["sensitivity", "rerun", "compare", "alternative", "with and without", "敏感性"])
        covariates = _contains_any(text, ["covariate", "regression", "model", "fd", "dvars", "motion"])
        reporting = _contains_any(text, ["report", "table", "robust", "attenuat", "change", "stable"])
        ok = branches and covariates and reporting
        return {"score": int(ok), "reason": f"branches={branches}; covariates={covariates}; reporting={reporting}"}
    if axis_name == "confound_strategy_coverage":
        nuisance = _contains_any(text, ["confound", "nuisance", "motion", "white matter", "csf", "compcor", "global signal"])
        cleanup = _contains_any(text, ["scrubbing", "censoring", "filter", "ica-aroma", "fd", "dvars"])
        ok = nuisance and cleanup
        return {"score": int(ok), "reason": f"nuisance={nuisance}; cleanup={cleanup}"}
    if axis_name == "methods_specificity":
        fmriprep = _contains_any(text, ["fmriprep", "bids", "confounds_timeseries", "confounds", "derivatives"])
        specific = _contains_any(text, ["columns", "parameters", "threshold", "fd", "dvars", "cosine", "acompcor", "non-aggr"])
        ok = fmriprep and specific
        return {"score": int(ok), "reason": f"fmriprep_or_bids={fmriprep}; specific_terms={specific}"}

    expectation_terms = [
        term
        for term in re.split(r"[^a-z0-9-]+", expectation.lower())
        if len(term) >= 5 and term not in {"should", "canonical", "expectation"}
    ]
    hits = sum(1 for term in set(expectation_terms) if term in text)
    ok = hits >= min(2, len(set(expectation_terms))) if expectation_terms else False
    return {"score": int(ok), "reason": f"fallback expectation keyword hits={hits}"}


def score_grounded_recommendation_response(
    case: dict[str, Any],
    response_text: str,
    retrieval_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response, parse_error = parse_response_json(response_text)
    required_fields = case_required_fields(case)
    retrieval_provenance = retrieval_provenance or {}
    retrieved_anchors = {
        _normal_anchor(str(anchor))
        for anchor in retrieval_provenance.get("retrieved_anchors", [])
        if str(anchor).strip()
    }
    if not isinstance(response, dict):
        axes = {
            str(axis.get("axis", "axis")): {"score": 0, "reason": "response is not valid JSON"}
            for axis in case.get("scoring_axes") or []
        }
        retrieval_fields = {
            key: retrieval_provenance.get(key, 0 if key.endswith("_count") else [])
            for key in [
                "retrieval_tool_call_count",
                "retrieval_success_count",
                "retrieval_error_count",
                "retrieved_anchor_count",
                "retrieved_anchors",
            ]
        }
        return {
            "valid_json": False,
            "json_parse_error": parse_error,
            "required_fields_present": [],
            "missing_required_fields": required_fields,
            "required_field_coverage": 0.0 if required_fields else None,
            "rubric_axis_scores": axes,
            "rubric_axis_score": 0.0 if axes else None,
            "required_family_hits": [],
            "required_family_recall": None,
            "valid_anchor_count": 0,
            "invalid_anchor_count": 0,
            "citation_like_count": 0,
            "invalid_citation_like_count": 0,
            "evidence_bearing_claim_count": 0,
            "supported_evidence_claim_count": 0,
            "claim_support_precision": None,
            "final_anchor_count": 0,
            "final_anchor_from_retrieval_count": 0,
            "final_anchor_from_retrieval_rate": None,
            "retrieved_anchor_utilization_rate": None,
            "retrieved_required_family_hits": [],
            "retrieved_required_family_recall": None,
            "final_required_family_mention_hits": [],
            "final_required_family_mention_recall": None,
            "required_family_precision": None,
            "required_family_f1": None,
            "detected_evidence_families": [],
            "detected_evidence_family_count": 0,
            "retrieved_to_final_required_family_utilization": None,
            "retrieved_evidence_used_count": 0,
            "retrieved_evidence_omitted_count": 0,
            "retrieved_evidence_used_anchor_count": 0,
            "retrieved_evidence_used_anchor_from_retrieval_count": 0,
            "retrieved_evidence_used_anchor_from_retrieval_rate": None,
            "retrieved_evidence_used_required_family_hits": [],
            "retrieved_evidence_used_required_family_recall": None,
            "diagnostic_family_mapping_count": 0,
            "diagnostic_family_mapping_used_count": 0,
            "diagnostic_family_mapping_omitted_count": 0,
            "diagnostic_family_mapping_anchor_count": 0,
            "diagnostic_family_mapping_anchor_from_retrieval_count": 0,
            "diagnostic_family_mapping_anchor_from_retrieval_rate": None,
            "diagnostic_family_mapping_required_family_hits": [],
            "diagnostic_family_mapping_required_family_recall": None,
            "decision_field_required_keys": [],
            "decision_field_predicted_keys": [],
            "decision_field_hits": [],
            "decision_field_recall": None,
            "decision_field_precision": None,
            "decision_field_macro_f1": None,
            "decision_convergence_score": None,
            "required_action_keys": [],
            "predicted_action_keys": [],
            "required_action_hits": [],
            "required_action_recall": None,
            "required_action_precision": None,
            "required_action_f1": None,
            "canonical_convergence_score": None,
            **retrieval_fields,
        }

    response_blob = _json_text(response)
    present_fields = [field for field in required_fields if field in response and response.get(field) not in (None, "", [])]
    missing_fields = [field for field in required_fields if field not in present_fields]
    evidence_basis = response.get("evidence_basis")
    if not isinstance(evidence_basis, list):
        evidence_basis = []

    valid_anchor_count = 0
    invalid_anchor_count = 0
    citation_like_count = 0
    invalid_citation_like_count = 0
    evidence_bearing_claim_count = 0
    supported_evidence_claim_count = 0
    required_families = list((case.get("canonical_task") or {}).get("required_evidence_families") or [])
    required_family_hits: set[str] = set()
    final_anchors: set[str] = set()

    for item in evidence_basis:
        item_text = _json_text(item).lower()
        if not isinstance(item, dict):
            item_valid, item_invalid = _anchor_counts(item_text)
            final_anchors.update(_all_anchor_atoms(item_text))
            valid_anchor_count += item_valid
            invalid_anchor_count += item_invalid
            citation_like_count += item_valid + item_invalid
            invalid_citation_like_count += item_invalid
            continue

        basis_type = str(item.get("basis_type") or "").strip()
        reference = _json_text(item.get("reference"))
        item_valid, item_invalid = _anchor_counts(reference)
        final_anchors.update(_all_anchor_atoms(reference))
        valid_anchor_count += item_valid
        invalid_anchor_count += item_invalid
        if item_valid or item_invalid:
            citation_like_count += item_valid + item_invalid
            invalid_citation_like_count += item_invalid
        elif basis_type in EVIDENCE_BEARING_BASIS_TYPES and reference.strip():
            citation_like_count += 1
            invalid_citation_like_count += 1

        if item_valid:
            for family in required_families:
                if _family_hit(str(family), item_text):
                    required_family_hits.add(str(family))

        if basis_type in EVIDENCE_BEARING_BASIS_TYPES:
            evidence_bearing_claim_count += 1
            claim = str(item.get("claim") or "").strip()
            support_span = str(item.get("support_span") or "").strip()
            verifiable = item.get("verifiable") is True
            if claim and support_span and verifiable and item_valid:
                supported_evidence_claim_count += 1

    axes: dict[str, Any] = {}
    for axis in case.get("scoring_axes") or []:
        axis_name = str(axis.get("axis", "axis"))
        axes[axis_name] = _score_axis(
            axis_name,
            str(axis.get("canonical_expectation") or ""),
            response_blob,
            sorted(required_family_hits),
            valid_anchor_count,
            len(required_families),
        )
    axis_values = [float(payload["score"]) for payload in axes.values()]
    final_from_retrieval = final_anchors & retrieved_anchors
    case_text = _case_expectation_text(case)
    evidence_basis_text = _json_text(evidence_basis)
    retrieved_text = str(retrieval_provenance.get("_retrieved_text") or "")
    retrieved_required_family_hits = _family_hits(
        required_families,
        "\n".join([retrieved_text, " ".join(sorted(retrieved_anchors))]),
    )
    retrieved_evidence_used_stats = _retrieved_evidence_used_stats(
        response,
        required_families,
        retrieved_anchors,
    )
    diagnostic_family_mapping_stats = _diagnostic_family_mapping_stats(
        response,
        required_families,
        retrieved_anchors,
    )
    final_required_family_mention_hits = _family_hits(required_families, response_blob)
    detected_evidence_families = _family_hits(
        _known_evidence_families(required_families),
        evidence_basis_text,
    )
    family_prf = _family_prf(
        required_families,
        sorted(required_family_hits),
        detected_evidence_families,
    )
    retrieved_hit_keys = {_family_key(family) for family in retrieved_required_family_hits}
    final_hit_keys = {_family_key(family) for family in required_family_hits}
    decision_required_keys = _keyword_hits(case_text, DECISION_KEYWORD_ALIASES)
    decision_predicted_keys = _keyword_hits(response_blob, DECISION_KEYWORD_ALIASES)
    decision_prf = _set_prf(decision_required_keys, decision_predicted_keys)
    action_required_keys = _keyword_hits(case_text, ACTION_KEYWORD_ALIASES)
    action_predicted_keys = _keyword_hits(_response_action_text(response), ACTION_KEYWORD_ALIASES)
    action_prf = _set_prf(action_required_keys, action_predicted_keys)
    canonical_fields = {
        "retrieved_required_family_hits": retrieved_required_family_hits,
        "retrieved_required_family_recall": (
            len(retrieved_required_family_hits) / len(required_families)
            if required_families
            else None
        ),
        "final_required_family_mention_hits": final_required_family_mention_hits,
        "final_required_family_mention_recall": (
            len(final_required_family_mention_hits) / len(required_families)
            if required_families
            else None
        ),
        "detected_evidence_families": detected_evidence_families,
        "retrieved_to_final_required_family_utilization": _safe_rate(
            len(retrieved_hit_keys & final_hit_keys),
            len(retrieved_hit_keys),
        ),
        **retrieved_evidence_used_stats,
        **diagnostic_family_mapping_stats,
        "decision_field_required_keys": decision_required_keys,
        "decision_field_predicted_keys": decision_predicted_keys,
        "decision_field_hits": decision_prf["hits"],
        "decision_field_recall": decision_prf["recall"],
        "decision_field_precision": decision_prf["precision"],
        "decision_field_macro_f1": decision_prf["f1"],
        "decision_convergence_score": _decision_axis_score(axes),
        "required_action_keys": action_required_keys,
        "predicted_action_keys": action_predicted_keys,
        "required_action_hits": action_prf["hits"],
        "required_action_recall": action_prf["recall"],
        "required_action_precision": action_prf["precision"],
        "required_action_f1": action_prf["f1"],
        **family_prf,
    }
    canonical_fields["canonical_convergence_score"] = _canonical_convergence_score(
        {
            **canonical_fields,
            "required_family_f1": family_prf["required_family_f1"],
        }
    )

    return {
        "valid_json": True,
        "json_parse_error": None,
        "required_fields_present": present_fields,
        "missing_required_fields": missing_fields,
        "required_field_coverage": (len(present_fields) / len(required_fields)) if required_fields else None,
        "rubric_axis_scores": axes,
        "rubric_axis_score": (sum(axis_values) / len(axis_values)) if axis_values else None,
        "required_family_hits": sorted(required_family_hits),
        "required_family_recall": (len(required_family_hits) / len(required_families)) if required_families else None,
        "valid_anchor_count": valid_anchor_count,
        "invalid_anchor_count": invalid_anchor_count,
        "citation_like_count": citation_like_count,
        "invalid_citation_like_count": invalid_citation_like_count,
        "evidence_bearing_claim_count": evidence_bearing_claim_count,
        "supported_evidence_claim_count": supported_evidence_claim_count,
        "claim_support_precision": (
            supported_evidence_claim_count / evidence_bearing_claim_count
            if evidence_bearing_claim_count
            else None
        ),
        "final_anchor_count": len(final_anchors),
        "final_anchor_from_retrieval_count": len(final_from_retrieval),
        "final_anchor_from_retrieval_rate": (
            len(final_from_retrieval) / len(final_anchors)
            if final_anchors
            else None
        ),
        "retrieved_anchor_utilization_rate": (
            len(final_from_retrieval) / len(retrieved_anchors)
            if retrieved_anchors
            else None
        ),
        "retrieval_tool_call_count": retrieval_provenance.get("retrieval_tool_call_count", 0),
        "retrieval_success_count": retrieval_provenance.get("retrieval_success_count", 0),
        "retrieval_error_count": retrieval_provenance.get("retrieval_error_count", 0),
        "retrieved_anchor_count": retrieval_provenance.get("retrieved_anchor_count", 0),
        "retrieved_anchors": sorted(retrieved_anchors),
        **canonical_fields,
    }


def score_contract_response(
    case: dict[str, Any],
    response_text: str,
    retrieval_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score non-grounded task shapes without pretending to grade hidden science.

    This is intentionally contract-level: valid JSON, declared top-level field
    coverage, simple evidence-anchor accounting, and retrieval provenance. The
    task-specific canonical axes remain unscored until dedicated scientific
    scorers exist for each task shape.
    """

    response, parse_error = parse_response_json(response_text)
    required_fields = case_required_fields(case) or ["answer"]
    retrieval_provenance = retrieval_provenance or {}
    retrieved_anchors = {
        _normal_anchor(str(anchor))
        for anchor in retrieval_provenance.get("retrieved_anchors", [])
        if str(anchor).strip()
    }
    base = _unscored_fields("contract_only", retrieval_provenance)
    base["metric_scope"] = "contract_only"
    base["canonical_metric_available"] = False

    if not isinstance(response, dict):
        base.update(
            {
                "valid_json": False,
                "json_parse_error": parse_error,
                "required_fields_present": [],
                "missing_required_fields": required_fields,
                "required_field_coverage": 0.0 if required_fields else None,
                "rubric_axis_scores": {
                    str(axis.get("axis", "axis")): {
                        "score": None,
                        "reason": "contract-only scorer: response is not valid JSON",
                    }
                    for axis in case.get("scoring_axes") or []
                },
            }
        )
        return base

    present_fields = [
        field
        for field in required_fields
        if field in response and response.get(field) not in (None, "", [])
    ]
    missing_fields = [field for field in required_fields if field not in present_fields]
    response_blob = _json_text(response)
    evidence_basis = response.get("evidence_basis")
    if not isinstance(evidence_basis, list):
        evidence_basis = []

    valid_anchor_count = 0
    invalid_anchor_count = 0
    citation_like_count = 0
    invalid_citation_like_count = 0
    evidence_bearing_claim_count = 0
    supported_evidence_claim_count = 0
    final_anchors: set[str] = set()

    for item in evidence_basis:
        item_text = _json_text(item)
        item_valid, item_invalid = _anchor_counts(item_text)
        final_anchors.update(_all_anchor_atoms(item_text))
        valid_anchor_count += item_valid
        invalid_anchor_count += item_invalid
        citation_like_count += item_valid + item_invalid
        invalid_citation_like_count += item_invalid

        if isinstance(item, dict):
            basis_type = str(item.get("basis_type") or "").strip()
            claim = str(item.get("claim") or "").strip()
            support_span = str(item.get("support_span") or "").strip()
            verifiable = item.get("verifiable") is True
            if basis_type in EVIDENCE_BEARING_BASIS_TYPES or basis_type == "artifact":
                evidence_bearing_claim_count += 1
                if claim and support_span and verifiable and (item_valid or basis_type == "artifact"):
                    supported_evidence_claim_count += 1

    final_from_retrieval = final_anchors & retrieved_anchors
    rubric_axis_scores = {
        str(axis.get("axis", "axis")): {
            "score": None,
            "reason": "contract-only scorer: task-specific canonical metric not implemented",
        }
        for axis in case.get("scoring_axes") or []
    }

    base.update(
        {
            "valid_json": True,
            "json_parse_error": None,
            "required_fields_present": present_fields,
            "missing_required_fields": missing_fields,
            "required_field_coverage": (
                len(present_fields) / len(required_fields) if required_fields else None
            ),
            "rubric_axis_scores": rubric_axis_scores,
            "rubric_axis_score": None,
            "valid_anchor_count": valid_anchor_count,
            "invalid_anchor_count": invalid_anchor_count,
            "citation_like_count": citation_like_count,
            "invalid_citation_like_count": invalid_citation_like_count,
            "evidence_bearing_claim_count": evidence_bearing_claim_count,
            "supported_evidence_claim_count": supported_evidence_claim_count,
            "claim_support_precision": (
                supported_evidence_claim_count / evidence_bearing_claim_count
                if evidence_bearing_claim_count
                else None
            ),
            "final_anchor_count": len(final_anchors),
            "final_anchor_from_retrieval_count": len(final_from_retrieval),
            "final_anchor_from_retrieval_rate": (
                len(final_from_retrieval) / len(final_anchors) if final_anchors else None
            ),
            "retrieved_anchor_utilization_rate": (
                len(final_from_retrieval) / len(retrieved_anchors) if retrieved_anchors else None
            ),
            "retrieval_tool_call_count": retrieval_provenance.get(
                "retrieval_tool_call_count", 0
            ),
            "retrieval_success_count": retrieval_provenance.get("retrieval_success_count", 0),
            "retrieval_error_count": retrieval_provenance.get("retrieval_error_count", 0),
            "retrieved_anchor_count": retrieval_provenance.get("retrieved_anchor_count", 0),
            "retrieved_anchors": sorted(retrieved_anchors),
        }
    )
    return base


def _case_for_record(record: dict[str, Any], cases_root: Path) -> dict[str, Any] | None:
    episode_dir = Path(str(record.get("episode_dir") or ""))
    prompt_json = episode_dir / "prompt.json"
    if prompt_json.exists():
        prompt_payload = read_json(prompt_json)
        case_path_value = prompt_payload.get("case_path")
        if case_path_value:
            case_path = Path(str(case_path_value))
            if not case_path.is_absolute():
                case_path = cases_root / case_path
            if case_path.exists():
                return read_json(case_path)
    case_id = str(record.get("case_id") or "")
    if case_id:
        for path in cases_root.glob("case_*.json"):
            try:
                candidate = read_json(path)
            except Exception:
                continue
            if candidate.get("case_id") == case_id:
                return candidate
    return None


def _record_status(record_or_metric: dict[str, Any]) -> str:
    return str(record_or_metric.get("status") or "")


def _br_condition(record_or_metric: dict[str, Any]) -> str:
    condition = str(record_or_metric.get("condition") or "")
    br_mode = str(record_or_metric.get("br_mode") or "")
    if _br_mcp_required(br_mode) or "with_br_required" in condition:
        return "with_br_required"
    if _br_mcp_enabled(br_mode) or "with_br" in condition:
        return "with_br"
    if br_mode == "without_br" or "without_br" in condition:
        return "without_br"
    return "unknown"


def _br_tool_names(tools_used: Any) -> list[str]:
    if not isinstance(tools_used, list):
        return []
    return sorted(
        {
            _normalize_tool_label(str(tool))
            for tool in tools_used
            if _is_br_tool_label(_normalize_tool_label(str(tool)))
        }
    )


def _add_br_usage_fields(
    metric: dict[str, Any],
    record: dict[str, Any],
    retrieval_provenance: dict[str, Any],
) -> None:
    br_tool_names = _br_tool_names(record.get("tools_used") or [])
    retrieval_tool_call_count = int(retrieval_provenance.get("retrieval_tool_call_count") or 0)
    record_tool_call_count = int(record.get("tool_call_count") or 0)
    br_tool_call_count = retrieval_tool_call_count
    if br_tool_call_count == 0 and br_tool_names:
        br_tool_call_count = max(record_tool_call_count, len(br_tool_names))
    metric.update(
        {
            "br_mode": record.get("br_mode"),
            "br_condition": _br_condition(record),
            "br_tool_names": br_tool_names,
            "br_tool_called": bool(br_tool_names) or retrieval_tool_call_count > 0,
            "br_tool_call_count": br_tool_call_count,
            "retrieval_tool_called": retrieval_tool_call_count > 0,
        }
    )


def _is_materialized_status(status: str) -> bool:
    return status in MATERIALIZED_STATUSES


def _is_attempted_record(record_or_metric: dict[str, Any]) -> bool:
    status = _record_status(record_or_metric)
    if _is_materialized_status(status):
        return False
    if record_or_metric.get("execute_requested") is False:
        return False
    return True


def _is_success_status(status: str) -> bool:
    return status == "succeeded"


def _is_failed_status(status: str) -> bool:
    return status in FAILED_STATUSES or status.startswith("failed")


def _record_text_file(record: dict[str, Any], key: str) -> str:
    path_value = str(((record.get("paths") or {}).get(key)) or "")
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _availability_class(record: dict[str, Any], stderr_text: str) -> str:
    status = _record_status(record)
    if _is_materialized_status(status):
        return "prompt_packet_only"
    if status == "skipped_execution_unsupported_task_shape":
        return "unsupported_task_shape"
    if status == "skipped_execution_unavailable_agent":
        return "agent_unavailable"
    if _is_success_status(status):
        return "completed"
    if _has_provider_or_account_limit(stderr_text):
        return "provider_or_account_limit"
    if status == "timed_out" or record.get("timed_out") is True:
        return "timeout"
    if status == "failed_output_capture":
        return "output_capture_failed"
    if status == "failed_error_event":
        return "agent_error_event"
    if _is_failed_status(status):
        return "execution_failed"
    return "other"


def _unscored_fields(
    reason: str,
    retrieval_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retrieval_provenance = retrieval_provenance or {}
    return {
        "scored": False,
        "unscored_reason": reason,
        "valid_json": None,
        "json_parse_error": None,
        "required_fields_present": [],
        "missing_required_fields": [],
        "required_field_coverage": None,
        "rubric_axis_scores": {},
        "rubric_axis_score": None,
        "required_family_hits": [],
        "required_family_recall": None,
        "valid_anchor_count": 0,
        "invalid_anchor_count": 0,
        "citation_like_count": 0,
        "invalid_citation_like_count": 0,
        "evidence_bearing_claim_count": 0,
        "supported_evidence_claim_count": 0,
        "claim_support_precision": None,
        "final_anchor_count": 0,
        "final_anchor_from_retrieval_count": 0,
        "final_anchor_from_retrieval_rate": None,
        "retrieved_anchor_utilization_rate": None,
        "retrieval_tool_call_count": retrieval_provenance.get("retrieval_tool_call_count", 0),
        "retrieval_success_count": retrieval_provenance.get("retrieval_success_count", 0),
        "retrieval_error_count": retrieval_provenance.get("retrieval_error_count", 0),
        "retrieved_anchor_count": retrieval_provenance.get("retrieved_anchor_count", 0),
        "retrieved_anchors": retrieval_provenance.get("retrieved_anchors", []),
        "valid_anchor_rate": None,
        "citation_hallucination_rate": None,
        "retrieval_success_rate": None,
        "grounding_quality_score": None,
        "retrieved_required_family_hits": [],
        "retrieved_required_family_recall": None,
        "final_required_family_mention_hits": [],
        "final_required_family_mention_recall": None,
        "required_family_precision": None,
        "required_family_f1": None,
        "detected_evidence_families": [],
        "detected_evidence_family_count": 0,
        "retrieved_to_final_required_family_utilization": None,
        "retrieved_evidence_used_count": 0,
        "retrieved_evidence_omitted_count": 0,
        "retrieved_evidence_used_anchor_count": 0,
        "retrieved_evidence_used_anchor_from_retrieval_count": 0,
        "retrieved_evidence_used_anchor_from_retrieval_rate": None,
        "retrieved_evidence_used_required_family_hits": [],
        "retrieved_evidence_used_required_family_recall": None,
        "diagnostic_family_mapping_count": 0,
        "diagnostic_family_mapping_used_count": 0,
        "diagnostic_family_mapping_omitted_count": 0,
        "diagnostic_family_mapping_anchor_count": 0,
        "diagnostic_family_mapping_anchor_from_retrieval_count": 0,
        "diagnostic_family_mapping_anchor_from_retrieval_rate": None,
        "diagnostic_family_mapping_required_family_hits": [],
        "diagnostic_family_mapping_required_family_recall": None,
        "decision_field_required_keys": [],
        "decision_field_predicted_keys": [],
        "decision_field_hits": [],
        "decision_field_recall": None,
        "decision_field_precision": None,
        "decision_field_macro_f1": None,
        "decision_convergence_score": None,
        "required_action_keys": [],
        "predicted_action_keys": [],
        "required_action_hits": [],
        "required_action_recall": None,
        "required_action_precision": None,
        "required_action_f1": None,
        "canonical_convergence_score": None,
    }


def _episode_grounding_quality(metric: dict[str, Any]) -> float | None:
    valid_anchor_count = int(metric.get("valid_anchor_count") or 0)
    invalid_anchor_count = int(metric.get("invalid_anchor_count") or 0)
    citation_like_count = int(metric.get("citation_like_count") or 0)
    invalid_citation_like_count = int(metric.get("invalid_citation_like_count") or 0)
    valid_anchor_rate = _safe_rate(valid_anchor_count, valid_anchor_count + invalid_anchor_count)
    citation_hallucination_rate = _safe_rate(invalid_citation_like_count, citation_like_count)
    components = [
        metric.get("required_family_recall"),
        valid_anchor_rate,
        (1.0 - citation_hallucination_rate) if citation_hallucination_rate is not None else None,
        metric.get("claim_support_precision"),
        metric.get("final_anchor_from_retrieval_rate"),
    ]
    values = [
        float(value)
        for value in components
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sum(values) / len(values) if values else None


def _add_episode_rate_metrics(metric: dict[str, Any]) -> None:
    valid_anchor_count = int(metric.get("valid_anchor_count") or 0)
    invalid_anchor_count = int(metric.get("invalid_anchor_count") or 0)
    citation_like_count = int(metric.get("citation_like_count") or 0)
    invalid_citation_like_count = int(metric.get("invalid_citation_like_count") or 0)
    retrieval_success_count = int(metric.get("retrieval_success_count") or 0)
    retrieval_error_count = int(metric.get("retrieval_error_count") or 0)
    metric["valid_anchor_rate"] = _safe_rate(
        valid_anchor_count,
        valid_anchor_count + invalid_anchor_count,
    )
    metric["citation_hallucination_rate"] = _safe_rate(
        invalid_citation_like_count,
        citation_like_count,
    )
    metric["retrieval_success_rate"] = _safe_rate(
        retrieval_success_count,
        retrieval_success_count + retrieval_error_count,
    )


def score_episode_record(record: dict[str, Any], cases_root: Path) -> dict[str, Any]:
    case = _case_for_record(record, cases_root)
    output_path_value = str(((record.get("paths") or {}).get("last_message")) or "")
    output_path = Path(output_path_value) if output_path_value else None
    response_text = (
        output_path.read_text(encoding="utf-8", errors="replace")
        if output_path is not None and output_path.is_file()
        else ""
    )
    events_path_value = str(((record.get("paths") or {}).get("events")) or "")
    retrieval_provenance = (
        extract_retrieval_provenance(Path(events_path_value))
        if events_path_value
        else extract_retrieval_provenance(Path(""))
    )
    status = _record_status(record)
    stderr_text = _record_text_file(record, "stderr")
    events_text = _record_text_file(record, "events")
    diagnostic_text = "\n".join(part for part in [stderr_text, events_text] if part)
    metric: dict[str, Any] = {
        "case_id": record.get("case_id"),
        "variant_id": record.get("variant_id"),
        "variant_type": record.get("variant_type"),
        "condition": record.get("condition"),
        "runner": record.get("runner"),
        "model": record.get("model"),
        "br_mode": record.get("br_mode"),
        "episode_dir": record.get("episode_dir"),
        "status": record.get("status"),
        "wall_time_s": record.get("wall_time_s"),
        "tool_call_count": record.get("tool_call_count", 0),
        "tools_used": record.get("tools_used", []),
        "response_chars": len(response_text),
        "case_loaded": case is not None,
        "canonical_validation_status": canonical_validation_status(case),
        "canonical_validation_tier": canonical_validation_tier(case),
        "canonical_validation_blocking": canonical_validation_blocking(case),
        "task_shape": record.get("task_shape"),
        "execute_requested": record.get("execute_requested"),
        "attempted": _is_attempted_record(record),
        "succeeded": _is_success_status(status),
        "timed_out": status == "timed_out" or record.get("timed_out") is True,
        "failed": _is_failed_status(status),
        "materialized": _is_materialized_status(status),
        "availability_class": _availability_class(record, diagnostic_text),
    }
    _add_br_usage_fields(metric, record, retrieval_provenance)
    if not _is_success_status(status):
        metric.update(_unscored_fields(f"status={status or 'missing'}", retrieval_provenance))
        _add_episode_rate_metrics(metric)
        return metric
    if case is None:
        metric.update(_unscored_fields("case_not_loaded", retrieval_provenance))
        _add_episode_rate_metrics(metric)
        metric["metric_error"] = "case_not_loaded"
        return metric
    task_shape = str(case.get("task_shape") or record.get("task_shape") or "")
    if task_shape == "grounded_recommendation":
        score = score_grounded_recommendation_response(case, response_text, retrieval_provenance)
        metric["metric_scope"] = "canonical_grounded_recommendation"
        metric["canonical_metric_available"] = True
    else:
        score = score_contract_response(case, response_text, retrieval_provenance)
        metric["metric_scope"] = "contract_only"
        metric["canonical_metric_available"] = False
    metric.update(score)
    metric["scored"] = score.get("valid_json") is True
    metric["unscored_reason"] = None if metric["scored"] else "invalid_json"
    _add_episode_rate_metrics(metric)
    metric["grounding_quality_score"] = (
        _episode_grounding_quality(metric) if metric["scored"] else None
    )
    return metric


def _mean(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _percentile(values: list[float], q: float) -> float | None:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = max(0.0, min(1.0, q)) * (len(clean) - 1)
    lower = int(position)
    upper = min(lower + 1, len(clean) - 1)
    weight = position - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _safe_rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    availability_counts: dict[str, int] = {}
    tools: set[str] = set()
    for row in rows:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        availability = str(row.get("availability_class") or "unknown")
        availability_counts[availability] = availability_counts.get(availability, 0) + 1
        tools.update(str(tool) for tool in row.get("tools_used") or [])

    attempted_rows = [row for row in rows if row.get("attempted") is True]
    succeeded_rows = [row for row in rows if row.get("succeeded") is True]
    scored_rows = [row for row in rows if row.get("scored") is True]
    valid_json_rows = [row for row in rows if row.get("valid_json") is True]
    timed_out_rows = [row for row in rows if row.get("timed_out") is True]
    failed_rows = [row for row in rows if row.get("failed") is True]
    materialized_rows = [row for row in rows if row.get("materialized") is True]
    br_conditions = sorted({str(row.get("br_condition") or "unknown") for row in rows})
    br_tool_called_attempted = [
        row for row in attempted_rows if row.get("br_tool_called") is True
    ]
    br_tool_called_scored = [
        row for row in scored_rows if row.get("br_tool_called") is True
    ]
    retrieval_tool_called_attempted = [
        row for row in attempted_rows if row.get("retrieval_tool_called") is True
    ]
    retrieval_tool_called_scored = [
        row for row in scored_rows if row.get("retrieval_tool_called") is True
    ]

    rubric_scores = [
        row.get("rubric_axis_score")
        for row in scored_rows
        if isinstance(row.get("rubric_axis_score"), (int, float))
    ]
    family_recalls = [
        row.get("required_family_recall")
        for row in scored_rows
        if isinstance(row.get("required_family_recall"), (int, float))
    ]
    field_coverages = [
        row.get("required_field_coverage")
        for row in scored_rows
        if isinstance(row.get("required_field_coverage"), (int, float))
    ]
    canonical_scores = [
        row.get("canonical_convergence_score")
        for row in scored_rows
        if isinstance(row.get("canonical_convergence_score"), (int, float))
    ]
    decision_f1s = [
        row.get("decision_field_macro_f1")
        for row in scored_rows
        if isinstance(row.get("decision_field_macro_f1"), (int, float))
    ]
    action_f1s = [
        row.get("required_action_f1")
        for row in scored_rows
        if isinstance(row.get("required_action_f1"), (int, float))
    ]
    family_precisions = [
        row.get("required_family_precision")
        for row in scored_rows
        if isinstance(row.get("required_family_precision"), (int, float))
    ]
    family_f1s = [
        row.get("required_family_f1")
        for row in scored_rows
        if isinstance(row.get("required_family_f1"), (int, float))
    ]
    retrieved_family_recalls = [
        row.get("retrieved_required_family_recall")
        for row in scored_rows
        if isinstance(row.get("retrieved_required_family_recall"), (int, float))
    ]
    retrieved_to_final_family_utilizations = [
        row.get("retrieved_to_final_required_family_utilization")
        for row in scored_rows
        if isinstance(row.get("retrieved_to_final_required_family_utilization"), (int, float))
    ]
    retrieved_evidence_used_family_recalls = [
        row.get("retrieved_evidence_used_required_family_recall")
        for row in scored_rows
        if isinstance(row.get("retrieved_evidence_used_required_family_recall"), (int, float))
    ]
    retrieved_evidence_used_anchor_from_retrieval_rates = [
        row.get("retrieved_evidence_used_anchor_from_retrieval_rate")
        for row in scored_rows
        if isinstance(row.get("retrieved_evidence_used_anchor_from_retrieval_rate"), (int, float))
    ]
    diagnostic_family_mapping_recalls = [
        row.get("diagnostic_family_mapping_required_family_recall")
        for row in scored_rows
        if isinstance(row.get("diagnostic_family_mapping_required_family_recall"), (int, float))
    ]
    diagnostic_family_mapping_anchor_from_retrieval_rates = [
        row.get("diagnostic_family_mapping_anchor_from_retrieval_rate")
        for row in scored_rows
        if isinstance(row.get("diagnostic_family_mapping_anchor_from_retrieval_rate"), (int, float))
    ]
    valid_anchor_count = sum(int(row.get("valid_anchor_count") or 0) for row in scored_rows)
    invalid_anchor_count = sum(int(row.get("invalid_anchor_count") or 0) for row in scored_rows)
    citation_like_count = sum(int(row.get("citation_like_count") or 0) for row in scored_rows)
    invalid_citation_like_count = sum(int(row.get("invalid_citation_like_count") or 0) for row in scored_rows)
    evidence_claims = sum(int(row.get("evidence_bearing_claim_count") or 0) for row in scored_rows)
    supported_claims = sum(int(row.get("supported_evidence_claim_count") or 0) for row in scored_rows)
    final_anchor_count = sum(int(row.get("final_anchor_count") or 0) for row in scored_rows)
    final_from_retrieval_count = sum(int(row.get("final_anchor_from_retrieval_count") or 0) for row in scored_rows)
    retrieved_anchor_count = sum(int(row.get("retrieved_anchor_count") or 0) for row in scored_rows)
    retrieval_tool_call_count = sum(int(row.get("retrieval_tool_call_count") or 0) for row in scored_rows)
    retrieval_success_count = sum(int(row.get("retrieval_success_count") or 0) for row in scored_rows)
    retrieval_error_count = sum(int(row.get("retrieval_error_count") or 0) for row in scored_rows)
    retrieved_evidence_used_count = sum(int(row.get("retrieved_evidence_used_count") or 0) for row in scored_rows)
    retrieved_evidence_omitted_count = sum(int(row.get("retrieved_evidence_omitted_count") or 0) for row in scored_rows)
    diagnostic_family_mapping_count = sum(
        int(row.get("diagnostic_family_mapping_count") or 0) for row in scored_rows
    )
    diagnostic_family_mapping_used_count = sum(
        int(row.get("diagnostic_family_mapping_used_count") or 0) for row in scored_rows
    )
    diagnostic_family_mapping_omitted_count = sum(
        int(row.get("diagnostic_family_mapping_omitted_count") or 0) for row in scored_rows
    )
    attempted_retrieval_tool_call_count = sum(
        int(row.get("retrieval_tool_call_count") or 0) for row in attempted_rows
    )
    attempted_retrieval_success_count = sum(
        int(row.get("retrieval_success_count") or 0) for row in attempted_rows
    )
    attempted_retrieval_error_count = sum(
        int(row.get("retrieval_error_count") or 0) for row in attempted_rows
    )
    br_tool_call_count_attempted = sum(
        int(row.get("br_tool_call_count") or 0) for row in attempted_rows
    )
    br_tool_call_count_scored = sum(
        int(row.get("br_tool_call_count") or 0) for row in scored_rows
    )
    tool_calls = sum(int(row.get("tool_call_count") or 0) for row in rows)
    attempted_tool_calls = sum(int(row.get("tool_call_count") or 0) for row in attempted_rows)
    scored_tool_calls = sum(int(row.get("tool_call_count") or 0) for row in scored_rows)
    attempted_wall_times = [
        float(row.get("wall_time_s"))
        for row in attempted_rows
        if isinstance(row.get("wall_time_s"), (int, float))
    ]
    scored_wall_times = [
        float(row.get("wall_time_s"))
        for row in scored_rows
        if isinstance(row.get("wall_time_s"), (int, float))
    ]

    valid_anchor_rate = _safe_rate(valid_anchor_count, valid_anchor_count + invalid_anchor_count)
    citation_hallucination_rate = _safe_rate(invalid_citation_like_count, citation_like_count)
    claim_support_precision = _safe_rate(supported_claims, evidence_claims)
    final_anchor_from_retrieval_rate = _safe_rate(final_from_retrieval_count, final_anchor_count)
    retrieved_anchor_utilization_rate = _safe_rate(final_from_retrieval_count, retrieved_anchor_count)
    retrieval_success_rate = _safe_rate(retrieval_success_count, retrieval_success_count + retrieval_error_count)
    grounding_components = [
        _mean(family_recalls),
        valid_anchor_rate,
        (1.0 - citation_hallucination_rate) if citation_hallucination_rate is not None else None,
        claim_support_precision,
        final_anchor_from_retrieval_rate,
    ]
    grounding_quality_values = [value for value in grounding_components if value is not None]
    rubric_stddev = statistics.pstdev(rubric_scores) if len(rubric_scores) > 1 else 0.0 if rubric_scores else None

    return {
        "n": len(rows),
        "total_episodes": len(rows),
        "attempted": len(attempted_rows),
        "succeeded": len(succeeded_rows),
        "scored": len(scored_rows),
        "valid_json": len(valid_json_rows),
        "timed_out": len(timed_out_rows),
        "failed": len(failed_rows),
        "materialized": len(materialized_rows),
        "quality_denominator": "scored_valid_json_succeeded_rows",
        "availability_denominator": "attempted_rows",
        "actual_br_tool_use_denominator": "attempted_rows",
        "br_condition": br_conditions[0] if len(br_conditions) == 1 else "mixed",
        "status_counts": status_counts,
        "availability_counts": availability_counts,
        "attempt_rate": _safe_rate(len(attempted_rows), len(rows)),
        "success_rate_attempted": _safe_rate(len(succeeded_rows), len(attempted_rows)),
        "scored_rate_attempted": _safe_rate(len(scored_rows), len(attempted_rows)),
        "scored_rate_succeeded": _safe_rate(len(scored_rows), len(succeeded_rows)),
        "valid_json_rate_succeeded": _safe_rate(len(valid_json_rows), len(succeeded_rows)),
        "timeout_rate_attempted": _safe_rate(len(timed_out_rows), len(attempted_rows)),
        "failed_rate_attempted": _safe_rate(len(failed_rows), len(attempted_rows)),
        "valid_json_rate": _safe_rate(len(valid_json_rows), len(succeeded_rows)),
        "mean_wall_time_s": _mean(scored_wall_times),
        "mean_wall_time_attempted_s": _mean(attempted_wall_times),
        "total_tool_calls": tool_calls,
        "attempted_tool_calls": attempted_tool_calls,
        "scored_tool_calls": scored_tool_calls,
        "mean_tool_calls": _safe_rate(scored_tool_calls, len(scored_rows)),
        "mean_tool_calls_attempted": _safe_rate(attempted_tool_calls, len(attempted_rows)),
        "tools_used": sorted(tools),
        "br_tool_called_attempted": len(br_tool_called_attempted),
        "br_tool_called_scored": len(br_tool_called_scored),
        "br_tool_called_rate_attempted": _safe_rate(
            len(br_tool_called_attempted), len(attempted_rows)
        ),
        "br_tool_called_rate_scored": _safe_rate(len(br_tool_called_scored), len(scored_rows)),
        "br_tool_call_count_attempted": br_tool_call_count_attempted,
        "br_tool_call_count_scored": br_tool_call_count_scored,
        "retrieval_tool_called_attempted": len(retrieval_tool_called_attempted),
        "retrieval_tool_called_scored": len(retrieval_tool_called_scored),
        "retrieval_tool_called_rate_attempted": _safe_rate(
            len(retrieval_tool_called_attempted), len(attempted_rows)
        ),
        "retrieval_tool_called_rate_scored": _safe_rate(
            len(retrieval_tool_called_scored), len(scored_rows)
        ),
        "attempted_retrieval_tool_call_count": attempted_retrieval_tool_call_count,
        "attempted_retrieval_success_count": attempted_retrieval_success_count,
        "attempted_retrieval_error_count": attempted_retrieval_error_count,
        "attempted_retrieval_success_rate": _safe_rate(
            attempted_retrieval_success_count,
            attempted_retrieval_success_count + attempted_retrieval_error_count,
        ),
        "mean_required_field_coverage": _mean(field_coverages),
        "mean_canonical_convergence_score": _mean(canonical_scores),
        "worst_canonical_convergence_score": min(canonical_scores) if canonical_scores else None,
        "p10_canonical_convergence_score": _percentile(canonical_scores, 0.10),
        "mean_decision_field_macro_f1": _mean(decision_f1s),
        "mean_required_action_f1": _mean(action_f1s),
        "mean_required_family_precision": _mean(family_precisions),
        "mean_required_family_f1": _mean(family_f1s),
        "mean_retrieved_required_family_recall": _mean(retrieved_family_recalls),
        "mean_retrieved_to_final_required_family_utilization": _mean(
            retrieved_to_final_family_utilizations
        ),
        "mean_retrieved_evidence_used_required_family_recall": _mean(
            retrieved_evidence_used_family_recalls
        ),
        "mean_retrieved_evidence_used_anchor_from_retrieval_rate": _mean(
            retrieved_evidence_used_anchor_from_retrieval_rates
        ),
        "retrieved_evidence_used_count": retrieved_evidence_used_count,
        "retrieved_evidence_omitted_count": retrieved_evidence_omitted_count,
        "mean_diagnostic_family_mapping_required_family_recall": _mean(
            diagnostic_family_mapping_recalls
        ),
        "mean_diagnostic_family_mapping_anchor_from_retrieval_rate": _mean(
            diagnostic_family_mapping_anchor_from_retrieval_rates
        ),
        "diagnostic_family_mapping_count": diagnostic_family_mapping_count,
        "diagnostic_family_mapping_used_count": diagnostic_family_mapping_used_count,
        "diagnostic_family_mapping_omitted_count": diagnostic_family_mapping_omitted_count,
        "mean_rubric_axis_score": _mean(rubric_scores),
        "mean_required_family_recall": _mean(family_recalls),
        "valid_anchor_rate": valid_anchor_rate,
        "citation_hallucination_rate": citation_hallucination_rate,
        "claim_support_precision": claim_support_precision,
        "final_anchor_from_retrieval_rate": final_anchor_from_retrieval_rate,
        "retrieved_anchor_utilization_rate": retrieved_anchor_utilization_rate,
        "retrieval_success_rate": retrieval_success_rate,
        "grounding_quality_score": (
            sum(grounding_quality_values) / len(grounding_quality_values)
            if grounding_quality_values
            else None
        ),
        "prompt_robustness": {
            "rubric_axis_score_stddev": rubric_stddev,
            "min_rubric_axis_score": min(rubric_scores) if rubric_scores else None,
            "score_at_least_0_8_rate": (
                sum(1 for score in rubric_scores if score >= 0.8) / len(rubric_scores)
                if rubric_scores
                else None
            ),
            "score": (max(0.0, 1.0 - rubric_stddev) if rubric_stddev is not None else None),
        },
        "valid_anchor_count": valid_anchor_count,
        "invalid_anchor_count": invalid_anchor_count,
        "citation_like_count": citation_like_count,
        "invalid_citation_like_count": invalid_citation_like_count,
        "evidence_bearing_claim_count": evidence_claims,
        "supported_evidence_claim_count": supported_claims,
        "final_anchor_count": final_anchor_count,
        "final_anchor_from_retrieval_count": final_from_retrieval_count,
        "retrieved_anchor_count": retrieved_anchor_count,
        "retrieval_tool_call_count": retrieval_tool_call_count,
        "retrieval_success_count": retrieval_success_count,
        "retrieval_error_count": retrieval_error_count,
    }


def _pair_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("case_id") or ""), str(row.get("variant_id") or ""))


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    return _mean(
        [
            row.get(key)
            for row in rows
            if isinstance(row.get(key), (int, float))
        ]
    )


def _paired_condition_comparisons(
    by_condition: dict[str, dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conditions = set(by_condition)
    pairs = _condition_pairs(conditions)

    comparisons: list[dict[str, Any]] = []
    rows_by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in metric_rows:
        rows_by_condition.setdefault(str(row.get("condition")), []).append(row)

    for baseline, treatment in pairs:
        base = by_condition[baseline]
        treat = by_condition[treatment]
        base_by_key = {_pair_key(row): row for row in rows_by_condition.get(baseline, [])}
        treat_by_key = {_pair_key(row): row for row in rows_by_condition.get(treatment, [])}
        shared_keys = sorted(set(base_by_key) & set(treat_by_key))
        scored_pairs = [
            (base_by_key[key], treat_by_key[key])
            for key in shared_keys
            if base_by_key[key].get("scored") is True
            and treat_by_key[key].get("scored") is True
        ]
        base_scored = [base_row for base_row, _treat_row in scored_pairs]
        treat_scored = [treat_row for _base_row, treat_row in scored_pairs]

        def delta(key: str) -> float | None:
            left = _mean_metric(base_scored, key)
            right = _mean_metric(treat_scored, key)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return float(right) - float(left)
            return None

        baseline_mean_tool_calls = _mean_metric(base_scored, "tool_call_count")
        treatment_mean_tool_calls = _mean_metric(treat_scored, "tool_call_count")
        tool_overhead = (
            treatment_mean_tool_calls - baseline_mean_tool_calls
            if baseline_mean_tool_calls is not None and treatment_mean_tool_calls is not None
            else None
        )
        baseline_mean_wall_time = _mean_metric(base_scored, "wall_time_s")
        treatment_mean_wall_time = _mean_metric(treat_scored, "wall_time_s")
        latency_overhead = (
            treatment_mean_wall_time - baseline_mean_wall_time
            if baseline_mean_wall_time is not None and treatment_mean_wall_time is not None
            else None
        )
        grounding_delta = delta("grounding_quality_score")
        rubric_delta = delta("rubric_axis_score")
        br_tool_call_overhead = delta("br_tool_call_count")
        retrieval_tool_call_overhead = delta("retrieval_tool_call_count")
        comparisons.append(
            {
                "baseline_condition": baseline,
                "treatment_condition": treatment,
                "pairing_policy": "same case_id and variant_id; both rows must be scored",
                "available_pair_count": len(shared_keys),
                "paired_scored_count": len(scored_pairs),
                "unscored_or_unavailable_pair_count": len(shared_keys) - len(scored_pairs),
                "baseline_total_episodes": base.get("total_episodes", base.get("n")),
                "treatment_total_episodes": treat.get("total_episodes", treat.get("n")),
                "baseline_scored": base.get("scored"),
                "treatment_scored": treat.get("scored"),
                "quality_denominator": "paired_scored_episodes",
                "canonical_convergence_score_delta": delta("canonical_convergence_score"),
                "decision_field_macro_f1_delta": delta("decision_field_macro_f1"),
                "required_action_f1_delta": delta("required_action_f1"),
                "rubric_axis_score_delta": rubric_delta,
                "required_family_recall_delta": delta("required_family_recall"),
                "required_family_precision_delta": delta("required_family_precision"),
                "required_family_f1_delta": delta("required_family_f1"),
                "retrieved_required_family_recall_delta": delta("retrieved_required_family_recall"),
                "retrieved_to_final_required_family_utilization_delta": delta(
                    "retrieved_to_final_required_family_utilization"
                ),
                "diagnostic_family_mapping_required_family_recall_delta": delta(
                    "diagnostic_family_mapping_required_family_recall"
                ),
                "valid_anchor_rate_delta": delta("valid_anchor_rate"),
                "citation_hallucination_rate_delta": delta("citation_hallucination_rate"),
                "claim_support_precision_delta": delta("claim_support_precision"),
                "final_anchor_from_retrieval_rate_delta": delta("final_anchor_from_retrieval_rate"),
                "retrieval_success_rate_delta": delta("retrieval_success_rate"),
                "grounding_quality_score_delta": grounding_delta,
                "latency_overhead_s": latency_overhead,
                "tool_call_overhead": tool_overhead,
                "br_tool_call_overhead": br_tool_call_overhead,
                "retrieval_tool_call_overhead": retrieval_tool_call_overhead,
                "baseline_br_tool_called_rate_scored": _safe_rate(
                    sum(1 for row in base_scored if row.get("br_tool_called") is True),
                    len(base_scored),
                ),
                "treatment_br_tool_called_rate_scored": _safe_rate(
                    sum(1 for row in treat_scored if row.get("br_tool_called") is True),
                    len(treat_scored),
                ),
                "tool_efficiency": {
                    "grounding_quality_delta_per_tool_call": (
                        grounding_delta / tool_overhead
                        if grounding_delta is not None and tool_overhead and tool_overhead > 0
                        else None
                    ),
                    "grounding_quality_delta_per_br_tool_call": (
                        grounding_delta / br_tool_call_overhead
                        if grounding_delta is not None
                        and br_tool_call_overhead
                        and br_tool_call_overhead > 0
                        else None
                    ),
                    "rubric_axis_delta_per_tool_call": (
                        rubric_delta / tool_overhead
                        if rubric_delta is not None and tool_overhead and tool_overhead > 0
                        else None
                    ),
                    "grounding_quality_delta_per_second": (
                        grounding_delta / latency_overhead
                        if grounding_delta is not None and latency_overhead and latency_overhead > 0
                        else None
                    ),
                },
            }
        )
    return comparisons


def _overall_status_summary(metric_rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    availability_counts: dict[str, int] = {}
    canonical_validation_tier_counts: dict[str, int] = {}
    for row in metric_rows:
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        availability = str(row.get("availability_class") or "unknown")
        availability_counts[availability] = availability_counts.get(availability, 0) + 1
        tier = str(row.get("canonical_validation_tier") or "unknown")
        canonical_validation_tier_counts[tier] = canonical_validation_tier_counts.get(tier, 0) + 1

    attempted = sum(1 for row in metric_rows if row.get("attempted") is True)
    succeeded = sum(1 for row in metric_rows if row.get("succeeded") is True)
    scored = sum(1 for row in metric_rows if row.get("scored") is True)
    valid_json = sum(1 for row in metric_rows if row.get("valid_json") is True)
    timed_out = sum(1 for row in metric_rows if row.get("timed_out") is True)
    failed = sum(1 for row in metric_rows if row.get("failed") is True)
    materialized = sum(1 for row in metric_rows if row.get("materialized") is True)
    canonical_blocking = sum(
        1 for row in metric_rows if row.get("canonical_validation_blocking") is True
    )
    br_tool_called_attempted = sum(
        1
        for row in metric_rows
        if row.get("attempted") is True and row.get("br_tool_called") is True
    )
    retrieval_tool_called_attempted = sum(
        1
        for row in metric_rows
        if row.get("attempted") is True and row.get("retrieval_tool_called") is True
    )
    br_tool_call_count_attempted = sum(
        int(row.get("br_tool_call_count") or 0)
        for row in metric_rows
        if row.get("attempted") is True
    )
    retrieval_tool_call_count_attempted = sum(
        int(row.get("retrieval_tool_call_count") or 0)
        for row in metric_rows
        if row.get("attempted") is True
    )
    return {
        "total_episodes": len(metric_rows),
        "attempted": attempted,
        "succeeded": succeeded,
        "scored": scored,
        "valid_json": valid_json,
        "timed_out": timed_out,
        "failed": failed,
        "materialized": materialized,
        "status_counts": status_counts,
        "availability_counts": availability_counts,
        "canonical_validation_tier_counts": canonical_validation_tier_counts,
        "canonical_validation_blocking": canonical_blocking,
        "attempt_rate": _safe_rate(attempted, len(metric_rows)),
        "success_rate_attempted": _safe_rate(succeeded, attempted),
        "scored_rate_attempted": _safe_rate(scored, attempted),
        "scored_rate_succeeded": _safe_rate(scored, succeeded),
        "valid_json_rate_succeeded": _safe_rate(valid_json, succeeded),
        "timeout_rate_attempted": _safe_rate(timed_out, attempted),
        "failed_rate_attempted": _safe_rate(failed, attempted),
        "prompt_packet_only": bool(metric_rows) and materialized == len(metric_rows),
        "executable_result_claim_eligible": attempted > 0 and scored > 0,
        "benchmark_grade_claim_eligible": attempted > 0 and scored > 0 and canonical_blocking == 0,
        "quality_denominator": "scored_valid_json_succeeded_rows",
        "availability_denominator": "attempted_rows",
        "actual_br_tool_use_denominator": "attempted_rows",
        "br_tool_called_attempted": br_tool_called_attempted,
        "br_tool_called_rate_attempted": _safe_rate(br_tool_called_attempted, attempted),
        "br_tool_call_count_attempted": br_tool_call_count_attempted,
        "retrieval_tool_called_attempted": retrieval_tool_called_attempted,
        "retrieval_tool_called_rate_attempted": _safe_rate(
            retrieval_tool_called_attempted,
            attempted,
        ),
        "retrieval_tool_call_count_attempted": retrieval_tool_call_count_attempted,
    }


def _run_evidence_policy(run_dir: Path, metric_rows: list[dict[str, Any]]) -> str:
    if metric_rows and all(row.get("materialized") is True for row in metric_rows):
        return "prompt_packet_only"
    name = run_dir.name.lower()
    retry_markers = ("retry", "topup", "best", "probe", "rerun")
    if any(marker in name for marker in retry_markers):
        return "retry_or_topup_attempts"
    return "single_run_attempts"


def write_metrics_report(run_dir: Path, metrics: dict[str, Any]) -> Path:
    report_path = run_dir / "METRICS_REPORT.md"
    status = metrics.get("status_summary") or {}
    lines = [
        "# Reproducibility Audit Metrics Report",
        "",
        f"Run: `{run_dir}`",
        "",
        f"Evidence policy: `{metrics.get('evidence_policy')}`",
        "",
        "## Status Semantics",
        "",
        "| Field | Count |",
        "| --- | ---: |",
    ]
    for key in [
        "total_episodes",
        "attempted",
        "succeeded",
        "scored",
        "valid_json",
        "timed_out",
        "failed",
        "materialized",
    ]:
        lines.append(f"| `{key}` | {status.get(key, 0)} |")
    lines.extend(
        [
            "",
            f"Quality denominator: `{status.get('quality_denominator')}`",
            "",
            f"Availability denominator: `{status.get('availability_denominator')}`",
            "",
            f"Actual BR tool-use denominator: `{status.get('actual_br_tool_use_denominator')}`",
            "",
            f"Prompt-packet only: `{status.get('prompt_packet_only')}`",
            "",
            f"Executable-result claim eligible: `{status.get('executable_result_claim_eligible')}`",
            "",
            f"Benchmark-grade canonical claim eligible: `{status.get('benchmark_grade_claim_eligible')}`",
            "",
            f"Canonical validation tiers: `{status.get('canonical_validation_tier_counts')}`",
            "",
            f"Attempted rows with actual BR tool use: `{status.get('br_tool_called_attempted', 0)}`",
            "",
            f"Attempted rows with actual retrieval use: `{status.get('retrieval_tool_called_attempted', 0)}`",
            "",
            "## Report Tables",
            "",
            "| Table | Path |",
            "| --- | --- |",
        ]
    )
    for name, path in sorted((metrics.get("report_tables") or {}).items()):
        lines.append(f"| `{name}` | `{path}` |")
    lines.extend(
        [
            "",
            "## By Condition",
            "",
            "| Condition | BR condition | Total | Attempted | Succeeded | Scored | Failed | Canonical convergence | Decision F1 | Action F1 | Evidence family F1 | Grounding | Actual BR calls | Retrieval calls |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for condition, summary in sorted((metrics.get("by_condition") or {}).items()):
        lines.append(
            "| `{condition}` | `{br_condition}` | {total} | {attempted} | {succeeded} | {scored} | "
            "{failed} | {canonical} | {decision} | {action} | {family_f1} | {grounding} | {br_calls} | {retrieval_calls} |".format(
                condition=condition,
                br_condition=summary.get("br_condition", "unknown"),
                total=summary.get("total_episodes", summary.get("n", 0)),
                attempted=summary.get("attempted", 0),
                succeeded=summary.get("succeeded", 0),
                scored=summary.get("scored", 0),
                failed=summary.get("failed", 0),
                canonical=_fmt_metric(summary.get("mean_canonical_convergence_score")),
                decision=_fmt_metric(summary.get("mean_decision_field_macro_f1")),
                action=_fmt_metric(summary.get("mean_required_action_f1")),
                family_f1=_fmt_metric(summary.get("mean_required_family_f1")),
                grounding=_fmt_metric(summary.get("grounding_quality_score")),
                br_calls=summary.get("br_tool_call_count_attempted", 0),
                retrieval_calls=summary.get("attempted_retrieval_tool_call_count", 0),
            )
        )
    lines.extend(
        [
            "",
            "## Paired BR Comparisons",
            "",
            "| Baseline | Treatment | Available pairs | Scored pairs | Canonical delta | Decision F1 delta | Action F1 delta | Evidence family F1 delta | Grounding delta | Actual BR tool overhead |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for comparison in metrics.get("condition_comparisons") or []:
        lines.append(
            "| `{baseline}` | `{treatment}` | {available} | {scored} | {canonical} | {decision} | {action} | {family_f1} | {grounding} | {br_overhead} |".format(
                baseline=comparison.get("baseline_condition"),
                treatment=comparison.get("treatment_condition"),
                available=comparison.get("available_pair_count", 0),
                scored=comparison.get("paired_scored_count", 0),
                canonical=_fmt_metric(comparison.get("canonical_convergence_score_delta")),
                decision=_fmt_metric(comparison.get("decision_field_macro_f1_delta")),
                action=_fmt_metric(comparison.get("required_action_f1_delta")),
                family_f1=_fmt_metric(comparison.get("required_family_f1_delta")),
                grounding=_fmt_metric(comparison.get("grounding_quality_score_delta")),
                br_overhead=_fmt_metric(comparison.get("br_tool_call_overhead")),
            )
        )
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _fmt_metric(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.3f}"
    return ""


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return value


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _read_text_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_user_prompt(prompt_text: str) -> str:
    start = "User prompt variant:\n"
    end = "\n\nCanonical task description:"
    if start in prompt_text and end in prompt_text:
        return prompt_text.split(start, 1)[1].split(end, 1)[0].strip()
    return ""


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16] if text else ""


def _episode_table_row(record: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    episode_dir = Path(str(record.get("episode_dir") or ""))
    prompt_path = episode_dir / "prompt.txt"
    output_path_value = str(((record.get("paths") or {}).get("last_message")) or "")
    output_path = Path(output_path_value) if output_path_value else episode_dir / "last_message.txt"
    events_path_value = str(((record.get("paths") or {}).get("events")) or "")
    stderr_path_value = str(((record.get("paths") or {}).get("stderr")) or "")
    events_path = Path(events_path_value) if events_path_value else episode_dir / "events.jsonl"
    stderr_path = Path(stderr_path_value) if stderr_path_value else episode_dir / "stderr.txt"
    prompt = _read_text_file(prompt_path)
    output = _read_text_file(output_path)
    stderr = _read_text_file(stderr_path)
    return {
        "case_id": record.get("case_id"),
        "variant_id": record.get("variant_id"),
        "variant_type": record.get("variant_type"),
        "condition": record.get("condition"),
        "runner": record.get("runner"),
        "model": record.get("model"),
        "br_mode": record.get("br_mode"),
        "br_condition": metric.get("br_condition"),
        "task_shape": record.get("task_shape"),
        "metric_scope": metric.get("metric_scope"),
        "canonical_metric_available": metric.get("canonical_metric_available"),
        "diagnostic_contract": record.get("diagnostic_contract"),
        "canonical_validation_status": metric.get("canonical_validation_status"),
        "canonical_validation_tier": metric.get("canonical_validation_tier"),
        "canonical_validation_blocking": metric.get("canonical_validation_blocking"),
        "status": record.get("status"),
        "availability_class": metric.get("availability_class"),
        "attempted": metric.get("attempted"),
        "succeeded": metric.get("succeeded"),
        "valid_json": metric.get("valid_json"),
        "scored": metric.get("scored"),
        "unscored_reason": metric.get("unscored_reason"),
        "returncode": record.get("returncode"),
        "timed_out": metric.get("timed_out"),
        "wall_time_s": record.get("wall_time_s"),
        "tool_call_count": record.get("tool_call_count"),
        "tools_used": record.get("tools_used") or [],
        "br_tool_called": metric.get("br_tool_called"),
        "br_tool_call_count": metric.get("br_tool_call_count"),
        "br_tool_names": metric.get("br_tool_names") or [],
        "retrieval_tool_called": metric.get("retrieval_tool_called"),
        "retrieval_tool_call_count": metric.get("retrieval_tool_call_count"),
        "retrieval_success_count": metric.get("retrieval_success_count"),
        "retrieval_error_count": metric.get("retrieval_error_count"),
        "retrieved_anchor_count": metric.get("retrieved_anchor_count"),
        "retrieved_required_family_hits": metric.get("retrieved_required_family_hits") or [],
        "retrieved_required_family_recall": metric.get("retrieved_required_family_recall"),
        "final_anchor_from_retrieval_rate": metric.get("final_anchor_from_retrieval_rate"),
        "required_family_hits": metric.get("required_family_hits") or [],
        "required_family_recall": metric.get("required_family_recall"),
        "required_family_precision": metric.get("required_family_precision"),
        "required_family_f1": metric.get("required_family_f1"),
        "final_required_family_mention_hits": metric.get("final_required_family_mention_hits") or [],
        "final_required_family_mention_recall": metric.get("final_required_family_mention_recall"),
        "retrieved_to_final_required_family_utilization": metric.get(
            "retrieved_to_final_required_family_utilization"
        ),
        "retrieved_evidence_used_count": metric.get("retrieved_evidence_used_count"),
        "retrieved_evidence_omitted_count": metric.get("retrieved_evidence_omitted_count"),
        "retrieved_evidence_used_anchor_from_retrieval_rate": metric.get(
            "retrieved_evidence_used_anchor_from_retrieval_rate"
        ),
        "retrieved_evidence_used_required_family_hits": metric.get(
            "retrieved_evidence_used_required_family_hits"
        )
        or [],
        "retrieved_evidence_used_required_family_recall": metric.get(
            "retrieved_evidence_used_required_family_recall"
        ),
        "diagnostic_family_mapping_count": metric.get("diagnostic_family_mapping_count"),
        "diagnostic_family_mapping_used_count": metric.get("diagnostic_family_mapping_used_count"),
        "diagnostic_family_mapping_omitted_count": metric.get(
            "diagnostic_family_mapping_omitted_count"
        ),
        "diagnostic_family_mapping_anchor_from_retrieval_rate": metric.get(
            "diagnostic_family_mapping_anchor_from_retrieval_rate"
        ),
        "diagnostic_family_mapping_required_family_hits": metric.get(
            "diagnostic_family_mapping_required_family_hits"
        )
        or [],
        "diagnostic_family_mapping_required_family_recall": metric.get(
            "diagnostic_family_mapping_required_family_recall"
        ),
        "required_field_coverage": metric.get("required_field_coverage"),
        "decision_field_macro_f1": metric.get("decision_field_macro_f1"),
        "decision_convergence_score": metric.get("decision_convergence_score"),
        "required_action_f1": metric.get("required_action_f1"),
        "canonical_convergence_score": metric.get("canonical_convergence_score"),
        "decision_field_hits": metric.get("decision_field_hits") or [],
        "required_action_hits": metric.get("required_action_hits") or [],
        "rubric_axis_score": metric.get("rubric_axis_score"),
        "grounding_quality_score": metric.get("grounding_quality_score"),
        "valid_anchor_rate": metric.get("valid_anchor_rate"),
        "citation_hallucination_rate": metric.get("citation_hallucination_rate"),
        "claim_support_precision": metric.get("claim_support_precision"),
        "json_parse_error": metric.get("json_parse_error"),
        "missing_required_fields": metric.get("missing_required_fields") or [],
        "input": _extract_user_prompt(prompt),
        "prompt": prompt,
        "prompt_sha16": _sha16(prompt),
        "output": output,
        "output_sha16": _sha16(output),
        "output_chars": len(output),
        "stderr_tail": stderr[-1200:],
        "episode_dir": str(episode_dir),
        "prompt_path": str(prompt_path) if prompt_path.exists() else "",
        "output_path": str(output_path) if output_path.exists() else "",
        "events_path": str(events_path) if events_path.exists() else "",
        "stderr_path": str(stderr_path) if stderr_path.exists() else "",
    }


def _availability_table_rows(by_condition: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition, summary in sorted(by_condition.items()):
        availability = summary.get("availability_counts") or {}
        rows.append(
            {
                "condition": condition,
                "br_condition": summary.get("br_condition"),
                "denominator": summary.get("availability_denominator"),
                "total_episodes": summary.get("total_episodes"),
                "attempted": summary.get("attempted"),
                "succeeded": summary.get("succeeded"),
                "failed": summary.get("failed"),
                "timed_out": summary.get("timed_out"),
                "materialized": summary.get("materialized"),
                "completed": availability.get("completed", 0),
                "provider_or_account_limit": availability.get("provider_or_account_limit", 0),
                "agent_error_event": availability.get("agent_error_event", 0),
                "timeout": availability.get("timeout", 0),
                "agent_unavailable": availability.get("agent_unavailable", 0),
                "unsupported_task_shape": availability.get("unsupported_task_shape", 0),
                "output_capture_failed": availability.get("output_capture_failed", 0),
                "execution_failed": availability.get("execution_failed", 0),
                "prompt_packet_only": availability.get("prompt_packet_only", 0),
                "success_rate_attempted": summary.get("success_rate_attempted"),
                "failed_rate_attempted": summary.get("failed_rate_attempted"),
                "br_tool_called_attempted": summary.get("br_tool_called_attempted"),
                "br_tool_called_rate_attempted": summary.get("br_tool_called_rate_attempted"),
                "br_tool_call_count_attempted": summary.get("br_tool_call_count_attempted"),
                "retrieval_tool_called_attempted": summary.get("retrieval_tool_called_attempted"),
                "retrieval_tool_called_rate_attempted": summary.get("retrieval_tool_called_rate_attempted"),
                "attempted_retrieval_tool_call_count": summary.get("attempted_retrieval_tool_call_count"),
                "attempted_retrieval_success_rate": summary.get("attempted_retrieval_success_rate"),
            }
        )
    return rows


def _quality_table_rows(by_condition: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition, summary in sorted(by_condition.items()):
        rows.append(
            {
                "condition": condition,
                "br_condition": summary.get("br_condition"),
                "denominator": summary.get("quality_denominator"),
                "scored": summary.get("scored"),
                "valid_json": summary.get("valid_json"),
                "succeeded": summary.get("succeeded"),
                "scored_rate_succeeded": summary.get("scored_rate_succeeded"),
                "valid_json_rate_succeeded": summary.get("valid_json_rate_succeeded"),
                "mean_canonical_convergence_score": summary.get("mean_canonical_convergence_score"),
                "worst_canonical_convergence_score": summary.get("worst_canonical_convergence_score"),
                "p10_canonical_convergence_score": summary.get("p10_canonical_convergence_score"),
                "mean_decision_field_macro_f1": summary.get("mean_decision_field_macro_f1"),
                "mean_required_action_f1": summary.get("mean_required_action_f1"),
                "mean_rubric_axis_score": summary.get("mean_rubric_axis_score"),
                "mean_required_family_recall": summary.get("mean_required_family_recall"),
                "mean_required_family_precision": summary.get("mean_required_family_precision"),
                "mean_required_family_f1": summary.get("mean_required_family_f1"),
                "mean_required_field_coverage": summary.get("mean_required_field_coverage"),
                "grounding_quality_score": summary.get("grounding_quality_score"),
                "mean_retrieved_required_family_recall": summary.get("mean_retrieved_required_family_recall"),
                "mean_retrieved_to_final_required_family_utilization": summary.get(
                    "mean_retrieved_to_final_required_family_utilization"
                ),
                "mean_retrieved_evidence_used_required_family_recall": summary.get(
                    "mean_retrieved_evidence_used_required_family_recall"
                ),
                "mean_retrieved_evidence_used_anchor_from_retrieval_rate": summary.get(
                    "mean_retrieved_evidence_used_anchor_from_retrieval_rate"
                ),
                "retrieved_evidence_used_count": summary.get("retrieved_evidence_used_count"),
                "retrieved_evidence_omitted_count": summary.get("retrieved_evidence_omitted_count"),
                "mean_diagnostic_family_mapping_required_family_recall": summary.get(
                    "mean_diagnostic_family_mapping_required_family_recall"
                ),
                "mean_diagnostic_family_mapping_anchor_from_retrieval_rate": summary.get(
                    "mean_diagnostic_family_mapping_anchor_from_retrieval_rate"
                ),
                "diagnostic_family_mapping_count": summary.get("diagnostic_family_mapping_count"),
                "diagnostic_family_mapping_used_count": summary.get(
                    "diagnostic_family_mapping_used_count"
                ),
                "diagnostic_family_mapping_omitted_count": summary.get(
                    "diagnostic_family_mapping_omitted_count"
                ),
                "valid_anchor_rate": summary.get("valid_anchor_rate"),
                "citation_hallucination_rate": summary.get("citation_hallucination_rate"),
                "claim_support_precision": summary.get("claim_support_precision"),
                "final_anchor_from_retrieval_rate": summary.get("final_anchor_from_retrieval_rate"),
                "retrieved_anchor_utilization_rate": summary.get("retrieved_anchor_utilization_rate"),
                "retrieval_success_rate": summary.get("retrieval_success_rate"),
                "br_tool_called_scored": summary.get("br_tool_called_scored"),
                "br_tool_called_rate_scored": summary.get("br_tool_called_rate_scored"),
                "br_tool_call_count_scored": summary.get("br_tool_call_count_scored"),
                "retrieval_tool_called_scored": summary.get("retrieval_tool_called_scored"),
                "retrieval_tool_called_rate_scored": summary.get("retrieval_tool_called_rate_scored"),
                "retrieval_tool_call_count": summary.get("retrieval_tool_call_count"),
                "prompt_robustness": summary.get("prompt_robustness"),
            }
        )
    return rows


def _variant_robustness_rows(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in metric_rows:
        key = (str(row.get("variant_id") or ""), str(row.get("variant_type") or ""))
        grouped.setdefault(key, []).append(row)
    rows: list[dict[str, Any]] = []
    for (variant_id, variant_type), group in sorted(grouped.items()):
        summary = _condition_summary(group)
        rows.append(
            {
                "variant_id": variant_id,
                "variant_type": variant_type,
                "denominator": summary.get("quality_denominator"),
                "total_episodes": summary.get("total_episodes"),
                "attempted": summary.get("attempted"),
                "succeeded": summary.get("succeeded"),
                "scored": summary.get("scored"),
                "valid_json": summary.get("valid_json"),
                "failed": summary.get("failed"),
                "timed_out": summary.get("timed_out"),
                "availability_counts": summary.get("availability_counts"),
                "mean_canonical_convergence_score": summary.get("mean_canonical_convergence_score"),
                "worst_canonical_convergence_score": summary.get("worst_canonical_convergence_score"),
                "mean_rubric_axis_score": summary.get("mean_rubric_axis_score"),
                "mean_decision_field_macro_f1": summary.get("mean_decision_field_macro_f1"),
                "mean_required_action_f1": summary.get("mean_required_action_f1"),
                "mean_required_family_recall": summary.get("mean_required_family_recall"),
                "mean_required_family_f1": summary.get("mean_required_family_f1"),
                "grounding_quality_score": summary.get("grounding_quality_score"),
                "valid_anchor_rate": summary.get("valid_anchor_rate"),
                "br_tool_called_rate_attempted": summary.get("br_tool_called_rate_attempted"),
                "retrieval_tool_called_rate_attempted": summary.get("retrieval_tool_called_rate_attempted"),
                "prompt_robustness": summary.get("prompt_robustness"),
            }
        )
    return rows


def _error_taxonomy_rows(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str, str], int] = {}
    for row in metric_rows:
        key = (
            str(row.get("condition") or ""),
            str(row.get("status") or ""),
            str(row.get("availability_class") or "unknown"),
        )
        counts[key] = counts.get(key, 0) + 1
        total_key = ("__all_conditions__", key[1], key[2])
        counts[total_key] = counts.get(total_key, 0) + 1
    return [
        {
            "condition": condition,
            "status": status,
            "availability_class": availability,
            "count": count,
        }
        for (condition, status, availability), count in sorted(counts.items())
    ]


def _as_string_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value if str(item).strip()}
    if isinstance(value, set):
        return {str(item) for item in value if str(item).strip()}
    if isinstance(value, tuple):
        return {str(item) for item in value if str(item).strip()}
    return set()


def _jaccard(left: set[str], right: set[str]) -> float | None:
    if not left and not right:
        return None
    return len(left & right) / len(left | right)


def _pairwise_jaccard(rows: list[dict[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            score = _jaccard(_as_string_set(left.get(field)), _as_string_set(right.get(field)))
            if score is not None:
                values.append(score)
    return _mean(values)


def _signature_entropy(rows: list[dict[str, Any]], field: str) -> float | None:
    signatures = [
        tuple(sorted(_as_string_set(row.get(field))))
        for row in rows
        if _as_string_set(row.get(field))
    ]
    if not signatures:
        return None
    counts: dict[tuple[str, ...], int] = {}
    for signature in signatures:
        counts[signature] = counts.get(signature, 0) + 1
    total = len(signatures)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _prompt_stability_rows(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in metric_rows:
        if row.get("scored") is not True:
            continue
        key = (
            str(row.get("case_id") or ""),
            str(row.get("model") or ""),
            str(row.get("condition") or ""),
            str(row.get("br_condition") or ""),
        )
        grouped.setdefault(key, []).append(row)
    rows: list[dict[str, Any]] = []
    for (case_id, model, condition, br_condition), group in sorted(grouped.items()):
        canonical_scores = [
            float(row.get("canonical_convergence_score"))
            for row in group
            if isinstance(row.get("canonical_convergence_score"), (int, float))
        ]
        rows.append(
            {
                "case_id": case_id,
                "model": model,
                "condition": condition,
                "br_condition": br_condition,
                "scored_variants": len(group),
                "mean_canonical_convergence": _mean(canonical_scores),
                "std_canonical_convergence": (
                    statistics.pstdev(canonical_scores) if len(canonical_scores) > 1 else 0.0
                    if canonical_scores
                    else None
                ),
                "p10_canonical_convergence": _percentile(canonical_scores, 0.10),
                "worst_prompt_canonical_score": min(canonical_scores) if canonical_scores else None,
                "prompt_pairwise_decision_agreement": _pairwise_jaccard(
                    group,
                    "decision_field_hits",
                ),
                "prompt_pairwise_action_jaccard": _pairwise_jaccard(
                    group,
                    "required_action_hits",
                ),
                "prompt_pairwise_evidence_family_jaccard": _pairwise_jaccard(
                    group,
                    "required_family_hits",
                ),
                "decision_entropy": _signature_entropy(group, "decision_field_hits"),
            }
        )
    return rows


def _condition_pairs(conditions: set[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for condition in sorted(conditions):
        if "without_br" not in condition:
            continue
        for candidate in [
            condition.replace("without_br", "with_br"),
            condition.replace("without_br", "with_br_required"),
            condition.replace("without_br", "with_br_mcp"),
            condition.replace("without_br", "with_br_gated"),
        ]:
            if candidate in conditions:
                pairs.append((condition, candidate))
                break
    if not pairs:
        without = [condition for condition in sorted(conditions) if "without" in condition and "br" in condition]
        with_br = [condition for condition in sorted(conditions) if "with" in condition and "br" in condition and "without" not in condition]
        if len(without) == 1 and len(with_br) == 1:
            pairs.append((without[0], with_br[0]))
    return pairs


def _br_loss_classification(baseline: dict[str, Any], treatment: dict[str, Any]) -> str:
    if treatment.get("availability_class") == "provider_or_account_limit":
        return "availability_provider_or_account_limit"
    if treatment.get("valid_json") is False:
        return "invalid_json"
    if treatment.get("scored") is not True:
        return "unscored_or_unavailable"
    retrieved_recall = treatment.get("retrieved_required_family_recall")
    final_recall = treatment.get("required_family_recall")
    baseline_final_recall = baseline.get("required_family_recall")
    mention_recall = treatment.get("final_required_family_mention_recall")
    retrieval_miss = (
        isinstance(retrieved_recall, (int, float))
        and isinstance(baseline_final_recall, (int, float))
        and retrieved_recall + 1e-12 < baseline_final_recall
    )
    agent_use_gap = (
        isinstance(retrieved_recall, (int, float))
        and isinstance(final_recall, (int, float))
        and retrieved_recall > final_recall + 1e-12
    )
    final_mentions_unscored = (
        isinstance(mention_recall, (int, float))
        and isinstance(final_recall, (int, float))
        and mention_recall > final_recall + 1e-12
    )
    treatment_claim_support = treatment.get("claim_support_precision")
    baseline_claim_support = baseline.get("claim_support_precision")
    treatment_hallucination = treatment.get("citation_hallucination_rate")
    baseline_hallucination = baseline.get("citation_hallucination_rate")
    unsupported_claim_or_bad_anchor = (
        isinstance(treatment_claim_support, (int, float))
        and isinstance(baseline_claim_support, (int, float))
        and treatment_claim_support + 1e-12 < baseline_claim_support
    ) or (
        isinstance(treatment_hallucination, (int, float))
        and isinstance(baseline_hallucination, (int, float))
        and treatment_hallucination > baseline_hallucination + 1e-12
    )
    if retrieval_miss and agent_use_gap:
        return "mixed_retrieval_miss_and_agent_use_gap"
    if final_mentions_unscored and agent_use_gap:
        return "final_mentions_not_in_scored_evidence_basis"
    if isinstance(mention_recall, (int, float)) and isinstance(final_recall, (int, float)):
        if mention_recall > final_recall + 1e-12:
            return "scorer_or_anchor_equivalence_gap"
    if retrieval_miss:
        return "retrieval_missed_canonical_anchors"
    if agent_use_gap:
        return "agent_ignored_retrieved_anchors"
    if unsupported_claim_or_bad_anchor:
        return "unsupported_extra_claim_or_bad_anchor"
    return "canonical_metric_lower"


def _br_loss_primary_mechanism(classification: str) -> str:
    if classification == "retrieval_missed_canonical_anchors":
        return "retrieval_miss"
    if classification in {
        "agent_ignored_retrieved_anchors",
        "final_mentions_not_in_scored_evidence_basis",
    }:
        return "agent_finalization_gap"
    if classification == "scorer_or_anchor_equivalence_gap":
        return "scorer_alias_or_anchor_equivalence"
    if classification == "unsupported_extra_claim_or_bad_anchor":
        return "unsupported_extra_claim"
    if classification == "mixed_retrieval_miss_and_agent_use_gap":
        return "mixed_retrieval_and_agent_use"
    if classification == "availability_provider_or_account_limit":
        return "availability_provider_or_account_limit"
    if classification == "invalid_json":
        return "invalid_json"
    if classification == "unscored_or_unavailable":
        return "unscored_or_unavailable"
    return "other_canonical_metric_loss"


def _br_loss_diagnostic_rows(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conditions = {str(row.get("condition") or "") for row in metric_rows}
    rows_by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in metric_rows:
        rows_by_condition.setdefault(str(row.get("condition")), []).append(row)
    diagnostics: list[dict[str, Any]] = []
    for baseline_condition, treatment_condition in _condition_pairs(conditions):
        base_by_key = {_pair_key(row): row for row in rows_by_condition.get(baseline_condition, [])}
        treat_by_key = {_pair_key(row): row for row in rows_by_condition.get(treatment_condition, [])}
        for key in sorted(set(base_by_key) & set(treat_by_key)):
            baseline = base_by_key[key]
            treatment = treat_by_key[key]
            base_score = baseline.get("canonical_convergence_score")
            treat_score = treatment.get("canonical_convergence_score")
            treatment_missing = treatment.get("scored") is not True
            score_loss = (
                isinstance(base_score, (int, float))
                and isinstance(treat_score, (int, float))
                and treat_score < base_score - 1e-12
            )
            if not treatment_missing and not score_loss:
                continue
            classification = _br_loss_classification(baseline, treatment)
            diagnostics.append(
                {
                    "case_id": key[0],
                    "variant_id": key[1],
                    "baseline_condition": baseline_condition,
                    "treatment_condition": treatment_condition,
                    "baseline_status": baseline.get("status"),
                    "treatment_status": treatment.get("status"),
                    "baseline_scored": baseline.get("scored"),
                    "treatment_scored": treatment.get("scored"),
                    "classification": classification,
                    "primary_mechanism": _br_loss_primary_mechanism(classification),
                    "canonical_validation_status": treatment.get("canonical_validation_status"),
                    "canonical_validation_tier": treatment.get("canonical_validation_tier"),
                    "canonical_validation_blocking": treatment.get("canonical_validation_blocking"),
                    "baseline_canonical_convergence_score": base_score,
                    "treatment_canonical_convergence_score": treat_score,
                    "canonical_convergence_delta": (
                        treat_score - base_score
                        if isinstance(base_score, (int, float))
                        and isinstance(treat_score, (int, float))
                        else None
                    ),
                    "baseline_required_family_recall": baseline.get("required_family_recall"),
                    "treatment_required_family_recall": treatment.get("required_family_recall"),
                    "treatment_retrieved_required_family_recall": treatment.get(
                        "retrieved_required_family_recall"
                    ),
                    "treatment_final_required_family_mention_recall": treatment.get(
                        "final_required_family_mention_recall"
                    ),
                    "treatment_retrieved_to_final_required_family_utilization": treatment.get(
                        "retrieved_to_final_required_family_utilization"
                    ),
                    "baseline_required_family_hits": baseline.get("required_family_hits"),
                    "treatment_required_family_hits": treatment.get("required_family_hits"),
                    "treatment_detected_evidence_families": treatment.get("detected_evidence_families"),
                    "treatment_retrieved_required_family_hits": treatment.get(
                        "retrieved_required_family_hits"
                    ),
                    "treatment_retrieved_evidence_used_required_family_hits": treatment.get(
                        "retrieved_evidence_used_required_family_hits"
                    ),
                    "treatment_diagnostic_family_mapping_required_family_hits": treatment.get(
                        "diagnostic_family_mapping_required_family_hits"
                    ),
                    "treatment_unscored_reason": treatment.get("unscored_reason"),
                    "treatment_json_parse_error": treatment.get("json_parse_error"),
                    "treatment_availability_class": treatment.get("availability_class"),
                }
            )
    return diagnostics


def write_report_tables(
    run_dir: Path,
    metrics: dict[str, Any],
    records: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> dict[str, str]:
    tables_dir = run_dir / REPORT_TABLES_DIRNAME
    by_condition = metrics.get("by_condition") or {}
    table_paths = {
        "episode_results": tables_dir / "episode_results.csv",
        "availability_by_condition": tables_dir / "availability_by_condition.csv",
        "quality_by_condition": tables_dir / "quality_by_condition.csv",
        "paired_br_delta": tables_dir / "paired_br_delta.csv",
        "prompt_stability_by_case_condition": tables_dir / "prompt_stability_by_case_condition.csv",
        "br_loss_diagnostics": tables_dir / "br_loss_diagnostics.csv",
        "variant_robustness": tables_dir / "variant_robustness.csv",
        "error_taxonomy": tables_dir / "error_taxonomy.csv",
    }

    episode_fields = [
        "case_id",
        "variant_id",
        "variant_type",
        "condition",
        "runner",
        "model",
        "br_mode",
        "br_condition",
        "task_shape",
        "metric_scope",
        "canonical_metric_available",
        "diagnostic_contract",
        "canonical_validation_status",
        "canonical_validation_tier",
        "canonical_validation_blocking",
        "status",
        "availability_class",
        "attempted",
        "succeeded",
        "valid_json",
        "scored",
        "unscored_reason",
        "returncode",
        "timed_out",
        "wall_time_s",
        "tool_call_count",
        "tools_used",
        "br_tool_called",
        "br_tool_call_count",
        "br_tool_names",
        "retrieval_tool_called",
        "retrieval_tool_call_count",
        "retrieval_success_count",
        "retrieval_error_count",
        "retrieved_anchor_count",
        "retrieved_required_family_hits",
        "retrieved_required_family_recall",
        "final_anchor_from_retrieval_rate",
        "required_family_hits",
        "required_family_recall",
        "required_family_precision",
        "required_family_f1",
        "final_required_family_mention_hits",
        "final_required_family_mention_recall",
        "retrieved_to_final_required_family_utilization",
        "retrieved_evidence_used_count",
        "retrieved_evidence_omitted_count",
        "retrieved_evidence_used_anchor_from_retrieval_rate",
        "retrieved_evidence_used_required_family_hits",
        "retrieved_evidence_used_required_family_recall",
        "diagnostic_family_mapping_count",
        "diagnostic_family_mapping_used_count",
        "diagnostic_family_mapping_omitted_count",
        "diagnostic_family_mapping_anchor_from_retrieval_rate",
        "diagnostic_family_mapping_required_family_hits",
        "diagnostic_family_mapping_required_family_recall",
        "required_field_coverage",
        "decision_field_macro_f1",
        "decision_convergence_score",
        "required_action_f1",
        "canonical_convergence_score",
        "decision_field_hits",
        "required_action_hits",
        "rubric_axis_score",
        "grounding_quality_score",
        "valid_anchor_rate",
        "citation_hallucination_rate",
        "claim_support_precision",
        "json_parse_error",
        "missing_required_fields",
        "input",
        "prompt",
        "prompt_sha16",
        "output",
        "output_sha16",
        "output_chars",
        "stderr_tail",
        "episode_dir",
        "prompt_path",
        "output_path",
        "events_path",
        "stderr_path",
    ]
    _write_csv(
        table_paths["episode_results"],
        episode_fields,
        [
            _episode_table_row(record, metric)
            for record, metric in zip(records, metric_rows, strict=False)
        ],
    )
    _write_csv(
        table_paths["availability_by_condition"],
        [
            "condition",
            "br_condition",
            "denominator",
            "total_episodes",
            "attempted",
            "succeeded",
            "failed",
            "timed_out",
            "materialized",
            "completed",
            "provider_or_account_limit",
            "agent_error_event",
            "timeout",
            "agent_unavailable",
            "unsupported_task_shape",
            "output_capture_failed",
            "execution_failed",
            "prompt_packet_only",
            "success_rate_attempted",
            "failed_rate_attempted",
            "br_tool_called_attempted",
            "br_tool_called_rate_attempted",
            "br_tool_call_count_attempted",
            "retrieval_tool_called_attempted",
            "retrieval_tool_called_rate_attempted",
            "attempted_retrieval_tool_call_count",
            "attempted_retrieval_success_rate",
        ],
        _availability_table_rows(by_condition),
    )
    _write_csv(
        table_paths["quality_by_condition"],
        [
            "condition",
            "br_condition",
            "denominator",
            "scored",
            "valid_json",
            "succeeded",
            "scored_rate_succeeded",
            "valid_json_rate_succeeded",
            "mean_canonical_convergence_score",
            "worst_canonical_convergence_score",
            "p10_canonical_convergence_score",
            "mean_decision_field_macro_f1",
            "mean_required_action_f1",
            "mean_rubric_axis_score",
            "mean_required_family_recall",
            "mean_required_family_precision",
            "mean_required_family_f1",
            "mean_required_field_coverage",
            "grounding_quality_score",
            "mean_retrieved_required_family_recall",
            "mean_retrieved_to_final_required_family_utilization",
            "mean_retrieved_evidence_used_required_family_recall",
            "mean_retrieved_evidence_used_anchor_from_retrieval_rate",
            "retrieved_evidence_used_count",
            "retrieved_evidence_omitted_count",
            "mean_diagnostic_family_mapping_required_family_recall",
            "mean_diagnostic_family_mapping_anchor_from_retrieval_rate",
            "diagnostic_family_mapping_count",
            "diagnostic_family_mapping_used_count",
            "diagnostic_family_mapping_omitted_count",
            "valid_anchor_rate",
            "citation_hallucination_rate",
            "claim_support_precision",
            "final_anchor_from_retrieval_rate",
            "retrieved_anchor_utilization_rate",
            "retrieval_success_rate",
            "br_tool_called_scored",
            "br_tool_called_rate_scored",
            "br_tool_call_count_scored",
            "retrieval_tool_called_scored",
            "retrieval_tool_called_rate_scored",
            "retrieval_tool_call_count",
            "prompt_robustness",
        ],
        _quality_table_rows(by_condition),
    )
    _write_csv(
        table_paths["paired_br_delta"],
        [
            "baseline_condition",
            "treatment_condition",
            "pairing_policy",
            "available_pair_count",
            "paired_scored_count",
            "unscored_or_unavailable_pair_count",
            "baseline_total_episodes",
            "treatment_total_episodes",
            "baseline_scored",
            "treatment_scored",
            "quality_denominator",
            "canonical_convergence_score_delta",
            "decision_field_macro_f1_delta",
            "required_action_f1_delta",
            "rubric_axis_score_delta",
            "required_family_recall_delta",
            "required_family_precision_delta",
            "required_family_f1_delta",
            "retrieved_required_family_recall_delta",
            "retrieved_to_final_required_family_utilization_delta",
            "diagnostic_family_mapping_required_family_recall_delta",
            "valid_anchor_rate_delta",
            "citation_hallucination_rate_delta",
            "claim_support_precision_delta",
            "final_anchor_from_retrieval_rate_delta",
            "retrieval_success_rate_delta",
            "grounding_quality_score_delta",
            "latency_overhead_s",
            "tool_call_overhead",
            "br_tool_call_overhead",
            "retrieval_tool_call_overhead",
            "baseline_br_tool_called_rate_scored",
            "treatment_br_tool_called_rate_scored",
            "tool_efficiency",
        ],
        metrics.get("condition_comparisons") or [],
    )
    _write_csv(
        table_paths["prompt_stability_by_case_condition"],
        [
            "case_id",
            "model",
            "condition",
            "br_condition",
            "scored_variants",
            "mean_canonical_convergence",
            "std_canonical_convergence",
            "p10_canonical_convergence",
            "worst_prompt_canonical_score",
            "prompt_pairwise_decision_agreement",
            "prompt_pairwise_action_jaccard",
            "prompt_pairwise_evidence_family_jaccard",
            "decision_entropy",
        ],
        _prompt_stability_rows(metric_rows),
    )
    _write_csv(
        table_paths["br_loss_diagnostics"],
        [
            "case_id",
            "variant_id",
            "baseline_condition",
            "treatment_condition",
            "baseline_status",
            "treatment_status",
            "baseline_scored",
            "treatment_scored",
            "classification",
            "primary_mechanism",
            "canonical_validation_status",
            "canonical_validation_tier",
            "canonical_validation_blocking",
            "baseline_canonical_convergence_score",
            "treatment_canonical_convergence_score",
            "canonical_convergence_delta",
            "baseline_required_family_recall",
            "treatment_required_family_recall",
            "treatment_retrieved_required_family_recall",
            "treatment_final_required_family_mention_recall",
            "treatment_retrieved_to_final_required_family_utilization",
            "baseline_required_family_hits",
            "treatment_required_family_hits",
            "treatment_detected_evidence_families",
            "treatment_retrieved_required_family_hits",
            "treatment_retrieved_evidence_used_required_family_hits",
            "treatment_diagnostic_family_mapping_required_family_hits",
            "treatment_unscored_reason",
            "treatment_json_parse_error",
            "treatment_availability_class",
        ],
        _br_loss_diagnostic_rows(metric_rows),
    )
    _write_csv(
        table_paths["variant_robustness"],
        [
            "variant_id",
            "variant_type",
            "denominator",
            "total_episodes",
            "attempted",
            "succeeded",
            "scored",
            "valid_json",
            "failed",
            "timed_out",
            "availability_counts",
            "mean_canonical_convergence_score",
            "worst_canonical_convergence_score",
            "mean_rubric_axis_score",
            "mean_decision_field_macro_f1",
            "mean_required_action_f1",
            "mean_required_family_recall",
            "mean_required_family_f1",
            "grounding_quality_score",
            "valid_anchor_rate",
            "br_tool_called_rate_attempted",
            "retrieval_tool_called_rate_attempted",
            "prompt_robustness",
        ],
        _variant_robustness_rows(metric_rows),
    )
    _write_csv(
        table_paths["error_taxonomy"],
        ["condition", "status", "availability_class", "count"],
        _error_taxonomy_rows(metric_rows),
    )
    return {key: str(path) for key, path in table_paths.items()}


def write_run_metrics(run_dir: Path, cases_root: Path) -> dict[str, Any]:
    episodes_path = run_dir / "episodes.jsonl"
    records = read_jsonl_rows(episodes_path) if episodes_path.exists() else []
    metric_rows = [score_episode_record(record, cases_root) for record in records]
    episode_metrics_path = run_dir / "episode_metrics.jsonl"
    with episode_metrics_path.open("w", encoding="utf-8") as fh:
        for row in metric_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in metric_rows:
        grouped.setdefault(str(row.get("condition")), []).append(row)
    by_condition = {
        condition: _condition_summary(rows)
        for condition, rows in sorted(grouped.items())
    }
    status_summary = _overall_status_summary(metric_rows)
    metrics = {
        "schema_version": "br.reproducibility_audit.metrics.v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "evidence_policy": _run_evidence_policy(run_dir, metric_rows),
        "episodes": len(metric_rows),
        "episodes_attempted": status_summary["attempted"],
        "episodes_succeeded": status_summary["succeeded"],
        "episodes_scored": status_summary["scored"],
        "episodes_valid_json": status_summary["valid_json"],
        "episodes_timed_out": status_summary["timed_out"],
        "episodes_failed": status_summary["failed"],
        "episodes_materialized": status_summary["materialized"],
        "status_summary": status_summary,
        "episode_metrics_path": str(episode_metrics_path),
        "metric_definitions": {
            "attempted": "Execution was requested and the row is not a prompt-packet-only materialization.",
            "succeeded": "Agent process completed with status=succeeded.",
            "scored": "Succeeded grounded_recommendation row with valid JSON and no metric error; quality means use only these rows.",
            "valid_json": "Final response parsed as JSON. Non-succeeded rows are not included in this denominator.",
            "availability_denominator": "Availability and execution-rate fields use attempted rows.",
            "quality_denominator": "Quality fields use scored rows only: status=succeeded, valid JSON, and metric scorer accepted the response.",
            "availability_counts": "Timeouts, provider/account failures, unavailable agents, and prompt packets are availability/reporting states, not answer-quality scores.",
            "br_condition": "Condition label normalized to without_br, with_br, with_br_required, mixed, or unknown.",
            "br_tool_called": "Whether the episode actually used a Brain Researcher tool, not merely whether BR was enabled by condition.",
            "br_tool_call_count": "Actual Brain Researcher tool-call count when detectable; uses retrieval call count or Brain Researcher tool traces.",
            "canonical_validation_tier": "Normalized case-governance state: draft, reviewed, locked, or unknown. Draft/reviewed rows are diagnostic, not benchmark-grade gold.",
            "canonical_validation_blocking": "Whether case governance should block benchmark-grade canonical-convergence claims.",
            "canonical_convergence_score": "Primary frozen-trace proxy: mean of decision-field F1, required-action F1, and required-evidence-family F1 when available.",
            "decision_field_macro_f1": "Keyword/equivalence-set F1 between canonical decision expectations and final response decision content; proxy until cases declare explicit canonical_decisions.",
            "required_action_f1": "Keyword/equivalence-set F1 between canonical action expectations and final response action/checklist content.",
            "required_family_precision": "Required evidence-family hits divided by detected known evidence families in the final response.",
            "required_family_f1": "F1 over required evidence-family precision and recall.",
            "retrieved_required_family_recall": "Required evidence families present in Brain Researcher retrieval output divided by required families.",
            "retrieved_to_final_required_family_utilization": "Retrieved required evidence families also used with valid final anchors divided by retrieved required families.",
            "retrieved_evidence_used_required_family_recall": "Required evidence families explicitly mapped in the final retrieved_evidence_used table divided by required families.",
            "retrieved_evidence_used_anchor_from_retrieval_rate": "Anchors in retrieved_evidence_used that also appeared in Brain Researcher retrieval output divided by anchors in retrieved_evidence_used.",
            "diagnostic_family_mapping_required_family_recall": "Diagnostic-contract-only: model-declared visible source families mapped to required families by the scorer, divided by required families.",
            "diagnostic_family_mapping_anchor_from_retrieval_rate": "Diagnostic-contract-only: anchors in diagnostic_family_mapping that also appeared in Brain Researcher retrieval output divided by diagnostic mapping anchors.",
            "br_loss_primary_mechanism": "Row-level BR-loss taxonomy bucket used for diagnostic calibration: retrieval miss, agent finalization gap, scorer/anchor equivalence, unsupported extra claim, mixed, or availability/parsing.",
            "rubric_axis_score": "Mean of deterministic 0/1 scores over case scoring_axes.",
            "required_family_recall": "Required evidence families represented by a valid anchor divided by required families.",
            "valid_anchor_rate": "Valid DOI/PMID/doc/KG/session anchors divided by valid plus malformed anchor labels.",
            "citation_hallucination_rate": "Malformed or citation-like unsupported references divided by citation-like references.",
            "claim_support_precision": "Evidence-bearing claims with claim, support span, verifiable=true, and valid anchor divided by evidence-bearing claims.",
            "final_anchor_from_retrieval_rate": "Final-answer anchors also present in Brain Researcher retrieval output divided by final-answer anchors.",
            "retrieval_success_rate": "Successful Brain Researcher google_file_search calls divided by successful plus error calls.",
            "retrieved_anchor_utilization_rate": "Final-answer anchors also present in retrieval output divided by retrieved anchors.",
            "prompt_robustness": "Score is 1 - population standard deviation of rubric_axis_score across prompt variants; higher is more stable.",
            "tool_efficiency": "Paired with-BR vs without-BR grounding-quality delta per added tool call or second.",
            "report_tables": "CSV tables separating row-level outputs, availability, quality, paired deltas, variant robustness, and error taxonomy.",
            "evidence_policy": "single_run_attempts for one execution pass; retry_or_topup_attempts must not be used as headline model-quality evidence unless pre-registered.",
        },
        "by_condition": by_condition,
        "condition_comparisons": _paired_condition_comparisons(by_condition, metric_rows),
    }
    metrics["report_tables"] = write_report_tables(run_dir, metrics, records, metric_rows)
    metrics_report_path = write_metrics_report(run_dir, metrics)
    metrics["metrics_report_path"] = str(metrics_report_path)
    write_json(run_dir / "metrics.json", metrics)
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        try:
            summary = read_json(summary_path)
        except Exception:
            summary = None
        if isinstance(summary, dict):
            summary["metrics"] = {
                "metrics_json": str(run_dir / "metrics.json"),
                "episode_metrics_jsonl": str(episode_metrics_path),
                "metrics_report_md": str(metrics_report_path),
                "status_summary": metrics.get("status_summary"),
                "evidence_policy": metrics.get("evidence_policy"),
                "episodes_scored": metrics.get("episodes_scored"),
                "condition_comparisons": metrics.get("condition_comparisons"),
                "report_tables": metrics.get("report_tables"),
            }
            write_json(summary_path, summary)
    return metrics


def run_agent_episode(
    prompt_path: Path,
    prompt: str,
    run_dir: Path,
    episode_dir: Path,
    condition: str,
    timeout_s: int,
    reasoning_effort: str,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    model: str | None,
    agent_condition: dict[str, Any] | None,
    claude_br_mcp_config: Path,
    allow_opencode_with_br: bool,
) -> dict[str, Any]:
    output_path = episode_dir / "last_message.txt"
    events_path = episode_dir / "events.jsonl"
    stderr_path = episode_dir / "stderr.txt"
    cmd, prompt_on_stdin, skip_reason = command_for_episode(
        output_path=output_path,
        condition=condition,
        prompt=prompt,
        run_dir=run_dir,
        reasoning_effort=reasoning_effort,
        codex_bin=codex_bin,
        claude_bin=claude_bin,
        opencode_bin=opencode_bin,
        model=model,
        agent_condition=agent_condition,
        claude_br_mcp_config=claude_br_mcp_config,
        allow_opencode_with_br=allow_opencode_with_br,
    )
    runner = str(agent_condition.get("runner") or "codex_cli") if agent_condition else "codex_cli"
    model_target = str(agent_condition.get("model_target") or model or "") if agent_condition else model
    write_json(
        episode_dir / "command.json",
        {
            "condition": condition,
            "runner": runner,
            "model": model_target,
            "br_mode": agent_condition.get("br_mode") if agent_condition else None,
            "command": command_for_record(cmd, prompt),
            "prompt_on_stdin": prompt_on_stdin,
            "skip_reason": skip_reason,
        },
    )
    if skip_reason:
        return {
            "status": "skipped_execution_unavailable_agent",
            "skip_reason": skip_reason,
            "returncode": None,
            "timed_out": False,
            "wall_time_s": 0.0,
            "token_cost_usd": None,
            "tool_call_count": 0,
            "tools_used": [],
            "retry_count": 0,
            "model": model_target,
            "runner": runner,
            "paths": {
                "last_message": str(output_path),
                "events": str(events_path),
                "stderr": str(stderr_path),
            },
        }

    started = time.monotonic()
    early_stop_reason = None
    try:
        returncode, timed_out, early_stop_reason = run_command_to_files(
            command=cmd,
            prompt_path=prompt_path,
            prompt_on_stdin=prompt_on_stdin,
            events_path=events_path,
            stderr_path=stderr_path,
            timeout_s=timeout_s,
            env=episode_env(agent_condition),
        )
    except Exception as exc:
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        returncode = None
        timed_out = False
    elapsed_s = round(time.monotonic() - started, 3)
    tool_call_count, tools = count_tool_events(events_path)
    error_event = has_error_event(events_path)
    last_message = ""
    if runner != "codex_cli" and not timed_out:
        last_message = extract_last_message(events_path)
        if last_message:
            output_path.write_text(last_message + "\n", encoding="utf-8")
    diagnostic_text = "\n".join([_read_recent_text(stderr_path), _read_recent_text(events_path)])
    provider_limit = (
        early_stop_reason == "provider_or_account_limit"
        or _has_provider_or_account_limit(diagnostic_text)
    )
    if provider_limit:
        status = "failed_provider_or_account_limit"
    elif timed_out:
        status = "timed_out"
    elif returncode != 0:
        status = "failed"
    elif error_event:
        status = "failed_error_event"
    elif runner != "codex_cli" and not output_path.exists():
        status = "failed_output_capture"
    elif runner != "codex_cli" and output_path.stat().st_size == 0:
        status = "failed_output_capture"
    else:
        status = "succeeded"
    return {
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "early_stop_reason": early_stop_reason,
        "json_error_event": error_event,
        "wall_time_s": elapsed_s,
        "token_cost_usd": None,
        "tool_call_count": tool_call_count,
        "tools_used": tools,
        "retry_count": 0,
        "model": model_target,
        "runner": runner,
        "br_mode": agent_condition.get("br_mode") if agent_condition else None,
        "paths": {
            "last_message": str(output_path),
            "events": str(events_path),
            "stderr": str(stderr_path),
        },
    }


def materialize_episode(
    run_dir: Path,
    case: dict[str, Any],
    variant: dict[str, Any],
    condition: str,
    execute: bool,
    timeout_s: int,
    reasoning_effort: str,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    model: str | None,
    agent_condition: dict[str, Any] | None = None,
    claude_br_mcp_config: Path | None = None,
    allow_opencode_with_br: bool = False,
    diagnostic_contract: bool = False,
) -> dict[str, Any]:
    case_id = str(case.get("case_id"))
    variant_id = str(variant.get("variant_id"))
    task_shape = str(case.get("task_shape") or "unknown")
    episode_dir = run_dir / "cases" / case_id / f"{variant_id}__{condition}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(
        case,
        variant,
        condition,
        agent_condition,
        diagnostic_contract=diagnostic_contract,
        episode_dir=episode_dir,
    )
    prompt_path = episode_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_payload = {
        "case_id": case_id,
        "variant_id": variant_id,
        "variant_type": variant.get("variant_type"),
        "condition": condition,
        "task_shape": task_shape,
        "prompt": prompt,
        "diagnostic_contract": diagnostic_contract,
        "case_path": case.get("_case_path"),
        "agent_condition": agent_condition,
    }
    write_json(episode_dir / "prompt.json", prompt_payload)
    model_target = (
        str(agent_condition.get("model_target") or "")
        if agent_condition is not None
        else model
    )

    record = {
        "case_id": case_id,
        "variant_id": variant_id,
        "variant_type": variant.get("variant_type"),
        "condition": condition,
        "runner": agent_condition.get("runner") if agent_condition else "codex_cli",
        "br_mode": agent_condition.get("br_mode") if agent_condition else None,
        "model_source": agent_condition.get("model_source") if agent_condition else None,
        "task_shape": task_shape,
        "episode_dir": str(episode_dir),
        "prompt_path": str(prompt_path),
        "execute_requested": execute,
        "status": "materialized",
        "returncode": None,
        "timed_out": False,
        "wall_time_s": 0.0,
        "token_cost_usd": None,
        "tool_call_count": 0,
        "tools_used": [],
        "retry_count": 0,
        "model": model_target,
        "diagnostic_contract": diagnostic_contract,
    }
    if execute:
        if task_shape not in SUPPORTED_EXECUTION_TASK_SHAPES:
            record["status"] = "failed"
            record["skip_reason"] = f"Unknown task_shape: {task_shape}"
        else:
            record.update(
                run_agent_episode(
                    prompt_path=prompt_path,
                    prompt=prompt,
                    run_dir=run_dir,
                    episode_dir=episode_dir,
                    condition=condition,
                    timeout_s=timeout_s,
                    reasoning_effort=reasoning_effort,
                    codex_bin=codex_bin,
                    claude_bin=claude_bin,
                    opencode_bin=opencode_bin,
                    model=model,
                    agent_condition=agent_condition,
                    claude_br_mcp_config=claude_br_mcp_config or (REPO_ROOT / ".mcp.json"),
                    allow_opencode_with_br=allow_opencode_with_br,
                )
            )
    write_json(episode_dir / "record.json", record)
    return record


def print_cases(cases_root: Path) -> None:
    by_id = load_case_index(cases_root)
    for case_id, row in by_id.items():
        print(f"{case_id}\t{row.get('task_shape')}\t{row.get('priority')}\t{row.get('file')}")


def print_variants(cases_root: Path, selectors: list[str]) -> None:
    for case in load_cases(cases_root, selectors):
        print(f"# {case.get('case_id')}")
        variants = case.get("prompt_variants") or []
        if not variants:
            print("(no prompt variants)")
            continue
        for variant in variants:
            print(f"{variant.get('variant_id')}\t{variant.get('variant_type')}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-root", type=Path, default=DEFAULT_CASES_ROOT)
    parser.add_argument("--case", action="append", dest="cases", default=[], help="Case id or case JSON filename/path.")
    parser.add_argument("--variant", action="append", dest="variants", default=[], help="Prompt variant id to include.")
    parser.add_argument("--condition", action="append", dest="conditions", default=[], help="Condition label to run.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--episode-manifest",
        type=Path,
        default=None,
        help=(
            "CSV of exact episodes to run. Required columns: case_id, variant_id, condition. "
            "--case, --variant, and --condition may further filter the manifest."
        ),
    )
    parser.add_argument("--limit-variants", type=int, default=None)
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL"), help="Optional Codex model name, e.g. gpt-5.5.")
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    parser.add_argument("--opencode-bin", default=os.environ.get("OPENCODE_BIN", "opencode"))
    parser.add_argument("--agent-conditions-path", type=Path, default=DEFAULT_AGENT_CONDITIONS_PATH)
    parser.add_argument(
        "--all-coding-agents",
        action="store_true",
        help="Use every coding-agent condition from --agent-conditions-path.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPO_ROOT / ".env",
        help="Optional KEY=VALUE env file loaded before launching model CLIs.",
    )
    parser.add_argument("--claude-br-mcp-config", type=Path, default=REPO_ROOT / ".mcp.json")
    parser.add_argument(
        "--allow-opencode-with-br-without-mcp",
        action="store_true",
        help="Run OpenCode with-BR rows even if `opencode mcp list` reports no configured MCP server.",
    )
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="Materialize prompts only.")
    parser.add_argument("--execute", action="store_true", help="Execute supported episodes through coding-agent CLIs.")
    parser.add_argument(
        "--diagnostic-contract",
        action="store_true",
        help=(
            "Add diagnostic-only family mapping fields to prompts. Use for calibration pilots, "
            "not formal benchmark runs."
        ),
    )
    parser.add_argument(
        "--score-run",
        type=Path,
        default=None,
        help="Compute durable metrics for an existing run directory and exit.",
    )
    parser.add_argument("--allow-empty-variants", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--list-variants", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases_root = args.cases_root.resolve()
    if args.score_run:
        metrics = write_run_metrics(args.score_run.resolve(), cases_root)
        print(json.dumps(metrics, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.list_cases:
        print_cases(cases_root)
        return 0
    if args.list_variants:
        selectors = args.cases or []
        if not selectors:
            print("Provide --case when using --list-variants", file=sys.stderr)
            return 2
        print_variants(cases_root, selectors)
        return 0
    if args.dry_run and args.execute:
        print("Use only one of --dry-run or --execute", file=sys.stderr)
        return 2
    loaded_env_keys = load_env_file(args.env_file.resolve()) if args.env_file else []
    execute = bool(args.execute)
    variant_ids = set(args.variants) if args.variants else None
    episode_manifest_rows: list[dict[str, str]] = []
    if args.episode_manifest:
        try:
            episode_manifest_rows = load_episode_manifest(args.episode_manifest.resolve())
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.cases:
            requested_cases = set(args.cases)
            episode_manifest_rows = [
                row for row in episode_manifest_rows if row["case_id"] in requested_cases
            ]
        if variant_ids is not None:
            episode_manifest_rows = [
                row for row in episode_manifest_rows if row["variant_id"] in variant_ids
            ]
        if args.conditions:
            requested_conditions = set(args.conditions)
            episode_manifest_rows = [
                row for row in episode_manifest_rows if row["condition"] in requested_conditions
            ]
        if not episode_manifest_rows:
            print("Episode manifest selection is empty after filters.", file=sys.stderr)
            return 2
    agent_conditions: dict[str, dict[str, Any]] = {}
    agent_conditions_path = args.agent_conditions_path.resolve()
    if agent_conditions_path.exists():
        agent_conditions = load_agent_conditions(agent_conditions_path)
    elif args.all_coding_agents:
        print(f"Missing coding-agent conditions file: {agent_conditions_path}", file=sys.stderr)
        return 2
    try:
        requested_conditions = (
            sorted({row["condition"] for row in episode_manifest_rows})
            if episode_manifest_rows and not args.conditions
            else args.conditions
        )
        conditions = select_conditions(
            requested=requested_conditions,
            all_coding_agents=args.all_coding_agents,
            agent_conditions=agent_conditions,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    case_selectors = (
        sorted({row["case_id"] for row in episode_manifest_rows})
        if episode_manifest_rows and not args.cases
        else args.cases
    )
    cases = load_cases(cases_root, case_selectors)
    run_name = args.run_name or f"repro_audit_{timestamp()}"
    run_dir = args.out_root.resolve() / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    selected_agent_conditions = {
        condition: agent_conditions[condition]
        for condition in conditions
        if condition in agent_conditions
    }

    manifest = {
        "run_name": run_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "cases_root": str(cases_root),
        "execute": execute,
        "conditions": conditions,
        "agent_conditions_path": str(agent_conditions_path),
        "agent_conditions": selected_agent_conditions,
        "all_coding_agents": args.all_coding_agents,
        "selected_cases": [case.get("case_id") for case in cases],
        "selected_variants": sorted(variant_ids) if variant_ids else "all",
        "episode_manifest": str(args.episode_manifest.resolve()) if args.episode_manifest else None,
        "episode_manifest_rows": len(episode_manifest_rows),
        "episode_manifest_exact": bool(episode_manifest_rows),
        "model": args.model,
        "loaded_env_keys": loaded_env_keys,
        "max_workers": args.max_workers,
        "diagnostic_contract": args.diagnostic_contract,
        "supported_execution_task_shapes": sorted(SUPPORTED_EXECUTION_TASK_SHAPES),
        "notes": [
            "Dry-run materializes prompt packets without agent calls.",
            "Execution is implemented for all declared reproducibility task shapes; non-grounded task shapes currently receive contract-level metrics unless a task-specific scorer exists.",
            "diagnostic_contract adds calibration-only family mapping fields and should not be used for benchmark-grade evaluation claims.",
            "token_cost_usd is reserved for future provider accounting and is currently null.",
        ],
    }
    write_json(run_dir / "run_manifest.json", manifest)
    records: list[dict[str, Any]] = []
    episode_requests: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    if episode_manifest_rows:
        condition_set = set(conditions)
        case_by_id = {str(case.get("case_id")): case for case in cases}
        for row in episode_manifest_rows:
            condition = row["condition"]
            if condition not in condition_set:
                continue
            case = case_by_id.get(row["case_id"])
            if case is None:
                print(f"Episode manifest references an unselected case: {row['case_id']}", file=sys.stderr)
                return 2
            variant = _variant_by_id(case).get(row["variant_id"])
            if variant is None:
                print(
                    f"Episode manifest references unknown variant {row['variant_id']} "
                    f"for case {row['case_id']}",
                    file=sys.stderr,
                )
                return 2
            episode_requests.append((case, variant, condition))
    else:
        for case in cases:
            variants = selected_variants(case, variant_ids)
            if args.limit_variants is not None:
                variants = variants[: args.limit_variants]
            if not variants:
                if args.allow_empty_variants:
                    record = {
                        "case_id": case.get("case_id"),
                        "status": "skipped_no_prompt_variants",
                        "case_path": case.get("_case_path"),
                    }
                    records.append(record)
                    append_jsonl(run_dir / "episodes.jsonl", record)
                    continue
                print(f"No prompt variants selected for case {case.get('case_id')}", file=sys.stderr)
                return 2
            for variant in variants:
                for condition in conditions:
                    episode_requests.append((case, variant, condition))

    def run_one(request: tuple[dict[str, Any], dict[str, Any], str]) -> dict[str, Any]:
        case, variant, condition = request
        return materialize_episode(
            run_dir=run_dir,
            case=case,
            variant=variant,
            condition=condition,
            execute=execute,
            timeout_s=args.timeout_s,
            reasoning_effort=args.reasoning_effort,
            codex_bin=args.codex_bin,
            claude_bin=args.claude_bin,
            opencode_bin=args.opencode_bin,
            model=args.model,
            agent_condition=agent_conditions.get(condition),
            claude_br_mcp_config=args.claude_br_mcp_config.resolve(),
            allow_opencode_with_br=args.allow_opencode_with_br_without_mcp,
            diagnostic_contract=args.diagnostic_contract,
        )

    workers = max(1, args.max_workers)
    if workers == 1:
        for request in episode_requests:
            record = run_one(request)
            records.append(record)
            append_jsonl(run_dir / "episodes.jsonl", record)
            print(
                f"{record['status']}\t{record.get('case_id')}\t{record.get('variant_id')}\t"
                f"{record.get('condition')}\t{record.get('episode_dir')}",
                flush=True,
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_one, request) for request in episode_requests]
            for future in as_completed(futures):
                record = future.result()
                records.append(record)
                append_jsonl(run_dir / "episodes.jsonl", record)
                print(
                    f"{record['status']}\t{record.get('case_id')}\t{record.get('variant_id')}\t"
                    f"{record.get('condition')}\t{record.get('episode_dir')}",
                    flush=True,
                )
    summary = {
        "run_dir": str(run_dir),
        "episodes": len(records),
        "status_counts": {},
        "condition_status_counts": {},
    }
    for record in records:
        status = str(record.get("status"))
        summary["status_counts"][status] = summary["status_counts"].get(status, 0) + 1
        condition = str(record.get("condition"))
        condition_counts = summary["condition_status_counts"].setdefault(condition, {})
        condition_counts[status] = condition_counts.get(status, 0) + 1
    metrics = write_run_metrics(run_dir, cases_root)
    summary["metrics"] = {
        "metrics_json": str(run_dir / "metrics.json"),
        "episode_metrics_jsonl": str(run_dir / "episode_metrics.jsonl"),
        "metrics_report_md": str(run_dir / "METRICS_REPORT.md"),
        "status_summary": metrics.get("status_summary"),
        "episodes_scored": metrics.get("episodes_scored"),
        "condition_comparisons": metrics.get("condition_comparisons"),
    }
    write_json(run_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
