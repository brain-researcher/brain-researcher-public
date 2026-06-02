"""Upper Confidence Bound (UCB) algorithms for contextual bandits."""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from scipy.linalg import LinAlgError, inv

from .contextual_bandit import BanditAction, Context, ContextualBandit

logger = logging.getLogger(__name__)


class UCBAlgorithm(ContextualBandit):
    """Standard Upper Confidence Bound algorithm."""

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        actions: Optional[List[BanditAction]] = None,
        confidence_level: float = 2.0,
        exploration_bonus: float = 1.0,
    ):
        super().__init__(n_arms, context_dim, actions, exploration_bonus)

        self.confidence_level = confidence_level
        self._exploration_count = 0
        self._exploitation_count = 0

    def select_arm(
        self,
        context: Union[np.ndarray, Context],
        available_arms: Optional[List[int]] = None,
        exploit: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        """Select arm using UCB strategy."""
        available_arms = available_arms or list(range(self.n_arms))

        if exploit:
            # Pure exploitation: select arm with highest mean reward
            mean_rewards = []
            for arm in available_arms:
                if self.action_counts[arm] > 0:
                    mean_reward = self.total_rewards[arm] / self.action_counts[arm]
                else:
                    mean_reward = 0.0
                mean_rewards.append(mean_reward)

            best_arm_idx = np.argmax(mean_rewards)
            selected_arm = available_arms[best_arm_idx]

            selection_info = {
                "method": "exploit",
                "mean_rewards": {
                    str(arm): float(reward)
                    for arm, reward in zip(available_arms, mean_rewards)
                },
                "selected_reward": float(mean_rewards[best_arm_idx]),
            }

            self._exploitation_count += 1

        else:
            # UCB selection
            ucb_values = []
            total_pulls = np.sum(self.action_counts)

            for arm in available_arms:
                if self.action_counts[arm] == 0:
                    # Infinite UCB for unobserved arms
                    ucb_values.append(float("inf"))
                else:
                    mean_reward = self.total_rewards[arm] / self.action_counts[arm]

                    if total_pulls > 1:
                        confidence_radius = self.confidence_level * np.sqrt(
                            np.log(total_pulls) / self.action_counts[arm]
                        )
                    else:
                        confidence_radius = 0.0

                    ucb_value = mean_reward + confidence_radius
                    ucb_values.append(ucb_value)

            # Select arm with highest UCB
            best_arm_idx = np.argmax(ucb_values)
            selected_arm = available_arms[best_arm_idx]

            selection_info = {
                "method": "ucb",
                "ucb_values": {
                    str(arm): float(ucb) for arm, ucb in zip(available_arms, ucb_values)
                },
                "mean_rewards": {
                    str(arm): float(
                        self.total_rewards[arm] / max(1, self.action_counts[arm])
                    )
                    for arm in available_arms
                },
                "confidence_radii": {
                    str(arm): float(
                        self.confidence_level
                        * np.sqrt(
                            np.log(max(2, total_pulls))
                            / max(1, self.action_counts[arm])
                        )
                    )
                    for arm in available_arms
                },
                "selected_ucb": float(ucb_values[best_arm_idx]),
            }

            # Determine if this was exploration or exploitation
            mean_reward = self.total_rewards[selected_arm] / max(
                1, self.action_counts[selected_arm]
            )
            best_mean_arm = available_arms[
                np.argmax(
                    [
                        self.total_rewards[arm] / max(1, self.action_counts[arm])
                        for arm in available_arms
                    ]
                )
            ]

            if selected_arm == best_mean_arm:
                self._exploitation_count += 1
                selection_info["decision_type"] = "exploitation"
            else:
                self._exploration_count += 1
                selection_info["decision_type"] = "exploration"

        selection_info.update(
            {
                "selected_arm": selected_arm,
                "available_arms": available_arms,
                "total_pulls": int(np.sum(self.action_counts)),
                "exploration_count": self._exploration_count,
                "exploitation_count": self._exploitation_count,
                "confidence_level": self.confidence_level,
            }
        )

        return selected_arm, selection_info

    def _get_algorithm_state(self) -> Dict[str, Any]:
        """Get UCB specific state."""
        return {
            "algorithm": "ucb",
            "confidence_level": self.confidence_level,
            "exploration_count": self._exploration_count,
            "exploitation_count": self._exploitation_count,
        }

    def _set_algorithm_state(self, state: Dict[str, Any]) -> None:
        """Set UCB specific state."""
        if "confidence_level" in state:
            self.confidence_level = state["confidence_level"]
        if "exploration_count" in state:
            self._exploration_count = state["exploration_count"]
        if "exploitation_count" in state:
            self._exploitation_count = state["exploitation_count"]


class LinUCB(ContextualBandit):
    """Linear Upper Confidence Bound for contextual bandits."""

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        actions: Optional[List[BanditAction]] = None,
        alpha: float = 1.0,
        regularization: float = 1.0,
        exploration_bonus: float = 1.0,
    ):
        super().__init__(n_arms, context_dim, actions, exploration_bonus)

        self.alpha = alpha  # Confidence parameter
        self.regularization = regularization

        # Initialize parameters for each arm
        self.A = [
            np.eye(context_dim) * regularization for _ in range(n_arms)
        ]  # Design matrices
        self.b = [np.zeros(context_dim) for _ in range(n_arms)]  # Reward vectors
        self.theta = [
            np.zeros(context_dim) for _ in range(n_arms)
        ]  # Parameter estimates

        self._exploration_count = 0
        self._exploitation_count = 0

    def select_arm(
        self,
        context: Union[np.ndarray, Context],
        available_arms: Optional[List[int]] = None,
        exploit: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        """Select arm using LinUCB strategy."""
        context_vector = self._extract_context_features(context)
        available_arms = available_arms or list(range(self.n_arms))

        if exploit:
            # Pure exploitation: select arm with highest expected reward
            expected_rewards = []
            for arm in available_arms:
                expected_reward = np.dot(self.theta[arm], context_vector)
                expected_rewards.append(expected_reward)

            best_arm_idx = np.argmax(expected_rewards)
            selected_arm = available_arms[best_arm_idx]

            selection_info = {
                "method": "exploit",
                "expected_rewards": {
                    str(arm): float(reward)
                    for arm, reward in zip(available_arms, expected_rewards)
                },
                "selected_reward": float(expected_rewards[best_arm_idx]),
            }

            self._exploitation_count += 1

        else:
            # LinUCB selection
            ucb_values = []
            expected_rewards = []
            confidence_radii = []

            for arm in available_arms:
                # Expected reward
                expected_reward = np.dot(self.theta[arm], context_vector)
                expected_rewards.append(expected_reward)

                # Confidence radius
                try:
                    A_inv = inv(self.A[arm])
                    confidence_radius = self.alpha * np.sqrt(
                        np.dot(context_vector, A_inv @ context_vector)
                    )
                except LinAlgError:
                    logger.warning(f"Numerical instability in LinUCB for arm {arm}")
                    confidence_radius = self.alpha  # Fallback

                confidence_radii.append(confidence_radius)

                # UCB value
                ucb_value = expected_reward + confidence_radius
                ucb_values.append(ucb_value)

            # Select arm with highest UCB
            best_arm_idx = np.argmax(ucb_values)
            selected_arm = available_arms[best_arm_idx]

            selection_info = {
                "method": "linucb",
                "ucb_values": {
                    str(arm): float(ucb) for arm, ucb in zip(available_arms, ucb_values)
                },
                "expected_rewards": {
                    str(arm): float(reward)
                    for arm, reward in zip(available_arms, expected_rewards)
                },
                "confidence_radii": {
                    str(arm): float(radius)
                    for arm, radius in zip(available_arms, confidence_radii)
                },
                "selected_ucb": float(ucb_values[best_arm_idx]),
            }

            # Determine exploration vs exploitation
            best_expected_arm = available_arms[np.argmax(expected_rewards)]

            if selected_arm == best_expected_arm:
                self._exploitation_count += 1
                selection_info["decision_type"] = "exploitation"
            else:
                self._exploration_count += 1
                selection_info["decision_type"] = "exploration"

        selection_info.update(
            {
                "selected_arm": selected_arm,
                "available_arms": available_arms,
                "exploration_count": self._exploration_count,
                "exploitation_count": self._exploitation_count,
                "alpha": self.alpha,
                "theta_norms": {
                    str(arm): float(np.linalg.norm(self.theta[arm]))
                    for arm in available_arms
                },
            }
        )

        return selected_arm, selection_info

    def update(
        self,
        context: Union[np.ndarray, Context],
        action: int,
        reward: float,
        feedback: Optional[Any] = None,
    ) -> None:
        """Update LinUCB parameters."""
        context_vector = self._extract_context_features(context)

        # Update design matrix and reward vector for the selected arm
        self.A[action] += np.outer(context_vector, context_vector)
        self.b[action] += reward * context_vector

        # Update parameter estimate
        try:
            A_inv = inv(self.A[action])
            self.theta[action] = A_inv @ self.b[action]
        except LinAlgError:
            logger.warning(
                f"Numerical instability updating LinUCB parameters for arm {action}"
            )
            # Fallback to gradient descent update
            learning_rate = 1.0 / (self.action_counts[action] + 1)
            prediction_error = reward - np.dot(self.theta[action], context_vector)
            self.theta[action] += learning_rate * prediction_error * context_vector

        # Update parent class
        super().update(context, action, reward, feedback)

        logger.debug(f"Updated LinUCB parameters for arm {action}")

    def predict_rewards(
        self, contexts: np.ndarray, arms: Optional[List[int]] = None
    ) -> np.ndarray:
        """Predict rewards using linear models."""
        arms = arms or list(range(self.n_arms))
        predictions = np.zeros((len(contexts), len(arms)))

        for i, context in enumerate(contexts):
            for j, arm in enumerate(arms):
                predictions[i, j] = np.dot(self.theta[arm], context)

        return predictions

    def get_confidence_intervals(
        self,
        contexts: np.ndarray,
        arms: Optional[List[int]] = None,
        confidence_level: float = 0.95,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Get confidence intervals for predictions."""
        arms = arms or list(range(self.n_arms))
        predictions = self.predict_rewards(contexts, arms)

        # Calculate confidence radii
        z_score = 1.96 if confidence_level == 0.95 else 2.576  # for 99%

        lower_bounds = np.zeros_like(predictions)
        upper_bounds = np.zeros_like(predictions)

        for i, context in enumerate(contexts):
            for j, arm in enumerate(arms):
                try:
                    A_inv = inv(self.A[arm])
                    confidence_radius = z_score * np.sqrt(
                        np.dot(context, A_inv @ context)
                    )
                except LinAlgError:
                    confidence_radius = 1.0  # Default uncertainty

                lower_bounds[i, j] = predictions[i, j] - confidence_radius
                upper_bounds[i, j] = predictions[i, j] + confidence_radius

        return lower_bounds, upper_bounds

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance based on parameter magnitudes."""
        # Average parameter magnitudes across all arms
        avg_params = np.mean([np.abs(theta) for theta in self.theta], axis=0)

        # Normalize
        total_importance = np.sum(avg_params)
        if total_importance > 0:
            avg_params = avg_params / total_importance

        return {f"feature_{i}": float(avg_params[i]) for i in range(self.context_dim)}

    def get_arm_analysis(self, arm_id: int) -> Dict[str, Any]:
        """Get detailed analysis for a specific arm."""
        if arm_id not in range(self.n_arms):
            raise ValueError(f"Invalid arm_id: {arm_id}")

        # Parameter statistics
        theta = self.theta[arm_id]

        try:
            A_inv = inv(self.A[arm_id])
            parameter_std = np.sqrt(np.diag(A_inv))
            condition_number = np.linalg.cond(self.A[arm_id])
        except LinAlgError:
            parameter_std = np.ones(self.context_dim)
            condition_number = float("inf")

        analysis = {
            "parameters": theta.tolist(),
            "parameter_std": parameter_std.tolist(),
            "parameter_confidence": (
                1.96 * parameter_std
            ).tolist(),  # 95% CI half-widths
            "design_matrix_condition": float(condition_number),
            "total_observations": int(self.action_counts[arm_id]),
            "parameter_norm": float(np.linalg.norm(theta)),
            "design_matrix_trace": float(np.trace(self.A[arm_id])),
            "design_matrix_determinant": (
                float(np.linalg.det(self.A[arm_id])) if condition_number < 1e12 else 0.0
            ),
        }

        return analysis

    def adapt_alpha(
        self,
        validation_contexts: np.ndarray,
        validation_actions: np.ndarray,
        validation_rewards: np.ndarray,
        alpha_range: Tuple[float, float] = (0.1, 5.0),
        num_trials: int = 20,
    ) -> float:
        """Adaptively tune the alpha parameter using validation data."""
        logger.info("Adapting LinUCB alpha parameter")

        best_alpha = self.alpha
        best_score = float("-inf")

        # Save current state
        original_A = [A.copy() for A in self.A]
        original_b = [b.copy() for b in self.b]
        original_theta = [theta.copy() for theta in self.theta]
        original_alpha = self.alpha

        for trial in range(num_trials):
            # Sample alpha
            trial_alpha = np.random.uniform(*alpha_range)
            self.alpha = trial_alpha

            # Reset parameters
            self.A = [
                np.eye(self.context_dim) * self.regularization
                for _ in range(self.n_arms)
            ]
            self.b = [np.zeros(self.context_dim) for _ in range(self.n_arms)]
            self.theta = [np.zeros(self.context_dim) for _ in range(self.n_arms)]

            # Evaluate on validation data
            total_reward = 0.0
            correct_selections = 0

            for context, action, reward in zip(
                validation_contexts, validation_actions, validation_rewards
            ):
                # Select arm with current alpha
                selected_arm, _ = self.select_arm(context)

                # Check if selection matches validation
                if selected_arm == action:
                    correct_selections += 1
                    total_reward += reward

                # Update with validation data
                self.update(context, action, reward)

            # Score based on accuracy and reward
            accuracy = correct_selections / len(validation_contexts)
            avg_reward = total_reward / len(validation_contexts)
            score = accuracy + 0.1 * avg_reward  # Weighted combination

            if score > best_score:
                best_score = score
                best_alpha = trial_alpha

        # Restore original state and apply best alpha
        self.A = original_A
        self.b = original_b
        self.theta = original_theta
        self.alpha = best_alpha

        logger.info(f"Best alpha: {best_alpha:.3f} (score: {best_score:.3f})")
        return best_alpha

    def _get_algorithm_state(self) -> Dict[str, Any]:
        """Get LinUCB specific state."""
        return {
            "algorithm": "linucb",
            "alpha": self.alpha,
            "regularization": self.regularization,
            "exploration_count": self._exploration_count,
            "exploitation_count": self._exploitation_count,
            "A": [A.tolist() for A in self.A],
            "b": [b.tolist() for b in self.b],
            "theta": [theta.tolist() for theta in self.theta],
        }

    def _set_algorithm_state(self, state: Dict[str, Any]) -> None:
        """Set LinUCB specific state."""
        if "alpha" in state:
            self.alpha = state["alpha"]
        if "regularization" in state:
            self.regularization = state["regularization"]
        if "exploration_count" in state:
            self._exploration_count = state["exploration_count"]
        if "exploitation_count" in state:
            self._exploitation_count = state["exploitation_count"]

        if "A" in state:
            self.A = [np.array(A) for A in state["A"]]
        if "b" in state:
            self.b = [np.array(b) for b in state["b"]]
        if "theta" in state:
            self.theta = [np.array(theta) for theta in state["theta"]]
