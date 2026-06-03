"""
Advanced deep learning models for neuroimaging.
Implements Vision Transformers, 3D CNNs, Graph Neural Networks, and more.
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from pathlib import Path
import json
from dataclasses import dataclass
from enum import Enum

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from pydantic import BaseModel, Field, ConfigDict
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class DLInput(BaseModel):
    """Base input model for deep learning tools."""
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ModelArchitecture(Enum):
    """Deep learning model architectures."""
    VISION_TRANSFORMER = "vit"
    CNN_3D = "cnn3d"
    GRAPH_NEURAL_NETWORK = "gnn"
    AUTOENCODER = "autoencoder"
    UNET_3D = "unet3d"
    RESNET_3D = "resnet3d"
    DENSENET_3D = "densenet3d"
    TRANSFORMER_ENCODER = "transformer"


class AdvancedDeepLearningTools:
    """Advanced deep learning tools for neuroimaging."""

    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if TORCH_AVAILABLE else None

    def get_all_tools(self):
        """Return all advanced DL tools."""
        return [
            VisionTransformerTool(),
            CNN3DTool(),
            GraphNeuralNetworkTool(),
            AutoencoderTool(),
            UNet3DTool(),
            ResNet3DTool(),
            DenseNet3DTool(),
            TransformerEncoderTool()
        ]


class VisionTransformerTool(NeuroToolWrapper):
    """Vision Transformer for neuroimaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "vision_transformer"

    def get_tool_description(self) -> str:
        return "Vision Transformer (ViT) for brain image analysis"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        input_shape: Tuple[int, int, int] = (64, 64, 64),
        patch_size: int = 8,
        n_classes: int = 2,
        hidden_dim: int = 768,
        n_heads: int = 12,
        n_layers: int = 12,
        task: str = "classification",
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run Vision Transformer model."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(
                    status="error",
                    error="PyTorch not available"
                )

            output_path = Path(output_dir or "vit_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create ViT model
            model = self._create_vit_model(
                input_shape, patch_size, n_classes,
                hidden_dim, n_heads, n_layers
            )

            # Generate synthetic data for demo
            data, labels = self._generate_synthetic_data(
                n_samples=100, shape=input_shape, n_classes=n_classes
            )

            # Train model (simplified)
            metrics = self._train_model(
                model, data, labels, task, epochs=5
            )

            # Save model
            model_path = output_path / "vit_model.pth"
            torch.save(model.state_dict(), model_path)

            # Save architecture info
            arch_info = {
                "architecture": "vision_transformer",
                "input_shape": input_shape,
                "patch_size": patch_size,
                "n_classes": n_classes,
                "hidden_dim": hidden_dim,
                "n_heads": n_heads,
                "n_layers": n_layers,
                "n_parameters": sum(p.numel() for p in model.parameters()),
                "device": str(self.device)
            }

            with open(output_path / "model_architecture.json", 'w') as f:
                json.dump(arch_info, f, indent=2)

            # Save training metrics
            with open(output_path / "training_metrics.json", 'w') as f:
                json.dump(metrics, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "model": str(model_path),
                        "architecture": str(output_path / "model_architecture.json"),
                        "metrics": str(output_path / "training_metrics.json")
                    },
                    "summary": {
                        **arch_info,
                        "final_loss": metrics["final_loss"],
                        "final_accuracy": metrics.get("final_accuracy", 0)
                    }
                }
            )

        except Exception as e:
            logger.error(f"Vision Transformer failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_vit_model(
        self,
        input_shape: Tuple[int, int, int],
        patch_size: int,
        n_classes: int,
        hidden_dim: int,
        n_heads: int,
        n_layers: int
    ) -> nn.Module:
        """Create Vision Transformer model."""

        class PatchEmbedding3D(nn.Module):
            """3D patch embedding for brain volumes."""

            def __init__(self, volume_size, patch_size, hidden_dim):
                super().__init__()
                self.volume_size = volume_size
                self.patch_size = patch_size
                self.n_patches = (volume_size[0] // patch_size) * \
                               (volume_size[1] // patch_size) * \
                               (volume_size[2] // patch_size)

                self.projection = nn.Conv3d(
                    1, hidden_dim,
                    kernel_size=patch_size,
                    stride=patch_size
                )

            def forward(self, x):
                x = self.projection(x)  # (B, hidden_dim, n_p_h, n_p_w, n_p_d)
                x = x.flatten(2)  # (B, hidden_dim, n_patches)
                x = x.transpose(1, 2)  # (B, n_patches, hidden_dim)
                return x

        class VisionTransformer3D(nn.Module):
            """3D Vision Transformer for neuroimaging."""

            def __init__(self, volume_size, patch_size, n_classes,
                        hidden_dim, n_heads, n_layers):
                super().__init__()

                self.patch_embed = PatchEmbedding3D(volume_size, patch_size, hidden_dim)

                # Position embedding
                n_patches = self.patch_embed.n_patches
                self.pos_embed = nn.Parameter(torch.randn(1, n_patches + 1, hidden_dim))
                self.cls_token = nn.Parameter(torch.randn(1, 1, hidden_dim))

                # Transformer encoder
                encoder_layer = nn.TransformerEncoderLayer(
                    hidden_dim, n_heads, dim_feedforward=hidden_dim * 4,
                    dropout=0.1, activation='gelu'
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, n_layers)

                # Classification head
                self.norm = nn.LayerNorm(hidden_dim)
                self.head = nn.Linear(hidden_dim, n_classes)

            def forward(self, x):
                B = x.shape[0]

                # Patch embedding
                x = self.patch_embed(x)

                # Add cls token
                cls_tokens = self.cls_token.expand(B, -1, -1)
                x = torch.cat([cls_tokens, x], dim=1)

                # Add position embedding
                x = x + self.pos_embed

                # Transformer
                x = x.transpose(0, 1)  # (seq_len, batch, hidden_dim)
                x = self.transformer(x)
                x = x.transpose(0, 1)  # (batch, seq_len, hidden_dim)

                # Classification
                cls_output = x[:, 0]
                cls_output = self.norm(cls_output)
                output = self.head(cls_output)

                return output

        return VisionTransformer3D(
            input_shape, patch_size, n_classes,
            hidden_dim, n_heads, n_layers
        ).to(self.device)

    def _generate_synthetic_data(
        self,
        n_samples: int,
        shape: Tuple[int, int, int],
        n_classes: int
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Generate synthetic brain imaging data."""
        # Create synthetic volumes
        data = torch.randn(n_samples, 1, *shape) * 0.1

        # Add class-specific patterns
        labels = torch.randint(0, n_classes, (n_samples,))

        for i in range(n_samples):
            label = labels[i].item()
            # Add pattern based on class
            if label == 0:
                data[i, 0, 20:40, 20:40, 20:40] += 0.5
            else:
                data[i, 0, 30:50, 30:50, 30:50] += 0.5

        return data.to(self.device), labels.to(self.device)

    def _train_model(
        self,
        model: nn.Module,
        data: torch.Tensor,
        labels: torch.Tensor,
        task: str,
        epochs: int
    ) -> Dict[str, Any]:
        """Train the model (simplified)."""
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)

        if task == "classification":
            criterion = nn.CrossEntropyLoss()
        else:
            criterion = nn.MSELoss()

        losses = []
        accuracies = []

        # Create simple data loader
        dataset = torch.utils.data.TensorDataset(data, labels)
        loader = DataLoader(dataset, batch_size=16, shuffle=True)

        for epoch in range(epochs):
            epoch_loss = 0
            correct = 0
            total = 0

            for batch_data, batch_labels in loader:
                optimizer.zero_grad()

                outputs = model(batch_data)
                loss = criterion(outputs, batch_labels)

                loss.backward()
                optimizer.step()

                epoch_loss += loss.item()

                if task == "classification":
                    _, predicted = outputs.max(1)
                    correct += predicted.eq(batch_labels).sum().item()
                    total += batch_labels.size(0)

            avg_loss = epoch_loss / len(loader)
            losses.append(avg_loss)

            if task == "classification":
                accuracy = correct / total
                accuracies.append(accuracy)

        return {
            "losses": losses,
            "accuracies": accuracies,
            "final_loss": losses[-1],
            "final_accuracy": accuracies[-1] if accuracies else 0
        }


class CNN3DTool(NeuroToolWrapper):
    """3D Convolutional Neural Network for neuroimaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "cnn_3d"

    def get_tool_description(self) -> str:
        return "3D CNN for volumetric brain image analysis"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        input_shape: Tuple[int, int, int] = (64, 64, 64),
        n_classes: int = 2,
        n_filters: List[int] = None,
        task: str = "classification",
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run 3D CNN model."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(
                    status="error",
                    error="PyTorch not available"
                )

            output_path = Path(output_dir or "cnn3d_output")
            output_path.mkdir(parents=True, exist_ok=True)

            if n_filters is None:
                n_filters = [32, 64, 128, 256]

            # Create 3D CNN model
            model = self._create_cnn3d_model(input_shape, n_classes, n_filters)

            # Generate synthetic data
            data, labels = self._generate_synthetic_data(
                n_samples=50, shape=input_shape, n_classes=n_classes
            )

            # Train model
            metrics = self._train_model(model, data, labels, epochs=3)

            # Save model
            model_path = output_path / "cnn3d_model.pth"
            torch.save(model.state_dict(), model_path)

            # Save info
            info = {
                "architecture": "cnn_3d",
                "input_shape": input_shape,
                "n_classes": n_classes,
                "n_filters": n_filters,
                "n_parameters": sum(p.numel() for p in model.parameters())
            }

            with open(output_path / "model_info.json", 'w') as f:
                json.dump(info, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "model": str(model_path),
                        "info": str(output_path / "model_info.json")
                    },
                    "summary": info
                }
            )

        except Exception as e:
            logger.error(f"3D CNN failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_cnn3d_model(
        self,
        input_shape: Tuple[int, int, int],
        n_classes: int,
        n_filters: List[int]
    ) -> nn.Module:
        """Create 3D CNN model."""

        class CNN3D(nn.Module):
            def __init__(self, input_shape, n_classes, n_filters):
                super().__init__()

                layers = []
                in_channels = 1

                for i, out_channels in enumerate(n_filters):
                    layers.extend([
                        nn.Conv3d(in_channels, out_channels, kernel_size=3, padding=1),
                        nn.BatchNorm3d(out_channels),
                        nn.ReLU(inplace=True),
                        nn.MaxPool3d(2)
                    ])
                    in_channels = out_channels

                self.features = nn.Sequential(*layers)

                # Calculate output size
                test_input = torch.zeros(1, 1, *input_shape)
                test_output = self.features(test_input)
                n_features = test_output.numel()

                self.classifier = nn.Sequential(
                    nn.Linear(n_features, 256),
                    nn.ReLU(inplace=True),
                    nn.Dropout(0.5),
                    nn.Linear(256, n_classes)
                )

            def forward(self, x):
                x = self.features(x)
                x = x.view(x.size(0), -1)
                x = self.classifier(x)
                return x

        return CNN3D(input_shape, n_classes, n_filters).to(self.device)

    def _generate_synthetic_data(
        self,
        n_samples: int,
        shape: Tuple[int, int, int],
        n_classes: int
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Generate synthetic data."""
        data = torch.randn(n_samples, 1, *shape) * 0.1
        labels = torch.randint(0, n_classes, (n_samples,))

        # Add patterns
        for i in range(n_samples):
            if labels[i] == 0:
                data[i, 0, 10:30, 10:30, 10:30] += 0.3
            else:
                data[i, 0, 35:55, 35:55, 35:55] += 0.3

        return data.to(self.device), labels.to(self.device)

    def _train_model(
        self,
        model: nn.Module,
        data: torch.Tensor,
        labels: torch.Tensor,
        epochs: int
    ) -> Dict[str, Any]:
        """Train the model."""
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.CrossEntropyLoss()

        losses = []

        for epoch in range(epochs):
            optimizer.zero_grad()
            outputs = model(data)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        return {"losses": losses, "final_loss": losses[-1]}


class GraphNeuralNetworkTool(NeuroToolWrapper):
    """Graph Neural Network for brain connectivity analysis."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "graph_neural_network"

    def get_tool_description(self) -> str:
        return "GNN for brain network analysis"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        n_nodes: int = 90,
        n_features: int = 100,
        n_classes: int = 2,
        hidden_dim: int = 128,
        n_layers: int = 3,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run Graph Neural Network."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(
                    status="error",
                    error="PyTorch not available"
                )

            output_path = Path(output_dir or "gnn_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create GNN model
            model = self._create_gnn_model(
                n_features, hidden_dim, n_classes, n_layers
            )

            # Generate synthetic graph data
            graphs, labels = self._generate_graph_data(
                n_samples=50, n_nodes=n_nodes, n_features=n_features, n_classes=n_classes
            )

            # Train model
            metrics = self._train_gnn(model, graphs, labels, epochs=10)

            # Save model
            model_path = output_path / "gnn_model.pth"
            torch.save(model.state_dict(), model_path)

            # Save info
            info = {
                "architecture": "graph_neural_network",
                "n_nodes": n_nodes,
                "n_features": n_features,
                "n_classes": n_classes,
                "hidden_dim": hidden_dim,
                "n_layers": n_layers,
                "n_parameters": sum(p.numel() for p in model.parameters())
            }

            with open(output_path / "gnn_info.json", 'w') as f:
                json.dump(info, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "model": str(model_path),
                        "info": str(output_path / "gnn_info.json")
                    },
                    "summary": {
                        **info,
                        "final_loss": metrics["final_loss"]
                    }
                }
            )

        except Exception as e:
            logger.error(f"GNN failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_gnn_model(
        self,
        n_features: int,
        hidden_dim: int,
        n_classes: int,
        n_layers: int
    ) -> nn.Module:
        """Create GNN model."""

        class GraphConvLayer(nn.Module):
            """Simple graph convolution layer."""

            def __init__(self, in_features, out_features):
                super().__init__()
                self.weight = nn.Parameter(torch.randn(in_features, out_features))
                self.bias = nn.Parameter(torch.zeros(out_features))

            def forward(self, x, adj):
                # x: (batch, n_nodes, features)
                # adj: (batch, n_nodes, n_nodes)
                support = torch.matmul(x, self.weight)
                output = torch.matmul(adj, support)
                return output + self.bias

        class GNN(nn.Module):
            def __init__(self, n_features, hidden_dim, n_classes, n_layers):
                super().__init__()

                self.layers = nn.ModuleList()

                # Input layer
                self.layers.append(GraphConvLayer(n_features, hidden_dim))

                # Hidden layers
                for _ in range(n_layers - 2):
                    self.layers.append(GraphConvLayer(hidden_dim, hidden_dim))

                # Output layer
                self.layers.append(GraphConvLayer(hidden_dim, n_classes))

                self.dropout = nn.Dropout(0.5)

            def forward(self, x, adj):
                for i, layer in enumerate(self.layers[:-1]):
                    x = layer(x, adj)
                    x = F.relu(x)
                    x = self.dropout(x)

                # Final layer
                x = self.layers[-1](x, adj)

                # Global pooling
                x = torch.mean(x, dim=1)  # Average over nodes

                return x

        return GNN(n_features, hidden_dim, n_classes, n_layers).to(self.device)

    def _generate_graph_data(
        self,
        n_samples: int,
        n_nodes: int,
        n_features: int,
        n_classes: int
    ) -> Tuple[List, torch.Tensor]:
        """Generate synthetic graph data."""
        graphs = []
        labels = torch.randint(0, n_classes, (n_samples,))

        for i in range(n_samples):
            # Node features
            x = torch.randn(n_nodes, n_features)

            # Adjacency matrix (random connectivity)
            adj = torch.rand(n_nodes, n_nodes) < 0.1
            adj = adj.float()
            adj = (adj + adj.t()) / 2  # Symmetrize

            # Add self-loops
            adj = adj + torch.eye(n_nodes)

            # Normalize
            deg = adj.sum(dim=1)
            deg_inv_sqrt = deg.pow(-0.5)
            deg_inv_sqrt[deg_inv_sqrt == float('inf')] = 0
            adj = deg_inv_sqrt.view(-1, 1) * adj * deg_inv_sqrt.view(1, -1)

            graphs.append((x.to(self.device), adj.to(self.device)))

        return graphs, labels.to(self.device)

    def _train_gnn(
        self,
        model: nn.Module,
        graphs: List,
        labels: torch.Tensor,
        epochs: int
    ) -> Dict[str, Any]:
        """Train GNN model."""
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.CrossEntropyLoss()

        losses = []

        for epoch in range(epochs):
            total_loss = 0

            for i, (x, adj) in enumerate(graphs):
                optimizer.zero_grad()

                # Add batch dimension
                x = x.unsqueeze(0)
                adj = adj.unsqueeze(0)
                label = labels[i:i+1]

                output = model(x, adj)
                loss = criterion(output, label)

                loss.backward()
                optimizer.step()

                total_loss += loss.item()

            avg_loss = total_loss / len(graphs)
            losses.append(avg_loss)

        return {"losses": losses, "final_loss": losses[-1]}


# Additional advanced models
class AutoencoderTool(NeuroToolWrapper):
    """Variational Autoencoder for neuroimaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "autoencoder"

    def get_tool_description(self) -> str:
        return "VAE for brain image reconstruction and generation"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        input_shape: Tuple[int, int, int] = (64, 64, 64),
        latent_dim: int = 128,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run Variational Autoencoder."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(status="error", error="PyTorch not available")

            output_path = Path(output_dir or "vae_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create VAE model
            model = self._create_vae(input_shape, latent_dim)

            # Train on synthetic data
            data = torch.randn(20, 1, *input_shape).to(self.device)
            losses = self._train_vae(model, data, epochs=5)

            # Save model
            torch.save(model.state_dict(), output_path / "vae_model.pth")

            return ToolResult(
                status="success",
                data={
                    "outputs": {"model": str(output_path / "vae_model.pth")},
                    "summary": {"latent_dim": latent_dim, "final_loss": losses[-1]}
                }
            )

        except Exception as e:
            logger.error(f"VAE failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_vae(self, input_shape: Tuple[int, int, int], latent_dim: int) -> nn.Module:
        """Create VAE model."""

        class VAE(nn.Module):
            def __init__(self, input_shape, latent_dim):
                super().__init__()

                # Encoder
                self.encoder = nn.Sequential(
                    nn.Conv3d(1, 32, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv3d(32, 64, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv3d(64, 128, 3, stride=2, padding=1),
                    nn.ReLU(),
                )

                # Calculate flattened size
                test_input = torch.zeros(1, 1, *input_shape)
                test_output = self.encoder(test_input)
                self.flatten_size = test_output.numel()

                self.fc_mu = nn.Linear(self.flatten_size, latent_dim)
                self.fc_logvar = nn.Linear(self.flatten_size, latent_dim)

                # Decoder
                self.fc_decode = nn.Linear(latent_dim, self.flatten_size)
                self.decoder = nn.Sequential(
                    nn.ConvTranspose3d(128, 64, 3, stride=2, padding=1, output_padding=1),
                    nn.ReLU(),
                    nn.ConvTranspose3d(64, 32, 3, stride=2, padding=1, output_padding=1),
                    nn.ReLU(),
                    nn.ConvTranspose3d(32, 1, 3, stride=2, padding=1, output_padding=1),
                    nn.Sigmoid()
                )

            def encode(self, x):
                x = self.encoder(x)
                x = x.view(x.size(0), -1)
                mu = self.fc_mu(x)
                logvar = self.fc_logvar(x)
                return mu, logvar

            def reparameterize(self, mu, logvar):
                std = torch.exp(0.5 * logvar)
                eps = torch.randn_like(std)
                return mu + eps * std

            def decode(self, z):
                x = self.fc_decode(z)
                x = x.view(x.size(0), 128, 8, 8, 8)  # Reshape for decoder
                x = self.decoder(x)
                return x

            def forward(self, x):
                mu, logvar = self.encode(x)
                z = self.reparameterize(mu, logvar)
                return self.decode(z), mu, logvar

        return VAE(input_shape, latent_dim).to(self.device)

    def _train_vae(self, model: nn.Module, data: torch.Tensor, epochs: int) -> List[float]:
        """Train VAE."""
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

        losses = []

        for epoch in range(epochs):
            optimizer.zero_grad()

            recon, mu, logvar = model(data)

            # Reconstruction loss
            recon_loss = F.mse_loss(recon, data, reduction='sum')

            # KL divergence
            kl_loss = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

            loss = recon_loss + kl_loss
            loss.backward()
            optimizer.step()

            losses.append(loss.item())

        return losses


class UNet3DTool(NeuroToolWrapper):
    """3D U-Net for brain segmentation."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "unet_3d"

    def get_tool_description(self) -> str:
        return "3D U-Net for volumetric segmentation"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        input_shape: Tuple[int, int, int] = (64, 64, 64),
        n_classes: int = 4,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run 3D U-Net."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(status="error", error="PyTorch not available")

            output_path = Path(output_dir or "unet3d_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create U-Net model
            model = self._create_unet3d(n_classes)

            # Save model architecture
            torch.save(model.state_dict(), output_path / "unet3d_model.pth")

            return ToolResult(
                status="success",
                data={
                    "outputs": {"model": str(output_path / "unet3d_model.pth")},
                    "summary": {
                        "architecture": "unet_3d",
                        "n_classes": n_classes,
                        "n_parameters": sum(p.numel() for p in model.parameters())
                    }
                }
            )

        except Exception as e:
            logger.error(f"U-Net 3D failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_unet3d(self, n_classes: int) -> nn.Module:
        """Create 3D U-Net model."""

        class DoubleConv(nn.Module):
            def __init__(self, in_channels, out_channels):
                super().__init__()
                self.double_conv = nn.Sequential(
                    nn.Conv3d(in_channels, out_channels, kernel_size=3, padding=1),
                    nn.BatchNorm3d(out_channels),
                    nn.ReLU(inplace=True),
                    nn.Conv3d(out_channels, out_channels, kernel_size=3, padding=1),
                    nn.BatchNorm3d(out_channels),
                    nn.ReLU(inplace=True)
                )

            def forward(self, x):
                return self.double_conv(x)

        class UNet3D(nn.Module):
            def __init__(self, n_classes):
                super().__init__()

                # Encoder
                self.enc1 = DoubleConv(1, 64)
                self.enc2 = DoubleConv(64, 128)
                self.enc3 = DoubleConv(128, 256)
                self.enc4 = DoubleConv(256, 512)

                self.pool = nn.MaxPool3d(2)

                # Bottleneck
                self.bottleneck = DoubleConv(512, 1024)

                # Decoder
                self.upconv4 = nn.ConvTranspose3d(1024, 512, kernel_size=2, stride=2)
                self.dec4 = DoubleConv(1024, 512)

                self.upconv3 = nn.ConvTranspose3d(512, 256, kernel_size=2, stride=2)
                self.dec3 = DoubleConv(512, 256)

                self.upconv2 = nn.ConvTranspose3d(256, 128, kernel_size=2, stride=2)
                self.dec2 = DoubleConv(256, 128)

                self.upconv1 = nn.ConvTranspose3d(128, 64, kernel_size=2, stride=2)
                self.dec1 = DoubleConv(128, 64)

                # Output
                self.out = nn.Conv3d(64, n_classes, kernel_size=1)

            def forward(self, x):
                # Encoder
                enc1 = self.enc1(x)
                enc2 = self.enc2(self.pool(enc1))
                enc3 = self.enc3(self.pool(enc2))
                enc4 = self.enc4(self.pool(enc3))

                # Bottleneck
                bottleneck = self.bottleneck(self.pool(enc4))

                # Decoder
                dec4 = self.upconv4(bottleneck)
                dec4 = torch.cat([dec4, enc4], dim=1)
                dec4 = self.dec4(dec4)

                dec3 = self.upconv3(dec4)
                dec3 = torch.cat([dec3, enc3], dim=1)
                dec3 = self.dec3(dec3)

                dec2 = self.upconv2(dec3)
                dec2 = torch.cat([dec2, enc2], dim=1)
                dec2 = self.dec2(dec2)

                dec1 = self.upconv1(dec2)
                dec1 = torch.cat([dec1, enc1], dim=1)
                dec1 = self.dec1(dec1)

                return self.out(dec1)

        return UNet3D(n_classes).to(self.device)


class ResNet3DTool(NeuroToolWrapper):
    """3D ResNet for neuroimaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "resnet_3d"

    def get_tool_description(self) -> str:
        return "3D ResNet for brain image classification"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        depth: int = 50,
        n_classes: int = 2,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run 3D ResNet."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(status="error", error="PyTorch not available")

            output_path = Path(output_dir or "resnet3d_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create ResNet model
            model = self._create_resnet3d(depth, n_classes)

            # Save model
            torch.save(model.state_dict(), output_path / "resnet3d_model.pth")

            return ToolResult(
                status="success",
                data={
                    "outputs": {"model": str(output_path / "resnet3d_model.pth")},
                    "summary": {
                        "architecture": f"resnet3d_{depth}",
                        "n_classes": n_classes,
                        "n_parameters": sum(p.numel() for p in model.parameters())
                    }
                }
            )

        except Exception as e:
            logger.error(f"ResNet3D failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_resnet3d(self, depth: int, n_classes: int) -> nn.Module:
        """Create 3D ResNet model."""

        class ResidualBlock(nn.Module):
            def __init__(self, in_channels, out_channels, stride=1):
                super().__init__()

                self.conv1 = nn.Conv3d(in_channels, out_channels, 3, stride, padding=1)
                self.bn1 = nn.BatchNorm3d(out_channels)
                self.conv2 = nn.Conv3d(out_channels, out_channels, 3, padding=1)
                self.bn2 = nn.BatchNorm3d(out_channels)

                self.shortcut = nn.Sequential()
                if stride != 1 or in_channels != out_channels:
                    self.shortcut = nn.Sequential(
                        nn.Conv3d(in_channels, out_channels, 1, stride),
                        nn.BatchNorm3d(out_channels)
                    )

            def forward(self, x):
                out = F.relu(self.bn1(self.conv1(x)))
                out = self.bn2(self.conv2(out))
                out += self.shortcut(x)
                out = F.relu(out)
                return out

        class ResNet3D(nn.Module):
            def __init__(self, depth, n_classes):
                super().__init__()

                # Initial convolution
                self.conv1 = nn.Conv3d(1, 64, kernel_size=7, stride=2, padding=3)
                self.bn1 = nn.BatchNorm3d(64)
                self.pool = nn.MaxPool3d(3, stride=2, padding=1)

                # Residual layers
                if depth == 18:
                    layers = [2, 2, 2, 2]
                elif depth == 34:
                    layers = [3, 4, 6, 3]
                elif depth == 50:
                    layers = [3, 4, 6, 3]
                else:
                    layers = [3, 4, 23, 3]  # ResNet-101

                self.layer1 = self._make_layer(64, 64, layers[0])
                self.layer2 = self._make_layer(64, 128, layers[1], stride=2)
                self.layer3 = self._make_layer(128, 256, layers[2], stride=2)
                self.layer4 = self._make_layer(256, 512, layers[3], stride=2)

                # Classification head
                self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))
                self.fc = nn.Linear(512, n_classes)

            def _make_layer(self, in_channels, out_channels, blocks, stride=1):
                layers = []
                layers.append(ResidualBlock(in_channels, out_channels, stride))
                for _ in range(1, blocks):
                    layers.append(ResidualBlock(out_channels, out_channels))
                return nn.Sequential(*layers)

            def forward(self, x):
                x = F.relu(self.bn1(self.conv1(x)))
                x = self.pool(x)

                x = self.layer1(x)
                x = self.layer2(x)
                x = self.layer3(x)
                x = self.layer4(x)

                x = self.avgpool(x)
                x = x.view(x.size(0), -1)
                x = self.fc(x)

                return x

        return ResNet3D(depth, n_classes).to(self.device)


class DenseNet3DTool(NeuroToolWrapper):
    """3D DenseNet for neuroimaging."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "densenet_3d"

    def get_tool_description(self) -> str:
        return "3D DenseNet for brain image analysis"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        growth_rate: int = 32,
        n_classes: int = 2,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run 3D DenseNet."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(status="error", error="PyTorch not available")

            output_path = Path(output_dir or "densenet3d_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create DenseNet model
            model = self._create_densenet3d(growth_rate, n_classes)

            # Save model
            torch.save(model.state_dict(), output_path / "densenet3d_model.pth")

            return ToolResult(
                status="success",
                data={
                    "outputs": {"model": str(output_path / "densenet3d_model.pth")},
                    "summary": {
                        "architecture": "densenet_3d",
                        "growth_rate": growth_rate,
                        "n_classes": n_classes
                    }
                }
            )

        except Exception as e:
            logger.error(f"DenseNet3D failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_densenet3d(self, growth_rate: int, n_classes: int) -> nn.Module:
        """Create 3D DenseNet model."""

        class DenseLayer(nn.Module):
            def __init__(self, in_channels, growth_rate):
                super().__init__()
                self.bn1 = nn.BatchNorm3d(in_channels)
                self.conv1 = nn.Conv3d(in_channels, 4 * growth_rate, 1)
                self.bn2 = nn.BatchNorm3d(4 * growth_rate)
                self.conv2 = nn.Conv3d(4 * growth_rate, growth_rate, 3, padding=1)

            def forward(self, x):
                out = self.conv1(F.relu(self.bn1(x)))
                out = self.conv2(F.relu(self.bn2(out)))
                return torch.cat([x, out], 1)

        class DenseBlock(nn.Module):
            def __init__(self, in_channels, growth_rate, n_layers):
                super().__init__()
                self.layers = nn.ModuleList()
                for i in range(n_layers):
                    self.layers.append(
                        DenseLayer(in_channels + i * growth_rate, growth_rate)
                    )

            def forward(self, x):
                for layer in self.layers:
                    x = layer(x)
                return x

        class DenseNet3D(nn.Module):
            def __init__(self, growth_rate, n_classes):
                super().__init__()

                # Initial convolution
                self.conv1 = nn.Conv3d(1, 64, 7, stride=2, padding=3)
                self.bn1 = nn.BatchNorm3d(64)
                self.pool1 = nn.MaxPool3d(3, stride=2, padding=1)

                # Dense blocks
                n_channels = 64
                self.dense1 = DenseBlock(n_channels, growth_rate, 6)
                n_channels += 6 * growth_rate

                self.trans1 = nn.Sequential(
                    nn.BatchNorm3d(n_channels),
                    nn.Conv3d(n_channels, n_channels // 2, 1),
                    nn.AvgPool3d(2)
                )
                n_channels = n_channels // 2

                self.dense2 = DenseBlock(n_channels, growth_rate, 12)
                n_channels += 12 * growth_rate

                # Classification
                self.bn2 = nn.BatchNorm3d(n_channels)
                self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))
                self.fc = nn.Linear(n_channels, n_classes)

            def forward(self, x):
                x = self.pool1(F.relu(self.bn1(self.conv1(x))))

                x = self.dense1(x)
                x = self.trans1(x)
                x = self.dense2(x)

                x = F.relu(self.bn2(x))
                x = self.avgpool(x)
                x = x.view(x.size(0), -1)
                x = self.fc(x)

                return x

        return DenseNet3D(growth_rate, n_classes).to(self.device)


class TransformerEncoderTool(NeuroToolWrapper):
    """Transformer encoder for sequence modeling of brain data."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "transformer_encoder"

    def get_tool_description(self) -> str:
        return "Transformer for brain signal analysis"

    def get_args_schema(self):
        return DLInput

    def _run(
        self,
        seq_length: int = 100,
        n_features: int = 90,
        n_classes: int = 2,
        n_heads: int = 8,
        n_layers: int = 6,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Run Transformer encoder."""
        try:
            if not TORCH_AVAILABLE:
                return ToolResult(status="error", error="PyTorch not available")

            output_path = Path(output_dir or "transformer_output")
            output_path.mkdir(parents=True, exist_ok=True)

            # Create Transformer model
            model = self._create_transformer(
                n_features, n_classes, n_heads, n_layers
            )

            # Save model
            torch.save(model.state_dict(), output_path / "transformer_model.pth")

            return ToolResult(
                status="success",
                data={
                    "outputs": {"model": str(output_path / "transformer_model.pth")},
                    "summary": {
                        "architecture": "transformer_encoder",
                        "seq_length": seq_length,
                        "n_features": n_features,
                        "n_heads": n_heads,
                        "n_layers": n_layers
                    }
                }
            )

        except Exception as e:
            logger.error(f"Transformer failed: {e}")
            return ToolResult(status="error", error=str(e))

    def _create_transformer(
        self,
        n_features: int,
        n_classes: int,
        n_heads: int,
        n_layers: int
    ) -> nn.Module:
        """Create Transformer model."""

        class TransformerClassifier(nn.Module):
            def __init__(self, n_features, n_classes, n_heads, n_layers):
                super().__init__()

                self.pos_encoder = nn.Parameter(torch.randn(1, 1000, n_features))

                encoder_layer = nn.TransformerEncoderLayer(
                    n_features, n_heads,
                    dim_feedforward=n_features * 4,
                    dropout=0.1
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, n_layers)

                self.classifier = nn.Linear(n_features, n_classes)

            def forward(self, x):
                # Add positional encoding
                seq_len = x.size(1)
                x = x + self.pos_encoder[:, :seq_len, :]

                # Transformer expects (seq_len, batch, features)
                x = x.transpose(0, 1)
                x = self.transformer(x)
                x = x.transpose(0, 1)

                # Global pooling
                x = x.mean(dim=1)

                # Classification
                x = self.classifier(x)

                return x

        return TransformerClassifier(n_features, n_classes, n_heads, n_layers).to(self.device)


def get_all_advanced_dl_tools():
    """Get all advanced deep learning tools."""
    tools = AdvancedDeepLearningTools()
    return tools.get_all_tools()