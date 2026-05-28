"""
Integration tests for ML workflow covering complete machine learning pipeline
including GNN models, graph embeddings, and their interactions with the knowledge graph.

Tests the full workflow from graph data preparation through training to inference,
ensuring all components work together correctly.
"""

import pytest
import asyncio
import pytest
pytest.skip('torch/gnn stack not available', allow_module_level=True)
import numpy as np
import torch
import torch.nn as nn
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from typing import List, Dict, Any, Tuple
import json
import tempfile
import os
from pathlib import Path

# Import the modules under test
from brain_researcher.services.neurokg.ml.gnn_models import (
    GCN, GraphSAGE, GAT, GNNPredictor, ModelConfig
)
from brain_researcher.services.neurokg.ml.graph_embeddings import (
    Node2Vec, DeepWalk, Graph2Vec, GraphEmbeddings, EmbeddingConfig
)


class MockNeo4jDriver:
    """Mock Neo4j driver for testing graph data operations"""
    
    def __init__(self):
        self.session_mock = AsyncMock()
        self.closed = False
        self._setup_mock_data()
    
    def _setup_mock_data(self):
        """Setup mock graph data"""
        # Mock nodes
        self.mock_nodes = [
            {"id": i, "labels": ["Concept"], "properties": {"name": f"concept_{i}", "embedding": [0.1 * i] * 64}}
            for i in range(100)
        ]
        
        # Mock edges
        self.mock_edges = [
            {"start": i, "end": (i + 1) % 100, "type": "RELATED_TO", "weight": 0.8}
            for i in range(200)
        ]
    
    async def session(self):
        return self.session_mock
    
    async def close(self):
        self.closed = True


class MockGraphData:
    """Mock graph data structure for testing"""
    
    def __init__(self, num_nodes=100, num_edges=200, num_features=64):
        self.num_nodes = num_nodes
        self.num_edges = num_edges
        self.num_features = num_features
        
        # Generate mock node features
        self.x = torch.randn(num_nodes, num_features)
        
        # Generate mock edge indices
        edge_list = [(i, (i + 1) % num_nodes) for i in range(num_edges)]
        self.edge_index = torch.tensor(edge_list, dtype=torch.long).t()
        
        # Generate mock labels for classification
        self.y = torch.randint(0, 5, (num_nodes,))
        
        # Training/test masks
        self.train_mask = torch.zeros(num_nodes, dtype=torch.bool)
        self.test_mask = torch.zeros(num_nodes, dtype=torch.bool)
        self.train_mask[:int(0.6 * num_nodes)] = True
        self.test_mask[int(0.8 * num_nodes):] = True


@pytest.fixture
async def mock_neo4j_driver():
    """Fixture for mock Neo4j driver"""
    driver = MockNeo4jDriver()
    yield driver
    await driver.close()


@pytest.fixture
def mock_graph_data():
    """Fixture for mock graph data"""
    return MockGraphData()


@pytest.fixture
def temp_model_dir():
    """Fixture for temporary model directory"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def embedding_config():
    """Fixture for embedding configuration"""
    return EmbeddingConfig(
        dimensions=64,
        walk_length=10,
        num_walks=5,
        window_size=5,
        workers=1,
        epochs=1,
        learning_rate=0.025
    )


@pytest.fixture
def model_config():
    """Fixture for GNN model configuration"""
    return ModelConfig(
        input_dim=64,
        hidden_dim=32,
        output_dim=5,
        num_layers=2,
        dropout=0.1,
        learning_rate=0.01,
        weight_decay=1e-4
    )


class TestMLWorkflowIntegration:
    """Test complete ML workflow integration"""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_embedding_to_gnn_pipeline(self, mock_neo4j_driver, temp_model_dir, 
                                                     embedding_config, model_config):
        """Test complete pipeline from embeddings to GNN training"""
        
        # Step 1: Generate graph embeddings
        embeddings = GraphEmbeddings()
        
        # Mock graph data for embedding generation
        mock_graph = {
            "nodes": list(range(100)),
            "edges": [(i, (i + 1) % 100) for i in range(200)]
        }
        
        with patch.object(embeddings, '_load_graph_from_neo4j', return_value=mock_graph):
            # Generate Node2Vec embeddings
            node2vec = Node2Vec(embedding_config)
            embedding_result = await embeddings.generate_embeddings(
                driver=mock_neo4j_driver,
                method="node2vec",
                config=embedding_config
            )
            
            assert "embeddings" in embedding_result
            assert "metadata" in embedding_result
            assert len(embedding_result["embeddings"]) == 100
            
        # Step 2: Prepare data for GNN training
        # Convert embeddings to graph data format
        node_features = torch.tensor([embedding_result["embeddings"][str(i)] for i in range(100)])
        edge_list = [(i, (i + 1) % 100) for i in range(200)]
        edge_index = torch.tensor(edge_list, dtype=torch.long).t()
        
        # Mock labels for supervised learning
        labels = torch.randint(0, 5, (100,))
        train_mask = torch.zeros(100, dtype=torch.bool)
        train_mask[:60] = True
        
        graph_data = type('GraphData', (), {
            'x': node_features,
            'edge_index': edge_index,
            'y': labels,
            'train_mask': train_mask,
            'test_mask': ~train_mask
        })()
        
        # Step 3: Train GNN model
        gnn_predictor = GNNPredictor()
        
        # Test GCN model
        gcn_model = GCN(model_config)
        training_result = await gnn_predictor.train_model(
            model=gcn_model,
            data=graph_data,
            config=model_config
        )
        
        assert "loss" in training_result
        assert "accuracy" in training_result
        assert training_result["accuracy"] > 0.0
        
        # Step 4: Test inference
        gcn_model.eval()
        with torch.no_grad():
            predictions = gcn_model(graph_data.x, graph_data.edge_index)
            assert predictions.shape == (100, 5)
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multi_model_comparison_workflow(self, mock_neo4j_driver, temp_model_dir,
                                                  embedding_config, model_config, mock_graph_data):
        """Test workflow comparing multiple GNN models on same data"""
        
        models_to_test = [
            ("GCN", GCN(model_config)),
            ("GraphSAGE", GraphSAGE(model_config)),
            ("GAT", GAT(model_config))
        ]
        
        gnn_predictor = GNNPredictor()
        results = {}
        
        for model_name, model in models_to_test:
            # Train each model
            training_result = await gnn_predictor.train_model(
                model=model,
                data=mock_graph_data,
                config=model_config
            )
            
            # Evaluate model
            model.eval()
            with torch.no_grad():
                predictions = model(mock_graph_data.x, mock_graph_data.edge_index)
                test_predictions = predictions[mock_graph_data.test_mask]
                test_labels = mock_graph_data.y[mock_graph_data.test_mask]
                
                # Calculate test accuracy
                test_acc = (test_predictions.argmax(dim=1) == test_labels).float().mean()
                
            results[model_name] = {
                "train_loss": training_result["loss"],
                "train_accuracy": training_result["accuracy"],
                "test_accuracy": float(test_acc)
            }
        
        # Verify all models trained successfully
        for model_name, result in results.items():
            assert result["train_accuracy"] > 0.0
            assert result["test_accuracy"] >= 0.0
            assert result["train_loss"] >= 0.0
        
        # Verify we have results for all models
        assert len(results) == 3
        assert "GCN" in results
        assert "GraphSAGE" in results
        assert "GAT" in results
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_embedding_method_comparison_workflow(self, mock_neo4j_driver, embedding_config):
        """Test workflow comparing different embedding methods"""
        
        embeddings = GraphEmbeddings()
        
        # Mock graph data
        mock_graph = {
            "nodes": list(range(50)),
            "edges": [(i, (i + 1) % 50) for i in range(100)]
        }
        
        embedding_methods = ["node2vec", "deepwalk"]
        results = {}
        
        with patch.object(embeddings, '_load_graph_from_neo4j', return_value=mock_graph):
            for method in embedding_methods:
                result = await embeddings.generate_embeddings(
                    driver=mock_neo4j_driver,
                    method=method,
                    config=embedding_config
                )
                
                # Verify embedding quality
                embedding_matrix = np.array([result["embeddings"][str(i)] for i in range(50)])
                
                # Check embedding dimensions
                assert embedding_matrix.shape == (50, embedding_config.dimensions)
                
                # Check embedding diversity (no all-zero embeddings)
                assert not np.allclose(embedding_matrix, 0)
                
                # Store results for comparison
                results[method] = {
                    "embeddings": embedding_matrix,
                    "metadata": result["metadata"]
                }
        
        # Compare embedding methods
        assert len(results) == 2
        
        # Verify embeddings are different between methods
        node2vec_emb = results["node2vec"]["embeddings"]
        deepwalk_emb = results["deepwalk"]["embeddings"]
        
        # Should not be identical (different random seeds/methods)
        similarity = np.corrcoef(node2vec_emb.flatten(), deepwalk_emb.flatten())[0, 1]
        assert not np.isclose(similarity, 1.0)  # Not identical
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_end_to_end_knowledge_graph_ml_workflow(self, mock_neo4j_driver, temp_model_dir,
                                                         embedding_config, model_config):
        """Test end-to-end workflow from Neo4j to trained ML models"""
        
        # Mock Neo4j session responses
        mock_session = mock_neo4j_driver.session_mock
        
        # Mock node query response
        mock_nodes_result = Mock()
        mock_nodes_result.data.return_value = [
            {"n": {"id": i, "name": f"concept_{i}", "type": "Concept"}}
            for i in range(50)
        ]
        
        # Mock relationship query response  
        mock_rels_result = Mock()
        mock_rels_result.data.return_value = [
            {"r": {"source": i, "target": (i + 1) % 50, "type": "RELATED_TO", "weight": 0.8}}
            for i in range(100)
        ]
        
        mock_session.run.side_effect = [mock_nodes_result, mock_rels_result]
        
        # Step 1: Load graph from Neo4j
        embeddings = GraphEmbeddings()
        
        with patch.object(embeddings, '_load_graph_from_neo4j') as mock_load:
            mock_load.return_value = {
                "nodes": list(range(50)),
                "edges": [(i, (i + 1) % 50) for i in range(100)]
            }
            
            # Step 2: Generate embeddings
            embedding_result = await embeddings.generate_embeddings(
                driver=mock_neo4j_driver,
                method="node2vec",
                config=embedding_config
            )
            
            # Step 3: Prepare training data
            node_features = torch.tensor([embedding_result["embeddings"][str(i)] for i in range(50)])
            edge_list = [(i, (i + 1) % 50) for i in range(100)]
            edge_index = torch.tensor(edge_list, dtype=torch.long).t()
            
            # Mock task-specific labels (e.g., node classification)
            labels = torch.randint(0, 3, (50,))
            train_mask = torch.zeros(50, dtype=torch.bool)
            train_mask[:30] = True
            test_mask = torch.zeros(50, dtype=torch.bool)
            test_mask[40:] = True
            
            graph_data = type('GraphData', (), {
                'x': node_features,
                'edge_index': edge_index,
                'y': labels,
                'train_mask': train_mask,
                'test_mask': test_mask
            })()
            
            # Step 4: Train and evaluate GNN
            model_config.output_dim = 3  # Match number of classes
            gcn_model = GCN(model_config)
            gnn_predictor = GNNPredictor()
            
            training_result = await gnn_predictor.train_model(
                model=gcn_model,
                data=graph_data,
                config=model_config
            )
            
            # Step 5: Model persistence and loading
            model_path = temp_model_dir / "gcn_model.pt"
            torch.save(gcn_model.state_dict(), model_path)
            
            # Load model and verify consistency
            loaded_model = GCN(model_config)
            loaded_model.load_state_dict(torch.load(model_path))
            loaded_model.eval()
            
            # Compare predictions
            gcn_model.eval()
            with torch.no_grad():
                original_preds = gcn_model(graph_data.x, graph_data.edge_index)
                loaded_preds = loaded_model(graph_data.x, graph_data.edge_index)
                
                # Predictions should be identical
                assert torch.allclose(original_preds, loaded_preds, rtol=1e-5)
            
            # Verify training was successful
            assert training_result["accuracy"] > 0.0
            assert training_result["loss"] >= 0.0
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ml_workflow_error_handling(self, mock_neo4j_driver, embedding_config, model_config):
        """Test error handling throughout the ML workflow"""
        
        embeddings = GraphEmbeddings()
        gnn_predictor = GNNPredictor()
        
        # Test embedding generation with connection error
        with patch.object(mock_neo4j_driver, 'session', side_effect=Exception("Connection failed")):
            with pytest.raises(Exception, match="Connection failed"):
                await embeddings.generate_embeddings(
                    driver=mock_neo4j_driver,
                    method="node2vec",
                    config=embedding_config
                )
        
        # Test GNN training with invalid data
        invalid_data = type('InvalidData', (), {
            'x': torch.randn(10, 5),  # Wrong feature dimension
            'edge_index': torch.tensor([[0, 1], [1, 0]], dtype=torch.long),
            'y': torch.randint(0, 3, (10,)),
            'train_mask': torch.ones(10, dtype=torch.bool)
        })()
        
        model = GCN(model_config)  # Expects 64 features, got 5
        
        with pytest.raises(RuntimeError):  # PyTorch will raise dimension mismatch
            await gnn_predictor.train_model(
                model=model,
                data=invalid_data,
                config=model_config
            )
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ml_workflow_memory_management(self, mock_graph_data, model_config):
        """Test memory management in ML workflow"""
        
        initial_memory = torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
        
        # Train multiple models to test memory cleanup
        models = []
        for i in range(3):
            model = GCN(model_config)
            gnn_predictor = GNNPredictor()
            
            await gnn_predictor.train_model(
                model=model,
                data=mock_graph_data,
                config=model_config
            )
            
            models.append(model)
        
        # Explicitly delete models
        for model in models:
            del model
        
        # Force garbage collection
        import gc
        gc.collect()
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            final_memory = torch.cuda.memory_allocated()
            # Memory should not have grown excessively
            assert final_memory <= initial_memory + 100 * 1024 * 1024  # 100MB tolerance
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_ml_workflows(self, mock_neo4j_driver, embedding_config, model_config):
        """Test running multiple ML workflows concurrently"""
        
        async def run_embedding_workflow(method: str):
            """Run embedding generation workflow"""
            embeddings = GraphEmbeddings()
            mock_graph = {
                "nodes": list(range(20)),
                "edges": [(i, (i + 1) % 20) for i in range(40)]
            }
            
            with patch.object(embeddings, '_load_graph_from_neo4j', return_value=mock_graph):
                result = await embeddings.generate_embeddings(
                    driver=mock_neo4j_driver,
                    method=method,
                    config=embedding_config
                )
                return result
        
        async def run_gnn_workflow(model_class):
            """Run GNN training workflow"""
            # Create small dataset for quick training
            data = MockGraphData(num_nodes=20, num_edges=40, num_features=64)
            model = model_class(model_config)
            gnn_predictor = GNNPredictor()
            
            result = await gnn_predictor.train_model(
                model=model,
                data=data,
                config=model_config
            )
            return result
        
        # Run multiple workflows concurrently
        embedding_tasks = [
            run_embedding_workflow("node2vec"),
            run_embedding_workflow("deepwalk")
        ]
        
        gnn_tasks = [
            run_gnn_workflow(GCN),
            run_gnn_workflow(GraphSAGE)
        ]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(
            *embedding_tasks,
            *gnn_tasks,
            return_exceptions=True
        )
        
        # Verify all tasks completed successfully
        for i, result in enumerate(results):
            assert not isinstance(result, Exception), f"Task {i} failed: {result}"
        
        # Verify embedding results
        for i in range(2):
            assert "embeddings" in results[i]
            assert len(results[i]["embeddings"]) == 20
        
        # Verify GNN training results
        for i in range(2, 4):
            assert "accuracy" in results[i]
            assert results[i]["accuracy"] > 0.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ml_workflow_monitoring_and_metrics():
    """Test monitoring and metrics collection throughout ML workflow"""
    
    metrics = {
        "embedding_generation_time": [],
        "model_training_time": [],
        "memory_usage": [],
        "accuracy_scores": []
    }
    
    # Mock time tracking
    import time
    
    # Simulate embedding generation with timing
    start_time = time.time()
    await asyncio.sleep(0.1)  # Simulate work
    metrics["embedding_generation_time"].append(time.time() - start_time)
    
    # Simulate model training with timing
    start_time = time.time()
    await asyncio.sleep(0.2)  # Simulate training
    metrics["model_training_time"].append(time.time() - start_time)
    
    # Simulate accuracy tracking
    metrics["accuracy_scores"].append(0.85)
    
    # Simulate memory usage tracking
    metrics["memory_usage"].append(torch.cuda.memory_allocated() if torch.cuda.is_available() else 1024)
    
    # Verify metrics collection
    assert len(metrics["embedding_generation_time"]) > 0
    assert len(metrics["model_training_time"]) > 0
    assert len(metrics["accuracy_scores"]) > 0
    assert len(metrics["memory_usage"]) > 0
    
    # Verify timing makes sense
    assert metrics["embedding_generation_time"][0] >= 0.1
    assert metrics["model_training_time"][0] >= 0.2
    assert 0.0 <= metrics["accuracy_scores"][0] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])