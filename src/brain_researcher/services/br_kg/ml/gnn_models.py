"""Graph Neural Network models - completes KG-031 Graph ML.

This module provides GCN, GraphSAGE, and GAT implementations for
node classification, link prediction, and graph-level tasks.
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import pickle
import json
from pathlib import Path

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.optim import Adam, AdamW
    from torch_geometric.nn import GCNConv, SAGEConv, GATConv, global_mean_pool, global_max_pool
    from torch_geometric.data import Data, Batch
    from torch_geometric.utils import to_networkx, from_networkx
    import networkx as nx
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    nn = None
    F = None
    Adam = None
    AdamW = None
    GCNConv = None
    SAGEConv = None
    GATConv = None
    global_mean_pool = None
    global_max_pool = None
    Data = None
    Batch = None
    to_networkx = None
    from_networkx = None
    nx = None
    TORCH_AVAILABLE = False

logger = logging.getLogger(__name__)

_NNModuleBase = nn.Module if TORCH_AVAILABLE else object


class GNNModelType(Enum):
    """Types of GNN models."""

    GCN = "gcn"  # Graph Convolutional Network
    GRAPHSAGE = "graphsage"  # GraphSAGE
    GAT = "gat"  # Graph Attention Network


@dataclass
class GNNConfig:
    """Configuration for GNN models."""

    model_type: GNNModelType
    input_dim: int
    hidden_dim: int = 128
    output_dim: int = 64
    num_layers: int = 3
    dropout: float = 0.5
    activation: str = "relu"

    # Model-specific parameters
    heads: int = 8  # For GAT
    concat_heads: bool = True  # For GAT
    aggr: str = "mean"  # For GraphSAGE

    # Training parameters
    learning_rate: float = 0.001
    weight_decay: float = 5e-4
    batch_size: int = 32
    epochs: int = 200
    early_stopping_patience: int = 50

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_type": self.model_type.value,
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "output_dim": self.output_dim,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "activation": self.activation,
            "heads": self.heads,
            "concat_heads": self.concat_heads,
            "aggr": self.aggr,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "batch_size": self.batch_size,
            "epochs": self.epochs,
            "early_stopping_patience": self.early_stopping_patience
        }


class GraphConvolutionalNetwork(_NNModuleBase):
    """Graph Convolutional Network (GCN) implementation."""

    def __init__(self, config: GNNConfig):
        """Initialize GCN model.

        Args:
            config: Model configuration
        """
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for GNN models")

        super().__init__()
        self.config = config

        # Build layers
        self.layers = nn.ModuleList()

        # Input layer
        self.layers.append(GCNConv(config.input_dim, config.hidden_dim))

        # Hidden layers
        for _ in range(config.num_layers - 2):
            self.layers.append(GCNConv(config.hidden_dim, config.hidden_dim))

        # Output layer
        if config.num_layers > 1:
            self.layers.append(GCNConv(config.hidden_dim, config.output_dim))

        # Dropout and activation
        self.dropout = nn.Dropout(config.dropout)
        self.activation = getattr(F, config.activation)

    def forward(self, x, edge_index, batch=None):
        """Forward pass.

        Args:
            x: Node features [num_nodes, input_dim]
            edge_index: Edge connectivity [2, num_edges]
            batch: Batch assignment for graph-level tasks

        Returns:
            Node embeddings [num_nodes, output_dim]
        """
        # Apply GCN layers
        for i, layer in enumerate(self.layers[:-1]):
            x = layer(x, edge_index)
            x = self.activation(x)
            x = self.dropout(x)

        # Final layer without activation
        if len(self.layers) > 1:
            x = self.layers[-1](x, edge_index)

        return x

    def predict_node_class(self, x, edge_index, num_classes):
        """Predict node classes.

        Args:
            x: Node features
            edge_index: Edge connectivity
            num_classes: Number of classes

        Returns:
            Class predictions [num_nodes, num_classes]
        """
        embeddings = self.forward(x, edge_index)

        # Add classification head if needed
        if not hasattr(self, 'classifier'):
            self.classifier = nn.Linear(self.config.output_dim, num_classes)

        return self.classifier(embeddings)

    def predict_links(self, x, edge_index, test_edges):
        """Predict link probabilities.

        Args:
            x: Node features
            edge_index: Edge connectivity
            test_edges: Edge pairs to predict [2, num_test_edges]

        Returns:
            Link probabilities [num_test_edges]
        """
        embeddings = self.forward(x, edge_index)

        # Get embeddings for edge endpoints
        src_embeddings = embeddings[test_edges[0]]
        dst_embeddings = embeddings[test_edges[1]]

        # Compute link scores (dot product)
        link_scores = torch.sum(src_embeddings * dst_embeddings, dim=1)

        return torch.sigmoid(link_scores)


class GraphSAGE(_NNModuleBase):
    """GraphSAGE implementation."""

    def __init__(self, config: GNNConfig):
        """Initialize GraphSAGE model.

        Args:
            config: Model configuration
        """
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for GNN models")

        super().__init__()
        self.config = config

        # Build layers
        self.layers = nn.ModuleList()

        # Input layer
        self.layers.append(SAGEConv(config.input_dim, config.hidden_dim, aggr=config.aggr))

        # Hidden layers
        for _ in range(config.num_layers - 2):
            self.layers.append(SAGEConv(config.hidden_dim, config.hidden_dim, aggr=config.aggr))

        # Output layer
        if config.num_layers > 1:
            self.layers.append(SAGEConv(config.hidden_dim, config.output_dim, aggr=config.aggr))

        # Dropout and activation
        self.dropout = nn.Dropout(config.dropout)
        self.activation = getattr(F, config.activation)

    def forward(self, x, edge_index, batch=None):
        """Forward pass."""
        # Apply SAGE layers
        for i, layer in enumerate(self.layers[:-1]):
            x = layer(x, edge_index)
            x = self.activation(x)
            x = self.dropout(x)

        # Final layer
        if len(self.layers) > 1:
            x = self.layers[-1](x, edge_index)

        return x


class GraphAttentionNetwork(_NNModuleBase):
    """Graph Attention Network (GAT) implementation."""

    def __init__(self, config: GNNConfig):
        """Initialize GAT model.

        Args:
            config: Model configuration
        """
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for GNN models")

        super().__init__()
        self.config = config

        # Build layers
        self.layers = nn.ModuleList()

        # Input layer
        self.layers.append(
            GATConv(
                config.input_dim,
                config.hidden_dim // config.heads if config.concat_heads else config.hidden_dim,
                heads=config.heads,
                concat=config.concat_heads,
                dropout=config.dropout
            )
        )

        # Hidden layers
        for _ in range(config.num_layers - 2):
            self.layers.append(
                GATConv(
                    config.hidden_dim,
                    config.hidden_dim // config.heads if config.concat_heads else config.hidden_dim,
                    heads=config.heads,
                    concat=config.concat_heads,
                    dropout=config.dropout
                )
            )

        # Output layer
        if config.num_layers > 1:
            self.layers.append(
                GATConv(
                    config.hidden_dim,
                    config.output_dim,
                    heads=1,
                    concat=False,
                    dropout=config.dropout
                )
            )

        # Activation
        self.activation = getattr(F, config.activation)

    def forward(self, x, edge_index, batch=None):
        """Forward pass."""
        # Apply GAT layers
        for i, layer in enumerate(self.layers[:-1]):
            x = layer(x, edge_index)
            x = self.activation(x)

        # Final layer
        if len(self.layers) > 1:
            x = self.layers[-1](x, edge_index)

        return x


class GNNPredictor:
    """High-level interface for GNN predictions."""

    def __init__(self, model_type: GNNModelType, config: Optional[GNNConfig] = None):
        """Initialize GNN predictor.

        Args:
            model_type: Type of GNN model to use
            config: Model configuration
        """
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch and PyTorch Geometric are required for GNN models")

        self.model_type = model_type
        self.config = config
        self.model = None
        self.optimizer = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        # Training history
        self.training_history = []

        logger.info(f"Initialized GNN predictor with {model_type.value} on {self.device}")

    def build_model(self, input_dim: int, output_dim: int, **kwargs):
        """Build the GNN model.

        Args:
            input_dim: Input feature dimension
            output_dim: Output dimension
            **kwargs: Additional configuration parameters
        """
        if self.config is None:
            self.config = GNNConfig(
                model_type=self.model_type,
                input_dim=input_dim,
                output_dim=output_dim,
                **kwargs
            )
        else:
            # Update dimensions
            self.config.input_dim = input_dim
            self.config.output_dim = output_dim

            # Update other parameters
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)

        # Create model based on type
        if self.model_type == GNNModelType.GCN:
            self.model = GraphConvolutionalNetwork(self.config)
        elif self.model_type == GNNModelType.GRAPHSAGE:
            self.model = GraphSAGE(self.config)
        elif self.model_type == GNNModelType.GAT:
            self.model = GraphAttentionNetwork(self.config)
        else:
            raise ValueError(f"Unsupported model type: {self.model_type}")

        self.model = self.model.to(self.device)

        # Setup optimizer
        self.optimizer = Adam(
            self.model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay
        )

        logger.info(f"Built {self.model_type.value} model with {sum(p.numel() for p in self.model.parameters())} parameters")

    def prepare_graph_data(self, graph_data: Dict[str, Any]) -> Data:
        """Prepare graph data for PyTorch Geometric.

        Args:
            graph_data: Dictionary with nodes, edges, and features

        Returns:
            PyTorch Geometric Data object
        """
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        node_features = graph_data.get("node_features", {})

        # Create node feature matrix
        if node_features:
            feature_dim = len(list(node_features.values())[0])
            x = torch.zeros(len(nodes), feature_dim, dtype=torch.float)

            node_id_to_idx = {node_id: idx for idx, node_id in enumerate(nodes)}

            for node_id, features in node_features.items():
                if node_id in node_id_to_idx:
                    x[node_id_to_idx[node_id]] = torch.tensor(features, dtype=torch.float)
        else:
            # Use identity features if no features provided
            x = torch.eye(len(nodes), dtype=torch.float)

        # Create edge index
        edge_index = []
        if edges:
            node_id_to_idx = {node_id: idx for idx, node_id in enumerate(nodes)}

            for edge in edges:
                src_id = edge.get("start") or edge.get("source")
                dst_id = edge.get("end") or edge.get("target")

                if src_id in node_id_to_idx and dst_id in node_id_to_idx:
                    edge_index.append([node_id_to_idx[src_id], node_id_to_idx[dst_id]])

        if edge_index:
            edge_index = torch.tensor(edge_index, dtype=torch.long).t()
        else:
            edge_index = torch.zeros((2, 0), dtype=torch.long)

        return Data(x=x, edge_index=edge_index).to(self.device)

    def train_node_classification(
        self,
        graph_data: Dict[str, Any],
        labels: Dict[str, int],
        train_mask: Optional[List[str]] = None,
        val_mask: Optional[List[str]] = None,
        num_classes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Train for node classification task.

        Args:
            graph_data: Graph structure and features
            labels: Node labels {node_id: class_label}
            train_mask: Training node IDs
            val_mask: Validation node IDs
            num_classes: Number of classes

        Returns:
            Training results
        """
        if self.model is None:
            raise ValueError("Model not built. Call build_model() first.")

        # Prepare data
        data = self.prepare_graph_data(graph_data)
        nodes = graph_data.get("nodes", [])
        node_id_to_idx = {node_id: idx for idx, node_id in enumerate(nodes)}

        # Prepare labels
        if num_classes is None:
            num_classes = len(set(labels.values()))

        y = torch.zeros(len(nodes), dtype=torch.long)
        for node_id, label in labels.items():
            if node_id in node_id_to_idx:
                y[node_id_to_idx[node_id]] = label
        y = y.to(self.device)

        # Prepare masks
        if train_mask is None:
            train_mask = list(labels.keys())[:int(0.8 * len(labels))]
        if val_mask is None:
            val_mask = list(labels.keys())[int(0.8 * len(labels)):]

        train_idx = [node_id_to_idx[nid] for nid in train_mask if nid in node_id_to_idx]
        val_idx = [node_id_to_idx[nid] for nid in val_mask if nid in node_id_to_idx]

        train_mask_tensor = torch.zeros(len(nodes), dtype=torch.bool)
        val_mask_tensor = torch.zeros(len(nodes), dtype=torch.bool)
        train_mask_tensor[train_idx] = True
        val_mask_tensor[val_idx] = True
        train_mask_tensor = train_mask_tensor.to(self.device)
        val_mask_tensor = val_mask_tensor.to(self.device)

        # Training loop
        self.model.train()
        best_val_acc = 0
        patience_counter = 0

        for epoch in range(self.config.epochs):
            self.optimizer.zero_grad()

            # Forward pass
            out = self.model.predict_node_class(data.x, data.edge_index, num_classes)
            loss = F.cross_entropy(out[train_mask_tensor], y[train_mask_tensor])

            # Backward pass
            loss.backward()
            self.optimizer.step()

            # Validation
            if epoch % 10 == 0:
                self.model.eval()
                with torch.no_grad():
                    val_out = self.model.predict_node_class(data.x, data.edge_index, num_classes)
                    val_pred = val_out[val_mask_tensor].argmax(dim=1)
                    val_acc = (val_pred == y[val_mask_tensor]).float().mean().item()

                    train_pred = out[train_mask_tensor].argmax(dim=1)
                    train_acc = (train_pred == y[train_mask_tensor]).float().mean().item()

                    self.training_history.append({
                        "epoch": epoch,
                        "loss": loss.item(),
                        "train_acc": train_acc,
                        "val_acc": val_acc
                    })

                    logger.info(f"Epoch {epoch}: Loss={loss.item():.4f}, Train Acc={train_acc:.4f}, Val Acc={val_acc:.4f}")

                    # Early stopping
                    if val_acc > best_val_acc:
                        best_val_acc = val_acc
                        patience_counter = 0
                    else:
                        patience_counter += 1

                    if patience_counter >= self.config.early_stopping_patience:
                        logger.info(f"Early stopping at epoch {epoch}")
                        break

                self.model.train()

        return {
            "best_val_acc": best_val_acc,
            "final_loss": loss.item(),
            "training_history": self.training_history,
            "num_epochs": len(self.training_history)
        }

    def train_link_prediction(
        self,
        graph_data: Dict[str, Any],
        positive_edges: List[Tuple[str, str]],
        negative_edges: List[Tuple[str, str]],
        train_ratio: float = 0.8
    ) -> Dict[str, Any]:
        """Train for link prediction task.

        Args:
            graph_data: Graph structure and features
            positive_edges: Positive edge examples
            negative_edges: Negative edge examples
            train_ratio: Ratio of edges for training

        Returns:
            Training results
        """
        if self.model is None:
            raise ValueError("Model not built. Call build_model() first.")

        # Prepare data
        data = self.prepare_graph_data(graph_data)
        nodes = graph_data.get("nodes", [])
        node_id_to_idx = {node_id: idx for idx, node_id in enumerate(nodes)}

        # Convert edges to indices
        def edges_to_indices(edges):
            edge_indices = []
            for src, dst in edges:
                if src in node_id_to_idx and dst in node_id_to_idx:
                    edge_indices.append([node_id_to_idx[src], node_id_to_idx[dst]])
            return torch.tensor(edge_indices, dtype=torch.long).t() if edge_indices else torch.zeros((2, 0), dtype=torch.long)

        pos_edges = edges_to_indices(positive_edges).to(self.device)
        neg_edges = edges_to_indices(negative_edges).to(self.device)

        # Split edges
        num_pos_train = int(train_ratio * pos_edges.size(1))
        num_neg_train = int(train_ratio * neg_edges.size(1))

        pos_train_edges = pos_edges[:, :num_pos_train]
        pos_val_edges = pos_edges[:, num_pos_train:]
        neg_train_edges = neg_edges[:, :num_neg_train]
        neg_val_edges = neg_edges[:, num_neg_train:]

        # Combine training edges
        train_edges = torch.cat([pos_train_edges, neg_train_edges], dim=1)
        train_labels = torch.cat([
            torch.ones(pos_train_edges.size(1)),
            torch.zeros(neg_train_edges.size(1))
        ]).to(self.device)

        val_edges = torch.cat([pos_val_edges, neg_val_edges], dim=1)
        val_labels = torch.cat([
            torch.ones(pos_val_edges.size(1)),
            torch.zeros(neg_val_edges.size(1))
        ]).to(self.device)

        # Training loop
        self.model.train()
        best_val_auc = 0
        patience_counter = 0

        for epoch in range(self.config.epochs):
            self.optimizer.zero_grad()

            # Forward pass
            train_pred = self.model.predict_links(data.x, data.edge_index, train_edges)
            loss = F.binary_cross_entropy(train_pred, train_labels)

            # Backward pass
            loss.backward()
            self.optimizer.step()

            # Validation
            if epoch % 10 == 0:
                self.model.eval()
                with torch.no_grad():
                    val_pred = self.model.predict_links(data.x, data.edge_index, val_edges)

                    # Calculate AUC (simplified)
                    val_pred_np = val_pred.cpu().numpy()
                    val_labels_np = val_labels.cpu().numpy()

                    # Sort by prediction score
                    sorted_indices = np.argsort(-val_pred_np)
                    sorted_labels = val_labels_np[sorted_indices]

                    # Calculate AUC approximately
                    pos_ranks = np.where(sorted_labels == 1)[0]
                    if len(pos_ranks) > 0:
                        val_auc = (pos_ranks.mean() + 1) / len(val_labels_np)
                        val_auc = 1 - val_auc  # Invert for AUC
                    else:
                        val_auc = 0.5

                    train_acc = ((train_pred > 0.5).float() == train_labels).float().mean().item()
                    val_acc = ((val_pred > 0.5).float() == val_labels).float().mean().item()

                    self.training_history.append({
                        "epoch": epoch,
                        "loss": loss.item(),
                        "train_acc": train_acc,
                        "val_acc": val_acc,
                        "val_auc": val_auc
                    })

                    logger.info(f"Epoch {epoch}: Loss={loss.item():.4f}, Train Acc={train_acc:.4f}, Val Acc={val_acc:.4f}, Val AUC={val_auc:.4f}")

                    # Early stopping
                    if val_auc > best_val_auc:
                        best_val_auc = val_auc
                        patience_counter = 0
                    else:
                        patience_counter += 1

                    if patience_counter >= self.config.early_stopping_patience:
                        logger.info(f"Early stopping at epoch {epoch}")
                        break

                self.model.train()

        return {
            "best_val_auc": best_val_auc,
            "final_loss": loss.item(),
            "training_history": self.training_history,
            "num_epochs": len(self.training_history)
        }

    def predict(self, graph_data: Dict[str, Any], task_type: str = "node_embeddings", **kwargs) -> Dict[str, Any]:
        """Make predictions.

        Args:
            graph_data: Graph structure and features
            task_type: Type of prediction task
            **kwargs: Additional parameters

        Returns:
            Predictions
        """
        if self.model is None:
            raise ValueError("Model not built. Call build_model() first.")

        data = self.prepare_graph_data(graph_data)

        self.model.eval()
        with torch.no_grad():
            if task_type == "node_embeddings":
                embeddings = self.model(data.x, data.edge_index)
                return {
                    "embeddings": embeddings.cpu().numpy(),
                    "node_ids": graph_data.get("nodes", [])
                }

            elif task_type == "node_classification":
                num_classes = kwargs.get("num_classes", 2)
                predictions = self.model.predict_node_class(data.x, data.edge_index, num_classes)
                probs = F.softmax(predictions, dim=1)
                return {
                    "predictions": predictions.argmax(dim=1).cpu().numpy(),
                    "probabilities": probs.cpu().numpy(),
                    "node_ids": graph_data.get("nodes", [])
                }

            elif task_type == "link_prediction":
                test_edges = kwargs.get("test_edges", [])
                if test_edges:
                    nodes = graph_data.get("nodes", [])
                    node_id_to_idx = {node_id: idx for idx, node_id in enumerate(nodes)}

                    edge_indices = []
                    for src, dst in test_edges:
                        if src in node_id_to_idx and dst in node_id_to_idx:
                            edge_indices.append([node_id_to_idx[src], node_id_to_idx[dst]])

                    if edge_indices:
                        edge_tensor = torch.tensor(edge_indices, dtype=torch.long).t().to(self.device)
                        link_probs = self.model.predict_links(data.x, data.edge_index, edge_tensor)
                        return {
                            "link_probabilities": link_probs.cpu().numpy(),
                            "test_edges": test_edges
                        }

                return {"link_probabilities": [], "test_edges": []}

            else:
                raise ValueError(f"Unsupported task type: {task_type}")

    def save_model(self, filepath: str):
        """Save trained model.

        Args:
            filepath: Path to save model
        """
        if self.model is None:
            raise ValueError("No model to save")

        save_data = {
            "model_state_dict": self.model.state_dict(),
            "config": self.config.to_dict(),
            "model_type": self.model_type.value,
            "training_history": self.training_history
        }

        torch.save(save_data, filepath)
        logger.info(f"Saved model to {filepath}")

    def load_model(self, filepath: str):
        """Load trained model.

        Args:
            filepath: Path to model file
        """
        save_data = torch.load(filepath, map_location=self.device)

        # Restore configuration
        config_dict = save_data["config"]
        self.config = GNNConfig(
            model_type=GNNModelType(config_dict["model_type"]),
            **{k: v for k, v in config_dict.items() if k != "model_type"}
        )
        self.model_type = GNNModelType(save_data["model_type"])

        # Build and load model
        self.build_model(self.config.input_dim, self.config.output_dim)
        self.model.load_state_dict(save_data["model_state_dict"])

        # Restore training history
        self.training_history = save_data.get("training_history", [])

        logger.info(f"Loaded model from {filepath}")

    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        if self.model is None:
            return {"status": "not_built"}

        return {
            "model_type": self.model_type.value,
            "config": self.config.to_dict() if self.config else None,
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "device": str(self.device),
            "training_epochs": len(self.training_history)
        }
