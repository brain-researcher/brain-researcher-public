#!/usr/bin/env python3
"""Build demo run bundles (v2) from demo index + existing artifacts.

This script does not execute pipelines. It materializes a normalized bundle per demo
entry so `/demos` can render prompt / replay / evidence / artifacts with explicit
semantic boundaries.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None


@dataclass
class DemoBuildSummary:
    total: int = 0
    built: int = 0
    skipped: int = 0
    strict_failures: int = 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def collect_manuscript_artifacts_by_slug(
    manuscript_map: Dict[str, Any],
) -> Dict[str, List[str]]:
    figures = manuscript_map.get("figures")
    if not isinstance(figures, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for _, fig_value in figures.items():
        if not isinstance(fig_value, dict):
            continue
        demos = fig_value.get("demos")
        if not isinstance(demos, list):
            continue
        for demo in demos:
            if not isinstance(demo, dict):
                continue
            slug = str(demo.get("slug", "")).strip()
            if not slug:
                continue
            artifacts = demo.get("primary_artifacts")
            if not isinstance(artifacts, list):
                continue
            for artifact in artifacts:
                value = str(artifact).strip()
                if value:
                    out.setdefault(slug, []).append(value)
    return out


def collect_candidate_artifacts(results_root: Path) -> List[Path]:
    if not results_root.exists():
        return []
    patterns = ("*.yaml", "*.yml", "*.json", "*.csv", "*.png", "*.jpg", "*.jpeg", "*.md", "*.pdf")
    files: List[Path] = []
    for pat in patterns:
        files.extend(results_root.rglob(pat))
    return sorted(set(files))


def find_matching_artifacts(
    all_artifacts: List[Path],
    *,
    source_run_ids: List[str],
    slug: str,
) -> List[str]:
    keys = [k.strip() for k in source_run_ids if k and k.strip()]
    keys.append(slug.replace("-", "_"))
    matched: List[str] = []
    for path in all_artifacts:
        hay = str(path).lower()
        if any(key.lower() in hay for key in keys):
            matched.append(str(path))
    return matched


def filter_existing_paths(paths: List[str]) -> List[str]:
    existing: List[str] = []
    for raw in paths:
        value = raw.strip()
        if not value:
            continue
        candidate = Path(value) if Path(value).is_absolute() else Path.cwd() / value
        if candidate.exists():
            existing.append(value)
    return existing


def dedupe_preserve_order(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in values:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def infer_mime_type(path_value: str) -> str:
    lower = path_value.lower()
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".yaml") or lower.endswith(".yml"):
        return "application/yaml"
    if lower.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if lower.endswith(".csv"):
        return "text/csv; charset=utf-8"
    if lower.endswith(".txt"):
        return "text/plain; charset=utf-8"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def infer_artifact_roles(path_value: str) -> List[str]:
    lower = path_value.lower()
    roles: List[str] = []
    if "/cases/" in lower:
        roles.append("prompt_source")
    if "/runbooks/" in lower:
        roles.append("runbook")
    if "/reports/" in lower:
        roles.append("reference_summary_source")
        roles.append("evidence")
    if "executive_summary" in lower:
        roles.append("reference_summary_source")
    if "/results/" in lower:
        roles.append("evidence")
    if lower.endswith(".png") or lower.endswith(".svg") or lower.endswith(".jpg") or lower.endswith(".jpeg"):
        roles.append("figure")
    if not roles:
        roles.append("artifact")
    # preserve order
    out: List[str] = []
    seen = set()
    for role in roles:
        if role not in seen:
            seen.add(role)
            out.append(role)
    return out


def infer_stage(path_value: str) -> Optional[str]:
    lower = path_value.lower()
    if "/reports/" in lower and lower.endswith(".pdf"):
        return "R5"
    match = re.search(r"(?:^|[_/\-])r([0-5])(?:[_\-.]|$)", lower)
    if not match:
        return None
    return f"R{match.group(1)}"


def read_text(path_value: str) -> str:
    path_obj = Path(path_value) if Path(path_value).is_absolute() else Path.cwd() / path_value
    try:
        return path_obj.read_text(encoding="utf-8")
    except Exception:
        return ""


def normalize_prompt_text(value: str) -> str:
    trimmed = value.strip()
    if len(trimmed) >= 2 and ((trimmed[0] == '"' and trimmed[-1] == '"') or (trimmed[0] == "'" and trimmed[-1] == "'")):
        return trimmed[1:-1].strip()
    return trimmed


def extract_fenced_blocks(text: str) -> List[str]:
    out: List[str] = []
    for match in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```", text):
        block = match.group(1).strip()
        if block:
            out.append(block)
    return out


def extract_section(text: str, heading_pattern: str) -> str:
    pattern = re.compile(rf"##\s*{heading_pattern}[\s\S]*?(?=\n##\s+|$)", re.IGNORECASE)
    match = pattern.search(text)
    return match.group(0).strip() if match else ""


def extract_heading_block(text: str, heading_keyword_pattern: str) -> str:
    pattern = re.compile(
        rf"^#+\s*[^\n]*{heading_keyword_pattern}[^\n]*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    start = match.start()
    next_heading = re.search(r"^#+\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def extract_user_query(raw_markdown: str) -> str:
    step0 = extract_section(raw_markdown, r"Step\s*0[^\n]*User Query[^\n]*") or extract_section(
        raw_markdown, r"User Query[^\n]*"
    )
    step_blocks = extract_fenced_blocks(step0) if step0 else []
    if step_blocks:
        return normalize_prompt_text(step_blocks[0])
    task_statement = extract_section(raw_markdown, r"Task Statement[^\n]*")
    if task_statement:
        blocks = extract_fenced_blocks(task_statement)
        if blocks:
            return normalize_prompt_text(blocks[0])
        for line in task_statement.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                return normalize_prompt_text(clean)
    m = re.search(
        r'"(?:user_query|research_question|claim_statement|claim_text)"\s*:\s*"([^"]+)"',
        raw_markdown,
        re.IGNORECASE,
    )
    if m:
        return normalize_prompt_text(m.group(1))
    return ""


def extract_primary_prompt_from_markdown(path_value: str) -> str:
    raw = read_text(path_value)
    if not raw:
        return ""
    step0 = extract_section(raw, r"Step\s*0[^\n]*")
    step_blocks = extract_fenced_blocks(step0) if step0 else []
    primary_base = normalize_prompt_text(step_blocks[0]) if step_blocks else normalize_prompt_text(
        extract_fenced_blocks(raw)[0] if extract_fenced_blocks(raw) else ""
    )
    user_query = extract_user_query(raw)
    if user_query and primary_base and user_query.lower() not in primary_base.lower():
        return f"User Query: {user_query}\n\nTask Prompt:\n{primary_base}"
    return user_query or primary_base


def extract_structured_highlights(path_value: str) -> List[str]:
    lower = path_value.lower()
    if not (lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".json")):
        return []
    raw = read_text(path_value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if lower.endswith(".json") else (yaml.safe_load(raw) if yaml else {})
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    out: List[str] = []
    r2 = parsed.get("r2_output")
    if isinstance(r2, dict):
        dominant = r2.get("dominant_driver_discovered")
        if isinstance(dominant, dict):
            axis = str(dominant.get("axis", "")).strip()
            contrib = dominant.get("contribution")
            if axis:
                if contrib is not None:
                    out.append(f"Dominant driver: {axis} ({contrib})")
                else:
                    out.append(f"Dominant driver: {axis}")
        risk = r2.get("default_pipeline_risk")
        if isinstance(risk, dict):
            statement = str(risk.get("risk_statement", "")).strip()
            if statement:
                out.append(statement)
    r4 = parsed.get("r4_output")
    if isinstance(r4, dict):
        key_results = r4.get("key_results")
        if isinstance(key_results, list):
            for item in key_results[:2]:
                if isinstance(item, dict):
                    finding = str(item.get("finding", "")).strip()
                    if finding:
                        out.append(finding)
    deduped: List[str] = []
    seen = set()
    for item in out:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def extract_bottom_line_summary(markdown: str) -> str:
    section = extract_section(markdown, r"Bottom Line")
    if not section:
        return ""
    for line in section.splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            return clean
    return ""


def extract_key_findings_summary(markdown: str) -> str:
    section = extract_section(markdown, r"Key Findings")
    if not section:
        return ""
    return section_lines(section, max_lines=3)


def extract_first_readable_paragraph(markdown: str) -> str:
    for line in markdown.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("#") or clean.startswith("```") or clean.startswith("- "):
            continue
        if re.match(r"^\d+\.\s", clean):
            continue
        if len(clean) >= 20:
            return clean
    return ""


def is_generic_summary_text(text: str) -> bool:
    lower = text.strip().lower()
    generic_markers = [
        "this cycle successfully upgraded the pipeline",
        "operational” to “auditable and defensible",
    ]
    return any(marker in lower for marker in generic_markers)


def token_set(value: str) -> set:
    return set(re.findall(r"[a-zA-Z]{3,}", value.lower()))


def lexical_overlap(lhs: str, rhs: str) -> float:
    left = token_set(lhs)
    right = token_set(rhs)
    if not left:
        return 0.0
    return len(left.intersection(right)) / float(len(left))


def summary_from_structured_obj(obj: Dict[str, Any]) -> str:
    snippets: List[str] = []

    r5 = obj.get("r5_output")
    if isinstance(r5, dict):
        aggregate = r5.get("aggregate_conclusion")
        if isinstance(aggregate, dict):
            key_message = str(aggregate.get("key_message", "")).strip()
            if key_message:
                snippets.append(key_message)

    r4 = obj.get("r4_output")
    if isinstance(r4, dict):
        key_results = r4.get("key_results")
        if isinstance(key_results, list):
            for item in key_results[:2]:
                if isinstance(item, dict):
                    finding = str(item.get("finding", "")).strip()
                    if finding:
                        snippets.append(finding)

    r3 = obj.get("r3_design_spec")
    if isinstance(r3, dict):
        rec = r3.get("recommendation")
        if isinstance(rec, dict):
            selected = str(rec.get("selected_path", "")).strip()
            rationale = str(rec.get("rationale", "")).strip()
            if selected:
                snippets.append(f"Selected design path: {selected}")
            if rationale:
                snippets.append(rationale)

    r2 = obj.get("r2_output")
    if isinstance(r2, dict):
        dominant = r2.get("dominant_driver_discovered")
        if isinstance(dominant, dict):
            axis = str(dominant.get("axis", "")).strip()
            contribution = dominant.get("contribution")
            if axis:
                snippets.append(
                    f"Dominant driver: {axis}"
                    + (f" (contribution={contribution})" if contribution is not None else "")
                )
        risk = r2.get("default_pipeline_risk")
        if isinstance(risk, dict):
            statement = str(risk.get("risk_statement", "")).strip()
            if statement:
                snippets.append(statement)

    if "qc_r2_runs" in obj and isinstance(obj.get("qc_r2_runs"), dict):
        qc_count = len(obj.get("qc_r2_runs"))
        snippets.append(f"QC sweep runs indexed: {qc_count}")

    return compact_lines(snippets, max_lines=3)


def build_artifacts(matched_paths: List[str]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for idx, path_value in enumerate(matched_paths):
        artifacts.append(
            {
                "id": f"a{idx + 1:03d}",
                "path": path_value,
                "mime_type": infer_mime_type(path_value),
                "roles": infer_artifact_roles(path_value),
                "stage": infer_stage(path_value),
                "title": Path(path_value).name,
            }
        )
    return artifacts


def artifact_by_role(artifacts: List[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    return [a for a in artifacts if role in (a.get("roles") or [])]


def document_ids_for_reference_output(artifacts: List[Dict[str, Any]]) -> List[str]:
    def score(artifact: Dict[str, Any]) -> Tuple[int, str]:
        roles = artifact.get("roles") or []
        path_value = str(artifact.get("path", "")).lower()
        if "figure" in roles:
            return (0, path_value)
        if path_value.endswith(".csv"):
            return (1, path_value)
        if "reference_summary_source" in roles:
            return (2, path_value)
        if path_value.endswith(".md"):
            return (3, path_value)
        return (4, path_value)

    candidates = [
        a
        for a in artifacts
        if "evidence" in (a.get("roles") or [])
        or "reference_summary_source" in (a.get("roles") or [])
        or "figure" in (a.get("roles") or [])
    ]
    ordered = sorted(candidates, key=score)
    return [a["id"] for a in ordered[:8]]


def build_prompt_pack(
    demo: Dict[str, Any], artifacts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    prompt_sources = artifact_by_role(artifacts, "prompt_source")
    source_id = prompt_sources[0]["id"] if prompt_sources else None
    primary = str(demo.get("primary_prompt") or "").strip()
    if prompt_sources:
        primary = primary or extract_primary_prompt_from_markdown(prompt_sources[0]["path"])
    if not primary:
        primary = str(demo.get("description") or demo.get("title") or "").strip()

    coding_prompt = str(demo.get("coding_prompt") or "").strip()
    mcp_prompt = str(demo.get("mcp_prompt") or "").strip()
    return {
        "primary_prompt": primary,
        "source_artifact_id": source_id,
        "followup_prompts": [],
        "coding_agent_prompts": [coding_prompt] if coding_prompt else [],
        "mcp_prompts": [mcp_prompt] if mcp_prompt else [],
    }


def build_reference_output(
    demo: Dict[str, Any], artifacts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    summary = ""
    summary_kind = "synthetic"
    source_id = None

    highlights: List[str] = []
    for artifact in artifacts:
        for item in extract_structured_highlights(artifact["path"]):
            if item not in highlights:
                highlights.append(item)
            if len(highlights) >= 6:
                break
        if len(highlights) >= 6:
            break

    if not highlights:
        for artifact in artifacts:
            path_value = str(artifact.get("path", "")).lower()
            roles = artifact.get("roles") or []
            if not path_value.endswith(".pdf") or "reference_summary_source" not in roles:
                continue
            title = str(artifact.get("title") or "").strip()
            if title:
                highlights.append(title)
                break

    def summary_artifact_score(artifact: Dict[str, Any]) -> Tuple[int, str]:
        path_value = str(artifact.get("path", "")).lower()
        score = 50
        if path_value.endswith(".yaml") or path_value.endswith(".yml") or path_value.endswith(".json"):
            if "r5_" in path_value:
                score = 0
            elif "r4_" in path_value:
                score = 1
            elif "r3_" in path_value:
                score = 2
            elif "r2_" in path_value and "run_index" not in path_value:
                score = 3
            elif "run_index" in path_value:
                score = 18
            else:
                score = 8
        elif path_value.endswith(".md"):
            if "executive_summary" in path_value:
                score = 10
            else:
                score = 12
        elif path_value.endswith(".csv"):
            score = 20
        return score, path_value

    sorted_artifacts = sorted(artifacts, key=summary_artifact_score)
    for artifact in sorted_artifacts:
        path_value = str(artifact.get("path", "")).strip()
        lower = path_value.lower()
        candidate = ""
        if lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".json"):
            obj = parse_structured_file(path_value)
            if obj:
                candidate = summary_from_structured_obj(obj)
        elif lower.endswith(".md"):
            markdown = read_text(path_value)
            if markdown:
                candidate = (
                    extract_key_findings_summary(markdown)
                    or extract_bottom_line_summary(markdown)
                    or extract_first_readable_paragraph(markdown)
                )
        if candidate:
            summary = candidate
            source_id = artifact.get("id")
            summary_kind = "answer"
            break

    if (not summary or is_generic_summary_text(summary)) and highlights:
        summary = highlights[0]
        summary_kind = "answer"

    if not summary:
        summary = str(demo.get("description") or demo.get("title") or "Recorded replay bundle.").strip()
        summary_kind = "synthetic"

    return {
        "summary": summary,
        "summary_kind": summary_kind,
        "source_artifact_id": source_id,
        "document_ids": document_ids_for_reference_output(artifacts),
        "highlights": highlights,
        "generated_at": None,
        "dataset_version": None,
    }


def stage_title(stage: str) -> str:
    mapping = {
        "R0": "Frame Query",
        "R1": "Evidence Retrieval",
        "R2": "Conflict Mapping",
        "R3": "Design Recommendation",
        "R4": "Execution",
        "R5": "RunCard / Export",
    }
    return mapping.get(stage.upper(), stage)


def clip_text(text: str, max_chars: int = 1800) -> str:
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def compact_lines(lines: List[str], max_lines: int = 4, max_line_chars: int = 260) -> str:
    out: List[str] = []
    seen = set()
    for item in lines:
        clean = re.sub(r"\s+", " ", item.strip())
        if not clean:
            continue
        clean = clip_text(clean, max_line_chars)
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= max_lines:
            break
    return "\n".join(out)


def parse_structured_file(path_value: str) -> Dict[str, Any]:
    lower = path_value.lower()
    if not (lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".json")):
        return {}
    raw = read_text(path_value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if lower.endswith(".json") else (yaml.safe_load(raw) if yaml else {})
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def section_lines(section: str, max_lines: int = 4) -> str:
    lines: List[str] = []
    for line in section.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("#") or clean.startswith("```"):
            continue
        if clean.startswith("- "):
            lines.append(clean[2:].strip())
            continue
        if re.match(r"^\d+\.\s", clean):
            lines.append(re.sub(r"^\d+\.\s*", "", clean))
            continue
        if len(clean) >= 24:
            lines.append(clean)
    return compact_lines(lines, max_lines=max_lines)


def stage_response_from_markdown(stage: str, path_value: str) -> str:
    raw = read_text(path_value)
    if not raw:
        return ""
    stage_key = stage.upper()
    section_map = {
        "R1": [r"What Was Executed", r"Scope and Objective"],
        "R2": [r"Key Findings"],
        "R3": [r"Defensibility Decision"],
        "R4": [r"Recommended Immediate Next Actions", r"Deliverables"],
        "R5": [r"Integrated vs Isolated", r"Bottom Line"],
    }
    for heading in section_map.get(stage_key, []):
        section = extract_section(raw, heading)
        if not section:
            continue
        condensed = section_lines(section, max_lines=4)
        if condensed:
            return condensed
    return ""


def stage_response_from_structured(stage: str, obj: Dict[str, Any]) -> str:
    stage_key = stage.upper()
    lines: List[str] = []

    r2 = obj.get("r2_output")
    if isinstance(r2, dict) and stage_key in {"R1", "R2"}:
        r2_primary: List[str] = []
        r2_support: List[str] = []

        dominant = r2.get("dominant_driver_discovered")
        if isinstance(dominant, dict):
            axis = str(dominant.get("axis", "")).strip()
            contrib = dominant.get("contribution")
            if axis:
                r2_primary.append(
                    f"Dominant driver: {axis}"
                    + (f" (contribution={contrib})" if contrib is not None else "")
                )

        risk = r2.get("default_pipeline_risk")
        if isinstance(risk, dict):
            statement = str(risk.get("risk_statement", "")).strip()
            if statement:
                r2_primary.append(statement)

        sens = r2.get("sensitivity_attribution")
        if isinstance(sens, dict):
            by_axis = sens.get("by_axis")
            if isinstance(by_axis, list):
                top_axes: List[str] = []
                for item in by_axis:
                    if isinstance(item, dict):
                        axis = str(item.get("axis", "")).strip()
                        contribution = item.get("contribution")
                        if axis:
                            top_axes.append(
                                f"{axis}={contribution}" if contribution is not None else axis
                            )
                if top_axes:
                    r2_primary.append("Sensitivity top axes: " + ", ".join(top_axes[:3]))

        readiness = r2.get("dataset_readiness")
        if isinstance(readiness, dict):
            ready_pairs = []
            for ds_name, ds_meta in readiness.items():
                if isinstance(ds_meta, dict):
                    status = str(ds_meta.get("analysis_subset_status", "")).strip()
                    if status:
                        ready_pairs.append(f"{ds_name}: {status}")
            if ready_pairs:
                r2_support.append("Dataset readiness -> " + "; ".join(ready_pairs[:3]))

        if stage_key == "R2":
            lines.extend(r2_primary + r2_support)
        else:
            lines.extend(r2_support + r2_primary)

    r3 = obj.get("r3_design_spec")
    if isinstance(r3, dict) and stage_key in {"R3", "R4"}:
        rec = r3.get("recommendation")
        if isinstance(rec, dict):
            selected = str(rec.get("selected_path", "")).strip()
            rationale = str(rec.get("rationale", "")).strip()
            if selected:
                lines.append(f"Selected design path: {selected}")
            if rationale:
                lines.append(f"Rationale: {rationale}")

        path_a = r3.get("path_a_hardened_glm") or r3.get("path_a_hardened_method_demo")
        if isinstance(path_a, dict):
            reqs = path_a.get("mandatory_requirements")
            if isinstance(reqs, list):
                req_lines = [str(item).strip() for item in reqs if str(item).strip()]
                if req_lines:
                    lines.append("Mandatory requirements: " + "; ".join(req_lines[:2]))

    r4 = obj.get("r4_output")
    if isinstance(r4, dict) and stage_key in {"R4", "R5"}:
        status = str(r4.get("status", "")).strip()
        if status:
            lines.append(f"Run card status: {status}")
        qc_gate = r4.get("qc_gate")
        if isinstance(qc_gate, dict):
            gate_status = str(qc_gate.get("gate_status", "")).strip()
            scan = qc_gate.get("scan_scope")
            clean_count = exclude_count = None
            if isinstance(scan, dict):
                clean_count = scan.get("clean_files")
                exclude_count = scan.get("excluded_files")
            if gate_status:
                gate_line = f"QC gate: {gate_status}"
                if clean_count is not None and exclude_count is not None:
                    gate_line += f" (clean={clean_count}, excluded={exclude_count})"
                lines.append(gate_line)
        key_results = r4.get("key_results")
        if isinstance(key_results, list):
            for item in key_results[:2]:
                if isinstance(item, dict):
                    finding = str(item.get("finding", "")).strip()
                    if finding:
                        lines.append(finding)

    r5 = obj.get("r5_output")
    if isinstance(r5, dict) and stage_key == "R5":
        aggregate = r5.get("aggregate_conclusion")
        if isinstance(aggregate, dict):
            key_message = str(aggregate.get("key_message", "")).strip()
            if key_message:
                lines.append(key_message)
            changed = aggregate.get("integration_changes_conclusions")
            improved = aggregate.get("integration_improves_defensibility")
            if changed is not None or improved is not None:
                lines.append(
                    "Integration impact: "
                    f"changes_conclusions={changed}, improves_defensibility={improved}"
                )
        scenario_results = r5.get("scenario_results")
        if isinstance(scenario_results, list) and scenario_results:
            first = scenario_results[0]
            if isinstance(first, dict):
                integrated = str(first.get("integrated_summary", "")).strip()
                isolated = str(first.get("isolated_summary", "")).strip()
                if integrated:
                    lines.append(f"Integrated: {integrated}")
                if isolated:
                    lines.append(f"Isolated: {isolated}")

    if stage_key in {"R1", "R2"} and "qc_r2_runs" in obj:
        qc_runs = obj.get("qc_r2_runs")
        pre_qc = obj.get("pre_qc_fragility_runs")
        if isinstance(qc_runs, dict):
            lines.append(f"QC sweep runs indexed: {len(qc_runs)}")
        if isinstance(pre_qc, dict):
            lines.append(f"Pre-QC fragility probes indexed: {len(pre_qc)}")

    return compact_lines(lines, max_lines=4)


def stage_response_from_csv(stage: str, path_value: str) -> str:
    if stage.upper() not in {"R1", "R2", "R4"}:
        return ""
    raw = read_text(path_value)
    if not raw:
        return ""
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) <= 1:
        return ""
    header = [cell.strip() for cell in lines[0].split(",")[:6]]
    row_count = max(0, len(lines) - 1)
    name = Path(path_value).name
    return compact_lines(
        [
            f"{name}: {row_count} rows",
            "Columns: " + ", ".join([cell for cell in header if cell]),
        ],
        max_lines=2,
    )


def stage_response_from_prompt_source(stage: str, path_value: str) -> str:
    raw = read_text(path_value)
    if not raw:
        return ""

    # For strict step-style prompt files, extract_case_stage_overrides handles this.
    # This helper targets template/narrative prompt contracts.
    stage_key = stage.upper()
    heading_patterns = {
        "R1": [
            r"Conflict Mapping",
            r"Single-Run Conflict Map",
            r"Phase 1",
            r"Step 1",
            r"Contrast Parsing",
        ],
        "R2": [
            r"Robustness Audit",
            r"Phase 2",
            r"Step 2",
            r"Multiverse",
            r"Results Collection",
            r"Batch Evaluation Prompt",
        ],
        "R3": [
            r"Design Recommendation",
            r"Phase 3",
            r"Sensitivity",
            r"Model Training",
            r"Step 3",
            r"Condition-Dimension Schema",
            r"Evidence Card Extraction",
        ],
        "R4": [
            r"Execution",
            r"MCP Call Sequence",
            r"Practical Execution Workflow",
            r"End-to-End",
            r"Step 4",
        ],
        "R5": [
            r"Loop Closure",
            r"Visualization",
            r"Output Structure",
            r"Figure",
            r"Step 5",
        ],
    }
    for pattern in heading_patterns.get(stage_key, []):
        block = extract_heading_block(raw, pattern)
        if not block:
            continue
        condensed = section_lines(block, max_lines=4)
        if condensed:
            return condensed
    return ""


def infer_stage_artifact_refs(
    *,
    stage: str,
    artifacts: List[Dict[str, Any]],
    artifact_by_stage: Dict[str, List[str]],
    fallback_ids: List[str],
) -> List[str]:
    stage_key = stage.upper()
    refs = artifact_by_stage.get(stage_key, [])
    if refs:
        return refs[:]

    candidates: List[str] = []
    for artifact in artifacts:
        aid = str(artifact.get("id", "")).strip()
        path_value = str(artifact.get("path", "")).lower()
        roles = artifact.get("roles") or []
        if not aid:
            continue
        if stage_key in {"R1", "R2"}:
            if "run_index" in path_value or "r2_" in path_value or path_value.endswith(".csv"):
                candidates.append(aid)
        elif stage_key == "R3":
            if "r3_" in path_value or "design" in path_value or "reference_summary_source" in roles:
                candidates.append(aid)
        elif stage_key == "R4":
            if "r4_" in path_value or "run_card" in path_value or "runcard" in path_value:
                candidates.append(aid)
        elif stage_key == "R5":
            if "r5_" in path_value or "loop_closure" in path_value:
                candidates.append(aid)

    if candidates:
        return dedupe_preserve_order(candidates)[:6]
    return fallback_ids[:]


def extract_case_stage_overrides(path_value: str) -> Dict[str, Dict[str, str]]:
    raw = read_text(path_value)
    if not raw:
        return {}

    sections = list(re.finditer(r"^##\s*Step[^\n]*$", raw, re.MULTILINE))
    if not sections:
        return {}

    stage_map: Dict[str, Dict[str, str]] = {}
    for idx, match in enumerate(sections):
        start = match.start()
        end = sections[idx + 1].start() if idx + 1 < len(sections) else len(raw)
        section = raw[start:end]
        header = match.group(0)

        stage = ""
        m_stage = re.search(r"\(R([0-5])\)", header, re.IGNORECASE)
        if m_stage:
            stage = f"R{m_stage.group(1)}"
        if not stage:
            m_step = re.search(r"Step\s*(\d+)", header, re.IGNORECASE)
            if m_step:
                num = int(m_step.group(1))
                fallback_map = {0: "R0", 1: "R0", 2: "R1", 3: "R2", 4: "R3", 5: "R4", 6: "R5"}
                stage = fallback_map.get(num, "")
        if not stage:
            continue

        prompt_text = ""
        prompt_heading = re.search(r"###\s*[^\n]*Prompt[^\n]*", section, re.IGNORECASE)
        if prompt_heading:
            prompt_tail = section[prompt_heading.end() :]
            prompt_blocks = extract_fenced_blocks(prompt_tail)
            if prompt_blocks:
                prompt_text = normalize_prompt_text(prompt_blocks[0])

        response_text = ""
        response_heading = re.search(
            r"###\s*[^\n]*(Example|Output|Handoff|Constraint|Decision)[^\n]*",
            section,
            re.IGNORECASE,
        )
        if response_heading:
            response_tail = section[response_heading.end() :]
            response_blocks = extract_fenced_blocks(response_tail)
            if response_blocks:
                response_text = normalize_prompt_text(response_blocks[0])

        if not response_text:
            blocks = [normalize_prompt_text(b) for b in extract_fenced_blocks(section)]
            if blocks:
                candidates = [b for b in blocks if b and b != prompt_text]
                if candidates:
                    response_text = candidates[0]

        if not response_text:
            response_text = extract_first_readable_paragraph(section)

        if prompt_text or response_text:
            stage_map[stage] = {
                "prompt": clip_text(prompt_text, 2400) if prompt_text else "",
                "response": clip_text(response_text, 2400) if response_text else "",
            }

    return stage_map


def stage_response_from_artifact(stage: str, artifact: Dict[str, Any]) -> str:
    path_value = str(artifact.get("path", "")).strip()
    if not path_value:
        return ""
    lower = path_value.lower()

    if lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".json"):
        structured = parse_structured_file(path_value)
        if structured:
            return stage_response_from_structured(stage, structured)
        return ""

    if lower.endswith(".md"):
        return stage_response_from_markdown(stage, path_value)

    if lower.endswith(".csv"):
        return stage_response_from_csv(stage, path_value)

    if lower.endswith(".pdf"):
        title = str(artifact.get("title") or Path(path_value).name).strip()
        return f"Curated PDF report available: {title}"

    return ""


def derive_stage_response(
    *,
    stage: str,
    artifacts: List[Dict[str, Any]],
    artifact_by_stage: Dict[str, List[str]],
    reference_output: Dict[str, Any],
) -> str:
    refs = artifact_by_stage.get(stage, [])
    artifact_map = {str(a.get("id")): a for a in artifacts}
    candidates: List[Dict[str, Any]] = [artifact_map[r] for r in refs if r in artifact_map]

    ref_set = set(refs)
    for artifact in artifacts:
        aid = str(artifact.get("id", "")).strip()
        if aid in ref_set:
            continue
        roles = artifact.get("roles") or []
        if "evidence" in roles or "reference_summary_source" in roles:
            candidates.append(artifact)

    def stage_artifact_score(stage_key: str, artifact: Dict[str, Any]) -> Tuple[int, str]:
        path_value = str(artifact.get("path", "")).lower()
        score = 50
        if stage_key == "R1":
            if "run_index" in path_value:
                score = 0
            elif "r2_" in path_value and ("robustness" in path_value or path_value.endswith(".yaml")):
                score = 1
            elif path_value.endswith(".csv"):
                score = 2
            elif "executive_summary" in path_value:
                score = 3
        elif stage_key == "R2":
            if "r2_" in path_value and ("robustness" in path_value or path_value.endswith(".yaml")):
                score = 0
            elif "executive_summary" in path_value:
                score = 1
            elif "run_index" in path_value:
                score = 2
            elif path_value.endswith(".csv"):
                score = 3
        elif stage_key == "R3":
            if "r3_" in path_value:
                score = 0
            elif "executive_summary" in path_value:
                score = 1
            elif "r2_" in path_value:
                score = 2
        elif stage_key == "R4":
            if "r4_" in path_value:
                score = 0
            elif "executive_summary" in path_value:
                score = 1
            elif "r3_" in path_value:
                score = 2
        elif stage_key == "R5":
            if "r5_" in path_value:
                score = 0
            elif "executive_summary" in path_value:
                score = 1
            elif "r4_" in path_value:
                score = 2
        return score, path_value

    candidates = sorted(candidates, key=lambda artifact: stage_artifact_score(stage.upper(), artifact))

    snippets: List[str] = []
    snippet_seen = set()
    substantial_count = 0
    for artifact in candidates:
        snippet = stage_response_from_artifact(stage, artifact)
        if snippet:
            normalized = re.sub(r"\s+", " ", snippet.strip())
            if normalized and normalized not in snippet_seen:
                snippet_seen.add(normalized)
                snippets.append(snippet)
                if len(normalized) >= 140:
                    substantial_count += 1
        if substantial_count >= 2:
            break
        if len(snippets) >= 3:
            break

    if snippets:
        return clip_text("\n\n".join(snippets), 2600)

    if stage.upper() in {"R2", "R3", "R4", "R5"}:
        highlights = reference_output.get("highlights")
        if isinstance(highlights, list):
            hl = [str(item).strip() for item in highlights if str(item).strip()]
            if hl:
                return compact_lines(hl, max_lines=3)

    if stage.upper() == "R5" and reference_output.get("summary_kind") != "query":
        summary = str(reference_output.get("summary", "")).strip()
        if summary:
            return clip_text(summary, 900)

    return ""


def build_replay(
    demo: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
    prompt_pack: Dict[str, Any],
    reference_output: Dict[str, Any],
) -> Dict[str, Any]:
    stage_tags = demo.get("stage_tags")
    if not isinstance(stage_tags, list) or not stage_tags:
        stage_tags = ["R0", "R2", "R4"]
    normalized_stage_tags = []
    for item in stage_tags:
        raw = str(item).strip().upper()
        if re.match(r"^R[0-5]$", raw):
            normalized_stage_tags.append(raw)
    if not normalized_stage_tags:
        normalized_stage_tags = ["R0", "R2", "R4"]

    artifact_by_stage: Dict[str, List[str]] = {}
    for artifact in artifacts:
        stage = artifact.get("stage")
        if stage:
            artifact_by_stage.setdefault(stage, []).append(artifact["id"])

    case_stage_overrides: Dict[str, Dict[str, str]] = {}
    prompt_sources = artifact_by_role(artifacts, "prompt_source")
    if prompt_sources:
        case_stage_overrides = extract_case_stage_overrides(prompt_sources[0]["path"])
    prompt_source_path = prompt_sources[0]["path"] if prompt_sources else ""
    demo_is_template = bool(demo.get("is_template", False))

    evidence_ids = [a["id"] for a in artifacts if "evidence" in (a.get("roles") or [])]
    steps: List[Dict[str, Any]] = []
    for idx, stage in enumerate(normalized_stage_tags):
        is_first = idx == 0
        refs = artifact_by_stage.get(stage, [])
        if not refs and stage.upper() in {"R4", "R5"}:
            refs = evidence_ids[:]

        stage_override = case_stage_overrides.get(stage, {})
        stage_prompt = str(stage_override.get("prompt", "")).strip()
        derived_response = derive_stage_response(
            stage=stage,
            artifacts=artifacts,
            artifact_by_stage=artifact_by_stage,
            reference_output=reference_output,
        )
        override_response = str(stage_override.get("response", "")).strip()

        stage_response = ""
        if override_response and len(override_response) >= 80:
            stage_response = override_response
        elif derived_response:
            stage_response = derived_response
        elif override_response:
            stage_response = override_response

        prompt_source_response = (
            stage_response_from_prompt_source(stage, prompt_source_path) if prompt_source_path else ""
        )
        if prompt_source_response:
            if demo_is_template:
                stage_response = prompt_source_response
            elif not stage_response:
                stage_response = prompt_source_response
            else:
                anchor_text = " ".join(
                    [
                        str(prompt_pack.get("primary_prompt") or "").strip(),
                        " ".join([str(v).strip() for v in (prompt_pack.get("mcp_prompts") or [])]),
                        str(demo.get("description") or "").strip(),
                    ]
                ).strip()
                current_overlap = lexical_overlap(anchor_text, stage_response)
                prompt_overlap = lexical_overlap(anchor_text, prompt_source_response)
                generic_fragility_markers = [
                    "events_strategy",
                    "file_integrity",
                    "qc gate",
                    "corrupted",
                ]
                current_lower = stage_response.lower()
                is_generic_fragility = any(m in current_lower for m in generic_fragility_markers)
                if prompt_overlap >= max(0.06, current_overlap + 0.03) and (
                    is_generic_fragility or len(stage_response) < 120
                ):
                    stage_response = prompt_source_response

        prompt_text: Optional[str] = None
        if stage_prompt:
            prompt_text = stage_prompt
        elif is_first:
            prompt_text = str(prompt_pack.get("primary_prompt") or "").strip() or None

        response_text: Optional[str] = stage_response or None
        if response_text and len(response_text.strip()) >= 120 and not refs:
            refs = infer_stage_artifact_refs(
                stage=stage,
                artifacts=artifacts,
                artifact_by_stage=artifact_by_stage,
                fallback_ids=evidence_ids[:6],
            )
        response_origin = "bundle" if response_text else "none"
        steps.append(
            {
                "step_id": f"stage_{stage}_{idx + 1}",
                "stage": stage,
                "title": stage_title(stage),
                "status": "completed",
                "tool": None,
                "tool_calls": [],
                "prompt_text": prompt_text,
                "response_text": response_text,
                "prompt_origin": "bundle" if prompt_text else "none",
                "response_origin": response_origin,
                "artifact_ref_ids": refs,
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
            }
        )
    return {
        "source": "bundle_steps",
        "steps": steps,
    }


def realign_reference_summary(
    *,
    demo: Dict[str, Any],
    prompt_pack: Dict[str, Any],
    reference_output: Dict[str, Any],
    replay: Dict[str, Any],
) -> Dict[str, Any]:
    summary = str(reference_output.get("summary") or "").strip()
    prompt = str(prompt_pack.get("primary_prompt") or "").strip()
    demo_is_template = bool(demo.get("is_template", False))

    mismatch = False
    if not summary:
        mismatch = True
    elif demo_is_template and summary[:1] in {'"', "{", "["}:
        mismatch = True
    elif is_generic_summary_text(summary):
        mismatch = True
    elif prompt and lexical_overlap(prompt, summary) < 0.06:
        mismatch = True

    if not mismatch:
        return reference_output

    steps = replay.get("steps") if isinstance(replay, dict) else []
    if not isinstance(steps, list):
        return reference_output

    preferred_order = {"R2": 0, "R1": 1, "R3": 2, "R4": 3, "R5": 4}
    candidates: List[Tuple[int, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        stage = str(step.get("stage", "")).strip().upper()
        response = str(step.get("response_text", "")).strip()
        if not response:
            continue
        priority = preferred_order.get(stage, 9)
        candidates.append((priority, response))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        if demo_is_template:
            description = str(demo.get("description") or "").strip()
            if description:
                reference_output = dict(reference_output)
                reference_output["summary"] = description
                reference_output["summary_kind"] = "synthetic"
        return reference_output

    best = candidates[0][1]
    if demo_is_template and best.lstrip()[:1] in {'"', "{", "["}:
        description = str(demo.get("description") or "").strip()
        if description:
            reference_output = dict(reference_output)
            reference_output["summary"] = description
            reference_output["summary_kind"] = "synthetic"
            return reference_output
    reference_output = dict(reference_output)
    reference_output["summary"] = compact_lines(best.splitlines(), max_lines=3, max_line_chars=260)
    reference_output["summary_kind"] = "answer"
    return reference_output


def build_bundle(
    demo: Dict[str, Any],
    *,
    all_artifacts: List[Path],
    manual_artifacts: Dict[str, List[str]],
) -> Dict[str, Any]:
    slug = str(demo.get("slug", "")).strip()
    source_run_ids = demo.get("source_run_ids") or []
    if not isinstance(source_run_ids, list):
        source_run_ids = []
    source_run_ids = [str(run_id).strip() for run_id in source_run_ids if str(run_id).strip()]

    matched = find_matching_artifacts(
        all_artifacts,
        source_run_ids=source_run_ids,
        slug=slug,
    )
    extra = filter_existing_paths(manual_artifacts.get(slug, []))
    matched = dedupe_preserve_order(matched + extra)

    artifacts = build_artifacts(matched)
    if str(demo.get("demo_type") or "").strip() == "manuscript_case_report":
        report_title = str(demo.get("report_title") or demo.get("title") or "").strip()
        for artifact in artifacts:
            if str(artifact.get("path") or "").lower().endswith(".pdf"):
                artifact["stage"] = "R5"
                if report_title:
                    artifact["title"] = report_title
    prompt_pack = build_prompt_pack(demo, artifacts)
    reference_output = build_reference_output(demo, artifacts)
    replay = build_replay(demo, artifacts, prompt_pack, reference_output)
    reference_output = realign_reference_summary(
        demo=demo,
        prompt_pack=prompt_pack,
        reference_output=reference_output,
        replay=replay,
    )

    fallback_level = "none"
    fallback_reasons: List[str] = []
    if not source_run_ids and str(demo.get("demo_type") or "").strip() != "manuscript_case_report":
        fallback_level = "partial"
        fallback_reasons.append("source_run_ids_missing")
    replay_steps = replay.get("steps") if isinstance(replay, dict) else []
    if isinstance(replay_steps, list) and replay_steps:
        with_response = sum(
            1
            for step in replay_steps
            if isinstance(step, dict) and str(step.get("response_text") or "").strip()
        )
        if with_response == 0:
            fallback_level = "synthetic" if fallback_level == "none" else "partial"
            fallback_reasons.append("no_stage_responses_extracted")
        elif with_response < len(replay_steps):
            if fallback_level == "none":
                fallback_level = "partial"
            fallback_reasons.append("partial_stage_responses_extracted")

    return {
        "schema_version": "demo-run-bundle-v2",
        "generated_at": utc_now_iso(),
        "demo": {
            "slug": slug,
            "analysis_id": demo.get("analysis_id"),
            "title": demo.get("title"),
            "description": demo.get("description"),
            "tags": demo.get("tags") or [],
            "demo_type": demo.get("demo_type"),
            "stage_tags": demo.get("stage_tags") or [],
            "evidence_mode": demo.get("evidence_mode", "hybrid"),
            "log_mode": demo.get("log_mode", "redacted_full_trace"),
            "manuscript_figure": demo.get("manuscript_figure"),
            "canonical_name": demo.get("canonical_name"),
            "is_template": bool(demo.get("is_template", False)),
            "template_reason": demo.get("template_reason"),
        },
        "source_run_ids": source_run_ids,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "prompt_pack": prompt_pack,
        "reference_output": reference_output,
        "replay": replay,
        "fallback": {
            "level": fallback_level,
            "reasons": fallback_reasons,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build demo run bundles from existing artifacts.")
    parser.add_argument(
        "--demo-index",
        type=Path,
        default=Path("configs/demo/demo_index.json"),
        help="Path to demo index JSON",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("docs/use_cases/brain_researcher_hybrid/reports"),
        help="Root path containing report/demo artifacts",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("configs/demo/run_bundles"),
        help="Output directory for run_bundle.json files",
    )
    parser.add_argument(
        "--manuscript-map",
        type=Path,
        default=Path("configs/demo/manuscript_map.yaml"),
        help="Optional manuscript map with per-demo primary_artifacts",
    )
    parser.add_argument(
        "--strict-real-only",
        action="store_true",
        help="Fail if a demo with evidence_mode=real has no matched artifacts",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without creating files",
    )
    args = parser.parse_args()

    index = load_json(args.demo_index)
    demos = index.get("demos") or []
    if not isinstance(demos, list):
        raise SystemExit("Invalid demo index: demos must be a list")

    all_artifacts = collect_candidate_artifacts(args.results_root)
    manuscript_map = load_yaml(args.manuscript_map) if args.manuscript_map.exists() else {}
    manual_artifacts = collect_manuscript_artifacts_by_slug(manuscript_map)
    summary = DemoBuildSummary(total=len(demos))

    for raw_demo in demos:
        if not isinstance(raw_demo, dict):
            summary.skipped += 1
            continue
        slug = str(raw_demo.get("slug", "")).strip()
        if not slug:
            summary.skipped += 1
            continue

        bundle = build_bundle(
            raw_demo,
            all_artifacts=all_artifacts,
            manual_artifacts=manual_artifacts,
        )
        evidence_mode = str(bundle["demo"].get("evidence_mode", "hybrid"))
        artifact_count = int(bundle.get("artifact_count", 0))
        if args.strict_real_only and evidence_mode == "real" and artifact_count == 0:
            summary.strict_failures += 1

        out_dir = args.output_root / slug
        out_file = out_dir / "run_bundle.json"
        if args.dry_run:
            print(f"[dry-run] {slug}: artifacts={artifact_count} -> {out_file}", flush=True)
            summary.built += 1
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        summary.built += 1

    print(
        json.dumps(
            {
                "total": summary.total,
                "built": summary.built,
                "skipped": summary.skipped,
                "strict_failures": summary.strict_failures,
                "output_root": str(args.output_root),
                "results_root": str(args.results_root),
            },
            indent=2,
        )
    )

    if summary.strict_failures > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
