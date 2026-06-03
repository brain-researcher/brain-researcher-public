"""Validate task-ontology structure against behavioral embedding similarity."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_GRAPH_EDGE_TYPES = ("BELONGS_TO_FAMILY", "MAPS_TO")


@dataclass(frozen=True)
class BehaviorStructureValidationConfig:
    """Configuration for task-structure vs behavior-space validation."""

    task_source: str = "Psych-101"
    task_label: str = "Task"
    text_embedding_property: str = "embedding_text_v1"
    behavior_embedding_property: str = "embedding_centaur_behavior_v1"
    graph_edge_types: tuple[str, ...] = DEFAULT_GRAPH_EDGE_TYPES


def build_behavior_structure_validation(
    raw_slice: dict[str, Any],
    *,
    config: BehaviorStructureValidationConfig = BehaviorStructureValidationConfig(),
) -> dict[str, Any]:
    """Compute pairwise structure/similarity metrics for task nodes."""
    task_nodes = _select_task_nodes(raw_slice, config=config)
    node_lookup = {
        str(node.get("id")): node
        for node in raw_slice.get("nodes") or []
        if node.get("id")
    }
    adjacency = _build_graph_adjacency(
        raw_slice, node_lookup=node_lookup, config=config
    )
    pairwise_records = _build_pairwise_records(task_nodes, adjacency=adjacency)
    summary = _summarize_pairwise_records(pairwise_records, task_nodes=task_nodes)
    return {
        "config": {
            "task_source": config.task_source,
            "task_label": config.task_label,
            "text_embedding_property": config.text_embedding_property,
            "behavior_embedding_property": config.behavior_embedding_property,
            "graph_edge_types": list(config.graph_edge_types),
        },
        "task_nodes": task_nodes,
        "pairwise_records": pairwise_records,
        "summary": summary,
    }


def write_behavior_structure_validation_artifacts(
    result: dict[str, Any],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write summary, pairwise table, and plots to disk."""
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    task_nodes_path = out_dir / "task_nodes.json"
    summary_path = out_dir / "summary.json"
    pairwise_tsv_path = out_dir / "pairwise_metrics.tsv"

    task_nodes_path.write_text(
        json.dumps(_json_ready(result.get("task_nodes") or []), indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(_json_ready(result.get("summary") or {}), indent=2),
        encoding="utf-8",
    )

    pairwise_records = result.get("pairwise_records") or []
    fieldnames = [
        "task_a_id",
        "task_a_name",
        "task_b_id",
        "task_b_name",
        "graph_distance",
        "graph_proximity",
        "text_cosine",
        "behavior_cosine",
        "same_family",
        "same_subfamily",
        "family_a",
        "family_b",
        "subfamily_a",
        "subfamily_b",
    ]
    with pairwise_tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in pairwise_records:
            writer.writerow({key: row.get(key) for key in fieldnames})

    plot_paths = _write_validation_plots(
        pairwise_records=pairwise_records,
        output_dir=out_dir,
    )

    return {
        "task_nodes_json": str(task_nodes_path),
        "summary_json": str(summary_path),
        "pairwise_metrics_tsv": str(pairwise_tsv_path),
        **plot_paths,
    }


def _select_task_nodes(
    raw_slice: dict[str, Any],
    *,
    config: BehaviorStructureValidationConfig,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw_node in raw_slice.get("nodes") or []:
        labels = [str(label) for label in raw_node.get("labels") or []]
        if config.task_label not in labels:
            continue
        properties = dict(raw_node.get("properties") or {})
        if str(properties.get("source") or "").strip() != config.task_source:
            continue
        text_vector = _coerce_numeric_vector(
            properties.get(config.text_embedding_property)
        )
        behavior_vector = _coerce_numeric_vector(
            properties.get(config.behavior_embedding_property)
        )
        if text_vector is None or behavior_vector is None:
            continue
        selected.append(
            {
                "id": str(raw_node.get("id")),
                "name": str(
                    properties.get("name")
                    or properties.get("canonical_name")
                    or raw_node.get("id")
                ),
                "family_id": _string_or_none(properties.get("family_id")),
                "subfamily_id": _string_or_none(properties.get("subfamily_id")),
                "canonical_task_id": _string_or_none(
                    properties.get("canonical_task_id")
                ),
                "text_embedding": text_vector,
                "behavior_embedding": behavior_vector,
            }
        )
    selected.sort(key=lambda node: node["id"])
    return selected


def _build_graph_adjacency(
    raw_slice: dict[str, Any],
    *,
    node_lookup: dict[str, dict[str, Any]],
    config: BehaviorStructureValidationConfig,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_lookup}
    allowed_edge_types = set(config.graph_edge_types)
    for edge in raw_slice.get("edges") or []:
        edge_type = str(
            edge.get("edge_type") or edge.get("type") or edge.get("relationship_type")
        )
        if edge_type not in allowed_edge_types:
            continue
        source = str(edge.get("source") or edge.get("start") or "").strip()
        target = str(edge.get("target") or edge.get("end") or "").strip()
        if not source or not target:
            continue
        if source not in adjacency or target not in adjacency:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def _build_pairwise_records(
    task_nodes: list[dict[str, Any]],
    *,
    adjacency: dict[str, set[str]],
) -> list[dict[str, Any]]:
    distance_by_source = {
        node["id"]: _shortest_path_lengths(node["id"], adjacency=adjacency)
        for node in task_nodes
    }
    records: list[dict[str, Any]] = []
    for left, right in combinations(task_nodes, 2):
        distance = distance_by_source.get(left["id"], {}).get(right["id"])
        records.append(
            {
                "task_a_id": left["id"],
                "task_a_name": left["name"],
                "task_b_id": right["id"],
                "task_b_name": right["name"],
                "graph_distance": distance,
                "graph_proximity": (
                    float(1.0 / (1.0 + distance)) if distance is not None else None
                ),
                "text_cosine": _cosine_similarity(
                    left["text_embedding"], right["text_embedding"]
                ),
                "behavior_cosine": _cosine_similarity(
                    left["behavior_embedding"], right["behavior_embedding"]
                ),
                "same_family": bool(
                    left.get("family_id")
                    and left.get("family_id") == right.get("family_id")
                ),
                "same_subfamily": bool(
                    left.get("subfamily_id")
                    and left.get("subfamily_id") == right.get("subfamily_id")
                ),
                "family_a": left.get("family_id"),
                "family_b": right.get("family_id"),
                "subfamily_a": left.get("subfamily_id"),
                "subfamily_b": right.get("subfamily_id"),
            }
        )
    return records


def _summarize_pairwise_records(
    pairwise_records: list[dict[str, Any]],
    *,
    task_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    connected_rows = [
        row for row in pairwise_records if row.get("graph_distance") is not None
    ]
    disconnected_rows = [
        row for row in pairwise_records if row.get("graph_distance") is None
    ]
    same_family_rows = [row for row in pairwise_records if row.get("same_family")]
    different_family_rows = [
        row for row in pairwise_records if not row.get("same_family")
    ]

    distances = [float(row["graph_distance"]) for row in connected_rows]
    proximities = [float(row["graph_proximity"]) for row in connected_rows]
    text_cosines_connected = [float(row["text_cosine"]) for row in connected_rows]
    behavior_cosines_connected = [
        float(row["behavior_cosine"]) for row in connected_rows
    ]

    summary = {
        "task_node_count": len(task_nodes),
        "pairwise_count": len(pairwise_records),
        "connected_pair_count": len(connected_rows),
        "disconnected_pair_count": len(disconnected_rows),
        "same_family_pair_count": len(same_family_rows),
        "different_family_pair_count": len(different_family_rows),
        "correlations": {
            "graph_distance_vs_text_cosine_spearman": _spearman(
                distances, text_cosines_connected
            ),
            "graph_distance_vs_behavior_cosine_spearman": _spearman(
                distances, behavior_cosines_connected
            ),
            "graph_proximity_vs_text_cosine_spearman": _spearman(
                proximities, text_cosines_connected
            ),
            "graph_proximity_vs_behavior_cosine_spearman": _spearman(
                proximities, behavior_cosines_connected
            ),
        },
        "group_stats": {
            "same_family_text_cosine_median": _median(
                row["text_cosine"] for row in same_family_rows
            ),
            "different_family_text_cosine_median": _median(
                row["text_cosine"] for row in different_family_rows
            ),
            "same_family_behavior_cosine_median": _median(
                row["behavior_cosine"] for row in same_family_rows
            ),
            "different_family_behavior_cosine_median": _median(
                row["behavior_cosine"] for row in different_family_rows
            ),
        },
    }
    summary["group_stats"]["text_family_separation_margin"] = _safe_difference(
        summary["group_stats"]["same_family_text_cosine_median"],
        summary["group_stats"]["different_family_text_cosine_median"],
    )
    summary["group_stats"]["behavior_family_separation_margin"] = _safe_difference(
        summary["group_stats"]["same_family_behavior_cosine_median"],
        summary["group_stats"]["different_family_behavior_cosine_median"],
    )
    return summary


def _write_validation_plots(
    *,
    pairwise_records: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, str]:
    if not pairwise_records:
        return {}
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return {}

    connected_rows = [
        row for row in pairwise_records if row.get("graph_distance") is not None
    ]
    if not connected_rows:
        return {}

    plot_paths: dict[str, str] = {}

    def _scatter_plot(value_key: str, file_name: str, y_label: str) -> None:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(
            [row["graph_distance"] for row in connected_rows],
            [row[value_key] for row in connected_rows],
            alpha=0.8,
        )
        ax.set_xlabel("Graph distance")
        ax.set_ylabel(y_label)
        ax.set_title(f"Graph distance vs {y_label}")
        fig.tight_layout()
        path = output_dir / file_name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plot_paths[file_name.replace(".png", "")] = str(path)

    _scatter_plot(
        "behavior_cosine", "graph_distance_vs_behavior_cosine.png", "Behavior cosine"
    )
    _scatter_plot("text_cosine", "graph_distance_vs_text_cosine.png", "Text cosine")

    same_family_behavior = [
        row["behavior_cosine"] for row in pairwise_records if row.get("same_family")
    ]
    different_family_behavior = [
        row["behavior_cosine"] for row in pairwise_records if not row.get("same_family")
    ]
    same_family_text = [
        row["text_cosine"] for row in pairwise_records if row.get("same_family")
    ]
    different_family_text = [
        row["text_cosine"] for row in pairwise_records if not row.get("same_family")
    ]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(
        [
            same_family_behavior or [math.nan],
            different_family_behavior or [math.nan],
            same_family_text or [math.nan],
            different_family_text or [math.nan],
        ],
        tick_labels=[
            "Behavior same family",
            "Behavior diff family",
            "Text same family",
            "Text diff family",
        ],
    )
    ax.set_ylabel("Cosine similarity")
    ax.set_title("Family separation in behavior/text spaces")
    fig.autofmt_xdate(rotation=20)
    fig.tight_layout()
    family_path = output_dir / "family_similarity_boxplot.png"
    fig.savefig(family_path, dpi=150)
    plt.close(fig)
    plot_paths["family_similarity_boxplot"] = str(family_path)

    return plot_paths


def _coerce_numeric_vector(value: Any) -> np.ndarray | None:
    if value is None or isinstance(value, str | bytes | dict):
        return None
    try:
        array = np.asarray(value, dtype=float)
    except Exception:
        return None
    if array.ndim != 1 or array.size == 0:
        return None
    if np.isnan(array).any():
        return None
    return array


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.floating | np.integer):
        return value.item()
    return value


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _shortest_path_lengths(
    source_id: str,
    *,
    adjacency: dict[str, set[str]],
) -> dict[str, int]:
    if source_id not in adjacency:
        return {}
    distances = {source_id: 0}
    queue = [source_id]
    while queue:
        current = queue.pop(0)
        current_distance = distances[current]
        for neighbor in adjacency.get(current, set()):
            if neighbor in distances:
                continue
            distances[neighbor] = current_distance + 1
            queue.append(neighbor)
    return distances


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0.0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _median(values: Any) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return float(np.median(np.asarray(numeric, dtype=float)))


def _safe_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _rankdata(np.asarray(left, dtype=float))
    right_ranks = _rankdata(np.asarray(right, dtype=float))
    left_centered = left_ranks - left_ranks.mean()
    right_centered = right_ranks - right_ranks.mean()
    denom = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denom == 0.0:
        return None
    return float(np.dot(left_centered, right_centered) / denom)


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(values):
        next_index = index + 1
        while (
            next_index < len(values)
            and values[order[next_index]] == values[order[index]]
        ):
            next_index += 1
        rank = ((index + next_index - 1) / 2.0) + 1.0
        for position in range(index, next_index):
            ranks[order[position]] = rank
        index = next_index
    return ranks
