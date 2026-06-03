#!/usr/bin/env python3
"""Build an interactive Neo4j/Bloom-style BR-KG schema graph.

The raw prod BR-KG has millions of edges, so this view deliberately uses the
full canonical schema-triple export instead of raw nodes. Each visual node is a
label set, and each visual edge is a typed schema triple aggregated by edge
count.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
SCHEMA_PATH = DATA_DIR / "kg_schema_triples_full_labelsets.csv"
GRAPH_JSON = DATA_DIR / "fig10_br_kg_3d_schema_graph_data.json"
HTML_PATH = FIG_DIR / "fig10_br_kg_3d_schema_browser.html"


SURFACE_COLORS = {
    "Statistical maps": "#20d3b3",
    "Publication evidence": "#4ea5ff",
    "Spatial anatomy": "#b8f34d",
    "Task and behavior": "#ffb000",
    "Ontology and terms": "#c77dff",
    "Tools and resources": "#ff6b6b",
    "Analysis methods": "#ff7ad9",
    "Other schema": "#95a3b3",
}

RELATION_COLORS = {
    "BELONGS_TO": "#20d3b3",
    "HAS_COORDINATE": "#4ea5ff",
    "HAS_TERM": "#c77dff",
    "IN_REGION": "#b8f34d",
    "ABOUT": "#ff7ad9",
    "IN_ONVOC": "#b77dff",
    "IN_DOMAIN": "#ffb000",
    "IN_SPACE": "#7ce7ff",
    "COMPUTED_WITH": "#ff6b6b",
    "GENERATED_FROM": "#f08cff",
    "DERIVED_FROM": "#ffffff",
    "Other": "#7786a3",
}


def _contains(label_key: str, *tokens: str) -> bool:
    lowered = label_key.lower()
    return any(token.lower() in lowered for token in tokens)


def classify_surface(label_key: str) -> str:
    if _contains(label_key, "StatsMap", "StatisticalMap", "Collection"):
        return "Statistical maps"
    if _contains(label_key, "Publication", "Citation", "Embedding"):
        return "Publication evidence"
    if _contains(label_key, "BrainRegion", "Coordinate", "TemplateSpace", "Atlas", "Parcellation"):
        return "Spatial anatomy"
    if _contains(label_key, "Task", "Subject", "Phenotype", "Condition", "Contrast"):
        return "Task and behavior"
    if _contains(label_key, "Concept", "Term", "Ontology", "Onvoc", "Process"):
        return "Ontology and terms"
    if _contains(label_key, "Tool", "DataResource", "OpenNeuro", "Dataset", "Modality"):
        return "Tools and resources"
    if _contains(label_key, "ModelSpec", "TaskAnalysis", "GLM"):
        return "Analysis methods"
    return "Other schema"


def short_label(label_key: str, max_len: int = 26) -> str:
    if len(label_key) <= max_len:
        return label_key
    keep = max(6, (max_len - 5) // 2)
    return f"{label_key[:keep]} ... {label_key[-keep:]}"


def count_label(label_key: str) -> int:
    return len([part for part in label_key.split("|") if part])


def build_graph() -> dict[str, Any]:
    frame = pd.read_csv(SCHEMA_PATH)
    frame = frame.sort_values("edge_count", ascending=False).reset_index(drop=True)
    total_edges = int(frame["edge_count"].sum())
    max_edge = float(frame["edge_count"].max())

    node_edges: dict[str, dict[str, float]] = defaultdict(lambda: {"in": 0.0, "out": 0.0})
    node_rels: dict[str, Counter[str]] = defaultdict(Counter)
    for row in frame.itertuples(index=False):
        source = str(row.source_labels_key)
        target = str(row.target_labels_key)
        rel = str(row.relationship_type)
        count = float(row.edge_count)
        node_edges[source]["out"] += count
        node_edges[target]["in"] += count
        node_rels[source][rel] += int(count)
        node_rels[target][rel] += int(count)

    surfaces = list(SURFACE_COLORS)
    surface_angles = {surface: 2 * math.pi * idx / len(surfaces) for idx, surface in enumerate(surfaces)}
    surface_offsets = Counter()
    nodes: list[dict[str, Any]] = []
    for node_id, values in sorted(node_edges.items(), key=lambda item: -(item[1]["in"] + item[1]["out"])):
        total = values["in"] + values["out"]
        surface = classify_surface(node_id)
        surface_offsets[surface] += 1
        angle = surface_angles[surface] + 0.22 * surface_offsets[surface]
        radius = 110 + 14 * surface_offsets[surface]
        nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "shortLabel": short_label(node_id),
                "surface": surface,
                "color": SURFACE_COLORS[surface],
                "val": round(3.5 + 17.5 * math.sqrt(total / max(total_edges, 1)), 3),
                "totalEdges": int(total),
                "incomingEdges": int(values["in"]),
                "outgoingEdges": int(values["out"]),
                "labelCount": count_label(node_id),
                "topRelationships": node_rels[node_id].most_common(5),
                "x": round(radius * math.cos(angle), 3),
                "y": round(radius * math.sin(angle), 3),
                "z": round((surface_offsets[surface] % 5 - 2) * 34, 3),
            }
        )

    top_rels = {rel for rel, _ in Counter(dict(zip(frame["relationship_type"], frame["edge_count"]))).most_common(10)}
    links: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        rel = str(row.relationship_type)
        count = int(row.edge_count)
        rel_group = rel if rel in RELATION_COLORS else "Other"
        links.append(
            {
                "source": str(row.source_labels_key),
                "target": str(row.target_labels_key),
                "rel": rel,
                "relGroup": rel_group,
                "color": RELATION_COLORS.get(rel_group, RELATION_COLORS["Other"]),
                "value": count,
                "rank": int(row.rank),
                "share": float(row.edge_share),
                "width": round(0.45 + 7.2 * math.sqrt(count / max_edge), 3),
                "particles": 5 if count >= 100_000 else 3 if count >= 30_000 else 1 if count >= 5_000 else 0,
                "schemaTriple": str(row.schema_triple),
            }
        )

    rel_counts = (
        frame.groupby("relationship_type")["edge_count"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"edge_count": "edges"})
    )
    surface_counts = Counter(node["surface"] for node in nodes)
    top_triples = frame.head(14)[
        ["rank", "schema_triple", "edge_count", "edge_share", "relationship_type"]
    ].to_dict(orient="records")

    return {
        "nodes": nodes,
        "links": links,
        "meta": {
            "totalEdges": total_edges,
            "schemaTriples": int(len(frame)),
            "nodeLabelSets": int(len(nodes)),
            "relationshipTypes": int(frame["relationship_type"].nunique()),
            "top1Share": float(frame["edge_count"].head(1).sum() / total_edges),
            "top3Share": float(frame["edge_count"].head(3).sum() / total_edges),
            "top10Share": float(frame["edge_count"].head(10).sum() / total_edges),
            "source": str(SCHEMA_PATH.relative_to(HERE)),
        },
        "surfaceLegend": [
            {"surface": surface, "color": color, "nodes": surface_counts.get(surface, 0)}
            for surface, color in SURFACE_COLORS.items()
        ],
        "relationshipLegend": [
            {
                "relationship": str(row.relationship_type),
                "edges": int(row.edges),
                "color": RELATION_COLORS.get(str(row.relationship_type), RELATION_COLORS["Other"]),
            }
            for row in rel_counts.head(10).itertuples(index=False)
        ],
        "topTriples": top_triples,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>BR-KG Schema Graph Browser</title>
  <style>
    :root {
      --bg: #071018;
      --panel: rgba(8, 18, 30, 0.82);
      --panel-strong: rgba(12, 28, 44, 0.92);
      --line: rgba(180, 226, 255, 0.16);
      --text: #edf8ff;
      --muted: #93aaba;
      --accent: #20d3b3;
      --hot: #ffb000;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background:
        radial-gradient(circle at 14% 18%, rgba(32,211,179,0.18), transparent 28%),
        radial-gradient(circle at 76% 18%, rgba(78,165,255,0.16), transparent 31%),
        linear-gradient(135deg, #05090f 0%, #091522 44%, #061017 100%);
      color: var(--text);
      font: 14px/1.4 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    #graph {
      position: fixed;
      inset: 0;
    }
    #graph::after {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(90deg, rgba(5,10,16,0.82), transparent 24%, transparent 76%, rgba(5,10,16,0.44)),
        linear-gradient(180deg, rgba(5,10,16,0.46), transparent 22%, rgba(5,10,16,0.34));
    }
    .hud {
      position: fixed;
      top: 22px;
      left: 24px;
      width: min(430px, calc(100vw - 48px));
      padding: 18px 18px 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      backdrop-filter: blur(18px);
      box-shadow: 0 24px 80px rgba(0,0,0,0.38);
      z-index: 5;
    }
    .eyebrow {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--accent);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: .14em;
      font-weight: 750;
    }
    .pulse {
      width: 9px;
      height: 9px;
      border-radius: 99px;
      background: var(--accent);
      box-shadow: 0 0 18px var(--accent);
    }
    h1 {
      margin: 9px 0 8px;
      font-size: clamp(28px, 3.2vw, 52px);
      line-height: .95;
      letter-spacing: 0;
    }
    .subtitle {
      margin: 0;
      color: #b7c9d7;
      max-width: 35rem;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 16px;
    }
    .stat {
      min-width: 0;
      padding: 10px 9px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255,255,255,0.045);
    }
    .stat strong {
      display: block;
      font-size: 18px;
      line-height: 1;
      color: #fff;
    }
    .stat span {
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.15;
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      margin-top: 14px;
      align-items: center;
    }
    input[type="search"] {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(1,7,12,.62);
      color: var(--text);
      padding: 10px 12px;
      outline: none;
    }
    button {
      border: 1px solid rgba(32,211,179,.42);
      color: var(--text);
      background: rgba(32,211,179,.14);
      padding: 10px 12px;
      border-radius: 12px;
      cursor: pointer;
      font-weight: 700;
    }
    .slider-row {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 10px;
      align-items: center;
      margin-top: 12px;
      color: var(--muted);
      font-size: 12px;
    }
    input[type="range"] {
      accent-color: var(--accent);
      width: 100%;
    }
    .side {
      position: fixed;
      top: 22px;
      right: 24px;
      width: min(380px, calc(100vw - 48px));
      max-height: calc(100vh - 44px);
      overflow: hidden auto;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      backdrop-filter: blur(18px);
      box-shadow: 0 24px 80px rgba(0,0,0,0.38);
      z-index: 5;
    }
    h2 {
      margin: 0 0 10px;
      font-size: 15px;
      letter-spacing: 0;
    }
    .legend {
      display: grid;
      gap: 8px;
      margin-bottom: 16px;
    }
    .legend-row {
      display: grid;
      grid-template-columns: 12px 1fr auto;
      align-items: center;
      gap: 9px;
      color: #cfe2ef;
      font-size: 12px;
    }
    .dot {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      box-shadow: 0 0 13px currentColor;
    }
    .triple-list {
      display: grid;
      gap: 8px;
    }
    .triple {
      padding: 9px 10px;
      border-radius: 12px;
      background: rgba(255,255,255,.05);
      border: 1px solid rgba(255,255,255,.08);
    }
    .triple .count {
      color: var(--hot);
      font-weight: 800;
      margin-right: 7px;
    }
    .triple .text {
      color: #dceaf3;
      font-size: 12px;
    }
    .tooltip {
      position: fixed;
      left: 50%;
      bottom: 22px;
      transform: translateX(-50%);
      width: min(620px, calc(100vw - 48px));
      padding: 13px 15px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel-strong);
      box-shadow: 0 18px 70px rgba(0,0,0,.45);
      z-index: 8;
      opacity: 0;
      pointer-events: none;
      transition: opacity .16s ease;
    }
    .tooltip.visible { opacity: 1; }
    .tooltip-title {
      display: flex;
      gap: 10px;
      align-items: center;
      font-weight: 800;
      font-size: 15px;
    }
    .tooltip-body {
      color: var(--muted);
      margin-top: 5px;
      font-size: 12px;
    }
    .caption {
      position: fixed;
      left: 24px;
      bottom: 20px;
      color: rgba(226, 242, 251, .68);
      max-width: 520px;
      font-size: 12px;
      z-index: 4;
    }
    @media (max-width: 920px) {
      .side { display: none; }
      .hud { width: calc(100vw - 32px); left: 16px; top: 16px; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .caption { display: none; }
    }
  </style>
</head>
<body>
  <div id="graph" aria-label="Interactive 3D BR-KG schema graph"></div>

  <section class="hud">
    <div class="eyebrow"><span class="pulse"></span> Prod BR-KG schema graph</div>
    <h1>BR-KG</h1>
    <p class="subtitle">Interactive schema-level graph: label-set nodes, typed relation edges, edge-count mass from the full prod export.</p>
    <div class="stats">
      <div class="stat"><strong id="stat-edges">-</strong><span>graph edges</span></div>
      <div class="stat"><strong id="stat-triples">-</strong><span>schema triples</span></div>
      <div class="stat"><strong id="stat-labels">-</strong><span>label sets</span></div>
      <div class="stat"><strong id="stat-top10">-</strong><span>top-10 edge share</span></div>
    </div>
    <div class="controls">
      <input id="search" type="search" placeholder="Search label set, e.g. Publication, StatsMap, Tool" list="node-options" />
      <button id="reset">Reset</button>
      <datalist id="node-options"></datalist>
    </div>
    <div class="slider-row">
      <span>Top</span>
      <input id="rank-limit" type="range" min="12" max="151" value="80" step="1" />
      <strong><span id="rank-value">80</span> triples</strong>
    </div>
  </section>

  <aside class="side">
    <h2>Node surfaces</h2>
    <div id="surface-legend" class="legend"></div>
    <h2>Dominant relationships</h2>
    <div id="relationship-legend" class="legend"></div>
    <h2>Top schema triples</h2>
    <div id="top-triples" class="triple-list"></div>
  </aside>

  <div id="tooltip" class="tooltip"></div>
  <div class="caption">This is an aggregated schema graph, not a raw node-link dump. Edge width and animated flow encode canonical schema-triple counts.</div>

  <script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script>
  <script src="https://unpkg.com/three-spritetext@1.8.0/dist/three-spritetext.min.js"></script>
  <script src="https://unpkg.com/3d-force-graph@1.77.0/dist/3d-force-graph.min.js"></script>
  <script>
    const graphPayload = __GRAPH_DATA__;
    const fmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
    const fullFmt = new Intl.NumberFormat("en-US");
    const meta = graphPayload.meta;
    const elem = document.getElementById("graph");
    const tooltip = document.getElementById("tooltip");
    let currentLimit = 80;
    let labelsVisible = true;
    let highlightedNode = null;

    document.getElementById("stat-edges").textContent = fmt.format(meta.totalEdges);
    document.getElementById("stat-triples").textContent = fullFmt.format(meta.schemaTriples);
    document.getElementById("stat-labels").textContent = fullFmt.format(meta.nodeLabelSets);
    document.getElementById("stat-top10").textContent = `${Math.round(meta.top10Share * 1000) / 10}%`;

    function renderLegend() {
      const surfaceRoot = document.getElementById("surface-legend");
      surfaceRoot.innerHTML = graphPayload.surfaceLegend
        .filter(row => row.nodes > 0)
        .map(row => `<div class="legend-row"><span class="dot" style="color:${row.color};background:${row.color}"></span><span>${row.surface}</span><span>${row.nodes}</span></div>`)
        .join("");

      const relRoot = document.getElementById("relationship-legend");
      relRoot.innerHTML = graphPayload.relationshipLegend
        .map(row => `<div class="legend-row"><span class="dot" style="color:${row.color};background:${row.color}"></span><span>${row.relationship}</span><span>${fmt.format(row.edges)}</span></div>`)
        .join("");

      const triples = document.getElementById("top-triples");
      triples.innerHTML = graphPayload.topTriples
        .map(row => `<div class="triple"><span class="count">#${row.rank} ${fmt.format(row.edge_count)}</span><span class="text">${row.schema_triple}</span></div>`)
        .join("");
    }

    function graphForLimit(limit) {
      const links = graphPayload.links.filter(link => link.rank <= limit);
      const nodeIds = new Set();
      links.forEach(link => {
        nodeIds.add(typeof link.source === "object" ? link.source.id : link.source);
        nodeIds.add(typeof link.target === "object" ? link.target.id : link.target);
      });
      const nodes = graphPayload.nodes.filter(node => nodeIds.has(node.id));
      return {
        nodes: nodes.map(node => ({ ...node })),
        links: links.map(link => ({ ...link }))
      };
    }

    const Graph = ForceGraph3D()(elem)
      .backgroundColor("rgba(0,0,0,0)")
      .graphData(graphForLimit(currentLimit))
      .nodeId("id")
      .nodeVal("val")
      .nodeColor(node => node.color)
      .nodeLabel(node => `${node.label}<br>${node.surface}<br>${fmt.format(node.totalEdges)} incident edges`)
      .linkColor(link => link.color)
      .linkOpacity(0.46)
      .linkWidth(link => link.width)
      .linkCurvature(link => Math.min(0.34, 0.04 + link.rank * 0.0012))
      .linkDirectionalArrowLength(3.2)
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalParticles(link => link.particles)
      .linkDirectionalParticleWidth(link => Math.max(1.2, link.width * 0.75))
      .linkDirectionalParticleSpeed(link => 0.0028 + Math.min(0.012, link.share * 0.08))
      .onNodeHover(node => {
        elem.style.cursor = node ? "pointer" : null;
        showNodeTooltip(node);
      })
      .onLinkHover(link => {
        elem.style.cursor = link ? "pointer" : null;
        showLinkTooltip(link);
      })
      .onNodeClick(node => {
        highlightedNode = node;
        const distance = 118 + node.val * 8;
        const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);
        Graph.cameraPosition(
          { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
          node,
          900
        );
      })
      .nodeThreeObject(node => {
        const group = new THREE.Group();
        const radius = Math.max(3.2, node.val);
        const geometry = new THREE.SphereGeometry(radius, 24, 24);
        const material = new THREE.MeshStandardMaterial({
          color: node.color,
          emissive: node.color,
          emissiveIntensity: 0.24,
          roughness: 0.38,
          metalness: 0.28
        });
        const sphere = new THREE.Mesh(geometry, material);
        group.add(sphere);

        const haloGeometry = new THREE.SphereGeometry(radius * 1.62, 24, 24);
        const haloMaterial = new THREE.MeshBasicMaterial({
          color: node.color,
          transparent: true,
          opacity: 0.075,
          depthWrite: false
        });
        group.add(new THREE.Mesh(haloGeometry, haloMaterial));

        if (labelsVisible && node.totalEdges >= 8000) {
          const sprite = new SpriteText(node.shortLabel);
          sprite.color = "#eaf8ff";
          sprite.textHeight = Math.max(5.5, Math.min(9.2, radius * 0.52));
          sprite.backgroundColor = "rgba(4,10,16,0.44)";
          sprite.borderRadius = 4;
          sprite.padding = 2.8;
          sprite.position.y = radius * 1.75;
          group.add(sprite);
        }
        return group;
      });

    function updateCanvasState() {
      const canvas = document.querySelector("canvas");
      if (canvas && window.__BRKG_GRAPH_STATE__) {
        window.__BRKG_GRAPH_STATE__.canvas = { width: canvas.width, height: canvas.height };
        window.__BRKG_GRAPH_STATE__.viewport = { width: window.innerWidth, height: window.innerHeight };
      }
    }

    function resizeGraph() {
      Graph.width(window.innerWidth).height(window.innerHeight);
      updateCanvasState();
    }

    Graph.d3Force("charge").strength(-260);
    Graph.d3Force("link").distance(link => 42 + Math.max(0, 9 - Math.log10(link.value + 1)) * 16);
    Graph.cameraPosition({ x: 0, y: -360, z: 225 }, { x: 0, y: 0, z: 0 }, 0);
    window.addEventListener("resize", () => requestAnimationFrame(resizeGraph));

    const ambient = new THREE.AmbientLight(0xffffff, 0.72);
    const directional = new THREE.DirectionalLight(0x8fdcff, 1.2);
    directional.position.set(120, -220, 340);
    Graph.scene().add(ambient);
    Graph.scene().add(directional);

    function showNodeTooltip(node) {
      if (!node) {
        tooltip.classList.remove("visible");
        return;
      }
      const rels = (node.topRelationships || []).map(([rel, count]) => `${rel}: ${fmt.format(count)}`).join(" · ");
      tooltip.innerHTML = `<div class="tooltip-title"><span class="dot" style="background:${node.color};color:${node.color}"></span>${node.label}</div><div class="tooltip-body">${node.surface} · ${fmt.format(node.totalEdges)} incident edges · out ${fmt.format(node.outgoingEdges)} · in ${fmt.format(node.incomingEdges)}<br>${rels}</div>`;
      tooltip.classList.add("visible");
    }

    function showLinkTooltip(link) {
      if (!link) {
        tooltip.classList.remove("visible");
        return;
      }
      const source = typeof link.source === "object" ? link.source.id : link.source;
      const target = typeof link.target === "object" ? link.target.id : link.target;
      tooltip.innerHTML = `<div class="tooltip-title"><span class="dot" style="background:${link.color};color:${link.color}"></span>${link.rel}</div><div class="tooltip-body">${source} -> ${target}<br>${fmt.format(link.value)} edges · rank #${link.rank} · ${(link.share * 100).toFixed(2)}% of graph edges</div>`;
      tooltip.classList.add("visible");
    }

    function updateLimit(limit) {
      currentLimit = Number(limit);
      document.getElementById("rank-value").textContent = currentLimit;
      Graph.graphData(graphForLimit(currentLimit));
      window.__BRKG_GRAPH_STATE__.limit = currentLimit;
    }

    document.getElementById("rank-limit").addEventListener("input", event => updateLimit(event.target.value));
    document.getElementById("reset").addEventListener("click", () => {
      document.getElementById("search").value = "";
      highlightedNode = null;
      Graph.cameraPosition({ x: 0, y: -360, z: 225 }, { x: 0, y: 0, z: 0 }, 850);
    });

    const dataList = document.getElementById("node-options");
    dataList.innerHTML = graphPayload.nodes.map(node => `<option value="${node.label}"></option>`).join("");
    document.getElementById("search").addEventListener("change", event => {
      const query = event.target.value.trim().toLowerCase();
      if (!query) return;
      const node = Graph.graphData().nodes.find(candidate => candidate.label.toLowerCase().includes(query));
      if (node) {
        Graph.cameraPosition({ x: node.x * 2.6, y: node.y * 2.6, z: node.z * 2.6 + 80 }, node, 900);
        showNodeTooltip(node);
      }
    });

    window.addEventListener("keydown", event => {
      if (event.key.toLowerCase() === "l") {
        labelsVisible = !labelsVisible;
        Graph.nodeThreeObject(Graph.nodeThreeObject());
      }
    });

    renderLegend();
    window.__BRKG_GRAPH_STATE__ = {
      ready: false,
      nodes: graphPayload.nodes.length,
      links: graphPayload.links.length,
      limit: currentLimit,
      source: meta.source
    };
    resizeGraph();

    setTimeout(() => {
      window.__BRKG_GRAPH_STATE__.ready = true;
      updateCanvasState();
    }, 3600);
  </script>
</body>
</html>
"""


def write_html(graph: dict[str, Any]) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_JSON.write_text(json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")
    html = HTML_TEMPLATE.replace("__GRAPH_DATA__", json.dumps(graph, separators=(",", ":")))
    HTML_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    graph = build_graph()
    write_html(graph)
    print(f"Wrote {GRAPH_JSON}")
    print(f"Wrote {HTML_PATH}")
    print(json.dumps(graph["meta"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
