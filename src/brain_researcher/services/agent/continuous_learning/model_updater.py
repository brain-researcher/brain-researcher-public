"""Model updater for incremental learning and adaptation."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json
from collections import deque

logger = logging.getLogger(__name__)


class UpdateStrategy(Enum):
    INCREMENTAL = "incremental"
    BATCH = "batch"
    EPISODIC = "episodic"
    ADAPTIVE = "adaptive"


class UpdateTrigger(Enum):
    TIME_BASED = "time_based"
    PERFORMANCE_BASED = "performance_based"
    DATA_BASED = "data_based"
    DRIFT_BASED = "drift_based"
    MANUAL = "manual"


@dataclass
class UpdateResult:
    """Result of model update operation."""
    success: bool
    update_type: UpdateStrategy
    performance_change: float
    update_time: datetime
    metadata: Dict[str, Any]
    error_message: Optional[str] = None


@dataclass
class UpdateConfig:
    """Configuration for model updates."""
    strategy: UpdateStrategy
    trigger: UpdateTrigger
    update_frequency: timedelta
    batch_size: int
    learning_rate: float
    performance_threshold: float
    max_updates_per_hour: int = 10
    validation_split: float = 0.2


class ModelUpdater:
    """Base class for model updating strategies."""

    def __init__(
        self,
        model: Any,
        config: UpdateConfig,
        performance_metric: Callable[[Any, Any], float]
    ):
        self.model = model
        self.config = config
        self.performance_metric = performance_metric

        # Update tracking
        self.update_history = []
        self.last_update = None
        self.updates_this_hour = 0
        self.last_hour_reset = datetime.utcnow()

        # Performance tracking
        self.performance_history = deque(maxlen=1000)
        self.baseline_performance = None

        # Data buffers
        self.training_buffer = deque(maxlen=10000)
        self.validation_buffer = deque(maxlen=2000)

        # Statistics
        self.total_updates = 0
        self.successful_updates = 0
        self.performance_improvements = 0

        logger.info(f"Initialized ModelUpdater with {config.strategy.value} strategy")

    def add_training_data(
        self,
        features: Any,
        labels: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Add new training data to buffer."""
        sample = {
            "features": features,
            "labels": labels,
            "timestamp": datetime.utcnow(),
            "metadata": metadata or {}
        }

        self.training_buffer.append(sample)

        # Trigger update if conditions are met
        if self._should_trigger_update():
            self.trigger_update()

    def add_performance_measurement(self, performance: float) -> None:
        """Add performance measurement for monitoring."""
        self.performance_history.append({
            "value": performance,
            "timestamp": datetime.utcnow()
        })

        # Set baseline if first measurement
        if self.baseline_performance is None:
            self.baseline_performance = performance

        # Trigger update if performance drops significantly
        if (self.config.trigger == UpdateTrigger.PERFORMANCE_BASED and
            performance < self.baseline_performance - self.config.performance_threshold):
            logger.info(f"Performance dropped to {performance:.3f}, triggering update")
            self.trigger_update()

    def trigger_update(self, force: bool = False) -> UpdateResult:
        """Trigger model update."""
        # Check rate limiting
        if not force and not self._check_rate_limit():
            return UpdateResult(
                success=False,
                update_type=self.config.strategy,
                performance_change=0.0,
                update_time=datetime.utcnow(),
                metadata={"reason": "rate_limited"},
                error_message="Update rate limit exceeded"
            )

        # Check if we have enough data
        if len(self.training_buffer) < self.config.batch_size:
            return UpdateResult(
                success=False,
                update_type=self.config.strategy,
                performance_change=0.0,
                update_time=datetime.utcnow(),
                metadata={"reason": "insufficient_data", "buffer_size": len(self.training_buffer)},
                error_message="Insufficient training data"
            )

        try:
            # Perform update based on strategy
            if self.config.strategy == UpdateStrategy.INCREMENTAL:
                result = self._incremental_update()
            elif self.config.strategy == UpdateStrategy.BATCH:
                result = self._batch_update()
            elif self.config.strategy == UpdateStrategy.EPISODIC:
                result = self._episodic_update()
            elif self.config.strategy == UpdateStrategy.ADAPTIVE:
                result = self._adaptive_update()
            else:
                raise ValueError(f"Unknown update strategy: {self.config.strategy}")

            # Track update
            self.update_history.append(result)
            self.last_update = result.update_time
            self.total_updates += 1

            if result.success:
                self.successful_updates += 1
                if result.performance_change > 0:
                    self.performance_improvements += 1

            # Update rate limiting
            self._update_rate_limit()

            logger.info(f"Model update completed: {result.success}, "
                       f"performance change: {result.performance_change:.4f}")

            return result

        except Exception as e:
            error_result = UpdateResult(
                success=False,
                update_type=self.config.strategy,
                performance_change=0.0,
                update_time=datetime.utcnow(),
                metadata={"error": str(e)},
                error_message=str(e)
            )

            self.update_history.append(error_result)
            logger.error(f"Model update failed: {e}")

            return error_result

    def _incremental_update(self) -> UpdateResult:
        """Perform incremental model update."""
        # Get recent samples
        recent_samples = list(self.training_buffer)[-self.config.batch_size:]

        # Measure pre-update performance
        pre_performance = self._evaluate_model()

        # Update model incrementally
        for sample in recent_samples:
            self._update_model_single_sample(
                sample["features"],
                sample["labels"],
                learning_rate=self.config.learning_rate
            )

        # Measure post-update performance
        post_performance = self._evaluate_model()
        performance_change = post_performance - pre_performance

        return UpdateResult(
            success=True,
            update_type=UpdateStrategy.INCREMENTAL,
            performance_change=performance_change,
            update_time=datetime.utcnow(),
            metadata={
                "samples_used": len(recent_samples),
                "pre_performance": pre_performance,
                "post_performance": post_performance,
                "learning_rate": self.config.learning_rate
            }
        )

    def _batch_update(self) -> UpdateResult:
        """Perform batch model update."""
        # Prepare training data
        all_samples = list(self.training_buffer)

        # Split into train/validation
        split_idx = int(len(all_samples) * (1 - self.config.validation_split))
        train_samples = all_samples[:split_idx]
        val_samples = all_samples[split_idx:]

        # Measure pre-update performance
        pre_performance = self._evaluate_model(val_samples)

        # Prepare batch data
        train_features = [s["features"] for s in train_samples]
        train_labels = [s["labels"] for s in train_samples]

        # Update model with batch
        self._update_model_batch(train_features, train_labels)

        # Measure post-update performance
        post_performance = self._evaluate_model(val_samples)
        performance_change = post_performance - pre_performance

        return UpdateResult(
            success=True,
            update_type=UpdateStrategy.BATCH,
            performance_change=performance_change,
            update_time=datetime.utcnow(),
            metadata={
                "train_samples": len(train_samples),
                "val_samples": len(val_samples),
                "pre_performance": pre_performance,
                "post_performance": post_performance
            }
        )

    def _episodic_update(self) -> UpdateResult:
        """Perform episodic model update."""
        # Group samples by episodes (if available)
        episodes = self._group_samples_by_episode()

        if not episodes:
            # Fallback to batch update
            return self._batch_update()

        # Measure pre-update performance
        pre_performance = self._evaluate_model()

        # Update with complete episodes
        total_samples = 0
        for episode in episodes:
            episode_features = [s["features"] for s in episode]
            episode_labels = [s["labels"] for s in episode]
            self._update_model_batch(episode_features, episode_labels)
            total_samples += len(episode)

        # Measure post-update performance
        post_performance = self._evaluate_model()
        performance_change = post_performance - pre_performance

        return UpdateResult(
            success=True,
            update_type=UpdateStrategy.EPISODIC,
            performance_change=performance_change,
            update_time=datetime.utcnow(),
            metadata={
                "episodes_used": len(episodes),
                "total_samples": total_samples,
                "pre_performance": pre_performance,
                "post_performance": post_performance
            }
        )

    def _adaptive_update(self) -> UpdateResult:
        """Perform adaptive model update based on current conditions."""
        # Analyze current performance trend
        recent_performance = [p["value"] for p in list(self.performance_history)[-10:]]

        if len(recent_performance) < 3:
            # Not enough data, use incremental
            return self._incremental_update()

        # Check performance trend
        performance_trend = np.polyfit(range(len(recent_performance)), recent_performance, 1)[0]

        if performance_trend < -0.01:  # Declining performance
            # Use batch update for significant improvement
            logger.info("Performance declining, using batch update")
            return self._batch_update()
        elif performance_trend > 0.005:  # Improving performance
            # Use incremental to maintain progress
            logger.info("Performance improving, using incremental update")
            return self._incremental_update()
        else:
            # Stable performance, use episodic for exploration
            logger.info("Performance stable, using episodic update")
            return self._episodic_update()

    def _should_trigger_update(self) -> bool:
        """Check if update should be triggered."""
        if self.config.trigger == UpdateTrigger.MANUAL:
            return False

        now = datetime.utcnow()

        if self.config.trigger == UpdateTrigger.TIME_BASED:
            if self.last_update is None:
                return True
            return (now - self.last_update) >= self.config.update_frequency

        elif self.config.trigger == UpdateTrigger.DATA_BASED:
            return len(self.training_buffer) >= self.config.batch_size * 2

        elif self.config.trigger == UpdateTrigger.PERFORMANCE_BASED:
            # Handled in add_performance_measurement
            return False

        elif self.config.trigger == UpdateTrigger.DRIFT_BASED:
            # Would be triggered externally by drift detector
            return False

        return False

    def _check_rate_limit(self) -> bool:
        """Check if update is within rate limits."""
        now = datetime.utcnow()

        # Reset hourly counter
        if (now - self.last_hour_reset).total_seconds() >= 3600:
            self.updates_this_hour = 0
            self.last_hour_reset = now

        return self.updates_this_hour < self.config.max_updates_per_hour

    def _update_rate_limit(self) -> None:
        """Update rate limiting counters."""
        self.updates_this_hour += 1

    def _evaluate_model(self, validation_data: Optional[List[Dict]] = None) -> float:
        """Evaluate model performance."""
        if validation_data is None:
            # Use validation buffer
            if not self.validation_buffer:
                # Use recent training data as proxy
                validation_data = list(self.training_buffer)[-100:]
            else:
                validation_data = list(self.validation_buffer)

        if not validation_data:
            return 0.0

        # Calculate performance metric
        total_performance = 0.0
        count = 0

        for sample in validation_data:
            try:
                prediction = self._predict_sample(sample["features"])
                performance = self.performance_metric(prediction, sample["labels"])
                total_performance += performance
                count += 1
            except Exception as e:
                logger.warning(f"Error evaluating sample: {e}")
                continue

        return total_performance / max(1, count)

    def _predict_sample(self, features: Any) -> Any:
        """Make prediction for a single sample."""
        # This would be implemented by subclass or use model.predict()
        if hasattr(self.model, 'predict'):
            return self.model.predict(features)
        else:
            raise NotImplementedError("Model prediction method not available")

    def _update_model_single_sample(
        self,
        features: Any,
        labels: Any,
        learning_rate: float
    ) -> None:
        """Update model with single sample."""
        # This would be implemented by subclass
        if hasattr(self.model, 'partial_fit'):
            self.model.partial_fit(features, labels)
        elif hasattr(self.model, 'fit'):
            # Fallback for models without incremental learning
            self.model.fit(features, labels)
        else:
            raise NotImplementedError("Model update method not available")

    def _update_model_batch(self, features: List[Any], labels: List[Any]) -> None:
        """Update model with batch of data."""
        # This would be implemented by subclass
        if hasattr(self.model, 'fit'):
            self.model.fit(features, labels)
        else:
            raise NotImplementedError("Model batch update method not available")

    def _group_samples_by_episode(self) -> List[List[Dict]]:
        """Group samples by episode (if metadata contains episode info)."""
        episodes = {}

        for sample in self.training_buffer:
            episode_id = sample["metadata"].get("episode_id")
            if episode_id is not None:
                if episode_id not in episodes:
                    episodes[episode_id] = []
                episodes[episode_id].append(sample)

        # Return episodes with sufficient samples
        return [episode for episode in episodes.values() if len(episode) >= 5]

    def get_statistics(self) -> Dict[str, Any]:
        """Get updater statistics."""
        recent_updates = [
            u for u in self.update_history
            if (datetime.utcnow() - u.update_time).days < 7
        ]

        recent_performance_changes = [
            u.performance_change for u in recent_updates if u.success
        ]

        stats = {
            "total_updates": self.total_updates,
            "successful_updates": self.successful_updates,
            "success_rate": self.successful_updates / max(1, self.total_updates),
            "performance_improvements": self.performance_improvements,
            "improvement_rate": self.performance_improvements / max(1, self.successful_updates),
            "updates_this_hour": self.updates_this_hour,
            "training_buffer_size": len(self.training_buffer),
            "validation_buffer_size": len(self.validation_buffer),
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "baseline_performance": self.baseline_performance,
            "current_performance": self._evaluate_model(),
            "recent_updates": len(recent_updates),
            "recent_avg_performance_change": float(np.mean(recent_performance_changes)) if recent_performance_changes else 0.0,
            "config": {
                "strategy": self.config.strategy.value,
                "trigger": self.config.trigger.value,
                "batch_size": self.config.batch_size,
                "learning_rate": self.config.learning_rate
            }
        }

        return stats

    def reset(self) -> None:
        """Reset updater state."""
        self.training_buffer.clear()
        self.validation_buffer.clear()
        self.performance_history.clear()
        self.update_history = []
        self.last_update = None
        self.baseline_performance = None
        self.total_updates = 0
        self.successful_updates = 0
        self.performance_improvements = 0

        logger.info("Reset model updater state")


class IncrementalModelUpdater(ModelUpdater):
    """Specialized updater for incremental learning models."""

    def __init__(
        self,
        model: Any,
        performance_metric: Callable[[Any, Any], float],
        learning_rate: float = 0.01,
        update_frequency: timedelta = timedelta(minutes=15),
        batch_size: int = 32
    ):
        config = UpdateConfig(
            strategy=UpdateStrategy.INCREMENTAL,
            trigger=UpdateTrigger.TIME_BASED,
            update_frequency=update_frequency,
            batch_size=batch_size,
            learning_rate=learning_rate,
            performance_threshold=0.05,
            validation_split=0.1
        )

        super().__init__(model, config, performance_metric)

        # Incremental-specific parameters
        self.momentum = 0.9
        self.adaptive_lr = True
        self.lr_decay = 0.95
        self.min_lr = 0.001

        # Moving averages for adaptive learning rate
        self.performance_ma = None
        self.lr_adjustment_history = deque(maxlen=20)

    def _incremental_update(self) -> UpdateResult:
        """Enhanced incremental update with adaptive learning rate."""
        # Get recent samples
        recent_samples = list(self.training_buffer)[-self.config.batch_size:]

        # Measure pre-update performance
        pre_performance = self._evaluate_model()

        # Adjust learning rate adaptively
        if self.adaptive_lr:
            self._adjust_learning_rate(pre_performance)

        # Update model incrementally with momentum
        for sample in recent_samples:
            self._incremental_update_with_momentum(
                sample["features"],
                sample["labels"]
            )

        # Measure post-update performance
        post_performance = self._evaluate_model()
        performance_change = post_performance - pre_performance

        # Track performance change for learning rate adaptation
        self.lr_adjustment_history.append(performance_change)

        return UpdateResult(
            success=True,
            update_type=UpdateStrategy.INCREMENTAL,
            performance_change=performance_change,
            update_time=datetime.utcnow(),
            metadata={
                "samples_used": len(recent_samples),
                "pre_performance": pre_performance,
                "post_performance": post_performance,
                "learning_rate": self.config.learning_rate,
                "adaptive_lr_used": self.adaptive_lr,
                "momentum": self.momentum
            }
        )

    def _adjust_learning_rate(self, current_performance: float) -> None:
        """Adjust learning rate based on performance trend."""
        if self.performance_ma is None:
            self.performance_ma = current_performance
            return

        # Update moving average
        alpha = 0.1
        self.performance_ma = alpha * current_performance + (1 - alpha) * self.performance_ma

        # Check recent performance changes
        if len(self.lr_adjustment_history) >= 3:
            recent_changes = list(self.lr_adjustment_history)[-3:]

            if all(change < 0 for change in recent_changes):
                # Performance declining, reduce learning rate
                self.config.learning_rate *= self.lr_decay
                self.config.learning_rate = max(self.min_lr, self.config.learning_rate)
                logger.debug(f"Reduced learning rate to {self.config.learning_rate:.6f}")

            elif all(change > 0 for change in recent_changes):
                # Performance improving, slightly increase learning rate
                self.config.learning_rate *= 1.05
                self.config.learning_rate = min(0.1, self.config.learning_rate)
                logger.debug(f"Increased learning rate to {self.config.learning_rate:.6f}")

    def _incremental_update_with_momentum(self, features: Any, labels: Any) -> None:
        """Update model with momentum (if supported)."""
        # This would need to be implemented based on specific model type
        # For now, fall back to standard update
        self._update_model_single_sample(features, labels, self.config.learning_rate)


class EnsembleModelUpdater(ModelUpdater):
    """Updater for ensemble models with member-specific updates."""

    def __init__(
        self,
        ensemble_models: List[Any],
        performance_metric: Callable[[Any, Any], float],
        member_weights: Optional[List[float]] = None,
        diversity_bonus: float = 0.1
    ):
        # Use adaptive strategy for ensembles
        config = UpdateConfig(
            strategy=UpdateStrategy.ADAPTIVE,
            trigger=UpdateTrigger.DATA_BASED,
            update_frequency=timedelta(hours=1),
            batch_size=100,
            learning_rate=0.01,
            performance_threshold=0.02,
            validation_split=0.2
        )

        # Use first model as representative
        super().__init__(ensemble_models[0], config, performance_metric)

        self.ensemble_models = ensemble_models
        self.member_weights = member_weights or [1.0] * len(ensemble_models)
        self.diversity_bonus = diversity_bonus

        # Member-specific statistics
        self.member_performance = [0.0] * len(ensemble_models)
        self.member_update_counts = [0] * len(ensemble_models)

    def trigger_update(self, force: bool = False) -> UpdateResult:
        """Update ensemble members with different strategies."""
        if not force and not self._check_rate_limit():
            return UpdateResult(
                success=False,
                update_type=self.config.strategy,
                performance_change=0.0,
                update_time=datetime.utcnow(),
                metadata={"reason": "rate_limited"},
                error_message="Update rate limit exceeded"
            )

        try:
            # Measure pre-update ensemble performance
            pre_performance = self._evaluate_ensemble()

            # Update each ensemble member
            member_results = []
            for i, model in enumerate(self.ensemble_models):
                member_result = self._update_ensemble_member(i, model)
                member_results.append(member_result)

            # Measure post-update ensemble performance
            post_performance = self._evaluate_ensemble()
            performance_change = post_performance - pre_performance

            # Update member weights based on individual performance
            self._update_member_weights()

            result = UpdateResult(
                success=True,
                update_type=UpdateStrategy.ADAPTIVE,
                performance_change=performance_change,
                update_time=datetime.utcnow(),
                metadata={
                    "ensemble_size": len(self.ensemble_models),
                    "pre_performance": pre_performance,
                    "post_performance": post_performance,
                    "member_results": [asdict(r) for r in member_results],
                    "member_weights": self.member_weights.copy(),
                    "diversity_score": self._calculate_diversity()
                }
            )

            # Track update
            self.update_history.append(result)
            self.last_update = result.update_time
            self.total_updates += 1
            self.successful_updates += 1
            if performance_change > 0:
                self.performance_improvements += 1

            self._update_rate_limit()

            logger.info(f"Ensemble update completed: performance change: {performance_change:.4f}")
            return result

        except Exception as e:
            error_result = UpdateResult(
                success=False,
                update_type=UpdateStrategy.ADAPTIVE,
                performance_change=0.0,
                update_time=datetime.utcnow(),
                metadata={"error": str(e)},
                error_message=str(e)
            )

            self.update_history.append(error_result)
            logger.error(f"Ensemble update failed: {e}")
            return error_result

    def _update_ensemble_member(self, member_index: int, model: Any) -> UpdateResult:
        """Update individual ensemble member."""
        # Use different data subsets for diversity
        all_samples = list(self.training_buffer)

        # Bootstrap sampling for this member
        np.random.seed(member_index)  # Ensure different sampling per member
        member_samples = np.random.choice(
            len(all_samples),
            size=min(self.config.batch_size, len(all_samples)),
            replace=True
        )

        # Get subset for this member
        member_data = [all_samples[i] for i in member_samples]

        # Measure member performance before update
        pre_perf = self._evaluate_member(member_index, member_data)

        # Update member
        features = [s["features"] for s in member_data]
        labels = [s["labels"] for s in member_data]

        if hasattr(model, 'fit'):
            model.fit(features, labels)

        # Measure member performance after update
        post_perf = self._evaluate_member(member_index, member_data)

        # Track member statistics
        self.member_performance[member_index] = post_perf
        self.member_update_counts[member_index] += 1

        return UpdateResult(
            success=True,
            update_type=UpdateStrategy.BATCH,
            performance_change=post_perf - pre_perf,
            update_time=datetime.utcnow(),
            metadata={
                "member_index": member_index,
                "samples_used": len(member_data),
                "pre_performance": pre_perf,
                "post_performance": post_perf
            }
        )

    def _evaluate_ensemble(self, validation_data: Optional[List[Dict]] = None) -> float:
        """Evaluate ensemble performance."""
        if validation_data is None:
            validation_data = list(self.training_buffer)[-100:]

        if not validation_data:
            return 0.0

        total_performance = 0.0
        count = 0

        for sample in validation_data:
            try:
                # Get predictions from all members
                predictions = []
                for i, model in enumerate(self.ensemble_models):
                    if hasattr(model, 'predict'):
                        pred = model.predict(sample["features"])
                        predictions.append(pred)

                if predictions:
                    # Weighted average prediction
                    ensemble_pred = np.average(predictions, weights=self.member_weights)
                    performance = self.performance_metric(ensemble_pred, sample["labels"])
                    total_performance += performance
                    count += 1

            except Exception as e:
                logger.warning(f"Error evaluating ensemble sample: {e}")
                continue

        return total_performance / max(1, count)

    def _evaluate_member(self, member_index: int, data: List[Dict]) -> float:
        """Evaluate individual member performance."""
        model = self.ensemble_models[member_index]
        total_performance = 0.0
        count = 0

        for sample in data:
            try:
                if hasattr(model, 'predict'):
                    prediction = model.predict(sample["features"])
                    performance = self.performance_metric(prediction, sample["labels"])
                    total_performance += performance
                    count += 1
            except Exception as e:
                logger.warning(f"Error evaluating member {member_index}: {e}")
                continue

        return total_performance / max(1, count)

    def _update_member_weights(self) -> None:
        """Update ensemble member weights based on performance."""
        # Softmax weighting based on performance
        performances = np.array(self.member_performance)

        # Add diversity bonus
        diversity_scores = self._calculate_member_diversity()
        adjusted_scores = performances + self.diversity_bonus * diversity_scores

        # Softmax
        exp_scores = np.exp(adjusted_scores - np.max(adjusted_scores))
        self.member_weights = list(exp_scores / np.sum(exp_scores))

        logger.debug(f"Updated member weights: {self.member_weights}")

    def _calculate_diversity(self) -> float:
        """Calculate ensemble diversity score."""
        # Simple diversity measure based on prediction variance
        if not self.training_buffer:
            return 0.0

        sample_data = list(self.training_buffer)[-50:]  # Use recent samples
        prediction_variances = []

        for sample in sample_data:
            try:
                predictions = []
                for model in self.ensemble_models:
                    if hasattr(model, 'predict'):
                        pred = model.predict(sample["features"])
                        predictions.append(pred)

                if len(predictions) > 1:
                    variance = np.var(predictions)
                    prediction_variances.append(variance)

            except Exception:
                continue

        return float(np.mean(prediction_variances)) if prediction_variances else 0.0

    def _calculate_member_diversity(self) -> np.ndarray:
        """Calculate diversity contribution of each member."""
        # Simplified: higher performance variance = higher diversity contribution
        performances = np.array(self.member_performance)
        mean_perf = np.mean(performances)

        # Members farther from mean contribute more diversity
        diversity_contributions = np.abs(performances - mean_perf)

        # Normalize
        max_div = np.max(diversity_contributions) if np.max(diversity_contributions) > 0 else 1.0
        return diversity_contributions / max_div