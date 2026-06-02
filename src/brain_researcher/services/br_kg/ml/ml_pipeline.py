"""ML Pipeline for graph machine learning - completes KG-031 Graph ML.

This module provides a complete ML pipeline including training, evaluation,
and prediction services for graph machine learning tasks.
"""

import asyncio
import json
import logging
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import joblib
    import numpy as np
    from sklearn.metrics import (
        accuracy_score,
        precision_recall_fscore_support,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    SKLEARN_AVAILABLE = True
except ImportError:
    np = None
    accuracy_score = None
    precision_recall_fscore_support = None
    roc_auc_score = None
    train_test_split = None
    joblib = None
    SKLEARN_AVAILABLE = False

from .gnn_models import GNNConfig, GNNModelType, GNNPredictor
from .graph_embeddings import EmbeddingConfig, EmbeddingType, GraphEmbedder

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of ML tasks."""

    NODE_CLASSIFICATION = "node_classification"
    LINK_PREDICTION = "link_prediction"
    GRAPH_CLASSIFICATION = "graph_classification"
    NODE_REGRESSION = "node_regression"
    GRAPH_REGRESSION = "graph_regression"
    EMBEDDING_GENERATION = "embedding_generation"
    ANOMALY_DETECTION = "anomaly_detection"
    COMMUNITY_DETECTION = "community_detection"


@dataclass
class MLTask:
    """Represents an ML task configuration."""

    task_id: str
    task_type: TaskType
    name: str
    description: str = ""

    # Data configuration
    graph_data: Optional[Dict[str, Any]] = None
    labels: Optional[Dict[str, Any]] = None
    features: Optional[Dict[str, Any]] = None

    # Model configuration
    model_type: str = "gnn"  # "gnn" or "embedding"
    model_config: Optional[Dict[str, Any]] = None

    # Training configuration
    train_ratio: float = 0.8
    val_ratio: float = 0.1
    test_ratio: float = 0.1
    random_seed: int = 42

    # Task metadata
    created_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "name": self.name,
            "description": self.description,
            "graph_data": self.graph_data,
            "labels": self.labels,
            "features": self.features,
            "model_type": self.model_type,
            "model_config": self.model_config,
            "train_ratio": self.train_ratio,
            "val_ratio": self.val_ratio,
            "test_ratio": self.test_ratio,
            "random_seed": self.random_seed,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MLTask":
        """Create from dictionary."""
        return cls(
            task_id=data["task_id"],
            task_type=TaskType(data["task_type"]),
            name=data["name"],
            description=data.get("description", ""),
            graph_data=data.get("graph_data"),
            labels=data.get("labels"),
            features=data.get("features"),
            model_type=data.get("model_type", "gnn"),
            model_config=data.get("model_config"),
            train_ratio=data.get("train_ratio", 0.8),
            val_ratio=data.get("val_ratio", 0.1),
            test_ratio=data.get("test_ratio", 0.1),
            random_seed=data.get("random_seed", 42),
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now().isoformat())
            ),
            tags=data.get("tags", []),
        )


@dataclass
class TrainingResult:
    """Results from model training."""

    task_id: str
    model_type: str

    # Training metrics
    training_metrics: Dict[str, Any] = field(default_factory=dict)
    validation_metrics: Dict[str, Any] = field(default_factory=dict)
    test_metrics: Dict[str, Any] = field(default_factory=dict)

    # Training history
    training_history: List[Dict[str, Any]] = field(default_factory=list)

    # Model info
    model_path: Optional[str] = None
    model_params: Dict[str, Any] = field(default_factory=dict)

    # Training metadata
    training_time_seconds: float = 0.0
    epochs_completed: int = 0
    best_epoch: int = 0

    # Status
    status: str = "completed"  # "completed", "failed", "stopped"
    error_message: Optional[str] = None

    completed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "model_type": self.model_type,
            "training_metrics": self.training_metrics,
            "validation_metrics": self.validation_metrics,
            "test_metrics": self.test_metrics,
            "training_history": self.training_history,
            "model_path": self.model_path,
            "model_params": self.model_params,
            "training_time_seconds": self.training_time_seconds,
            "epochs_completed": self.epochs_completed,
            "best_epoch": self.best_epoch,
            "status": self.status,
            "error_message": self.error_message,
            "completed_at": self.completed_at.isoformat(),
        }


class ModelTrainer:
    """Trains machine learning models on graph data."""

    def __init__(self, model_storage_path: str = "./models"):
        """Initialize model trainer.

        Args:
            model_storage_path: Path to store trained models
        """
        if not SKLEARN_AVAILABLE:
            logger.warning(
                "scikit-learn not available, some functionality may be limited"
            )

        self.model_storage_path = Path(model_storage_path)
        self.model_storage_path.mkdir(parents=True, exist_ok=True)

        # Training state
        self.active_trainings: Dict[str, Any] = {}
        self.training_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

        logger.info(f"Initialized model trainer with storage at {model_storage_path}")

    async def train_model(self, task: MLTask) -> TrainingResult:
        """Train a model for the given task.

        Args:
            task: ML task to train for

        Returns:
            Training results
        """
        start_time = datetime.now()

        try:
            logger.info(f"Starting training for task {task.task_id}: {task.name}")

            # Mark task as active
            self.active_trainings[task.task_id] = {
                "start_time": start_time,
                "status": "training",
                "progress": 0.0,
            }

            # Train based on model type
            if task.model_type == "gnn":
                result = await self._train_gnn_model(task)
            elif task.model_type == "embedding":
                result = await self._train_embedding_model(task)
            else:
                raise ValueError(f"Unsupported model type: {task.model_type}")

            # Calculate training time
            result.training_time_seconds = (datetime.now() - start_time).total_seconds()
            result.completed_at = datetime.now()
            result.status = "completed"

            # Save model if path is provided
            if result.model_path:
                model_dir = self.model_storage_path / task.task_id
                model_dir.mkdir(exist_ok=True)

                # Update path to full path
                result.model_path = str(model_dir / Path(result.model_path).name)

            logger.info(
                f"Completed training for task {task.task_id} in {result.training_time_seconds:.2f}s"
            )

            # Notify callbacks
            for callback in self.training_callbacks:
                try:
                    callback(task.task_id, result.to_dict())
                except Exception as e:
                    logger.error(f"Error in training callback: {e}", exc_info=True)

            return result

        except Exception as e:
            logger.error(f"Training failed for task {task.task_id}: {e}", exc_info=True)

            result = TrainingResult(
                task_id=task.task_id,
                model_type=task.model_type,
                training_time_seconds=(datetime.now() - start_time).total_seconds(),
                status="failed",
                error_message=str(e),
                completed_at=datetime.now(),
            )

            return result

        finally:
            # Clean up active training
            self.active_trainings.pop(task.task_id, None)

    async def _train_gnn_model(self, task: MLTask) -> TrainingResult:
        """Train a GNN model."""
        if not task.graph_data:
            raise ValueError("Graph data is required for GNN training")

        # Parse model configuration
        model_config = task.model_config or {}
        model_type = GNNModelType(model_config.get("model_type", "gcn"))

        # Determine input/output dimensions
        nodes = task.graph_data.get("nodes", [])
        node_features = task.graph_data.get("node_features", {})

        if node_features:
            input_dim = len(list(node_features.values())[0])
        else:
            input_dim = len(nodes)  # Use identity features

        # Determine output dimension based on task
        if task.task_type == TaskType.NODE_CLASSIFICATION and task.labels:
            output_dim = len(set(task.labels.values()))
        elif task.task_type == TaskType.LINK_PREDICTION:
            output_dim = 1  # Binary classification
        else:
            output_dim = model_config.get("output_dim", 64)

        # Create GNN config
        gnn_config = GNNConfig(
            model_type=model_type,
            input_dim=input_dim,
            output_dim=output_dim,
            **{k: v for k, v in model_config.items() if k not in ["model_type"]},
        )

        # Create and build model
        predictor = GNNPredictor(model_type, gnn_config)
        predictor.build_model(input_dim, output_dim)

        # Train based on task type
        if task.task_type == TaskType.NODE_CLASSIFICATION:
            if not task.labels:
                raise ValueError("Labels are required for node classification")

            # Split nodes for train/val
            node_ids = list(task.labels.keys())
            if SKLEARN_AVAILABLE:
                train_nodes, val_nodes = train_test_split(
                    node_ids, train_size=task.train_ratio, random_state=task.random_seed
                )
            else:
                # Simple split without sklearn
                split_idx = int(len(node_ids) * task.train_ratio)
                train_nodes = node_ids[:split_idx]
                val_nodes = node_ids[split_idx:]

            training_results = predictor.train_node_classification(
                task.graph_data,
                task.labels,
                train_mask=train_nodes,
                val_mask=val_nodes,
                num_classes=output_dim,
            )

        elif task.task_type == TaskType.LINK_PREDICTION:
            # Generate positive and negative edges for training
            edges = task.graph_data.get("edges", [])
            positive_edges = [
                (e.get("start") or e.get("source"), e.get("end") or e.get("target"))
                for e in edges
            ]

            # Generate negative edges (sample non-existing edges)
            negative_edges = self._generate_negative_edges(
                task.graph_data, len(positive_edges)
            )

            training_results = predictor.train_link_prediction(
                task.graph_data,
                positive_edges,
                negative_edges,
                train_ratio=task.train_ratio,
            )

        else:
            raise ValueError(f"Unsupported task type for GNN: {task.task_type}")

        # Save model
        model_filename = f"gnn_{model_type.value}_{task.task_id}.pth"
        model_path = self.model_storage_path / task.task_id / model_filename
        model_path.parent.mkdir(exist_ok=True, parents=True)
        predictor.save_model(str(model_path))

        # Create result
        result = TrainingResult(
            task_id=task.task_id,
            model_type="gnn",
            training_metrics={"final_loss": training_results.get("final_loss", 0.0)},
            validation_metrics={
                "best_val_acc": training_results.get("best_val_acc", 0.0)
            },
            training_history=training_results.get("training_history", []),
            model_path=model_filename,
            model_params=gnn_config.to_dict(),
            epochs_completed=training_results.get("num_epochs", 0),
        )

        return result

    async def _train_embedding_model(self, task: MLTask) -> TrainingResult:
        """Train an embedding model."""
        if not task.graph_data:
            raise ValueError("Graph data is required for embedding training")

        # Parse model configuration
        model_config = task.model_config or {}
        embedding_type = EmbeddingType(model_config.get("embedding_type", "node2vec"))

        # Create embedding config
        embedding_config = EmbeddingConfig(
            embedding_type=embedding_type,
            **{k: v for k, v in model_config.items() if k not in ["embedding_type"]},
        )

        # Create embedder
        embedder = GraphEmbedder(embedding_type, embedding_config)

        # Train embeddings
        start_time = datetime.now()
        embeddings = embedder.fit(task.graph_data)
        training_time = (datetime.now() - start_time).total_seconds()

        if not embeddings:
            raise ValueError("Failed to generate embeddings")

        # Save embeddings
        model_filename = f"embeddings_{embedding_type.value}_{task.task_id}.pkl"
        model_path = self.model_storage_path / task.task_id / model_filename
        model_path.parent.mkdir(exist_ok=True, parents=True)
        embedder.save_model(str(model_path))

        # Calculate basic metrics
        embedding_info = embedder.get_embedding_info()

        # Create result
        result = TrainingResult(
            task_id=task.task_id,
            model_type="embedding",
            training_metrics={
                "num_embeddings": embedding_info["num_embeddings"],
                "embedding_dimension": embedding_info["embedding_dimension"],
                "training_time_seconds": training_time,
            },
            model_path=model_filename,
            model_params=embedding_config.to_dict(),
        )

        return result

    def _generate_negative_edges(
        self, graph_data: Dict[str, Any], num_negatives: int
    ) -> List[Tuple[str, str]]:
        """Generate negative edges for link prediction."""
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        # Create set of existing edges
        existing_edges = set()
        for edge in edges:
            src = edge.get("start") or edge.get("source")
            dst = edge.get("end") or edge.get("target")
            existing_edges.add((src, dst))
            existing_edges.add((dst, src))  # Treat as undirected

        # Generate random negative edges
        negative_edges = []
        attempts = 0
        max_attempts = num_negatives * 10

        import random

        while len(negative_edges) < num_negatives and attempts < max_attempts:
            src = random.choice(nodes)
            dst = random.choice(nodes)

            if src != dst and (src, dst) not in existing_edges:
                negative_edges.append((src, dst))

            attempts += 1

        return negative_edges

    def add_training_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Add a callback for training events."""
        self.training_callbacks.append(callback)

    def get_training_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get status of active training."""
        return self.active_trainings.get(task_id)

    def list_active_trainings(self) -> Dict[str, Any]:
        """List all active trainings."""
        return self.active_trainings.copy()


class ModelEvaluator:
    """Evaluates trained models."""

    def __init__(self):
        """Initialize model evaluator."""
        if not SKLEARN_AVAILABLE:
            logger.warning(
                "scikit-learn not available, some metrics may not be available"
            )

    def evaluate_model(
        self,
        model_path: str,
        test_data: Dict[str, Any],
        task_type: TaskType,
        labels: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a trained model.

        Args:
            model_path: Path to the trained model
            test_data: Test data
            task_type: Type of ML task
            labels: Ground truth labels

        Returns:
            Evaluation metrics
        """
        try:
            if task_type == TaskType.NODE_CLASSIFICATION:
                return self._evaluate_node_classification(model_path, test_data, labels)
            elif task_type == TaskType.LINK_PREDICTION:
                return self._evaluate_link_prediction(model_path, test_data, labels)
            elif task_type == TaskType.EMBEDDING_GENERATION:
                return self._evaluate_embeddings(model_path, test_data)
            else:
                raise ValueError(f"Unsupported task type for evaluation: {task_type}")

        except Exception as e:
            logger.error(f"Evaluation failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _evaluate_node_classification(
        self, model_path: str, test_data: Dict[str, Any], labels: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate node classification model."""
        # Load GNN model
        predictor = GNNPredictor(GNNModelType.GCN)  # Type will be loaded from file
        predictor.load_model(model_path)

        # Make predictions
        predictions_result = predictor.predict(
            test_data, task_type="node_classification"
        )
        predictions = predictions_result["predictions"]
        probabilities = predictions_result["probabilities"]
        node_ids = predictions_result["node_ids"]

        # Get ground truth
        true_labels = [labels[node_id] for node_id in node_ids if node_id in labels]
        pred_labels = predictions[: len(true_labels)]

        if not true_labels:
            return {"error": "No ground truth labels found"}

        # Calculate metrics
        metrics = {}

        if SKLEARN_AVAILABLE:
            metrics["accuracy"] = accuracy_score(true_labels, pred_labels)

            # Precision, recall, F1
            precision, recall, f1, _ = precision_recall_fscore_support(
                true_labels, pred_labels, average="weighted"
            )
            metrics["precision"] = precision
            metrics["recall"] = recall
            metrics["f1_score"] = f1

            # AUC if probabilities available
            if len(set(true_labels)) == 2:  # Binary classification
                try:
                    metrics["auc"] = roc_auc_score(
                        true_labels, probabilities[: len(true_labels), 1]
                    )
                except:
                    pass
        else:
            # Basic accuracy without sklearn
            metrics["accuracy"] = sum(
                1 for i in range(len(true_labels)) if true_labels[i] == pred_labels[i]
            ) / len(true_labels)

        metrics["num_test_samples"] = len(true_labels)
        metrics["num_classes"] = len(set(true_labels))

        return metrics

    def _evaluate_link_prediction(
        self, model_path: str, test_data: Dict[str, Any], test_edges: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate link prediction model."""
        # Load GNN model
        predictor = GNNPredictor(GNNModelType.GCN)  # Type will be loaded from file
        predictor.load_model(model_path)

        # Extract positive and negative test edges
        positive_edges = test_edges.get("positive", [])
        negative_edges = test_edges.get("negative", [])

        if not positive_edges or not negative_edges:
            return {"error": "Need both positive and negative test edges"}

        # Make predictions
        all_test_edges = positive_edges + negative_edges
        predictions_result = predictor.predict(
            test_data, task_type="link_prediction", test_edges=all_test_edges
        )

        link_probs = predictions_result["link_probabilities"]

        # Ground truth labels
        true_labels = [1] * len(positive_edges) + [0] * len(negative_edges)

        # Calculate metrics
        metrics = {}

        if SKLEARN_AVAILABLE and len(link_probs) == len(true_labels):
            try:
                metrics["auc"] = roc_auc_score(true_labels, link_probs)
            except:
                pass

            # Binary classification metrics
            pred_labels = (np.array(link_probs) > 0.5).astype(int)
            metrics["accuracy"] = accuracy_score(true_labels, pred_labels)

            precision, recall, f1, _ = precision_recall_fscore_support(
                true_labels, pred_labels, average="binary"
            )
            metrics["precision"] = precision
            metrics["recall"] = recall
            metrics["f1_score"] = f1

        metrics["num_positive_edges"] = len(positive_edges)
        metrics["num_negative_edges"] = len(negative_edges)

        return metrics

    def _evaluate_embeddings(
        self, model_path: str, test_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate embedding quality."""
        # Load embeddings
        embedder = GraphEmbedder(EmbeddingType.NODE2VEC)  # Type will be loaded
        embedder.load_model(model_path)

        # Get embedding info
        embedding_info = embedder.get_embedding_info()

        # Basic quality metrics
        embeddings = embedder.get_all_embeddings()

        if not embeddings:
            return {"error": "No embeddings found"}

        # Calculate embedding statistics
        embedding_matrix = np.array(list(embeddings.values()))

        metrics = {
            "num_embeddings": len(embeddings),
            "embedding_dimension": embedding_matrix.shape[1],
            "mean_norm": float(np.mean(np.linalg.norm(embedding_matrix, axis=1))),
            "std_norm": float(np.std(np.linalg.norm(embedding_matrix, axis=1))),
            "coverage": embedding_info.get("num_embeddings", 0)
            / len(test_data.get("nodes", [])),
        }

        return metrics


class PredictionService:
    """Provides prediction services for trained models."""

    def __init__(self, model_storage_path: str = "./models"):
        """Initialize prediction service.

        Args:
            model_storage_path: Path where models are stored
        """
        self.model_storage_path = Path(model_storage_path)

        # Cache for loaded models
        self.model_cache: Dict[str, Any] = {}
        self.cache_size_limit = 5

        logger.info("Initialized prediction service")

    def predict(
        self, model_id: str, graph_data: Dict[str, Any], task_type: TaskType, **kwargs
    ) -> Dict[str, Any]:
        """Make predictions using a trained model.

        Args:
            model_id: ID of the trained model
            graph_data: Graph data to make predictions on
            task_type: Type of prediction task
            **kwargs: Additional arguments

        Returns:
            Prediction results
        """
        try:
            # Load model if not in cache
            model = self._get_model(model_id)

            if model is None:
                return {"error": f"Model {model_id} not found"}

            # Make predictions based on model type
            if isinstance(model, GNNPredictor):
                return self._predict_with_gnn(model, graph_data, task_type, **kwargs)
            elif isinstance(model, GraphEmbedder):
                return self._predict_with_embedder(model, graph_data, **kwargs)
            else:
                return {"error": f"Unsupported model type for {model_id}"}

        except Exception as e:
            logger.error(f"Prediction failed for model {model_id}: {e}", exc_info=True)
            return {"error": str(e)}

    def _get_model(self, model_id: str) -> Optional[Any]:
        """Get model from cache or load from disk."""
        if model_id in self.model_cache:
            return self.model_cache[model_id]

        # Find model file
        model_dir = self.model_storage_path / model_id
        if not model_dir.exists():
            return None

        # Look for model files
        gnn_files = list(model_dir.glob("gnn_*.pth"))
        embedding_files = list(model_dir.glob("embeddings_*.pkl"))

        model = None

        if gnn_files:
            # Load GNN model
            model_file = gnn_files[0]
            model = GNNPredictor(GNNModelType.GCN)  # Type will be loaded from file
            model.load_model(str(model_file))

        elif embedding_files:
            # Load embedding model
            model_file = embedding_files[0]
            model = GraphEmbedder(EmbeddingType.NODE2VEC)  # Type will be loaded
            model.load_model(str(model_file))

        if model:
            # Add to cache
            self.model_cache[model_id] = model

            # Limit cache size
            if len(self.model_cache) > self.cache_size_limit:
                oldest_key = next(iter(self.model_cache))
                del self.model_cache[oldest_key]

        return model

    def _predict_with_gnn(
        self,
        model: GNNPredictor,
        graph_data: Dict[str, Any],
        task_type: TaskType,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make predictions with GNN model."""
        if task_type == TaskType.NODE_CLASSIFICATION:
            num_classes = kwargs.get("num_classes", 2)
            return model.predict(
                graph_data, task_type="node_classification", num_classes=num_classes
            )

        elif task_type == TaskType.LINK_PREDICTION:
            test_edges = kwargs.get("test_edges", [])
            return model.predict(
                graph_data, task_type="link_prediction", test_edges=test_edges
            )

        else:
            return model.predict(graph_data, task_type="node_embeddings")

    def _predict_with_embedder(
        self, model: GraphEmbedder, graph_data: Dict[str, Any], **kwargs
    ) -> Dict[str, Any]:
        """Make predictions with embedding model."""
        # For embeddings, we just return the embeddings
        embeddings = model.get_all_embeddings()

        # Optional: find similar entities
        target_entity = kwargs.get("target_entity")
        if target_entity and target_entity in embeddings:
            similar_entities = model.most_similar(
                target_entity, topn=kwargs.get("topn", 10)
            )
            return {
                "target_entity": target_entity,
                "embedding": embeddings[target_entity].tolist(),
                "similar_entities": similar_entities,
            }

        return {
            "embeddings": {k: v.tolist() for k, v in embeddings.items()},
            "embedding_info": model.get_embedding_info(),
        }

    def list_available_models(self) -> List[Dict[str, Any]]:
        """List available models."""
        models = []

        for model_dir in self.model_storage_path.iterdir():
            if model_dir.is_dir():
                model_info = {
                    "model_id": model_dir.name,
                    "model_files": [],
                    "model_type": "unknown",
                }

                # Check for GNN files
                gnn_files = list(model_dir.glob("gnn_*.pth"))
                if gnn_files:
                    model_info["model_type"] = "gnn"
                    model_info["model_files"] = [f.name for f in gnn_files]

                # Check for embedding files
                embedding_files = list(model_dir.glob("embeddings_*.pkl"))
                if embedding_files:
                    model_info["model_type"] = "embedding"
                    model_info["model_files"] = [f.name for f in embedding_files]

                models.append(model_info)

        return models

    def clear_cache(self):
        """Clear model cache."""
        self.model_cache.clear()
        logger.info("Cleared model cache")


class MLPipeline:
    """Complete ML pipeline for graph machine learning."""

    def __init__(self, storage_path: str = "./ml_pipeline"):
        """Initialize ML pipeline.

        Args:
            storage_path: Path for pipeline storage
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Components
        self.trainer = ModelTrainer(str(self.storage_path / "models"))
        self.evaluator = ModelEvaluator()
        self.prediction_service = PredictionService(str(self.storage_path / "models"))

        # Task management
        self.tasks: Dict[str, MLTask] = {}
        self.training_results: Dict[str, TrainingResult] = {}

        # Load existing tasks
        self._load_tasks()

        logger.info(f"Initialized ML pipeline with storage at {storage_path}")

    def create_task(self, task: MLTask) -> str:
        """Create a new ML task.

        Args:
            task: ML task to create

        Returns:
            Task ID
        """
        self.tasks[task.task_id] = task
        self._save_task(task)

        logger.info(f"Created ML task {task.task_id}: {task.name}")
        return task.task_id

    async def run_task(self, task_id: str) -> TrainingResult:
        """Run an ML task (train and evaluate).

        Args:
            task_id: Task ID to run

        Returns:
            Training results
        """
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.tasks[task_id]

        # Train model
        training_result = await self.trainer.train_model(task)

        # Store result
        self.training_results[task_id] = training_result
        self._save_training_result(training_result)

        # Evaluate if training was successful
        if training_result.status == "completed" and training_result.model_path:
            try:
                evaluation_metrics = self.evaluator.evaluate_model(
                    str(
                        self.storage_path
                        / "models"
                        / task_id
                        / training_result.model_path
                    ),
                    task.graph_data,
                    task.task_type,
                    task.labels,
                )
                training_result.test_metrics = evaluation_metrics
                self._save_training_result(training_result)

            except Exception as e:
                logger.error(f"Evaluation failed for task {task_id}: {e}")

        return training_result

    def predict(
        self, task_id: str, graph_data: Dict[str, Any], **kwargs
    ) -> Dict[str, Any]:
        """Make predictions for a task.

        Args:
            task_id: Task ID
            graph_data: Graph data to predict on
            **kwargs: Additional arguments

        Returns:
            Prediction results
        """
        if task_id not in self.tasks:
            return {"error": f"Task {task_id} not found"}

        task = self.tasks[task_id]

        return self.prediction_service.predict(
            task_id, graph_data, task.task_type, **kwargs
        )

    def get_task(self, task_id: str) -> Optional[MLTask]:
        """Get task by ID."""
        return self.tasks.get(task_id)

    def get_training_result(self, task_id: str) -> Optional[TrainingResult]:
        """Get training result by task ID."""
        return self.training_results.get(task_id)

    def list_tasks(self) -> List[MLTask]:
        """List all tasks."""
        return list(self.tasks.values())

    def list_training_results(self) -> List[TrainingResult]:
        """List all training results."""
        return list(self.training_results.values())

    def delete_task(self, task_id: str) -> bool:
        """Delete a task and its associated data.

        Args:
            task_id: Task ID to delete

        Returns:
            True if deleted successfully
        """
        if task_id not in self.tasks:
            return False

        # Remove from memory
        self.tasks.pop(task_id, None)
        self.training_results.pop(task_id, None)

        # Remove files
        task_file = self.storage_path / "tasks" / f"{task_id}.json"
        result_file = self.storage_path / "results" / f"{task_id}.json"

        if task_file.exists():
            task_file.unlink()
        if result_file.exists():
            result_file.unlink()

        # Remove model directory
        model_dir = self.storage_path / "models" / task_id
        if model_dir.exists():
            import shutil

            shutil.rmtree(model_dir)

        logger.info(f"Deleted task {task_id}")
        return True

    def _save_task(self, task: MLTask):
        """Save task to disk."""
        tasks_dir = self.storage_path / "tasks"
        tasks_dir.mkdir(exist_ok=True)

        task_file = tasks_dir / f"{task.task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task.to_dict(), f, indent=2)

    def _save_training_result(self, result: TrainingResult):
        """Save training result to disk."""
        results_dir = self.storage_path / "results"
        results_dir.mkdir(exist_ok=True)

        result_file = results_dir / f"{result.task_id}.json"
        with open(result_file, "w") as f:
            json.dump(result.to_dict(), f, indent=2)

    def _load_tasks(self):
        """Load existing tasks from disk."""
        tasks_dir = self.storage_path / "tasks"
        results_dir = self.storage_path / "results"

        if tasks_dir.exists():
            for task_file in tasks_dir.glob("*.json"):
                try:
                    with open(task_file, "r") as f:
                        task_data = json.load(f)

                    task = MLTask.from_dict(task_data)
                    self.tasks[task.task_id] = task

                except Exception as e:
                    logger.error(f"Failed to load task from {task_file}: {e}")

        if results_dir.exists():
            for result_file in results_dir.glob("*.json"):
                try:
                    with open(result_file, "r") as f:
                        result_data = json.load(f)

                    result = TrainingResult(**result_data)
                    self.training_results[result.task_id] = result

                except Exception as e:
                    logger.error(
                        f"Failed to load training result from {result_file}: {e}"
                    )

        logger.info(
            f"Loaded {len(self.tasks)} tasks and {len(self.training_results)} training results"
        )

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get overall pipeline status."""
        active_trainings = self.trainer.list_active_trainings()
        available_models = self.prediction_service.list_available_models()

        # Task statistics
        task_types = defaultdict(int)
        completed_tasks = 0
        failed_tasks = 0

        for result in self.training_results.values():
            if result.status == "completed":
                completed_tasks += 1
            elif result.status == "failed":
                failed_tasks += 1

        for task in self.tasks.values():
            task_types[task.task_type.value] += 1

        return {
            "total_tasks": len(self.tasks),
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "active_trainings": len(active_trainings),
            "available_models": len(available_models),
            "task_types": dict(task_types),
            "storage_path": str(self.storage_path),
            "active_training_details": active_trainings,
        }
