#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.mcp.run_gallant_feasibility_audit import HttpMCPClient, LocalMCPClient
except ModuleNotFoundError:  # pragma: no cover - runtime fallback
    _audit_path = Path(__file__).resolve().parents[1] / "mcp" / "run_gallant_feasibility_audit.py"
    _spec = importlib.util.spec_from_file_location("run_gallant_feasibility_audit", _audit_path)
    if _spec is None or _spec.loader is None:
        raise RuntimeError(f"Cannot load MCP client helpers from {_audit_path}")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _mod
    _spec.loader.exec_module(_mod)
    HttpMCPClient = _mod.HttpMCPClient
    LocalMCPClient = _mod.LocalMCPClient


ALLOWED_NODE_TYPES = {
    "Task",
    "Concept",
    "Construct",
    "Contrast",
    "TaskCondition",
    "Condition",
    "OntologyConcept",
    "OnvocClass",
}
ALLOWED_RELATIONS = {
    "CONTRAST_OF",
    "HAS_CONTRAST",
    "USES_CONDITION",
    "MEASURES",
    "ASSERTS",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_items(resp: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(resp, dict):
        return []
    for key in ("items", "neighbors", "results", "nodes"):
        raw = resp.get(key)
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
    data = resp.get("data")
    if isinstance(data, dict):
        for key in ("items", "neighbors", "results", "nodes"):
            raw = data.get(key)
            if isinstance(raw, list):
                return [r for r in raw if isinstance(r, dict)]
    return []


def extract_node_id(node: dict[str, Any]) -> str:
    for key in ("kg_id", "id", "node_id", "neighbor_kg_id", "target_kg_id"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def extract_node_label(node: dict[str, Any]) -> str:
    for key in ("label", "name", "node_label"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def extract_node_type(node: dict[str, Any]) -> str:
    for key in ("node_type", "type", "label_type"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def extract_relation(node: dict[str, Any]) -> str:
    for key in ("relation", "relation_type", "predicate", "edge_type"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def extract_nested_onvoc_ids(payload: Any, out: set[str]) -> None:
    if isinstance(payload, dict):
        for k, v in payload.items():
            lk = str(k).lower()
            if lk in {"onvoc_id", "onvoc_primary_id"} and isinstance(v, str):
                vv = v.strip()
                if vv.startswith("ONVOC_"):
                    out.add(vv)
            elif lk in {"onvoc_ids", "standardized_onvoc_ids"} and isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        xx = x.strip()
                        if xx.startswith("ONVOC_"):
                            out.add(xx)
            extract_nested_onvoc_ids(v, out)
    elif isinstance(payload, list):
        for x in payload:
            extract_nested_onvoc_ids(x, out)


def is_unresolved_item(item: dict[str, Any] | None) -> bool:
    if not isinstance(item, dict):
        return True
    quality = item.get("quality")
    if isinstance(quality, dict):
        n_features = int(quality.get("n_features") or 0)
        task_resolved = bool(quality.get("task_resolved", False))
        if (not task_resolved) or n_features <= 0:
            return True

    n_kg = len(item.get("kg_feature_ids") or [])
    n_onvoc = len(item.get("onvoc_ids") or [])
    return (n_kg + n_onvoc) <= 0


def create_client(args: argparse.Namespace):
    if args.transport == "local":
        return LocalMCPClient()
    token = args.mcp_token or os.getenv("BR_MCP_TOKEN")
    return HttpMCPClient(url=args.mcp_url, token=token, timeout_s=float(args.timeout_seconds))


def resolve_combo(
    client,
    *,
    task_raw: str,
    canonical_task: str,
    contrast: str,
) -> dict[str, Any]:
    evidence: list[str] = []
    kg_ids: set[str] = set()
    onvoc_ids: set[str] = set()

    task_node_id = ""
    task_node_label = ""
    contrast_node_id = ""

    task_queries = [
        f"task:{task_raw}",
        canonical_task,
        canonical_task.replace(" task", ""),
        task_raw,
    ]
    for q in task_queries:
        resp = client.call("kg_search_nodes", {"query": q, "limit": 8, "node_types": "Task"})
        items = parse_items(resp)
        evidence.append(f"kg_search_nodes(task) q='{q}' n={len(items)} ok={bool(resp.get('ok', False))}")
        if task_node_id:
            continue
        for it in items:
            node_id = extract_node_id(it)
            node_type = extract_node_type(it)
            if not node_id:
                continue
            if node_type and "task" not in node_type.lower():
                continue
            task_node_id = node_id
            task_node_label = extract_node_label(it)
            kg_ids.add(node_id)
            break

    if task_node_id:
        resp = client.call("kg_neighbors", {"kg_id": task_node_id, "limit": 64})
        neigh = parse_items(resp)
        evidence.append(f"kg_neighbors(task={task_node_id}) n={len(neigh)} ok={bool(resp.get('ok', False))}")
        for nn in neigh:
            relation = extract_relation(nn)
            node_id = extract_node_id(nn)
            node_type = extract_node_type(nn)
            if not node_id:
                continue
            if relation and relation not in ALLOWED_RELATIONS:
                continue
            if node_type and node_type not in ALLOWED_NODE_TYPES:
                continue
            kg_ids.add(node_id)

    contrast_resp = client.call(
        "kg_search_nodes",
        {"query": contrast, "limit": 8, "node_types": "Contrast"},
    )
    contrast_items = parse_items(contrast_resp)
    evidence.append(
        f"kg_search_nodes(contrast='{contrast}') n={len(contrast_items)} ok={bool(contrast_resp.get('ok', False))}"
    )
    for it in contrast_items:
        node_id = extract_node_id(it)
        node_type = extract_node_type(it)
        if not node_id:
            continue
        if node_type and "contrast" not in node_type.lower():
            continue
        contrast_node_id = node_id
        kg_ids.add(node_id)
        break

    if contrast_node_id:
        resp = client.call("kg_neighbors", {"kg_id": contrast_node_id, "limit": 64})
        neigh = parse_items(resp)
        evidence.append(
            f"kg_neighbors(contrast={contrast_node_id}) n={len(neigh)} ok={bool(resp.get('ok', False))}"
        )
        for nn in neigh:
            relation = extract_relation(nn)
            node_id = extract_node_id(nn)
            node_type = extract_node_type(nn)
            if not node_id:
                continue
            if relation and relation not in ALLOWED_RELATIONS:
                continue
            if node_type and node_type not in ALLOWED_NODE_TYPES:
                continue
            kg_ids.add(node_id)

    qa_resp = client.call(
        "kg_multihop_qa",
        {
            "question": f"Find contrast and construct links for task '{canonical_task}' and contrast '{contrast}'.",
            "max_hops": 2,
            "max_results": 30,
        },
    )
    evidence.append(f"kg_multihop_qa ok={bool(qa_resp.get('ok', False))}")
    qa_items = parse_items(qa_resp)
    for it in qa_items:
        node_id = extract_node_id(it)
        node_type = extract_node_type(it)
        if node_id and ((not node_type) or node_type in ALLOWED_NODE_TYPES):
            kg_ids.add(node_id)
    extract_nested_onvoc_ids(qa_resp, onvoc_ids)

    map_resp = client.call(
        "task_to_concept_mapping",
        {"task_name": canonical_task, "include_synonyms": True},
    )
    evidence.append(f"task_to_concept_mapping ok={bool(map_resp.get('ok', False))}")
    extract_nested_onvoc_ids(map_resp, onvoc_ids)

    kg_feature_ids = sorted(x for x in kg_ids if isinstance(x, str) and x.strip())
    onvoc_ids_sorted = sorted(x for x in onvoc_ids if isinstance(x, str) and x.startswith("ONVOC_"))

    return {
        "task_raw": task_raw,
        "canonical_task": canonical_task,
        "contrast": contrast,
        "task_node_id": task_node_id,
        "task_node_label": task_node_label,
        "kg_feature_ids": kg_feature_ids,
        "onvoc_ids": onvoc_ids_sorted,
        "evidence": evidence,
        "quality": {
            "task_resolved": bool(task_node_id),
            "contrast_resolved": bool(contrast_node_id),
            "n_features": int(len(kg_feature_ids) + len(onvoc_ids_sorted)),
        },
    }


def collect_target_combos(
    fev2_script: Path,
    root: Path,
    max_per_task: int,
    max_samples: int,
) -> list[dict[str, str]]:
    fe = load_module(fev2_script, "fev2_for_refresh")
    all_maps = fe.list_stat_maps(root)
    selected = fe.select_maps(all_maps, max_per_task, max_samples)
    combo_df = (
        selected[["task_raw", "canonical_task", "contrast"]]
        .drop_duplicates()
        .sort_values(["canonical_task", "task_raw", "contrast"])
        .reset_index(drop=True)
    )
    return combo_df.to_dict(orient="records")


def item_key(task_raw: str, contrast: str) -> tuple[str, str]:
    return (str(task_raw).strip(), str(contrast).strip())


def summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    n_items = len(items)
    n_task_resolved = 0
    n_contrast_resolved = 0
    n_with_features = 0
    for it in items:
        q = it.get("quality") if isinstance(it, dict) else {}
        if isinstance(q, dict):
            if bool(q.get("task_resolved", False)):
                n_task_resolved += 1
            if bool(q.get("contrast_resolved", False)):
                n_contrast_resolved += 1
            if int(q.get("n_features") or 0) > 0:
                n_with_features += 1

    return {
        "n_items": int(n_items),
        "task_resolution_rate": float(n_task_resolved / n_items) if n_items else 0.0,
        "contrast_resolution_rate": float(n_contrast_resolved / n_items) if n_items else 0.0,
        "feature_nonempty_rate": float(n_with_features / n_items) if n_items else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh unresolved rows in KG feature map.")
    parser.add_argument(
        "--fev2-script",
        type=Path,
        default=Path("scripts/analysis/run_forward_encoding_v2.py"),
    )
    parser.add_argument("--root", type=Path, default=Path("data/openneuro_glmfitlins/stat_maps"))
    parser.add_argument("--max-samples", type=int, default=900)
    parser.add_argument("--max-per-task", type=int, default=80)
    parser.add_argument(
        "--kg-feature-map-in",
        type=Path,
        default=Path("outputs/forward_encoding_v2/kg_feature_map.json"),
    )
    parser.add_argument(
        "--kg-feature-map-out",
        type=Path,
        default=Path("outputs/forward_encoding_v2/kg_feature_map.refreshed.json"),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("outputs/forward_encoding_v2/kg_refresh_report.json"),
    )
    parser.add_argument("--transport", choices=["local", "http"], default="local")
    parser.add_argument(
        "--mcp-url",
        type=str,
        default=os.getenv("BR_MCP_URL", "http://127.0.0.1:7000/mcp"),
    )
    parser.add_argument("--mcp-token", type=str, default=os.getenv("BR_MCP_TOKEN", ""))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=0, help="Max unresolved combos to refresh; 0 means all.")
    args = parser.parse_args()

    in_payload = json.loads(args.kg_feature_map_in.read_text(encoding="utf-8"))
    in_items = in_payload.get("items") if isinstance(in_payload, dict) else None
    if not isinstance(in_items, list):
        raise RuntimeError(f"Invalid kg map input: {args.kg_feature_map_in}")

    target_combos = collect_target_combos(
        args.fev2_script,
        args.root,
        max_per_task=args.max_per_task,
        max_samples=args.max_samples,
    )

    existing_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for it in in_items:
        if not isinstance(it, dict):
            continue
        key = item_key(it.get("task_raw", ""), it.get("contrast", ""))
        if key[0] and key[1]:
            existing_by_key[key] = it

    unresolved_keys: list[tuple[str, str]] = []
    total_targets = 0
    for row in target_combos:
        key = item_key(row.get("task_raw", ""), row.get("contrast", ""))
        if not key[0] or not key[1]:
            continue
        total_targets += 1
        old = existing_by_key.get(key)
        if is_unresolved_item(old):
            unresolved_keys.append(key)

    if args.limit > 0:
        unresolved_keys = unresolved_keys[: args.limit]

    client = create_client(args)

    updated_count = 0
    failed_count = 0
    errors: list[dict[str, Any]] = []

    canonical_by_key = {
        item_key(r["task_raw"], r["contrast"]): str(r.get("canonical_task", ""))
        for r in target_combos
    }

    for key in unresolved_keys:
        task_raw, contrast = key
        canonical_task = canonical_by_key.get(key, "")
        try:
            refreshed = resolve_combo(
                client,
                task_raw=task_raw,
                canonical_task=canonical_task,
                contrast=contrast,
            )
            existing_by_key[key] = refreshed
            updated_count += 1
        except Exception as exc:  # pragma: no cover - defensive
            failed_count += 1
            errors.append(
                {
                    "task_raw": task_raw,
                    "contrast": contrast,
                    "error": str(exc),
                }
            )

    out_items: list[dict[str, Any]] = []
    for row in target_combos:
        key = item_key(row.get("task_raw", ""), row.get("contrast", ""))
        if not key[0] or not key[1]:
            continue
        item = existing_by_key.get(key)
        if isinstance(item, dict):
            out_items.append(item)
        else:
            out_items.append(
                {
                    "task_raw": row.get("task_raw", ""),
                    "canonical_task": row.get("canonical_task", ""),
                    "contrast": row.get("contrast", ""),
                    "task_node_id": "",
                    "task_node_label": "",
                    "kg_feature_ids": [],
                    "onvoc_ids": [],
                    "evidence": ["missing_after_refresh"],
                    "quality": {
                        "task_resolved": False,
                        "contrast_resolved": False,
                        "n_features": 0,
                    },
                }
            )

    summary = summarize_items(out_items)

    out_payload = {
        "metadata": {
            "created_at": utc_now_iso(),
            "source": "refresh_kg_feature_map_unresolved.py",
            "n_items": int(summary["n_items"]),
            "n_tasks": int(len({str(x.get("canonical_task", "")) for x in out_items})),
            "task_resolution_rate": float(summary["task_resolution_rate"]),
            "contrast_resolution_rate": float(summary["contrast_resolution_rate"]),
            "source_tools": [
                "kg_search_nodes",
                "kg_neighbors",
                "kg_multihop_qa",
                "task_to_concept_mapping",
            ],
            "allowed_node_types": sorted(ALLOWED_NODE_TYPES),
        },
        "items": out_items,
    }
    args.kg_feature_map_out.parent.mkdir(parents=True, exist_ok=True)
    args.kg_feature_map_out.write_text(
        json.dumps(out_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    still_unresolved = sum(1 for it in out_items if is_unresolved_item(it))
    report = {
        "generated_at": utc_now_iso(),
        "input_map": str(args.kg_feature_map_in),
        "output_map": str(args.kg_feature_map_out),
        "total_targets": int(total_targets),
        "unresolved_before": int(len(unresolved_keys)),
        "updated_count": int(updated_count),
        "failed_count": int(failed_count),
        "still_unresolved": int(still_unresolved),
        "errors": errors,
        "summary": summary,
    }
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "output_map": str(args.kg_feature_map_out),
                "report": str(args.report_out),
                "report_summary": {
                    "total_targets": report["total_targets"],
                    "updated_count": report["updated_count"],
                    "still_unresolved": report["still_unresolved"],
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
