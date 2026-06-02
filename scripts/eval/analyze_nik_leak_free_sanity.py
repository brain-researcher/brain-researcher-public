#!/usr/bin/env python3
"""Compact analyzer for the NIK leak-free sanity rerun.

Compares without_br vs +BR episodes on structural-only signals (no LLM judge
calls). Supports both:
  - direct episode dirs named task__model__mode
  - real-trace dirs under episodes/<condition_id>/<task_id>

Computes:
  - JSON validity rate when last_message.txt is present
  - evidence_basis row count and basis_type distribution when present
  - structurally grounded rate for evidence_basis rows whose basis_type is
    grounded and whose reference matches a DOI/PMID/doc:/kg: pattern
  - live MCP/action usage from parsed_actions.jsonl and record.json

Diagnostic intent: if with_br Δ on structural grounding is large positive AND model
actually called BR MCP at runtime → real signal. If +BR doesn't call MCP at all or
the structural rate doesn't move → BR is not adding value in the live (non-leaked)
condition.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

GROUNDED_BASIS_TYPES = {"specific_citation", "retrieved_document", "kg_fact", "session_memory"}
DOI_RE = re.compile(r"^(?:doi:)?10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
PMID_RE = re.compile(r"^(?:pmid:)?\d{6,9}$", re.IGNORECASE)
DOC_RE = re.compile(r"^(?:doc|document):[A-Za-z0-9_.:/?=&%+#@~,-]{4,}$", re.IGNORECASE)
KG_RE = re.compile(r"^(?:kg|kg_node|node)[:_/.-][A-Za-z0-9_.:/-]{2,}$", re.IGNORECASE)
MCP_ACTION_TYPES = {"mcp_tool", "recipe_tool"}
MODE_SUFFIX_RE = re.compile(r"^(?P<model>.+)_(?P<mode>with_br(?:_mcp)?|without_br)$")


def iter_episode_dirs(run_dir: Path) -> list[Path]:
    episodes_root = run_dir / "episodes"
    if episodes_root.exists():
        return sorted(
            p.parent
            for p in episodes_root.glob("*/*/record.json")
            if p.parent.is_dir()
        )
    return sorted(p for p in run_dir.iterdir() if p.is_dir() and "__" in p.name)


def parse_last_message(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def is_structural_reference(ref: Any) -> bool:
    if not isinstance(ref, str):
        return False
    return any(p.match(ref) for p in (DOI_RE, PMID_RE, DOC_RE, KG_RE))


def infer_episode_identity(ep_dir: Path, record: dict[str, Any]) -> dict[str, str]:
    name = ep_dir.name
    parts = name.split("__")

    task_from_name = parts[0] if parts else name
    model_from_name = "?"
    mode_from_name: str | None = None

    if len(parts) >= 3:
        model_from_name = parts[1] or "?"
        mode_from_name = "__".join(parts[2:]) or None
    elif len(parts) == 2:
        match = MODE_SUFFIX_RE.match(parts[1])
        if match:
            model_from_name = match.group("model")
            mode_from_name = match.group("mode")
        else:
            model_from_name = parts[1] or "?"

    condition_id = str(record.get("condition_id") or mode_from_name or ep_dir.parent.name)
    task_id = str(record.get("task_id") or task_from_name)
    model_id = str(record.get("model") or record.get("model_id") or model_from_name)
    mode = str(
        record.get("br_mode")
        or record.get("mode")
        or mode_from_name
        or ("with_br_mcp" if "with_br" in condition_id else "without_br")
    )
    mode = normalize_mode(mode, condition_id)
    return {
        "condition_id": condition_id,
        "task_id": task_id,
        "model_id": model_id,
        "mode": mode,
    }


def normalize_mode(raw_mode: str, condition_id: str = "") -> str:
    mode = str(raw_mode or "").strip()
    condition = str(condition_id or "").strip()
    for candidate in (mode, condition):
        normalized = candidate.strip("_")
        if not normalized:
            continue
        if normalized.endswith("__without_br") or normalized.endswith("_without_br"):
            return "without_br"
        if normalized == "without_br":
            return "without_br"
        if "__with_br" in normalized:
            return normalized.split("__", 1)[1]
        if normalized.endswith("_with_br_mcp") or normalized.endswith("_with_br"):
            return normalized[normalized.rfind("with_br") :]
        with_br_idx = normalized.find("with_br")
        if with_br_idx >= 0:
            return normalized[with_br_idx:]
        if normalized.startswith("with_br"):
            return normalized
    return mode or ("with_br_mcp" if "with_br" in condition else "without_br")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def actions_from_events(path: Path) -> list[dict[str, Any]]:
    by_call_id: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(read_jsonl(path)):
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = str(item.get("type") or event.get("type") or "")
        if item_type != "mcp_tool_call":
            continue
        call_id = str(item.get("id") or event.get("id") or f"event_{index}")
        event_type = str(event.get("type") or "")
        action = {
            "action_type": "mcp_tool",
            "source": f"codex.{event_type or 'event'}.mcp_tool_call",
            "target": item.get("tool") or item.get("name") or "",
            "server": item.get("server"),
            "status": item.get("status"),
            "raw": event,
        }
        # Prefer completed events over started events for one action per call.
        previous = by_call_id.get(call_id)
        if previous is None or event_type == "item.completed":
            by_call_id[call_id] = action
    return list(by_call_id.values())


def returncode_is_zero(value: Any) -> bool:
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def normalize_record_status(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status:
        return str(status)
    if "returncode" in record:
        return "succeeded" if returncode_is_zero(record.get("returncode")) else "failed"
    return "missing_record"


def analyze_episode(ep_dir: Path) -> dict[str, Any]:
    rec_path = ep_dir / "record.json"
    record = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    status = normalize_record_status(record)

    identity = infer_episode_identity(ep_dir, record)
    condition_id = identity["condition_id"]
    task_id = identity["task_id"]
    model_id = identity["model_id"]
    mode = identity["mode"]

    last_msg_path = ep_dir / "last_message.txt"
    payload = parse_last_message(last_msg_path.read_text()) if last_msg_path.exists() else None

    eb = payload.get("evidence_basis") if isinstance(payload, dict) else None
    if not isinstance(eb, list):
        eb = []

    basis_counts: dict[str, int] = defaultdict(int)
    grounded_rows = 0
    grounded_struct_ok = 0
    for row in eb:
        if not isinstance(row, dict):
            continue
        bt = row.get("basis_type") or "missing"
        basis_counts[str(bt)] += 1
        if bt in GROUNDED_BASIS_TYPES:
            grounded_rows += 1
            if is_structural_reference(row.get("reference")):
                grounded_struct_ok += 1

    actions = read_jsonl(ep_dir / "parsed_actions.jsonl")
    if not actions:
        actions = actions_from_events(ep_dir / "events.jsonl")
    mcp_actions = [
        action
        for action in actions
        if str(action.get("action_type") or "") in MCP_ACTION_TYPES
        or str(action.get("source") or "").startswith("mcp_")
    ]
    concrete_actions = [
        action
        for action in actions
        if str(action.get("target") or "").strip()
        and str(action.get("action_type") or "") not in {"neutral", "none"}
    ]
    ti = record.get("tool_indicators") if isinstance(record.get("tool_indicators"), dict) else {}

    return {
        "task_id": task_id,
        "model_id": model_id,
        "condition_id": condition_id,
        "mode": mode,
        "status": status,
        "succeeded": status == "succeeded",
        "json_error": bool(record.get("json_error_event")),
        "valid_json": payload is not None,
        "last_message_present": last_msg_path.exists(),
        "eb_rows": len(eb),
        "basis_counts": dict(basis_counts),
        "grounded_rows": grounded_rows,
        "structurally_ok": grounded_struct_ok,
        "structural_grounded_rate": grounded_struct_ok / max(len(eb), 1) if eb else 0.0,
        "action_count": len(actions),
        "mcp_action_count": len(mcp_actions),
        "concrete_action_count": len(concrete_actions),
        "mentions_br": bool(ti.get("mentions_brain_researcher")) or mode != "without_br",
        "mentions_mcp": bool(ti.get("mentions_mcp")) or bool(mcp_actions),
        "mentions_tool_call": bool(ti.get("mentions_tool_call")) or bool(actions),
        "elapsed_s": record.get("elapsed_s") or record.get("wall_time_s"),
        "returncode": record.get("returncode"),
    }


def summarize(rows: list[dict[str, Any]], mode_filter: str | None = None) -> dict[str, float]:
    if mode_filter:
        rows = [r for r in rows if r["mode"] == mode_filter]
    n = len(rows) or 1
    return {
        "n": len(rows),
        "success_rate": sum(r["succeeded"] for r in rows) / n,
        "json_error_rate": sum(r["json_error"] for r in rows) / n,
        "valid_json_rate": sum(r["valid_json"] for r in rows) / n,
        "mean_eb_rows": sum(r["eb_rows"] for r in rows) / n,
        "mean_grounded_rows": sum(r["grounded_rows"] for r in rows) / n,
        "mean_structurally_ok": sum(r["structurally_ok"] for r in rows) / n,
        "mean_struct_grounded_rate": sum(r["structural_grounded_rate"] for r in rows) / n,
        "mean_action_count": sum(r["action_count"] for r in rows) / n,
        "mean_mcp_action_count": sum(r["mcp_action_count"] for r in rows) / n,
        "mean_concrete_action_count": sum(r["concrete_action_count"] for r in rows) / n,
        "mentions_mcp_rate": sum(r["mentions_mcp"] for r in rows) / n,
        "mentions_br_rate": sum(r["mentions_br"] for r in rows) / n,
        "mentions_tool_call_rate": sum(r["mentions_tool_call"] for r in rows) / n,
    }


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: analyze_nik_leak_free_sanity.py <run_dir>")
    run_dir = Path(sys.argv[1])
    rows = [analyze_episode(p) for p in iter_episode_dirs(run_dir)]
    print(f"# Episodes parsed: {len(rows)}\n")

    print("## Per-episode")
    print(
        f"{'condition':<32} {'task':<10} {'model':<14} {'mode':<12} "
        f"{'status':<10} {'json':>5} {'eb':>3} {'act':>3} {'mcp':>4} "
        f"{'route':>5}"
    )
    for r in rows:
        print(
            f"{r['condition_id']:<32} {r['task_id']:<10} "
            f"{r['model_id']:<14} {r['mode']:<12} "
            f"{r['status']:<10} {'Y' if r['valid_json'] else 'N':>5} "
            f"{r['eb_rows']:>3} {r['action_count']:>3} "
            f"{r['mcp_action_count']:>4} {r['concrete_action_count']:>5}"
        )

    print("\n## Aggregated by mode")
    for mode in sorted({r["mode"] for r in rows}):
        s = summarize(rows, mode)
        print(f"\n[{mode}] n={s['n']}")
        for k, v in s.items():
            if k == "n":
                continue
            print(f"  {k:<28} {v:.3f}")

    modes = sorted({r["mode"] for r in rows})
    if len(modes) == 2 and "without_br" in modes:
        without = summarize(rows, "without_br")
        other = [m for m in modes if m != "without_br"][0]
        with_ = summarize(rows, other)
        print(f"\n## Δ (with={other} − without_br)")
        for k in without:
            if k == "n":
                continue
            d = with_[k] - without[k]
            print(f"  {k:<28} Δ={d:+.3f}   ({without[k]:.3f} → {with_[k]:.3f})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0) from None
