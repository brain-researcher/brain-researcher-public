"""Experience replay buffers for continuous learning."""

import json
import logging
import random
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Single experience tuple for replay buffer."""

    state: dict[str, Any]
    action: str
    reward: float
    next_state: dict[str, Any] | None
    done: bool
    timestamp: datetime
    metadata: dict[str, Any]
    priority: float = 1.0
    importance_weight: float = 1.0


class SamplingStrategy(Enum):
    UNIFORM = "uniform"
    PRIORITIZED = "prioritized"
    RECENCY = "recency"
    TEMPORAL = "temporal"
    DIVERSITY = "diversity"


class ExperienceReplay:
    """Basic experience replay buffer for online learning."""

    def __init__(
        self,
        capacity: int = 10000,
        min_experiences: int = 100,
        sampling_strategy: SamplingStrategy = SamplingStrategy.UNIFORM,
    ):
        self.capacity = capacity
        self.min_experiences = min_experiences
        self.sampling_strategy = sampling_strategy

        self.buffer = deque(maxlen=capacity)
        self.position = 0

        # Statistics
        self.total_added = 0
        self.total_sampled = 0
        self.last_update = datetime.utcnow()

    def add(
        self,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any] | None = None,
        done: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: float = 1.0,
    ) -> None:
        """Add experience to the replay buffer."""
        experience = Experience(
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            done=done,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
            priority=priority,
        )

        self.buffer.append(experience)
        self.total_added += 1
        self.last_update = datetime.utcnow()

        logger.debug(
            f"Added experience to buffer (size: {len(self.buffer)}/{self.capacity})"
        )

    def sample(
        self, batch_size: int, strategy: SamplingStrategy | None = None
    ) -> list[Experience]:
        """Sample batch of experiences from buffer."""
        if len(self.buffer) < self.min_experiences:
            logger.warning(
                f"Buffer has insufficient experiences ({len(self.buffer)} < {self.min_experiences})"
            )
            return []

        strategy = strategy or self.sampling_strategy
        actual_batch_size = min(batch_size, len(self.buffer))

        if strategy == SamplingStrategy.UNIFORM:
            indices = np.random.choice(
                len(self.buffer), actual_batch_size, replace=False
            )
            batch = [self.buffer[i] for i in indices]

        elif strategy == SamplingStrategy.PRIORITIZED:
            batch = self._sample_prioritized(actual_batch_size)

        elif strategy == SamplingStrategy.RECENCY:
            # Sample more recent experiences with higher probability
            weights = self._calculate_recency_weights()
            indices = np.random.choice(
                len(self.buffer), actual_batch_size, replace=False, p=weights
            )
            batch = [self.buffer[i] for i in indices]

        elif strategy == SamplingStrategy.TEMPORAL:
            # Sample temporally diverse experiences
            batch = self._sample_temporal_diverse(actual_batch_size)

        elif strategy == SamplingStrategy.DIVERSITY:
            # Sample diverse experiences based on state similarity
            batch = self._sample_diverse(actual_batch_size)

        else:
            # Fallback to uniform
            indices = np.random.choice(
                len(self.buffer), actual_batch_size, replace=False
            )
            batch = [self.buffer[i] for i in indices]

        self.total_sampled += len(batch)
        return batch

    def update_priorities(
        self, experiences: list[Experience], priorities: list[float]
    ) -> None:
        """Update priorities of experiences (for prioritized replay)."""
        for experience, priority in zip(experiences, priorities, strict=False):
            experience.priority = priority

        logger.debug(f"Updated priorities for {len(experiences)} experiences")

    def get_statistics(self) -> dict[str, Any]:
        """Get buffer statistics."""
        if not self.buffer:
            return {"size": 0}

        rewards = [exp.reward for exp in self.buffer]
        priorities = [exp.priority for exp in self.buffer]

        # Time distribution
        now = datetime.utcnow()
        ages_hours = [
            (now - exp.timestamp).total_seconds() / 3600 for exp in self.buffer
        ]

        # Action distribution
        actions = [exp.action for exp in self.buffer]
        action_counts = {}
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1

        stats = {
            "size": len(self.buffer),
            "capacity": self.capacity,
            "total_added": self.total_added,
            "total_sampled": self.total_sampled,
            "reward_stats": {
                "mean": float(np.mean(rewards)),
                "std": float(np.std(rewards)),
                "min": float(np.min(rewards)),
                "max": float(np.max(rewards)),
            },
            "priority_stats": {
                "mean": float(np.mean(priorities)),
                "std": float(np.std(priorities)),
                "min": float(np.min(priorities)),
                "max": float(np.max(priorities)),
            },
            "age_stats": {
                "mean_hours": float(np.mean(ages_hours)),
                "max_hours": float(np.max(ages_hours)),
                "min_hours": float(np.min(ages_hours)),
            },
            "action_distribution": action_counts,
            "last_update": self.last_update.isoformat(),
        }

        return stats

    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer.clear()
        self.position = 0
        self.total_added = 0
        self.total_sampled = 0

        logger.info("Cleared experience replay buffer")

    def save(self, filepath: str) -> None:
        """Save buffer to file."""
        data = {
            "capacity": self.capacity,
            "min_experiences": self.min_experiences,
            "sampling_strategy": self.sampling_strategy.value,
            "total_added": self.total_added,
            "total_sampled": self.total_sampled,
            "experiences": [],
        }

        for exp in self.buffer:
            exp_data = asdict(exp)
            exp_data["timestamp"] = exp.timestamp.isoformat()
            data["experiences"].append(exp_data)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved experience buffer to {filepath}")

    def load(self, filepath: str) -> None:
        """Load buffer from file."""
        with open(filepath) as f:
            data = json.load(f)

        self.capacity = data["capacity"]
        self.min_experiences = data["min_experiences"]
        self.sampling_strategy = SamplingStrategy(data["sampling_strategy"])
        self.total_added = data["total_added"]
        self.total_sampled = data["total_sampled"]

        # Reconstruct buffer
        self.buffer = deque(maxlen=self.capacity)
        for exp_data in data["experiences"]:
            exp_data["timestamp"] = datetime.fromisoformat(exp_data["timestamp"])
            experience = Experience(**exp_data)
            self.buffer.append(experience)

        logger.info(f"Loaded experience buffer from {filepath}")

    def __len__(self) -> int:
        return len(self.buffer)

    # Private methods

    def _calculate_recency_weights(self) -> np.ndarray:
        """Calculate sampling weights based on recency."""
        if not self.buffer:
            return np.array([])

        now = datetime.utcnow()
        ages = [
            (now - exp.timestamp).total_seconds() / 3600 for exp in self.buffer
        ]  # hours

        # Exponential decay: more recent experiences have higher weight
        decay_rate = 0.1  # Decay per hour
        weights = np.exp(-decay_rate * np.array(ages))

        # Normalize
        weights = weights / np.sum(weights)

        return weights

    def _sample_prioritized(self, batch_size: int) -> list[Experience]:
        """Sample experiences based on priorities."""
        priorities = np.array([exp.priority for exp in self.buffer])

        # Avoid zero probabilities
        priorities = priorities + 1e-8
        probabilities = priorities / np.sum(priorities)

        indices = np.random.choice(
            len(self.buffer), batch_size, replace=False, p=probabilities
        )
        batch = [self.buffer[i] for i in indices]

        # Calculate importance weights for bias correction
        max_weight = (len(self.buffer) * np.min(probabilities)) ** -1
        for i, exp in enumerate(batch):
            prob = probabilities[indices[i]]
            exp.importance_weight = (len(self.buffer) * prob) ** -1 / max_weight

        return batch

    def _sample_temporal_diverse(self, batch_size: int) -> list[Experience]:
        """Sample temporally diverse experiences."""
        if len(self.buffer) <= batch_size:
            return list(self.buffer)

        # Sort by timestamp
        sorted_experiences = sorted(self.buffer, key=lambda x: x.timestamp)

        # Divide into time buckets and sample from each
        num_buckets = min(batch_size, 10)
        bucket_size = len(sorted_experiences) // num_buckets

        batch = []
        for i in range(num_buckets):
            start_idx = i * bucket_size
            end_idx = (
                start_idx + bucket_size
                if i < num_buckets - 1
                else len(sorted_experiences)
            )

            bucket = sorted_experiences[start_idx:end_idx]
            if bucket:
                samples_from_bucket = min(batch_size // num_buckets + 1, len(bucket))
                batch.extend(random.sample(bucket, samples_from_bucket))

        # If we need more samples, add random ones
        if len(batch) < batch_size:
            remaining = batch_size - len(batch)
            available = [exp for exp in self.buffer if exp not in batch]
            if available:
                batch.extend(random.sample(available, min(remaining, len(available))))

        return batch[:batch_size]

    def _sample_diverse(self, batch_size: int) -> list[Experience]:
        """Sample diverse experiences based on state similarity."""
        # Simple implementation: cluster by action and sample from each cluster
        action_groups = {}
        for exp in self.buffer:
            action = exp.action
            if action not in action_groups:
                action_groups[action] = []
            action_groups[action].append(exp)

        batch = []
        samples_per_action = max(1, batch_size // len(action_groups))

        for action, experiences in action_groups.items():
            sample_size = min(samples_per_action, len(experiences))
            batch.extend(random.sample(experiences, sample_size))

        # Fill remaining slots randomly
        if len(batch) < batch_size:
            remaining = batch_size - len(batch)
            available = [exp for exp in self.buffer if exp not in batch]
            if available:
                batch.extend(random.sample(available, min(remaining, len(available))))

        return batch[:batch_size]


class PrioritizedExperienceReplay(ExperienceReplay):
    """Prioritized Experience Replay with TD-error based sampling."""

    def __init__(
        self,
        capacity: int = 10000,
        alpha: float = 0.6,
        beta: float = 0.4,
        beta_increment: float = 0.001,
        epsilon: float = 1e-6,
    ):
        super().__init__(capacity, sampling_strategy=SamplingStrategy.PRIORITIZED)

        self.alpha = (
            alpha  # How much prioritization to use (0=uniform, 1=full prioritization)
        )
        self.beta = (
            beta  # Importance sampling weight (0=no correction, 1=full correction)
        )
        self.beta_increment = beta_increment
        self.epsilon = epsilon  # Small constant to avoid zero priorities

        # Priority storage - using a simple list for now
        # In production, would use a sum tree for O(log n) operations
        self.priorities = []
        self.max_priority = 1.0

    def add(
        self,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any] | None = None,
        done: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: float | None = None,
    ) -> None:
        """Add experience with priority."""
        if priority is None:
            priority = self.max_priority  # New experiences get max priority

        # Add to parent buffer
        super().add(state, action, reward, next_state, done, metadata, priority)

        # Update priorities list
        if len(self.priorities) >= self.capacity:
            self.priorities[self.position % self.capacity] = priority
        else:
            self.priorities.append(priority)

        self.max_priority = max(self.max_priority, priority)

    def sample(
        self, batch_size: int, **kwargs
    ) -> tuple[list[Experience], np.ndarray, np.ndarray]:
        """Sample batch with importance weights."""
        if len(self.buffer) < self.min_experiences:
            return [], np.array([]), np.array([])

        # Calculate sampling probabilities
        priorities = np.array(self.priorities[: len(self.buffer)]) + self.epsilon
        probabilities = priorities**self.alpha
        probabilities = probabilities / np.sum(probabilities)

        # Sample indices
        indices = np.random.choice(
            len(self.buffer), batch_size, replace=False, p=probabilities
        )

        # Get experiences
        batch = [self.buffer[i] for i in indices]

        # Calculate importance sampling weights
        max_weight = (len(self.buffer) * np.min(probabilities)) ** (-self.beta)
        weights = (len(self.buffer) * probabilities[indices]) ** (-self.beta)
        weights = weights / max_weight

        # Update beta
        self.beta = min(1.0, self.beta + self.beta_increment)

        self.total_sampled += len(batch)

        return batch, indices, weights

    def update_priorities(self, indices: np.ndarray, priorities: np.ndarray) -> None:
        """Update priorities for specific experiences."""
        for idx, priority in zip(indices, priorities, strict=False):
            if idx < len(self.priorities):
                self.priorities[idx] = priority + self.epsilon
                self.buffer[idx].priority = priority

        self.max_priority = max(self.max_priority, np.max(priorities))

        logger.debug(f"Updated {len(indices)} priorities")

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics including priority information."""
        stats = super().get_statistics()

        if self.priorities:
            stats.update(
                {
                    "alpha": self.alpha,
                    "beta": self.beta,
                    "max_priority": self.max_priority,
                    "priority_distribution": {
                        "mean": float(np.mean(self.priorities)),
                        "std": float(np.std(self.priorities)),
                        "min": float(np.min(self.priorities)),
                        "max": float(np.max(self.priorities)),
                    },
                }
            )

        return stats


class TemporalExperienceReplay(ExperienceReplay):
    """Experience replay that maintains temporal coherence."""

    def __init__(
        self,
        capacity: int = 10000,
        sequence_length: int = 5,
        overlap_ratio: float = 0.5,
    ):
        super().__init__(capacity, sampling_strategy=SamplingStrategy.TEMPORAL)

        self.sequence_length = sequence_length
        self.overlap_ratio = overlap_ratio

        # Group experiences by episode/session
        self.episodes = []
        self.current_episode = []

    def add(
        self,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any] | None = None,
        done: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: float = 1.0,
    ) -> None:
        """Add experience and manage episodes."""
        experience = Experience(
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            done=done,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
            priority=priority,
        )

        self.current_episode.append(experience)

        if done:
            # End of episode
            self.episodes.append(self.current_episode)
            self.current_episode = []

            # Maintain capacity
            while len(self.episodes) > self.capacity // self.sequence_length:
                self.episodes.pop(0)

        # Also add to regular buffer
        super().add(state, action, reward, next_state, done, metadata, priority)

    def sample_sequences(self, batch_size: int) -> list[list[Experience]]:
        """Sample sequences of experiences."""
        if not self.episodes:
            return []

        sequences = []

        for _ in range(batch_size):
            # Sample random episode
            episode = random.choice(self.episodes)

            if len(episode) >= self.sequence_length:
                # Sample random starting position
                start_idx = random.randint(0, len(episode) - self.sequence_length)
                sequence = episode[start_idx : start_idx + self.sequence_length]
            else:
                # Use entire episode if shorter than sequence_length
                sequence = episode

            sequences.append(sequence)

        return sequences

    def get_episode_statistics(self) -> dict[str, Any]:
        """Get episode-based statistics."""
        if not self.episodes:
            return {"num_episodes": 0}

        episode_lengths = [len(episode) for episode in self.episodes]
        episode_returns = []

        for episode in self.episodes:
            episode_return = sum(exp.reward for exp in episode)
            episode_returns.append(episode_return)

        stats = {
            "num_episodes": len(self.episodes),
            "current_episode_length": len(self.current_episode),
            "episode_length_stats": {
                "mean": float(np.mean(episode_lengths)),
                "std": float(np.std(episode_lengths)),
                "min": int(np.min(episode_lengths)),
                "max": int(np.max(episode_lengths)),
            },
            "episode_return_stats": {
                "mean": float(np.mean(episode_returns)),
                "std": float(np.std(episode_returns)),
                "min": float(np.min(episode_returns)),
                "max": float(np.max(episode_returns)),
            },
        }

        return stats
