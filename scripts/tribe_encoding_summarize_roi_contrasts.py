#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from nilearn import datasets


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _condition_groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[(str(row["task_id"]), str(row["condition"]))].append(idx)
    return groups


def _load_manifests(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        if task_id not in manifests:
            manifests[task_id] = _read_json(Path(row["manifest_path"]))
    return manifests


def _format_roi_name(name: str, hemisphere: str) -> str:
    pretty = name.replace("G_and_S", "G&S").replace("_", " ")
    hemi_prefix = "L" if hemisphere == "lh" else "R"
    return f"{hemi_prefix}: {pretty}"


def _fetch_surface_atlas() -> dict[str, Any]:
    atlas = datasets.fetch_atlas_surf_destrieux()
    left = np.asarray(atlas["map_left"], dtype=np.int32)
    right = np.asarray(atlas["map_right"], dtype=np.int32)
    labels = list(atlas["labels"])
    rois: list[dict[str, Any]] = []
    for hemisphere, mapping in (("lh", left), ("rh", right)):
        for label_idx, label_name in enumerate(labels):
            if label_idx == 0:
                continue
            vertex_idx = np.flatnonzero(mapping == label_idx)
            if vertex_idx.size == 0:
                continue
            global_idx = vertex_idx if hemisphere == "lh" else vertex_idx + left.size
            rois.append(
                {
                    "roi_id": f"{hemisphere}:{label_idx}",
                    "hemisphere": hemisphere,
                    "label_index": int(label_idx),
                    "name": _format_roi_name(str(label_name), hemisphere),
                    "vertex_indices": global_idx.astype(np.int32),
                }
            )
    return {
        "name": "destrieux_surface_fsaverage5",
        "template": str(atlas.get("template", "fsaverage")),
        "left_n_vertices": int(left.size),
        "right_n_vertices": int(right.size),
        "n_rois": len(rois),
        "rois": rois,
    }


def _item_roi_matrix(embeddings: np.ndarray, atlas: dict[str, Any]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    roi_values = np.zeros((embeddings.shape[0], len(atlas["rois"])), dtype=np.float32)
    for roi_idx, roi in enumerate(atlas["rois"]):
        roi_values[:, roi_idx] = embeddings[:, roi["vertex_indices"]].mean(axis=1)
    return roi_values, atlas["rois"]


def _top_roi_records(
    *, diff: np.ndarray, effect: np.ndarray, rois: list[dict[str, Any]], top_k: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive_order = np.argsort(diff)[::-1]
    negative_order = np.argsort(diff)
    top_positive: list[dict[str, Any]] = []
    top_negative: list[dict[str, Any]] = []
    for idx in positive_order:
        if len(top_positive) >= top_k or diff[idx] <= 0:
            break
        top_positive.append(
            {
                "roi_id": rois[idx]["roi_id"],
                "roi_name": rois[idx]["name"],
                "mean_diff": float(diff[idx]),
                "cohen_d": float(effect[idx]),
            }
        )
    for idx in negative_order:
        if len(top_negative) >= top_k or diff[idx] >= 0:
            break
        top_negative.append(
            {
                "roi_id": rois[idx]["roi_id"],
                "roi_name": rois[idx]["name"],
                "mean_diff": float(diff[idx]),
                "cohen_d": float(effect[idx]),
            }
        )
    return top_positive, top_negative


def _roi_contrast_summaries(
    *,
    manifests: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    roi_values: np.ndarray,
    rois: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    groups = _condition_groups(rows)
    summaries: list[dict[str, Any]] = []
    for task_id, manifest in sorted(manifests.items()):
        for contrast in manifest.get("contrasts", []):
            pos_idxs: list[int] = []
            neg_idxs: list[int] = []
            for condition in contrast.get("positive_conditions", []):
                pos_idxs.extend(groups.get((task_id, str(condition)), []))
            for condition in contrast.get("negative_conditions", []):
                neg_idxs.extend(groups.get((task_id, str(condition)), []))
            if not pos_idxs or not neg_idxs:
                continue
            pos = roi_values[pos_idxs]
            neg = roi_values[neg_idxs]
            diff = pos.mean(axis=0) - neg.mean(axis=0)
            pos_var = pos.var(axis=0, ddof=1) if len(pos_idxs) > 1 else np.zeros(diff.shape, dtype=np.float32)
            neg_var = neg.var(axis=0, ddof=1) if len(neg_idxs) > 1 else np.zeros(diff.shape, dtype=np.float32)
            pooled = np.sqrt(np.maximum((pos_var + neg_var) / 2.0, 1e-8))
            cohen_d = diff / pooled
            top_positive, top_negative = _top_roi_records(
                diff=diff, effect=cohen_d, rois=rois, top_k=top_k
            )
            summaries.append(
                {
                    "candidate_type": "roi_contrast_summary",
                    "task_id": task_id,
                    "contrast_id": str(contrast["contrast_id"]),
                    "family": manifest.get("family"),
                    "expected_rois": manifest.get("expected_rois", []),
                    "positive_conditions": contrast.get("positive_conditions", []),
                    "negative_conditions": contrast.get("negative_conditions", []),
                    "n_positive": len(pos_idxs),
                    "n_negative": len(neg_idxs),
                    "roi_diff_norm": float(np.linalg.norm(diff)),
                    "roi_mean_abs_diff": float(np.mean(np.abs(diff))),
                    "max_abs_cohen_d": float(np.max(np.abs(cohen_d))),
                    "top_positive_rois": top_positive,
                    "top_negative_rois": top_negative,
                    "roi_vector": [float(x) for x in diff.tolist()],
                }
            )
    return summaries


def _dedupe_candidates(
    *,
    contrast_findings: list[dict[str, Any]],
    cross_task_findings: list[dict[str, Any]],
    nn_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}

    def keep(key: tuple[Any, ...], row: dict[str, Any]) -> None:
        current = deduped.get(key)
        if current is None or float(row.get("score", 0.0)) > float(current.get("score", 0.0)):
            deduped[key] = dict(row)

    for row in contrast_findings:
        keep(("contrast", row["task_id"], row["contrast_id"]), row)
    for row in cross_task_findings:
        pair = tuple(
            sorted(
                [
                    f"{row['left_task_id']}::{row['left_condition']}",
                    f"{row['right_task_id']}::{row['right_condition']}",
                ]
            )
        )
        keep(("cross_task_similarity",) + pair, row)
    for row in nn_findings:
        pair = tuple(
            sorted(
                [
                    f"{row['task_id']}::{row['item_id']}",
                    f"{row['neighbor_task_id']}::{row['neighbor_item_id']}",
                ]
            )
        )
        keep(("nearest_neighbor_surprise",) + pair, row)
    return list(deduped.values())


def _priority_score(row: dict[str, Any], type_max: dict[str, float]) -> float:
    candidate_type = str(row.get("candidate_type"))
    base = float(row.get("score", 0.0))
    denom = max(type_max.get(candidate_type, 1.0), 1e-8)
    normalized = base / denom
    weights = {"contrast": 3.0, "cross_task_similarity": 1.5, "nearest_neighbor_surprise": 1.0}
    return float(weights.get(candidate_type, 1.0) * normalized)


def _select_diverse_candidates(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    contrasts = [row for row in candidates if row.get("candidate_type") == "contrast"]
    others = [row for row in candidates if row.get("candidate_type") != "contrast"]
    contrasts.sort(key=lambda row: (float(row["priority_score"]), float(row.get("score", 0.0))), reverse=True)
    others.sort(key=lambda row: (float(row["priority_score"]), float(row.get("score", 0.0))), reverse=True)

    selected: list[dict[str, Any]] = []
    selected.extend(contrasts[:top_k])
    if len(selected) >= top_k:
        return selected[:top_k]

    node_uses: dict[tuple[str, str], int] = defaultdict(int)
    pair_uses: set[tuple[str, str]] = set()

    for row in others:
        if len(selected) >= top_k:
            break
        candidate_type = str(row.get("candidate_type"))
        if candidate_type == "cross_task_similarity":
            nodes = [
                (str(row["left_task_id"]), str(row["left_condition"])),
                (str(row["right_task_id"]), str(row["right_condition"])),
            ]
            pair_key = tuple(sorted([f"{nodes[0][0]}::{nodes[0][1]}", f"{nodes[1][0]}::{nodes[1][1]}"]))
            if pair_key in pair_uses or any(node_uses[node] >= 1 for node in nodes):
                continue
            selected.append(row)
            pair_uses.add(pair_key)
            for node in nodes:
                node_uses[node] += 1
        elif candidate_type == "nearest_neighbor_surprise":
            nodes = [
                (str(row["task_id"]), str(row["condition"])),
                (str(row["neighbor_task_id"]), str(row["neighbor_condition"])),
            ]
            pair_key = tuple(sorted([f"{nodes[0][0]}::{nodes[0][1]}", f"{nodes[1][0]}::{nodes[1][1]}"]))
            if pair_key in pair_uses or any(node_uses[node] >= 1 for node in nodes):
                continue
            selected.append(row)
            pair_uses.add(pair_key)
            for node in nodes:
                node_uses[node] += 1
        else:
            selected.append(row)
    return selected[:top_k]


def _build_reranked_candidates(
    *,
    contrast_findings: list[dict[str, Any]],
    cross_task_findings: list[dict[str, Any]],
    nn_findings: list[dict[str, Any]],
    roi_summaries: dict[tuple[str, str], dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    candidates = _dedupe_candidates(
        contrast_findings=contrast_findings,
        cross_task_findings=cross_task_findings,
        nn_findings=nn_findings,
    )
    type_max: dict[str, float] = {}
    for row in candidates:
        candidate_type = str(row.get("candidate_type"))
        type_max[candidate_type] = max(type_max.get(candidate_type, 0.0), float(row.get("score", 0.0)))

    enriched: list[dict[str, Any]] = []
    for row in candidates:
        out = dict(row)
        out["priority_score"] = _priority_score(row, type_max)
        if row.get("candidate_type") == "contrast":
            roi_summary = roi_summaries.get((str(row["task_id"]), str(row["contrast_id"])))
            if roi_summary is not None:
                out["roi_support"] = {
                    "top_positive_rois": roi_summary.get("top_positive_rois", []),
                    "top_negative_rois": roi_summary.get("top_negative_rois", []),
                    "max_abs_cohen_d": roi_summary.get("max_abs_cohen_d"),
                }
        enriched.append(out)

    selected = _select_diverse_candidates(enriched, top_k)
    for rank, row in enumerate(selected, start=1):
        row["priority_rank"] = rank
    return selected


def _truncate(text: str, width: int = 140) -> str:
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    return text[: width - 3].rstrip() + "..."


def _keyword_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(text).lower())
        if len(token) >= 4 and token not in {"left", "right", "region", "regions", "cortex"}
    }


def _kg_summary_payload(*, answer: str, expected_rois: list[str]) -> dict[str, Any]:
    answer_tokens = _keyword_tokens(answer)
    expected_tokens: set[str] = set()
    for roi in expected_rois:
        expected_tokens.update(_keyword_tokens(roi))
    overlap = sorted(answer_tokens & expected_tokens)
    if not overlap:
        return {
            "text": "No clean KG alignment extracted from the automatic lookup; manual follow-up recommended.",
            "relevance": "low",
            "overlap_tokens": overlap,
        }
    return {
        "text": _truncate(answer, width=220),
        "relevance": "matched",
        "overlap_tokens": overlap,
    }


def _kg_lookup(kg_followups: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in kg_followups:
        if row.get("candidate_type") == "kg_followup":
            lookup[(str(row.get("task_id")), str(row.get("contrast_id")))] = row
    return lookup


def _build_hypothesis_cards(
    *, reranked: list[dict[str, Any]], kg_lookup: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for row in reranked:
        candidate_type = str(row.get("candidate_type"))
        card: dict[str, Any] = {
            "priority_rank": int(row["priority_rank"]),
            "candidate_type": candidate_type,
            "priority_score": float(row["priority_score"]),
            "score": float(row.get("score", 0.0)),
        }
        if candidate_type == "contrast":
            task_id = str(row["task_id"])
            contrast_id = str(row["contrast_id"])
            kg_row = kg_lookup.get((task_id, contrast_id), {})
            kg_answer = kg_row.get("kg_response", {}).get("result", {}).get("answer", "")
            kg_summary = _kg_summary_payload(
                answer=str(kg_answer), expected_rois=list(row.get("expected_rois", []))
            )
            roi_support = row.get("roi_support", {})
            card.update(
                {
                    "title": f"{task_id}:{contrast_id}",
                    "task_id": task_id,
                    "contrast_id": contrast_id,
                    "positive_conditions": row.get("positive_conditions", []),
                    "negative_conditions": row.get("negative_conditions", []),
                    "expected_rois": row.get("expected_rois", []),
                    "top_positive_rois": roi_support.get("top_positive_rois", []),
                    "top_negative_rois": roi_support.get("top_negative_rois", []),
                    "hypothesis": row.get("hypothesis"),
                    "kg_summary": kg_summary["text"],
                    "kg_relevance": kg_summary["relevance"],
                    "kg_overlap_tokens": kg_summary["overlap_tokens"],
                }
            )
        elif candidate_type == "nearest_neighbor_surprise":
            card.update(
                {
                    "title": f"{row['task_id']}:{row['condition']} ~ {row['neighbor_task_id']}:{row['neighbor_condition']}",
                    "task_id": row.get("task_id"),
                    "condition": row.get("condition"),
                    "neighbor_condition": row.get("neighbor_condition"),
                    "item_pair": [row.get("item_id"), row.get("neighbor_item_id")],
                    "hypothesis": row.get("hypothesis"),
                }
            )
        else:
            card.update(
                {
                    "title": f"{row['left_task_id']}:{row['left_condition']} ~ {row['right_task_id']}:{row['right_condition']}",
                    "left": {"task_id": row.get("left_task_id"), "condition": row.get("left_condition")},
                    "right": {"task_id": row.get("right_task_id"), "condition": row.get("right_condition")},
                    "hypothesis": row.get("hypothesis"),
                }
            )
        cards.append(card)
    return cards


def _make_bar_plot(cards: list[dict[str, Any]], out_path: Path) -> None:
    if not cards:
        return
    labels = [textwrap.fill(card["title"], width=30) for card in cards[:12]]
    scores = [float(card["priority_score"]) for card in cards[:12]]
    palette = {
        "contrast": "#1f77b4",
        "cross_task_similarity": "#2ca02c",
        "nearest_neighbor_surprise": "#d62728",
    }
    colors = [palette.get(card["candidate_type"], "#7f7f7f") for card in cards[:12]]
    plt.figure(figsize=(12, 6))
    y = np.arange(len(labels))
    plt.barh(y, scores, color=colors)
    plt.yticks(y, labels)
    plt.gca().invert_yaxis()
    plt.xlabel("Priority Score")
    plt.title("Prioritized TRIBE Sweep Candidates")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=180)
    plt.close()


def _make_contrast_heatmap(
    *, roi_summaries: list[dict[str, Any]], out_path: Path, top_k_contrasts: int, top_k_rois: int
) -> None:
    if not roi_summaries:
        return
    selected = sorted(
        roi_summaries,
        key=lambda row: (float(row.get("source_score", 0.0)), float(row["max_abs_cohen_d"])),
        reverse=True,
    )[:top_k_contrasts]
    roi_names: list[str] = []
    for row in selected:
        for roi in row.get("top_positive_rois", []) + row.get("top_negative_rois", []):
            if roi["roi_name"] not in roi_names:
                roi_names.append(roi["roi_name"])
            if len(roi_names) >= top_k_rois:
                break
        if len(roi_names) >= top_k_rois:
            break
    if not roi_names:
        return

    matrix = np.zeros((len(selected), len(roi_names)), dtype=np.float32)
    for row_idx, row in enumerate(selected):
        roi_map = {roi["roi_name"]: float(roi["mean_diff"]) for roi in row.get("top_positive_rois", []) + row.get("top_negative_rois", [])}
        for col_idx, roi_name in enumerate(roi_names):
            matrix[row_idx, col_idx] = roi_map.get(roi_name, 0.0)

    plt.figure(figsize=(max(8, len(roi_names) * 0.7), max(4, len(selected) * 0.8)))
    vmax = float(np.max(np.abs(matrix))) if matrix.size else 1.0
    plt.imshow(matrix, aspect="auto", cmap="coolwarm", vmin=-vmax, vmax=vmax)
    plt.colorbar(label="ROI Mean Difference")
    plt.xticks(np.arange(len(roi_names)), [textwrap.fill(name, 18) for name in roi_names], rotation=45, ha="right")
    plt.yticks(np.arange(len(selected)), [textwrap.fill(f"{row['task_id']}:{row['contrast_id']}", 28) for row in selected])
    plt.title("Top Contrast ROI Summary")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=180)
    plt.close()


def _report_markdown(
    *,
    run_summary: dict[str, Any],
    analysis_summary: dict[str, Any],
    roi_summaries: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    figure_paths: dict[str, Path],
) -> str:
    lines: list[str] = []
    lines.append("# TRIBE Wave-1 ROI Hypothesis Report")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- Run root: {run_summary['run_root']}")
    lines.append(f"- Analysis dir: {analysis_summary['analysis_dir']}")
    lines.append(f"- Successful stimuli: {run_summary['n_success']} / failures {run_summary['n_failures']}")
    lines.append(f"- Embedding shape: {tuple(analysis_summary['embedding_shape'])}")
    lines.append(f"- Contrast findings: {analysis_summary['n_contrast_findings']}")
    lines.append(f"- Cross-task similarity findings: {analysis_summary['n_cross_task_findings']}")
    lines.append(f"- Nearest-neighbor surprises: {analysis_summary['n_nearest_neighbor_findings']}")
    lines.append("")
    lines.append("## Figures")
    lines.append("")
    for label, path in figure_paths.items():
        lines.append(f"- {label}: {path}")
    lines.append("")
    lines.append("## Top Contrast Summaries")
    lines.append("")
    top_contrasts = sorted(
        roi_summaries,
        key=lambda row: (float(row.get("source_score", 0.0)), float(row["max_abs_cohen_d"])),
        reverse=True,
    )[:5]
    for row in top_contrasts:
        lines.append(f"### {row['task_id']}:{row['contrast_id']}")
        lines.append("")
        lines.append(f"- Expected ROIs: {', '.join(row.get('expected_rois', [])) or 'n/a'}")
        pos = ", ".join(f"{roi['roi_name']} (d={roi['cohen_d']:.2f})" for roi in row.get("top_positive_rois", [])[:5]) or "n/a"
        neg = ", ".join(f"{roi['roi_name']} (d={roi['cohen_d']:.2f})" for roi in row.get("top_negative_rois", [])[:5]) or "n/a"
        lines.append(f"- Top positive ROIs: {pos}")
        lines.append(f"- Top negative ROIs: {neg}")
        lines.append("")
    lines.append("## Prioritized Hypothesis Cards")
    lines.append("")
    for card in cards[:12]:
        lines.append(f"### {card['priority_rank']}. {card['title']}")
        lines.append("")
        lines.append(f"- Candidate type: {card['candidate_type']} | priority {card['priority_score']:.3f} | raw score {card['score']:.3f}")
        if card["candidate_type"] == "contrast":
            lines.append(f"- Conditions: {card.get('positive_conditions', [])} vs {card.get('negative_conditions', [])}")
            pos = ", ".join(f"{roi['roi_name']} (d={roi['cohen_d']:.2f})" for roi in card.get("top_positive_rois", [])[:4]) or "n/a"
            neg = ", ".join(f"{roi['roi_name']} (d={roi['cohen_d']:.2f})" for roi in card.get("top_negative_rois", [])[:4]) or "n/a"
            lines.append(f"- ROI support+: {pos}")
            lines.append(f"- ROI support-: {neg}")
            lines.append(f"- KG summary ({card.get('kg_relevance', 'n/a')} relevance): {card.get('kg_summary') or 'n/a'}")
        elif card["candidate_type"] == "nearest_neighbor_surprise":
            lines.append(f"- Item pair: {card.get('item_pair', [])} with conditions {card.get('condition')} and {card.get('neighbor_condition')}")
        else:
            left = card.get("left", {})
            right = card.get("right", {})
            lines.append(f"- Cross-task pair: {left.get('task_id')}:{left.get('condition')} ~ {right.get('task_id')}:{right.get('condition')}")
        lines.append(f"- Hypothesis: {card.get('hypothesis')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate TRIBE embedding findings into ROI summaries and a compact hypothesis report.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--top-roi-k", type=int, default=8)
    parser.add_argument("--top-candidates", type=int, default=20)
    parser.add_argument("--top-contrast-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_root = Path(args.run_root).expanduser().resolve()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()

    run_summary = _read_json(run_root / "run_summary.json")
    analysis_summary = _read_json(analysis_dir / "summary.json")
    rows = _read_jsonl(run_root / "embedding_rows.jsonl")
    embeddings = np.load(run_root / "embeddings_matrix.npy")
    manifests = _load_manifests(rows)
    contrast_findings = _read_jsonl(analysis_dir / "contrast_findings.jsonl")
    cross_task_findings = _read_jsonl(analysis_dir / "cross_task_similarity_findings.jsonl")
    nn_findings = _read_jsonl(analysis_dir / "nearest_neighbor_surprises.jsonl")
    kg_followups = _read_jsonl(analysis_dir / "kg_followups.jsonl")

    atlas = _fetch_surface_atlas()
    roi_values, rois = _item_roi_matrix(embeddings, atlas)
    roi_summaries = _roi_contrast_summaries(
        manifests=manifests,
        rows=rows,
        roi_values=roi_values,
        rois=rois,
        top_k=int(args.top_roi_k),
    )
    contrast_score_lookup = {
        (str(row["task_id"]), str(row["contrast_id"])): float(row.get("score", 0.0))
        for row in contrast_findings
    }
    for row in roi_summaries:
        row["source_score"] = contrast_score_lookup.get((str(row["task_id"]), str(row["contrast_id"])), 0.0)

    roi_lookup = {(row["task_id"], row["contrast_id"]): row for row in roi_summaries}
    reranked = _build_reranked_candidates(
        contrast_findings=contrast_findings,
        cross_task_findings=cross_task_findings,
        nn_findings=nn_findings,
        roi_summaries=roi_lookup,
        top_k=int(args.top_candidates),
    )
    cards = _build_hypothesis_cards(reranked=reranked, kg_lookup=_kg_lookup(kg_followups))

    figure_dir = analysis_dir / "figures"
    bar_path = figure_dir / "prioritized_candidates_bar.png"
    heatmap_path = figure_dir / "contrast_roi_heatmap.png"
    _make_bar_plot(cards, bar_path)
    _make_contrast_heatmap(
        roi_summaries=roi_summaries,
        out_path=heatmap_path,
        top_k_contrasts=int(args.top_contrast_k),
        top_k_rois=max(int(args.top_roi_k), 10),
    )

    report_path = analysis_dir / "hypothesis_report.md"
    report = _report_markdown(
        run_summary=run_summary,
        analysis_summary=analysis_summary,
        roi_summaries=roi_summaries,
        cards=cards,
        figure_paths={
            "Prioritized candidate bar plot": bar_path,
            "Contrast ROI heatmap": heatmap_path,
        },
    )

    roi_payload = {
        "atlas_name": atlas["name"],
        "template": atlas["template"],
        "left_n_vertices": atlas["left_n_vertices"],
        "right_n_vertices": atlas["right_n_vertices"],
        "n_rois": atlas["n_rois"],
    }
    _write_json(analysis_dir / "roi_atlas_summary.json", roi_payload)
    _write_jsonl(analysis_dir / "roi_contrast_summaries.jsonl", roi_summaries)
    _write_jsonl(analysis_dir / "ranked_candidates_deduped.jsonl", reranked)
    _write_jsonl(analysis_dir / "hypothesis_cards.jsonl", cards)
    _write_text(report_path, report)

    print(
        json.dumps(
            {
                "analysis_dir": str(analysis_dir),
                "report_path": str(report_path),
                "n_roi_contrast_summaries": len(roi_summaries),
                "n_reranked_candidates": len(reranked),
                "n_hypothesis_cards": len(cards),
                "figure_paths": {
                    "prioritized_candidates_bar": str(bar_path),
                    "contrast_roi_heatmap": str(heatmap_path),
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
