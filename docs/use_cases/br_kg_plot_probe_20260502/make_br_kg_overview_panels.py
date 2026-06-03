#!/usr/bin/env python3
"""Generate fancy BR-KG overview panels from prod exports.

Panels:

- node circle pack: what node labels exist and their relative scale
- edge circle pack: what relationship types exist and their relative scale
- schema meta-graph: dominant source-label / relationship / target-label topology
- provenance Sankey: measured upstream source values -> node labels
- edge density matrix: source label x target label edge counts
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle, FancyArrowPatch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"

LABEL_COUNTS = DATA_DIR / "kg_schema_triples_full_label_counts.csv"
REL_COUNTS = DATA_DIR / "kg_schema_triples_full_relationship_counts.csv"
LABELSET_TRIPLES = DATA_DIR / "kg_schema_triples_full_labelsets.csv"
UNWOUND_TRIPLES = DATA_DIR / "kg_schema_triples_full_unwound_labels.csv"
SOURCE_PROBE = DATA_DIR / "br_kg_source_values_probe.json"
OVERVIEW_DATA = DATA_DIR / "br_kg_overview_panel_data.json"


NODE_CATEGORY_COLORS = {
    "Imaging-derived": "#20d3b3",
    "Literature": "#4ea5ff",
    "Ontology": "#c77dff",
    "Biomedical": "#b8f34d",
    "Data and methods": "#ffb000",
    "Review and governance": "#9ea7ff",
    "Other": "#95a3b3",
}

EDGE_CATEGORY_COLORS = {
    "Membership and provenance": "#20d3b3",
    "Spatial and anatomical": "#b8f34d",
    "Semantic and ontology": "#c77dff",
    "Methods and runtime": "#ffb000",
    "Literature evidence": "#4ea5ff",
    "Data and cohort": "#ff6b6b",
    "Review and governance": "#9ea7ff",
    "Other": "#95a3b3",
}

SOURCE_COLORS = {
    "Neurosynth": "#4ea5ff",
    "NeuroVault": "#20d3b3",
    "Neurostore": "#6fb6ff",
    "OpenNeuro / GLM": "#ffb000",
    "Cognitive Atlas": "#c77dff",
    "PubMed / scholarly": "#3b82f6",
    "ONVOC / ontology": "#b47cff",
    "Atlas / anatomy": "#b8f34d",
    "NiCLIP / embeddings": "#66d9e8",
    "Tool registry": "#ff6b6b",
    "Neurobagel": "#f08c00",
    "Psych-101": "#f783ac",
    "Other": "#95a3b3",
}


def classify_node(label: str) -> str:
    value = label.lower()
    if any(token.lower() in value for token in ["statisticalmap", "statsmap", "statmap", "coordinate", "brainregion", "templatespace", "atlas", "parcellation", "parcel", "region", "brainannotation"]):
        return "Imaging-derived"
    if any(token.lower() in value for token in ["publication", "citation", "author", "institution", "embedding"]):
        return "Literature"
    if any(token.lower() in value for token in ["concept", "term", "ontology", "onvoc", "process", "taskfamily"]):
        return "Ontology"
    if any(token.lower() in value for token in ["phenotype", "species", "finding"]):
        return "Biomedical"
    if any(token.lower() in value for token in ["dataset", "dataresource", "openneuro", "tool", "modality", "repository", "model", "glm", "run", "task", "contrast", "condition", "subject", "experiment", "battery"]):
        return "Data and methods"
    if "review" in value or "policy" in value or "severity" in value:
        return "Review and governance"
    if "collection" in value:
        return "Imaging-derived"
    return "Other"


def classify_edge(rel: str) -> str:
    value = rel.lower()
    if any(token in value for token in ["belongs", "part", "derived", "generated", "hosted", "documented"]):
        return "Membership and provenance"
    if any(token in value for token in ["coordinate", "region", "space", "parcel", "activates", "located"]):
        return "Spatial and anatomical"
    if any(token in value for token in ["term", "about", "onvoc", "domain", "measure", "classified", "kind", "similar", "mentions", "related"]):
        return "Semantic and ontology"
    if any(token in value for token in ["computed", "implements", "version", "glm", "runtime", "failure", "summary", "variant"]):
        return "Methods and runtime"
    if any(token in value for token in ["cites", "citation", "authored", "asserts", "evidence", "text_embedding"]):
        return "Literature evidence"
    if any(token in value for token in ["resource", "dataset", "task", "condition", "phenotype", "modality", "participates", "includes", "battery"]):
        return "Data and cohort"
    if any(token in value for token in ["review", "rule", "severity", "policy", "calibrates", "requires_field", "validity", "lifecycle"]):
        return "Review and governance"
    return "Other"


def canonical_source(source_value: str) -> str:
    value = source_value.lower()
    if "neurosynth" in value:
        return "Neurosynth"
    if "neurovault" in value:
        return "NeuroVault"
    if "neurostore" in value:
        return "Neurostore"
    if "openneuro" in value or "glmfitlins" in value:
        return "OpenNeuro / GLM"
    if "cognitive_atlas" in value or "cogatlas" in value or value in {"cogatlas"}:
        return "Cognitive Atlas"
    if "pubmed" in value or "scholarly" in value:
        return "PubMed / scholarly"
    if "onvoc" in value or "ontology" in value:
        return "ONVOC / ontology"
    if "nilearn" in value or "allen" in value or "neuromaps" in value or "yeo" in value:
        return "Atlas / anatomy"
    if "niclip" in value:
        return "NiCLIP / embeddings"
    if "capabilities" in value or "tool" in value:
        return "Tool registry"
    if "neurobagel" in value:
        return "Neurobagel"
    if "psych-101" in value or "psych101" in value:
        return "Psych-101"
    return "Other"


def clean_label(text: Any, max_len: int = 24) -> str:
    value = str(text)
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def clean_schema_node_label(text: Any) -> str:
    """Display canonical label sets without leaking the pipe-delimited key form."""
    parts = [part for part in str(text).split("|") if part]
    if not parts:
        return str(text)
    if len(parts) == 1:
        return clean_label(parts[0], 18)
    shown = [clean_label(part, 16) for part in parts[:2]]
    if len(parts) > 2:
        shown[-1] = shown[-1] + "+"
    return "\n".join(shown)


def fmt_count(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return f"{value:.0f}"


def pct_text(value: float) -> str:
    if value >= 0.995:
        return ">99%"
    if value >= 0.10:
        return f"{value * 100:.0f}%"
    return f"{value * 100:.1f}%"


def mix_color(color: str, other: str, amount: float) -> str:
    base_rgb = np.array(to_rgb(color))
    other_rgb = np.array(to_rgb(other))
    mixed = base_rgb * (1.0 - amount) + other_rgb * amount
    return "#{:02x}{:02x}{:02x}".format(*(np.clip(mixed * 255, 0, 255).astype(int)))


def save_figure(name: str) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(FIG_DIR / f"{name}.png", dpi=260, bbox_inches="tight")
    plt.savefig(FIG_DIR / f"{name}.svg", bbox_inches="tight")
    plt.close()


def greedy_pack(radii: list[float], *, pad: float = 0.012) -> tuple[list[tuple[float, float, float]], float]:
    if not radii:
        return [], 0.0
    order = sorted(range(len(radii)), key=lambda idx: radii[idx], reverse=True)
    placed_by_order: dict[int, tuple[float, float, float]] = {}
    placed: list[tuple[float, float, float]] = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    placed_by_order[order[0]] = (0.0, 0.0, radii[order[0]])
    placed.append((0.0, 0.0, radii[order[0]]))
    base_step = max(min(radii) * 0.48, max(radii) * 0.045, 0.003)

    for idx in order[1:]:
        r = radii[idx]
        found = None
        for pass_idx in range(6):
            step = base_step * (1.0 + pass_idx * 0.55)
            for k in range(1, 26000):
                radius = step * math.sqrt(k)
                theta = k * golden
                x = radius * math.cos(theta)
                y = radius * math.sin(theta)
                ok = True
                for px, py, pr in placed:
                    if math.hypot(x - px, y - py) < r + pr + pad:
                        ok = False
                        break
                if ok:
                    found = (x, y, r)
                    break
            if found is not None:
                break
        if found is None:
            # Fallback should be rare; put the circle just outside current bounds.
            bound = max(math.hypot(px, py) + pr for px, py, pr in placed)
            found = (bound + r + pad, 0.0, r)
        placed_by_order[idx] = found
        placed.append(found)

    xs = [x for x, _, _ in placed]
    ys = [y for _, y, _ in placed]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    centered = [(x - cx, y - cy, r) for x, y, r in placed_by_order.values()]
    bound = max(math.hypot(x, y) + r for x, y, r in centered)
    by_original = [placed_by_order[i] for i in range(len(radii))]
    by_original = [(x - cx, y - cy, r) for x, y, r in by_original]
    return by_original, bound


def category_circle_pack(frame: pd.DataFrame, *, name_col: str, value_col: str, category_col: str) -> pd.DataFrame:
    rows = []
    total = float(frame[value_col].sum())
    category_totals = frame.groupby(category_col)[value_col].sum().sort_values(ascending=False)
    category_radii_raw = np.sqrt(category_totals.to_numpy(dtype=float) / max(total, 1.0))
    category_radii = (category_radii_raw / max(category_radii_raw.max(), 1e-9) * 0.36 + 0.10).tolist()
    category_positions, category_bound = greedy_pack(category_radii, pad=0.07)
    scale = 0.92 / max(category_bound, 1e-9)

    for cat_idx, category in enumerate(category_totals.index.tolist()):
        cat_rows = frame[frame[category_col] == category].sort_values(value_col, ascending=False).reset_index(drop=True)
        cat_total = float(cat_rows[value_col].sum())
        category_radius = category_radii[cat_idx] * scale
        cx, cy, _ = category_positions[cat_idx]
        cx *= scale
        cy *= scale

        raw_child_radii = np.sqrt(cat_rows[value_col].to_numpy(dtype=float) / max(cat_total, 1.0))
        child_radii = (raw_child_radii / max(raw_child_radii.max(), 1e-9) * 0.095 + 0.013).tolist()
        child_positions, child_bound = greedy_pack(child_radii, pad=0.004)
        child_scale = (category_radius * 0.80) / max(child_bound, 1e-9)
        for row_idx, row in cat_rows.iterrows():
            x, y, r = child_positions[row_idx]
            rows.append(
                {
                    "name": str(row[name_col]),
                    "value": float(row[value_col]),
                    "category": str(category),
                    "x": cx + x * child_scale,
                    "y": cy + y * child_scale,
                    "r": r * child_scale,
                    "category_x": cx,
                    "category_y": cy,
                    "category_r": category_radius,
                    "category_total": cat_total,
                }
            )
    return pd.DataFrame(rows)


def draw_circle_pack(pack: pd.DataFrame, *, title: str, subtitle: str, output_name: str, colors: dict[str, str], label_top_n: int, unit_name: str) -> None:
    sns.set_theme(style="white", context="paper", font_scale=1.0)
    fig = plt.figure(figsize=(15.6, 10.4))
    fig.patch.set_facecolor("#07111f")
    gs = fig.add_gridspec(1, 2, width_ratios=[0.9, 2.1], wspace=0.02)
    ax_info = fig.add_subplot(gs[0, 0])
    ax = fig.add_subplot(gs[0, 1])
    for axis in (ax_info, ax):
        axis.set_facecolor("#07111f")

    # Soft atlas frame: decorative, but it also visually separates the graph boundary.
    for radius, alpha, linewidth in [(1.06, 0.28, 1.2), (0.88, 0.10, 0.9), (0.64, 0.08, 0.8)]:
        ax.add_patch(Circle((0, 0), radius, fill=False, edgecolor="#7d8fa6", linewidth=linewidth, linestyle=(0, (3, 7)), alpha=alpha))
    ax.add_patch(Circle((0, 0), 1.02, fill=False, edgecolor="#d8f6ff", linewidth=1.8, linestyle=(0, (5, 5)), alpha=0.62))

    category_seen = set()
    for _, row in pack.sort_values("category_total", ascending=False).iterrows():
        category = row["category"]
        if category in category_seen:
            continue
        category_seen.add(category)
        color = colors.get(category, "#95a3b3")
        for glow_radius, glow_alpha in [(row["category_r"] * 1.08, 0.08), (row["category_r"] * 1.18, 0.035)]:
            ax.add_patch(Circle((row["category_x"], row["category_y"]), glow_radius, facecolor=color, edgecolor="none", alpha=glow_alpha, zorder=0))
        ax.add_patch(
            Circle(
                (row["category_x"], row["category_y"]),
                row["category_r"],
                facecolor=color,
                alpha=0.085,
                edgecolor=mix_color(color, "#ffffff", 0.25),
                linewidth=1.8,
            )
        )
        ax.text(
            row["category_x"],
            row["category_y"] + row["category_r"] + 0.025,
            f"{category}\n{fmt_count(row['category_total'])}",
            ha="center",
            va="bottom",
            fontsize=8.6,
            color="#dbe9f7",
            weight="bold",
            path_effects=[pe.withStroke(linewidth=3.2, foreground="#07111f", alpha=0.95)],
        )

    top_names = set(pack.sort_values("value", ascending=False).head(label_top_n)["name"])
    for _, row in pack.sort_values("r", ascending=False).iterrows():
        color = colors.get(row["category"], "#95a3b3")
        ax.add_patch(Circle((row["x"], row["y"]), row["r"] * 1.18, facecolor=color, alpha=0.12, edgecolor="none", zorder=2))
        ax.add_patch(Circle((row["x"], row["y"]), row["r"], facecolor=mix_color(color, "#ffffff", 0.04), alpha=0.94, edgecolor="#f8fbff", linewidth=0.72, zorder=3))
        ax.add_patch(Circle((row["x"] - row["r"] * 0.22, row["y"] + row["r"] * 0.22), row["r"] * 0.30, facecolor="#ffffff", alpha=0.12, edgecolor="none", zorder=4))
        if row["name"] in top_names and row["r"] > 0.018:
            label = f"{clean_label(row['name'], 18)}\n{fmt_count(row['value'])}"
            fontsize = float(np.clip(row["r"] * 80, 5.3, 13.2))
            ax.text(
                row["x"],
                row["y"],
                label,
                ha="center",
                va="center",
                fontsize=fontsize,
                color="#03111d",
                weight="bold",
                zorder=5,
                path_effects=[pe.withStroke(linewidth=1.3, foreground="#ffffff", alpha=0.45)],
            )

    ax.text(0.0, 1.135, title, ha="center", va="bottom", fontsize=24, color="#f4f8ff", weight="bold")
    ax.text(0.0, -1.135, subtitle, ha="center", va="top", fontsize=10.2, color="#a7b7c9")
    ax.set_xlim(-1.16, 1.16)
    ax.set_ylim(-1.18, 1.18)
    ax.set_aspect("equal")
    ax.axis("off")

    total = float(pack["value"].sum())
    categories = pack.groupby("category")["value"].sum().sort_values(ascending=False)
    top_rows = pack.sort_values("value", ascending=False).head(5).copy()
    dominant = top_rows.iloc[0]

    ax_info.set_xlim(0, 1)
    ax_info.set_ylim(0, 1)
    ax_info.axis("off")
    ax_info.text(0.06, 0.96, "BR-KG atlas overview", color="#dbe9f7", fontsize=10.5, weight="bold", ha="left")
    ax_info.text(0.06, 0.915, f"{len(pack):,} {unit_name} types", color="#8ea2b8", fontsize=8.4, ha="left")
    ax_info.text(0.06, 0.845, fmt_count(total), color="#f4f8ff", fontsize=31, weight="bold", ha="left")
    ax_info.text(0.06, 0.805, f"total {unit_name} instances", color="#8ea2b8", fontsize=8.6, ha="left")

    dom_color = colors.get(str(dominant["category"]), "#95a3b3")
    ax_info.add_patch(Rectangle((0.06, 0.705), 0.88, 0.075, facecolor="#0e1d31", edgecolor="#263b55", linewidth=0.8))
    ax_info.add_patch(Rectangle((0.06, 0.705), 0.010 + 0.86 * float(dominant["value"]) / total, 0.075, facecolor=dom_color, edgecolor="none", alpha=0.92))
    ax_info.text(0.085, 0.759, "dominant surface", color="#dbe9f7", fontsize=7.4, weight="bold", ha="left", va="center")
    ax_info.text(0.085, 0.728, f"{dominant['name']}  {fmt_count(dominant['value'])} ({pct_text(float(dominant['value']) / total)})", color="#f4f8ff", fontsize=8.2, ha="left", va="center")

    ax_info.text(0.06, 0.645, "Category share", color="#dbe9f7", fontsize=9.1, weight="bold", ha="left")
    y = 0.605
    for category, value in categories.items():
        color = colors.get(category, "#95a3b3")
        width = 0.57 * float(value) / total
        ax_info.add_patch(Rectangle((0.06, y - 0.012), 0.57, 0.024, facecolor="#122236", edgecolor="none", alpha=0.95))
        ax_info.add_patch(Rectangle((0.06, y - 0.012), max(width, 0.005), 0.024, facecolor=color, edgecolor="none", alpha=0.95))
        ax_info.text(0.665, y, pct_text(float(value) / total), color="#8ea2b8", fontsize=7.4, va="center", ha="right")
        ax_info.scatter([0.705], [y], s=46, color=color, edgecolor="#f8fbff", linewidth=0.5)
        ax_info.text(0.735, y, clean_label(category, 25), color="#dbe9f7", fontsize=7.6, va="center", ha="left")
        y -= 0.043

    ax_info.text(0.06, 0.275, "Top surfaces", color="#dbe9f7", fontsize=9.1, weight="bold", ha="left")
    y = 0.235
    for _, row in top_rows.iterrows():
        color = colors.get(row["category"], "#95a3b3")
        ax_info.scatter([0.075], [y], s=68, color=color, edgecolor="#f8fbff", linewidth=0.55)
        ax_info.text(0.105, y + 0.010, clean_label(row["name"], 24), color="#f4f8ff", fontsize=8.0, ha="left", va="center", weight="bold")
        ax_info.text(0.105, y - 0.012, f"{fmt_count(row['value'])}  {pct_text(float(row['value']) / total)}", color="#8ea2b8", fontsize=7.4, ha="left", va="center")
        y -= 0.043

    ax_info.text(0.06, 0.035, "Encoding: bubble area = count; ring color = broad schema/source category.", color="#6f8298", fontsize=7.5, ha="left")
    save_figure(output_name)


def plot_node_circle_pack() -> pd.DataFrame:
    frame = pd.read_csv(LABEL_COUNTS)
    frame["category"] = frame["label"].map(classify_node)
    pack = category_circle_pack(frame, name_col="label", value_col="node_count", category_col="category")
    pack.to_csv(DATA_DIR / "fig11_node_circle_pack_positions.csv", index=False)
    draw_circle_pack(
        pack,
        title="BR-KG node-type composition",
        subtitle="Circle area is node count; color groups node labels by broad source category. Outer dashed line is the BR-KG overview boundary.",
        output_name="fig11_node_circle_pack",
        colors=NODE_CATEGORY_COLORS,
        label_top_n=23,
        unit_name="node",
    )
    return pack


def plot_edge_circle_pack() -> pd.DataFrame:
    frame = pd.read_csv(REL_COUNTS)
    frame["category"] = frame["relationship_type"].map(classify_edge)
    pack = category_circle_pack(frame, name_col="relationship_type", value_col="edge_count", category_col="category")
    pack.to_csv(DATA_DIR / "fig12_edge_circle_pack_positions.csv", index=False)
    draw_circle_pack(
        pack,
        title="BR-KG relationship-type composition",
        subtitle="Circle area is edge count; color groups relationship types by semantic role.",
        output_name="fig12_edge_circle_pack",
        colors=EDGE_CATEGORY_COLORS,
        label_top_n=24,
        unit_name="edge",
    )
    return pack


def plot_schema_metagraph() -> pd.DataFrame:
    triples = pd.read_csv(LABELSET_TRIPLES).sort_values("edge_count", ascending=False).head(38).copy()
    endpoints = sorted(set(triples["source_labels_key"]) | set(triples["target_labels_key"]))
    incident = Counter()
    for row in triples.itertuples(index=False):
        incident[row.source_labels_key] += int(row.edge_count)
        incident[row.target_labels_key] += int(row.edge_count)

    graph = nx.DiGraph()
    for node in endpoints:
        graph.add_node(node, category=classify_node(node), incident=incident[node])
    for row in triples.itertuples(index=False):
        graph.add_edge(row.source_labels_key, row.target_labels_key, rel=row.relationship_type, weight=int(row.edge_count), rank=int(row.rank))

    anchors = {
        "Imaging-derived": (-0.42, 0.05),
        "Literature": (-0.58, 0.50),
        "Ontology": (0.46, 0.23),
        "Biomedical": (0.64, -0.30),
        "Data and methods": (-0.06, -0.52),
        "Review and governance": (0.52, -0.60),
        "Other": (0.0, 0.0),
    }
    initial = {}
    per_cat: dict[str, list[str]] = defaultdict(list)
    for node in endpoints:
        per_cat[classify_node(node)].append(node)
    for category, nodes in per_cat.items():
        ax0, ay0 = anchors.get(category, (0.0, 0.0))
        for idx, node in enumerate(sorted(nodes, key=lambda n: -incident[n])):
            angle = 2 * math.pi * idx / max(len(nodes), 1)
            radius = 0.10 + 0.035 * (idx % 3)
            initial[node] = (ax0 + radius * math.cos(angle), ay0 + radius * math.sin(angle))

    pos = nx.spring_layout(graph, pos=initial, seed=11, k=0.72, iterations=160, weight=None)
    sns.set_theme(style="white", context="paper", font_scale=1.0)
    fig, ax = plt.subplots(figsize=(15.5, 11.0))
    fig.patch.set_facecolor("#f8fbff")
    ax.set_facecolor("#f8fbff")

    max_edge = max(nx.get_edge_attributes(graph, "weight").values())
    for u, v, attrs in sorted(graph.edges(data=True), key=lambda item: item[2]["weight"]):
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        width = 0.7 + 7.4 * math.sqrt(attrs["weight"] / max_edge)
        color = EDGE_CATEGORY_COLORS.get(classify_edge(attrs["rel"]), "#95a3b3")
        rad = 0.13 if u != v else 0.24
        patch = FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>",
            mutation_scale=10 + width,
            linewidth=width,
            color=color,
            alpha=0.40,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=19,
            shrinkB=19,
            zorder=1,
        )
        ax.add_patch(patch)
        if attrs["rank"] <= 14:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(mx, my, attrs["rel"], fontsize=7.5, color="#364656", ha="center", va="center", bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.74), zorder=4)

    max_incident = max(incident.values())
    for node in sorted(graph.nodes(), key=lambda n: incident[n]):
        x, y = pos[node]
        category = graph.nodes[node]["category"]
        size = 520 + 2500 * math.sqrt(incident[node] / max_incident)
        ax.scatter([x], [y], s=size, c=[NODE_CATEGORY_COLORS.get(category, "#95a3b3")], edgecolors="white", linewidths=1.7, alpha=0.94, zorder=3)
        fontsize = 6.9 if incident[node] < 15_000 else 8.5
        ax.text(x, y, clean_schema_node_label(node), ha="center", va="center", fontsize=fontsize, color="#061018", weight="bold", zorder=5)

    node_handles = [
        plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=color, markeredgecolor="white", markersize=9, label=cat)
        for cat, color in NODE_CATEGORY_COLORS.items()
        if any(graph.nodes[n]["category"] == cat for n in graph.nodes())
    ]
    edge_handles = [
        plt.Line2D([0], [0], color=color, linewidth=4, alpha=0.55, label=cat)
        for cat, color in EDGE_CATEGORY_COLORS.items()
        if any(classify_edge(attrs["rel"]) == cat for _, _, attrs in graph.edges(data=True))
    ]
    leg1 = ax.legend(handles=node_handles, title="Node category", loc="upper left", bbox_to_anchor=(0.01, 0.99), frameon=False, fontsize=8.5, title_fontsize=9)
    ax.add_artist(leg1)
    ax.legend(handles=edge_handles, title="Edge category", loc="lower right", bbox_to_anchor=(0.99, 0.02), frameon=False, fontsize=8.5, title_fontsize=9)
    ax.set_title("Dominant BR-KG schema meta-graph", fontsize=22, weight="bold", pad=16)
    ax.text(0.5, -0.055, "Nodes are canonical label sets; directed edges are top schema triples by edge count. Width scales with log edge mass.", transform=ax.transAxes, ha="center", fontsize=10.5, color="#526272")
    ax.axis("off")
    save_figure("fig13_schema_meta_graph")

    out = []
    for node in graph.nodes:
        out.append({"labelset": node, "category": graph.nodes[node]["category"], "incident_edge_count_top38": int(incident[node]), "x": float(pos[node][0]), "y": float(pos[node][1])})
    positions = pd.DataFrame(out)
    positions.to_csv(DATA_DIR / "fig13_schema_meta_graph_node_positions.csv", index=False)
    return positions


def plot_edge_density_matrix() -> pd.DataFrame:
    labels = pd.read_csv(LABEL_COUNTS).head(18)["label"].tolist()
    triples = pd.read_csv(UNWOUND_TRIPLES)
    matrix = (
        triples[triples["source_label"].isin(labels) & triples["target_label"].isin(labels)]
        .pivot_table(index="source_label", columns="target_label", values="edge_count", aggfunc="sum", fill_value=0)
        .reindex(index=labels, columns=labels, fill_value=0)
    )
    matrix.to_csv(DATA_DIR / "fig14_edge_density_matrix_top_labels.csv")
    log_matrix = np.log10(matrix.astype(float) + 1.0)
    annot = matrix.astype(object).copy()
    for row in annot.index:
        for col in annot.columns:
            value = float(matrix.loc[row, col])
            annot.loc[row, col] = fmt_count(value) if value >= 1000 else ""

    sns.set_theme(style="white", context="paper", font_scale=0.9)
    fig, ax = plt.subplots(figsize=(13.5, 11.2))
    heat = sns.heatmap(
        log_matrix,
        ax=ax,
        cmap="viridis",
        linewidths=0.45,
        linecolor="#eef2f4",
        cbar_kws={"label": "log10(edge count + 1)", "shrink": 0.75},
        annot=annot,
        fmt="",
        annot_kws={"fontsize": 7},
    )
    ax.set_title("BR-KG edge density matrix", fontsize=21, weight="bold", pad=16)
    ax.set_xlabel("Target node label")
    ax.set_ylabel("Source node label")
    ax.tick_params(axis="x", rotation=55, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    heat.collections[0].colorbar.ax.tick_params(labelsize=8)
    fig.text(0.5, 0.02, "Top 18 node labels by count; cells are unwound source-label x target-label edge counts from prod schema export.", ha="center", fontsize=10, color="#526272")
    fig.subplots_adjust(bottom=0.22, left=0.16, right=0.92, top=0.89)
    save_figure("fig14_edge_density_matrix")
    return matrix.reset_index()


def make_sankey_flows() -> pd.DataFrame:
    if not SOURCE_PROBE.exists():
        return pd.DataFrame(columns=["source_group", "label", "count"])
    source_probe = json.loads(SOURCE_PROBE.read_text())
    rows = source_probe.get("source_values", [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["source_group", "label", "count"])
    frame["source_group"] = frame["source_value"].map(canonical_source)
    grouped = frame.groupby(["source_group", "label"], as_index=False)["count"].sum()
    top_sources = grouped.groupby("source_group")["count"].sum().sort_values(ascending=False).head(8).index
    grouped["source_group"] = grouped["source_group"].where(grouped["source_group"].isin(top_sources), "Other sources")
    top_labels = grouped.groupby("label")["count"].sum().sort_values(ascending=False).head(10).index
    grouped["target_label"] = grouped["label"].where(grouped["label"].isin(top_labels), "Other labels")
    grouped = grouped.groupby(["source_group", "target_label"], as_index=False)["count"].sum().rename(columns={"target_label": "label"})
    grouped = grouped[grouped["count"] > 0].sort_values("count", ascending=False)
    grouped.to_csv(DATA_DIR / "fig15_source_provenance_sankey_flows.csv", index=False)
    return grouped


def draw_sankey_band(ax: plt.Axes, x0: float, y0a: float, y0b: float, x1: float, y1a: float, y1b: float, color: str, alpha: float = 0.42) -> None:
    verts = [
        (x0, y0a),
        ((x0 + x1) / 2, y0a),
        ((x0 + x1) / 2, y1a),
        (x1, y1a),
        (x1, y1b),
        ((x0 + x1) / 2, y1b),
        ((x0 + x1) / 2, y0b),
        (x0, y0b),
        (x0, y0a),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none", alpha=alpha))


def plot_source_provenance_sankey() -> pd.DataFrame:
    flows = make_sankey_flows()
    if flows.empty:
        return flows
    source_totals = flows.groupby("source_group")["count"].sum().sort_values(ascending=False)
    target_totals = flows.groupby("label")["count"].sum().sort_values(ascending=False)
    sources = source_totals.index.tolist()
    targets = target_totals.index.tolist()
    flows_plot = flows.copy()

    def intervals(items: list[str], totals: pd.Series) -> dict[str, tuple[float, float]]:
        y = 0.94
        out = {}
        gap = 0.014
        available = 0.84 - gap * (len(items) - 1)
        denom = max(float(totals.reindex(items).fillna(0).sum()), 1.0)
        for item in items:
            h = available * float(totals.get(item, 0.0)) / denom
            out[item] = (y - h, y)
            y -= h + gap
        return out

    source_intervals = intervals(sources, flows_plot.groupby("source_group")["count"].sum())
    target_intervals = intervals(targets, flows_plot.groupby("label")["count"].sum())

    def adjusted_label_positions(items: list[str], item_intervals: dict[str, tuple[float, float]], *, min_sep: float) -> dict[str, float]:
        raw = {item: (item_intervals[item][0] + item_intervals[item][1]) / 2 for item in items}
        adjusted = {}
        previous = 1.0
        for item in items:
            y = min(raw[item], previous - min_sep)
            adjusted[item] = y
            previous = y
        min_y = min(adjusted.values())
        if min_y < 0.055:
            shift = 0.055 - min_y
            adjusted = {item: min(0.955, y + shift) for item, y in adjusted.items()}
        return adjusted

    source_label_y = adjusted_label_positions(sources, source_intervals, min_sep=0.034)
    target_label_y = adjusted_label_positions(targets, target_intervals, min_sep=0.038)
    source_cursor = {key: value[0] for key, value in source_intervals.items()}
    target_cursor = {key: value[0] for key, value in target_intervals.items()}
    source_height = {key: value[1] - value[0] for key, value in source_intervals.items()}
    target_height = {key: value[1] - value[0] for key, value in target_intervals.items()}
    source_total_plot = flows_plot.groupby("source_group")["count"].sum().to_dict()
    target_total_plot = flows_plot.groupby("label")["count"].sum().to_dict()

    sns.set_theme(style="white", context="paper", font_scale=1.0)
    fig, ax = plt.subplots(figsize=(14.0, 10.4))
    fig.patch.set_facecolor("#f8fbff")
    ax.set_facecolor("#f8fbff")

    for _, row in flows_plot.sort_values(["source_group", "count"], ascending=[True, False]).iterrows():
        src = row["source_group"]
        dst = row["label"]
        count = float(row["count"])
        sh = source_height[src] * count / max(source_total_plot.get(src, 1), 1)
        th = target_height[dst] * count / max(target_total_plot.get(dst, 1), 1)
        sy0, sy1 = source_cursor[src], source_cursor[src] + sh
        ty0, ty1 = target_cursor[dst], target_cursor[dst] + th
        source_cursor[src] += sh
        target_cursor[dst] += th
        draw_sankey_band(ax, 0.20, sy0, sy1, 0.78, ty0, ty1, SOURCE_COLORS.get(src, SOURCE_COLORS["Other"]), alpha=0.38)

    for src in sources:
        y0, y1 = source_intervals[src]
        color = SOURCE_COLORS.get(src, SOURCE_COLORS["Other"])
        ax.add_patch(Rectangle((0.075, y0), 0.11, y1 - y0, color=color, alpha=0.92, ec="white", lw=0.6))
        compact = (y1 - y0) < 0.024
        label = f"{clean_label(src, 18)} {fmt_count(source_total_plot.get(src, 0))}" if compact else f"{src}\n{fmt_count(source_total_plot.get(src, 0))}"
        ax.text(0.067, source_label_y[src], label, ha="right", va="center", fontsize=7.6 if compact else 8.6, color="#263645")
    for dst in targets:
        y0, y1 = target_intervals[dst]
        ax.add_patch(Rectangle((0.795, y0), 0.12, y1 - y0, color="#263645", alpha=0.82, ec="white", lw=0.6))
        compact = (y1 - y0) < 0.024
        label = f"{clean_label(dst, 18)} {fmt_count(target_total_plot.get(dst, 0))}" if compact else f"{clean_label(dst, 20)}\n{fmt_count(target_total_plot.get(dst, 0))}"
        ax.text(0.925, target_label_y[dst], label, ha="left", va="center", fontsize=7.4 if compact else 8.3, color="#263645")

    ax.text(0.13, 0.985, "Upstream source", ha="center", va="bottom", fontsize=12, weight="bold")
    ax.text(0.855, 0.985, "Node label", ha="center", va="bottom", fontsize=12, weight="bold")
    ax.set_title("BR-KG source provenance Sankey", fontsize=22, weight="bold", pad=18)
    ax.text(0.5, 0.025, "Flows use measured node `source`/`provenance`/`data_origin`-like properties from prod; small flows are grouped into Other.", ha="center", fontsize=10.5, color="#526272")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    save_figure("fig15_source_provenance_sankey")
    return flows


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    node_pack = plot_node_circle_pack()
    edge_pack = plot_edge_circle_pack()
    meta_positions = plot_schema_metagraph()
    matrix = plot_edge_density_matrix()
    sankey_flows = plot_source_provenance_sankey()
    summary = {
        "node_circle_pack_rows": int(len(node_pack)),
        "edge_circle_pack_rows": int(len(edge_pack)),
        "schema_metagraph_nodes": int(len(meta_positions)),
        "edge_density_matrix_rows": int(len(matrix)),
        "sankey_flow_rows": int(len(sankey_flows)),
        "figures": [
            "figures/fig11_node_circle_pack.png",
            "figures/fig12_edge_circle_pack.png",
            "figures/fig13_schema_meta_graph.png",
            "figures/fig14_edge_density_matrix.png",
            "figures/fig15_source_provenance_sankey.png",
        ],
    }
    OVERVIEW_DATA.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
