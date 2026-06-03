#!/usr/bin/env python3
"""Generate a bounded plot probe from the production Brain Researcher BRKG.

The script intentionally avoids broad filesystem scans and large vector exports.
It pulls:

- graph count summaries from prod Neo4j via the prod k3s VM path,
- the small task embedding panel already stored directly on Task nodes,
- job/session summaries from the shared prod jobstore SQLite database,
- mounted FAISS/storage file metadata from bounded top-level paths.

Outputs are written next to this script under:

- data/prod_br_kg_plot_data.json
- figures/*.png and figures/*.svg
- SUMMARY.md
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


PROJECT = "${GCP_PROJECT_ID}"
ZONE = "us-west1-b"
VM = "${GCE_VM_NAME}"
NAMESPACE = "brain-researcher-core"
BR_KG_POD = "brain-researcher-br_kg-0"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_PATH = DATA_DIR / "prod_br_kg_plot_data.json"
SUMMARY_PATH = HERE / "SUMMARY.md"


def _run(command: list[str], *, timeout: int = 180) -> str:
    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed with exit code "
            f"{proc.returncode}: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def _extract_json(stdout: str) -> dict[str, Any]:
    match = re.search(r"BR_PLOT_DATA_BEGIN\s*(\{.*\})\s*BR_PLOT_DATA_END", stdout, re.S)
    if not match:
        raise ValueError(f"Could not find JSON sentinel in output:\n{stdout[:2000]}")
    return json.loads(match.group(1))


def _ssh(command: str, *, timeout: int = 180) -> str:
    return _run(
        [
            "gcloud",
            "compute",
            "ssh",
            VM,
            "--zone",
            ZONE,
            "--project",
            PROJECT,
            "--command",
            command,
        ],
        timeout=timeout,
    )


def _remote_python(command_body: str, *, in_br_kg_pod: bool, timeout: int = 180) -> dict[str, Any]:
    payload = base64.b64encode(command_body.encode("utf-8")).decode("ascii")
    python_command = f"python -c \"import base64; exec(base64.b64decode('{payload}'))\""
    if in_br_kg_pod:
        remote = (
            f"sudo k3s kubectl -n {NAMESPACE} exec {BR_KG_POD} -- "
            f"{python_command}"
        )
    else:
        remote = f"python3 -c \"import base64; exec(base64.b64decode('{payload}'))\""
    return _extract_json(_ssh(remote, timeout=timeout))


def fetch_neo4j_data() -> dict[str, Any]:
    code = r'''
import json
import os
from neo4j import GraphDatabase

uri = os.environ["NEO4J_URI"]
user = os.environ.get("NEO4J_USER", "neo4j")
password = os.environ["NEO4J_PASSWORD"]

queries = {
    "label_counts": """
        MATCH (n) UNWIND labels(n) AS label
        RETURN label, count(*) AS count
        ORDER BY count DESC LIMIT 50
    """,
    "relationship_counts": """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(*) AS count
        ORDER BY count DESC LIMIT 80
    """,
    "graph_triples": """
        MATCH (a)-[r]->(b)
        RETURN labels(a) AS src, type(r) AS rel, labels(b) AS dst, count(*) AS count
        ORDER BY count DESC LIMIT 100
    """,
    "tool_family_counts": """
        MATCH (t:Tool)
        OPTIONAL MATCH (t)-[:IMPLEMENTS_FAMILY]->(f)
        RETURN coalesce(f.name, f.id, "unassigned") AS family, count(t) AS tools
        ORDER BY tools DESC LIMIT 60
    """,
    "statmap_region_counts": """
        MATCH (:StatsMap)-[:IN_REGION]->(r:BrainRegion)
        RETURN coalesce(r.name, r.label, r.id) AS region, count(*) AS count
        ORDER BY count DESC LIMIT 50
    """,
    "statmap_concept_counts": """
        MATCH (:StatsMap)-[:MEASURES]->(c:Concept)
        RETURN coalesce(c.name, c.label, c.id) AS concept, count(*) AS count
        ORDER BY count DESC LIMIT 50
    """,
    "embedding_inventory": """
        MATCH (e:Embedding)
        RETURN e.kind AS kind, e.model AS model, e.source AS source,
               e.dimension AS dim, count(*) AS count,
               collect(DISTINCT e.storage_path)[0..5] AS storage_paths
        ORDER BY count DESC LIMIT 50
    """,
    "task_embeddings": """
        MATCH (t:Task)
        WHERE t.embedding_text_v1 IS NOT NULL
          AND t.embedding_centaur_behavior_v1 IS NOT NULL
        RETURN coalesce(t.name, t.label, t.id) AS name,
               t.id AS id,
               t.embedding_text_v1 AS text,
               t.embedding_centaur_behavior_v1 AS behavior,
               t.embedding_text_v1_model AS text_model,
               t.embedding_centaur_behavior_v1_model AS behavior_model
        ORDER BY name LIMIT 200
    """,
    "statsmap_runs": """
        MATCH (s:StatsMap)
        RETURN count(s) AS statmaps,
               count(DISTINCT s.run) AS distinct_runs,
               collect(DISTINCT s.run)[0..30] AS sample_runs
    """,
}

def normalize(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return str(value)

driver = GraphDatabase.driver(uri, auth=(user, password))
out = {}
with driver.session() as session:
    for name, query in queries.items():
        rows = []
        for record in session.run(query):
            rows.append({key: normalize(record[key]) for key in record.keys()})
        out[name] = rows
driver.close()

print("BR_PLOT_DATA_BEGIN")
print(json.dumps(out, separators=(",", ":")))
print("BR_PLOT_DATA_END")
'''
    return _remote_python(code, in_br_kg_pod=True, timeout=240)


def fetch_vm_data() -> dict[str, Any]:
    code = r'''
import json
import os
import sqlite3
import re
from pathlib import Path

jobstore = Path("/srv/brain-researcher/jobstore/jobs.sqlite")
DOMAIN_TERMS = [
    "qc",
    "preprocess",
    "glm",
    "activation",
    "connectivity",
    "graph",
    "prediction",
    "decoding",
    "diffusion",
    "tractography",
    "eeg",
    "meg",
    "clinical",
    "evidence",
    "review",
    "memory",
    "ood",
    "meta-analysis",
    "openneuro",
    "neurosynth",
    "nimare",
]

def _json_loads(value, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default

def _text_terms(value):
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return {f"term_{term.replace('-', '_')}": int(term in text) for term in DOMAIN_TERMS}

def _safe_len(value):
    try:
        return len(value)
    except Exception:
        return 0

out = {
    "jobstore_path": str(jobstore),
    "jobs_by_state": [],
    "jobs_by_kind": [],
    "job_audit_event_types": [],
    "studio_runtime_status": [],
    "studio_session_status": [],
    "jobstore_jobs": [],
    "jobstore_episode_states": [],
    "mcp_run_states": [],
    "mcp_run_inventory": {},
    "storage_files": [],
}

if jobstore.exists():
    con = sqlite3.connect(f"file:{jobstore}?mode=ro&immutable=1", uri=True)
    cur = con.cursor()
    query_map = {
        "jobs_by_state": "select state, count(*) from jobs group by state order by count(*) desc",
        "jobs_by_kind": "select kind, count(*) from jobs group by kind order by count(*) desc limit 40",
        "job_audit_event_types": "select event_type, count(*) from job_audit group by event_type order by count(*) desc limit 40",
        "studio_runtime_status": "select kind, status, count(*) from studio_runtime_sessions group by kind, status order by count(*) desc",
        "studio_session_status": "select status, count(*) from studio_sessions group by status order by count(*) desc",
    }
    for key, query in query_map.items():
        out[key] = [list(row) for row in cur.execute(query)]

    job_features = {}
    for row in cur.execute("""
        select job_id, kind, state, priority, created_at, queued_at, claimed_at, started_at,
               finished_at, updated_at, attempt, max_attempts, exit_code, gpu_req, cpus,
               memory_gb, walltime_minutes, job_name, run_id, run_dir, user_id, session_id,
               project_id, error_message, payload_json
        from jobs order by created_at
    """):
        (
            job_id, kind, state, priority, created_at, queued_at, claimed_at, started_at,
            finished_at, updated_at, attempt, max_attempts, exit_code, gpu_req, cpus,
            memory_gb, walltime_minutes, job_name, run_id, run_dir, user_id, session_id,
            project_id, error_message, payload_json
        ) = row
        payload = _json_loads(payload_json, {})
        terms = _text_terms(payload)
        tool_id = payload.get("tool_id") if isinstance(payload, dict) else None
        prompt = payload.get("prompt") if isinstance(payload, dict) else ""
        plan_events = payload.get("plan_events") if isinstance(payload, dict) else []
        steps = payload.get("steps") if isinstance(payload, dict) else []
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else []
        duration_s = None
        if started_at and finished_at:
            duration_s = max(0, int(finished_at) - int(started_at))
        base = {
            "job_id": job_id,
            "kind": kind,
            "state": state,
            "priority": int(priority or 0),
            "created_at": int(created_at or 0),
            "queued_at": int(queued_at or 0),
            "claimed_at": int(claimed_at or 0),
            "started_at": int(started_at or 0),
            "finished_at": int(finished_at or 0),
            "updated_at": int(updated_at or 0),
            "duration_s": int(duration_s or 0),
            "attempt": int(attempt or 0),
            "max_attempts": int(max_attempts or 0),
            "exit_code": int(exit_code) if exit_code is not None else -1,
            "gpu_req": int(gpu_req or 0),
            "cpus": int(cpus or 0),
            "memory_gb": float(memory_gb or 0.0),
            "walltime_minutes": int(walltime_minutes or 0),
            "job_name_present": int(bool(job_name)),
            "run_id_present": int(bool(run_id)),
            "run_dir_present": int(bool(run_dir)),
            "user_present": int(bool(user_id)),
            "session_present": int(bool(session_id)),
            "project_present": int(bool(project_id)),
            "error_present": int(bool(error_message)),
            "tool_id": str(tool_id or ""),
            "prompt_len": len(str(prompt or "")),
            "step_count": _safe_len(steps),
            "artifact_count": _safe_len(artifacts),
            "plan_event_count": _safe_len(plan_events),
        }
        base.update(terms)
        job_features[job_id] = base
        job_point = dict(base)
        job_point.update({
            "point_id": f"job:{job_id}",
            "source": "job",
            "event_type": "job",
            "event_offset_s": 0,
            "payload_key_count": _safe_len(payload.keys()) if isinstance(payload, dict) else 0,
            "payload_text_len": len(payload_json or ""),
        })
        out["jobstore_jobs"].append(job_point)

    for row in cur.execute("""
        select a.id, a.job_id, a.event_type, a.payload_json, a.created_at
        from job_audit a order by a.created_at, a.id
    """):
        audit_id, job_id, event_type, payload_json, created_at = row
        base = dict(job_features.get(job_id, {}))
        payload = _json_loads(payload_json, {})
        payload_terms = _text_terms(payload)
        for key, value in payload_terms.items():
            base[key] = int(bool(base.get(key, 0) or value))
        job_created = int(base.get("created_at") or created_at or 0)
        point = {
            **base,
            "point_id": f"audit:{audit_id}",
            "source": "job_audit",
            "event_type": str(event_type or "unknown"),
            "event_created_at": int(created_at or 0),
            "event_offset_s": max(0, int(created_at or 0) - job_created),
            "payload_key_count": _safe_len(payload.keys()) if isinstance(payload, dict) else 0,
            "payload_text_len": len(payload_json or ""),
            "audit_id": int(audit_id or 0),
        }
        out["jobstore_episode_states"].append(point)
    con.close()

runs_root = Path("/srv/brain-researcher/jobstore/mcp_runs/runs")
if runs_root.exists():
    names = sorted(p.name for p in runs_root.iterdir() if p.is_dir())
    file_counts = {}
    status_counts = {}
    run_dirs = sorted((p for p in runs_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    for run_dir in run_dirs[-300:]:
        for child in run_dir.iterdir():
            file_counts[child.name] = file_counts.get(child.name, 0) + 1
        run_json = run_dir / "run.json"
        if run_json.exists():
            try:
                status = json.loads(run_json.read_text()).get("status") or "unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
            except Exception:
                pass
    for run_dir in run_dirs:
        files = {child.name: child for child in run_dir.iterdir()}
        run_json = files.get("run.json")
        run_obj = _json_loads(run_json.read_text(errors="replace"), {}) if run_json and run_json.exists() else {}
        status = str(run_obj.get("status") or "planned")
        steps = run_obj.get("steps") if isinstance(run_obj, dict) else []
        timing = run_obj.get("timing_policy") if isinstance(run_obj, dict) else {}
        event_counts = {}
        for jsonl_name in ["trace.jsonl", "research_events.jsonl", "tool_trace.jsonl", "conversation_log.jsonl"]:
            p = files.get(jsonl_name)
            if p and p.exists() and p.stat().st_size < 2_000_000:
                try:
                    event_counts[jsonl_name] = len(p.read_text(errors="replace").splitlines())
                except Exception:
                    event_counts[jsonl_name] = 0
            else:
                event_counts[jsonl_name] = 0
        text_blob = " ".join([run_dir.name, " ".join(files.keys()), json.dumps(run_obj, default=str)[:4000]]).lower()
        state = {
            "point_id": f"mcp_run:{run_dir.name}",
            "source": "mcp_run",
            "event_type": "run",
            "job_id": "",
            "kind": "mcp_run",
            "state": status,
            "created_at": 0,
            "started_at": 0,
            "finished_at": 0,
            "updated_at": 0,
            "duration_s": 0,
            "attempt": 0,
            "max_attempts": 0,
            "exit_code": -1,
            "gpu_req": 0,
            "cpus": 0,
            "memory_gb": 0.0,
            "walltime_minutes": 0,
            "job_name_present": 0,
            "run_id_present": 1,
            "run_dir_present": 1,
            "user_present": 0,
            "session_present": int((run_dir / "session_snapshot.json").exists() or (run_dir / "session_transcript.jsonl").exists()),
            "project_present": 0,
            "error_present": int(bool(run_obj.get("error"))),
            "tool_id": "",
            "prompt_len": 0,
            "step_count": _safe_len(steps),
            "artifact_count": int((run_dir / "artifacts").exists()),
            "plan_event_count": event_counts.get("research_events.jsonl", 0),
            "event_created_at": 0,
            "event_offset_s": 0,
            "payload_key_count": _safe_len(run_obj.keys()) if isinstance(run_obj, dict) else 0,
            "payload_text_len": len(text_blob),
            "has_trace": int((run_dir / "trace.jsonl").exists()),
            "has_tool_trace": int((run_dir / "tool_trace.jsonl").exists()),
            "has_research_events": int((run_dir / "research_events.jsonl").exists()),
            "has_observation": int((run_dir / "observation.json").exists()),
            "has_trajectory": int((run_dir / "trajectory.json").exists()),
            "has_review_verdict": int((run_dir / "scientific_review_verdict.json").exists() or (run_dir / "code_review_verdict.json").exists()),
            "trace_event_count": event_counts.get("trace.jsonl", 0),
            "tool_trace_event_count": event_counts.get("tool_trace.jsonl", 0),
            "conversation_event_count": event_counts.get("conversation_log.jsonl", 0),
        }
        state.update(_text_terms(text_blob))
        out["mcp_run_states"].append(state)
    out["mcp_run_inventory"] = {
        "run_dirs": len(names),
        "latest": names[-12:],
        "file_counts": sorted(file_counts.items(), key=lambda x: (-x[1], x[0]))[:40],
        "status_counts_latest_300": sorted(status_counts.items(), key=lambda x: (-x[1], x[0])),
    }

for root in [
    Path("/srv/indexes/niclip"),
    Path("/srv/datasets/neurosynth_nimare"),
    Path("/srv/datasets/neurosynth_maps"),
    Path("/srv/datasets/scholarly_metadata"),
    Path("/srv/brain-researcher/jobstore"),
]:
    if not root.exists():
        continue
    files = []
    try:
        for path in root.iterdir():
            if path.is_file():
                files.append({
                    "root": str(root),
                    "name": path.name,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                })
    except Exception:
        pass
    out["storage_files"].extend(sorted(files, key=lambda x: -x["bytes"])[:40])

print("BR_PLOT_DATA_BEGIN")
print(json.dumps(out, separators=(",", ":")))
print("BR_PLOT_DATA_END")
'''
    return _remote_python(code, in_br_kg_pod=False, timeout=180)


def fetch_data(force: bool = False) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_PATH.exists() and not force:
        data = json.loads(DATA_PATH.read_text())
        if data.get("vm", {}).get("jobstore_episode_states"):
            return data
        data["vm"] = fetch_vm_data()
        DATA_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return data

    data = {
        "source": {
            "project": PROJECT,
            "zone": ZONE,
            "vm": VM,
            "namespace": NAMESPACE,
            "br_kg_pod": BR_KG_POD,
        },
        "neo4j": fetch_neo4j_data(),
        "vm": fetch_vm_data(),
    }
    DATA_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def _to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _save_current_figure(name: str) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    png = FIG_DIR / f"{name}.png"
    svg = FIG_DIR / f"{name}.svg"
    plt.savefig(png, dpi=220, bbox_inches="tight")
    plt.savefig(svg, bbox_inches="tight")
    plt.close()


def _clean_label(value: Any, max_len: int = 38) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "..."


def plot_counts(data: dict[str, Any]) -> None:
    labels = _to_frame(data["neo4j"]["label_counts"]).head(25)
    rels = _to_frame(data["neo4j"]["relationship_counts"]).head(25)

    sns.set_theme(style="whitegrid", context="talk")
    fig, axes = plt.subplots(1, 2, figsize=(22, 10))

    sns.barplot(data=labels, x="count", y="label", ax=axes[0], color="#2a9d8f")
    axes[0].set_xscale("log")
    axes[0].set_title("Node labels")
    axes[0].set_xlabel("count, log scale")
    axes[0].set_ylabel("")

    sns.barplot(data=rels, x="count", y="rel_type", ax=axes[1], color="#e76f51")
    axes[1].set_xscale("log")
    axes[1].set_title("Edge types")
    axes[1].set_xlabel("count, log scale")
    axes[1].set_ylabel("")

    fig.suptitle("Prod BRKG is dominated by spatial, publication, task, and embedding surfaces", y=1.02)
    fig.subplots_adjust(wspace=0.38)
    _save_current_figure("fig01_node_and_edge_counts")


def plot_schema_network(data: dict[str, Any]) -> None:
    triples = data["neo4j"]["graph_triples"][:45]
    graph = nx.DiGraph()
    for row in triples:
        src = row["src"][0] if row.get("src") else "Unknown"
        dst = row["dst"][0] if row.get("dst") else "Unknown"
        rel = row["rel"]
        count = int(row["count"])
        graph.add_node(src)
        graph.add_node(dst)
        if graph.has_edge(src, dst):
            graph[src][dst]["weight"] += count
            graph[src][dst]["rels"].append(rel)
        else:
            graph.add_edge(src, dst, weight=count, rels=[rel])

    pos = nx.spring_layout(graph, seed=7, k=1.1, weight="weight")
    weights = np.array([graph[u][v]["weight"] for u, v in graph.edges()], dtype=float)
    widths = 1.0 + 6.0 * (np.log10(weights) - np.log10(weights.min())) / max(
        1e-9, np.log10(weights.max()) - np.log10(weights.min())
    )

    plt.figure(figsize=(15, 11))
    nx.draw_networkx_nodes(graph, pos, node_size=1300, node_color="#f4a261", edgecolors="#333333")
    nx.draw_networkx_labels(graph, pos, font_size=9)
    nx.draw_networkx_edges(
        graph,
        pos,
        width=widths,
        edge_color="#264653",
        alpha=0.55,
        arrows=True,
        arrowsize=14,
        connectionstyle="arc3,rad=0.08",
    )

    edge_labels = {}
    for u, v, attrs in graph.edges(data=True):
        rels = Counter(attrs["rels"]).most_common(2)
        edge_labels[(u, v)] = "/".join(rel for rel, _ in rels)
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=7, label_pos=0.55)

    plt.title("Top schema triples suggest separate graph views, not one full-KG view")
    plt.axis("off")
    _save_current_figure("fig02_schema_triple_network")


def _schema_triple_frame(data: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for rank, row in enumerate(data["neo4j"].get("graph_triples", []), start=1):
        src = row["src"][0] if row.get("src") else "Unknown"
        dst = row["dst"][0] if row.get("dst") else "Unknown"
        rel = str(row.get("rel") or "UNKNOWN")
        count = int(row.get("count") or 0)
        rows.append(
            {
                "rank": rank,
                "source_label": str(src),
                "relationship_type": rel,
                "target_label": str(dst),
                "relation_target": f"{rel} -> {dst}",
                "schema_triple": f"{src} -[{rel}]-> {dst}",
                "count": count,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    total = float(frame["count"].sum())
    frame["count_share"] = frame["count"] / total if total else 0.0
    frame["source_total"] = frame.groupby("source_label")["count"].transform("sum")
    frame["relationship_total"] = frame.groupby("relationship_type")["count"].transform("sum")
    frame["relation_target_total"] = frame.groupby("relation_target")["count"].transform("sum")
    return frame


def _ordered_schema_pivot(
    frame: pd.DataFrame,
    *,
    row_col: str,
    col_col: str,
    value_col: str,
    max_rows: int,
    max_cols: int,
) -> pd.DataFrame:
    rows = (
        frame.groupby(row_col)[value_col]
        .sum()
        .sort_values(ascending=False)
        .head(max_rows)
        .index
        .tolist()
    )
    cols = (
        frame.groupby(col_col)[value_col]
        .sum()
        .sort_values(ascending=False)
        .head(max_cols)
        .index
        .tolist()
    )
    pivot = (
        frame[frame[row_col].isin(rows) & frame[col_col].isin(cols)]
        .pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc="sum", fill_value=0)
        .reindex(index=rows, columns=cols, fill_value=0)
    )
    return pivot


def _log_count_pivot(pivot: pd.DataFrame) -> pd.DataFrame:
    return np.log10(pivot.astype(float) + 1.0)


def _format_count(value: float) -> str:
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    if value > 0:
        return f"{value:.0f}"
    return ""


def _relation_target_tick(value: str) -> str:
    if " -> " not in value:
        return _clean_label(value, 26)
    rel, target = value.split(" -> ", 1)
    return f"{_clean_label(rel, 22)}\n-> {_clean_label(target, 18)}"


def plot_schema_triple_heatmap(data: dict[str, Any]) -> dict[str, Any]:
    frame = _schema_triple_frame(data)
    if frame.empty:
        return {"available": False}

    out_path = DATA_DIR / "kg_schema_triple_heatmap.csv"
    frame.to_csv(out_path, index=False)

    source_rel = _ordered_schema_pivot(
        frame,
        row_col="source_label",
        col_col="relationship_type",
        value_col="count",
        max_rows=15,
        max_cols=18,
    )
    source_rel_target = _ordered_schema_pivot(
        frame,
        row_col="source_label",
        col_col="relation_target",
        value_col="count",
        max_rows=15,
        max_cols=24,
    )

    source_rel_labels = source_rel.copy().astype(object)
    source_rel_target_labels = source_rel_target.copy().astype(object)
    for labels in [source_rel_labels, source_rel_target_labels]:
        for row in labels.index:
            for col in labels.columns:
                labels.loc[row, col] = _format_count(labels.loc[row, col])
                if labels.loc[row, col] and float(
                    source_rel.loc[row, col] if col in source_rel.columns else source_rel_target.loc[row, col]
                ) < 3000:
                    labels.loc[row, col] = ""

    sns.set_theme(style="white", context="paper", font_scale=0.92)
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(25, 12.0),
        gridspec_kw={"width_ratios": [0.95, 1.55], "wspace": 0.26},
    )
    cmap = "viridis"

    sns.heatmap(
        _log_count_pivot(source_rel),
        ax=axes[0],
        cmap=cmap,
        cbar=False,
        linewidths=0.4,
        linecolor="#f1f1f1",
        annot=source_rel_labels,
        fmt="",
        annot_kws={"fontsize": 7},
    )
    axes[0].set_title("Source label x relationship type", fontsize=14, pad=12)
    axes[0].set_xlabel("")
    axes[0].set_ylabel("Source label")
    axes[0].tick_params(axis="x", rotation=55, labelsize=8)
    axes[0].tick_params(axis="y", labelsize=9)

    clipped_cols = [_relation_target_tick(col) for col in source_rel_target.columns]
    display_right = _log_count_pivot(source_rel_target)
    display_right.columns = clipped_cols
    source_rel_target_labels.columns = clipped_cols
    heat = sns.heatmap(
        display_right,
        ax=axes[1],
        cmap=cmap,
        cbar=True,
        cbar_kws={"label": "log10(edge count + 1)", "shrink": 0.72, "pad": 0.015},
        linewidths=0.35,
        linecolor="#f1f1f1",
        annot=source_rel_target_labels,
        fmt="",
        annot_kws={"fontsize": 6.5},
    )
    axes[1].set_title("Top schema triples: source label x (relationship -> target label)", fontsize=14, pad=12)
    axes[1].set_xlabel("")
    axes[1].set_ylabel("")
    axes[1].tick_params(axis="x", rotation=62, labelsize=7.2)
    axes[1].tick_params(axis="y", labelsize=9)
    heat.collections[0].colorbar.ax.tick_params(labelsize=8)

    top_triple = frame.sort_values("count", ascending=False).iloc[0]
    fig.suptitle("KG schema triple heatmap exposes dominant BRKG relation surfaces", y=1.02, fontsize=22)
    fig.text(
        0.50,
        0.035,
        "Cells are prod Neo4j schema-triple edge counts from the bounded top-triple export; annotations show large nonzero cells.",
        ha="center",
        fontsize=10,
        color="#444444",
    )
    fig.subplots_adjust(left=0.06, right=0.94, bottom=0.28, top=0.88, wspace=0.26)
    _save_current_figure("fig08_kg_schema_triple_heatmap")

    top_sources = (
        frame.groupby("source_label")["count"].sum().sort_values(ascending=False).head(5).to_dict()
    )
    top_relationships = (
        frame.groupby("relationship_type")["count"].sum().sort_values(ascending=False).head(5).to_dict()
    )
    return {
        "available": True,
        "triple_rows": int(len(frame)),
        "triple_edge_count": int(frame["count"].sum()),
        "top_triple": {
            "schema_triple": str(top_triple["schema_triple"]),
            "count": int(top_triple["count"]),
            "count_share": float(top_triple["count_share"]),
        },
        "top_sources": {str(k): int(v) for k, v in top_sources.items()},
        "top_relationships": {str(k): int(v) for k, v in top_relationships.items()},
        "csv": str(out_path.relative_to(HERE)),
    }


def _load_full_schema_export() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    labelset_path = DATA_DIR / "kg_schema_triples_full_labelsets.csv"
    unwound_path = DATA_DIR / "kg_schema_triples_full_unwound_labels.csv"
    if not labelset_path.exists() or not unwound_path.exists():
        return None
    labelsets = pd.read_csv(labelset_path)
    unwound = pd.read_csv(unwound_path)
    return labelsets, unwound


def _truncate_middle(value: Any, max_len: int = 44) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    keep = max(4, (max_len - 5) // 2)
    return text[:keep] + " ... " + text[-keep:]


def _schema_bar_label(row: pd.Series) -> str:
    source = _truncate_middle(row["source_labels_key"], 16)
    target = _truncate_middle(row["target_labels_key"], 22)
    rel = _clean_label(row["relationship_type"], 16)
    return f"{source} -[{rel}]->\n{target}"


def plot_full_schema_triple_atlas(data: dict[str, Any]) -> dict[str, Any]:
    loaded = _load_full_schema_export()
    if loaded is None:
        return {"available": False, "reason": "full schema export files missing"}
    labelsets, _unwound = loaded
    if labelsets.empty:
        return {"available": False, "reason": "full schema export was empty"}

    total_edges = float(labelsets["edge_count"].sum())
    labelsets = labelsets.sort_values("edge_count", ascending=False).reset_index(drop=True)
    labelsets["rank"] = np.arange(1, len(labelsets) + 1)
    labelsets["edge_share"] = labelsets["edge_count"] / total_edges if total_edges else 0.0
    labelsets["cumulative_edge_share"] = labelsets["edge_share"].cumsum()

    def rank_for_share(target: float) -> int:
        hits = labelsets[labelsets["cumulative_edge_share"] >= target]
        return int(hits["rank"].iloc[0]) if not hits.empty else int(len(labelsets))

    pareto_stats = {
        "top1_share": float(labelsets["cumulative_edge_share"].iloc[0]),
        "top3_share": float(labelsets["cumulative_edge_share"].iloc[min(2, len(labelsets) - 1)]),
        "top10_share": float(labelsets["cumulative_edge_share"].iloc[min(9, len(labelsets) - 1)]),
        "rank_for_90pct": rank_for_share(0.90),
        "rank_for_95pct": rank_for_share(0.95),
        "rank_for_99pct": rank_for_share(0.99),
    }

    source_order = (
        labelsets.groupby("source_labels_key")["edge_count"]
        .sum()
        .sort_values(ascending=False)
        .head(14)
        .index
        .tolist()
    )
    target_order = (
        labelsets.groupby("target_labels_key")["edge_count"]
        .sum()
        .sort_values(ascending=False)
        .head(16)
        .index
        .tolist()
    )
    source_target = (
        labelsets[
            labelsets["source_labels_key"].isin(source_order)
            & labelsets["target_labels_key"].isin(target_order)
        ]
        .pivot_table(
            index="source_labels_key",
            columns="target_labels_key",
            values="edge_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(index=source_order, columns=target_order, fill_value=0)
    )
    source_target_labels = source_target.astype(object).copy()
    for row in source_target_labels.index:
        for col in source_target_labels.columns:
            value = float(source_target.loc[row, col])
            source_target_labels.loc[row, col] = _format_count(value) if value >= 3000 else ""

    top_sources = (
        labelsets.groupby("source_labels_key")["edge_count"]
        .sum()
        .sort_values(ascending=False)
        .head(9)
        .index
        .tolist()
    )
    top_rels = (
        labelsets.groupby("relationship_type")["edge_count"]
        .sum()
        .sort_values(ascending=False)
        .head(9)
        .index
        .tolist()
    )
    composition = (
        labelsets[labelsets["source_labels_key"].isin(top_sources)]
        .assign(relationship_group=lambda df: np.where(df["relationship_type"].isin(top_rels), df["relationship_type"], "Other"))
        .pivot_table(
            index="source_labels_key",
            columns="relationship_group",
            values="edge_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(index=top_sources, fill_value=0)
    )
    if "Other" in composition.columns:
        rel_columns = [rel for rel in top_rels if rel in composition.columns] + ["Other"]
    else:
        rel_columns = [rel for rel in top_rels if rel in composition.columns]
    composition = composition[rel_columns]
    composition_prop = composition.div(composition.sum(axis=1), axis=0).fillna(0.0)

    top_triples = labelsets.head(16).iloc[::-1].copy()
    top_triples["bar_label"] = top_triples.apply(_schema_bar_label, axis=1)

    atlas_metrics = {
        "total_edges": int(total_edges),
        "schema_triple_count": int(len(labelsets)),
        **pareto_stats,
        "source_target_rows": int(source_target.shape[0]),
        "source_target_columns": int(source_target.shape[1]),
    }
    metrics_path = DATA_DIR / "kg_schema_full_atlas_metrics.json"
    metrics_path.write_text(json.dumps(atlas_metrics, indent=2, sort_keys=True), encoding="utf-8")

    sns.set_theme(style="white", context="paper", font_scale=0.95)
    fig = plt.figure(figsize=(26, 17))
    grid = fig.add_gridspec(
        2,
        2,
        width_ratios=[1.0, 1.42],
        height_ratios=[0.95, 1.05],
        wspace=0.48,
        hspace=0.42,
    )
    ax_pareto = fig.add_subplot(grid[0, 0])
    ax_heat = fig.add_subplot(grid[0, 1])
    ax_comp = fig.add_subplot(grid[1, 0])
    ax_top = fig.add_subplot(grid[1, 1])

    ax_pareto.bar(
        labelsets["rank"].head(30),
        labelsets["edge_share"].head(30),
        color="#8ecae6",
        edgecolor="#254b5f",
        linewidth=0.35,
        label="Individual triple share",
    )
    ax_pareto.plot(
        labelsets["rank"],
        labelsets["cumulative_edge_share"],
        color="#d95f02",
        linewidth=2.4,
        label="Cumulative share",
    )
    for target in [0.90, 0.95, 0.99]:
        rank = rank_for_share(target)
        ax_pareto.axhline(target, color="#9a9a9a", linewidth=0.8, linestyle="--", alpha=0.65)
        ax_pareto.axvline(rank, color="#9a9a9a", linewidth=0.8, linestyle="--", alpha=0.65)
        ax_pareto.text(
            rank + 1.2,
            target - 0.035,
            f"{int(target * 100)}% at {rank} triples",
            fontsize=8,
            color="#444444",
        )
    ax_pareto.set_title("Schema edge mass is highly concentrated", fontsize=14, pad=10)
    ax_pareto.set_xlabel("Schema triple rank")
    ax_pareto.set_ylabel("Share of graph edges")
    ax_pareto.set_xlim(0, len(labelsets) + 3)
    ax_pareto.set_ylim(0, 1.04)
    ax_pareto.legend(frameon=False, fontsize=8, loc="lower right")
    for spine in ["top", "right"]:
        ax_pareto.spines[spine].set_visible(False)

    heat_data = np.log10(source_target.astype(float) + 1.0)
    heat_data.columns = [_truncate_middle(col, 24) for col in heat_data.columns]
    source_target_labels.columns = heat_data.columns
    sns.heatmap(
        heat_data,
        ax=ax_heat,
        cmap="viridis",
        cbar=True,
        cbar_kws={"label": "log10(edge count + 1)", "shrink": 0.74, "pad": 0.015},
        linewidths=0.35,
        linecolor="#f3f3f3",
        annot=source_target_labels,
        fmt="",
        annot_kws={"fontsize": 6.8},
    )
    ax_heat.set_title("Source x target label-set blocks", fontsize=14, pad=10)
    ax_heat.set_xlabel("Target label set")
    ax_heat.set_ylabel("Source label set")
    ax_heat.tick_params(axis="x", rotation=58, labelsize=7.5)
    ax_heat.tick_params(axis="y", labelsize=8.5)

    okabe = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#999999", "#332288", "#882255"]
    left = np.zeros(len(composition_prop))
    y_positions = np.arange(len(composition_prop))
    for idx, rel in enumerate(composition_prop.columns):
        values = composition_prop[rel].to_numpy()
        ax_comp.barh(
            y_positions,
            values,
            left=left,
            color=okabe[idx % len(okabe)],
            edgecolor="white",
            linewidth=0.4,
            label=rel,
        )
        left += values
    source_totals = composition.sum(axis=1)
    ax_comp.set_yticks(y_positions)
    ax_comp.set_yticklabels([f"{_truncate_middle(src, 24)}\n{_format_count(source_totals[src])} edges" for src in composition_prop.index])
    ax_comp.invert_yaxis()
    ax_comp.set_xlim(0, 1)
    ax_comp.set_xlabel("Within-source edge proportion")
    ax_comp.set_title("Relationship composition differs by source surface", fontsize=14, pad=10)
    ax_comp.legend(
        frameon=False,
        bbox_to_anchor=(0.0, -0.16),
        loc="upper left",
        fontsize=7.2,
        title="Relationship",
        ncol=4,
        columnspacing=1.0,
        handlelength=1.5,
    )
    for spine in ["top", "right"]:
        ax_comp.spines[spine].set_visible(False)

    ax_top.barh(top_triples["bar_label"], top_triples["edge_count"], color="#2a9d8f", edgecolor="#1f4f4a", linewidth=0.4)
    ax_top.set_xscale("log")
    ax_top.set_xlabel("Edge count, log scale")
    ax_top.set_title("Top canonical schema triples", fontsize=14, pad=10)
    ax_top.tick_params(axis="y", labelsize=8)
    for y_idx, (_, row) in enumerate(top_triples.iterrows()):
        ax_top.text(
            row["edge_count"] * 1.04,
            y_idx,
            _format_count(row["edge_count"]),
            va="center",
            fontsize=8,
            color="#333333",
            clip_on=False,
        )
    for spine in ["top", "right"]:
        ax_top.spines[spine].set_visible(False)

    fig.suptitle("Full BRKG schema triple atlas", fontsize=24, weight="bold", y=0.982)
    fig.text(
        0.5,
        0.018,
        "Canonical label-set triples preserve edge counts exactly; source/target blocks reveal that BRKG is dominated by a few typed relation surfaces.",
        ha="center",
        fontsize=10.5,
        color="#444444",
    )
    fig.subplots_adjust(left=0.08, right=0.93, bottom=0.17, top=0.92, wspace=0.48, hspace=0.42)
    _save_current_figure("fig09_full_schema_triple_atlas")

    return {
        "available": True,
        **atlas_metrics,
        "metrics": str(metrics_path.relative_to(HERE)),
    }


def _cosine_distance_matrix(vectors: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = values / norms
    similarity = np.clip(unit @ unit.T, -1.0, 1.0)
    distance = 1.0 - similarity
    np.fill_diagonal(distance, 0.0)
    return distance


def _upper_triangle(matrix: np.ndarray) -> np.ndarray:
    idx = np.triu_indices_from(matrix, k=1)
    return matrix[idx]


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    rank_a = pd.Series(a).rank(method="average").to_numpy()
    rank_b = pd.Series(b).rank(method="average").to_numpy()
    return float(np.corrcoef(rank_a, rank_b)[0, 1])


def _neighbor_overlap(text_dist: np.ndarray, behavior_dist: np.ndarray, *, k: int) -> list[float]:
    overlaps: list[float] = []
    for row in range(text_dist.shape[0]):
        text_neighbors = [idx for idx in np.argsort(text_dist[row]) if idx != row][:k]
        behavior_neighbors = [idx for idx in np.argsort(behavior_dist[row]) if idx != row][:k]
        shared = set(text_neighbors) & set(behavior_neighbors)
        overlaps.append(len(shared) / float(k))
    return overlaps


def _pair_label(left: str, right: str) -> str:
    return f"{_clean_label(left, 24)} <-> {_clean_label(right, 24)}"


def _normalized_count(counts: dict[str, int], *keys: str) -> float:
    values = [math.log1p(float(counts.get(key, 0))) for key in keys]
    if not values:
        return 0.0
    denominator = max((math.log1p(float(value)) for value in counts.values()), default=1.0)
    return float(np.clip(max(values) / max(denominator, 1e-9), 0.0, 1.0))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _choose(options: list[str], idx: int, rng: np.random.Generator) -> str:
    if not options:
        return "unassigned"
    offset = int(rng.integers(0, len(options)))
    return options[(idx + offset) % len(options)]


PANEL_C_SPECS: list[dict[str, Any]] = [
    {
        "family": "QC / preprocessing",
        "modalities": ["fMRI", "sMRI", "dMRI"],
        "datasets": ["OpenNeuro", "OpenNeuro derivatives", "Neurodesk runtime"],
        "task_types": ["quality control", "confound inspection", "normalization"],
        "tool_families": ["preprocessing", "mriqc", "fmriprep", "segmentation"],
        "flags": {
            "needs_preprocessing": 1.0,
            "uses_spatial_map": 0.55,
            "uses_glm": 0.10,
            "uses_connectivity": 0.15,
            "uses_prediction": 0.05,
            "uses_diffusion": 0.25,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.10,
            "uses_evidence": 0.25,
            "uses_review": 0.45,
            "uses_memory": 0.30,
            "ood_novelty": 0.05,
            "constraint_load": 0.80,
            "evidence_strength": 0.35,
            "review_load": 0.55,
            "memory_reuse": 0.45,
            "benchmark_score": 0.50,
            "runtime_cost": 0.70,
        },
    },
    {
        "family": "Task GLM & activation",
        "modalities": ["fMRI", "behavior"],
        "datasets": ["OpenNeuro", "NeuroSynth", "NiMARE"],
        "task_types": ["task activation", "contrast estimation", "statistical map"],
        "tool_families": ["glm", "fitlins", "statistics", "nimare"],
        "flags": {
            "needs_preprocessing": 0.55,
            "uses_spatial_map": 0.95,
            "uses_glm": 1.00,
            "uses_connectivity": 0.10,
            "uses_prediction": 0.10,
            "uses_diffusion": 0.00,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.10,
            "uses_evidence": 0.55,
            "uses_review": 0.35,
            "uses_memory": 0.25,
            "ood_novelty": 0.05,
            "constraint_load": 0.55,
            "evidence_strength": 0.70,
            "review_load": 0.40,
            "memory_reuse": 0.35,
            "benchmark_score": 0.70,
            "runtime_cost": 0.55,
        },
    },
    {
        "family": "Connectivity / graph",
        "modalities": ["fMRI", "sMRI", "dMRI"],
        "datasets": ["OpenNeuro", "OpenNeuro derivatives", "clinical cohort"],
        "task_types": ["functional connectivity", "graph metric", "network comparison"],
        "tool_families": ["connectivity", "xcpd", "networkx", "statistics"],
        "flags": {
            "needs_preprocessing": 0.70,
            "uses_spatial_map": 0.60,
            "uses_glm": 0.15,
            "uses_connectivity": 1.00,
            "uses_prediction": 0.35,
            "uses_diffusion": 0.25,
            "uses_eeg_meg": 0.05,
            "uses_clinical": 0.35,
            "uses_evidence": 0.45,
            "uses_review": 0.40,
            "uses_memory": 0.30,
            "ood_novelty": 0.10,
            "constraint_load": 0.65,
            "evidence_strength": 0.55,
            "review_load": 0.45,
            "memory_reuse": 0.35,
            "benchmark_score": 0.60,
            "runtime_cost": 0.65,
        },
    },
    {
        "family": "Prediction & decoding",
        "modalities": ["fMRI", "sMRI", "behavior", "clinical"],
        "datasets": ["OpenNeuro", "clinical cohort", "benchmark cases"],
        "task_types": ["decoding", "prediction", "cross-validation"],
        "tool_families": ["machine learning", "sklearn", "statistics", "review"],
        "flags": {
            "needs_preprocessing": 0.45,
            "uses_spatial_map": 0.35,
            "uses_glm": 0.20,
            "uses_connectivity": 0.35,
            "uses_prediction": 1.00,
            "uses_diffusion": 0.05,
            "uses_eeg_meg": 0.05,
            "uses_clinical": 0.45,
            "uses_evidence": 0.35,
            "uses_review": 0.45,
            "uses_memory": 0.35,
            "ood_novelty": 0.20,
            "constraint_load": 0.65,
            "evidence_strength": 0.45,
            "review_load": 0.55,
            "memory_reuse": 0.45,
            "benchmark_score": 0.85,
            "runtime_cost": 0.60,
        },
    },
    {
        "family": "Diffusion / tractography",
        "modalities": ["dMRI", "sMRI"],
        "datasets": ["OpenNeuro derivatives", "clinical cohort", "Neurodesk runtime"],
        "task_types": ["tractography", "connectome", "diffusion QC"],
        "tool_families": ["diffusion", "tractography", "connectivity", "preprocessing"],
        "flags": {
            "needs_preprocessing": 0.80,
            "uses_spatial_map": 0.70,
            "uses_glm": 0.00,
            "uses_connectivity": 0.55,
            "uses_prediction": 0.20,
            "uses_diffusion": 1.00,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.35,
            "uses_evidence": 0.30,
            "uses_review": 0.45,
            "uses_memory": 0.25,
            "ood_novelty": 0.15,
            "constraint_load": 0.85,
            "evidence_strength": 0.40,
            "review_load": 0.55,
            "memory_reuse": 0.35,
            "benchmark_score": 0.55,
            "runtime_cost": 0.85,
        },
    },
    {
        "family": "EEG / MEG analysis",
        "modalities": ["EEG", "MEG", "iEEG"],
        "datasets": ["OpenNeuro", "clinical cohort", "benchmark cases"],
        "task_types": ["time frequency", "event-related response", "source localization"],
        "tool_families": ["mne", "signal processing", "statistics", "review"],
        "flags": {
            "needs_preprocessing": 0.75,
            "uses_spatial_map": 0.25,
            "uses_glm": 0.20,
            "uses_connectivity": 0.30,
            "uses_prediction": 0.25,
            "uses_diffusion": 0.00,
            "uses_eeg_meg": 1.00,
            "uses_clinical": 0.25,
            "uses_evidence": 0.35,
            "uses_review": 0.45,
            "uses_memory": 0.25,
            "ood_novelty": 0.10,
            "constraint_load": 0.75,
            "evidence_strength": 0.35,
            "review_load": 0.50,
            "memory_reuse": 0.30,
            "benchmark_score": 0.45,
            "runtime_cost": 0.55,
        },
    },
    {
        "family": "Clinical analysis",
        "modalities": ["clinical", "sMRI", "fMRI", "PET"],
        "datasets": ["clinical cohort", "OpenNeuro", "scholarly metadata"],
        "task_types": ["group comparison", "biomarker analysis", "outcome model"],
        "tool_families": ["statistics", "machine learning", "review", "metadata"],
        "flags": {
            "needs_preprocessing": 0.45,
            "uses_spatial_map": 0.45,
            "uses_glm": 0.30,
            "uses_connectivity": 0.30,
            "uses_prediction": 0.55,
            "uses_diffusion": 0.15,
            "uses_eeg_meg": 0.10,
            "uses_clinical": 1.00,
            "uses_evidence": 0.65,
            "uses_review": 0.70,
            "uses_memory": 0.40,
            "ood_novelty": 0.15,
            "constraint_load": 0.90,
            "evidence_strength": 0.60,
            "review_load": 0.75,
            "memory_reuse": 0.35,
            "benchmark_score": 0.60,
            "runtime_cost": 0.50,
        },
    },
    {
        "family": "Evidence synthesis",
        "modalities": ["literature", "fMRI", "behavior"],
        "datasets": ["NeuroSynth", "scholarly metadata", "NiMARE"],
        "task_types": ["meta-analysis", "evidence retrieval", "claim grounding"],
        "tool_families": ["literature search", "nimare", "rag", "metadata"],
        "flags": {
            "needs_preprocessing": 0.05,
            "uses_spatial_map": 0.60,
            "uses_glm": 0.25,
            "uses_connectivity": 0.10,
            "uses_prediction": 0.05,
            "uses_diffusion": 0.00,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.25,
            "uses_evidence": 1.00,
            "uses_review": 0.65,
            "uses_memory": 0.45,
            "ood_novelty": 0.10,
            "constraint_load": 0.45,
            "evidence_strength": 1.00,
            "review_load": 0.70,
            "memory_reuse": 0.55,
            "benchmark_score": 0.70,
            "runtime_cost": 0.35,
        },
    },
    {
        "family": "Scientific review",
        "modalities": ["literature", "runtime", "benchmark"],
        "datasets": ["scholarly metadata", "jobstore", "benchmark cases"],
        "task_types": ["artifact review", "method audit", "protocol critique"],
        "tool_families": ["review", "rubric", "metadata", "rag"],
        "flags": {
            "needs_preprocessing": 0.00,
            "uses_spatial_map": 0.15,
            "uses_glm": 0.10,
            "uses_connectivity": 0.10,
            "uses_prediction": 0.10,
            "uses_diffusion": 0.00,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.25,
            "uses_evidence": 0.85,
            "uses_review": 1.00,
            "uses_memory": 0.55,
            "ood_novelty": 0.10,
            "constraint_load": 0.70,
            "evidence_strength": 0.75,
            "review_load": 1.00,
            "memory_reuse": 0.65,
            "benchmark_score": 0.80,
            "runtime_cost": 0.25,
        },
    },
    {
        "family": "Memory & reuse",
        "modalities": ["memory", "runtime", "literature"],
        "datasets": ["jobstore", "scholarly metadata", "benchmark cases"],
        "task_types": ["route reuse", "case memory", "cache lookup"],
        "tool_families": ["memory", "metadata", "rag", "review"],
        "flags": {
            "needs_preprocessing": 0.05,
            "uses_spatial_map": 0.20,
            "uses_glm": 0.10,
            "uses_connectivity": 0.10,
            "uses_prediction": 0.20,
            "uses_diffusion": 0.00,
            "uses_eeg_meg": 0.00,
            "uses_clinical": 0.20,
            "uses_evidence": 0.60,
            "uses_review": 0.60,
            "uses_memory": 1.00,
            "ood_novelty": 0.25,
            "constraint_load": 0.45,
            "evidence_strength": 0.55,
            "review_load": 0.60,
            "memory_reuse": 1.00,
            "benchmark_score": 0.65,
            "runtime_cost": 0.20,
        },
    },
    {
        "family": "OOD ideation",
        "modalities": ["literature", "benchmark", "clinical", "behavior"],
        "datasets": ["scholarly metadata", "benchmark cases", "OpenNeuro"],
        "task_types": ["hypothesis generation", "OOD stress test", "route proposal"],
        "tool_families": ["ideation", "review", "rag", "metadata"],
        "flags": {
            "needs_preprocessing": 0.10,
            "uses_spatial_map": 0.25,
            "uses_glm": 0.15,
            "uses_connectivity": 0.20,
            "uses_prediction": 0.35,
            "uses_diffusion": 0.10,
            "uses_eeg_meg": 0.10,
            "uses_clinical": 0.35,
            "uses_evidence": 0.70,
            "uses_review": 0.75,
            "uses_memory": 0.70,
            "ood_novelty": 1.00,
            "constraint_load": 0.55,
            "evidence_strength": 0.55,
            "review_load": 0.75,
            "memory_reuse": 0.75,
            "benchmark_score": 0.50,
            "runtime_cost": 0.30,
        },
    },
]


def plot_task_embeddings(data: dict[str, Any]) -> dict[str, Any]:
    rows = data["neo4j"]["task_embeddings"]
    if not rows:
        return {"available": False}

    names = [str(row["name"]) for row in rows]
    text_vectors = np.asarray([row["text"] for row in rows], dtype=float)
    behavior_vectors = np.asarray([row["behavior"] for row in rows], dtype=float)

    text_dist = _cosine_distance_matrix(text_vectors)
    behavior_dist = _cosine_distance_matrix(behavior_vectors)
    text_pairs = _upper_triangle(text_dist)
    behavior_pairs = _upper_triangle(behavior_dist)
    distance_rho = _spearman(text_pairs, behavior_pairs)
    overlap_3 = _neighbor_overlap(text_dist, behavior_dist, k=3)
    overlap_5 = _neighbor_overlap(text_dist, behavior_dist, k=5)

    pair_i, pair_j = np.triu_indices_from(text_dist, k=1)
    pair_df = pd.DataFrame(
        {
            "task_a": [names[i] for i in pair_i],
            "task_b": [names[j] for j in pair_j],
            "pair": [_pair_label(names[i], names[j]) for i, j in zip(pair_i, pair_j)],
            "text_cosine_distance": text_pairs,
            "behavior_cosine_distance": behavior_pairs,
        }
    )
    pair_df["text_distance_percentile"] = pair_df["text_cosine_distance"].rank(pct=True)
    pair_df["behavior_distance_percentile"] = pair_df["behavior_cosine_distance"].rank(pct=True)
    pair_df["text_close_behavior_far"] = (
        pair_df["behavior_distance_percentile"] - pair_df["text_distance_percentile"]
    )
    pair_df["behavior_close_text_far"] = (
        pair_df["text_distance_percentile"] - pair_df["behavior_distance_percentile"]
    )
    pair_df = pair_df.sort_values("text_close_behavior_far", ascending=False)
    pair_df.to_csv(DATA_DIR / "task_embedding_pair_disagreements.csv", index=False)

    semantic_only = pair_df.head(12).iloc[::-1]
    behavior_only = pair_df.sort_values("behavior_close_text_far", ascending=False).head(12).iloc[::-1]

    fig, axes = plt.subplots(1, 2, figsize=(22, 9))
    sns.barplot(
        data=semantic_only,
        x="text_close_behavior_far",
        y="pair",
        ax=axes[0],
        color="#2a9d8f",
    )
    axes[0].set_title("Text-near, behavior-far task pairs")
    axes[0].set_xlabel("behavior distance rank minus text distance rank")
    axes[0].set_ylabel("")

    sns.barplot(
        data=behavior_only,
        x="behavior_close_text_far",
        y="pair",
        ax=axes[1],
        color="#e76f51",
    )
    axes[1].set_title("Behavior-near, text-far task pairs")
    axes[1].set_xlabel("text distance rank minus behavior distance rank")
    axes[1].set_ylabel("")

    fig.suptitle(
        "Task embedding disagreements: the informative unit is task pairs, not clusters",
        y=1.02,
    )
    fig.tight_layout()
    _save_current_figure("fig03_task_pair_disagreements")

    return {
        "available": True,
        "task_count": len(rows),
        "text_dim": int(text_vectors.shape[1]),
        "behavior_dim": int(behavior_vectors.shape[1]),
        "pairwise_distance_spearman": distance_rho,
        "mean_top3_neighbor_overlap": float(np.mean(overlap_3)),
        "mean_top5_neighbor_overlap": float(np.mean(overlap_5)),
        "top_text_close_behavior_far": semantic_only.iloc[::-1][
            ["task_a", "task_b", "text_close_behavior_far"]
        ].head(5).to_dict(orient="records"),
        "top_behavior_close_text_far": behavior_only.iloc[::-1][
            ["task_a", "task_b", "behavior_close_text_far"]
        ].head(5).to_dict(orient="records"),
    }


def _build_panel_c_routes(data: dict[str, Any], *, routes_per_family: int = 18) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    label_counts = {row["label"]: int(row["count"]) for row in data["neo4j"]["label_counts"]}
    rel_counts = {row["rel_type"]: int(row["count"]) for row in data["neo4j"]["relationship_counts"]}
    jobs_total = sum(int(count) for _, count in data["vm"].get("jobs_by_state", []))
    mcp_runs = int(data["vm"].get("mcp_run_inventory", {}).get("run_dirs", 0) or 0)
    runtime_total = max(1, jobs_total + mcp_runs)

    priors = {
        "spatial": max(
            _normalized_count(label_counts, "Coordinate", "StatsMap", "BrainRegion"),
            _normalized_count(rel_counts, "HAS_COORDINATE", "IN_REGION", "IN_SPACE"),
        ),
        "task": max(
            _normalized_count(label_counts, "Task", "Contrast", "Dataset"),
            _normalized_count(rel_counts, "HAS_CONTRAST", "MEASURES", "ABOUT"),
        ),
        "tool": max(
            _normalized_count(label_counts, "Tool", "ToolVersion"),
            _normalized_count(rel_counts, "COMPUTED_WITH", "HAS_VERSION", "IMPLEMENTS_FAMILY"),
        ),
        "evidence": max(
            _normalized_count(label_counts, "Publication", "Embedding", "Term"),
            _normalized_count(rel_counts, "HAS_TEXT_EMBEDDING", "HAS_TERM", "CITES"),
        ),
        "graph": max(
            _normalized_count(rel_counts, "BELONGS_TO", "DERIVED_FROM", "MAPS_TO"),
            _normalized_count(label_counts, "StatisticalMap", "Collection", "Concept"),
        ),
        "runtime": float(np.clip(math.log1p(runtime_total) / 9.0, 0.0, 1.0)),
        "memory": float(np.clip(math.log1p(mcp_runs) / 8.0, 0.0, 1.0)),
    }

    task_names = [str(row["name"]) for row in data["neo4j"].get("task_embeddings", [])]
    regions = [str(row["region"]) for row in data["neo4j"].get("statmap_region_counts", [])]
    concepts = [str(row["concept"]) for row in data["neo4j"].get("statmap_concept_counts", [])]
    anchors = {
        "task": task_names or ["task contrast"],
        "region": regions or ["brain region"],
        "concept": concepts or ["neuroscience concept"],
    }

    rows: list[dict[str, Any]] = []
    numeric_keys = list(PANEL_C_SPECS[0]["flags"].keys())
    for spec_idx, spec in enumerate(PANEL_C_SPECS):
        family = str(spec["family"])
        family_slug = _slug(family)
        flags = dict(spec["flags"])
        for idx in range(routes_per_family):
            modality = _choose(spec["modalities"], idx, rng)
            dataset = _choose(spec["datasets"], idx + spec_idx, rng)
            task_type = _choose(spec["task_types"], idx + 2 * spec_idx, rng)
            tool_family = _choose(spec["tool_families"], idx + 3 * spec_idx, rng)
            if flags.get("uses_spatial_map", 0.0) > 0.55:
                anchor = _choose(anchors["region"], idx, rng)
            elif flags.get("uses_evidence", 0.0) > 0.65:
                anchor = _choose(anchors["concept"], idx, rng)
            else:
                anchor = _choose(anchors["task"], idx, rng)

            row: dict[str, Any] = {
                "route_id": f"route_{family_slug}_{idx:02d}",
                "route_label": f"{dataset} + {modality} + {task_type} + {tool_family}",
                "analysis_family": family,
                "modality": modality,
                "dataset": dataset,
                "task_type": task_type,
                "tool_family": tool_family,
                "kg_anchor": anchor,
            }
            for key in numeric_keys:
                row[key] = float(np.clip(flags[key] + rng.normal(0.0, 0.065), 0.0, 1.0))

            row["kg_spatial_prior"] = float(np.clip(row["uses_spatial_map"] * priors["spatial"], 0.0, 1.0))
            row["kg_task_prior"] = float(np.clip(max(row["uses_glm"], row["uses_prediction"]) * priors["task"], 0.0, 1.0))
            row["kg_tool_prior"] = float(np.clip((0.45 + row["needs_preprocessing"] * 0.35) * priors["tool"], 0.0, 1.0))
            row["kg_evidence_prior"] = float(np.clip(row["uses_evidence"] * priors["evidence"], 0.0, 1.0))
            row["kg_graph_prior"] = float(np.clip(row["uses_connectivity"] * priors["graph"], 0.0, 1.0))
            row["runtime_prior"] = float(np.clip(row["runtime_cost"] * priors["runtime"], 0.0, 1.0))
            row["memory_prior"] = float(np.clip(row["memory_reuse"] * priors["memory"], 0.0, 1.0))
            rows.append(row)

    return pd.DataFrame(rows)


def _embed_panel_c_features(
    features: pd.DataFrame,
    *,
    n_neighbors: int = 14,
    min_dist: float = 0.28,
) -> tuple[np.ndarray, str]:
    scaled = StandardScaler().fit_transform(features)
    try:
        import umap

        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=n_neighbors,
            min_dist=min_dist,
            metric="euclidean",
            random_state=7,
        )
        return np.asarray(reducer.fit_transform(scaled), dtype=float), "UMAP"
    except Exception:
        from sklearn.manifold import TSNE

        reducer = TSNE(
            n_components=2,
            perplexity=18,
            init="pca",
            learning_rate="auto",
            random_state=7,
        )
        return np.asarray(reducer.fit_transform(scaled), dtype=float), "t-SNE fallback"


def _panel_c_families() -> list[str]:
    return [str(spec["family"]) for spec in PANEL_C_SPECS]


def _infer_panel_c_family(row: pd.Series) -> str:
    def flag(name: str) -> bool:
        return bool(float(row.get(name, 0) or 0) > 0)

    event_type = str(row.get("event_type", "") or "").lower()
    source = str(row.get("source", "") or "").lower()
    state = str(row.get("state", "") or "").lower()
    tool_id = str(row.get("tool_id", "") or "").lower()
    text = " ".join([event_type, source, state, tool_id])

    if flag("term_qc") or flag("term_preprocess"):
        return "QC / preprocessing"
    if flag("term_glm") or flag("term_activation"):
        return "Task GLM & activation"
    if flag("term_connectivity") or flag("term_graph"):
        return "Connectivity / graph"
    if flag("term_prediction") or flag("term_decoding"):
        return "Prediction & decoding"
    if flag("term_diffusion") or flag("term_tractography"):
        return "Diffusion / tractography"
    if flag("term_eeg") or flag("term_meg"):
        return "EEG / MEG analysis"
    if flag("term_clinical"):
        return "Clinical analysis"
    if flag("term_evidence") or flag("term_meta_analysis") or flag("term_neurosynth") or flag("term_nimare"):
        return "Evidence synthesis"
    if flag("term_ood"):
        return "OOD ideation"
    if flag("term_memory") or "cache" in text or "session" in text:
        return "Memory & reuse"
    if flag("term_review") or "review" in text or source == "mcp_run":
        return "Scientific review"
    if "tool_execution" in text or "tool" in tool_id:
        return "Memory & reuse"
    return "Scientific review"


def _build_panel_c_prod_states(data: dict[str, Any]) -> pd.DataFrame:
    vm = data.get("vm", {})
    rows = []
    rows.extend(vm.get("jobstore_episode_states") or [])
    rows.extend(vm.get("jobstore_jobs") or [])
    rows.extend(vm.get("mcp_run_states") or [])
    if not rows:
        return pd.DataFrame()

    states = pd.DataFrame(rows)
    for col in ["point_id", "source", "event_type", "kind", "state", "tool_id", "job_id"]:
        if col not in states.columns:
            states[col] = ""
        states[col] = states[col].fillna("").astype(str)
    states["analysis_family"] = states.apply(_infer_panel_c_family, axis=1)
    states["point_label"] = states["source"] + " / " + states["event_type"] + " / " + states["state"]
    return states


def _panel_c_feature_frame(points: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    ignore = {
        "point_id",
        "point_label",
        "source",
        "event_type",
        "kind",
        "state",
        "tool_id",
        "job_id",
        "analysis_family",
        "route_id",
        "route_label",
        "modality",
        "dataset",
        "task_type",
        "tool_family",
        "kg_anchor",
        "embedding_x",
        "embedding_y",
    }
    numeric_cols = [
        col
        for col in points.columns
        if col not in ignore and pd.api.types.is_numeric_dtype(points[col])
    ]
    categorical_cols = (
        ["source", "event_type", "kind", "state", "tool_id"]
        if mode == "prod_jobstore_episode_states"
        else ["modality", "dataset", "task_type", "tool_family"]
    )
    available_categories = [col for col in categorical_cols if col in points.columns]
    parts = [points[numeric_cols].astype(float).fillna(0.0)]
    if available_categories:
        parts.append(pd.get_dummies(points[available_categories].fillna(""), prefix=available_categories, dtype=float))
    return pd.concat(parts, axis=1)


def plot_panel_c_decision_space(data: dict[str, Any]) -> dict[str, Any]:
    families = _panel_c_families()
    states = _build_panel_c_prod_states(data)
    if not states.empty:
        points = states
        mode = "prod_jobstore_episode_states"
        feature_frame = _panel_c_feature_frame(points, mode=mode)
        coords, method = _embed_panel_c_features(feature_frame, n_neighbors=28, min_dist=0.08)
        csv_path = DATA_DIR / "panel_c_prod_episode_states.csv"
        title = f"Prod jobstore episode states form a dense analytic-state manifold (n={len(points):,})"
        caption = "Each point is a real prod job, job-audit state transition, or MCP run state; colors are inferred from payload/run features."
        point_size = 9
        alpha = 0.36
        edge_alpha = 0.0
    else:
        points = _build_panel_c_routes(data)
        points = points.rename(columns={"route_id": "point_id", "route_label": "point_label"})
        mode = "prototype_candidate_routes"
        feature_frame = _panel_c_feature_frame(points, mode=mode)
        coords, method = _embed_panel_c_features(feature_frame)
        csv_path = DATA_DIR / "panel_c_candidate_routes.csv"
        title = "Candidate routes form scientific neighborhoods from route metadata, KG support, and run/review priors"
        caption = "Each point is a candidate analytic route prototype. Family labels are colors, not direct embedding features."
        point_size = 64
        alpha = 0.90
        edge_alpha = 0.35

    points["embedding_x"] = coords[:, 0]
    points["embedding_y"] = coords[:, 1]

    scaled = StandardScaler().fit_transform(feature_frame)
    family_values = points["analysis_family"].to_numpy()
    neighbor_count = min(6, len(points))
    neighbors = NearestNeighbors(n_neighbors=neighbor_count).fit(scaled).kneighbors(scaled, return_distance=False)
    purity = []
    for idx, row in enumerate(neighbors):
        peer_idx = [int(peer) for peer in row if int(peer) != idx][: max(1, neighbor_count - 1)]
        purity.append(float(np.mean(family_values[peer_idx] == family_values[idx])) if peer_idx else 1.0)
    family_codes = points["analysis_family"].astype("category").cat.codes.to_numpy()
    silhouette = float(silhouette_score(scaled, family_codes)) if len(set(family_codes)) > 1 else 1.0

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    points.to_csv(csv_path, index=False)

    colors = [
        "#2a9d8f",
        "#e76f51",
        "#457b9d",
        "#f4a261",
        "#6d597a",
        "#8ab17d",
        "#b56576",
        "#118ab2",
        "#ef476f",
        "#073b4c",
        "#a7c957",
    ]
    palette = dict(zip(families, colors))

    sns.set_theme(style="white", context="talk")
    fig, ax = plt.subplots(figsize=(15.5, 10.5))

    if edge_alpha > 0:
        edge_neighbors = NearestNeighbors(n_neighbors=4).fit(scaled).kneighbors(scaled, return_distance=False)
        seen_edges: set[tuple[int, int]] = set()
        for src, row in enumerate(edge_neighbors):
            for dst in row[1:]:
                edge = tuple(sorted((int(src), int(dst))))
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                ax.plot(
                    [points.loc[edge[0], "embedding_x"], points.loc[edge[1], "embedding_x"]],
                    [points.loc[edge[0], "embedding_y"], points.loc[edge[1], "embedding_y"]],
                    color="#b8c0c8",
                    linewidth=0.45,
                    alpha=edge_alpha,
                    zorder=1,
                )

    draw_order = sorted(families, key=lambda name: int((points["analysis_family"] == name).sum()))
    for family in draw_order:
        group = points[points["analysis_family"] == family]
        if group.empty:
            continue
        ax.scatter(
            group["embedding_x"],
            group["embedding_y"],
            s=point_size,
            color=palette[family],
            label=family,
            alpha=alpha,
            edgecolors="#242424",
            linewidth=0.0 if mode == "prod_jobstore_episode_states" else 0.35,
            rasterized=mode == "prod_jobstore_episode_states",
            zorder=2,
        )

    for family, group in points.groupby("analysis_family", sort=False):
        if mode == "prod_jobstore_episode_states" and len(group) < 50:
            continue
        label = _clean_label(family, 28)
        if mode == "prod_jobstore_episode_states":
            label = f"{label}\nn={len(group):,}"
        ax.text(
            float(group["embedding_x"].median()),
            float(group["embedding_y"].median()),
            label,
            ha="center",
            va="center",
            fontsize=9.5 if mode == "prod_jobstore_episode_states" else 10.5,
            weight="bold",
            color="#222222",
            bbox={
                "boxstyle": "round,pad=0.26",
                "facecolor": "white",
                "edgecolor": "#333333",
                "linewidth": 0.6,
                "alpha": 0.86,
            },
            zorder=3,
        )

    ax.set_xlabel(f"{method} 1")
    ax.set_ylabel(f"{method} 2")
    ax.set_title(title, pad=16, fontsize=15)
    fig.suptitle("c. Analytic decision space", y=0.985, fontsize=28, weight="bold")
    legend = ax.legend(
        title="Scientific region",
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=False,
        fontsize=10,
        title_fontsize=11,
        markerscale=3.0,
    )
    for handle in legend.legend_handles:
        try:
            handle.set_alpha(1.0)
            handle.set_sizes([65])
        except Exception:
            pass
    ax.grid(True, color="#e8e8e8", linewidth=0.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(
        0.50,
        0.022,
        caption,
        ha="center",
        fontsize=10.5,
        color="#444444",
    )
    fig.tight_layout(rect=[0.02, 0.05, 0.82, 0.94])
    _save_current_figure("fig06_panel_c_analytic_decision_space")

    return {
        "available": True,
        "mode": mode,
        "point_count": int(len(points)),
        "route_count": int(len(points)),
        "family_count": int(len(families)),
        "feature_count": int(feature_frame.shape[1]),
        "embedding_method": method,
        "silhouette_by_family": silhouette,
        "mean_top5_neighbor_family_purity": float(np.mean(purity)),
        "route_csv": str(csv_path.relative_to(HERE)),
        "source_counts": points["source"].value_counts().head(12).to_dict() if "source" in points else {},
        "family_counts": points["analysis_family"].value_counts().to_dict(),
    }


def _score01(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    if len(values) == 0:
        return values
    low = float(values.min())
    high = float(values.max())
    if not np.isfinite(low) or not np.isfinite(high) or abs(high - low) < 1e-12:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return ((values - low) / (high - low)).clip(0.0, 1.0)


def _bool_score(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).astype(float).clip(0.0, 1.0)


def _state_contains(frame: pd.DataFrame, column: str, pattern: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index)
    return frame[column].fillna("").astype(str).str.lower().str.contains(pattern, regex=True).astype(float)


def _build_panel_d_feature_scores(points: pd.DataFrame) -> pd.DataFrame:
    scored = points.copy()
    success = _state_contains(scored, "state", "succeeded|complete|done")
    failure = _state_contains(scored, "state", "failed|error|cancel")
    error = _bool_score(scored, "error_present").clip(lower=failure)
    has_run = _bool_score(scored, "run_id_present")
    has_dir = _bool_score(scored, "run_dir_present")
    has_project = _bool_score(scored, "project_present")
    has_trace = _bool_score(scored, "has_trace")
    has_tool_trace = _bool_score(scored, "has_tool_trace")
    has_research_events = _bool_score(scored, "has_research_events")
    has_observation = _bool_score(scored, "has_observation")
    has_trajectory = _bool_score(scored, "has_trajectory")
    has_review = _bool_score(scored, "has_review_verdict")
    artifact = _bool_score(scored, "artifact_count")
    session = _bool_score(scored, "session_present")

    payload_keys = _score01(np.log1p(pd.to_numeric(scored.get("payload_key_count", 0), errors="coerce").fillna(0)))
    payload_len = _score01(np.log1p(pd.to_numeric(scored.get("payload_text_len", 0), errors="coerce").fillna(0)))
    prompt_len = _score01(np.log1p(pd.to_numeric(scored.get("prompt_len", 0), errors="coerce").fillna(0)))
    steps = _score01(np.log1p(pd.to_numeric(scored.get("step_count", 0), errors="coerce").fillna(0)))
    plan_events = _score01(np.log1p(pd.to_numeric(scored.get("plan_event_count", 0), errors="coerce").fillna(0)))
    trace_events = _score01(np.log1p(pd.to_numeric(scored.get("trace_event_count", 0), errors="coerce").fillna(0)))
    tool_trace_events = _score01(np.log1p(pd.to_numeric(scored.get("tool_trace_event_count", 0), errors="coerce").fillna(0)))
    attempts = _score01(pd.to_numeric(scored.get("attempt", 0), errors="coerce").fillna(0))
    duration = _score01(np.log1p(pd.to_numeric(scored.get("duration_s", 0), errors="coerce").fillna(0)))

    term_qc = _bool_score(scored, "term_qc")
    term_preprocess = _bool_score(scored, "term_preprocess")
    term_glm = _bool_score(scored, "term_glm")
    term_activation = _bool_score(scored, "term_activation")
    term_connectivity = _bool_score(scored, "term_connectivity")
    term_graph = _bool_score(scored, "term_graph")
    term_prediction = _bool_score(scored, "term_prediction")
    term_decoding = _bool_score(scored, "term_decoding")
    term_evidence = _bool_score(scored, "term_evidence")
    term_review = _bool_score(scored, "term_review")
    term_memory = _bool_score(scored, "term_memory")
    term_ood = _bool_score(scored, "term_ood")
    term_openneuro = _bool_score(scored, "term_openneuro")
    term_neurosynth = _bool_score(scored, "term_neurosynth")
    term_nimare = _bool_score(scored, "term_nimare")

    provenance = (
        0.16 * has_run
        + 0.16 * has_dir
        + 0.12 * has_project
        + 0.12 * has_trace
        + 0.10 * has_tool_trace
        + 0.12 * has_research_events
        + 0.10 * has_observation
        + 0.07 * artifact
        + 0.05 * payload_keys
    ).clip(0.0, 1.0)
    review_activity = (
        0.36 * term_review
        + 0.24 * has_review
        + 0.16 * plan_events
        + 0.14 * trace_events
        + 0.10 * _state_contains(scored, "event_type", "review|step|status")
    ).clip(0.0, 1.0)
    memory_reuse_count = (
        term_memory
        + session
        + has_trajectory
        + (plan_events > 0).astype(float)
        + (trace_events > 0).astype(float)
        + (tool_trace_events > 0).astype(float)
    )
    memory_reuse = (memory_reuse_count / 6.0).clip(0.0, 1.0)
    conflict_density = (
        0.34 * error
        + 0.20 * failure
        + 0.16 * attempts
        + 0.14 * _state_contains(scored, "event_type", "failed|error|cancel|recovered")
        + 0.10 * (1.0 - success)
        + 0.06 * duration
    ).clip(0.0, 1.0)
    admissibility = (
        0.30 * success
        + 0.20 * (1.0 - error)
        + 0.16 * provenance
        + 0.12 * has_project
        + 0.10 * has_run
        + 0.07 * (1.0 - attempts)
        + 0.05 * artifact
    ).clip(0.0, 1.0)

    gsr_sensitivity = (
        0.26 * term_connectivity
        + 0.20 * term_preprocess
        + 0.18 * term_qc
        + 0.16 * term_glm
        + 0.10 * term_openneuro
        + 0.10 * term_graph
    ).clip(0.0, 1.0)
    hrf_completeness = (
        0.30 * term_glm
        + 0.22 * term_activation
        + 0.15 * steps
        + 0.13 * provenance
        + 0.10 * term_openneuro
        + 0.10 * payload_keys
    ).clip(0.0, 1.0)
    leakage_risk = (
        0.26 * term_prediction
        + 0.22 * term_decoding
        + 0.16 * term_openneuro
        + 0.14 * (1.0 - provenance)
        + 0.12 * prompt_len
        + 0.10 * conflict_density
    ).clip(0.0, 1.0)
    ood_novelty = (
        0.42 * term_ood
        + 0.20 * term_prediction
        + 0.16 * term_decoding
        + 0.12 * prompt_len
        + 0.10 * (1.0 - provenance)
    ).clip(0.0, 1.0)
    robustness = (
        0.20 * success
        + 0.18 * provenance
        + 0.14 * has_tool_trace
        + 0.12 * has_trajectory
        + 0.10 * has_review
        + 0.10 * tool_trace_events
        + 0.08 * term_evidence
        + 0.04 * term_neurosynth
        + 0.04 * term_nimare
    ).clip(0.0, 1.0)

    scored["admissibility_score"] = admissibility
    scored["provenance_score"] = provenance
    scored["gsr_sensitivity_score"] = gsr_sensitivity
    scored["hrf_completeness_score"] = hrf_completeness
    scored["leakage_risk_score"] = leakage_risk
    scored["conflict_density"] = conflict_density
    scored["review_activity"] = review_activity
    scored["memory_reuse_count"] = memory_reuse_count
    scored["memory_reuse_score"] = memory_reuse
    scored["ood_novelty_score"] = ood_novelty
    scored["robustness_score"] = robustness
    return scored


def plot_panel_d_feature_signatures(data: dict[str, Any]) -> dict[str, Any]:
    panel_c_path = DATA_DIR / "panel_c_prod_episode_states.csv"
    if panel_c_path.exists():
        points = pd.read_csv(panel_c_path, low_memory=False)
    else:
        points = _build_panel_c_prod_states(data)
    if points.empty or "embedding_x" not in points.columns or "embedding_y" not in points.columns:
        return {"available": False}

    scored = _build_panel_d_feature_scores(points)
    feature_defs = [
        ("Admissibility", "admissibility_score"),
        ("Provenance completeness", "provenance_score"),
        ("GSR sensitivity", "gsr_sensitivity_score"),
        ("HRF completeness", "hrf_completeness_score"),
        ("Leakage risk", "leakage_risk_score"),
        ("Conflict density", "conflict_density"),
        ("Review activity", "review_activity"),
        ("Memory reuse", "memory_reuse_score"),
        ("OOD novelty", "ood_novelty_score"),
        ("Backend robustness", "robustness_score"),
    ]

    out_cols = [
        "point_id",
        "source",
        "event_type",
        "kind",
        "state",
        "analysis_family",
        "embedding_x",
        "embedding_y",
    ] + [column for _, column in feature_defs] + ["memory_reuse_count"]
    score_csv = DATA_DIR / "panel_d_feature_signatures.csv"
    scored[out_cols].to_csv(score_csv, index=False)

    sns.set_theme(style="white", context="talk")
    fig, axes = plt.subplots(2, 5, figsize=(24, 10.8), sharex=True, sharey=True)
    cmap = sns.light_palette("#0f8f8f", as_cmap=True)
    x = pd.to_numeric(scored["embedding_x"], errors="coerce")
    y = pd.to_numeric(scored["embedding_y"], errors="coerce")
    valid = x.notna() & y.notna()

    last_scatter = None
    for ax, (title, column) in zip(axes.flat, feature_defs):
        values = pd.to_numeric(scored[column], errors="coerce").fillna(0.0).clip(0.0, 1.0)
        ax.scatter(x[valid], y[valid], s=2.0, color="#c7c7c7", alpha=0.12, linewidth=0, rasterized=True)
        active = valid & (values > 0.02)
        last_scatter = ax.scatter(
            x[active],
            y[active],
            c=values[active],
            s=5.0,
            cmap=cmap,
            vmin=0.0,
            vmax=1.0,
            alpha=0.86,
            linewidth=0,
            rasterized=True,
        )
        ax.set_title(title, fontsize=13, pad=8)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    if last_scatter is not None:
        cax = fig.add_axes([0.865, 0.075, 0.095, 0.018])
        cbar = fig.colorbar(last_scatter, cax=cax, orientation="horizontal")
        cbar.set_ticks([0.0, 1.0])
        cbar.set_ticklabels(["Low", "High"])
        cbar.outline.set_visible(False)

    fig.suptitle("d. Feature signatures across the space", y=0.992, fontsize=28, weight="bold")
    fig.text(
        0.50,
        0.035,
        "Scientific properties are localized across the prod episode-state decision space; scores are transparent proxies from jobstore and run-artifact fields.",
        ha="center",
        fontsize=11,
        color="#444444",
    )
    fig.tight_layout(rect=[0.02, 0.07, 0.98, 0.94])
    _save_current_figure("fig07_panel_d_feature_signatures")

    return {
        "available": True,
        "point_count": int(len(scored)),
        "feature_count": int(len(feature_defs)),
        "score_csv": str(score_csv.relative_to(HERE)),
        "feature_means": {column: float(scored[column].mean()) for _, column in feature_defs},
    }


def plot_tool_and_runtime(data: dict[str, Any]) -> None:
    tools = _to_frame(data["neo4j"]["tool_family_counts"]).head(25)
    jobs_state = pd.DataFrame(data["vm"]["jobs_by_state"], columns=["state", "count"])
    jobs_kind = pd.DataFrame(data["vm"]["jobs_by_kind"], columns=["kind", "count"])
    studio = pd.DataFrame(data["vm"]["studio_runtime_status"], columns=["kind", "status", "count"])

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    sns.barplot(data=tools, x="tools", y="family", ax=axes[0, 0], color="#457b9d")
    axes[0, 0].set_title("Tool families")
    axes[0, 0].set_xlabel("tools")
    axes[0, 0].set_ylabel("")

    sns.barplot(data=jobs_state, x="state", y="count", ax=axes[0, 1], palette=["#2a9d8f", "#e76f51"])
    axes[0, 1].set_title("Job states")
    axes[0, 1].set_xlabel("")
    axes[0, 1].set_ylabel("jobs")

    sns.barplot(data=jobs_kind.head(12), x="kind", y="count", ax=axes[1, 0], color="#e9c46a")
    axes[1, 0].set_title("Job kinds")
    axes[1, 0].tick_params(axis="x", rotation=25)
    axes[1, 0].set_xlabel("")
    axes[1, 0].set_ylabel("jobs")

    if not studio.empty:
        pivot = studio.pivot_table(index="kind", columns="status", values="count", fill_value=0)
        sns.heatmap(pivot, annot=True, fmt=".0f", cmap="YlGnBu", ax=axes[1, 1], cbar=False)
    axes[1, 1].set_title("Studio runtime sessions")
    axes[1, 1].set_xlabel("status")
    axes[1, 1].set_ylabel("runtime")

    fig.suptitle("Tools and runtime/job telemetry should be plotted separately from scientific KG structure", y=1.02)
    fig.tight_layout()
    _save_current_figure("fig04_tool_and_runtime_surfaces")


def plot_spatial_and_storage(data: dict[str, Any]) -> None:
    regions = _to_frame(data["neo4j"]["statmap_region_counts"]).head(25)
    concepts = _to_frame(data["neo4j"]["statmap_concept_counts"]).head(20)
    storage = pd.DataFrame(data["vm"]["storage_files"])
    if not storage.empty:
        storage = storage.sort_values("bytes", ascending=False).head(20)
        storage["mb"] = storage["bytes"] / (1024 * 1024)
        storage["label"] = storage["name"].map(lambda x: _clean_label(x, 34))

    fig, axes = plt.subplots(1, 3, figsize=(21, 9))
    sns.barplot(data=regions, x="count", y="region", ax=axes[0], color="#8ab17d")
    axes[0].set_title("StatsMap -> BrainRegion")
    axes[0].set_xlabel("edges")
    axes[0].set_ylabel("")

    sns.barplot(data=concepts, x="count", y="concept", ax=axes[1], color="#b56576")
    axes[1].set_title("StatsMap -> Concept")
    axes[1].set_xlabel("edges")
    axes[1].set_ylabel("")

    if not storage.empty:
        sns.barplot(data=storage, x="mb", y="label", ax=axes[2], color="#6d597a")
    axes[2].set_title("Largest bounded storage files")
    axes[2].set_xlabel("MB")
    axes[2].set_ylabel("")

    fig.suptitle("Spatial/statistical map assets are their own view: region load, concept load, file inventory", y=1.02)
    fig.tight_layout()
    _save_current_figure("fig05_spatial_and_storage_surfaces")


def write_summary(
    data: dict[str, Any],
    schema_heatmap_stats: dict[str, Any],
    full_schema_atlas_stats: dict[str, Any],
    cluster_stats: dict[str, Any],
    panel_c_stats: dict[str, Any],
    panel_d_stats: dict[str, Any],
) -> None:
    labels = data["neo4j"]["label_counts"]
    rels = data["neo4j"]["relationship_counts"]
    emb = data["neo4j"]["embedding_inventory"]
    statsmap = data["neo4j"]["statsmap_runs"][0] if data["neo4j"]["statsmap_runs"] else {}
    mcp = data["vm"]["mcp_run_inventory"]
    jobs = data["vm"]["jobs_by_state"]

    text = [
        "# Prod BRKG Plot Probe",
        "",
        "Generated from bounded prod queries through `${GCE_VM_NAME}` and `brain-researcher-br_kg-0`.",
        "",
        "## Generated Figures",
        "",
        "- `figures/fig01_node_and_edge_counts.png`: label and relationship count imbalance.",
        "- `figures/fig02_schema_triple_network.png`: top source-label / edge / target-label structure.",
        "- `figures/fig03_task_pair_disagreements.png`: task pairs where text and behavior embeddings disagree.",
        "- `figures/fig04_tool_and_runtime_surfaces.png`: tool families plus job/studio runtime telemetry.",
        "- `figures/fig05_spatial_and_storage_surfaces.png`: StatsMap region/concept load plus bounded storage files.",
        "- `figures/fig06_panel_c_analytic_decision_space.png`: Panel C embedding of prod episode states.",
        "- `figures/fig07_panel_d_feature_signatures.png`: Panel D small multiples of feature signatures over Panel C.",
        "- `figures/fig08_kg_schema_triple_heatmap.png`: source-label x relationship / target-label schema triple heatmaps.",
        "- `figures/fig09_full_schema_triple_atlas.png`: full canonical schema-triple concentration and source/target surface atlas.",
        "",
        "## What To Separate",
        "",
        "1. **Scientific KG structure**: labels, edge types, and schema triples. Do not mix this with job telemetry.",
        "2. **Embedding maps**: task text/behavior embeddings and publication embeddings. Treat these as vector-space views, not graph-count views.",
        "3. **Tool capability surface**: Tool, ToolVersion, ToolFamily, modality/resource edges. This is a capability taxonomy view.",
        "4. **Spatial/statmap surface**: StatsMap, BrainRegion, Concept, TemplateSpace, Coordinate, NIfTI/map assets.",
        "5. **Runtime/jobstore surface**: jobs, audit events, MCP runs, studio runtime sessions.",
        "",
        "## Key Counts",
        "",
        f"- Top node label: `{labels[0]['label']}` = {labels[0]['count']:,}.",
        f"- Top edge type: `{rels[0]['rel_type']}` = {rels[0]['count']:,}.",
    ]

    if emb:
        first = emb[0]
        text.append(
            f"- Embedding inventory: {first['count']:,} `{first['kind']}` embeddings, "
            f"model `{first['model']}`, dim {first['dim']}."
        )
    if statsmap:
        text.append(
            f"- StatsMap run surface: {statsmap.get('statmaps', 0):,} statmaps across "
            f"{statsmap.get('distinct_runs', 0)} distinct run values."
        )
    if jobs:
        text.append("- Job states: " + ", ".join(f"{state}={count}" for state, count in jobs) + ".")
    if mcp:
        text.append(f"- MCP run directories: {mcp.get('run_dirs', 0):,}.")

    text += [
        "",
        "## KG Schema Triple Heatmap",
        "",
    ]
    if schema_heatmap_stats.get("available"):
        top = schema_heatmap_stats["top_triple"]
        text += [
            f"- Top schema-triple rows used: n={schema_heatmap_stats['triple_rows']} bounded prod triples.",
            f"- Edge count represented in those rows: {schema_heatmap_stats['triple_edge_count']:,}.",
            f"- Dominant triple: `{top['schema_triple']}` = {top['count']:,} edges "
            f"({top['count_share']:.1%} of represented top-triple edges).",
            f"- Heatmap table: `{schema_heatmap_stats['csv']}`.",
            "- Interpretation: BRKG is not a homogeneous graph; its largest surfaces are source-specific schema blocks such as map membership, publication terms/coordinates, and StatsMap spatial/model relations.",
        ]
        if schema_heatmap_stats.get("top_sources"):
            text.append(
                "- Top source labels by represented edges: "
                + ", ".join(f"{key}={value:,}" for key, value in schema_heatmap_stats["top_sources"].items())
                + "."
            )
        if schema_heatmap_stats.get("top_relationships"):
            text.append(
                "- Top relationship types by represented edges: "
                + ", ".join(f"{key}={value:,}" for key, value in schema_heatmap_stats["top_relationships"].items())
                + "."
            )
    else:
        text.append("- KG schema triple heatmap was skipped because schema triples were unavailable.")

    text += [
        "",
        "## Full KG Schema Triple Atlas",
        "",
    ]
    if full_schema_atlas_stats.get("available"):
        text += [
            f"- Canonical label-set schema triples: n={full_schema_atlas_stats['schema_triple_count']:,}, "
            f"edge sum={full_schema_atlas_stats['total_edges']:,}.",
            f"- Edge concentration: top-1={full_schema_atlas_stats['top1_share']:.1%}, "
            f"top-3={full_schema_atlas_stats['top3_share']:.1%}, "
            f"top-10={full_schema_atlas_stats['top10_share']:.1%}.",
            f"- Triples needed to cover graph mass: 90%={full_schema_atlas_stats['rank_for_90pct']}, "
            f"95%={full_schema_atlas_stats['rank_for_95pct']}, "
            f"99%={full_schema_atlas_stats['rank_for_99pct']}.",
            f"- Atlas metrics: `{full_schema_atlas_stats['metrics']}`.",
            "- Canonical export: `data/kg_schema_triples_full_labelsets.csv`.",
            "- Heatmap-friendly export: `data/kg_schema_triples_full_unwound_labels.csv`.",
            "- Interpretation: the full graph is dominated by a small number of typed schema surfaces, so paper figures should use schema blocks and Pareto concentration rather than a node-link network.",
        ]
    else:
        reason = full_schema_atlas_stats.get("reason", "full schema export unavailable")
        text.append(f"- Full schema triple atlas was skipped: {reason}.")

    text += [
        "",
        "## Task Embedding Diagnostic",
        "",
    ]
    if cluster_stats.get("available"):
        text += [
            f"- Task text embeddings: n={cluster_stats['task_count']}, dim={cluster_stats['text_dim']}.",
            f"- Task behavior embeddings: n={cluster_stats['task_count']}, dim={cluster_stats['behavior_dim']}.",
            f"- Pairwise text-vs-behavior distance agreement: Spearman rho={cluster_stats['pairwise_distance_spearman']:.3f}.",
            f"- Shared nearest-neighbor fraction: top-3={cluster_stats['mean_top3_neighbor_overlap']:.3f}, "
            f"top-5={cluster_stats['mean_top5_neighbor_overlap']:.3f}.",
            "- Interpretation: the useful view is task-pair disagreement, not clusters.",
            "- Full task-pair table: `data/task_embedding_pair_disagreements.csv`.",
        ]
        if cluster_stats.get("top_text_close_behavior_far"):
            text += ["", "Top text-close / behavior-far pairs:"]
            for row in cluster_stats["top_text_close_behavior_far"]:
                text.append(
                    f"- `{row['task_a']}` <-> `{row['task_b']}` "
                    f"(rank gap {row['text_close_behavior_far']:.3f})"
                )
        if cluster_stats.get("top_behavior_close_text_far"):
            text += ["", "Top behavior-close / text-far pairs:"]
            for row in cluster_stats["top_behavior_close_text_far"]:
                text.append(
                    f"- `{row['task_a']}` <-> `{row['task_b']}` "
                    f"(rank gap {row['behavior_close_text_far']:.3f})"
                )
    else:
        text.append("- Task embedding diagnostic was skipped because task vectors were unavailable.")

    text += [
        "",
        "## Panel C Analytic Decision Space",
        "",
    ]
    if panel_c_stats.get("available"):
        if panel_c_stats.get("mode") == "prod_jobstore_episode_states":
            text += [
                f"- Prod episode-state points: n={panel_c_stats['point_count']} across "
                f"{panel_c_stats['family_count']} inferred scientific regions.",
                f"- Sources: "
                + ", ".join(f"{key}={value}" for key, value in panel_c_stats.get("source_counts", {}).items())
                + ".",
                f"- Embedding method: {panel_c_stats['embedding_method']}; feature columns={panel_c_stats['feature_count']}.",
                f"- Region structure diagnostic: silhouette={panel_c_stats['silhouette_by_family']:.3f}; "
                f"mean top-5 same-region neighbor fraction={panel_c_stats['mean_top5_neighbor_family_purity']:.3f}.",
                f"- Episode-state table: `{panel_c_stats['route_csv']}`.",
                "- Interpretation: this panel now uses real prod jobstore states, job-level records, and MCP run records rather than only hand-built route prototypes.",
                "- Caveat: scientific region colors are inferred from job payload/run-artifact features; they are not human-curated labels.",
            ]
        else:
            text += [
                f"- Candidate analytic route prototypes: n={panel_c_stats['route_count']} across "
                f"{panel_c_stats['family_count']} scientific regions.",
                f"- Embedding method: {panel_c_stats['embedding_method']}; feature columns={panel_c_stats['feature_count']}.",
                f"- Region structure diagnostic: silhouette={panel_c_stats['silhouette_by_family']:.3f}; "
                f"mean top-5 same-region neighbor fraction={panel_c_stats['mean_top5_neighbor_family_purity']:.3f}.",
                f"- Route table: `{panel_c_stats['route_csv']}`.",
                "- Interpretation: this panel shows a candidate decision-space prototype from route metadata, tool/workflow fields, KG support priors, and runtime/review/memory features.",
                "- Caveat: this is not yet an executed-route or full episode-state embedding. Replace the prototype rows with planner-emitted route records when those become available.",
            ]
    else:
        text.append("- Panel C was skipped because route features could not be generated.")

    text += [
        "",
        "## Panel D Feature Signatures",
        "",
    ]
    if panel_d_stats.get("available"):
        text += [
            f"- Feature overlays: {panel_d_stats['feature_count']} signatures over "
            f"{panel_d_stats['point_count']:,} Panel C points.",
            f"- Feature table: `{panel_d_stats['score_csv']}`.",
            "- Included signatures: admissibility, provenance completeness, GSR sensitivity, HRF completeness, leakage risk, conflict density, review activity, memory reuse, OOD novelty, and backend robustness.",
            "- Interpretation: feature intensity is spatially localized across the same UMAP background, so properties can be inspected independently of cluster labels.",
            "- Caveat: these are proxy scores derived from available jobstore/run-artifact fields. GSR, HRF, leakage, and robustness should become direct route fields for a final paper panel.",
        ]
        means = panel_d_stats.get("feature_means") or {}
        if means:
            text.append("- Mean proxy scores: " + ", ".join(f"{key}={value:.2f}" for key, value in means.items()) + ".")
    else:
        text.append("- Panel D was skipped because Panel C coordinates were unavailable.")

    text += [
        "",
        "## Caveats",
        "",
        "- This is a bounded plot probe, not a full benchmark or a full data export.",
        "- Publication embeddings are represented in inventory and graph links here; raw publication vector extraction was intentionally not pulled into this first pack.",
        "- OpenNeuro paths are mounted by `s3fs`; broad recursive scans were avoided.",
        "",
    ]
    SUMMARY_PATH.write_text("\n".join(text), encoding="utf-8")


def main() -> None:
    force = "--force" in os.sys.argv
    data = fetch_data(force=force)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    plot_counts(data)
    plot_schema_network(data)
    schema_heatmap_stats = plot_schema_triple_heatmap(data)
    full_schema_atlas_stats = plot_full_schema_triple_atlas(data)
    cluster_stats = plot_task_embeddings(data)
    plot_tool_and_runtime(data)
    plot_spatial_and_storage(data)
    panel_c_stats = plot_panel_c_decision_space(data)
    panel_d_stats = plot_panel_d_feature_signatures(data)
    write_summary(data, schema_heatmap_stats, full_schema_atlas_stats, cluster_stats, panel_c_stats, panel_d_stats)

    print(f"Wrote {DATA_PATH}")
    print(f"Wrote figures to {FIG_DIR}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
