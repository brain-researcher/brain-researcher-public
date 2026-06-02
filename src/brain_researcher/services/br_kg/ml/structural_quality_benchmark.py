"""Structural quality benchmark for BR-KG graph slices.

This module treats graph models as diagnostic probes. The primary output is a
graph diagnostic report describing relation-level learnability and control
adjusted consistency, not a standalone GNN leaderboard.
"""

from __future__ import annotations

import json
import logging
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from .gnn_models import TORCH_AVAILABLE, GNNConfig, GNNModelType, GNNPredictor
from .graph_embeddings import DEPS_AVAILABLE as GRAPH_EMBEDDING_DEPS_AVAILABLE
from .graph_embeddings import DEPS_IMPORT_ERROR as GRAPH_EMBEDDING_IMPORT_ERROR
from .graph_embeddings import EmbeddingConfig, EmbeddingType, GraphEmbedder

logger = logging.getLogger(__name__)


@dataclass
class StructuralQualityBenchmarkConfig:
    """Configuration for the structural quality benchmark."""

    benchmark_id: str = "br_kg_structural_quality_v1"
    evaluation_edge_types: Optional[list[str]] = None
    key_edge_types: list[str] = field(default_factory=list)
    train_ratio: float = 0.7
    val_ratio: float = 0.1
    test_ratio: float = 0.2
    negatives_per_positive: int = 2
    hard_negative_ratio: float = 0.5
    min_positive_edges_per_type: int = 3
    include_node2vec_probe: bool = True
    include_graphsage_probe: bool = False
    node2vec_dimensions: int = 64
    node2vec_walk_length: int = 20
    node2vec_num_walks: int = 8
    graphsage_hidden_dim: int = 32
    graphsage_output_dim: int = 16
    graphsage_epochs: int = 40
    graphsage_num_layers: int = 2
    graphsage_learning_rate: float = 0.01
    graphsage_dropout: float = 0.2
    audit_group_keys: list[str] = field(default_factory=list)
    audit_group_scope: str = "source"
    min_group_samples: int = 5
    random_seed: int = 42

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _EdgeRecord:
    source: str
    target: str
    edge_type: str


@dataclass(frozen=True)
class _SampleRecord:
    source: str
    target: str
    edge_type: str
    source_type: str
    target_type: str
    label: int
    split: str
    negative_kind: Optional[str] = None


@dataclass
class _NormalizedGraph:
    nodes: list[str]
    node_types: dict[str, str]
    node_features: dict[str, np.ndarray]
    node_properties: dict[str, dict[str, Any]]
    edges: list[_EdgeRecord]


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (float, int, np.floating, np.integer)):
        if math.isnan(float(value)):
            return None
        return float(value)
    return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _normalize_group_key(value: str) -> str:
    return " ".join(str(value).strip().split()).lower()


def _group_value(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _cosine_similarity(
    vec_a: Optional[np.ndarray], vec_b: Optional[np.ndarray]
) -> float:
    if vec_a is None or vec_b is None:
        return 0.0
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def _compute_binary_auc(labels: list[int], scores: list[float]) -> Optional[float]:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return None

    greater = 0.0
    total = len(positives) * len(negatives)
    for pos_score in positives:
        for neg_score in negatives:
            if pos_score > neg_score:
                greater += 1.0
            elif pos_score == neg_score:
                greater += 0.5
    return greater / total if total else None


def _compute_average_precision(
    labels: list[int], scores: list[float]
) -> Optional[float]:
    positives = sum(labels)
    if positives == 0:
        return None

    ranked = sorted(zip(scores, labels), key=lambda item: item[0], reverse=True)
    correct = 0
    precision_sum = 0.0
    for index, (_, label) in enumerate(ranked, start=1):
        if label == 1:
            correct += 1
            precision_sum += correct / index
    return precision_sum / positives if positives else None


def _group_ranking_metrics(
    samples: list[_SampleRecord], scores: list[float]
) -> dict[str, Optional[float]]:
    grouped: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    for sample, score in zip(samples, scores):
        grouped[(sample.edge_type, sample.source)].append((score, sample.label))

    reciprocal_ranks: list[float] = []
    recall_at_10: list[float] = []
    recall_at_50: list[float] = []

    for rows in grouped.values():
        ranked = sorted(rows, key=lambda item: item[0], reverse=True)
        labels = [label for _, label in ranked]
        if 1 not in labels:
            continue
        first_positive = labels.index(1) + 1
        reciprocal_ranks.append(1.0 / first_positive)
        recall_at_10.append(1.0 if 1 in labels[:10] else 0.0)
        recall_at_50.append(1.0 if 1 in labels[:50] else 0.0)

    return {
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else None,
        "recall_at_10": float(np.mean(recall_at_10)) if recall_at_10 else None,
        "recall_at_50": float(np.mean(recall_at_50)) if recall_at_50 else None,
    }


def _metric_bundle(
    samples: list[_SampleRecord], scores: list[float]
) -> dict[str, Optional[float]]:
    labels = [sample.label for sample in samples]
    return {
        "auroc": _compute_binary_auc(labels, scores),
        "average_precision": _compute_average_precision(labels, scores),
        **_group_ranking_metrics(samples, scores),
    }


class StructuralQualityBenchmark:
    """Graph diagnostic benchmark with probe-model comparisons."""

    def __init__(self, config: Optional[StructuralQualityBenchmarkConfig] = None):
        self.config = config or StructuralQualityBenchmarkConfig()
        self._rng = random.Random(self.config.random_seed)

    def run(
        self,
        graph_data: dict[str, Any],
        output_dir: Optional[str] = None,
        graph_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_graph(graph_data)
        split_manifest, split_samples = self._build_split_manifest(normalized)
        probe_model_comparison, score_maps = self._run_probe_models(
            normalized, split_samples
        )
        graph_diagnostic_report = self._build_graph_diagnostic_report(
            normalized, split_manifest, probe_model_comparison
        )
        fairness_audit_report = self._build_fairness_audit_report(
            normalized=normalized,
            split_samples=split_samples,
            probe_model_comparison=probe_model_comparison,
            score_maps=score_maps,
        )

        result = {
            "benchmark_id": self.config.benchmark_id,
            "generated_at": (
                graph_metadata.get("generated_at") if graph_metadata else None
            ),
            "graph_metadata": graph_metadata or {},
            "config": self.config.to_dict(),
            "graph_diagnostic_report": graph_diagnostic_report,
            "fairness_audit_report": fairness_audit_report,
            "probe_model_comparison": probe_model_comparison,
            "split_manifest": split_manifest,
        }

        if output_dir:
            self._write_artifacts(output_dir, result)

        return result

    def _normalize_graph(self, graph_data: dict[str, Any]) -> _NormalizedGraph:
        node_types: dict[str, str] = {}
        node_features: dict[str, np.ndarray] = {}
        node_properties: dict[str, dict[str, Any]] = {}
        nodes: list[str] = []

        for raw_node in graph_data.get("nodes", []):
            if isinstance(raw_node, dict):
                node_id = (
                    raw_node.get("id")
                    or raw_node.get("node_id")
                    or raw_node.get("name")
                )
                if node_id is None:
                    continue
                node_id = str(node_id)
                nodes.append(node_id)
                node_type = (
                    raw_node.get("node_type")
                    or raw_node.get("type")
                    or raw_node.get("label")
                )
                if node_type:
                    node_types[node_id] = str(node_type)
                properties = dict(raw_node.get("properties") or {})
                if properties:
                    node_properties[node_id] = properties
                features = raw_node.get("features")
                if features is not None:
                    node_features[node_id] = np.asarray(features, dtype=float)
            else:
                nodes.append(str(raw_node))

        for node_id, node_type in graph_data.get("node_types", {}).items():
            node_types[str(node_id)] = str(node_type)
            if str(node_id) not in nodes:
                nodes.append(str(node_id))

        for node_id, features in graph_data.get("node_features", {}).items():
            node_id = str(node_id)
            node_features[node_id] = np.asarray(features, dtype=float)
            if node_id not in nodes:
                nodes.append(node_id)

        node_set = set(nodes)
        edges: list[_EdgeRecord] = []
        for raw_edge in graph_data.get("edges", []):
            source = raw_edge.get("start") or raw_edge.get("source")
            target = raw_edge.get("end") or raw_edge.get("target")
            edge_type = (
                raw_edge.get("edge_type")
                or raw_edge.get("relationship_type")
                or raw_edge.get("type")
                or raw_edge.get("label")
                or "RELATED_TO"
            )
            if source is None or target is None:
                continue
            source = str(source)
            target = str(target)
            if source not in node_set or target not in node_set:
                continue
            edges.append(
                _EdgeRecord(source=source, target=target, edge_type=str(edge_type))
            )

        return _NormalizedGraph(
            nodes=nodes,
            node_types=node_types,
            node_features=node_features,
            node_properties=node_properties,
            edges=edges,
        )

    def _diagnostic_bucket(
        self,
        *,
        positives: int,
        primary_auroc: Optional[float],
        control_margin: Optional[float],
    ) -> str:
        if positives < self.config.min_positive_edges_per_type:
            return "underpowered"
        if primary_auroc is None:
            return "underpowered"
        if (
            control_margin is not None
            and primary_auroc >= 0.8
            and control_margin >= 0.1
        ):
            return "strong"
        if (
            control_margin is not None
            and primary_auroc >= 0.65
            and control_margin >= 0.03
        ):
            return "marginal"
        return "weak_or_noisy"

    def _build_split_manifest(
        self, normalized: _NormalizedGraph
    ) -> tuple[dict[str, Any], dict[str, list[_SampleRecord]]]:
        existing_by_type: dict[str, set[tuple[str, str]]] = defaultdict(set)
        edges_by_type: dict[str, list[_EdgeRecord]] = defaultdict(list)
        degrees: Counter[str] = Counter()

        for edge in normalized.edges:
            existing_by_type[edge.edge_type].add((edge.source, edge.target))
            edges_by_type[edge.edge_type].append(edge)
            degrees[edge.source] += 1
            degrees[edge.target] += 1

        candidate_edge_types = sorted(edges_by_type.keys())
        if self.config.evaluation_edge_types is not None:
            allowed = set(self.config.evaluation_edge_types)
            candidate_edge_types = [
                edge_type for edge_type in candidate_edge_types if edge_type in allowed
            ]

        all_samples: dict[str, list[_SampleRecord]] = {
            "train": [],
            "val": [],
            "test": [],
        }
        per_edge_type: dict[str, Any] = {}

        node_ids_by_type: dict[str, list[str]] = defaultdict(list)
        for node_id in normalized.nodes:
            node_ids_by_type[normalized.node_types.get(node_id, "Unknown")].append(
                node_id
            )

        for edge_type in candidate_edge_types:
            positives = edges_by_type[edge_type]
            shuffled_positives = positives[:]
            self._rng.shuffle(shuffled_positives)

            negatives: list[_SampleRecord] = []
            for positive in shuffled_positives:
                source_type = normalized.node_types.get(positive.source, "Unknown")
                target_type = normalized.node_types.get(positive.target, "Unknown")
                negatives.extend(
                    self._sample_negative_edges(
                        normalized=normalized,
                        source_id=positive.source,
                        source_type=source_type,
                        target_type=target_type,
                        edge_type=edge_type,
                        positives_by_type=existing_by_type,
                        degrees=degrees,
                        count=self.config.negatives_per_positive,
                    )
                )

            positive_samples = [
                _SampleRecord(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.edge_type,
                    source_type=normalized.node_types.get(edge.source, "Unknown"),
                    target_type=normalized.node_types.get(edge.target, "Unknown"),
                    label=1,
                    split="pending",
                )
                for edge in shuffled_positives
            ]

            pos_splits = self._assign_splits(positive_samples)
            neg_splits = self._assign_splits(negatives)

            for split_name, split_values in pos_splits.items():
                all_samples[split_name].extend(split_values)
            for split_name, split_values in neg_splits.items():
                all_samples[split_name].extend(split_values)

            per_edge_type[edge_type] = {
                "positive_edges": len(positive_samples),
                "negative_edges": len(negatives),
                "source_types": sorted(
                    {sample.source_type for sample in positive_samples}
                ),
                "target_types": sorted(
                    {sample.target_type for sample in positive_samples}
                ),
                "splits": {
                    split_name: {
                        "positives": sum(1 for sample in values if sample.label == 1),
                        "negatives": sum(1 for sample in values if sample.label == 0),
                    }
                    for split_name, values in {
                        "train": pos_splits["train"] + neg_splits["train"],
                        "val": pos_splits["val"] + neg_splits["val"],
                        "test": pos_splits["test"] + neg_splits["test"],
                    }.items()
                },
                "coverage_status": (
                    "adequate"
                    if len(positive_samples) >= self.config.min_positive_edges_per_type
                    else "underpowered"
                ),
            }

        manifest = {
            "split_strategy": "edge_stratified_by_type",
            "negative_sampling": {
                "strategy": "typed_random_plus_hard",
                "negatives_per_positive": self.config.negatives_per_positive,
                "hard_negative_ratio": self.config.hard_negative_ratio,
            },
            "per_edge_type": per_edge_type,
        }
        return manifest, all_samples

    def _sample_negative_edges(
        self,
        normalized: _NormalizedGraph,
        source_id: str,
        source_type: str,
        target_type: str,
        edge_type: str,
        positives_by_type: dict[str, set[tuple[str, str]]],
        degrees: Counter[str],
        count: int,
    ) -> list[_SampleRecord]:
        candidates = [
            target_id
            for target_id in normalized.nodes
            if normalized.node_types.get(target_id, "Unknown") == target_type
            and target_id != source_id
            and (source_id, target_id) not in positives_by_type[edge_type]
        ]
        if not candidates:
            return []

        hard_count = min(
            len(candidates), int(round(count * self.config.hard_negative_ratio))
        )
        random_count = max(0, count - hard_count)

        scored_candidates = []
        source_features = normalized.node_features.get(source_id)
        for candidate_id in candidates:
            candidate_features = normalized.node_features.get(candidate_id)
            score = _cosine_similarity(source_features, candidate_features)
            score += 0.05 * math.log1p(
                degrees[source_id] * max(1, degrees[candidate_id])
            )
            scored_candidates.append((candidate_id, score))
        scored_candidates.sort(key=lambda item: item[1], reverse=True)

        selected_ids: list[tuple[str, str]] = []
        for candidate_id, _ in scored_candidates[:hard_count]:
            selected_ids.append((candidate_id, "hard_typed"))

        remaining_pool = [
            candidate_id
            for candidate_id in candidates
            if candidate_id not in {cid for cid, _ in selected_ids}
        ]
        self._rng.shuffle(remaining_pool)
        for candidate_id in remaining_pool[:random_count]:
            selected_ids.append((candidate_id, "random_typed"))

        return [
            _SampleRecord(
                source=source_id,
                target=target_id,
                edge_type=edge_type,
                source_type=source_type,
                target_type=target_type,
                label=0,
                split="pending",
                negative_kind=negative_kind,
            )
            for target_id, negative_kind in selected_ids
        ]

    def _assign_splits(
        self, samples: list[_SampleRecord]
    ) -> dict[str, list[_SampleRecord]]:
        if not samples:
            return {"train": [], "val": [], "test": []}

        total = len(samples)
        train_count = int(total * self.config.train_ratio)
        val_count = int(total * self.config.val_ratio)
        test_count = total - train_count - val_count

        if total >= 2 and train_count == 0:
            train_count = 1
            test_count = max(0, total - train_count - val_count)
        if total >= 3 and test_count == 0:
            test_count = 1
            if train_count > 1:
                train_count -= 1
            elif val_count > 0:
                val_count -= 1

        reassigned = []
        for index, sample in enumerate(samples):
            if index < train_count:
                split = "train"
            elif index < train_count + val_count:
                split = "val"
            else:
                split = "test"
            reassigned.append(
                _SampleRecord(
                    source=sample.source,
                    target=sample.target,
                    edge_type=sample.edge_type,
                    source_type=sample.source_type,
                    target_type=sample.target_type,
                    label=sample.label,
                    split=split,
                    negative_kind=sample.negative_kind,
                )
            )

        output = {"train": [], "val": [], "test": []}
        for sample in reassigned:
            output[sample.split].append(sample)
        return output

    def _run_probe_models(
        self,
        normalized: _NormalizedGraph,
        split_samples: dict[str, list[_SampleRecord]],
    ) -> tuple[dict[str, Any], dict[str, list[float]]]:
        eval_samples = split_samples["test"] or split_samples["val"]
        train_samples = split_samples["train"]

        models: dict[str, Any] = {}
        score_maps: dict[str, list[float]] = {}

        score_maps["type_prior"] = self._score_with_type_prior(
            train_samples, eval_samples
        )
        score_maps["degree_only"] = self._score_with_degree_only(
            normalized, eval_samples
        )

        if normalized.node_features:
            score_maps["text_cosine"] = self._score_with_text_cosine(
                normalized, eval_samples
            )
        else:
            models["text_cosine"] = {
                "status": "skipped",
                "reason": "missing_node_features",
            }

        if self.config.include_node2vec_probe:
            score_or_reason = self._score_with_node2vec(
                normalized, train_samples, eval_samples
            )
            if isinstance(score_or_reason, list):
                score_maps["node2vec"] = score_or_reason
            else:
                models["node2vec"] = score_or_reason

        if self.config.include_graphsage_probe:
            score_or_reason = self._score_with_graphsage(
                normalized, train_samples, eval_samples
            )
            if isinstance(score_or_reason, list):
                score_maps["graphsage_text_v1"] = score_or_reason
            else:
                models["graphsage_text_v1"] = score_or_reason

        for model_name, scores in score_maps.items():
            per_edge_type = {}
            for edge_type in sorted({sample.edge_type for sample in eval_samples}):
                edge_samples = [
                    sample for sample in eval_samples if sample.edge_type == edge_type
                ]
                edge_scores = [
                    score
                    for sample, score in zip(eval_samples, scores)
                    if sample.edge_type == edge_type
                ]
                per_edge_type[edge_type] = _metric_bundle(edge_samples, edge_scores)

            models[model_name] = {
                "status": "completed",
                "overall": _metric_bundle(eval_samples, scores),
                "per_edge_type": per_edge_type,
            }

        primary_probe_model = None
        for candidate in (
            "graphsage_text_v1",
            "node2vec",
            "text_cosine",
            "degree_only",
        ):
            if models.get(candidate, {}).get("status") == "completed":
                primary_probe_model = candidate
                break

        return (
            {
                "primary_probe_model": primary_probe_model,
                "controls": ["type_prior", "degree_only", "text_cosine"],
                "trivial_controls": ["type_prior", "degree_only"],
                "evaluation_split": "test" if split_samples["test"] else "val",
                "models": models,
            },
            score_maps,
        )

    def _score_with_type_prior(
        self, train_samples: list[_SampleRecord], eval_samples: list[_SampleRecord]
    ) -> list[float]:
        positives = [sample for sample in train_samples if sample.label == 1]
        counts = Counter(
            (sample.edge_type, sample.source_type, sample.target_type)
            for sample in positives
        )
        total_by_edge = Counter(sample.edge_type for sample in positives)
        scores = []
        for sample in eval_samples:
            numerator = (
                counts[(sample.edge_type, sample.source_type, sample.target_type)] + 1
            )
            denominator = total_by_edge[sample.edge_type] + len(counts) + 1
            scores.append(numerator / denominator)
        return scores

    def _score_with_degree_only(
        self, normalized: _NormalizedGraph, eval_samples: list[_SampleRecord]
    ) -> list[float]:
        degree = Counter()
        for edge in normalized.edges:
            degree[edge.source] += 1
            degree[edge.target] += 1
        return [
            math.log1p(degree[sample.source] + 1)
            * math.log1p(degree[sample.target] + 1)
            for sample in eval_samples
        ]

    def _score_with_text_cosine(
        self, normalized: _NormalizedGraph, eval_samples: list[_SampleRecord]
    ) -> list[float]:
        scores = []
        for sample in eval_samples:
            scores.append(
                _cosine_similarity(
                    normalized.node_features.get(sample.source),
                    normalized.node_features.get(sample.target),
                )
            )
        return scores

    def _score_with_node2vec(
        self,
        normalized: _NormalizedGraph,
        train_samples: list[_SampleRecord],
        eval_samples: list[_SampleRecord],
    ) -> list[float] | dict[str, Any]:
        if not GRAPH_EMBEDDING_DEPS_AVAILABLE:
            payload = {
                "status": "skipped",
                "reason": "graph_embedding_dependencies_unavailable",
            }
            if GRAPH_EMBEDDING_IMPORT_ERROR:
                payload["detail"] = GRAPH_EMBEDDING_IMPORT_ERROR
            return payload

        training_graph = {
            "nodes": normalized.nodes,
            "edges": [
                {
                    "source": sample.source,
                    "target": sample.target,
                    "edge_type": sample.edge_type,
                }
                for sample in train_samples
                if sample.label == 1
            ],
        }

        try:
            config = EmbeddingConfig(
                embedding_type=EmbeddingType.NODE2VEC,
                dimensions=self.config.node2vec_dimensions,
                walk_length=self.config.node2vec_walk_length,
                num_walks=self.config.node2vec_num_walks,
            )
            embedder = GraphEmbedder(EmbeddingType.NODE2VEC, config)
            embeddings = embedder.fit(training_graph)
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Node2Vec probe skipped: %s", exc)
            return {"status": "skipped", "reason": f"node2vec_failed: {exc}"}

        return [
            _cosine_similarity(
                embeddings.get(sample.source), embeddings.get(sample.target)
            )
            for sample in eval_samples
        ]

    def _score_with_graphsage(
        self,
        normalized: _NormalizedGraph,
        train_samples: list[_SampleRecord],
        eval_samples: list[_SampleRecord],
    ) -> list[float] | dict[str, Any]:
        if not TORCH_AVAILABLE:
            return {"status": "skipped", "reason": "torch_or_pyg_unavailable"}

        if not normalized.node_features:
            return {"status": "skipped", "reason": "missing_node_features"}

        train_positive_edges = [
            (sample.source, sample.target)
            for sample in train_samples
            if sample.label == 1
        ]
        train_negative_edges = [
            (sample.source, sample.target)
            for sample in train_samples
            if sample.label == 0
        ]
        if not train_positive_edges or not train_negative_edges:
            return {"status": "skipped", "reason": "insufficient_train_edges"}

        training_graph = {
            "nodes": normalized.nodes,
            "edges": [
                {"source": src, "target": dst} for src, dst in train_positive_edges
            ],
            "node_features": {
                node_id: features.tolist()
                for node_id, features in normalized.node_features.items()
            },
        }
        input_dim = len(next(iter(normalized.node_features.values())))
        config = GNNConfig(
            model_type=GNNModelType.GRAPHSAGE,
            input_dim=input_dim,
            hidden_dim=self.config.graphsage_hidden_dim,
            output_dim=self.config.graphsage_output_dim,
            num_layers=self.config.graphsage_num_layers,
            dropout=self.config.graphsage_dropout,
            learning_rate=self.config.graphsage_learning_rate,
            epochs=self.config.graphsage_epochs,
            early_stopping_patience=max(5, self.config.graphsage_epochs // 4),
        )

        try:
            predictor = GNNPredictor(GNNModelType.GRAPHSAGE, config)
            predictor.build_model()
            predictor.train_link_prediction(
                training_graph, train_positive_edges, train_negative_edges
            )
            predictions = predictor.predict(
                training_graph,
                task_type="link_prediction",
                test_edges=[(sample.source, sample.target) for sample in eval_samples],
            )
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("GraphSAGE probe skipped: %s", exc)
            return {"status": "skipped", "reason": f"graphsage_failed: {exc}"}

        raw_scores = predictions.get("link_probabilities", [])
        return [float(score) for score in raw_scores]

    def _build_graph_diagnostic_report(
        self,
        normalized: _NormalizedGraph,
        split_manifest: dict[str, Any],
        probe_model_comparison: dict[str, Any],
    ) -> dict[str, Any]:
        node_type_counts = Counter(
            normalized.node_types.get(node_id, "Unknown")
            for node_id in normalized.nodes
        )
        edge_type_counts = Counter(edge.edge_type for edge in normalized.edges)
        degree = Counter()
        for edge in normalized.edges:
            degree[edge.source] += 1
            degree[edge.target] += 1

        orphan_counts = Counter()
        for node_id in normalized.nodes:
            if degree[node_id] == 0:
                orphan_counts[normalized.node_types.get(node_id, "Unknown")] += 1

        total_nodes = len(normalized.nodes)
        total_edges = len(normalized.edges)
        primary_probe_model = probe_model_comparison.get("primary_probe_model")
        models = probe_model_comparison.get("models", {})
        control_models = [
            model_name
            for model_name in probe_model_comparison.get("trivial_controls", [])
            if models.get(model_name, {}).get("status") == "completed"
        ]

        per_edge_type_diagnostics = {}
        edge_scores_for_summary = []
        key_edge_types = self.config.key_edge_types or sorted(edge_type_counts.keys())

        for edge_type in sorted(edge_type_counts.keys()):
            positives = (
                split_manifest["per_edge_type"]
                .get(edge_type, {})
                .get("positive_edges", 0)
            )
            primary_metrics = (
                models.get(primary_probe_model, {})
                .get("per_edge_type", {})
                .get(edge_type, {})
                if primary_probe_model
                else {}
            )
            control_aurocs = [
                models[model_name]["per_edge_type"].get(edge_type, {}).get("auroc")
                for model_name in control_models
            ]
            control_aurocs = [score for score in control_aurocs if score is not None]
            primary_auroc = primary_metrics.get("auroc")
            best_control = max(control_aurocs) if control_aurocs else None
            control_margin = (
                primary_auroc - best_control
                if primary_auroc is not None and best_control is not None
                else None
            )
            coverage_ratio = positives / total_edges if total_edges else 0.0

            bucket = self._diagnostic_bucket(
                positives=positives,
                primary_auroc=primary_auroc,
                control_margin=control_margin,
            )

            if primary_auroc is not None:
                coverage_component = min(
                    1.0, positives / max(1, self.config.min_positive_edges_per_type * 2)
                )
                margin_component = max(0.0, control_margin or 0.0)
                edge_score = min(
                    1.0,
                    0.55 * primary_auroc
                    + 0.25 * margin_component
                    + 0.20 * coverage_component,
                )
                if edge_type in key_edge_types:
                    edge_scores_for_summary.append(edge_score)

            per_edge_type_diagnostics[edge_type] = {
                "positive_edges": positives,
                "coverage_ratio": coverage_ratio,
                "primary_probe_model": primary_probe_model,
                "primary_probe_metrics": primary_metrics,
                "best_control_auroc": best_control,
                "control_margin": control_margin,
                "diagnostic_bucket": bucket,
            }

        overall_degree_values = [degree[node_id] for node_id in normalized.nodes]
        report = {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "node_type_counts": dict(node_type_counts),
            "edge_type_counts": dict(edge_type_counts),
            "per_node_type_coverage": {
                node_type: {
                    "count": count,
                    "coverage_ratio": count / total_nodes if total_nodes else 0.0,
                    "orphans": orphan_counts.get(node_type, 0),
                    "orphan_rate": (
                        orphan_counts.get(node_type, 0) / count if count else 0.0
                    ),
                    "mean_degree": (
                        float(
                            np.mean(
                                [
                                    degree[node_id]
                                    for node_id in normalized.nodes
                                    if normalized.node_types.get(node_id, "Unknown")
                                    == node_type
                                ]
                            )
                        )
                        if count
                        else 0.0
                    ),
                }
                for node_type, count in sorted(node_type_counts.items())
            },
            "degree_statistics": {
                "mean_degree": (
                    float(np.mean(overall_degree_values))
                    if overall_degree_values
                    else 0.0
                ),
                "median_degree": (
                    float(np.median(overall_degree_values))
                    if overall_degree_values
                    else 0.0
                ),
                "max_degree": (
                    int(max(overall_degree_values)) if overall_degree_values else 0
                ),
            },
            "per_edge_type_diagnostics": per_edge_type_diagnostics,
            "primary_probe_model": primary_probe_model,
            "structure_consistency_score": (
                float(np.mean(edge_scores_for_summary))
                if edge_scores_for_summary
                else 0.0
            ),
        }
        return report

    def _build_fairness_audit_report(
        self,
        *,
        normalized: _NormalizedGraph,
        split_samples: dict[str, list[_SampleRecord]],
        probe_model_comparison: dict[str, Any],
        score_maps: dict[str, list[float]],
    ) -> dict[str, Any]:
        requested_group_keys = [
            key for key in self.config.audit_group_keys if str(key).strip()
        ]
        evaluation_split = probe_model_comparison.get("evaluation_split", "test")
        eval_samples = split_samples.get(evaluation_split, [])
        primary_probe_model = probe_model_comparison.get("primary_probe_model")
        models = probe_model_comparison.get("models", {})
        controls = [
            model_name
            for model_name in probe_model_comparison.get("trivial_controls", [])
            if models.get(model_name, {}).get("status") == "completed"
        ]

        if not requested_group_keys:
            return {
                "schema_version": "br_kg-fairness-audit-v1",
                "status": "not_requested",
                "requested_group_keys": [],
                "resolved_group_keys": [],
                "missing_group_keys": [],
                "evaluation_split": evaluation_split,
                "primary_probe_model": primary_probe_model,
                "group_scope": self.config.audit_group_scope,
                "min_group_samples": self.config.min_group_samples,
                "per_group_key": {},
            }

        if self.config.audit_group_scope != "source":
            raise ValueError(
                f"Unsupported audit_group_scope={self.config.audit_group_scope!r}; only 'source' is currently supported"
            )

        source_node_ids = sorted({sample.source for sample in eval_samples})
        source_properties = {
            node_id: normalized.node_properties.get(node_id, {})
            for node_id in source_node_ids
        }
        available_keys = {
            _normalize_group_key(key): key
            for props in source_properties.values()
            for key, value in props.items()
            if _group_value(value) is not None
        }

        resolved_group_keys: list[str] = []
        missing_group_keys: list[str] = []
        per_group_key: dict[str, Any] = {}

        for requested_key in requested_group_keys:
            normalized_key = _normalize_group_key(requested_key)
            resolved_key = available_keys.get(normalized_key)
            if resolved_key is None:
                missing_group_keys.append(requested_key)
                continue

            resolved_group_keys.append(resolved_key)
            node_groups: dict[str, str] = {}
            missing_nodes = 0
            for node_id, props in source_properties.items():
                value = _group_value(props.get(resolved_key))
                if value is None:
                    missing_nodes += 1
                    continue
                node_groups[node_id] = value

            group_node_counts = Counter(node_groups.values())
            grouped_samples: dict[str, list[tuple[_SampleRecord, int]]] = defaultdict(
                list
            )
            missing_eval_samples = 0
            for index, sample in enumerate(eval_samples):
                group_value = node_groups.get(sample.source)
                if group_value is None:
                    missing_eval_samples += 1
                    continue
                grouped_samples[group_value].append((sample, index))

            per_value = {}
            for group_value, sample_rows in sorted(grouped_samples.items()):
                sample_indices = [index for _, index in sample_rows]
                group_samples = [sample for sample, _ in sample_rows]
                positive_edges = sum(1 for sample in group_samples if sample.label == 1)
                negative_edges = sum(1 for sample in group_samples if sample.label == 0)
                primary_scores = (
                    [score_maps[primary_probe_model][index] for index in sample_indices]
                    if primary_probe_model in score_maps
                    else []
                )
                primary_metrics = (
                    _metric_bundle(group_samples, primary_scores)
                    if primary_scores
                    else {}
                )
                primary_auroc = primary_metrics.get("auroc")

                control_aurocs: list[float] = []
                for model_name in controls:
                    scores = score_maps.get(model_name)
                    if scores is None:
                        continue
                    metrics = _metric_bundle(
                        group_samples,
                        [scores[index] for index in sample_indices],
                    )
                    auroc = metrics.get("auroc")
                    if auroc is not None:
                        control_aurocs.append(auroc)
                best_control = max(control_aurocs) if control_aurocs else None
                control_margin = (
                    primary_auroc - best_control
                    if primary_auroc is not None and best_control is not None
                    else None
                )
                underpowered = (
                    len(group_samples) < self.config.min_group_samples
                    or positive_edges < self.config.min_positive_edges_per_type
                )
                bucket = (
                    "underpowered"
                    if underpowered
                    else self._diagnostic_bucket(
                        positives=positive_edges,
                        primary_auroc=primary_auroc,
                        control_margin=control_margin,
                    )
                )

                per_edge_type = {}
                for edge_type in sorted({sample.edge_type for sample in group_samples}):
                    edge_rows = [
                        (sample, idx)
                        for sample, idx in sample_rows
                        if sample.edge_type == edge_type
                    ]
                    edge_indices = [idx for _, idx in edge_rows]
                    edge_samples = [sample for sample, _ in edge_rows]
                    edge_positive_edges = sum(
                        1 for sample in edge_samples if sample.label == 1
                    )
                    edge_primary_scores = (
                        [score_maps[primary_probe_model][idx] for idx in edge_indices]
                        if primary_probe_model in score_maps
                        else []
                    )
                    edge_primary_metrics = (
                        _metric_bundle(edge_samples, edge_primary_scores)
                        if edge_primary_scores
                        else {}
                    )
                    edge_primary_auroc = edge_primary_metrics.get("auroc")
                    edge_control_aurocs: list[float] = []
                    for model_name in controls:
                        scores = score_maps.get(model_name)
                        if scores is None:
                            continue
                        metrics = _metric_bundle(
                            edge_samples,
                            [scores[idx] for idx in edge_indices],
                        )
                        auroc = metrics.get("auroc")
                        if auroc is not None:
                            edge_control_aurocs.append(auroc)
                    edge_best_control = (
                        max(edge_control_aurocs) if edge_control_aurocs else None
                    )
                    edge_control_margin = (
                        edge_primary_auroc - edge_best_control
                        if edge_primary_auroc is not None
                        and edge_best_control is not None
                        else None
                    )
                    edge_bucket = (
                        "underpowered"
                        if (
                            len(edge_samples) < self.config.min_group_samples
                            or edge_positive_edges
                            < self.config.min_positive_edges_per_type
                        )
                        else self._diagnostic_bucket(
                            positives=edge_positive_edges,
                            primary_auroc=edge_primary_auroc,
                            control_margin=edge_control_margin,
                        )
                    )
                    per_edge_type[edge_type] = {
                        "sample_count": len(edge_samples),
                        "positive_edges": edge_positive_edges,
                        "negative_edges": sum(
                            1 for sample in edge_samples if sample.label == 0
                        ),
                        "primary_probe_metrics": edge_primary_metrics,
                        "best_control_auroc": edge_best_control,
                        "control_margin": edge_control_margin,
                        "diagnostic_bucket": edge_bucket,
                    }

                per_value[group_value] = {
                    "node_count": int(group_node_counts.get(group_value, 0)),
                    "sample_count": len(group_samples),
                    "positive_edges": positive_edges,
                    "negative_edges": negative_edges,
                    "primary_probe_metrics": primary_metrics,
                    "best_control_auroc": best_control,
                    "control_margin": control_margin,
                    "diagnostic_bucket": bucket,
                    "per_edge_type": per_edge_type,
                }

            disparity_summary = {}
            observed_edge_types = sorted(
                {
                    edge_type
                    for group_payload in per_value.values()
                    for edge_type in group_payload["per_edge_type"].keys()
                }
            )
            for edge_type in observed_edge_types:
                group_aurocs = {
                    group_name: group_payload["per_edge_type"][edge_type][
                        "primary_probe_metrics"
                    ].get("auroc")
                    for group_name, group_payload in per_value.items()
                    if group_payload["per_edge_type"].get(edge_type)
                    and group_payload["per_edge_type"][edge_type]["diagnostic_bucket"]
                    != "underpowered"
                    and group_payload["per_edge_type"][edge_type][
                        "primary_probe_metrics"
                    ].get("auroc")
                    is not None
                }
                if len(group_aurocs) < 2:
                    continue
                disparity_summary[edge_type] = {
                    "max_auroc_gap": max(group_aurocs.values())
                    - min(group_aurocs.values()),
                    "best_group": max(group_aurocs, key=group_aurocs.get),
                    "worst_group": min(group_aurocs, key=group_aurocs.get),
                }

            per_group_key[resolved_key] = {
                "node_coverage": {
                    "total_source_nodes": len(source_node_ids),
                    "resolved_source_nodes": len(node_groups),
                    "missing_source_nodes": missing_nodes,
                    "coverage_ratio": (
                        len(node_groups) / len(source_node_ids)
                        if source_node_ids
                        else 0.0
                    ),
                },
                "sample_coverage": {
                    "evaluation_samples": len(eval_samples),
                    "resolved_samples": sum(
                        len(items) for items in grouped_samples.values()
                    ),
                    "missing_samples": missing_eval_samples,
                    "coverage_ratio": (
                        sum(len(items) for items in grouped_samples.values())
                        / len(eval_samples)
                        if eval_samples
                        else 0.0
                    ),
                },
                "underpowered_groups": sorted(
                    group_name
                    for group_name, payload in per_value.items()
                    if payload["sample_count"] < self.config.min_group_samples
                    or payload["positive_edges"]
                    < self.config.min_positive_edges_per_type
                ),
                "per_group_value": per_value,
                "disparity_summary": disparity_summary,
            }

        status = "completed" if resolved_group_keys else "no_resolved_groups"
        return {
            "schema_version": "br_kg-fairness-audit-v1",
            "status": status,
            "requested_group_keys": requested_group_keys,
            "resolved_group_keys": resolved_group_keys,
            "missing_group_keys": missing_group_keys,
            "evaluation_split": evaluation_split,
            "primary_probe_model": primary_probe_model,
            "group_scope": self.config.audit_group_scope,
            "min_group_samples": self.config.min_group_samples,
            "per_group_key": per_group_key,
        }

    def _write_artifacts(self, output_dir: str, result: dict[str, Any]) -> None:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        artifact_map = {
            "benchmark_manifest.json": {
                "benchmark_id": result["benchmark_id"],
                "config": result["config"],
                "graph_metadata": result["graph_metadata"],
            },
            "split_manifest.json": result["split_manifest"],
            "graph_diagnostic_report.json": result["graph_diagnostic_report"],
            "fairness_audit_report.json": result["fairness_audit_report"],
            "probe_model_comparison.json": result["probe_model_comparison"],
        }

        for filename, payload in artifact_map.items():
            (output_path / filename).write_text(
                json.dumps(_json_ready(payload), indent=2, sort_keys=True),
                encoding="utf-8",
            )


def run_structural_quality_benchmark(
    graph_data: dict[str, Any],
    config: Optional[StructuralQualityBenchmarkConfig] = None,
    output_dir: Optional[str] = None,
    graph_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience wrapper for the structural quality benchmark."""

    benchmark = StructuralQualityBenchmark(config=config)
    return benchmark.run(
        graph_data=graph_data, output_dir=output_dir, graph_metadata=graph_metadata
    )
