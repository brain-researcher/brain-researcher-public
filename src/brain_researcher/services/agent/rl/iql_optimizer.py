"""Implicit Q-Learning (IQL) optimizer for offline RL."""

import json
import logging
import pickle
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .policy_network import PolicyNetwork, QNetwork, ValueNetwork
from .reward_model import NeuroimagingRewardModel

logger = logging.getLogger(__name__)


class OfflineDataset:
    """Dataset for offline RL training."""

    def __init__(self):
        self.states = []
        self.actions = []
        self.rewards = []
        self.next_states = []
        self.dones = []
        self.importance_weights = []

    def add_batch(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        next_states: np.ndarray,
        dones: np.ndarray,
        importance_weights: Optional[np.ndarray] = None,
    ) -> None:
        """Add a batch of data to the dataset."""
        if importance_weights is None:
            importance_weights = np.ones(len(states))

        self.states.extend(states)
        self.actions.extend(actions)
        self.rewards.extend(rewards)
        self.next_states.extend(next_states)
        self.dones.extend(dones)
        self.importance_weights.extend(importance_weights)

    def sample_batch(self, batch_size: int) -> Tuple[np.ndarray, ...]:
        """Sample a batch from the dataset."""
        if len(self.states) < batch_size:
            indices = np.arange(len(self.states))
        else:
            indices = np.random.choice(len(self.states), batch_size, replace=False)

        batch_states = np.array([self.states[i] for i in indices])
        batch_actions = np.array([self.actions[i] for i in indices])
        batch_rewards = np.array([self.rewards[i] for i in indices])
        batch_next_states = np.array([self.next_states[i] for i in indices])
        batch_dones = np.array([self.dones[i] for i in indices])
        batch_weights = np.array([self.importance_weights[i] for i in indices])

        return (
            batch_states,
            batch_actions,
            batch_rewards,
            batch_next_states,
            batch_dones,
            batch_weights,
        )

    def __len__(self) -> int:
        return len(self.states)

    def get_statistics(self) -> Dict[str, float]:
        """Get dataset statistics."""
        if not self.states:
            return {}

        return {
            "size": len(self.states),
            "mean_reward": float(np.mean(self.rewards)),
            "std_reward": float(np.std(self.rewards)),
            "min_reward": float(np.min(self.rewards)),
            "max_reward": float(np.max(self.rewards)),
            "action_distribution": {
                str(action): float(np.mean(np.array(self.actions) == action))
                for action in np.unique(self.actions)
            },
        }


class IQLOptimizer:
    """Implicit Q-Learning optimizer for offline RL."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Optional[List[int]] = None,
        expectile: float = 0.7,
        temperature: float = 3.0,
        learning_rate: float = 0.0003,
        discount: float = 0.99,
    ):
        """Initialize IQL optimizer.

        Args:
            state_dim: Dimension of state space
            action_dim: Number of discrete actions
            hidden_dims: Hidden layer dimensions for networks
            expectile: Expectile parameter for value function (tau in IQL paper)
            temperature: Temperature for advantage weighting (beta in IQL paper)
            learning_rate: Learning rate for all networks
            discount: Discount factor (gamma)
        """
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.expectile = expectile
        self.temperature = temperature
        self.learning_rate = learning_rate
        self.discount = discount

        hidden_dims = hidden_dims or [256, 256]

        # Initialize networks
        self.q_network = QNetwork(state_dim, action_dim, hidden_dims)
        self.target_q_network = QNetwork(state_dim, action_dim, hidden_dims)
        self.v_network = ValueNetwork(state_dim, hidden_dims)
        self.policy = PolicyNetwork(state_dim, action_dim, hidden_dims)

        # Set learning rates
        self.q_network.learning_rate = learning_rate
        self.v_network.learning_rate = learning_rate
        self.policy.learning_rate = learning_rate

        # Copy to target network
        self._copy_to_target()

        # Training statistics
        self.training_stats = {
            "q_losses": [],
            "v_losses": [],
            "policy_losses": [],
            "mean_q_values": [],
            "mean_v_values": [],
            "episodes_trained": 0,
        }

        # Target update frequency
        self.target_update_frequency = 2000
        self.update_step = 0

    def train(
        self,
        dataset: OfflineDataset,
        epochs: int = 100,
        batch_size: int = 256,
        validation_split: float = 0.1,
    ) -> Dict[str, List[float]]:
        """Train IQL on offline dataset.

        Args:
            dataset: Offline dataset
            epochs: Number of training epochs
            batch_size: Training batch size
            validation_split: Fraction of data for validation

        Returns:
            Training history dictionary
        """
        logger.info(f"Starting IQL training on dataset of size {len(dataset)}")

        # Split dataset for validation
        total_size = len(dataset)
        val_size = int(total_size * validation_split)
        train_size = total_size - val_size

        # Training loop
        for epoch in range(epochs):
            epoch_q_losses = []
            epoch_v_losses = []
            epoch_policy_losses = []

            # Number of batches per epoch
            batches_per_epoch = max(1, train_size // batch_size)

            for batch_idx in range(batches_per_epoch):
                # Sample batch
                states, actions, rewards, next_states, dones, weights = (
                    dataset.sample_batch(batch_size)
                )

                # Train networks
                q_loss = self._train_q_function(
                    states, actions, rewards, next_states, dones, weights
                )
                v_loss = self._train_value_function(states, weights)
                policy_loss = self._train_policy(states, actions, weights)

                epoch_q_losses.append(q_loss)
                epoch_v_losses.append(v_loss)
                epoch_policy_losses.append(policy_loss)

                self.update_step += 1

                # Update target network periodically
                if self.update_step % self.target_update_frequency == 0:
                    self._copy_to_target()

            # Log epoch statistics
            avg_q_loss = np.mean(epoch_q_losses)
            avg_v_loss = np.mean(epoch_v_losses)
            avg_policy_loss = np.mean(epoch_policy_losses)

            self.training_stats["q_losses"].append(avg_q_loss)
            self.training_stats["v_losses"].append(avg_v_loss)
            self.training_stats["policy_losses"].append(avg_policy_loss)

            # Validation
            if val_size > 0:
                val_stats = self._validate(dataset, val_size)
                self.training_stats["mean_q_values"].append(val_stats["mean_q"])
                self.training_stats["mean_v_values"].append(val_stats["mean_v"])

            if epoch % 10 == 0:
                logger.info(
                    f"Epoch {epoch}: Q loss = {avg_q_loss:.4f}, "
                    f"V loss = {avg_v_loss:.4f}, Policy loss = {avg_policy_loss:.4f}"
                )

        self.training_stats["episodes_trained"] += epochs
        logger.info(f"Completed IQL training after {epochs} epochs")

        return self.training_stats

    def select_action(
        self, state: np.ndarray, deterministic: bool = False, return_info: bool = False
    ) -> Tuple[int, Optional[Dict]]:
        """Select action using trained policy.

        Args:
            state: Current state
            deterministic: Whether to select deterministically
            return_info: Whether to return additional info

        Returns:
            Selected action and optional info dict
        """
        if len(state.shape) == 1:
            state = state.reshape(1, -1)

        action, prob = self.policy.select_action(state, deterministic)

        if return_info:
            # Get Q-values and value for debugging
            q_values = self.q_network.get_q_values(state)[0]
            value = self.v_network.get_value(state)

            info = {
                "action_prob": prob,
                "q_values": q_values.tolist(),
                "state_value": value,
                "max_q": float(np.max(q_values)),
                "advantage": float(q_values[action] - value),
            }

            return action, info

        return action, None

    def get_q_value(self, state: np.ndarray, action: int) -> float:
        """Get Q-value for state-action pair."""
        return self.q_network.get_q_value(state, action)

    def get_value(self, state: np.ndarray) -> float:
        """Get state value."""
        return self.v_network.get_value(state)

    def evaluate_policy(
        self,
        test_states: np.ndarray,
        test_actions: np.ndarray,
        test_rewards: np.ndarray,
    ) -> Dict[str, float]:
        """Evaluate policy performance on test data."""
        total_return = 0.0
        correct_actions = 0

        for i, state in enumerate(test_states):
            predicted_action, _ = self.select_action(state, deterministic=True)

            if predicted_action == test_actions[i]:
                correct_actions += 1

            # Calculate return (simplified - assumes single step)
            total_return += test_rewards[i]

        accuracy = correct_actions / len(test_states) if len(test_states) > 0 else 0.0
        average_return = (
            total_return / len(test_states) if len(test_states) > 0 else 0.0
        )

        # Additional metrics
        mean_q_values = []
        mean_values = []

        for state in test_states[:100]:  # Sample for efficiency
            q_values = self.q_network.get_q_values(state.reshape(1, -1))[0]
            value = self.v_network.get_value(state.reshape(1, -1))

            mean_q_values.append(np.mean(q_values))
            mean_values.append(value)

        return {
            "action_accuracy": accuracy,
            "average_return": average_return,
            "mean_q_value": float(np.mean(mean_q_values)) if mean_q_values else 0.0,
            "mean_state_value": float(np.mean(mean_values)) if mean_values else 0.0,
            "q_value_std": float(np.std(mean_q_values)) if mean_q_values else 0.0,
        }

    def save(self, filepath: str) -> None:
        """Save trained model."""
        model_data = {
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "expectile": self.expectile,
            "temperature": self.temperature,
            "discount": self.discount,
            "training_stats": self.training_stats,
        }

        # Save networks
        self.q_network.save(f"{filepath}_q_network.json")
        self.v_network.save(f"{filepath}_v_network.json")
        self.policy.save(f"{filepath}_policy.json")

        # Save metadata
        with open(f"{filepath}_metadata.json", "w") as f:
            json.dump(model_data, f, indent=2)

        logger.info(f"Saved IQL model to {filepath}")

    def load(self, filepath: str) -> None:
        """Load trained model."""
        # Load metadata
        with open(f"{filepath}_metadata.json", "r") as f:
            model_data = json.load(f)

        self.state_dim = model_data["state_dim"]
        self.action_dim = model_data["action_dim"]
        self.expectile = model_data["expectile"]
        self.temperature = model_data["temperature"]
        self.discount = model_data["discount"]
        self.training_stats = model_data["training_stats"]

        # Load networks
        self.q_network.load(f"{filepath}_q_network.json")
        self.v_network.load(f"{filepath}_v_network.json")
        self.policy.load(f"{filepath}_policy.json")

        # Copy to target network
        self._copy_to_target()

        logger.info(f"Loaded IQL model from {filepath}")

    # Private methods

    def _train_q_function(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        next_states: np.ndarray,
        dones: np.ndarray,
        weights: np.ndarray,
    ) -> float:
        """Train Q-function using target values from V-function."""
        # Get next state values from V-network
        next_values = np.array(
            [self.v_network.get_value(ns.reshape(1, -1)) for ns in next_states]
        )

        # Calculate targets
        targets = rewards + self.discount * next_values * (1 - dones)

        # Get current Q-values for taken actions
        current_q_values = np.array(
            [
                self.q_network.get_q_value(states[i].reshape(1, -1), actions[i])
                for i in range(len(states))
            ]
        )

        # Create target array for all actions
        q_targets = np.zeros((len(states), self.action_dim))
        for i, action in enumerate(actions):
            q_targets[i] = self.q_network.get_q_values(states[i].reshape(1, -1))[0]
            q_targets[i, action] = targets[i]

        # Train Q-network
        loss = self.q_network.backward(states, q_targets)

        return loss

    def _train_value_function(self, states: np.ndarray, weights: np.ndarray) -> float:
        """Train value function using expectile regression."""
        # Get Q-values from target Q-network
        q_values_batch = np.array(
            [
                self.target_q_network.get_q_values(state.reshape(1, -1))[0]
                for state in states
            ]
        )

        # Calculate expectile targets (max Q-value)
        max_q_values = np.max(q_values_batch, axis=1)

        # Get current V-values
        current_values = np.array(
            [self.v_network.get_value(state.reshape(1, -1)) for state in states]
        )

        # Expectile loss
        diff = max_q_values - current_values
        expectile_weights = np.where(diff > 0, self.expectile, 1 - self.expectile)

        # Create weighted targets for training
        v_targets = current_values + expectile_weights * diff
        v_targets = v_targets.reshape(-1, 1)

        # Train V-network
        loss = self.v_network.backward(states, v_targets)

        return loss

    def _train_policy(
        self, states: np.ndarray, actions: np.ndarray, weights: np.ndarray
    ) -> float:
        """Train policy using advantage weighting."""
        # Calculate advantages
        advantages = []
        for i, state in enumerate(states):
            q_val = self.q_network.get_q_value(state.reshape(1, -1), actions[i])
            v_val = self.v_network.get_value(state.reshape(1, -1))
            advantage = q_val - v_val
            advantages.append(advantage)

        advantages = np.array(advantages)

        # Advantage weighting
        exp_advantages = np.exp(advantages / self.temperature)
        exp_advantages = np.clip(exp_advantages, 0, 100)  # Prevent overflow

        # Create weighted targets for policy
        policy_targets = np.zeros((len(states), self.action_dim))
        current_probs = np.array(
            [self.policy.forward(state.reshape(1, -1))[0] for state in states]
        )

        for i, action in enumerate(actions):
            policy_targets[i] = current_probs[i]
            # Increase probability for actions with positive advantage
            if exp_advantages[i] > 1.0:
                policy_targets[i, action] *= exp_advantages[i]

        # Normalize
        policy_targets = policy_targets / np.sum(policy_targets, axis=1, keepdims=True)

        # Custom policy training with cross-entropy loss
        loss = self._train_policy_cross_entropy(states, policy_targets, exp_advantages)

        return loss

    def _train_policy_cross_entropy(
        self, states: np.ndarray, targets: np.ndarray, weights: np.ndarray
    ) -> float:
        """Train policy with weighted cross-entropy loss."""
        # Forward pass
        probs = np.array(
            [self.policy.forward(state.reshape(1, -1))[0] for state in states]
        )

        # Cross-entropy loss
        epsilon = 1e-8
        log_probs = np.log(probs + epsilon)
        loss = -np.mean(np.sum(targets * log_probs, axis=1) * weights)

        # Approximate backward pass for policy
        # This is a simplified implementation - in practice would use proper gradients
        prob_diff = probs - targets

        # Update policy parameters (simplified)
        for i, state in enumerate(states):
            # Create pseudo-target based on cross-entropy gradient
            pseudo_target = (
                probs[i] - self.policy.learning_rate * prob_diff[i] * weights[i]
            )
            pseudo_target = np.clip(pseudo_target, 0, 1)
            pseudo_target = pseudo_target / np.sum(pseudo_target)

            self.policy.backward(state.reshape(1, -1), pseudo_target.reshape(1, -1))

        return loss

    def _copy_to_target(self) -> None:
        """Copy Q-network weights to target Q-network."""
        # Copy weights
        for i in range(len(self.q_network.weights)):
            self.target_q_network.weights[i] = self.q_network.weights[i].copy()
            self.target_q_network.biases[i] = self.q_network.biases[i].copy()

    def _validate(self, dataset: OfflineDataset, sample_size: int) -> Dict[str, float]:
        """Validate model on dataset sample."""
        states, actions, rewards, next_states, dones, _ = dataset.sample_batch(
            sample_size
        )

        # Calculate mean Q-values and V-values
        mean_q = np.mean(
            [
                np.mean(self.q_network.get_q_values(state.reshape(1, -1)))
                for state in states
            ]
        )

        mean_v = np.mean(
            [self.v_network.get_value(state.reshape(1, -1)) for state in states]
        )

        return {"mean_q": mean_q, "mean_v": mean_v}
