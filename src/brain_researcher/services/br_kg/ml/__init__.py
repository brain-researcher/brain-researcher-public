"""Graph Machine Learning infrastructure for advanced analytics.

This module provides Graph Neural Networks (GNNs), graph embeddings, and
ML pipelines for knowledge graph analysis and prediction tasks.

Key Components:
- GNN Models: GCN, GraphSAGE, GAT implementations
- Graph Embeddings: Node2Vec, Graph2Vec, DeepWalk
- ML Pipeline: Training, inference, and evaluation workflows
"""

from .gnn_models import (
    GNNModelType,
    GNNPredictor,
    GraphAttentionNetwork,
    GraphConvolutionalNetwork,
    GraphSAGE,
)
from .graph_embeddings import (
    DeepWalkEmbedder,
    EmbeddingType,
    Graph2VecEmbedder,
    GraphEmbedder,
    Node2VecEmbedder,
)
from .ml_pipeline import (
    MLPipeline,
    ModelEvaluator,
    ModelTrainer,
    PredictionService,
    TaskType,
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
    "TaskType",
]
