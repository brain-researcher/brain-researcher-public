#!/usr/bin/env python3
"""Draw instance-level BR-KG example galleries from bounded prod probes."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"

PATH_PROBE = DATA_DIR / "brkg_instance_path_probe.json"
DATASET_PROBE = DATA_DIR / "brkg_instance_dataset_probe.json"
TASK_PROBE = DATA_DIR / "brkg_instance_task_probe.json"
MULTIHOP_PROBE = DATA_DIR / "brkg_instance_multihop_probe.json"
ALT_MULTIHOP_PROBE = DATA_DIR / "brkg_instance_multihop_alt_probe.json"
POLDRACK_PROBE = DATA_DIR / "brkg_poldrack_publication_probe.json"
GALLERY_DATA = DATA_DIR / "brkg_instance_gallery_examples.json"


TYPE_COLORS = {
    "Publication": "#4C78A8",
    "Author": "#72B7B2",
    "Coordinate": "#14A085",
    "StatsMap": "#14A085",
    "StatisticalMap": "#14A085",
    "BrainRegion": "#59A14F",
    "TemplateSpace": "#59A14F",
    "Collection": "#1BA99A",
    "Term": "#8E63B7",
    "Concept": "#8E63B7",
    "Task": "#D99000",
    "Contrast": "#E5AE38",
    "Dataset": "#D99000",
    "Repository": "#C89B3C",
    "Modality": "#E5AE38",
    "DataResource": "#D65F5F",
    "ModelSpec": "#D65F5F",
    "TaskAnalysis": "#D65F5F",
    "Tool": "#D65F5F",
    "ToolVersion": "#E88888",
    "ToolFamily": "#D99000",
    "Property": "#7F8B99",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def first(value: list[Any], fallback: Any = None) -> Any:
    return value[0] if value else fallback


def prop(row: dict[str, Any] | None, *keys: str, default: str = "") -> str:
    row = row or {}
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return default


def trim(text: str, max_len: int = 44) -> str:
    text = " ".join(str(text).replace("\n", " ").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def node(node_id: str, label: str, node_type: str, *, note: str = "", property_node: bool = False) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": trim(label, 52),
        "type": node_type,
        "note": trim(note, 56),
        "property_node": property_node,
    }


def edge(source: str, target: str, label: str, *, property_edge: bool = False) -> dict[str, Any]:
    return {"source": source, "target": target, "label": label, "property_edge": property_edge}


def dataset_size_note(item: dict[str, Any] | None) -> str:
    subjects = prop(item, "subjects_count")
    sessions = prop(item, "sessions_count")
    parts = []
    if subjects:
        parts.append(f"{subjects} subject" if subjects == "1" else f"{subjects} subjects")
    if sessions:
        parts.append(f"{sessions} session" if sessions == "1" else f"{sessions} sessions")
    return "; ".join(parts)


def select_multihop_example(default_rows: list[dict[str, Any]]) -> dict[str, Any]:
    alt_rows = load_optional_json(ALT_MULTIHOP_PROBE).get("dataset_task_concept_distinct", [])
    for row in alt_rows:
        dataset_name = prop(row.get("dataset"), "name")
        task_name = prop(row.get("task"), "name")
        concept_name = prop(row.get("concept"), "name", "label")
        modality_name = prop(row.get("modality"), "name")
        if (
            dataset_name == "Myconnectome"
            and task_name == "n-back task"
            and concept_name == "updating"
            and modality_name == "fMRI"
        ):
            return row
    return first(alt_rows, first(default_rows, {}))


def build_examples() -> dict[str, Any]:
    paths = load_json(PATH_PROBE)
    datasets = load_json(DATASET_PROBE)
    tasks = load_json(TASK_PROBE)
    multihop = load_json(MULTIHOP_PROBE)

    poldrack_rows = load_optional_json(POLDRACK_PROBE).get("publication_poldrack_property", [])
    pub_row = next(
        (
            row
            for row in poldrack_rows
            if prop(row.get("p"), "authors").lower().startswith("poldrack")
            and len(row.get("coords", [])) >= 2
            and len(row.get("terms", [])) >= 1
        ),
        paths["publication_rich"][0],
    )
    pub = pub_row["p"]
    coords = pub_row["coords"]
    terms = pub_row["terms"]
    author_node = first(pub_row.get("authors", []), {})
    author_label = prop(author_node, "name", default="")
    author_note = "scholarly metadata"
    author_edge_label = "AUTHORED_BY"
    author_property_edge = False
    if prop(pub, "authors").lower().find("poldrack") >= 0:
        author_label = "Russell Poldrack"
        author_note = "authors field: Poldrack RA"
        author_edge_label = "AUTHORS_FIELD"
        author_property_edge = True

    stat_row = paths["statsmap_rich"][0]
    stat = stat_row["s"]
    stat_regions = stat_row["regions"]
    stat_model = first(stat_row["models"], {})
    stat_resource = first(stat_row["resources"], {})
    stat_contrast = stat_row["contrast"]

    nv_row = paths["statisticalmap_rich"][0]
    nv_map = nv_row["m"]
    nv_collection = nv_row["collection"]
    nv_concept = first(nv_row["concepts"], {})

    task_row = tasks["task_connected"][1]
    task = task_row["task"]
    task_concepts = task_row["concepts"]
    task_contrasts = task_row["contrasts"]

    dataset_row = datasets["dataset_connected"][0]
    dataset = dataset_row["d"]
    dataset_repo = first(dataset_row["repos"], {})
    dataset_modality = first(dataset_row["modalities"], {})
    dataset_task = first(dataset_row["tasks"], {})

    tool_row = paths["tool_rich"][2]
    tool = tool_row["tool"]
    tool_version = first(tool_row["versions"], {})
    tool_family = first(tool_row["families"], {})
    tool_modality = first(tool_row["modalities"], {})

    mh = select_multihop_example(multihop["dataset_task_concept"])
    mh_dataset = mh["dataset"]
    mh_repo = mh["repo"]
    mh_modality = mh["modality"]
    mh_task = mh["task"]
    mh_concept = mh["concept"]

    examples = [
        {
            "id": "literature_peak",
            "title": "Literature peak",
            "message": "A paper anchors coordinates, terms, and authors.",
            "center": "pub",
            "nodes": [
                node("pub", prop(pub, "title"), "Publication", note=f"{prop(pub, 'journal')} {prop(pub, 'publication_year')}"),
                node("coord1", f"MNI ({prop(coords[0], 'x')}, {prop(coords[0], 'y')}, {prop(coords[0], 'z')})", "Coordinate", note=prop(coords[0], "source")),
                node("coord2", f"MNI ({prop(coords[1], 'x')}, {prop(coords[1], 'y')}, {prop(coords[1], 'z')})", "Coordinate", note=prop(coords[1], "source")),
                node("term", prop(first(terms), "name"), "Term", note="Neurosynth term"),
                node("author", author_label, "Author", note=author_note),
            ],
            "edges": [
                edge("pub", "coord1", "HAS_COORDINATE"),
                edge("pub", "coord2", "HAS_COORDINATE"),
                edge("pub", "term", "HAS_TERM"),
                edge("pub", "author", author_edge_label, property_edge=author_property_edge),
            ],
        },
        {
            "id": "saved_statmap",
            "title": "Saved statistical map",
            "message": "OpenNeuro-derived map links analysis, file, contrast, and regions.",
            "center": "statmap",
            "nodes": [
                node("statmap", f"{prop(stat, 'contrast')} {prop(stat, 'stat_type')}-map", "StatsMap", note=f"{prop(stat, 'dataset_folder')} / subj {prop(stat, 'subject')}"),
                node("contrast", prop(stat_contrast, "name"), "Contrast", note=prop(stat_contrast, "task")),
                node("file", prop(stat_resource, "name"), "DataResource", note=f"{prop(stat_resource, 'format')} / {prop(stat_resource, 'source')}"),
                node("region", prop(first(stat_regions), "name"), "BrainRegion", note=prop(first(stat_regions), "space")),
                node("model", f"GLM: {prop(stat_model, 'hrf_model', default='unknown')}", "ModelSpec", note=prop(stat_model, "model_name")),
            ],
            "edges": [
                edge("statmap", "contrast", "DERIVED_FROM"),
                edge("statmap", "file", "HAS_RESOURCE"),
                edge("statmap", "region", "IN_REGION"),
                edge("statmap", "model", "COMPUTED_WITH"),
            ],
        },
        {
            "id": "neurovault_asset",
            "title": "NeuroVault map asset",
            "message": "A map node preserves collection, ontology, and downloadable surface/file anchors.",
            "center": "map",
            "nodes": [
                node("map", prop(nv_map, "name", "id"), "StatisticalMap", note=f"NeuroVault image {prop(nv_map, 'id')}"),
                node("collection", prop(nv_collection, "name"), "Collection", note=f"collection {prop(nv_collection, 'id')}"),
                node("concept", prop(nv_concept, "name", "label"), "Concept", note=prop(nv_concept, "source")),
                node("surface", "surface_left_file", "Property", note=prop(nv_map, "surface_left_file"), property_node=True),
                node("url", "image URL", "Property", note=prop(nv_map, "url"), property_node=True),
            ],
            "edges": [
                edge("map", "collection", "BELONGS_TO"),
                edge("map", "concept", "IN_ONVOC"),
                edge("map", "surface", "surface_left_file", property_edge=True),
                edge("map", "url", "url", property_edge=True),
            ],
        },
        {
            "id": "task_construct",
            "title": "Task to construct",
            "message": "Task definitions connect to measured constructs and contrast definitions.",
            "center": "task",
            "nodes": [
                node("task", prop(task, "name"), "Task", note=prop(task, "id")),
                node("concept1", prop(first(task_concepts), "name"), "Concept", note="measured construct"),
                node("concept2", prop(task_concepts[1] if len(task_concepts) > 1 else {}, "name"), "Concept", note="measured construct"),
                node("contrast1", prop(first(task_contrasts), "name"), "Contrast", note="contrast"),
                node("contrast2", prop(task_contrasts[1] if len(task_contrasts) > 1 else {}, "name"), "Contrast", note="contrast"),
            ],
            "edges": [
                edge("task", "concept1", "MEASURES"),
                edge("task", "concept2", "MEASURES"),
                edge("task", "contrast1", "HAS_CONTRAST"),
                edge("task", "contrast2", "HAS_CONTRAST"),
            ],
        },
        {
            "id": "dataset_coverage",
            "title": "Dataset coverage",
            "message": "Dataset metadata links repository, modality, and task inventory.",
            "center": "dataset",
            "nodes": [
                node("dataset", prop(dataset, "name"), "Dataset", note=dataset_size_note(dataset)),
                node("repo", prop(dataset_repo, "name", "id"), "Repository", note="HOSTED_AT"),
                node("modality", prop(dataset_modality, "name", "id"), "Modality", note="HAS_MODALITY"),
                node("task", prop(dataset_task, "name", "id"), "Task", note="HAS_TASK"),
                node("source", prop(dataset, "source_repo_bucket", default="OpenNeuro"), "Property", note=prop(dataset, "id"), property_node=True),
            ],
            "edges": [
                edge("dataset", "repo", "HOSTED_AT"),
                edge("dataset", "modality", "HAS_MODALITY"),
                edge("dataset", "task", "HAS_TASK"),
                edge("dataset", "source", "source_repo", property_edge=True),
            ],
        },
        {
            "id": "tool_contract",
            "title": "Tool / workflow contract",
            "message": "Tool nodes expose runtime family, modality support, and version anchors.",
            "center": "tool",
            "nodes": [
                node("tool", prop(tool, "display_name", "name"), "Tool", note=prop(tool, "software")),
                node("version", prop(tool_version, "version", "id"), "ToolVersion", note=prop(tool_version, "id")),
                node("family", prop(tool_family, "name", "id"), "ToolFamily", note="analysis family"),
                node("modality", prop(tool_modality, "name", "id"), "Modality", note="supported modality"),
                node("source", prop(tool, "source"), "Property", note="tool registry source", property_node=True),
            ],
            "edges": [
                edge("tool", "version", "HAS_VERSION"),
                edge("tool", "family", "IMPLEMENTS_FAMILY"),
                edge("tool", "modality", "SUPPORTS_MODALITY"),
                edge("tool", "source", "source_file", property_edge=True),
            ],
        },
    ]

    multihop_path = {
        "id": "dataset_task_construct_path",
        "title": "Example multi-hop query path",
        "message": "Traversal turns dataset metadata into a scientific construct path.",
        "nodes": [
            node("repo", prop(mh_repo, "name", "id"), "Repository", note="source catalogue"),
            node("dataset", prop(mh_dataset, "name"), "Dataset", note=dataset_size_note(mh_dataset)),
            node("modality", prop(mh_modality, "name", "id"), "Modality", note="data type"),
            node("task", prop(mh_task, "name"), "Task", note=prop(mh_task, "family_label", default=prop(mh_task, "id"))),
            node("concept", prop(mh_concept, "name"), "Concept", note="scientific construct"),
        ],
        "edges": [
            edge("dataset", "repo", "HOSTED_AT"),
            edge("dataset", "modality", "HAS_MODALITY"),
            edge("dataset", "task", "HAS_TASK"),
            edge("task", "concept", "MEASURES"),
        ],
    }
    return {"examples": examples, "multihop_path": multihop_path}


def wrap_label(text: str, width: int = 20, lines: int = 3) -> str:
    display = trim(text, width * lines)
    if "_" in display and len(display) > width:
        display = display.replace("_", " ")
    chunks = textwrap.wrap(display, width=width, break_long_words=False)
    return "\n".join(chunks[:lines])


def node_position(index: int) -> tuple[float, float]:
    positions = {
        0: (0.50, 0.52),
        1: (0.20, 0.72),
        2: (0.80, 0.72),
        3: (0.20, 0.25),
        4: (0.80, 0.25),
    }
    return positions[index]


def draw_node(ax: plt.Axes, x: float, y: float, item: dict[str, Any], *, scale: float = 1.0) -> None:
    color = TYPE_COLORS.get(item["type"], "#95a3b3")
    radius = 0.087 * scale if item["id"] != "pub" else 0.095 * scale
    size = 3650 * scale * scale
    if item.get("property_node"):
        ax.scatter([x], [y], s=size * 1.18, facecolors="#FFFFFF", edgecolors="#A9B4C1", linewidths=1.8, alpha=1.0, zorder=5)
        ax.scatter([x], [y], s=size * 0.90, facecolors="#EEF2F6", edgecolors=color, linewidths=1.0, alpha=1.0, zorder=6)
    else:
        ax.scatter([x], [y], s=size * 2.65, color=color, alpha=0.12, linewidths=0, zorder=3)
        ax.scatter([x], [y], s=size * 1.18, color="#FFFFFF", edgecolors=color, linewidths=2.2, alpha=1.0, zorder=5)
        ax.scatter([x], [y], s=size * 0.86, color=color, edgecolors="#FFFFFF", linewidths=1.0, alpha=0.96, zorder=6)
    ax.text(
        x,
        y + radius + 0.025,
        item["type"],
        ha="center",
        va="bottom",
        fontsize=6.2,
        color="#536273",
        weight="bold",
        zorder=8,
    )
    ax.text(
        x,
        y,
        wrap_label(item["label"], width=16, lines=3),
        ha="center",
        va="center",
        fontsize=6.7,
        color="#101820",
        weight="bold",
        zorder=8,
    )
    if item.get("note"):
        ax.text(
            x,
            y - radius - 0.030,
            wrap_label(item["note"], width=22, lines=2),
            ha="center",
            va="top",
            fontsize=5.6,
            color="#667789",
            zorder=8,
        )


def draw_edge(
    ax: plt.Axes,
    p1: tuple[float, float],
    p2: tuple[float, float],
    label: str,
    *,
    color: str = "#7fb9ff",
    dashed: bool = False,
    label_offset: tuple[float, float] = (0.0, 0.0),
) -> None:
    arrow = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="-|>",
        mutation_scale=10,
        linewidth=1.35,
        color=color,
        alpha=0.88 if not dashed else 0.62,
        linestyle=(0, (3, 3)) if dashed else "solid",
        connectionstyle="arc3,rad=0.06",
        shrinkA=34,
        shrinkB=34,
        zorder=2,
    )
    ax.add_patch(arrow)
    mx = (p1[0] + p2[0]) / 2 + label_offset[0]
    my = (p1[1] + p2[1]) / 2 + label_offset[1]
    ax.text(
        mx,
        my,
        label.lower(),
        ha="center",
        va="center",
        fontsize=5.7,
        color="#27313C",
        bbox={"boxstyle": "round,pad=0.15", "fc": "#FFFFFF", "ec": "#D7DFE8", "lw": 0.55, "alpha": 0.94},
        zorder=7,
    )


def draw_tile(ax: plt.Axes, example: dict[str, Any], panel_label: str) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor("#FFFFFF")
    ax.add_patch(Rectangle((0.018, 0.018), 0.964, 0.964, facecolor="#FFFFFF", edgecolor="#C9D3DE", linewidth=1.0, zorder=0))
    ax.add_patch(Rectangle((0.018, 0.895), 0.964, 0.087, facecolor="#F1F6FA", edgecolor="none", zorder=1))
    ax.text(0.040, 0.955, panel_label, ha="left", va="center", color="#23527C", fontsize=10, weight="bold")
    ax.text(0.095, 0.956, example["title"], ha="left", va="center", color="#1C2733", fontsize=9.7, weight="bold")
    ax.text(0.095, 0.914, example["message"], ha="left", va="center", color="#5C6B7A", fontsize=6.6)

    positions = {item["id"]: node_position(idx) for idx, item in enumerate(example["nodes"])}
    type_by_id = {item["id"]: item["type"] for item in example["nodes"]}
    for item in example["edges"]:
        src, dst = item["source"], item["target"]
        color = TYPE_COLORS.get(type_by_id.get(dst), "#7fb9ff")
        draw_edge(ax, positions[src], positions[dst], item["label"], color=color, dashed=item.get("property_edge", False))
    for idx, item in enumerate(example["nodes"]):
        draw_node(ax, *node_position(idx), item, scale=1.0 if idx else 1.1)


def draw_split_examples(payload: dict[str, Any]) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for idx, example in enumerate(payload["examples"]):
        panel = chr(ord("a") + idx)
        fig, ax = plt.subplots(figsize=(6.2, 4.7))
        fig.patch.set_facecolor("#FFFFFF")
        draw_tile(ax, example, panel)
        fig.subplots_adjust(left=0.02, right=0.98, top=0.985, bottom=0.02)
        stem = f"fig16{panel}_brkg_{example['id']}"
        for ext, kwargs in {
            "png": {"dpi": 300, "bbox_inches": "tight", "pad_inches": 0.04},
            "svg": {"bbox_inches": "tight", "pad_inches": 0.04},
        }.items():
            out = FIG_DIR / f"{stem}.{ext}"
            fig.savefig(out, **kwargs)
            outputs.append(str(out.relative_to(HERE)))
        plt.close(fig)
    return outputs


def draw_multihop(payload: dict[str, Any]) -> None:
    item = payload["multihop_path"]
    nodes = item["nodes"]
    edges = item["edges"]
    order = ["repo", "dataset", "modality", "task", "concept"]
    positions = {
        "repo": (0.17, 0.62),
        "dataset": (0.40, 0.62),
        "modality": (0.40, 0.28),
        "task": (0.64, 0.62),
        "concept": (0.87, 0.62),
    }
    node_map = {n["id"]: n for n in nodes}
    fig, ax = plt.subplots(figsize=(6.2, 4.7))
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0.018, 0.018), 0.964, 0.964, facecolor="#FFFFFF", edgecolor="#C9D3DE", linewidth=1.0, zorder=0))
    ax.add_patch(Rectangle((0.018, 0.895), 0.964, 0.087, facecolor="#F1F6FA", edgecolor="none", zorder=1))
    ax.text(0.040, 0.955, "g", ha="left", va="center", color="#23527C", fontsize=10, weight="bold")
    ax.text(0.095, 0.956, "Multi-hop query path", ha="left", va="center", color="#1C2733", fontsize=9.7, weight="bold")
    ax.text(0.095, 0.914, item["message"], ha="left", va="center", color="#5C6B7A", fontsize=6.6)
    label_offsets = {
        "HOSTED_AT": (0.0, 0.045),
        "HAS_TASK": (0.0, 0.045),
        "MEASURES": (0.0, 0.045),
    }
    for relation in edges:
        src, dst = relation["source"], relation["target"]
        draw_edge(
            ax,
            positions[src],
            positions[dst],
            relation["label"],
            color=TYPE_COLORS.get(node_map[dst]["type"], "#7fb9ff"),
            label_offset=label_offsets.get(relation["label"], (0.0, 0.0)),
        )
    for node_id in order:
        draw_node(ax, *positions[node_id], node_map[node_id], scale=0.58)
    ax.text(
        0.5,
        0.095,
        "Example path: OpenNeuro -> Myconnectome -> n-back task -> updating.",
        ha="center",
        color="#667789",
        fontsize=6.4,
    )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.985, bottom=0.02)
    fig.savefig(FIG_DIR / "fig17_brkg_multihop_query_path.png", dpi=300, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(FIG_DIR / "fig17_brkg_multihop_query_path.svg", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_examples()
    GALLERY_DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for stale in ("fig16_brkg_instance_gallery.png", "fig16_brkg_instance_gallery.svg"):
        stale_path = FIG_DIR / stale
        if stale_path.exists():
            stale_path.unlink()
    outputs = draw_split_examples(payload)
    draw_multihop(payload)
    print(
        json.dumps(
            {
                "examples": len(payload["examples"]),
                "figures": outputs + ["figures/fig17_brkg_multihop_query_path.png", "figures/fig17_brkg_multihop_query_path.svg"],
                "data": str(GALLERY_DATA.relative_to(HERE)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
