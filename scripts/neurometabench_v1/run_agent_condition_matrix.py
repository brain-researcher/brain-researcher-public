#!/usr/bin/env python3
"""Run NeuroMetaBench coding-agent producer conditions.

This launcher is intentionally about coding-agent surfaces, not direct LLM API
calls. It materializes per-condition prompts, runs the configured CLI when
requested, records cost/latency-adjacent episode metadata, and aggregates Layer A
prediction bundles for the existing evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.evaluate_study_set import evaluate_prediction_files
from scripts.neurometabench_v1.layer_b_harness_finalizer import (
    BR_REQUIRED_MODES,
    finalize_layer_b_episode,
)
from scripts.neurometabench_v1.run_layer_b_comparison import (
    ConditionInput as LayerBConditionInput,
    run_comparison as run_layer_b_comparison,
)
from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    LAYER_A_SCREENING,
    LAYER_B_REPRODUCTION,
    load_case_records,
    load_mixed_pool_candidates,
    read_jsonl,
    write_jsonl,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONDITIONS_PATH = (
    REPO_ROOT / "benchmarks" / "neurometabench" / "agent_conditions.v1.jsonl"
)
DEFAULT_LAYER_A_PROMPT = (
    REPO_ROOT
    / "benchmarks"
    / "neurometabench"
    / "prompts"
    / "layer_a_coding_agent_producer.md"
)
DEFAULT_LAYER_B_PROMPT = (
    REPO_ROOT
    / "benchmarks"
    / "neurometabench"
    / "prompts"
    / "layer_b_coding_agent_producer.md"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "benchmarks" / "neurometabench" / "experiments" / "agent_condition_matrix"
)
DEFAULT_LAYER_B_PURE_NIMARE_OUTPUT = (
    REPO_ROOT / "benchmarks" / "neurometabench" / "experiments" / "path_b_reproduction"
)
LAYER_B_EVALUATOR_PATH = REPO_ROOT / "scripts" / "neurometabench_v1" / "run_layer_b_comparison.py"
CONDITION_RECORD_TYPE = "condition"
BR_MODE_WITH = "with_br_mcp"
BR_MODE_WITH_REQUIRED = "with_br_required"
BR_MODES_WITH_TOOLS = {BR_MODE_WITH, *BR_REQUIRED_MODES}
OPENCODE_MCP_MISSING_STATUS = "skipped_missing_opencode_br_mcp"
MIXED_POOL_BUDGET_POLICY = "preserve_all_gt_pmids_may_exceed_requested_max"
LAYER_A_BR_SCREENING_ANCHORS = "br_screening_anchors.json"
EPISODE_SCOPE_CASE = "case"
EPISODE_SCOPE_CONDITION = "condition"
PROCESS_GROUP_SHUTDOWN_GRACE_S = 5
AGENT_VISIBLE_CANDIDATE_FIELDS = {
    "pmid",
    "study_pmid",
    "rank",
    "title",
    "abstract",
    "author",
    "authors",
    "year",
    "journal",
    "doi",
    "pmcid",
    "pub_types",
    "publication_types",
}


@dataclass(frozen=True)
class Condition:
    condition_id: str
    runner: str
    model_target: str
    br_mode: str
    layers: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class Episode:
    condition: Condition
    episode_dir: Path
    producer_output_dir: Path
    command: list[str]
    prompt: str
    meta_pmids: tuple[str, ...]
    status: str = "materialized"
    skip_reason: str | None = None


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_default)
        + "\n",
        encoding="utf-8",
    )


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
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        os.environ[key] = value
        loaded.append(key)
    return loaded


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=json_default)
            + "\n"
        )


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


def read_json_or_none(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_conditions(path: Path) -> list[Condition]:
    out: list[Condition] = []
    for row in read_jsonl_rows(path):
        if row.get("record_type") != CONDITION_RECORD_TYPE:
            continue
        condition_id = str(row.get("condition_id") or "").strip()
        runner = str(row.get("runner") or "").strip()
        model_target = str(row.get("model_target") or "").strip()
        br_mode = str(row.get("br_mode") or "").strip()
        layers = tuple(str(layer) for layer in row.get("layers") or ())
        if not condition_id or not runner or not model_target:
            raise ValueError(f"Malformed condition row in {path}: {row}")
        out.append(
            Condition(
                condition_id=condition_id,
                runner=runner,
                model_target=model_target,
                br_mode=br_mode,
                layers=layers,
                raw=row,
            )
        )
    return out


def filter_conditions(
    conditions: Iterable[Condition],
    *,
    layer: str,
    condition_ids: set[str],
    runners: set[str],
    max_conditions: int | None,
) -> list[Condition]:
    selected: list[Condition] = []
    for condition in conditions:
        if layer not in condition.layers:
            continue
        if condition_ids and condition.condition_id not in condition_ids:
            continue
        if runners and condition.runner not in runners:
            continue
        selected.append(condition)
        if max_conditions is not None and len(selected) >= max_conditions:
            break
    return selected


def condition_br_available(condition: Condition) -> bool:
    return condition.br_mode in BR_MODES_WITH_TOOLS


def condition_br_required(condition: Condition, *, force_required: bool = False) -> bool:
    return condition_br_available(condition) and (
        force_required or condition.br_mode in BR_REQUIRED_MODES
    )


def _layer_key(layer: str) -> str:
    if layer == "layer_a":
        return LAYER_A_SCREENING
    if layer == "layer_b":
        return LAYER_B_REPRODUCTION
    raise ValueError(f"Unsupported layer: {layer}")


def select_cases(
    *,
    cases_path: Path,
    layer: str,
    meta_pmids: set[str],
    limit_cases: int | None,
) -> list[dict[str, Any]]:
    target_layer = _layer_key(layer)
    selected: list[dict[str, Any]] = []
    for case in load_case_records(cases_path):
        meta_pmid = str(case.get("meta_pmid") or "").strip()
        if not meta_pmid:
            continue
        if meta_pmids and meta_pmid not in meta_pmids and f"neurometabench:{meta_pmid}" not in meta_pmids:
            continue
        task_layers = case.get("task_layers") or []
        if case.get("primary_task_layer") != target_layer and target_layer not in task_layers:
            continue
        selected.append(case)
        if limit_cases is not None and len(selected) >= limit_cases:
            break
    return selected


def _safe_case_for_agent(case: dict[str, Any]) -> dict[str, Any]:
    blocked = {"gt_pmids", "n_gt", "selected_n"}
    return {key: value for key, value in case.items() if key not in blocked}


def _safe_candidate_for_agent(source: dict[str, Any], *, pmid: str, rank: int) -> dict[str, Any]:
    """Return the physically agent-visible candidate row.

    The raw mixed-pool source tables can carry answer-key-shaped fields such as
    corrected labels, source sheet names, or source meta-analysis IDs. Keep a
    small bibliographic allowlist so benchmark prompts do not depend on moral
    anti-cheat instructions.
    """

    out: dict[str, Any] = {}
    for field in AGENT_VISIBLE_CANDIDATE_FIELDS:
        value = source.get(field)
        if value not in (None, ""):
            out[field] = value
    out["pmid"] = pmid
    out.setdefault("study_pmid", pmid)
    out["rank"] = rank
    return out


def _load_study_metadata(data_dir: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for filename in (
        "all_studies_annotated_wt.csv",
        "all_studies_annotated.csv",
        "all_studies.csv",
    ):
        path = data_dir / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                pmid = str(row.get("study_pmid") or row.get("pmid") or "").strip()
                if pmid and pmid not in metadata:
                    metadata[pmid] = dict(row)
    return metadata


def materialize_layer_a_inputs(
    *,
    run_dir: Path,
    cases: list[dict[str, Any]],
    data_dir: Path,
    max_candidates: int,
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
) -> dict[str, Path]:
    """Write agent-visible case inputs without gold PMID labels."""

    input_root = run_dir / "case_inputs" / "layer_a"
    metadata = _load_study_metadata(data_dir)
    outputs: dict[str, Path] = {}
    for case in cases:
        meta_pmid = str(case.get("meta_pmid") or "").strip()
        case_dir = input_root / f"layer_a_{meta_pmid}_mixed_pool"
        candidate_pmids = load_mixed_pool_candidates(
            data_dir,
            meta_pmid,
            noise_ratio=mixed_pool_noise_ratio,
            seed=mixed_pool_seed,
            max_total=max_candidates,
        )
        candidate_rows: list[dict[str, Any]] = []
        for rank, pmid in enumerate(candidate_pmids, 1):
            source = dict(metadata.get(pmid, {}))
            candidate_rows.append(_safe_candidate_for_agent(source, pmid=pmid, rank=rank))

        write_json(case_dir / "case.json", _safe_case_for_agent(case))
        write_jsonl(candidate_rows, case_dir / "candidates.jsonl")
        write_json(
            case_dir / "input_manifest.json",
            {
                "case_id": case.get("case_id"),
                "meta_pmid": meta_pmid,
                "candidate_source": "mixed_pool",
                "candidate_pmids_file": "candidates.jsonl",
                "n_candidates": len(candidate_rows),
                "requested_max_candidates": max_candidates,
                "max_candidates": max_candidates,
                "candidate_budget_policy": MIXED_POOL_BUDGET_POLICY,
                "candidate_count_exceeds_requested_max": len(candidate_rows)
                > max_candidates,
                "mixed_pool_noise_ratio": mixed_pool_noise_ratio,
                "mixed_pool_seed": mixed_pool_seed,
                "gold_labels_visible_to_agent": False,
            },
        )
        outputs[meta_pmid] = case_dir
    return outputs


def materialize_layer_b_inputs(
    *,
    run_dir: Path,
    cases: list[dict[str, Any]],
) -> dict[str, Path]:
    input_root = run_dir / "case_inputs" / "layer_b"
    outputs: dict[str, Path] = {}
    for case in cases:
        meta_pmid = str(case.get("meta_pmid") or "").strip()
        case_dir = input_root / f"layer_b_{meta_pmid}"
        write_json(case_dir / "case.json", _safe_case_for_agent(case))
        write_json(
            case_dir / "input_manifest.json",
            {
                "case_id": case.get("case_id"),
                "meta_pmid": meta_pmid,
                "nimads_assets": case.get("nimads_assets"),
                "gold_labels_visible_to_agent": False,
            },
        )
        outputs[meta_pmid] = case_dir
    return outputs


def build_prompt(
    *,
    base_prompt: str,
    layer: str,
    condition: Condition,
    cases: list[dict[str, Any]],
    input_dirs: dict[str, Path],
    producer_output_dir: Path,
    max_candidates: int,
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
    layer_b_soft_deadline_s: int | None = None,
    require_br_effective_use: bool = False,
) -> str:
    per_case_episode = len(cases) == 1
    case_rows = [
        {
            "case_id": case.get("case_id"),
            "meta_pmid": case.get("meta_pmid"),
            "topic": case.get("topic"),
            "input_dir": str(input_dirs[str(case.get("meta_pmid"))]),
        }
        for case in cases
    ]
    case_list = "\n".join(
        f"- {row['meta_pmid']} ({row['topic']}): `{row['input_dir']}`"
        for row in case_rows
    )
    br_required = condition_br_required(
        condition,
        force_required=require_br_effective_use,
    )
    if condition_br_available(condition):
        br_instruction = (
            "BR MCP/tools are available for this condition. Use them as you would "
            "any other available tool. Record any BR calls that you make."
        )
        if layer == "layer_a":
            br_instruction += (
                "\n- Layer A BR use is for recall-oriented evidence recovery. "
                "Do not use BR as a conservative exclusion filter."
                "\n- Do not exclude a candidate merely because BR did not return "
                "supporting evidence. If local title/abstract evidence is plausible "
                "but incomplete after BR use, preserve the candidate as `uncertain`."
                "\n- Keep the include / exclude / uncertain triage explicit. BR can "
                "support include decisions, recover evidence for uncertain candidates, "
                "or document criterion-grounded exclusions."
                "\n- When BR materially affects screening, write "
                "`br_screening_anchors.json` with an `anchors` list. Each anchor "
                "must include `candidate_pmid`, `decision`, `supports_inclusion`, "
                "`eligibility_criterion`, `evidence_source`, `evidence_summary`, "
                "`confidence`, and `consumed_by`; the same candidate and decision "
                "must appear in `screening_decisions.jsonl`."
            )
            if br_required:
                br_instruction += (
                    "\n- This is a BR-required Layer A condition: make at least one "
                    "BR call for screening evidence recovery, and write a non-empty "
                    "`br_screening_anchors.json` consumed by `screening_decisions.jsonl`."
                    " At least one consumed anchor must be inclusion-supporting: "
                    "`supports_inclusion=true` with decision `include` or `uncertain`. "
                    "Exclusion-only anchors are audit metadata and do not satisfy the "
                    "required-BR recovery gate."
                )
        elif br_required:
            br_instruction += (
                "\n- This is a BR-required condition: make at least one BR call "
                "for route/preflight, reconciliation, or audit; include the BR "
                "anchor in provenance and consume the anchor in either an artifact "
                "or the report."
                "\n- BR table write policy: conservative. BR is enrichment-first "
                "and correction-second in Layer B reproduction mode."
                "\n- Treat `coordinate_table.csv` and `included_studies.csv` as "
                "reproduction artifacts owned by the local NiMADS/NiMARE "
                "extraction. Do not split, merge, rename, case-normalize, "
                "punctuation-normalize, alias-expand, or replace local "
                "`study_id` / `study_name` values based on BR evidence."
                "\n- Do not use BR to transform coordinate spaces, change "
                "coordinate values, filter annotation subsets, or alter analysis "
                "IDs. BR can describe these reconciliations in "
                "`spatial_report.md`, `provenance_manifest.json`, or "
                "`br_reconciliation_anchors.json`."
                "\n- Make useful BR results canonicalizable for audit artifacts: "
                "map each BR-derived identifier or provenance fact to explicit "
                "fields such as `study_id`, `study_pmid`, `doi`, `pmcid`, "
                "`source_asset`, `source_file`, `sample_size`, `coordinate_space`, "
                "and `original_study_ids`; consume audited values in "
                "`spatial_report.md`, `provenance_manifest.json`, or "
                "`br_reconciliation_anchors.json` by default."
                "\n- Write `br_reconciliation_anchors.json` in each case bundle "
                "with an `anchors` list. Each anchor must name `target_artifact`, "
                "`target_field`, `canonical_value`, `evidence_source`, "
                "`evidence_summary`, `confidence`, and `changed_bundle`; changed "
                "anchors must use the canonical value in the target artifact or "
                "report."
                "\n- Keep anchor `canonical_value` entries short and exact. Put "
                "explanatory prose in `evidence_summary`, not in "
                "`canonical_value`."
                "\n- Do not set `changed_bundle=true` for audit-only evidence. "
                "Use `changed_bundle=true` only when the exact `canonical_value` "
                "appears in the named `target_artifact` or in "
                "`spatial_report.md`."
                "\n- If a BR response provides `canonical_anchors`, copy those "
                "anchors into `br_reconciliation_anchors.json` where applicable."
                "\n- Add a compact `BR reconciliation anchors` line or table to "
                "`spatial_report.md` that repeats every changed `canonical_value` "
                "exactly."
                "\n- Do not change scientific table values solely to satisfy "
                "anchor consumption. Preserve the canonical NiMADS/NiMARE values "
                "needed for reproduction in `coordinate_table.csv` and "
                "`included_studies.csv`."
                "\n- Prefer `spatial_report.md` or `provenance_manifest.json` as "
                "the `target_artifact` for BR audit anchors. Use "
                "`coordinate_table.csv` or `included_studies.csv` only when the "
                "BR result directly corrects or fills a blank or unparseable "
                "canonical field in that table. Preserve the raw local value in "
                "an `original_*` or `source_*` field instead of replacing identity "
                "evidence."
                "\n- Use the repository NiMADS/NiMARE reproduction path whenever "
                "possible. Do not replace `convert_nimads_to_dataset` or the "
                "repository reproduction helper with a hand-rolled ALE/KDE map "
                "generator unless the official path is unavailable. Fallback or "
                "synthetic maps must be marked degraded with `map_generated=false` "
                "or `map_generation_status=degraded_fallback` and an exact reason "
                "in `metrics.json`, `provenance_manifest.json`, and "
                "`spatial_report.md`."
            )
    else:
        br_instruction = "BR MCP/tools are disabled for this condition. Do not call BR tools."
    aggregate_instruction = (
        "- This is a one-case episode. Write only that case bundle; the outer\n"
        "  harness will aggregate prediction rows across case episodes.\n"
        if per_case_episode
        else "- Write one case bundle per listed case; the outer harness will aggregate\n"
        "  prediction rows after the episode finishes.\n"
    )
    layer_specific = (
        f"""
Layer A matrix overrides:
- Candidate source: `mixed_pool`
- Requested candidate cap: `{max_candidates}`
- Candidate budget policy: `{MIXED_POOL_BUDGET_POLICY}`. The actual
  per-case candidate count in `input_manifest.json` is authoritative and may
  exceed the requested cap when a case has more GT PMIDs than the cap.
- Mixed-pool noise ratio: `{mixed_pool_noise_ratio}`
- Mixed-pool seed: `{mixed_pool_seed}`
- For each case, read `case.json`, `input_manifest.json`, and `candidates.jsonl`
  from the input directory listed below.
- Screen and rank exactly every row in each `candidates.jsonl`; do not stop at
  the requested cap when the materialized file contains more rows.
- Write each case bundle under:
  `{producer_output_dir}/layer_a_<meta_pmid>_mixed_pool/`
{aggregate_instruction.rstrip()}
"""
        if layer == "layer_a"
        else f"""
Layer B matrix overrides:
- For each case, read `case.json` and `input_manifest.json` from the input
  directory listed below.
- Write each case bundle under:
  `{producer_output_dir}/layer_b_<meta_pmid>/`
- Write a condition-level `RUN_SUMMARY.json` under:
  `{producer_output_dir}/RUN_SUMMARY.json`
- Evaluator contract path:
  `{LAYER_B_EVALUATOR_PATH}`
- Before doing substantive work, run:
  `python {LAYER_B_EVALUATOR_PATH} --print-contract`
- The harness exports `METABENCH_EVALUATOR_PATH`, `METABENCH_OUTPUT_DIR`,
  `METABENCH_CASE_ID`, and `METABENCH_META_PMID` for one-case episodes.
- Soft deadline: `{layer_b_soft_deadline_s if layer_b_soft_deadline_s else "not_set"}`
  seconds. Do not spend more than the first third of the run exploring files.
  If a soft deadline is set, stop exploration before that point and finalize
  artifacts: write the current `coordinate_table.csv`, `included_studies.csv`,
  valid ALE map paths if generation succeeded, `provenance_manifest.json`,
  `spatial_report.md`, and `br_reconciliation_anchors.json` for BR-required
  runs; run artifact preflight/finalizer if available; then exit cleanly.
  If ALE generation failed and only a synthetic or fallback approximation is
  available, mark the map degraded instead of presenting it as a clean ALE map.
- In BR-required Layer B conditions, `br_reconciliation_anchors.json` is a
  required BR-specific contract artifact; without-BR conditions should not
  synthesize it.
"""
    )

    return f"""{base_prompt.rstrip()}

---

# Matrix Run Overrides

Run only the cases below and only this condition.

Condition:
- condition_id: `{condition.condition_id}`
- runner: `{condition.runner}`
- model_target: `{condition.model_target}`
- br_mode: `{condition.br_mode}`
- producer_output_dir: `{producer_output_dir}`

Cases:
{case_list}

{layer_specific.strip()}

Anti-cheat boundary:
- Do not inspect or use `gt_pmids`, included-study answer keys, evaluator outputs,
  prior experiment outputs, pure NiMARE/control outputs, or any generated baseline
  prediction files to make bundle contents.
- Use only the sanitized per-case inputs above, repository code, public metadata,
  and permitted tools for the condition.
- If you discover that a required input is missing, write a `failure.json` in the
  relevant bundle and continue to the next case.

BR boundary:
{br_instruction}

Required execution metadata:
- Write `trajectory.json` or `provenance_manifest.json` with tool calls, commands,
  start/end timestamps, and any failure reasons.
- Write `observation.json` for Layer A case bundles with enough details to audit
  screening behavior.
- Do not run the benchmark evaluator. The outer harness runs evaluation after
  producer artifacts are complete.
- Do not finish with prose only; the benchmark consumes files.
"""


def _command_exists(binary: str) -> bool:
    return shutil.which(binary) is not None


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
    return result.returncode == 0 and "no mcp servers configured" not in combined


def empty_mcp_config(run_dir: Path) -> Path:
    path = run_dir / "empty_mcp.json"
    write_json(path, {"mcpServers": {}})
    return path


def build_command(
    *,
    condition: Condition,
    prompt: str,
    run_dir: Path,
    repo_root: Path,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    claude_br_mcp_config: Path,
    allow_opencode_with_br: bool,
) -> tuple[list[str], str | None]:
    if condition.runner == "codex_cli":
        if not _command_exists(codex_bin):
            return [], f"missing_binary:{codex_bin}"
        br_enabled = "true" if condition_br_available(condition) else "false"
        command = [
            codex_bin,
            "--ask-for-approval",
            "never",
            "-c",
            f"mcp_servers.brain-researcher-prod.enabled={br_enabled}",
            "-m",
            condition.model_target,
            "exec",
            "--cd",
            str(repo_root),
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "-",
        ]
        return command, None

    if condition.runner == "claude_code":
        if not _command_exists(claude_bin):
            return [], f"missing_binary:{claude_bin}"
        mcp_config = (
            claude_br_mcp_config
            if condition_br_available(condition)
            else empty_mcp_config(run_dir)
        )
        if condition_br_available(condition) and not mcp_config.exists():
            return [], f"missing_claude_br_mcp_config:{mcp_config}"
        command = [
            claude_bin,
            "-p",
            "--model",
            condition.model_target,
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "stream-json",
            "--verbose",
            "--add-dir",
            str(repo_root),
            "--mcp-config",
            str(mcp_config),
            "--strict-mcp-config",
            prompt,
        ]
        return command, None

    if condition.runner == "opencode":
        if not _command_exists(opencode_bin):
            return [], f"missing_binary:{opencode_bin}"
        if condition_br_available(condition) and not allow_opencode_with_br:
            if not opencode_has_mcp():
                return [], OPENCODE_MCP_MISSING_STATUS
        command = [
            opencode_bin,
            "run",
            "--dir",
            str(repo_root),
            "--model",
            condition.model_target,
            "--format",
            "json",
            "--dangerously-skip-permissions",
            prompt,
        ]
        return command, None

    return [], f"unsupported_runner:{condition.runner}"


def _count_tool_calls(output_text: str) -> tuple[int, list[str]]:
    count = 0
    names: list[str] = []
    for line in output_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        text = json.dumps(payload, sort_keys=True)
        if "tool_call" in text or "mcp_tool_call" in text:
            count += 1
        for key in ("tool", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value not in names:
                names.append(value)
    return count, names


def _has_json_error_event(output_text: str) -> bool:
    for line in output_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "error" or payload.get("error"):
            return True
    return False


def materialize_episode(episode: Episode) -> None:
    episode.episode_dir.mkdir(parents=True, exist_ok=True)
    episode.producer_output_dir.mkdir(parents=True, exist_ok=True)
    (episode.episode_dir / "prompt.txt").write_text(episode.prompt, encoding="utf-8")
    write_json(
        episode.episode_dir / "command.json",
        {
            "condition_id": episode.condition.condition_id,
            "runner": episode.condition.runner,
            "model_target": episode.condition.model_target,
            "br_mode": episode.condition.br_mode,
            "meta_pmids": list(episode.meta_pmids),
            "command": episode.command,
            "producer_output_dir": episode.producer_output_dir,
            "status": episode.status,
            "skip_reason": episode.skip_reason,
        },
    )


def episode_env(
    episode: Episode,
    *,
    layer_b_soft_deadline_s: int | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    if (
        episode.condition.runner == "opencode"
        and not condition_br_available(episode.condition)
    ):
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    env["METABENCH_EVALUATOR_PATH"] = str(LAYER_B_EVALUATOR_PATH)
    env["METABENCH_OUTPUT_ROOT"] = str(episode.producer_output_dir)
    if episode.meta_pmids:
        meta_pmid = episode.meta_pmids[0]
        env["METABENCH_META_PMID"] = meta_pmid
        env["METABENCH_CASE_ID"] = f"neurometabench:{meta_pmid}"
        env["METABENCH_OUTPUT_DIR"] = str(
            episode.producer_output_dir / f"layer_b_{meta_pmid}"
        )
    if layer_b_soft_deadline_s:
        env["METABENCH_SOFT_DEADLINE_S"] = str(layer_b_soft_deadline_s)
    return env


def _terminate_process_group(process: subprocess.Popen[str]) -> bool:
    """Terminate a process and its children when a timeout fires."""

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
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                pass
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


def _run_command_with_group_timeout(
    *,
    command: list[str],
    input_text: str | None,
    env: dict[str, str],
    timeout_s: int,
) -> tuple[subprocess.CompletedProcess[str] | None, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout_s)
        return (
            subprocess.CompletedProcess(command, process.returncode, stdout, stderr),
            stdout or "",
            stderr or "",
            False,
        )
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=PROCESS_GROUP_SHUTDOWN_GRACE_S)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            stdout, stderr = process.communicate()
        return None, stdout or "", stderr or "", True


def run_episode(
    *,
    episode: Episode,
    timeout_s: int,
    dry_run: bool,
    layer: str = "layer_a",
    run_dir: Path | None = None,
    enable_layer_b_finalizer: bool = False,
    require_br_effective_use: bool = False,
    layer_b_soft_deadline_s: int | None = None,
) -> dict[str, Any]:
    materialize_episode(episode)
    started = utc_now()
    start_time = time.monotonic()
    record: dict[str, Any] = {
        "condition_id": episode.condition.condition_id,
        "runner": episode.condition.runner,
        "model_target": episode.condition.model_target,
        "br_mode": episode.condition.br_mode,
        "meta_pmids": list(episode.meta_pmids),
        "started_at": started,
        "producer_output_dir": str(episode.producer_output_dir),
        "episode_dir": str(episode.episode_dir),
        "dry_run": dry_run,
        "status": episode.status,
        "skip_reason": episode.skip_reason,
        "wall_time_s": 0.0,
        "tool_calls": 0,
        "tools_used": [],
        "retry_count": 0,
        "token_cost": None,
        "token_cost_status": "not_instrumented",
    }
    if dry_run:
        record["status"] = "dry_run"
        write_json(episode.episode_dir / "record.json", record)
        return record
    if episode.skip_reason:
        record["status"] = "skipped"
        record["ended_at"] = utc_now()
        write_json(episode.episode_dir / "record.json", record)
        return record

    result, stdout, stderr, timed_out = _run_command_with_group_timeout(
        command=episode.command,
        input_text=episode.prompt if episode.condition.runner == "codex_cli" else None,
        env=episode_env(
            episode,
            layer_b_soft_deadline_s=layer_b_soft_deadline_s,
        ),
        timeout_s=timeout_s,
    )
    if result is not None and not timed_out:
        wall_time_s = round(time.monotonic() - start_time, 3)
        (episode.episode_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (episode.episode_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        tool_calls, tools_used = _count_tool_calls(f"{stdout}\n{stderr}")
        error_event = _has_json_error_event(f"{stdout}\n{stderr}")
        status = "succeeded" if result.returncode == 0 else "failed"
        if result.returncode == 0 and error_event:
            status = "failed"
        record.update(
            {
                "status": status,
                "returncode": result.returncode,
                "json_error_event": error_event,
                "opencode_project_config_disabled": (
                    episode.condition.runner == "opencode"
                    and not condition_br_available(episode.condition)
                ),
                "ended_at": utc_now(),
                "wall_time_s": wall_time_s,
                "tool_calls": tool_calls,
                "tools_used": tools_used,
            }
        )
    else:
        wall_time_s = round(time.monotonic() - start_time, 3)
        (episode.episode_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (episode.episode_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        record.update(
            {
                "status": "timed_out",
                "returncode": None,
                "ended_at": utc_now(),
                "wall_time_s": wall_time_s,
                "error": f"timeout after {timeout_s}s",
                "terminated_process_group": True,
                "opencode_project_config_disabled": (
                    episode.condition.runner == "opencode"
                    and not condition_br_available(episode.condition)
                ),
            }
        )
    if (
        layer == "layer_b"
        and enable_layer_b_finalizer
        and run_dir is not None
        and not dry_run
        and not episode.skip_reason
    ):
        finalizer = finalize_layer_b_episode(
            producer_output_dir=episode.producer_output_dir,
            input_root=run_dir / "case_inputs" / "layer_b",
            meta_pmids=list(episode.meta_pmids),
            condition_metadata={
                "condition_id": episode.condition.condition_id,
                "runner": episode.condition.runner,
                "model_target": episode.condition.model_target,
                "br_mode": episode.condition.br_mode,
            },
            command=episode.command,
            started_at=record.get("started_at"),
            ended_at=record.get("ended_at"),
            repo_root=REPO_ROOT,
            episode_dir=episode.episode_dir,
            require_br_effective_use=condition_br_required(
                episode.condition,
                force_required=require_br_effective_use,
            ),
        )
        record["layer_b_harness_finalizer"] = finalizer
        if record.get("status") == "succeeded" and not finalizer["all_br_required_pass"]:
            record["status"] = "failed_br_required_gate"
            record["error"] = "BR-required condition did not produce an effective BR anchor"
    write_json(episode.episode_dir / "record.json", record)
    return record


def _load_resume_record(episode: Episode) -> dict[str, Any] | None:
    record_path = episode.episode_dir / "record.json"
    if not record_path.exists():
        return None
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    status = str(record.get("status") or "")
    if status not in {
        "succeeded",
        "skipped",
        "failed",
        "timed_out",
        "failed_output_validation",
        "failed_br_required_gate",
    }:
        return None
    record["resumed_from_record"] = True
    return record


def _round_robin_by_condition(episodes: list[Episode]) -> list[Episode]:
    grouped: dict[str, list[Episode]] = {}
    for episode in episodes:
        grouped.setdefault(episode.condition.condition_id, []).append(episode)
    ordered: list[Episode] = []
    while grouped:
        empty: list[str] = []
        for condition_id, condition_episodes in grouped.items():
            ordered.append(condition_episodes.pop(0))
            if not condition_episodes:
                empty.append(condition_id)
        for condition_id in empty:
            del grouped[condition_id]
    return ordered


def run_episodes(
    *,
    episodes: list[Episode],
    timeout_s: int,
    dry_run: bool,
    max_workers: int,
    resume: bool,
    records_path: Path,
    layer: str = "layer_a",
    run_dir: Path | None = None,
    enable_layer_b_finalizer: bool = False,
    require_br_effective_use: bool = False,
    layer_b_soft_deadline_s: int | None = None,
) -> list[dict[str, Any]]:
    workers = max(1, max_workers)
    records: list[dict[str, Any]] = []
    pending: list[Episode] = []
    for episode in episodes:
        record = _load_resume_record(episode) if resume else None
        if record is not None:
            records.append(record)
        else:
            pending.append(episode)

    if workers > 1:
        pending = _round_robin_by_condition(pending)

    if workers == 1:
        for episode in pending:
            record = run_episode(
                episode=episode,
                timeout_s=timeout_s,
                dry_run=dry_run,
                layer=layer,
                run_dir=run_dir,
                enable_layer_b_finalizer=enable_layer_b_finalizer,
                require_br_effective_use=require_br_effective_use,
                layer_b_soft_deadline_s=layer_b_soft_deadline_s,
            )
            records.append(record)
            append_jsonl(records_path, record)
        return records

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_episode = {
            executor.submit(
                run_episode,
                episode=episode,
                timeout_s=timeout_s,
                dry_run=dry_run,
                layer=layer,
                run_dir=run_dir,
                enable_layer_b_finalizer=enable_layer_b_finalizer,
                require_br_effective_use=require_br_effective_use,
                layer_b_soft_deadline_s=layer_b_soft_deadline_s,
            ): episode
            for episode in pending
        }
        for future in as_completed(future_to_episode):
            record = future.result()
            records.append(record)
            append_jsonl(records_path, record)
    return records


def _layer_a_anchor_list(case_dir: Path) -> list[dict[str, Any]]:
    payload = read_json_or_none(case_dir / LAYER_A_BR_SCREENING_ANCHORS)
    if isinstance(payload, dict):
        payload = payload.get("anchors")
    if not isinstance(payload, list):
        return []
    return [anchor for anchor in payload if isinstance(anchor, dict)]


def collect_layer_a_predictions(run_dir: Path, conditions: list[Condition]) -> list[Path]:
    paths: list[Path] = []
    for condition in conditions:
        condition_dir = run_dir / "producer_outputs" / condition.condition_id
        if not condition_dir.exists():
            continue
        aggregate = condition_dir / "predictions.aggregate.jsonl"
        rows: list[dict[str, Any]] = []
        for prediction_path in sorted(condition_dir.rglob("predictions.jsonl")):
            for row in read_jsonl(prediction_path):
                copied = dict(row)
                copied.setdefault("source_prediction_jsonl", str(prediction_path))
                copied.setdefault("system", condition.condition_id)
                copied.setdefault("execution_mode", "coding_agent")
                anchors = _layer_a_anchor_list(prediction_path.parent)
                if anchors and "br_screening_anchors" not in copied:
                    copied["br_screening_anchors"] = anchors
                    copied["br_screening_anchors_file"] = str(
                        prediction_path.parent / LAYER_A_BR_SCREENING_ANCHORS
                    )
                rows.append(copied)
        if rows:
            write_jsonl(rows, aggregate)
            paths.append(aggregate)
    return paths


def _input_candidate_pmids(case_input_dir: Path) -> list[str]:
    pmids: list[str] = []
    for row in read_jsonl(case_input_dir / "candidates.jsonl"):
        pmid = str(row.get("pmid") or row.get("study_pmid") or "").strip()
        if pmid:
            pmids.append(pmid)
    return pmids


def _anchor_candidate_pmid(anchor: dict[str, Any]) -> str:
    return str(
        anchor.get("candidate_pmid")
        or anchor.get("pmid")
        or anchor.get("study_pmid")
        or ""
    ).strip()


def _anchor_decision(anchor: dict[str, Any]) -> str:
    return str(anchor.get("decision") or "").strip().lower()


def _decision_rows_by_pmid(decision_rows: list[dict[str, Any]]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for row in decision_rows:
        pmid = str(row.get("pmid") or row.get("study_pmid") or "").strip()
        decision = str(row.get("decision") or "").strip().lower()
        if pmid and decision in {"include", "exclude", "uncertain"}:
            decisions[pmid] = decision
    return decisions


def _validate_layer_a_br_screening_anchors(
    *,
    anchor_path: Path,
    expected_pmids: set[str],
    decision_by_pmid: dict[str, str],
    required: bool,
) -> list[str]:
    if not anchor_path.exists():
        return ["missing_br_screening_anchors_json"] if required else []
    payload = read_json_or_none(anchor_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("anchors"), list):
        return ["invalid_br_screening_anchors_json"]
    anchors = [anchor for anchor in payload["anchors"] if isinstance(anchor, dict)]
    if required and not anchors:
        return ["empty_br_screening_anchors"]

    errors: list[str] = []
    consumed_count = 0
    consumed_inclusion_support_count = 0
    for index, anchor in enumerate(anchors):
        prefix = f"br_screening_anchor[{index}]"
        pmid = _anchor_candidate_pmid(anchor)
        decision = _anchor_decision(anchor)
        supports_inclusion = anchor.get("supports_inclusion")
        if not pmid:
            errors.append(f"{prefix}:missing_candidate_pmid")
        elif pmid not in expected_pmids:
            errors.append(f"{prefix}:candidate_outside_materialized_input")
        if decision not in {"include", "exclude", "uncertain"}:
            errors.append(f"{prefix}:invalid_decision")
        if not isinstance(supports_inclusion, bool):
            errors.append(f"{prefix}:missing_boolean_supports_inclusion")
        elif decision == "exclude" and supports_inclusion:
            errors.append(f"{prefix}:exclude_anchor_cannot_support_inclusion")
        elif decision in {"include", "uncertain"} and not supports_inclusion:
            errors.append(f"{prefix}:include_or_uncertain_anchor_must_support_inclusion")
        for field in ("eligibility_criterion", "evidence_source", "evidence_summary", "confidence"):
            if not str(anchor.get(field) or "").strip():
                errors.append(f"{prefix}:missing_{field}")
        if pmid and decision and decision_by_pmid.get(pmid) == decision:
            consumed_count += 1
            if supports_inclusion is True and decision in {"include", "uncertain"}:
                consumed_inclusion_support_count += 1
    if required and anchors and consumed_count == 0:
        errors.append("br_screening_anchors_not_consumed_by_decisions")
    if required and anchors and consumed_inclusion_support_count == 0:
        errors.append("missing_consumed_inclusion_supporting_br_screening_anchor")
    return errors


def validate_layer_a_outputs(
    *,
    run_dir: Path,
    cases: list[dict[str, Any]],
    conditions: list[Condition],
    require_br_effective_use: bool = False,
) -> dict[str, dict[str, Any]]:
    """Validate that producer rows screened exactly the materialized candidates."""

    validation: dict[str, dict[str, Any]] = {}
    expected_by_meta: dict[str, list[str]] = {}
    for case in cases:
        meta_pmid = str(case.get("meta_pmid") or "").strip()
        expected_by_meta[meta_pmid] = _input_candidate_pmids(
            run_dir / "case_inputs" / "layer_a" / f"layer_a_{meta_pmid}_mixed_pool"
        )

    for condition in conditions:
        condition_dir = run_dir / "producer_outputs" / condition.condition_id
        br_required = condition_br_required(
            condition,
            force_required=require_br_effective_use,
        )
        condition_errors: list[dict[str, Any]] = []
        case_status: dict[str, dict[str, Any]] = {}
        for meta_pmid, expected_pmids in expected_by_meta.items():
            expected_set = set(expected_pmids)
            case_dir = condition_dir / f"layer_a_{meta_pmid}_mixed_pool"
            prediction_path = case_dir / "predictions.jsonl"
            decisions_path = case_dir / "screening_decisions.jsonl"
            errors: list[str] = []

            prediction_rows = read_jsonl(prediction_path)
            if not prediction_rows:
                errors.append("missing_predictions_jsonl")
            else:
                prediction = prediction_rows[0]
                ranked_pmids = [
                    str(pmid).strip()
                    for pmid in prediction.get("ranked_pmids", [])
                    if str(pmid).strip()
                ]
                predicted_pmids = {
                    str(pmid).strip()
                    for pmid in prediction.get("predicted_pmids", [])
                    if str(pmid).strip()
                }
                if len(ranked_pmids) != len(expected_pmids):
                    errors.append(
                        "ranked_pmids_count_mismatch:"
                        f"expected={len(expected_pmids)} observed={len(ranked_pmids)}"
                    )
                if set(ranked_pmids) != expected_set:
                    missing = sorted(expected_set - set(ranked_pmids))
                    extra = sorted(set(ranked_pmids) - expected_set)
                    errors.append(
                        "ranked_pmids_set_mismatch:"
                        f"missing={len(missing)} extra={len(extra)}"
                    )
                if not predicted_pmids <= expected_set:
                    errors.append(
                        "predicted_pmids_outside_candidates:"
                        f"n={len(predicted_pmids - expected_set)}"
                    )

            decision_rows = read_jsonl(decisions_path)
            if not decision_rows:
                errors.append("missing_screening_decisions_jsonl")
            elif len(decision_rows) != len(expected_pmids):
                errors.append(
                    "screening_decisions_count_mismatch:"
                    f"expected={len(expected_pmids)} observed={len(decision_rows)}"
                )
            errors.extend(
                _validate_layer_a_br_screening_anchors(
                    anchor_path=case_dir / LAYER_A_BR_SCREENING_ANCHORS,
                    expected_pmids=expected_set,
                    decision_by_pmid=_decision_rows_by_pmid(decision_rows),
                    required=br_required,
                )
            )

            if errors:
                condition_errors.append({"meta_pmid": meta_pmid, "errors": errors})
            case_status[meta_pmid] = {
                "expected_n_candidates": len(expected_pmids),
                "valid": not errors,
                "errors": errors,
            }

        validation[condition.condition_id] = {
            "valid": not condition_errors,
            "cases": case_status,
            "errors": condition_errors,
        }
    return validation


def collect_layer_b_comparison_conditions(
    *,
    run_dir: Path,
    conditions: list[Condition],
    records: list[dict[str, Any]],
) -> list[LayerBConditionInput]:
    """Return condition artifact roots for uniform Layer B comparison."""

    comparison_conditions: list[LayerBConditionInput] = []
    if DEFAULT_LAYER_B_PURE_NIMARE_OUTPUT.exists():
        comparison_conditions.append(
            LayerBConditionInput(
                name="pure_nimare",
                path=DEFAULT_LAYER_B_PURE_NIMARE_OUTPUT,
            )
        )

    succeeded_condition_ids = {
        str(record.get("condition_id"))
        for record in records
        if record.get("status") == "succeeded"
    }
    for condition in conditions:
        if condition.condition_id not in succeeded_condition_ids:
            continue
        comparison_conditions.append(
            LayerBConditionInput(
                name=condition.condition_id,
                path=run_dir / "producer_outputs" / condition.condition_id,
            )
        )
    return comparison_conditions


def compare_layer_b_outputs(
    *,
    run_dir: Path,
    conditions: list[Condition],
    records: list[dict[str, Any]],
    normalize_artifacts: bool = False,
    trace_br_anchors: bool = False,
) -> Path | None:
    comparison_conditions = collect_layer_b_comparison_conditions(
        run_dir=run_dir,
        conditions=conditions,
        records=records,
    )
    if not comparison_conditions:
        return None
    evaluation_dir = run_dir / "evaluation"
    run_layer_b_comparison(
        comparison_conditions,
        evaluation_dir,
        normalize_artifacts=normalize_artifacts,
        trace_br_anchors=trace_br_anchors,
    )
    return evaluation_dir


def write_run_summary(
    *,
    run_dir: Path,
    layer: str,
    cases: list[dict[str, Any]],
    conditions: list[Condition],
    records: list[dict[str, Any]],
    evaluation_dir: Path | None,
    episode_scope: str,
    output_validation: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "run_dir": str(run_dir),
        "layer": layer,
        "created_at": utc_now(),
        "n_cases": len(cases),
        "meta_pmids": [case.get("meta_pmid") for case in cases],
        "n_conditions": len(conditions),
        "episode_scope": episode_scope,
        "condition_ids": [condition.condition_id for condition in conditions],
        "status_counts": status_counts,
        "evaluation_dir": str(evaluation_dir) if evaluation_dir else None,
        "output_validation": output_validation or {},
        "records": records,
    }
    write_json(run_dir / "RUN_SUMMARY.json", summary)
    return summary


def build_episodes(
    *,
    run_dir: Path,
    layer: str,
    base_prompt: str,
    cases: list[dict[str, Any]],
    input_dirs: dict[str, Path],
    conditions: list[Condition],
    max_candidates: int,
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
    codex_bin: str,
    claude_bin: str,
    opencode_bin: str,
    claude_br_mcp_config: Path,
    allow_opencode_with_br: bool,
    episode_scope: str,
    layer_b_soft_deadline_s: int | None = None,
    require_br_effective_use: bool = False,
) -> list[Episode]:
    episodes: list[Episode] = []
    if episode_scope not in {EPISODE_SCOPE_CASE, EPISODE_SCOPE_CONDITION}:
        raise ValueError(f"Unsupported episode_scope: {episode_scope}")
    for condition in conditions:
        condition_output_dir = run_dir / "producer_outputs" / condition.condition_id
        case_groups = (
            [[case] for case in cases]
            if episode_scope == EPISODE_SCOPE_CASE
            else [cases]
        )
        for case_group in case_groups:
            meta_pmids = tuple(str(case.get("meta_pmid") or "") for case in case_group)
            producer_output_dir = condition_output_dir
            if layer == "layer_b" and episode_scope == EPISODE_SCOPE_CASE:
                producer_output_dir = (
                    condition_output_dir / f"_episode_{layer}_{meta_pmids[0]}"
                )
            prompt = build_prompt(
                base_prompt=base_prompt,
                layer=layer,
                condition=condition,
                cases=case_group,
                input_dirs=input_dirs,
                producer_output_dir=producer_output_dir,
                max_candidates=max_candidates,
                mixed_pool_noise_ratio=mixed_pool_noise_ratio,
                mixed_pool_seed=mixed_pool_seed,
                layer_b_soft_deadline_s=layer_b_soft_deadline_s,
                require_br_effective_use=require_br_effective_use,
            )
            command, skip_reason = build_command(
                condition=condition,
                prompt=prompt,
                run_dir=run_dir,
                repo_root=REPO_ROOT,
                codex_bin=codex_bin,
                claude_bin=claude_bin,
                opencode_bin=opencode_bin,
                claude_br_mcp_config=claude_br_mcp_config,
                allow_opencode_with_br=allow_opencode_with_br,
            )
            episode_id = condition.condition_id
            if episode_scope == EPISODE_SCOPE_CASE:
                episode_id = f"{condition.condition_id}/{layer}_{meta_pmids[0]}"
            episodes.append(
                Episode(
                    condition=condition,
                    episode_dir=run_dir / "episodes" / episode_id,
                    producer_output_dir=producer_output_dir,
                    command=command,
                    prompt=prompt,
                    meta_pmids=meta_pmids,
                    status="skipped" if skip_reason else "materialized",
                    skip_reason=skip_reason,
                )
            )
    return episodes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=["layer_a", "layer_b"], default="layer_a")
    parser.add_argument("--conditions-file", type=Path, default=DEFAULT_CONDITIONS_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-name")
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--runner", action="append", default=[])
    parser.add_argument("--meta-pmid", action="append", default=[])
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--max-conditions", type=int)
    parser.add_argument("--max-candidates", type=int, default=150)
    parser.add_argument("--mixed-pool-noise-ratio", type=int, default=5)
    parser.add_argument("--mixed-pool-seed", type=int, default=0)
    parser.add_argument(
        "--episode-scope",
        choices=[EPISODE_SCOPE_CASE, EPISODE_SCOPE_CONDITION],
        default=EPISODE_SCOPE_CASE,
        help=(
            "Run one agent episode per case for fairer cross-model comparison, "
            "or one episode per condition for legacy multi-case prompts."
        ),
    )
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument(
        "--soft-deadline-s",
        type=int,
        default=None,
        help=(
            "Layer B prompt/env soft deadline. Agents should stop exploration "
            "and finalize artifacts before the hard timeout."
        ),
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum number of coding-agent episodes to run concurrently.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing terminal episode record.json files in the run directory.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPO_ROOT / ".env",
        help=(
            "Optional KEY=VALUE env file loaded before launching model CLIs; "
            "existing environment variables take precedence."
        ),
    )
    parser.add_argument("--claude-br-mcp-config", type=Path, default=REPO_ROOT / ".mcp.json")
    parser.add_argument(
        "--allow-opencode-with-br-without-mcp",
        action="store_true",
        help="Run OpenCode with_br rows even if `opencode mcp list` reports no configured MCP server.",
    )
    parser.add_argument(
        "--layer-b-harness-finalizer",
        action="store_true",
        help=(
            "After each Layer B episode, have the harness inject required "
            "provenance fields, write a missing report template, run preflight, "
            "and trace BR anchors."
        ),
    )
    parser.add_argument(
        "--require-br-effective-use",
        action="store_true",
        help=(
            "For with-BR rows, require a consumed BR anchor. Layer A checks "
            "br_screening_anchors.json; Layer B checks reconciliation anchors "
            "and can mark failed gates as failed_br_required_gate."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.execute and args.dry_run:
        print("Use either --execute or --dry-run, not both.", file=sys.stderr)
        return 2
    dry_run = not args.execute
    run_name = args.run_name or f"{args.layer}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = args.output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    base_prompt_path = DEFAULT_LAYER_A_PROMPT if args.layer == "layer_a" else DEFAULT_LAYER_B_PROMPT
    base_prompt = base_prompt_path.read_text(encoding="utf-8")
    conditions = filter_conditions(
        load_conditions(args.conditions_file),
        layer=args.layer,
        condition_ids={str(value) for value in args.condition},
        runners={str(value) for value in args.runner},
        max_conditions=args.max_conditions,
    )
    cases = select_cases(
        cases_path=args.cases,
        layer=args.layer,
        meta_pmids={str(value) for value in args.meta_pmid},
        limit_cases=args.limit_cases,
    )
    if not conditions:
        print("No matching conditions.", file=sys.stderr)
        return 2
    if not cases:
        print("No matching cases.", file=sys.stderr)
        return 2

    if args.layer == "layer_a":
        input_dirs = materialize_layer_a_inputs(
            run_dir=run_dir,
            cases=cases,
            data_dir=args.data_dir,
            max_candidates=args.max_candidates,
            mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
            mixed_pool_seed=args.mixed_pool_seed,
        )
    else:
        input_dirs = materialize_layer_b_inputs(run_dir=run_dir, cases=cases)

    episodes = build_episodes(
        run_dir=run_dir,
        layer=args.layer,
        base_prompt=base_prompt,
        cases=cases,
        input_dirs=input_dirs,
        conditions=conditions,
        max_candidates=args.max_candidates,
        mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
        mixed_pool_seed=args.mixed_pool_seed,
        codex_bin=args.codex_bin,
        claude_bin=args.claude_bin,
        opencode_bin=args.opencode_bin,
        claude_br_mcp_config=args.claude_br_mcp_config,
        allow_opencode_with_br=args.allow_opencode_with_br_without_mcp,
        episode_scope=args.episode_scope,
        layer_b_soft_deadline_s=args.soft_deadline_s,
        require_br_effective_use=args.require_br_effective_use,
    )

    records = run_episodes(
        episodes=episodes,
        timeout_s=args.timeout_s,
        dry_run=dry_run,
        max_workers=args.max_workers,
        resume=args.resume,
        records_path=run_dir / "episode_records.jsonl",
        layer=args.layer,
        run_dir=run_dir,
        enable_layer_b_finalizer=args.layer_b_harness_finalizer,
        require_br_effective_use=args.require_br_effective_use,
        layer_b_soft_deadline_s=args.soft_deadline_s,
    )

    evaluation_dir: Path | None = None
    output_validation: dict[str, dict[str, Any]] = {}
    if args.layer == "layer_a" and not dry_run:
        output_validation = validate_layer_a_outputs(
            run_dir=run_dir,
            cases=cases,
            conditions=conditions,
            require_br_effective_use=args.require_br_effective_use,
        )
        write_json(run_dir / "output_validation.json", output_validation)
        valid_condition_ids: set[str] = set()
        for record in records:
            if record.get("status") != "succeeded":
                continue
            validation = output_validation.get(str(record.get("condition_id"))) or {}
            record["output_validation"] = validation
            if validation.get("valid"):
                valid_condition_ids.add(str(record.get("condition_id")))
            else:
                record["status"] = "failed_output_validation"
        prediction_paths = collect_layer_a_predictions(
            run_dir,
            [
                condition
                for condition in conditions
                if condition.condition_id in valid_condition_ids
            ],
        )
        if prediction_paths:
            evaluation_dir = run_dir / "evaluation"
            evaluate_prediction_files(args.cases, prediction_paths, evaluation_dir)
    elif args.layer == "layer_b" and not dry_run:
        evaluation_dir = compare_layer_b_outputs(
            run_dir=run_dir,
            conditions=conditions,
            records=records,
            normalize_artifacts=args.layer_b_harness_finalizer,
            trace_br_anchors=args.layer_b_harness_finalizer,
        )

    summary = write_run_summary(
        run_dir=run_dir,
        layer=args.layer,
        cases=cases,
        conditions=conditions,
        records=records,
        evaluation_dir=evaluation_dir,
        episode_scope=args.episode_scope,
        output_validation=output_validation,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
