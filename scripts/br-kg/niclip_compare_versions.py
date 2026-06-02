from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client


def _load_edges(
    db,
    version: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    limit_clause = f"LIMIT {limit}" if limit else ""
    query = f"""
    MATCH (a)-[r:MAPS_TO {{source_load:'niclip', match_version:$version}}]->(b)
    RETURN
      a AS a, b AS b, properties(r) AS r_props
    {limit_clause}
    """
    rows = db.execute_query(query, {"version": version})
    edges: list[dict[str, Any]] = []
    for row in rows:
        a = row.get("a")
        b = row.get("b")
        r_props = row.get("r_props")
        if a is None or b is None or r_props is None:
            continue
        a_props = _props(a)
        b_props = _props(b)
        r_props = dict(r_props or {})
        edges.append(
            {
                "start_id": str(a_props.get("id") or a.element_id),
                "end_id": str(b_props.get("id") or b.element_id),
                "confidence": r_props.get("confidence"),
                "method": r_props.get("method"),
                "profile": r_props.get("match_profile"),
                "source_label": _label(a_props),
                "target_label": _label(b_props),
            }
        )
    return edges


def _props(entity: Any) -> dict[str, Any]:
    if entity is None:
        return {}
    if hasattr(entity, "items"):
        return dict(entity.items())
    try:
        return dict(entity)
    except Exception:
        return dict(getattr(entity, "_properties", {}) or {})


def _label(props: dict[str, Any]) -> str:
    return (
        props.get("name")
        or props.get("label")
        or props.get("title")
        or props.get("task_name")
        or props.get("concept_name")
        or ""
    )


def _edge_key(edge: dict[str, Any]) -> tuple[str, str]:
    return (edge["start_id"], edge["end_id"])


def _summarize(edges: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile: dict[str, int] = {}
    by_method: dict[str, int] = {}
    confidences: list[float] = []
    for edge in edges:
        profile = edge.get("profile") or "<none>"
        by_profile[profile] = by_profile.get(profile, 0) + 1
        method = edge.get("method") or "<none>"
        by_method[method] = by_method.get(method, 0) + 1
        conf = edge.get("confidence")
        if isinstance(conf, (int, float)):
            confidences.append(float(conf))
    conf_stats = {}
    if confidences:
        conf_stats = {
            "min": min(confidences),
            "avg": sum(confidences) / len(confidences),
            "max": max(confidences),
        }
    return {
        "total": len(edges),
        "by_profile": by_profile,
        "by_method": by_method,
        "confidence": conf_stats,
    }


def _sample(edges: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    if not edges:
        return []
    ordered = sorted(edges, key=lambda e: (e.get("confidence") is None, e.get("confidence", 0.0)))
    if len(ordered) <= size:
        return ordered
    # Take low/mid/high slices
    slice_size = max(1, size // 3)
    low = ordered[:slice_size]
    mid_start = max(0, len(ordered) // 2 - slice_size // 2)
    mid = ordered[mid_start : mid_start + slice_size]
    high = ordered[-slice_size:]
    sample = low + mid + high
    return sample[:size]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare niclip MAPS_TO versions")
    parser.add_argument("--v1", default="niclip_v1")
    parser.add_argument("--v2", default="niclip_v2")
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument(
        "--output-prefix",
        default="artifacts/matching/niclip_compare_v1_v2",
        help="Output prefix for JSON/CSV reports",
    )
    args = parser.parse_args()

    db = create_graph_client()

    edges_v1 = _load_edges(db, args.v1)
    edges_v2 = _load_edges(db, args.v2)

    v1_keys = { _edge_key(e) for e in edges_v1 }
    v2_keys = { _edge_key(e) for e in edges_v2 }

    v1_only = [e for e in edges_v1 if _edge_key(e) not in v2_keys]
    v2_only = [e for e in edges_v2 if _edge_key(e) not in v1_keys]
    overlap = len(v1_keys & v2_keys)

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "version_a": args.v1,
        "version_b": args.v2,
        "summary": {
            "v1": _summarize(edges_v1),
            "v2": _summarize(edges_v2),
            "v1_only": _summarize(v1_only),
            "v2_only": _summarize(v2_only),
            "overlap": overlap,
        },
    }

    output_prefix = Path(args.output_prefix)
    json_path = output_prefix.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Write samples
    samples = [
        {"group": "v1_only", **row} for row in _sample(v1_only, args.sample_size)
    ] + [
        {"group": "v2_only", **row} for row in _sample(v2_only, args.sample_size)
    ]
    csv_path = output_prefix.with_suffix(".csv")
    _write_csv(csv_path, samples)

    db.close()


if __name__ == "__main__":
    main()
