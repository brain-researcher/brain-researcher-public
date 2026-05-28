#!/usr/bin/env python3
"""Create comprehensive NeuroKG schema inventory tables.

The raw graph has millions of edges. These tables summarize the full prod
schema-triple export without dropping any canonical schema triples:

- canonical schema triples: one row per source-label-set / relationship /
  target-label-set triple
- label-set nodes: one row per canonical label set appearing in triples
- node labels: one row per Neo4j node label
- relationship types: one row per relationship type
- source-target surfaces: one row per source-label-set / target-label-set block
"""

from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
TABLE_DIR = HERE / "tables"

LABELSETS_PATH = DATA_DIR / "kg_schema_triples_full_labelsets.csv"
UNWOUND_PATH = DATA_DIR / "kg_schema_triples_full_unwound_labels.csv"
LABEL_COUNTS_PATH = DATA_DIR / "kg_schema_triples_full_label_counts.csv"
REL_COUNTS_PATH = DATA_DIR / "kg_schema_triples_full_relationship_counts.csv"

TRIPLES_CSV = TABLE_DIR / "neurokg_schema_triples_comprehensive.csv"
LABELSETS_CSV = TABLE_DIR / "neurokg_labelset_nodes_inventory.csv"
NODE_LABELS_CSV = TABLE_DIR / "neurokg_node_labels_inventory.csv"
RELATIONSHIPS_CSV = TABLE_DIR / "neurokg_relationship_types_inventory.csv"
SOURCE_TARGET_CSV = TABLE_DIR / "neurokg_source_target_surfaces.csv"
DATA_DICTIONARY_MD = TABLE_DIR / "neurokg_schema_inventory_data_dictionary.md"
HTML_PATH = TABLE_DIR / "neurokg_schema_inventory.html"
XLSX_PATH = TABLE_DIR / "neurokg_schema_inventory.xlsx"
SUMMARY_JSON = TABLE_DIR / "neurokg_schema_inventory_summary.json"


SURFACE_ORDER = [
    "Statistical maps",
    "Publication evidence",
    "Spatial anatomy",
    "Task and behavior",
    "Ontology and terms",
    "Tools and resources",
    "Analysis methods",
    "Review and governance",
    "Other schema",
]

SURFACE_COLORS = {
    "Statistical maps": "#20d3b3",
    "Publication evidence": "#4ea5ff",
    "Spatial anatomy": "#b8f34d",
    "Task and behavior": "#ffb000",
    "Ontology and terms": "#c77dff",
    "Tools and resources": "#ff6b6b",
    "Analysis methods": "#ff7ad9",
    "Review and governance": "#9ea7ff",
    "Other schema": "#95a3b3",
}


def _contains(label_key: str, *tokens: str) -> bool:
    lowered = label_key.lower()
    return any(token.lower() in lowered for token in tokens)


def classify_surface(label_key: str) -> str:
    if _contains(label_key, "StatsMap", "StatisticalMap", "Collection", "StatMap"):
        return "Statistical maps"
    if _contains(label_key, "Publication", "Citation", "Embedding", "Author", "Institution"):
        return "Publication evidence"
    if _contains(label_key, "BrainRegion", "Coordinate", "TemplateSpace", "Atlas", "Parcellation", "Parcel", "Region"):
        return "Spatial anatomy"
    if _contains(label_key, "Task", "Subject", "Phenotype", "Condition", "Contrast", "Experiment", "Battery"):
        return "Task and behavior"
    if _contains(label_key, "Concept", "Term", "Ontology", "Onvoc", "Process", "Finding", "Species"):
        return "Ontology and terms"
    if _contains(label_key, "Tool", "DataResource", "OpenNeuro", "Dataset", "Modality", "Repository", "Consortium"):
        return "Tools and resources"
    if _contains(label_key, "ModelSpec", "TaskAnalysis", "GLM", "Run", "ExecutionFailure", "ResultSummary"):
        return "Analysis methods"
    if _contains(label_key, "Review", "Policy", "Validity", "Rule", "Calibration", "Severity"):
        return "Review and governance"
    return "Other schema"


def split_labelset(label_key: str) -> list[str]:
    return [part for part in str(label_key).split("|") if part]


def compact_join(values: list[Any], *, limit: int = 8) -> str:
    clean = [str(value) for value in values if str(value)]
    if len(clean) <= limit:
        return "; ".join(clean)
    return "; ".join(clean[:limit]) + f"; ... (+{len(clean) - limit})"


def fmt_count(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:.0f}"


def label_count_string(label_key: str, label_counts: dict[str, int]) -> str:
    return "; ".join(f"{label}={label_counts.get(label, 0):,}" for label in split_labelset(label_key))


def top_counter_string(counter: Counter[str], *, limit: int = 6) -> str:
    return "; ".join(f"{key}={value:,}" for key, value in counter.most_common(limit))


def build_tables() -> dict[str, pd.DataFrame]:
    labelsets = pd.read_csv(LABELSETS_PATH).sort_values("rank").reset_index(drop=True)
    unwound = pd.read_csv(UNWOUND_PATH).sort_values("rank").reset_index(drop=True)
    label_counts = pd.read_csv(LABEL_COUNTS_PATH).sort_values("node_count", ascending=False)
    rel_counts = pd.read_csv(REL_COUNTS_PATH).sort_values("edge_count", ascending=False)

    total_edges = int(labelsets["edge_count"].sum())
    label_count_map = dict(zip(label_counts["label"], label_counts["node_count"]))
    rel_count_map = dict(zip(rel_counts["relationship_type"], rel_counts["edge_count"]))
    labelset_ids = sorted(set(labelsets["source_labels_key"]) | set(labelsets["target_labels_key"]))
    labelset_id_map = {labelset_id: f"labelset_{idx:03d}" for idx, labelset_id in enumerate(labelset_ids, start=1)}
    relationship_id_map = {
        str(row.relationship_type): f"relationship_{idx:03d}"
        for idx, row in enumerate(rel_counts.itertuples(index=False), start=1)
    }

    schema = labelsets.copy()
    schema["schema_triple_id"] = schema["rank"].map(lambda value: f"schema_triple_{int(value):03d}")
    schema["data_source"] = "prod_neurokg_neo4j_schema_export"
    schema["export_source_file"] = str(LABELSETS_PATH.relative_to(HERE))
    schema["source_labelset_id"] = schema["source_labels_key"].map(labelset_id_map)
    schema["source_node_type"] = schema["source_labels_key"]
    schema["source_role"] = "source"
    schema["target_node_type"] = schema["target_labels_key"]
    schema["target_labelset_id"] = schema["target_labels_key"].map(labelset_id_map)
    schema["target_role"] = "target"
    schema["source_surface"] = schema["source_labels_key"].map(classify_surface)
    schema["target_surface"] = schema["target_labels_key"].map(classify_surface)
    schema["source_component_labels"] = schema["source_labels_key"].map(lambda value: "; ".join(split_labelset(value)))
    schema["target_component_labels"] = schema["target_labels_key"].map(lambda value: "; ".join(split_labelset(value)))
    schema["source_component_node_counts"] = schema["source_labels_key"].map(lambda value: label_count_string(value, label_count_map))
    schema["target_component_node_counts"] = schema["target_labels_key"].map(lambda value: label_count_string(value, label_count_map))
    schema["relationship_type_id"] = schema["relationship_type"].map(relationship_id_map)
    schema["relationship_edge_count_total"] = schema["relationship_type"].map(rel_count_map).astype(int)
    schema["schema_triple_share_of_relationship"] = schema["edge_count"] / schema["relationship_edge_count_total"]
    schema["schema_triple_share_of_graph"] = schema["edge_count"] / total_edges
    schema["source_target_pair"] = schema["source_labels_key"] + " -> " + schema["target_labels_key"]
    schema["source_target_surface_pair"] = schema["source_surface"] + " -> " + schema["target_surface"]
    schema["is_multilabel_source"] = schema["source_label_count"] > 1
    schema["is_multilabel_target"] = schema["target_label_count"] > 1
    schema["canonical_counting_note"] = "canonical label-set triple; edge count preserves full graph edge cardinality"
    schema = schema[
        [
            "schema_triple_id",
            "rank",
            "data_source",
            "export_source_file",
            "schema_triple",
            "source_labelset_id",
            "source_node_type",
            "source_role",
            "source_surface",
            "source_label_count",
            "source_component_labels",
            "source_component_node_counts",
            "relationship_type_id",
            "relationship_type",
            "relationship_edge_count_total",
            "target_labelset_id",
            "target_node_type",
            "target_role",
            "target_surface",
            "target_label_count",
            "target_component_labels",
            "target_component_node_counts",
            "edge_count",
            "edge_share",
            "schema_triple_share_of_graph",
            "schema_triple_share_of_relationship",
            "source_target_pair",
            "source_target_surface_pair",
            "is_multilabel_source",
            "is_multilabel_target",
            "canonical_counting_note",
        ]
    ]

    outgoing = labelsets.groupby("source_labels_key")["edge_count"].sum().to_dict()
    incoming = labelsets.groupby("target_labels_key")["edge_count"].sum().to_dict()
    out_triple_count = labelsets.groupby("source_labels_key").size().to_dict()
    in_triple_count = labelsets.groupby("target_labels_key").size().to_dict()
    out_rel_counter: dict[str, Counter[str]] = defaultdict(Counter)
    in_rel_counter: dict[str, Counter[str]] = defaultdict(Counter)
    target_counter: dict[str, Counter[str]] = defaultdict(Counter)
    source_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for row in labelsets.itertuples(index=False):
        out_rel_counter[row.source_labels_key][row.relationship_type] += int(row.edge_count)
        in_rel_counter[row.target_labels_key][row.relationship_type] += int(row.edge_count)
        target_counter[row.source_labels_key][row.target_labels_key] += int(row.edge_count)
        source_counter[row.target_labels_key][row.source_labels_key] += int(row.edge_count)

    labelset_rows = []
    for labelset_id in labelset_ids:
        labels = split_labelset(labelset_id)
        outgoing_edges = int(outgoing.get(labelset_id, 0))
        incoming_edges = int(incoming.get(labelset_id, 0))
        labelset_rows.append(
            {
                "labelset_id": labelset_id_map[labelset_id],
                "labelset": labelset_id,
                "surface": classify_surface(labelset_id),
                "label_count": len(labels),
                "component_labels": "; ".join(labels),
                "component_label_node_counts": label_count_string(labelset_id, label_count_map),
                "exact_labelset_node_count": "not_exported",
                "exact_labelset_count_note": "not exported; component label counts are shown instead",
                "outgoing_schema_triples": int(out_triple_count.get(labelset_id, 0)),
                "incoming_schema_triples": int(in_triple_count.get(labelset_id, 0)),
                "outgoing_edge_count": outgoing_edges,
                "incoming_edge_count": incoming_edges,
                "incident_edge_count": outgoing_edges + incoming_edges,
                "top_outgoing_relationships": top_counter_string(out_rel_counter[labelset_id]),
                "top_incoming_relationships": top_counter_string(in_rel_counter[labelset_id]),
                "top_target_labelsets": top_counter_string(target_counter[labelset_id]),
                "top_source_labelsets": top_counter_string(source_counter[labelset_id]),
            }
        )
    labelset_table = pd.DataFrame(labelset_rows).sort_values("incident_edge_count", ascending=False)

    unwound_out_edges = unwound.groupby("source_label")["edge_count"].sum().to_dict()
    unwound_in_edges = unwound.groupby("target_label")["edge_count"].sum().to_dict()
    unwound_out_triples = unwound.groupby("source_label").size().to_dict()
    unwound_in_triples = unwound.groupby("target_label").size().to_dict()
    label_out_rels: dict[str, Counter[str]] = defaultdict(Counter)
    label_in_rels: dict[str, Counter[str]] = defaultdict(Counter)
    for row in unwound.itertuples(index=False):
        label_out_rels[row.source_label][row.relationship_type] += int(row.edge_count)
        label_in_rels[row.target_label][row.relationship_type] += int(row.edge_count)

    node_labels = label_counts.copy()
    node_labels["node_label_id"] = [f"node_label_{idx:03d}" for idx in range(1, len(node_labels) + 1)]
    node_labels["surface"] = node_labels["label"].map(classify_surface)
    node_labels["outgoing_schema_triples_unwound"] = node_labels["label"].map(lambda label: int(unwound_out_triples.get(label, 0)))
    node_labels["incoming_schema_triples_unwound"] = node_labels["label"].map(lambda label: int(unwound_in_triples.get(label, 0)))
    node_labels["outgoing_edge_count_unwound"] = node_labels["label"].map(lambda label: int(unwound_out_edges.get(label, 0)))
    node_labels["incoming_edge_count_unwound"] = node_labels["label"].map(lambda label: int(unwound_in_edges.get(label, 0)))
    node_labels["incident_edge_count_unwound"] = node_labels["outgoing_edge_count_unwound"] + node_labels["incoming_edge_count_unwound"]
    node_labels["top_outgoing_relationships_unwound"] = node_labels["label"].map(lambda label: top_counter_string(label_out_rels[label]))
    node_labels["top_incoming_relationships_unwound"] = node_labels["label"].map(lambda label: top_counter_string(label_in_rels[label]))
    node_labels["unwound_counting_note"] = "multi-label endpoints counted once per component label"
    node_labels = node_labels[
        [
            "node_label_id",
            "label",
            "surface",
            "node_count",
            "outgoing_schema_triples_unwound",
            "incoming_schema_triples_unwound",
            "outgoing_edge_count_unwound",
            "incoming_edge_count_unwound",
            "incident_edge_count_unwound",
            "top_outgoing_relationships_unwound",
            "top_incoming_relationships_unwound",
            "unwound_counting_note",
        ]
    ]

    rel_rows = []
    for row in rel_counts.itertuples(index=False):
        rel = str(row.relationship_type)
        sub = labelsets[labelsets["relationship_type"] == rel].sort_values("edge_count", ascending=False)
        rel_edges = int(row.edge_count)
        source_counts = Counter(dict(sub.groupby("source_labels_key")["edge_count"].sum()))
        target_counts = Counter(dict(sub.groupby("target_labels_key")["edge_count"].sum()))
        dominant = sub.iloc[0] if not sub.empty else None
        rel_rows.append(
            {
                "relationship_type_id": relationship_id_map[rel],
                "relationship_type": rel,
                "edge_count": rel_edges,
                "edge_share_of_graph": rel_edges / total_edges,
                "schema_triple_count": int(len(sub)),
                "source_labelset_count": int(sub["source_labels_key"].nunique()),
                "target_labelset_count": int(sub["target_labels_key"].nunique()),
                "top_source_labelsets": top_counter_string(source_counts),
                "top_target_labelsets": top_counter_string(target_counts),
                "dominant_schema_triple": str(dominant["schema_triple"]) if dominant is not None else "",
                "dominant_schema_triple_edge_count": int(dominant["edge_count"]) if dominant is not None else 0,
                "dominant_schema_triple_share_of_relationship": float(dominant["edge_count"] / rel_edges) if dominant is not None and rel_edges else 0.0,
            }
        )
    relationships = pd.DataFrame(rel_rows)

    surface = (
        labelsets.groupby(["source_labels_key", "target_labels_key"], as_index=False)
        .agg(
            edge_count=("edge_count", "sum"),
            schema_triple_count=("schema_triple", "count"),
            relationship_types=("relationship_type", lambda values: "; ".join(sorted(set(map(str, values))))),
            top_schema_triples=("schema_triple", lambda values: compact_join(list(values), limit=4)),
        )
        .sort_values("edge_count", ascending=False)
        .reset_index(drop=True)
    )
    surface["surface_pair_id"] = [f"surface_pair_{idx:03d}" for idx in range(1, len(surface) + 1)]
    surface["source_surface"] = surface["source_labels_key"].map(classify_surface)
    surface["target_surface"] = surface["target_labels_key"].map(classify_surface)
    surface["edge_share_of_graph"] = surface["edge_count"] / total_edges
    surface = surface[
        [
            "surface_pair_id",
            "source_labels_key",
            "source_surface",
            "target_labels_key",
            "target_surface",
            "edge_count",
            "edge_share_of_graph",
            "schema_triple_count",
            "relationship_types",
            "top_schema_triples",
        ]
    ]

    return {
        "schema_triples": schema,
        "labelset_nodes": labelset_table,
        "node_labels": node_labels,
        "relationship_types": relationships,
        "source_target_surfaces": surface,
    }


def write_csvs(tables: dict[str, pd.DataFrame]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    tables["schema_triples"].to_csv(TRIPLES_CSV, index=False)
    tables["labelset_nodes"].to_csv(LABELSETS_CSV, index=False)
    tables["node_labels"].to_csv(NODE_LABELS_CSV, index=False)
    tables["relationship_types"].to_csv(RELATIONSHIPS_CSV, index=False)
    tables["source_target_surfaces"].to_csv(SOURCE_TARGET_CSV, index=False)


def write_xlsx(tables: dict[str, pd.DataFrame]) -> bool:
    try:
        with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as writer:
            for sheet_name, frame in tables.items():
                frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                worksheet = writer.sheets[sheet_name[:31]]
                worksheet.freeze_panes = "A2"
                for column_cells in worksheet.columns:
                    max_len = max(len(str(cell.value or "")) for cell in column_cells[:200])
                    worksheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 48)
        return True
    except Exception:
        return False


def write_data_dictionary(tables: dict[str, pd.DataFrame], *, wrote_xlsx: bool) -> None:
    lines = [
        "# NeuroKG Schema Inventory Data Dictionary",
        "",
        "These tables are generated from the full prod NeuroKG schema-triple export.",
        "Canonical schema triples preserve graph edge cardinality exactly; unwound node-label tables count multi-label endpoints once per component label.",
        "",
        "## Files",
        "",
        f"- `{TRIPLES_CSV.name}`: one row per canonical schema triple.",
        f"- `{LABELSETS_CSV.name}`: one row per canonical label-set node used in the schema graph.",
        f"- `{NODE_LABELS_CSV.name}`: one row per Neo4j node label.",
        f"- `{RELATIONSHIPS_CSV.name}`: one row per Neo4j relationship type.",
        f"- `{SOURCE_TARGET_CSV.name}`: one row per source-label-set / target-label-set surface block.",
        f"- `{HTML_PATH.name}`: searchable browser version of the same tables.",
    ]
    if wrote_xlsx:
        lines.append(f"- `{XLSX_PATH.name}`: Excel workbook with all sheets.")

    lines += [
        "",
        "## Recommended Main Supplement Table",
        "",
        "Use `neurokg_schema_triples_comprehensive.csv` as the main comprehensive table. Key columns:",
        "",
        "- `schema_triple_id`, `rank`: stable row identifiers sorted by edge mass.",
        "- `source_node_type`, `source_surface`: source label-set and coarse scientific surface.",
        "- `relationship_type`, `relationship_edge_count_total`: edge type and total edge count for that relationship.",
        "- `target_node_type`, `target_surface`: target label-set and coarse scientific surface.",
        "- `edge_count`, `schema_triple_share_of_graph`: edge mass for this exact schema triple.",
        "- `schema_triple_share_of_relationship`: how much of that relationship type is explained by this source-target pair.",
        "- `source_component_node_counts`, `target_component_node_counts`: component label counts for interpreting multi-label label sets.",
        "",
        "## Table Shapes",
        "",
    ]
    for name, frame in tables.items():
        lines.append(f"- `{name}`: {len(frame):,} rows x {len(frame.columns):,} columns.")
    DATA_DICTIONARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def html_table(frame: pd.DataFrame, table_id: str, max_rows: int | None = None) -> str:
    display = frame if max_rows is None else frame.head(max_rows)
    headers = "".join(f"<th>{html.escape(str(col))}</th>" for col in display.columns)
    rows = []
    for _, row in display.iterrows():
        cells = []
        for value in row:
            if isinstance(value, float):
                text = f"{value:.4f}" if not math.isnan(value) else ""
            else:
                text = str(value)
            cells.append(f"<td>{html.escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table id="{table_id}"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def write_html(tables: dict[str, pd.DataFrame], summary: dict[str, Any]) -> None:
    tabs = [
        ("schema_triples", "Schema triples", "Canonical source -> relationship -> target rows."),
        ("labelset_nodes", "Label-set nodes", "Aggregated schema nodes used by the graph browser."),
        ("node_labels", "Node labels", "Single Neo4j node-label dictionary."),
        ("relationship_types", "Relationships", "Edge-type dictionary."),
        ("source_target_surfaces", "Source-target surfaces", "Surface blocks collapsed across relationship types."),
    ]
    nav = "\n".join(
        f'<button class="tab-button{" active" if idx == 0 else ""}" data-tab="{key}">{label}</button>'
        for idx, (key, label, _) in enumerate(tabs)
    )
    sections = []
    for idx, (key, label, desc) in enumerate(tabs):
        frame = tables[key]
        sections.append(
            f"""
            <section id="{key}" class="tab-panel{' active' if idx == 0 else ''}">
              <div class="panel-head">
                <div>
                  <h2>{html.escape(label)}</h2>
                  <p>{html.escape(desc)} Showing {len(frame):,} rows.</p>
                </div>
                <input class="filter" data-table="{key}_table" type="search" placeholder="Filter this table" />
              </div>
              <div class="table-wrap">{html_table(frame, key + "_table")}</div>
            </section>
            """
        )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>NeuroKG Schema Inventory Tables</title>
  <style>
    :root {{
      --bg: #f7f9fc;
      --ink: #17202a;
      --muted: #657487;
      --line: #dbe3ee;
      --panel: #ffffff;
      --accent: #167e72;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 13px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 34px 18px;
      background: linear-gradient(135deg, #08131f, #0f2636);
      color: white;
    }}
    h1 {{ margin: 0 0 8px; font-size: 34px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #b9cedd; max-width: 900px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
      max-width: 1000px;
    }}
    .stat {{
      border: 1px solid rgba(255,255,255,.13);
      border-radius: 8px;
      padding: 10px 12px;
      background: rgba(255,255,255,.07);
    }}
    .stat strong {{ display: block; font-size: 20px; }}
    .stat span {{ display: block; color: #b9cedd; font-size: 11px; }}
    main {{ padding: 18px 24px 32px; }}
    .tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .tab-button {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 9px 12px;
      cursor: pointer;
      color: var(--ink);
      font-weight: 700;
    }}
    .tab-button.active {{
      border-color: var(--accent);
      color: white;
      background: var(--accent);
    }}
    .tab-panel {{
      display: none;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      overflow: hidden;
    }}
    .tab-panel.active {{ display: block; }}
    .panel-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }}
    h2 {{ margin: 0; font-size: 18px; }}
    .panel-head p {{ margin: 3px 0 0; color: var(--muted); }}
    .filter {{
      width: min(340px, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      font: inherit;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: calc(100vh - 270px);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      min-width: 1250px;
    }}
    th, td {{
      border-bottom: 1px solid #edf1f6;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: #eef4f8;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    td {{
      max-width: 430px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    tbody tr:hover {{ background: #f5fbfb; }}
    .links {{
      margin-top: 14px;
      color: var(--muted);
    }}
    .links code {{ color: var(--ink); }}
    @media (max-width: 820px) {{
      header {{ padding: 22px 18px 16px; }}
      main {{ padding: 14px; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .panel-head {{ align-items: stretch; flex-direction: column; }}
      .filter {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>NeuroKG Schema Inventory</h1>
    <p>Comprehensive tabular view of the prod NeuroKG schema: canonical schema triples, label-set nodes, single node labels, relationship types, and source-target surfaces.</p>
    <div class="stats">
      <div class="stat"><strong>{summary['total_edges']:,}</strong><span>graph edges</span></div>
      <div class="stat"><strong>{summary['schema_triples']:,}</strong><span>schema triples</span></div>
      <div class="stat"><strong>{summary['labelsets']:,}</strong><span>label-set nodes</span></div>
      <div class="stat"><strong>{summary['node_labels']:,}</strong><span>node labels</span></div>
      <div class="stat"><strong>{summary['relationship_types']:,}</strong><span>relationship types</span></div>
    </div>
  </header>
  <main>
    <nav class="tabs">{nav}</nav>
    {''.join(sections)}
    <div class="links">CSV/XLSX files are in this same <code>tables/</code> directory. Canonical rows preserve edge cardinality; node-label rows use unwound multi-label counting.</div>
  </main>
  <script>
    document.querySelectorAll('.tab-button').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('.tab-button').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(x => x.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(button.dataset.tab).classList.add('active');
      }});
    }});
    document.querySelectorAll('.filter').forEach(input => {{
      input.addEventListener('input', () => {{
        const query = input.value.toLowerCase();
        const table = document.getElementById(input.dataset.table);
        table.querySelectorAll('tbody tr').forEach(row => {{
          row.style.display = row.innerText.toLowerCase().includes(query) ? '' : 'none';
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    HTML_PATH.write_text(html_text, encoding="utf-8")


def write_summary_json(tables: dict[str, pd.DataFrame], *, wrote_xlsx: bool) -> dict[str, Any]:
    schema = tables["schema_triples"]
    summary = {
        "total_edges": int(schema["edge_count"].sum()),
        "schema_triples": int(len(schema)),
        "labelsets": int(len(tables["labelset_nodes"])),
        "node_labels": int(len(tables["node_labels"])),
        "relationship_types": int(len(tables["relationship_types"])),
        "source_target_surfaces": int(len(tables["source_target_surfaces"])),
        "top1_share": float(schema["edge_count"].head(1).sum() / schema["edge_count"].sum()),
        "top3_share": float(schema["edge_count"].head(3).sum() / schema["edge_count"].sum()),
        "top10_share": float(schema["edge_count"].head(10).sum() / schema["edge_count"].sum()),
        "wrote_xlsx": bool(wrote_xlsx),
        "files": {
            "schema_triples": str(TRIPLES_CSV.relative_to(HERE)),
            "labelset_nodes": str(LABELSETS_CSV.relative_to(HERE)),
            "node_labels": str(NODE_LABELS_CSV.relative_to(HERE)),
            "relationship_types": str(RELATIONSHIPS_CSV.relative_to(HERE)),
            "source_target_surfaces": str(SOURCE_TARGET_CSV.relative_to(HERE)),
            "data_dictionary": str(DATA_DICTIONARY_MD.relative_to(HERE)),
            "html": str(HTML_PATH.relative_to(HERE)),
            "xlsx": str(XLSX_PATH.relative_to(HERE)) if wrote_xlsx else "",
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    tables = build_tables()
    write_csvs(tables)
    wrote_xlsx = write_xlsx(tables)
    summary = write_summary_json(tables, wrote_xlsx=wrote_xlsx)
    write_data_dictionary(tables, wrote_xlsx=wrote_xlsx)
    write_html(tables, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
