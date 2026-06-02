"""Fallback Graph Neural Network connectivity utilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class GNNConnectivityParameters:
    """Configuration for GNN connectivity fallback."""

    connectivity_file: Optional[str]
    timeseries_file: Optional[str]
    output_dir: str
    graph_type: str
    threshold: Optional[float]
    sparsity: Optional[float]
    model_type: str
    n_layers: int
    hidden_dim: int
    task: str
    n_classes: Optional[int]
    mode: str
    epochs: int
    learning_rate: float
    compute_metrics: bool
    metrics: List[str]
    save_model: bool
    save_embeddings: bool
    save_predictions: bool
    visualize: bool
    seed: Optional[int]
    use_real_gnn: bool


def gnn_connectivity_from_payload(
    payload: Dict[str, object],
) -> GNNConnectivityParameters:
    """Normalise payload into parameters."""

    output_dir = payload.get("output_dir") or Path.cwd() / "gnn_connectivity"
    use_real_gnn = bool(payload.get("use_real_gnn", False))
    if "use_real_gnn" not in payload:
        use_real_gnn = os.environ.get("BR_GNN_USE_REAL", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    return GNNConnectivityParameters(
        connectivity_file=(
            str(payload.get("connectivity_file"))
            if payload.get("connectivity_file")
            else None
        ),
        timeseries_file=(
            str(payload.get("timeseries_file"))
            if payload.get("timeseries_file")
            else None
        ),
        output_dir=str(output_dir),
        graph_type=str(payload.get("graph_type", "functional")),
        threshold=payload.get("threshold"),
        sparsity=payload.get("sparsity"),
        model_type=str(payload.get("model_type", "gcn")),
        n_layers=int(payload.get("n_layers", 3)),
        hidden_dim=int(payload.get("hidden_dim", 64)),
        task=str(payload.get("task", "node_classification")),
        n_classes=payload.get("n_classes"),
        mode=str(payload.get("mode", "train")),
        epochs=int(payload.get("epochs", 100)),
        learning_rate=float(payload.get("learning_rate", 0.01)),
        compute_metrics=bool(payload.get("compute_metrics", True)),
        metrics=list(
            payload.get(
                "metrics", ["degree", "clustering", "betweenness", "modularity"]
            )
        ),
        save_model=bool(payload.get("save_model", True)),
        save_embeddings=bool(payload.get("save_embeddings", True)),
        save_predictions=bool(payload.get("save_predictions", True)),
        visualize=bool(payload.get("visualize", True)),
        seed=payload.get("seed"),
        use_real_gnn=use_real_gnn,
    )


def _load_connectivity(
    params: GNNConnectivityParameters, rng: np.random.Generator
) -> np.ndarray:
    if params.connectivity_file:
        path = Path(params.connectivity_file)
        if path.suffix == ".npy" and path.exists():
            return np.load(path)
        if path.suffix == ".npz" and path.exists():
            npz = np.load(path)
            return npz[npz.files[0]]
    if params.timeseries_file:
        ts_path = Path(params.timeseries_file)
        if ts_path.suffix == ".npy" and ts_path.exists():
            ts = np.load(ts_path)
        elif ts_path.suffix == ".npz" and ts_path.exists():
            npz = np.load(ts_path)
            ts = npz[npz.files[0]]
        else:
            ts = rng.normal(size=(200, 100))
        cov = np.corrcoef(ts, rowvar=False)
        np.fill_diagonal(cov, 0.0)
        return cov
    size = 90
    mat = rng.normal(size=(size, size))
    mat = (mat + mat.T) / 2.0
    np.fill_diagonal(mat, 0.0)
    return mat


def _apply_threshold(
    matrix: np.ndarray, threshold: Optional[float], sparsity: Optional[float]
) -> np.ndarray:
    adj = matrix.copy()
    if threshold is not None:
        mask = np.abs(adj) < threshold
        adj[mask] = 0.0
    if sparsity is not None:
        flat = np.abs(adj[np.triu_indices_from(adj, k=1)])
        if flat.size:
            cut = np.quantile(flat, 1 - max(0.0, min(1.0, sparsity)))
            mask = np.abs(adj) < cut
            adj[mask] = 0.0
    return adj


def _graph_metrics(adj: np.ndarray, metrics: List[str]) -> Dict[str, Dict[str, float]]:
    results: Dict[str, Dict[str, float]] = {}
    deg = adj.sum(axis=1)
    if "degree" in metrics:
        results["degree"] = {
            "mean": float(np.mean(deg)),
            "std": float(np.std(deg)),
            "min": float(np.min(deg)),
            "max": float(np.max(deg)),
        }
    if "clustering" in metrics:
        bin_adj = (adj != 0).astype(float)
        triangles = np.diag(bin_adj @ bin_adj @ bin_adj) / 2
        denom = np.maximum(deg * (deg - 1), 1)
        clustering = triangles / denom
        results["clustering"] = {
            "mean": float(np.mean(clustering)),
            "std": float(np.std(clustering)),
        }
    if "betweenness" in metrics:
        # Simple proxy using degree centrality variance
        centrality = deg / np.maximum(adj.shape[0] - 1, 1)
        results["betweenness"] = {
            "mean": float(np.mean(centrality)),
            "std": float(np.std(centrality)),
        }
    if "modularity" in metrics:
        # Proxy modularity score based on density
        density = (
            float(np.count_nonzero(adj) / (adj.shape[0] * (adj.shape[0] - 1)))
            if adj.shape[0] > 1
            else 0.0
        )
        results["modularity"] = {
            "estimate": float(1 - density),
        }
    return results


def _attempt_real_gnn(
    params: GNNConnectivityParameters, adjacency: np.ndarray, rng: np.random.Generator
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        from brain_researcher.services.br_kg.ml import gnn_models
    except Exception as exc:
        return None, f"gnn_models_import_failed: {exc}"

    if not getattr(gnn_models, "TORCH_AVAILABLE", False):
        return None, "torch_unavailable"

    try:
        model_type = gnn_models.GNNModelType(params.model_type.lower())
    except Exception:
        model_type = gnn_models.GNNModelType.GCN

    n_nodes = adjacency.shape[0]
    nodes = [f"node_{i}" for i in range(n_nodes)]
    degree = (adjacency != 0).sum(axis=1)
    strength = np.sum(np.abs(adjacency), axis=1)
    max_degree = np.max(degree) if degree.size else 1.0
    max_strength = np.max(strength) if strength.size else 1.0
    node_features = {
        node: [float(degree[i] / max_degree), float(strength[i] / max_strength)]
        for i, node in enumerate(nodes)
    }

    edges = []
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if adjacency[i, j] != 0:
                edges.append({"start": nodes[i], "end": nodes[j]})
                edges.append({"start": nodes[j], "end": nodes[i]})

    graph_data = {
        "nodes": nodes,
        "edges": edges,
        "node_features": node_features,
    }

    predictor = gnn_models.GNNPredictor(model_type=model_type)
    predictor.build_model(
        input_dim=2,
        output_dim=params.hidden_dim,
        hidden_dim=params.hidden_dim,
        num_layers=max(2, params.n_layers),
        epochs=min(params.epochs, 50),
        learning_rate=params.learning_rate,
    )

    training = None
    label_source = None
    task_type = params.task

    if params.mode == "train":
        if params.task == "node_classification":
            median_strength = float(np.median(strength)) if strength.size else 0.0
            labels = {
                node: int(strength[i] >= median_strength)
                for i, node in enumerate(nodes)
            }
            label_source = "strength_median"
            if labels:
                training = predictor.train_node_classification(
                    graph_data,
                    labels,
                    num_classes=params.n_classes or 2,
                )
        elif params.task == "link_prediction":
            positive_edges = [
                (nodes[i], nodes[j])
                for i in range(n_nodes)
                for j in range(i + 1, n_nodes)
                if adjacency[i, j] != 0
            ]
            negative_edges = []
            if n_nodes > 1:
                attempts = 0
                while (
                    len(negative_edges) < min(len(positive_edges), 200)
                    and attempts < n_nodes * n_nodes
                ):
                    i = int(rng.integers(0, n_nodes))
                    j = int(rng.integers(0, n_nodes))
                    if i == j:
                        attempts += 1
                        continue
                    if adjacency[i, j] == 0:
                        negative_edges.append((nodes[i], nodes[j]))
                    attempts += 1
            if positive_edges and negative_edges:
                training = predictor.train_link_prediction(
                    graph_data,
                    positive_edges=positive_edges,
                    negative_edges=negative_edges,
                )

    embeddings_payload = predictor.predict(graph_data, task_type="node_embeddings")
    embeddings = embeddings_payload.get("embeddings")

    predictions = None
    probabilities = None
    link_edges = None
    if params.task == "node_classification":
        pred_payload = predictor.predict(
            graph_data,
            task_type="node_classification",
            num_classes=params.n_classes or 2,
        )
        predictions = pred_payload.get("predictions")
        probabilities = pred_payload.get("probabilities")
    elif params.task == "link_prediction":
        test_edges = []
        for i in range(min(n_nodes, 20)):
            for j in range(i + 1, min(n_nodes, 20)):
                test_edges.append((nodes[i], nodes[j]))
        pred_payload = predictor.predict(
            graph_data,
            task_type="link_prediction",
            test_edges=test_edges,
        )
        predictions = pred_payload.get("link_probabilities")
        link_edges = pred_payload.get("test_edges")

    return (
        {
            "embeddings": embeddings,
            "predictions": predictions,
            "probabilities": probabilities,
            "link_edges": link_edges,
            "training": training,
            "label_source": label_source,
            "task_type": task_type,
            "model_info": predictor.get_model_info(),
        },
        None,
    )


def run_gnn_connectivity(params: GNNConnectivityParameters) -> Dict[str, object]:
    if params.seed is not None:
        np.random.seed(int(params.seed))
    rng = np.random.default_rng(params.seed)

    adjacency = _load_connectivity(params, rng)
    adjacency = np.array(adjacency, dtype=float)
    adjacency = (adjacency + adjacency.T) / 2.0
    np.fill_diagonal(adjacency, 0.0)

    adjacency = _apply_threshold(adjacency, params.threshold, params.sparsity)

    n_nodes = adjacency.shape[0]
    real_gnn_attempted = bool(params.use_real_gnn)
    real_gnn_used = False
    real_gnn_error = None
    real_gnn_payload: Optional[Dict[str, Any]] = None

    if real_gnn_attempted:
        real_gnn_payload, real_gnn_error = _attempt_real_gnn(params, adjacency, rng)
        real_gnn_used = real_gnn_payload is not None

    if real_gnn_used:
        embeddings = np.asarray(
            real_gnn_payload.get("embeddings", []), dtype=np.float32
        )
        predictions = real_gnn_payload.get("predictions")
    else:
        embeddings = rng.normal(scale=0.1, size=(n_nodes, params.hidden_dim)).astype(
            np.float32
        )
        logits = rng.normal(size=(n_nodes, params.n_classes or 2)).astype(np.float32)
        predictions = np.argmax(logits, axis=1)

    graph_metrics = (
        _graph_metrics(adjacency, params.metrics) if params.compute_metrics else {}
    )

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, Optional[str]] = {
        "results": None,
        "embeddings": None,
        "predictions": None,
        "model": None,
        "visualization": None,
    }

    if params.save_embeddings:
        emb_path = out_dir / "node_embeddings.npy"
        np.save(emb_path, embeddings)
        outputs["embeddings"] = str(emb_path)

    if params.save_predictions and predictions is not None:
        pred_path = out_dir / "predictions.npy"
        np.save(pred_path, np.asarray(predictions))
        outputs["predictions"] = str(pred_path)

    if params.save_model:
        if real_gnn_used and real_gnn_payload and real_gnn_payload.get("model_info"):
            model_path = out_dir / "gnn_model.json"
            model_payload = {
                "model_type": params.model_type,
                "n_layers": params.n_layers,
                "hidden_dim": params.hidden_dim,
                "epochs": params.epochs,
                "learning_rate": params.learning_rate,
                "real_gnn": True,
                "model_info": real_gnn_payload.get("model_info"),
            }
        else:
            model_path = out_dir / "gnn_model.json"
            model_payload = {
                "model_type": params.model_type,
                "n_layers": params.n_layers,
                "hidden_dim": params.hidden_dim,
                "epochs": params.epochs,
                "learning_rate": params.learning_rate,
                "real_gnn": False,
            }
        model_path.write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        outputs["model"] = str(model_path)

    summary = {
        "graph_type": params.graph_type,
        "model_type": params.model_type,
        "task": params.task,
        "n_nodes": int(n_nodes),
        "n_edges": int(np.count_nonzero(adjacency) // 2),
        "graph_metrics": graph_metrics,
        "used_full_backend": real_gnn_used,
        "real_gnn_attempted": real_gnn_attempted,
        "real_gnn_error": real_gnn_error,
        "label_source": (
            real_gnn_payload.get("label_source") if real_gnn_payload else None
        ),
    }

    results_path = out_dir / "gnn_results.json"
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    outputs["results"] = str(results_path)

    if params.visualize:
        viz_path = out_dir / "graph_visualization.png"
        viz_path.write_bytes(b"")
        outputs["visualization"] = str(viz_path)

    if real_gnn_used:
        message = f"GNN connectivity (real) completed — nodes: {summary['n_nodes']}, edges: {summary['n_edges']}"
    else:
        message = f"GNN connectivity fallback completed — nodes: {summary['n_nodes']}, edges: {summary['n_edges']}"

    metrics = {
        "graph_metrics": graph_metrics,
        "node_count": summary["n_nodes"],
    }
    if real_gnn_payload and real_gnn_payload.get("training") is not None:
        metrics["training"] = real_gnn_payload.get("training")

    return {
        "outputs": {k: v for k, v in outputs.items() if v is not None},
        "summary": summary,
        "metrics": metrics,
        "message": message,
    }


__all__ = [
    "GNNConnectivityParameters",
    "gnn_connectivity_from_payload",
    "run_gnn_connectivity",
]
