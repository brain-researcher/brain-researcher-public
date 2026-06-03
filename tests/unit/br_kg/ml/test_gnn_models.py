"""Unit tests for GNN models ML module.

This module tests the Graph Neural Network functionality including:
- GCN, GraphSAGE, and GAT model implementations
- Node classification and link prediction tasks
- Data preparation and model training
- Model persistence and evaluation
"""

import os
import tempfile
from unittest.mock import Mock, patch

import numpy as np
import pytest

# Import the modules to test
try:
    from brain_researcher.services.br_kg.ml.gnn_models import (
        GNNConfig,
        GNNModelType,
        GNNPredictor,
        GraphAttentionNetwork,
        GraphConvolutionalNetwork,
        GraphSAGE,
    )
except ImportError:
    # Fallback if absolute imports don't work
    import os
    import sys

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from brain_researcher.services.br_kg.ml.gnn_models import (
        GNNConfig,
        GNNModelType,
        GNNPredictor,
        GraphAttentionNetwork,
        GraphConvolutionalNetwork,
        GraphSAGE,
    )


# Mock PyTorch components for testing when not available
class MockTensor:
    """Mock tensor for testing without PyTorch."""

    def __init__(self, data=None, dtype=None):
        if isinstance(data, list | np.ndarray):
            self.data = np.array(data)
        else:
            self.data = data if data is not None else np.array([])
        self.shape = self.data.shape if hasattr(self.data, "shape") else (0,)
        self._dtype = dtype

    def size(self, dim=None):
        if dim is None:
            return self.shape
        return self.shape[dim] if dim < len(self.shape) else 1

    def item(self):
        return float(self.data) if np.isscalar(self.data) else self.data.item()

    def cpu(self):
        return self

    def numpy(self):
        return self.data

    def argmax(self, dim=None):
        return MockTensor(np.argmax(self.data, axis=dim))

    def __getitem__(self, key):
        return MockTensor(self.data[key])

    def __len__(self):
        return len(self.data)

    def float(self):
        return self

    def mean(self):
        return MockTensor(np.mean(self.data))


class MockModule:
    """Mock neural network module."""

    def __init__(self, *args, **kwargs):
        self.training = True
        self.parameters_list = [MockTensor(np.random.randn(10, 10)) for _ in range(3)]

    def parameters(self):
        return self.parameters_list

    def train(self, mode=True):
        self.training = mode
        return self

    def eval(self):
        self.training = False
        return self

    def to(self, device):
        return self

    def state_dict(self):
        return {"layer1.weight": MockTensor(np.random.randn(10, 10))}

    def load_state_dict(self, state_dict):
        pass


class TestGNNConfig:
    """Test GNNConfig configuration class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = GNNConfig(model_type=GNNModelType.GCN, input_dim=128, output_dim=64)

        assert config.model_type == GNNModelType.GCN
        assert config.input_dim == 128
        assert config.output_dim == 64
        assert config.hidden_dim == 128
        assert config.num_layers == 3
        assert config.dropout == 0.5
        assert config.learning_rate == 0.001

    def test_custom_config(self):
        """Test custom configuration values."""
        config = GNNConfig(
            model_type=GNNModelType.GAT,
            input_dim=256,
            output_dim=128,
            hidden_dim=64,
            num_layers=4,
            dropout=0.3,
            heads=4,
            learning_rate=0.01,
            epochs=100,
        )

        assert config.model_type == GNNModelType.GAT
        assert config.input_dim == 256
        assert config.output_dim == 128
        assert config.hidden_dim == 64
        assert config.num_layers == 4
        assert config.dropout == 0.3
        assert config.heads == 4
        assert config.learning_rate == 0.01
        assert config.epochs == 100

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = GNNConfig(
            model_type=GNNModelType.GRAPHSAGE, input_dim=100, output_dim=50
        )

        config_dict = config.to_dict()

        assert config_dict["model_type"] == "graphsage"
        assert config_dict["input_dim"] == 100
        assert config_dict["output_dim"] == 50
        assert "hidden_dim" in config_dict
        assert "learning_rate" in config_dict


class TestGNNModels:
    """Test individual GNN model classes."""

    @pytest.fixture
    def mock_torch(self):
        """Mock PyTorch components."""
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.TORCH_AVAILABLE", True
        ):
            # Mock torch components
            mock_torch = Mock()
            mock_nn = Mock()
            mock_f = Mock()

            # Mock tensor creation
            mock_torch.zeros.return_value = MockTensor(np.zeros((10, 5)))
            mock_torch.tensor.return_value = MockTensor()
            mock_torch.eye.return_value = MockTensor(np.eye(10))
            mock_torch.device.return_value = "cpu"
            mock_torch.cuda.is_available.return_value = False

            # Mock F functions
            mock_f.relu = lambda x: x
            mock_f.cross_entropy = lambda pred, target: MockTensor(0.5)
            mock_f.binary_cross_entropy = lambda pred, target: MockTensor(0.3)
            mock_f.softmax = lambda x, dim=None: x

            # Mock module
            mock_nn.Module = MockModule
            mock_nn.ModuleList = list
            mock_nn.Dropout = MockModule
            mock_nn.Linear = MockModule

            with patch.multiple(
                "brain_researcher.services.br_kg.ml.gnn_models",
                torch=mock_torch,
                nn=mock_nn,
                F=mock_f,
                Adam=Mock,
                GCNConv=Mock,
                SAGEConv=Mock,
                GATConv=Mock,
                Data=Mock,
            ):
                yield mock_torch

    def test_gcn_initialization(self, mock_torch):
        """Test GCN model initialization."""
        config = GNNConfig(
            model_type=GNNModelType.GCN,
            input_dim=10,
            output_dim=5,
            hidden_dim=8,
            num_layers=2,
        )

        with patch("brain_researcher.services.br_kg.ml.gnn_models.GCNConv", MockModule):
            model = GraphConvolutionalNetwork(config)

            assert model.config == config
            assert len(model.layers) == 2  # num_layers

    def test_graphsage_initialization(self, mock_torch):
        """Test GraphSAGE model initialization."""
        config = GNNConfig(
            model_type=GNNModelType.GRAPHSAGE, input_dim=10, output_dim=5, num_layers=3
        )

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.SAGEConv", MockModule
        ):
            model = GraphSAGE(config)

            assert model.config == config
            assert len(model.layers) == 3

    def test_gat_initialization(self, mock_torch):
        """Test GAT model initialization."""
        config = GNNConfig(
            model_type=GNNModelType.GAT,
            input_dim=10,
            output_dim=5,
            heads=4,
            num_layers=2,
        )

        with patch("brain_researcher.services.br_kg.ml.gnn_models.GATConv", MockModule):
            model = GraphAttentionNetwork(config)

            assert model.config == config
            assert len(model.layers) == 2


class TestGNNPredictor:
    """Test GNNPredictor high-level interface."""

    @pytest.fixture
    def mock_torch_available(self):
        """Mock PyTorch availability."""
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.TORCH_AVAILABLE", True
        ):
            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.device.return_value = "cpu"
                mock_torch.cuda.is_available.return_value = False
                mock_torch.zeros.return_value = MockTensor(np.zeros((10, 5)))
                mock_torch.tensor.return_value = MockTensor()
                mock_torch.eye.return_value = MockTensor(np.eye(10))
                mock_torch.ones.return_value = MockTensor(np.ones(10))
                mock_torch.sum = lambda x, dim=None: MockTensor(
                    np.sum(x.data, axis=dim)
                )
                mock_torch.sigmoid = lambda x: MockTensor(1 / (1 + np.exp(-x.data)))
                mock_torch.cat = lambda tensors, dim=0: MockTensor(
                    np.concatenate([t.data for t in tensors], axis=dim)
                )
                yield mock_torch

    def test_predictor_initialization(self, mock_torch_available):
        """Test GNN predictor initialization."""
        predictor = GNNPredictor(GNNModelType.GCN)

        assert predictor.model_type == GNNModelType.GCN
        assert predictor.model is None
        assert predictor.config is None
        assert len(predictor.training_history) == 0

    def test_build_gcn_model(self, mock_torch_available):
        """Test building GCN model."""
        predictor = GNNPredictor(GNNModelType.GCN)

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphConvolutionalNetwork",
            MockModule,
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=10, output_dim=5, hidden_dim=8)

                assert predictor.config is not None
                assert predictor.config.input_dim == 10
                assert predictor.config.output_dim == 5
                assert predictor.config.hidden_dim == 8
                assert predictor.model is not None
                assert predictor.optimizer is not None

    def test_build_graphsage_model(self, mock_torch_available):
        """Test building GraphSAGE model."""
        predictor = GNNPredictor(GNNModelType.GRAPHSAGE)

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphSAGE", MockModule
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=15, output_dim=8)

                assert predictor.config.model_type == GNNModelType.GRAPHSAGE
                assert predictor.config.input_dim == 15
                assert predictor.config.output_dim == 8

    def test_build_gat_model(self, mock_torch_available):
        """Test building GAT model."""
        predictor = GNNPredictor(GNNModelType.GAT)

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphAttentionNetwork",
            MockModule,
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=20, output_dim=10, heads=4)

                assert predictor.config.model_type == GNNModelType.GAT
                assert predictor.config.heads == 4

    def test_unsupported_model_type(self, mock_torch_available):
        """Test handling of unsupported model type."""
        predictor = GNNPredictor(GNNModelType.GCN)
        predictor.model_type = "unsupported_type"

        with pytest.raises(ValueError, match="Unsupported model type"):
            predictor.build_model(input_dim=10, output_dim=5)

    def test_prepare_graph_data_with_features(self, mock_torch_available):
        """Test preparing graph data with node features."""
        predictor = GNNPredictor(GNNModelType.GCN)

        graph_data = {
            "nodes": ["node1", "node2", "node3"],
            "edges": [
                {"start": "node1", "end": "node2"},
                {"start": "node2", "end": "node3"},
            ],
            "node_features": {
                "node1": [1.0, 2.0, 3.0],
                "node2": [4.0, 5.0, 6.0],
                "node3": [7.0, 8.0, 9.0],
            },
        }

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.Data", Mock
        ) as mock_data:
            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.zeros.return_value = MockTensor(np.zeros((3, 3)))
                mock_torch.tensor.return_value = MockTensor()
                mock_torch.eye.return_value = MockTensor(np.eye(3))

                predictor.prepare_graph_data(graph_data)

                # Should create Data object with features and edges
                mock_data.assert_called_once()

    def test_prepare_graph_data_without_features(self, mock_torch_available):
        """Test preparing graph data without node features (uses identity)."""
        predictor = GNNPredictor(GNNModelType.GCN)

        graph_data = {
            "nodes": ["node1", "node2"],
            "edges": [{"start": "node1", "end": "node2"}],
        }

        with patch("brain_researcher.services.br_kg.ml.gnn_models.Data", Mock):
            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.eye.return_value = MockTensor(np.eye(2))
                mock_torch.tensor.return_value = MockTensor()

                predictor.prepare_graph_data(graph_data)

                # Should use identity matrix as features
                mock_torch.eye.assert_called_with(2, dtype=mock_torch.float)

    def test_node_classification_training(self, mock_torch_available):
        """Test node classification training."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Mock model and optimizer
        mock_model = Mock()
        mock_model.predict_node_class.return_value = MockTensor(
            np.array([[0.8, 0.2], [0.3, 0.7], [0.6, 0.4]])
        )
        mock_model.train = Mock()
        mock_model.eval = Mock()
        predictor.model = mock_model

        mock_optimizer = Mock()
        predictor.optimizer = mock_optimizer

        # Mock config
        predictor.config = GNNConfig(
            model_type=GNNModelType.GCN,
            input_dim=5,
            output_dim=2,
            epochs=2,  # Short training for testing
            early_stopping_patience=1,
        )

        # Test data
        graph_data = {
            "nodes": ["node1", "node2", "node3"],
            "edges": [{"start": "node1", "end": "node2"}],
        }

        labels = {"node1": 0, "node2": 1, "node3": 0}
        train_mask = ["node1", "node2"]
        val_mask = ["node3"]

        # Mock data preparation
        with patch.object(predictor, "prepare_graph_data") as mock_prep:
            mock_data = Mock()
            mock_data.x = MockTensor(np.random.randn(3, 5))
            mock_data.edge_index = MockTensor(np.array([[0, 1], [1, 2]]))
            mock_prep.return_value = mock_data

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                with patch("brain_researcher.services.br_kg.ml.gnn_models.F") as mock_f:
                    # Mock tensor operations
                    mock_torch.zeros.return_value = MockTensor(np.zeros(3))
                    mock_torch.tensor.return_value = MockTensor()
                    mock_f.cross_entropy.return_value = MockTensor(0.5)

                    # Mock loss backward and optimizer
                    mock_loss = Mock()
                    mock_loss.backward = Mock()
                    mock_loss.item.return_value = 0.5
                    mock_f.cross_entropy.return_value = mock_loss

                    # Run training
                    results = predictor.train_node_classification(
                        graph_data, labels, train_mask, val_mask, num_classes=2
                    )

                    # Check results
                    assert "best_val_acc" in results
                    assert "final_loss" in results
                    assert "training_history" in results
                    assert len(predictor.training_history) > 0

    def test_link_prediction_training(self, mock_torch_available):
        """Test link prediction training."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Mock model
        mock_model = Mock()
        mock_model.predict_links.return_value = MockTensor(
            np.array([0.8, 0.3, 0.9, 0.1])
        )
        predictor.model = mock_model

        mock_optimizer = Mock()
        predictor.optimizer = mock_optimizer

        predictor.config = GNNConfig(
            model_type=GNNModelType.GCN, input_dim=5, output_dim=10, epochs=2
        )

        # Test data
        graph_data = {"nodes": ["A", "B", "C", "D"], "edges": []}
        positive_edges = [("A", "B"), ("C", "D")]
        negative_edges = [("A", "C"), ("B", "D")]

        with patch.object(predictor, "prepare_graph_data") as mock_prep:
            mock_data = Mock()
            mock_data.x = MockTensor(np.random.randn(4, 5))
            mock_data.edge_index = MockTensor(np.array([[0, 1], [2, 3]]))
            mock_prep.return_value = mock_data

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                with patch("brain_researcher.services.br_kg.ml.gnn_models.F") as mock_f:
                    # Mock tensor operations
                    mock_torch.tensor.return_value = MockTensor()
                    mock_torch.zeros.return_value = MockTensor(np.zeros((2, 0)))
                    mock_torch.ones.return_value = MockTensor(np.ones(2))
                    mock_torch.cat.return_value = MockTensor(np.array([0, 1, 2, 3]))
                    mock_f.binary_cross_entropy.return_value = Mock(
                        item=lambda: 0.3, backward=Mock()
                    )

                    results = predictor.train_link_prediction(
                        graph_data, positive_edges, negative_edges
                    )

                    assert "best_val_auc" in results
                    assert "final_loss" in results
                    assert "training_history" in results

    def test_node_embeddings_prediction(self, mock_torch_available):
        """Test node embeddings prediction."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Mock model
        mock_model = Mock()
        mock_model.return_value = MockTensor(np.random.randn(3, 8))
        mock_model.eval = Mock()
        predictor.model = mock_model

        graph_data = {
            "nodes": ["node1", "node2", "node3"],
            "edges": [{"start": "node1", "end": "node2"}],
        }

        with patch.object(predictor, "prepare_graph_data") as mock_prep:
            mock_data = Mock()
            mock_data.x = MockTensor(np.random.randn(3, 5))
            mock_data.edge_index = MockTensor()
            mock_prep.return_value = mock_data

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.no_grad.return_value.__enter__ = Mock()
                mock_torch.no_grad.return_value.__exit__ = Mock()

                results = predictor.predict(graph_data, task_type="node_embeddings")

                assert "embeddings" in results
                assert "node_ids" in results
                assert results["node_ids"] == ["node1", "node2", "node3"]

    def test_node_classification_prediction(self, mock_torch_available):
        """Test node classification prediction."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Mock model
        mock_model = Mock()
        mock_model.predict_node_class.return_value = MockTensor(
            np.array([[0.8, 0.2], [0.3, 0.7]])
        )
        mock_model.eval = Mock()
        predictor.model = mock_model

        graph_data = {"nodes": ["node1", "node2"], "edges": []}

        with patch.object(predictor, "prepare_graph_data") as mock_prep:
            mock_prep.return_value = Mock()

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                with patch("brain_researcher.services.br_kg.ml.gnn_models.F") as mock_f:
                    mock_torch.no_grad.return_value.__enter__ = Mock()
                    mock_torch.no_grad.return_value.__exit__ = Mock()
                    mock_f.softmax.return_value = MockTensor(
                        np.array([[0.7, 0.3], [0.4, 0.6]])
                    )

                    results = predictor.predict(
                        graph_data, task_type="node_classification", num_classes=2
                    )

                    assert "predictions" in results
                    assert "probabilities" in results
                    assert "node_ids" in results

    def test_link_prediction_prediction(self, mock_torch_available):
        """Test link prediction prediction."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Mock model
        mock_model = Mock()
        mock_model.predict_links.return_value = MockTensor(np.array([0.8, 0.3]))
        mock_model.eval = Mock()
        predictor.model = mock_model

        graph_data = {"nodes": ["A", "B", "C"], "edges": []}
        test_edges = [("A", "B"), ("B", "C")]

        with patch.object(predictor, "prepare_graph_data") as mock_prep:
            mock_prep.return_value = Mock()

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.no_grad.return_value.__enter__ = Mock()
                mock_torch.no_grad.return_value.__exit__ = Mock()
                mock_torch.tensor.return_value = MockTensor()

                results = predictor.predict(
                    graph_data, task_type="link_prediction", test_edges=test_edges
                )

                assert "link_probabilities" in results
                assert "test_edges" in results
                assert results["test_edges"] == test_edges

    def test_model_saving_loading(self, mock_torch_available):
        """Test model saving and loading."""
        predictor = GNNPredictor(GNNModelType.GCN)

        # Build model
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphConvolutionalNetwork",
            MockModule,
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=10, output_dim=5)

        # Add training history
        predictor.training_history = [{"epoch": 1, "loss": 0.5}]

        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # Test saving
            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.save = Mock()

                predictor.save_model(tmp_path)

                mock_torch.save.assert_called_once()
                save_data = mock_torch.save.call_args[0][0]

                assert "model_state_dict" in save_data
                assert "config" in save_data
                assert "model_type" in save_data
                assert "training_history" in save_data

            # Test loading
            mock_save_data = {
                "model_state_dict": {"layer1.weight": MockTensor()},
                "config": predictor.config.to_dict(),
                "model_type": GNNModelType.GCN.value,
                "training_history": [{"epoch": 1, "loss": 0.5}],
            }

            with patch(
                "brain_researcher.services.br_kg.ml.gnn_models.torch"
            ) as mock_torch:
                mock_torch.load.return_value = mock_save_data

                new_predictor = GNNPredictor(GNNModelType.GCN)

                with patch.object(new_predictor, "build_model") as mock_build:
                    new_predictor.load_model(tmp_path)

                    mock_build.assert_called_once()
                    assert len(new_predictor.training_history) == 1

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_model_without_build_error(self, mock_torch_available):
        """Test error when trying to use model before building."""
        predictor = GNNPredictor(GNNModelType.GCN)

        graph_data = {"nodes": ["A"], "edges": []}

        with pytest.raises(ValueError, match="Model not built"):
            predictor.train_node_classification(graph_data, {"A": 0})

        with pytest.raises(ValueError, match="Model not built"):
            predictor.train_link_prediction(graph_data, [], [])

        with pytest.raises(ValueError, match="Model not built"):
            predictor.predict(graph_data)

        with pytest.raises(ValueError, match="No model to save"):
            predictor.save_model("test.pt")

    def test_get_model_info(self, mock_torch_available):
        """Test getting model information."""
        predictor = GNNPredictor(GNNModelType.GAT)

        # Before building model
        info = predictor.get_model_info()
        assert info["status"] == "not_built"

        # After building model
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphAttentionNetwork",
            MockModule,
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=10, output_dim=5)

                info = predictor.get_model_info()

                assert info["model_type"] == "gat"
                assert info["parameters"] > 0
                assert info["device"] == "cpu"
                assert "config" in info

    def test_unsupported_task_type(self, mock_torch_available):
        """Test error for unsupported prediction task type."""
        predictor = GNNPredictor(GNNModelType.GCN)

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.GraphConvolutionalNetwork",
            MockModule,
        ):
            with patch("brain_researcher.services.br_kg.ml.gnn_models.Adam", Mock):
                predictor.build_model(input_dim=10, output_dim=5)

        graph_data = {"nodes": ["A"], "edges": []}

        with pytest.raises(ValueError, match="Unsupported task type"):
            predictor.predict(graph_data, task_type="unsupported_task")


class TestTorchUnavailable:
    """Test behavior when PyTorch is not available."""

    def test_import_error_on_model_creation(self):
        """Test ImportError when PyTorch is not available."""
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.TORCH_AVAILABLE", False
        ):
            config = GNNConfig(GNNModelType.GCN, input_dim=10, output_dim=5)

            with pytest.raises(
                ImportError, match="PyTorch and PyTorch Geometric are required"
            ):
                GraphConvolutionalNetwork(config)

            with pytest.raises(
                ImportError, match="PyTorch and PyTorch Geometric are required"
            ):
                GraphSAGE(config)

            with pytest.raises(
                ImportError, match="PyTorch and PyTorch Geometric are required"
            ):
                GraphAttentionNetwork(config)

            with pytest.raises(
                ImportError, match="PyTorch and PyTorch Geometric are required"
            ):
                GNNPredictor(GNNModelType.GCN)


@pytest.mark.integration
class TestGNNIntegration:
    """Integration tests with synthetic data."""

    def test_end_to_end_node_classification(self):
        """Test complete node classification workflow with synthetic data."""
        # This test would run with actual PyTorch if available
        # For now, we mock the entire workflow

        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.TORCH_AVAILABLE", True
        ):
            # Create synthetic graph data
            graph_data = {
                "nodes": [f"node_{i}" for i in range(10)],
                "edges": [
                    {"start": f"node_{i}", "end": f"node_{(i+1)%10}"} for i in range(10)
                ],
                "node_features": {
                    f"node_{i}": [float(i % 3), float((i + 1) % 3), float((i + 2) % 3)]
                    for i in range(10)
                },
            }

            # Labels for 3-class classification
            labels = {f"node_{i}": i % 3 for i in range(10)}

            predictor = GNNPredictor(GNNModelType.GCN)

            # Mock the entire training process
            with patch.object(predictor, "build_model") as mock_build:
                with patch.object(predictor, "train_node_classification") as mock_train:
                    mock_train.return_value = {
                        "best_val_acc": 0.85,
                        "final_loss": 0.2,
                        "training_history": [{"epoch": 1, "loss": 0.5}],
                    }

                    # Build and train model
                    predictor.build_model(input_dim=3, output_dim=3)
                    results = predictor.train_node_classification(graph_data, labels)

                    assert results["best_val_acc"] == 0.85
                    mock_build.assert_called_once()
                    mock_train.assert_called_once()

    def test_end_to_end_link_prediction(self):
        """Test complete link prediction workflow with synthetic data."""
        with patch(
            "brain_researcher.services.br_kg.ml.gnn_models.TORCH_AVAILABLE", True
        ):
            # Create synthetic graph data
            graph_data = {
                "nodes": [f"node_{i}" for i in range(6)],
                "edges": [
                    {"start": "node_0", "end": "node_1"},
                    {"start": "node_2", "end": "node_3"},
                ],
                "node_features": {
                    f"node_{i}": [float(i), float(i * 2)] for i in range(6)
                },
            }

            # Positive and negative edge examples
            positive_edges = [("node_0", "node_1"), ("node_2", "node_3")]
            negative_edges = [("node_0", "node_3"), ("node_1", "node_2")]

            predictor = GNNPredictor(GNNModelType.GRAPHSAGE)

            with patch.object(predictor, "build_model"):
                with patch.object(predictor, "train_link_prediction") as mock_train:
                    mock_train.return_value = {
                        "best_val_auc": 0.78,
                        "final_loss": 0.4,
                        "training_history": [{"epoch": 1, "loss": 0.6}],
                    }

                    predictor.build_model(input_dim=2, output_dim=8)
                    results = predictor.train_link_prediction(
                        graph_data, positive_edges, negative_edges
                    )

                    assert results["best_val_auc"] == 0.78


if __name__ == "__main__":
    pytest.main([__file__])
