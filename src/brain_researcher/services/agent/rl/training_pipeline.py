"""Training pipeline for RL optimization in neuroimaging agent."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import json
import os

from .iql_optimizer import IQLOptimizer, OfflineDataset
from .cql_optimizer import CQLOptimizer
from .reward_model import NeuroimagingRewardModel, RewardMetrics
from ...feedback.reward_tracker import RewardTracker

logger = logging.getLogger(__name__)


class TrainingMode(Enum):
    IQL = "iql"
    CQL = "cql"
    BOTH = "both"


@dataclass
class TrainingConfig:
    mode: TrainingMode
    state_dim: int
    action_dim: int
    epochs: int = 100
    batch_size: int = 256
    learning_rate: float = 0.0003
    validation_split: float = 0.1

    # IQL specific
    iql_expectile: float = 0.7
    iql_temperature: float = 3.0

    # CQL specific
    cql_alpha: float = 5.0
    cql_tau: float = 0.005
    use_ensemble: bool = False

    # General
    discount: float = 0.99
    min_dataset_size: int = 1000
    max_dataset_size: int = 50000

    # Evaluation
    eval_frequency: int = 10
    eval_episodes: int = 100

    # Saving
    save_frequency: int = 50
    checkpoint_dir: str = "./rl_checkpoints"


@dataclass
class TrainingMetrics:
    episode: int
    timestamp: datetime
    train_loss: float
    eval_performance: Dict[str, float]
    dataset_size: int
    training_time: float
    model_path: Optional[str] = None


class RLTrainingPipeline:
    """Comprehensive RL training pipeline for neuroimaging agent."""

    def __init__(
        self,
        config: TrainingConfig,
        reward_tracker: RewardTracker,
        reward_model: Optional[NeuroimagingRewardModel] = None
    ):
        self.config = config
        self.reward_tracker = reward_tracker
        self.reward_model = reward_model or NeuroimagingRewardModel()

        # Initialize optimizers
        self.iql_optimizer = None
        self.cql_optimizer = None

        if config.mode in [TrainingMode.IQL, TrainingMode.BOTH]:
            self.iql_optimizer = IQLOptimizer(
                state_dim=config.state_dim,
                action_dim=config.action_dim,
                expectile=config.iql_expectile,
                temperature=config.iql_temperature,
                learning_rate=config.learning_rate,
                discount=config.discount
            )

        if config.mode in [TrainingMode.CQL, TrainingMode.BOTH]:
            self.cql_optimizer = CQLOptimizer(
                state_dim=config.state_dim,
                action_dim=config.action_dim,
                alpha=config.cql_alpha,
                learning_rate=config.learning_rate,
                discount=config.discount,
                tau=config.cql_tau,
                use_ensemble=config.use_ensemble
            )

        # Training state
        self.training_history = []
        self.current_dataset = OfflineDataset()
        self.best_performance = float('-inf')
        self.episodes_trained = 0

        # Create checkpoint directory
        os.makedirs(config.checkpoint_dir, exist_ok=True)

        logger.info(f"Initialized RL training pipeline with mode: {config.mode.value}")

    def update_dataset(
        self,
        min_age_hours: int = 0,
        max_age_hours: int = 168,  # 1 week
        balance_actions: bool = True
    ) -> int:
        """Update dataset with recent reward tracker data."""
        logger.info("Updating training dataset from reward tracker...")

        # Get training data from reward tracker
        states, actions, rewards, next_states, dones, weights = self.reward_tracker.get_training_data(
            batch_size=self.config.max_dataset_size,
            max_age_hours=max_age_hours,
            balance_actions=balance_actions
        )

        if len(states) < self.config.min_dataset_size:
            logger.warning(f"Insufficient training data: {len(states)} < {self.config.min_dataset_size}")
            return 0

        # Create new dataset
        self.current_dataset = OfflineDataset()
        self.current_dataset.add_batch(states, actions, rewards, next_states, dones, weights)

        # Update reward model baselines
        recent_performance = self._get_recent_performance_data()
        if recent_performance:
            self.reward_model.update_baselines(recent_performance)

        logger.info(f"Updated dataset with {len(self.current_dataset)} samples")
        return len(self.current_dataset)

    def train_epoch(self) -> Dict[str, Any]:
        """Train for one epoch and return metrics."""
        if len(self.current_dataset) < self.config.min_dataset_size:
            logger.warning("Dataset too small for training")
            return {}

        start_time = datetime.utcnow()
        results = {}

        # Train IQL if enabled
        if self.iql_optimizer:
            logger.info("Training IQL optimizer...")
            iql_stats = self.iql_optimizer.train(
                dataset=self.current_dataset,
                epochs=1,  # Single epoch
                batch_size=self.config.batch_size,
                validation_split=self.config.validation_split
            )
            results["iql"] = {
                "q_loss": iql_stats["q_losses"][-1] if iql_stats["q_losses"] else 0,
                "v_loss": iql_stats["v_losses"][-1] if iql_stats["v_losses"] else 0,
                "policy_loss": iql_stats["policy_losses"][-1] if iql_stats["policy_losses"] else 0
            }

        # Train CQL if enabled
        if self.cql_optimizer:
            logger.info("Training CQL optimizer...")
            cql_stats = self.cql_optimizer.train(
                dataset=self.current_dataset,
                epochs=1,  # Single epoch
                batch_size=self.config.batch_size,
                validation_split=self.config.validation_split
            )
            results["cql"] = {
                "q_loss": cql_stats["q_losses"][-1] if cql_stats["q_losses"] else 0,
                "cql_penalty": cql_stats["cql_penalties"][-1] if cql_stats["cql_penalties"] else 0,
                "policy_loss": cql_stats["policy_losses"][-1] if cql_stats["policy_losses"] else 0
            }

        training_time = (datetime.utcnow() - start_time).total_seconds()
        self.episodes_trained += 1

        results["metadata"] = {
            "episode": self.episodes_trained,
            "dataset_size": len(self.current_dataset),
            "training_time": training_time,
            "timestamp": datetime.utcnow().isoformat()
        }

        logger.info(f"Completed training epoch {self.episodes_trained} in {training_time:.2f}s")
        return results

    def evaluate_models(
        self,
        test_states: Optional[np.ndarray] = None,
        test_actions: Optional[np.ndarray] = None,
        test_rewards: Optional[np.ndarray] = None
    ) -> Dict[str, Dict[str, float]]:
        """Evaluate trained models."""
        if test_states is None:
            # Use validation split from current dataset
            val_size = int(len(self.current_dataset) * self.config.validation_split)
            test_states, test_actions, test_rewards, _, _, _ = self.current_dataset.sample_batch(val_size)

        results = {}

        # Evaluate IQL
        if self.iql_optimizer:
            iql_performance = self.iql_optimizer.evaluate_policy(test_states, test_actions, test_rewards)
            results["iql"] = iql_performance
            logger.info(f"IQL Evaluation - Accuracy: {iql_performance['action_accuracy']:.3f}, "
                       f"Return: {iql_performance['average_return']:.3f}")

        # Evaluate CQL
        if self.cql_optimizer:
            cql_performance = self.cql_optimizer.evaluate_policy(test_states, test_actions, test_rewards)
            results["cql"] = cql_performance
            logger.info(f"CQL Evaluation - Accuracy: {cql_performance['action_accuracy']:.3f}, "
                       f"Return: {cql_performance['average_return']:.3f}, "
                       f"Conservative Penalty: {cql_performance['conservative_penalty']:.3f}")

        return results

    def run_training_loop(
        self,
        max_epochs: Optional[int] = None,
        early_stopping_patience: int = 20,
        performance_threshold: float = 0.8
    ) -> List[TrainingMetrics]:
        """Run the complete training loop."""
        max_epochs = max_epochs or self.config.epochs
        early_stopping_counter = 0
        training_metrics = []

        logger.info(f"Starting RL training loop for {max_epochs} epochs")

        for epoch in range(max_epochs):
            # Update dataset periodically
            if epoch % 10 == 0:
                dataset_size = self.update_dataset()
                if dataset_size == 0:
                    logger.warning(f"No training data available at epoch {epoch}")
                    continue

            # Train for one epoch
            train_results = self.train_epoch()
            if not train_results:
                continue

            # Evaluate periodically
            eval_results = {}
            if epoch % self.config.eval_frequency == 0:
                eval_results = self.evaluate_models()

                # Check for improvement
                current_performance = self._calculate_overall_performance(eval_results)

                if current_performance > self.best_performance:
                    self.best_performance = current_performance
                    early_stopping_counter = 0

                    # Save best models
                    self.save_models(f"best_epoch_{epoch}")
                    logger.info(f"New best performance: {current_performance:.3f} at epoch {epoch}")
                else:
                    early_stopping_counter += 1

            # Create training metrics
            metrics = TrainingMetrics(
                episode=epoch,
                timestamp=datetime.utcnow(),
                train_loss=self._extract_train_loss(train_results),
                eval_performance=eval_results,
                dataset_size=len(self.current_dataset),
                training_time=train_results.get("metadata", {}).get("training_time", 0)
            )

            training_metrics.append(metrics)
            self.training_history.append(metrics)

            # Save checkpoints
            if epoch % self.config.save_frequency == 0:
                checkpoint_path = self.save_models(f"checkpoint_epoch_{epoch}")
                metrics.model_path = checkpoint_path

            # Early stopping
            if early_stopping_counter >= early_stopping_patience:
                logger.info(f"Early stopping at epoch {epoch} (no improvement for {early_stopping_patience} epochs)")
                break

            # Performance threshold check
            if self.best_performance >= performance_threshold:
                logger.info(f"Reached performance threshold {performance_threshold} at epoch {epoch}")
                break

        logger.info(f"Training completed. Best performance: {self.best_performance:.3f}")
        return training_metrics

    def select_action(
        self,
        state: np.ndarray,
        algorithm: str = "auto",
        deterministic: bool = False
    ) -> Tuple[int, Dict[str, Any]]:
        """Select action using trained models.

        Args:
            state: Current state
            algorithm: Which algorithm to use ("iql", "cql", "auto")
            deterministic: Whether to select deterministically

        Returns:
            Selected action and additional info
        """
        if algorithm == "auto":
            # Choose best performing algorithm
            algorithm = self._get_best_algorithm()

        info = {"algorithm_used": algorithm}

        if algorithm == "iql" and self.iql_optimizer:
            action, iql_info = self.iql_optimizer.select_action(
                state, deterministic=deterministic, return_info=True
            )
            if iql_info:
                info.update(iql_info)

        elif algorithm == "cql" and self.cql_optimizer:
            action, cql_info = self.cql_optimizer.select_action(
                state, deterministic=deterministic, return_info=True
            )
            if cql_info:
                info.update(cql_info)

        else:
            # Fallback to random action
            action = np.random.choice(self.config.action_dim)
            info["fallback"] = "random_action"

        return action, info

    def save_models(self, name: str) -> str:
        """Save trained models and metadata."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(self.config.checkpoint_dir, f"{name}_{timestamp}")

        # Save models
        if self.iql_optimizer:
            self.iql_optimizer.save(f"{save_path}_iql")

        if self.cql_optimizer:
            self.cql_optimizer.save(f"{save_path}_cql")

        # Save training metadata
        metadata = {
            "config": asdict(self.config),
            "training_history": [asdict(m) for m in self.training_history],
            "best_performance": self.best_performance,
            "episodes_trained": self.episodes_trained,
            "dataset_stats": self.current_dataset.get_statistics()
        }

        with open(f"{save_path}_metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info(f"Saved models and metadata to {save_path}")
        return save_path

    def load_models(self, save_path: str) -> None:
        """Load trained models and metadata."""
        # Load metadata
        with open(f"{save_path}_metadata.json", 'r') as f:
            metadata = json.load(f)

        self.best_performance = metadata["best_performance"]
        self.episodes_trained = metadata["episodes_trained"]

        # Load models
        if self.iql_optimizer:
            try:
                self.iql_optimizer.load(f"{save_path}_iql")
                logger.info("Loaded IQL model")
            except FileNotFoundError:
                logger.warning("IQL model file not found")

        if self.cql_optimizer:
            try:
                self.cql_optimizer.load(f"{save_path}_cql")
                logger.info("Loaded CQL model")
            except FileNotFoundError:
                logger.warning("CQL model file not found")

        logger.info(f"Loaded models from {save_path}")

    def get_training_summary(self) -> Dict[str, Any]:
        """Get comprehensive training summary."""
        if not self.training_history:
            return {"message": "No training history available"}

        recent_metrics = self.training_history[-10:] if len(self.training_history) >= 10 else self.training_history

        summary = {
            "total_epochs": len(self.training_history),
            "best_performance": self.best_performance,
            "current_dataset_size": len(self.current_dataset),
            "recent_avg_loss": np.mean([m.train_loss for m in recent_metrics]),
            "training_time_total": sum(m.training_time for m in self.training_history),
            "algorithms_enabled": [],
            "dataset_statistics": self.current_dataset.get_statistics()
        }

        if self.iql_optimizer:
            summary["algorithms_enabled"].append("IQL")

        if self.cql_optimizer:
            summary["algorithms_enabled"].append("CQL")

        # Performance trend
        if len(self.training_history) >= 5:
            recent_performances = [
                self._calculate_overall_performance(m.eval_performance)
                for m in self.training_history[-5:] if m.eval_performance
            ]

            if recent_performances:
                summary["recent_performance_trend"] = {
                    "mean": float(np.mean(recent_performances)),
                    "std": float(np.std(recent_performances)),
                    "improving": recent_performances[-1] > recent_performances[0] if len(recent_performances) > 1 else False
                }

        return summary

    def optimize_hyperparameters(
        self,
        param_ranges: Dict[str, Tuple[float, float]],
        num_trials: int = 20,
        trial_epochs: int = 10
    ) -> Dict[str, Any]:
        """Optimize hyperparameters using random search."""
        logger.info(f"Starting hyperparameter optimization with {num_trials} trials")

        best_params = {}
        best_score = float('-inf')
        trial_results = []

        original_config = asdict(self.config)

        for trial in range(num_trials):
            logger.info(f"Hyperparameter trial {trial + 1}/{num_trials}")

            # Sample random parameters
            trial_params = {}
            for param_name, (min_val, max_val) in param_ranges.items():
                trial_params[param_name] = np.random.uniform(min_val, max_val)

            # Update config
            for param_name, value in trial_params.items():
                if hasattr(self.config, param_name):
                    setattr(self.config, param_name, value)

            # Recreate optimizers with new parameters
            self._recreate_optimizers()

            # Run short training
            trial_metrics = []
            for epoch in range(trial_epochs):
                if epoch % 5 == 0:
                    self.update_dataset()

                train_results = self.train_epoch()
                if not train_results:
                    continue

                if epoch == trial_epochs - 1:  # Evaluate on last epoch
                    eval_results = self.evaluate_models()
                    score = self._calculate_overall_performance(eval_results)
                    trial_metrics.append(score)

            # Calculate trial score
            trial_score = np.mean(trial_metrics) if trial_metrics else 0

            trial_results.append({
                "trial": trial,
                "params": trial_params.copy(),
                "score": trial_score
            })

            if trial_score > best_score:
                best_score = trial_score
                best_params = trial_params.copy()
                logger.info(f"New best hyperparameters (score: {best_score:.3f}): {best_params}")

        # Restore original config and apply best parameters
        for param_name, value in original_config.items():
            if hasattr(self.config, param_name):
                setattr(self.config, param_name, value)

        for param_name, value in best_params.items():
            if hasattr(self.config, param_name):
                setattr(self.config, param_name, value)

        self._recreate_optimizers()

        logger.info(f"Hyperparameter optimization completed. Best score: {best_score:.3f}")

        return {
            "best_params": best_params,
            "best_score": best_score,
            "all_trials": trial_results,
            "improvement": best_score - trial_results[0]["score"] if trial_results else 0
        }

    # Private methods

    def _recreate_optimizers(self) -> None:
        """Recreate optimizers with current config."""
        if self.config.mode in [TrainingMode.IQL, TrainingMode.BOTH]:
            self.iql_optimizer = IQLOptimizer(
                state_dim=self.config.state_dim,
                action_dim=self.config.action_dim,
                expectile=self.config.iql_expectile,
                temperature=self.config.iql_temperature,
                learning_rate=self.config.learning_rate,
                discount=self.config.discount
            )

        if self.config.mode in [TrainingMode.CQL, TrainingMode.BOTH]:
            self.cql_optimizer = CQLOptimizer(
                state_dim=self.config.state_dim,
                action_dim=self.config.action_dim,
                alpha=self.config.cql_alpha,
                learning_rate=self.config.learning_rate,
                discount=self.config.discount,
                tau=self.config.cql_tau,
                use_ensemble=self.config.use_ensemble
            )

    def _get_recent_performance_data(self) -> List[Dict]:
        """Get recent performance data for reward model updates."""
        # This would integrate with the reward tracker to get recent task performance
        # For now, return empty list
        return []

    def _calculate_overall_performance(self, eval_results: Dict[str, Dict[str, float]]) -> float:
        """Calculate overall performance score from evaluation results."""
        if not eval_results:
            return 0.0

        scores = []

        for algorithm, metrics in eval_results.items():
            if "action_accuracy" in metrics:
                scores.append(metrics["action_accuracy"])
            if "average_return" in metrics:
                scores.append(metrics["average_return"] / 10.0)  # Normalize return

        return np.mean(scores) if scores else 0.0

    def _extract_train_loss(self, train_results: Dict) -> float:
        """Extract representative training loss from results."""
        losses = []

        if "iql" in train_results:
            losses.append(train_results["iql"].get("q_loss", 0))

        if "cql" in train_results:
            losses.append(train_results["cql"].get("q_loss", 0))

        return np.mean(losses) if losses else 0.0

    def _get_best_algorithm(self) -> str:
        """Determine which algorithm is performing better."""
        if not self.training_history:
            return "iql" if self.iql_optimizer else "cql"

        # Look at recent evaluation results
        recent_evals = [m.eval_performance for m in self.training_history[-5:] if m.eval_performance]

        if not recent_evals:
            return "iql" if self.iql_optimizer else "cql"

        iql_scores = []
        cql_scores = []

        for eval_result in recent_evals:
            if "iql" in eval_result:
                iql_scores.append(eval_result["iql"].get("action_accuracy", 0))
            if "cql" in eval_result:
                cql_scores.append(eval_result["cql"].get("action_accuracy", 0))

        iql_avg = np.mean(iql_scores) if iql_scores else 0
        cql_avg = np.mean(cql_scores) if cql_scores else 0

        return "iql" if iql_avg >= cql_avg else "cql"