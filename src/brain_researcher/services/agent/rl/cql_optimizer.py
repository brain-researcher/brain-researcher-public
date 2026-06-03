"""Conservative Q-Learning (CQL) optimizer for offline RL."""

import json
import logging

import numpy as np

from .iql_optimizer import OfflineDataset
from .policy_network import EnsembleQNetwork, PolicyNetwork, QNetwork

logger = logging.getLogger(__name__)


class CQLOptimizer:
    """Conservative Q-Learning optimizer for safe offline RL."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: list[int] | None = None,
        alpha: float = 5.0,
        learning_rate: float = 0.0003,
        discount: float = 0.99,
        tau: float = 0.005,
        use_ensemble: bool = False,
        num_random_actions: int = 10,
    ):
        """Initialize CQL optimizer.

        Args:
            state_dim: Dimension of state space
            action_dim: Number of discrete actions
            hidden_dims: Hidden layer dimensions for networks
            alpha: CQL penalty weight (higher = more conservative)
            learning_rate: Learning rate for all networks
            discount: Discount factor (gamma)
            tau: Soft update coefficient for target network
            use_ensemble: Whether to use ensemble Q-networks
            num_random_actions: Number of random actions for CQL penalty
        """
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.alpha = alpha
        self.learning_rate = learning_rate
        self.discount = discount
        self.tau = tau
        self.num_random_actions = num_random_actions

        hidden_dims = hidden_dims or [256, 256]

        # Initialize Q-networks
        if use_ensemble:
            self.q_network = EnsembleQNetwork(
                state_dim, action_dim, num_networks=3, hidden_dims=hidden_dims
            )
            self.target_q_network = EnsembleQNetwork(
                state_dim, action_dim, num_networks=3, hidden_dims=hidden_dims
            )
        else:
            self.q_network = QNetwork(state_dim, action_dim, hidden_dims)
            self.target_q_network = QNetwork(state_dim, action_dim, hidden_dims)

        # Initialize policy (for evaluation)
        self.policy = PolicyNetwork(state_dim, action_dim, hidden_dims)

        # Set learning rates
        if hasattr(self.q_network, "networks"):  # Ensemble
            for network in self.q_network.networks:
                network.learning_rate = learning_rate
        else:
            self.q_network.learning_rate = learning_rate

        self.policy.learning_rate = learning_rate

        # Copy to target network
        self._soft_update_target(1.0)  # Full copy initially

        # Training statistics
        self.training_stats = {
            "q_losses": [],
            "cql_penalties": [],
            "policy_losses": [],
            "mean_q_values": [],
            "conservative_penalty": [],
            "episodes_trained": 0,
        }

        self.update_step = 0
        self.use_ensemble = use_ensemble

    def train(
        self,
        dataset: OfflineDataset,
        epochs: int = 100,
        batch_size: int = 256,
        validation_split: float = 0.1,
        policy_training_ratio: int = 4,  # Train policy every N Q-function updates
    ) -> dict[str, list[float]]:
        """Train CQL on offline dataset.

        Args:
            dataset: Offline dataset
            epochs: Number of training epochs
            batch_size: Training batch size
            validation_split: Fraction of data for validation
            policy_training_ratio: How often to train policy vs Q-function

        Returns:
            Training history dictionary
        """
        logger.info(f"Starting CQL training on dataset of size {len(dataset)}")

        # Split dataset for validation
        total_size = len(dataset)
        val_size = int(total_size * validation_split)
        train_size = total_size - val_size

        # Training loop
        for epoch in range(epochs):
            epoch_q_losses = []
            epoch_cql_penalties = []
            epoch_policy_losses = []

            # Number of batches per epoch
            batches_per_epoch = max(1, train_size // batch_size)

            for _batch_idx in range(batches_per_epoch):
                # Sample batch
                states, actions, rewards, next_states, dones, weights = (
                    dataset.sample_batch(batch_size)
                )

                # Train Q-function
                q_loss, cql_penalty = self._train_q_function(
                    states, actions, rewards, next_states, dones, weights
                )
                epoch_q_losses.append(q_loss)
                epoch_cql_penalties.append(cql_penalty)

                # Train policy less frequently
                if self.update_step % policy_training_ratio == 0:
                    policy_loss = self._train_policy(states, weights)
                    epoch_policy_losses.append(policy_loss)

                self.update_step += 1

                # Soft update target network
                self._soft_update_target(self.tau)

            # Log epoch statistics
            avg_q_loss = np.mean(epoch_q_losses)
            avg_cql_penalty = np.mean(epoch_cql_penalties)
            avg_policy_loss = (
                np.mean(epoch_policy_losses) if epoch_policy_losses else 0.0
            )

            self.training_stats["q_losses"].append(avg_q_loss)
            self.training_stats["cql_penalties"].append(avg_cql_penalty)
            self.training_stats["policy_losses"].append(avg_policy_loss)

            # Validation
            if val_size > 0:
                val_stats = self._validate(dataset, val_size)
                self.training_stats["mean_q_values"].append(val_stats["mean_q"])
                self.training_stats["conservative_penalty"].append(
                    val_stats["conservative_penalty"]
                )

            # Adaptive alpha adjustment
            if epoch > 10 and epoch % 10 == 0:
                self._adjust_alpha(avg_cql_penalty)

            if epoch % 10 == 0:
                logger.info(
                    f"Epoch {epoch}: Q loss = {avg_q_loss:.4f}, "
                    f"CQL penalty = {avg_cql_penalty:.4f}, "
                    f"Policy loss = {avg_policy_loss:.4f}, Alpha = {self.alpha:.4f}"
                )

        self.training_stats["episodes_trained"] += epochs
        logger.info(f"Completed CQL training after {epochs} epochs")

        return self.training_stats

    def select_action(
        self,
        state: np.ndarray,
        deterministic: bool = False,
        use_policy: bool = True,
        return_info: bool = False,
    ) -> tuple[int, dict | None]:
        """Select action using trained Q-network or policy.

        Args:
            state: Current state
            deterministic: Whether to select deterministically
            use_policy: Whether to use policy or Q-network for action selection
            return_info: Whether to return additional info

        Returns:
            Selected action and optional info dict
        """
        if len(state.shape) == 1:
            state = state.reshape(1, -1)

        if use_policy:
            action, prob = self.policy.select_action(state, deterministic)
        else:
            # Use Q-network for action selection
            if self.use_ensemble:
                q_values, uncertainty = self.q_network.get_q_values_ensemble(state)
                q_values = q_values[0] if len(q_values.shape) == 2 else q_values
            else:
                q_values = self.q_network.get_q_values(state)
                q_values = q_values[0] if len(q_values.shape) == 2 else q_values
                np.zeros_like(q_values)

            if deterministic:
                action = np.argmax(q_values)
            else:
                # Softmax with temperature
                temperature = 0.1
                probs = self._softmax(q_values / temperature)
                action = np.random.choice(len(probs), p=probs)

            prob = probs[action] if not deterministic else 1.0

        if return_info:
            # Get additional info
            if self.use_ensemble:
                q_values, q_uncertainty = self.q_network.get_q_values_ensemble(state)
                q_values = q_values[0] if len(q_values.shape) == 2 else q_values
                q_uncertainty = (
                    q_uncertainty[0] if len(q_uncertainty.shape) == 2 else q_uncertainty
                )
            else:
                q_values = self.q_network.get_q_values(state)
                q_values = q_values[0] if len(q_values.shape) == 2 else q_values
                q_uncertainty = np.zeros_like(q_values)

            policy_probs = self.policy.forward(state)[0]

            info = {
                "action_prob": prob,
                "q_values": q_values.tolist(),
                "q_uncertainty": q_uncertainty.tolist(),
                "policy_probs": policy_probs.tolist(),
                "max_q": float(np.max(q_values)),
                "conservative_gap": float(np.max(q_values) - np.mean(q_values)),
            }

            return action, info

        return action, None

    def get_conservative_penalty(self, states: np.ndarray) -> float:
        """Calculate conservative penalty for given states."""
        if self.use_ensemble:
            q_values_data, _ = self.q_network.get_q_values_ensemble(states)
        else:
            q_values_data = np.array(
                [
                    self.q_network.get_q_values(state.reshape(1, -1))[0]
                    for state in states
                ]
            )

        # Random action Q-values (for penalty calculation)
        random_q_values = []
        for state in states:
            random_actions = np.random.choice(self.action_dim, self.num_random_actions)
            if self.use_ensemble:
                random_q, _ = self.q_network.get_q_values_ensemble(state.reshape(1, -1))
                random_q = random_q[0] if len(random_q.shape) == 2 else random_q
            else:
                random_q = self.q_network.get_q_values(state.reshape(1, -1))
                random_q = random_q[0] if len(random_q.shape) == 2 else random_q

            random_q_values.append([random_q[a] for a in random_actions])

        random_q_values = np.array(random_q_values)

        # Calculate logsumexp penalty
        logsumexp_random = np.mean(
            [np.log(np.sum(np.exp(q_vals))) for q_vals in random_q_values]
        )

        dataset_q_values = np.mean(q_values_data)

        penalty = logsumexp_random - dataset_q_values
        return penalty

    def evaluate_policy(
        self,
        test_states: np.ndarray,
        test_actions: np.ndarray,
        test_rewards: np.ndarray,
        use_policy: bool = True,
    ) -> dict[str, float]:
        """Evaluate policy performance on test data."""
        total_return = 0.0
        correct_actions = 0
        conservative_penalties = []

        for i, state in enumerate(test_states):
            predicted_action, info = self.select_action(
                state, deterministic=True, use_policy=use_policy, return_info=True
            )

            if predicted_action == test_actions[i]:
                correct_actions += 1

            total_return += test_rewards[i]

            if info:
                conservative_penalties.append(info["conservative_gap"])

        accuracy = correct_actions / len(test_states) if len(test_states) > 0 else 0.0
        average_return = (
            total_return / len(test_states) if len(test_states) > 0 else 0.0
        )

        # Calculate overall conservative penalty
        sample_states = test_states[: min(100, len(test_states))]
        overall_penalty = self.get_conservative_penalty(sample_states)

        return {
            "action_accuracy": accuracy,
            "average_return": average_return,
            "conservative_penalty": overall_penalty,
            "mean_conservative_gap": (
                float(np.mean(conservative_penalties))
                if conservative_penalties
                else 0.0
            ),
            "test_samples": len(test_states),
        }

    def save(self, filepath: str) -> None:
        """Save trained model."""
        model_data = {
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "alpha": self.alpha,
            "discount": self.discount,
            "tau": self.tau,
            "use_ensemble": self.use_ensemble,
            "training_stats": self.training_stats,
        }

        # Save networks
        if self.use_ensemble:
            self.q_network.save_ensemble(f"{filepath}_q_network")
        else:
            self.q_network.save(f"{filepath}_q_network.json")

        self.policy.save(f"{filepath}_policy.json")

        # Save metadata
        with open(f"{filepath}_metadata.json", "w") as f:
            json.dump(model_data, f, indent=2)

        logger.info(f"Saved CQL model to {filepath}")

    def load(self, filepath: str) -> None:
        """Load trained model."""
        # Load metadata
        with open(f"{filepath}_metadata.json") as f:
            model_data = json.load(f)

        self.state_dim = model_data["state_dim"]
        self.action_dim = model_data["action_dim"]
        self.alpha = model_data["alpha"]
        self.discount = model_data["discount"]
        self.tau = model_data["tau"]
        self.use_ensemble = model_data["use_ensemble"]
        self.training_stats = model_data["training_stats"]

        # Load networks
        if self.use_ensemble:
            self.q_network.load_ensemble(f"{filepath}_q_network")
        else:
            self.q_network.load(f"{filepath}_q_network.json")

        self.policy.load(f"{filepath}_policy.json")

        # Copy to target network
        self._soft_update_target(1.0)

        logger.info(f"Loaded CQL model from {filepath}")

    # Private methods

    def _train_q_function(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        next_states: np.ndarray,
        dones: np.ndarray,
        weights: np.ndarray,
    ) -> tuple[float, float]:
        """Train Q-function with CQL penalty."""
        # Standard Q-learning targets
        if self.use_ensemble:
            next_q_values, _ = self.target_q_network.get_q_values_ensemble(next_states)
        else:
            next_q_values = np.array(
                [
                    self.target_q_network.get_q_values(ns.reshape(1, -1))[0]
                    for ns in next_states
                ]
            )

        next_max_q = (
            np.max(next_q_values, axis=1)
            if len(next_q_values.shape) == 2
            else np.max(next_q_values)
        )
        targets = rewards + self.discount * next_max_q * (1 - dones)

        # Current Q-values
        if self.use_ensemble:
            current_q_values, _ = self.q_network.get_q_values_ensemble(states)
        else:
            np.array(
                [
                    self.q_network.get_q_values(state.reshape(1, -1))[0]
                    for state in states
                ]
            )

        # Standard Q-learning loss
        q_loss_components = []
        cql_penalties = []

        batch_size = len(states)

        for i in range(batch_size):
            state = states[i].reshape(1, -1)
            action = actions[i]
            target = targets[i]

            if self.use_ensemble:
                current_q_all, _ = self.q_network.get_q_values_ensemble(state)
                current_q_all = (
                    current_q_all[0] if len(current_q_all.shape) == 2 else current_q_all
                )
            else:
                current_q_all = self.q_network.get_q_values(state)[0]

            current_q = current_q_all[action]

            # Standard TD loss
            td_loss = (current_q - target) ** 2

            # CQL penalty term
            # 1. Q-values for random actions
            random_actions = np.random.choice(self.action_dim, self.num_random_actions)
            random_q_values = [current_q_all[a] for a in random_actions]

            # 2. Q-values for policy actions (if we have a policy)
            policy_probs = self.policy.forward(state)[0]
            policy_weighted_q = np.sum(policy_probs * current_q_all)

            # 3. Calculate logsumexp penalty
            all_q_for_penalty = list(random_q_values) + [policy_weighted_q]
            max_q_penalty = max(all_q_for_penalty)

            # Numerically stable logsumexp
            exp_sum = sum(np.exp(q - max_q_penalty) for q in all_q_for_penalty)
            logsumexp_penalty = max_q_penalty + np.log(exp_sum)

            # CQL penalty: logsumexp(Q(s,a)) - Q(s,a_data)
            cql_penalty = logsumexp_penalty - current_q
            cql_penalties.append(cql_penalty)

            # Total loss
            total_loss = td_loss + self.alpha * cql_penalty
            q_loss_components.append(total_loss)

            # Train network on this example
            q_target_vector = current_q_all.copy()
            q_target_vector[action] = target - self.alpha * cql_penalty  # Adjust target

            if self.use_ensemble:
                # Train ensemble with bootstrap sampling
                np.random.choice(1, 1, replace=True)  # Single sample for now
                self.q_network.train_ensemble(
                    state, q_target_vector.reshape(1, -1), bootstrap=False
                )
            else:
                self.q_network.backward(state, q_target_vector.reshape(1, -1))

        avg_q_loss = np.mean(q_loss_components)
        avg_cql_penalty = np.mean(cql_penalties)

        return avg_q_loss, avg_cql_penalty

    def _train_policy(self, states: np.ndarray, weights: np.ndarray) -> float:
        """Train policy to maximize Q-values."""
        policy_losses = []

        for state in states:
            state = state.reshape(1, -1)

            # Get Q-values
            if self.use_ensemble:
                q_values, _ = self.q_network.get_q_values_ensemble(state)
                q_values = q_values[0] if len(q_values.shape) == 2 else q_values
            else:
                q_values = self.q_network.get_q_values(state)[0]

            # Policy probabilities
            policy_probs = self.policy.forward(state)[0]

            # Policy loss: maximize expected Q-value
            expected_q = np.sum(policy_probs * q_values)
            policy_loss = -expected_q  # Negative because we want to maximize

            # Create target that increases probability of high-Q actions
            temperature = 0.1
            q_softmax = self._softmax(q_values / temperature)

            # Train policy towards Q-value based target
            self.policy.backward(state, q_softmax.reshape(1, -1))

            policy_losses.append(policy_loss)

        return np.mean(policy_losses)

    def _soft_update_target(self, tau: float) -> None:
        """Soft update target networks."""
        if self.use_ensemble:
            # Update ensemble networks
            for i in range(len(self.target_q_network.networks)):
                for j in range(len(self.q_network.networks[i].weights)):
                    self.target_q_network.networks[i].weights[j] = (
                        tau * self.q_network.networks[i].weights[j]
                        + (1 - tau) * self.target_q_network.networks[i].weights[j]
                    )
                    self.target_q_network.networks[i].biases[j] = (
                        tau * self.q_network.networks[i].biases[j]
                        + (1 - tau) * self.target_q_network.networks[i].biases[j]
                    )
        else:
            # Update single network
            for i in range(len(self.q_network.weights)):
                self.target_q_network.weights[i] = (
                    tau * self.q_network.weights[i]
                    + (1 - tau) * self.target_q_network.weights[i]
                )
                self.target_q_network.biases[i] = (
                    tau * self.q_network.biases[i]
                    + (1 - tau) * self.target_q_network.biases[i]
                )

    def _adjust_alpha(self, current_penalty: float) -> None:
        """Adaptively adjust CQL penalty weight."""
        # Target penalty range
        target_penalty_min = 0.1
        target_penalty_max = 1.0

        if current_penalty < target_penalty_min:
            # Increase alpha to make more conservative
            self.alpha *= 1.1
            self.alpha = min(self.alpha, 10.0)  # Cap at 10
        elif current_penalty > target_penalty_max:
            # Decrease alpha to reduce conservatism
            self.alpha *= 0.95
            self.alpha = max(self.alpha, 0.1)  # Floor at 0.1

        logger.debug(
            f"Adjusted alpha to {self.alpha:.4f} (penalty: {current_penalty:.4f})"
        )

    def _validate(self, dataset: OfflineDataset, sample_size: int) -> dict[str, float]:
        """Validate model on dataset sample."""
        states, actions, rewards, next_states, dones, _ = dataset.sample_batch(
            sample_size
        )

        # Calculate mean Q-values
        if self.use_ensemble:
            q_values_batch, _ = self.q_network.get_q_values_ensemble(states)
        else:
            q_values_batch = np.array(
                [
                    self.q_network.get_q_values(state.reshape(1, -1))[0]
                    for state in states
                ]
            )

        mean_q = np.mean(q_values_batch)

        # Calculate conservative penalty
        conservative_penalty = self.get_conservative_penalty(states)

        return {"mean_q": mean_q, "conservative_penalty": conservative_penalty}

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Compute softmax probabilities."""
        exp_x = np.exp(x - np.max(x))  # Numerical stability
        return exp_x / np.sum(exp_x)
