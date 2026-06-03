"""Graph Machine Learning infrastructure for advanced analytics.

This module provides Graph Neural Networks (GNNs), graph embeddings, and
ML pipelines for knowledge graph analysis and prediction tasks.

Key Components:
- GNN Models: GCN, GraphSAGE, GAT implementations
- Graph Embeddings: Node2Vec, Graph2Vec, DeepWalk
- ML Pipeline: Training, inference, and evaluation workflows
"""

from .gnn_models import (
    GraphConvolutionalNetwork,
    GraphSAGE,
    GraphAttentionNetwork,
    GNNModelType,
    GNNPredictor
)
from .graph_embeddings import (
    Node2VecEmbedder,
    Graph2VecEmbedder,
    DeepWalkEmbedder,
    EmbeddingType,
    GraphEmbedder
)
from .ml_pipeline import (
    MLPipeline,
    ModelTrainer,
    ModelEvaluator,
    PredictionService,
    TaskType
)

__all__ = [
    "GraphConvolutionalNetwork",
    "GraphSAGE",
    "GraphAttentionNetwork",
    "GNNModelType",
    "GNNPredictor",
    "Node2VecEmbedder",
    "Graph2VecEmbedder",
    "DeepWalkEmbedder",
    "EmbeddingType",
    "GraphEmbedder",
    "MLPipeline",
    "ModelTrainer",
    "ModelEvaluator",
    "PredictionService",
    "TaskType"
]