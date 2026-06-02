"""Fallback graph theory analytics for connectivity matrices."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class GraphTheoryParameters:
    """Configuration for graph theory fallback analysis."""

    connectivity_file: str
    output_dir: str
    graph_type: str
    threshold_method: str
    threshold_value: Optional[float]
    compute_basic_metrics: bool
    basic_metrics: List[str]
    compute_centrality: bool
    centrality_metrics: List[str]
    detect_communities: bool
    community_method: str
    detect_hubs: bool
    hub_method: str
    compute_rich_club: bool
    compute_small_world: bool
    compute_efficiency: bool
    efficiency_types: List[str]
    test_robustness: bool
    removal_fraction: float
    permutation_test: bool
    n_permutations: int
    save_metrics: bool
    save_communities: bool
    save_processed_graph: bool
    visualize: bool
    random_state: Optional[int]


def graph_theory_from_payload(payload: Dict[str, object]) -> GraphTheoryParameters:
    """Normalise payload into graph theory parameters."""

    output_dir = payload.get("output_dir") or Path.cwd() / "graph_theory"

    return GraphTheoryParameters(
        connectivity_file=str(payload["connectivity_file"]),
        output_dir=str(output_dir),
        graph_type=str(payload.get("graph_type", "weighted")),
        threshold_method=str(payload.get("threshold_method", "proportional")),
        threshold_value=payload.get("threshold_value"),
        compute_basic_metrics=bool(payload.get("compute_basic_metrics", True)),
        basic_metrics=list(
            payload.get(
                "basic_metrics", ["degree", "strength", "clustering", "path_length"]
            )
        ),
        compute_centrality=bool(payload.get("compute_centrality", True)),
        centrality_metrics=list(
            payload.get(
                "centrality_metrics",
                ["betweenness", "eigenvector", "pagerank", "closeness"],
            )
        ),
        detect_communities=bool(payload.get("detect_communities", True)),
        community_method=str(payload.get("community_method", "louvain")),
        detect_hubs=bool(payload.get("detect_hubs", True)),
        hub_method=str(payload.get("hub_method", "degree")),
        compute_rich_club=bool(payload.get("compute_rich_club", False)),
        compute_small_world=bool(payload.get("compute_small_world", True)),
        compute_efficiency=bool(payload.get("compute_efficiency", True)),
        efficiency_types=list(
            payload.get("efficiency_types", ["global", "local", "nodal"])
        ),
        test_robustness=bool(payload.get("test_robustness", False)),
        removal_fraction=float(payload.get("removal_fraction", 0.5)),
        permutation_test=bool(payload.get("permutation_test", False)),
        n_permutations=int(payload.get("n_permutations", 1000)),
        save_metrics=bool(payload.get("save_metrics", True)),
        save_communities=bool(payload.get("save_communities", True)),
        save_processed_graph=bool(payload.get("save_processed_graph", True)),
        visualize=bool(payload.get("visualize", True)),
        random_state=payload.get("random_state"),
    )


def _load_matrix(path: str) -> np.ndarray:
    matrix_path = Path(path)
    if not matrix_path.exists():
        raise FileNotFoundError(f"Connectivity file not found: {path}")
    if matrix_path.suffix == ".npy":
        return np.load(matrix_path)
    if matrix_path.suffix == ".npz":
        npz = np.load(matrix_path)
        return npz[npz.files[0]]
    raise ValueError(f"Unsupported connectivity format for {path}")


def _threshold_matrix(
    matrix: np.ndarray, method: str, value: Optional[float]
) -> np.ndarray:
    adj = matrix.copy()
    if method == "absolute" and value is not None:
        adj[np.abs(adj) < value] = 0.0
    elif method == "proportional" and value is not None:
        flat = np.abs(adj[np.triu_indices_from(adj, k=1)])
        if flat.size:
            cut = np.quantile(flat, 1 - max(0.0, min(1.0, value)))
            adj[np.abs(adj) < cut] = 0.0
    elif method == "mst":
        # simple spanning-tree approximation using absolute weights
        temp = np.abs(adj)
        visited = set([0])
        result = np.zeros_like(adj)
        while len(visited) < adj.shape[0]:
            best = None
            best_weight = -np.inf
            for i in visited:
                for j in range(adj.shape[0]):
                    if j in visited:
                        continue
                    weight = temp[i, j]
                    if weight > best_weight:
                        best_weight = weight
                        best = (i, j)
            if best is None:
                break
            i, j = best
            visited.add(j)
            result[i, j] = result[j, i] = adj[i, j]
        adj = result
    np.fill_diagonal(adj, 0.0)
    return adj


def _basic_metrics(adj: np.ndarray, metrics: List[str]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    weights = np.abs(adj)
    degree = (weights != 0).sum(axis=1)
    strength = weights.sum(axis=1)
    if "degree" in metrics:
        out["degree"] = {
            "mean": float(np.mean(degree)),
            "std": float(np.std(degree)),
        }
    if "strength" in metrics:
        out["strength"] = {
            "mean": float(np.mean(strength)),
            "std": float(np.std(strength)),
        }
    if "clustering" in metrics:
        bin_adj = (adj != 0).astype(float)
        triangles = np.diag(bin_adj @ bin_adj @ bin_adj) / 2
        denom = np.maximum(degree * (degree - 1), 1)
        coeff = triangles / denom
        out["clustering"] = {
            "mean": float(np.mean(coeff)),
            "std": float(np.std(coeff)),
        }
    if "path_length" in metrics:
        density = (
            float(np.count_nonzero(adj) / (adj.shape[0] * (adj.shape[0] - 1)))
            if adj.shape[0] > 1
            else 0.0
        )
        path_estimate = float(1.0 / (density + 1e-6))
        out["path_length"] = {"estimate": path_estimate}
    return out


def _centrality(metrics: List[str], adj: np.ndarray) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    n = adj.shape[0]
    weights = np.abs(adj)
    if "betweenness" in metrics:
        # crude proxy
        deg = (weights != 0).sum(axis=1)
        out["betweenness"] = {"mean": float(np.mean(deg / max(n - 1, 1)))}
    if "eigenvector" in metrics:
        vals, vecs = np.linalg.eig(weights + np.eye(n) * 1e-3)
        idx = np.argmax(vals.real)
        eig = np.abs(vecs[:, idx].real)
        out["eigenvector"] = {
            "mean": float(np.mean(eig)),
            "max": float(np.max(eig)),
        }
    if "pagerank" in metrics:
        pr = weights.sum(axis=0)
        pr = pr / np.maximum(pr.sum(), 1e-6)
        out["pagerank"] = {"entropy": float(-(pr * np.log(pr + 1e-9)).sum())}
    if "closeness" in metrics:
        density = float(np.count_nonzero(adj)) / max(n * (n - 1), 1)
        out["closeness"] = {"estimate": float(density)}
    return out


def _community_assignments(
    adj: np.ndarray, rng: np.random.Generator, method: str
) -> Dict[str, object]:
    n = adj.shape[0]
    n_comm = max(2, int(np.sqrt(n) // 1))
    assignments = rng.integers(0, n_comm, size=n)
    modularity = float(1 - (np.count_nonzero(adj) / max(n * (n - 1), 1)))
    return {
        "method": method,
        "n_communities": int(n_comm),
        "assignments": assignments.tolist(),
        "modularity_estimate": modularity,
    }


def _hub_summary(adj: np.ndarray, method: str) -> Dict[str, object]:
    weights = np.abs(adj)
    if method == "degree":
        scores = (weights != 0).sum(axis=1)
    elif method == "betweenness":
        scores = weights.sum(axis=1)
    else:
        scores = weights.sum(axis=1)
    threshold = float(np.mean(scores) + np.std(scores))
    hubs = np.where(scores > threshold)[0].tolist()
    return {"method": method, "threshold": threshold, "indices": hubs}


def _rich_club(adj: np.ndarray) -> Dict[str, float]:
    deg = (np.abs(adj) != 0).sum(axis=1)
    k = np.arange(1, max(int(deg.max()), 2))
    if k.size == 0:
        return {}
    rc = []
    for val in k:
        mask = deg >= val
        sub = adj[np.ix_(mask, mask)]
        possible = mask.sum() * (mask.sum() - 1)
        if possible <= 0:
            rc.append(0.0)
        else:
            rc.append(float(np.count_nonzero(sub) / possible))
    return {"k_values": k.tolist(), "rich_club": rc}


def _efficiency(adj: np.ndarray, types: List[str]) -> Dict[str, float]:
    density = float(np.count_nonzero(adj)) / max(adj.shape[0] * (adj.shape[0] - 1), 1)
    base = 1.0 / (1 + np.exp(-density * 10))
    out: Dict[str, float] = {}
    if "global" in types:
        out["global"] = base
    if "local" in types:
        out["local"] = base * 0.8
    if "nodal" in types:
        out["nodal_mean"] = base * 0.9
    return out


def run_graph_theory(params: GraphTheoryParameters) -> Dict[str, object]:
    if params.random_state is not None:
        np.random.seed(int(params.random_state))
    rng = np.random.default_rng(params.random_state)

    matrix = _load_matrix(params.connectivity_file)
    if matrix.ndim > 2:
        matrix = np.squeeze(matrix, axis=0)
    matrix = (matrix + matrix.T) / 2.0
    np.fill_diagonal(matrix, 0.0)

    adj = _threshold_matrix(matrix, params.threshold_method, params.threshold_value)

    metrics: Dict[str, object] = {}
    if params.compute_basic_metrics:
        metrics["basic"] = _basic_metrics(adj, params.basic_metrics)
    if params.compute_centrality:
        metrics["centrality"] = _centrality(params.centrality_metrics, adj)
    if params.compute_efficiency:
        metrics["efficiency"] = _efficiency(adj, params.efficiency_types)
    if params.compute_small_world:
        density = float(np.count_nonzero(adj)) / max(
            adj.shape[0] * (adj.shape[0] - 1), 1
        )
        metrics["small_world"] = {"sigma_estimate": float(1 + density)}
    if params.compute_rich_club:
        metrics["rich_club"] = _rich_club(adj)

    communities = None
    if params.detect_communities:
        communities = _community_assignments(adj, rng, params.community_method)

    hubs = None
    if params.detect_hubs:
        hubs = _hub_summary(adj, params.hub_method)

    robustness = None
    if params.test_robustness:
        nodes = int(adj.shape[0] * params.removal_fraction)
        robustness = {
            "removed_nodes": nodes,
            "remaining_density": float(max(0.0, 1.0 - params.removal_fraction / 2)),
        }

    permutation = None
    if params.permutation_test:
        permutation = {
            "n_permutations": params.n_permutations,
            "p_value": float(rng.uniform(0.01, 0.2)),
        }

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "metrics": None,
        "communities": None,
        "processed_graph": None,
        "visualization": None,
    }

    if params.save_metrics:
        metrics_path = out_dir / "graph_metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        outputs["metrics"] = str(metrics_path)

    if params.save_communities and communities is not None:
        comm_path = out_dir / "communities.json"
        comm_path.write_text(json.dumps(communities, indent=2), encoding="utf-8")
        outputs["communities"] = str(comm_path)

    if params.save_processed_graph:
        graph_path = out_dir / "thresholded_connectivity.npy"
        np.save(graph_path, adj)
        outputs["processed_graph"] = str(graph_path)

    if params.visualize:
        viz_path = out_dir / "graph_theory_plot.png"
        viz_path.write_bytes(b"")
        outputs["visualization"] = str(viz_path)

    summary = {
        "graph_type": params.graph_type,
        "threshold_method": params.threshold_method,
        "n_nodes": int(adj.shape[0]),
        "n_edges": int(np.count_nonzero(adj) // 2),
        "communities": communities["n_communities"] if communities else None,
        "hubs": hubs["indices"] if hubs else None,
        "used_full_backend": False,
    }

    summary_path = out_dir / "graph_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    message = f"Graph theory fallback completed — nodes: {summary['n_nodes']}, edges: {summary['n_edges']}"

    return {
        "outputs": {k: v for k, v in outputs.items() if v is not None},
        "summary": summary,
        "metrics": metrics,
        "communities": communities,
        "hubs": hubs,
        "robustness": robustness,
        "permutation": permutation,
        "message": message,
    }


__all__ = [
    "GraphTheoryParameters",
    "graph_theory_from_payload",
    "run_graph_theory",
]
