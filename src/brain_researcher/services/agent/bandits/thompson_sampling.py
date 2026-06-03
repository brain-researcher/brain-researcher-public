"""Thompson Sampling implementation for contextual bandits."""

import logging
from typing import Any

import numpy as np
from scipy.linalg import LinAlgError, inv
from scipy.stats import multivariate_normal

from .contextual_bandit import BanditAction, Context, ContextualBandit

logger = logging.getLogger(__name__)


class BayesianLinearRegression:
    """Bayesian Linear Regression for Thompson Sampling."""

    def __init__(
        self,
        context_dim: int,
        prior_mean: np.ndarray | None = None,
        prior_precision: np.ndarray | None = None,
        noise_precision: float = 1.0,
    ):
        self.context_dim = context_dim
        self.noise_precision = noise_precision

        # Prior parameters
        self.prior_mean = (
            prior_mean if prior_mean is not None else np.zeros(context_dim)
        )
        self.prior_precision = (
            prior_precision
            if prior_precision is not None
            else np.eye(context_dim) * 0.01
        )

        # Posterior parameters (initialized to prior)
        self.posterior_mean = self.prior_mean.copy()
        self.posterior_precision = self.prior_precision.copy()

        # For numerical stability
        self.regularization = 1e-6

        # Track updates
        self.n_updates = 0

    def update(self, context: np.ndarray, reward: float) -> None:
        """Update posterior with new observation."""
        if len(context.shape) == 1:
            context = context.reshape(-1, 1)
        elif context.shape[0] != self.context_dim:
            context = context.T

        # Update precision matrix: A_new = A_old + lambda * x * x^T
        outer_product = np.outer(context.flatten(), context.flatten())
        self.posterior_precision += self.noise_precision * outer_product

        # Add regularization for numerical stability
        self.posterior_precision += np.eye(self.context_dim) * self.regularization

        try:
            # Update mean: mu_new = A_new^-1 * (A_old * mu_old + lambda * x * reward)
            precision_inv = inv(self.posterior_precision)
            old_term = self.posterior_precision @ self.posterior_mean
            new_term = self.noise_precision * context.flatten() * reward
            self.posterior_mean = precision_inv @ (old_term + new_term)

        except LinAlgError as e:
            logger.warning(f"Numerical instability in Bayesian update: {e}")
            # Fallback: simple online update
            learning_rate = 1.0 / (self.n_updates + 1)
            prediction_error = reward - np.dot(self.posterior_mean, context.flatten())
            self.posterior_mean += learning_rate * prediction_error * context.flatten()

        self.n_updates += 1

    def sample_parameters(self) -> np.ndarray:
        """Sample parameters from posterior distribution."""
        try:
            precision_inv = inv(self.posterior_precision)

            # Sample from multivariate normal distribution
            sampled_params = multivariate_normal.rvs(
                mean=self.posterior_mean, cov=precision_inv, size=1
            )

            return sampled_params

        except (LinAlgError, ValueError) as e:
            logger.warning(f"Error sampling parameters: {e}, using posterior mean")
            # Fallback to posterior mean with small noise
            noise = np.random.normal(0, 0.1, self.context_dim)
            return self.posterior_mean + noise

    def predict_mean(self, context: np.ndarray) -> float:
        """Predict expected reward for given context."""
        return np.dot(self.posterior_mean, context.flatten())

    def predict_std(self, context: np.ndarray) -> float:
        """Predict standard deviation of reward for given context."""
        try:
            precision_inv = inv(self.posterior_precision)
            variance = np.dot(context.flatten(), precision_inv @ context.flatten())
            return np.sqrt(variance + 1.0 / self.noise_precision)
        except LinAlgError:
            return 1.0  # Default uncertainty

    def sample_prediction(self, context: np.ndarray) -> float:
        """Sample predicted reward from posterior predictive distribution."""
        # Sample parameters from posterior
        sampled_params = self.sample_parameters()

        # Predict with sampled parameters
        mean_prediction = np.dot(sampled_params, context.flatten())

        # Add observation noise
        noise_std = 1.0 / np.sqrt(self.noise_precision)
        return np.random.normal(mean_prediction, noise_std)

    def get_parameters(self) -> tuple[np.ndarray, np.ndarray]:
        """Get current posterior parameters."""
        try:
            precision_inv = inv(self.posterior_precision)
            return self.posterior_mean.copy(), precision_inv.copy()
        except LinAlgError:
            return self.posterior_mean.copy(), np.eye(self.context_dim)

    def reset(self) -> None:
        """Reset to prior."""
        self.posterior_mean = self.prior_mean.copy()
        self.posterior_precision = self.prior_precision.copy()
        self.n_updates = 0


class ThompsonSampling(ContextualBandit):
    """Thompson Sampling for contextual multi-armed bandits."""

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        actions: list[BanditAction] | None = None,
        noise_precision: float = 1.0,
        prior_precision: float = 0.01,
        exploration_bonus: float = 1.0,
    ):
        super().__init__(n_arms, context_dim, actions, exploration_bonus)

        # Initialize Bayesian linear regression for each arm
        prior_precision_matrix = np.eye(context_dim) * prior_precision

        self.models = [
            BayesianLinearRegression(
                context_dim=context_dim,
                prior_precision=prior_precision_matrix,
                noise_precision=noise_precision,
            )
            for _ in range(n_arms)
        ]

        # Thompson sampling specific tracking
        self.parameter_samples = []
        self.predicted_rewards = []
        self._exploration_count = 0
        self._exploitation_count = 0

    def select_arm(
        self,
        context: np.ndarray | Context,
        available_arms: list[int] | None = None,
        exploit: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        """Select arm using Thompson Sampling."""
        context_vector = self._extract_context_features(context)
        available_arms = available_arms or list(range(self.n_arms))

        if exploit:
            # Pure exploitation: select arm with highest posterior mean
            mean_rewards = [
                self.models[arm].predict_mean(context_vector) for arm in available_arms
            ]
            best_arm_idx = np.argmax(mean_rewards)
            selected_arm = available_arms[best_arm_idx]

            selection_info = {
                "method": "exploit",
                "predicted_rewards": {
                    str(arm): float(reward)
                    for arm, reward in zip(available_arms, mean_rewards, strict=False)
                },
                "selected_reward": float(mean_rewards[best_arm_idx]),
            }

            self._exploitation_count += 1

        else:
            # Thompson Sampling: sample parameters and predict rewards
            sampled_rewards = []
            parameter_samples = []

            for arm in available_arms:
                # Sample parameters from posterior
                sampled_params = self.models[arm].sample_parameters()
                parameter_samples.append(sampled_params)

                # Predict reward with sampled parameters
                predicted_reward = np.dot(sampled_params, context_vector)
                sampled_rewards.append(predicted_reward)

            # Select arm with highest sampled reward
            best_arm_idx = np.argmax(sampled_rewards)
            selected_arm = available_arms[best_arm_idx]

            # Store samples for analysis
            self.parameter_samples.append(
                dict(zip(available_arms, parameter_samples, strict=False))
            )
            self.predicted_rewards.append(
                dict(zip(available_arms, sampled_rewards, strict=False))
            )

            selection_info = {
                "method": "thompson_sampling",
                "sampled_rewards": {
                    str(arm): float(reward)
                    for arm, reward in zip(
                        available_arms, sampled_rewards, strict=False
                    )
                },
                "selected_reward": float(sampled_rewards[best_arm_idx]),
                "parameter_sample": parameter_samples[best_arm_idx].tolist(),
            }

            self._exploration_count += 1

        # Add uncertainty estimates
        uncertainties = {}
        for arm in available_arms:
            uncertainties[str(arm)] = float(
                self.models[arm].predict_std(context_vector)
            )

        selection_info.update(
            {
                "selected_arm": selected_arm,
                "available_arms": available_arms,
                "uncertainties": uncertainties,
                "exploration_count": self._exploration_count,
                "exploitation_count": self._exploitation_count,
            }
        )

        return selected_arm, selection_info

    def update(
        self,
        context: np.ndarray | Context,
        action: int,
        reward: float,
        feedback: Any | None = None,
    ) -> None:
        """Update Thompson Sampling model with observed reward."""
        context_vector = self._extract_context_features(context)

        # Update Bayesian model for the selected arm
        self.models[action].update(context_vector, reward)

        # Update parent class
        super().update(context, action, reward, feedback)

        logger.debug(
            f"Updated Thompson Sampling model for arm {action} with reward {reward}"
        )

    def predict_rewards(
        self, contexts: np.ndarray, arms: list[int] | None = None
    ) -> np.ndarray:
        """Predict rewards using posterior means."""
        arms = arms or list(range(self.n_arms))
        predictions = np.zeros((len(contexts), len(arms)))

        for i, context in enumerate(contexts):
            for j, arm in enumerate(arms):
                predictions[i, j] = self.models[arm].predict_mean(context)

        return predictions

    def get_uncertainty_estimates(
        self, contexts: np.ndarray, arms: list[int] | None = None
    ) -> np.ndarray:
        """Get uncertainty estimates for predictions."""
        arms = arms or list(range(self.n_arms))
        uncertainties = np.zeros((len(contexts), len(arms)))

        for i, context in enumerate(contexts):
            for j, arm in enumerate(arms):
                uncertainties[i, j] = self.models[arm].predict_std(context)

        return uncertainties

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance based on posterior parameter magnitudes."""
        importance = np.zeros(self.context_dim)

        for arm in range(self.n_arms):
            mean_params, _ = self.models[arm].get_parameters()
            importance += np.abs(mean_params)

        # Normalize
        importance = (
            importance / np.sum(importance) if np.sum(importance) > 0 else importance
        )

        return {f"feature_{i}": float(importance[i]) for i in range(self.context_dim)}

    def sample_arm_preferences(
        self, context: np.ndarray, num_samples: int = 1000
    ) -> dict[int, float]:
        """Sample arm preferences for uncertainty quantification."""
        arm_wins = dict.fromkeys(range(self.n_arms), 0)

        for _ in range(num_samples):
            sampled_rewards = [
                self.models[arm].sample_prediction(context)
                for arm in range(self.n_arms)
            ]

            best_arm = np.argmax(sampled_rewards)
            arm_wins[best_arm] += 1

        # Convert to probabilities
        return {arm: count / num_samples for arm, count in arm_wins.items()}

    def get_posterior_analysis(self, arm_id: int) -> dict[str, Any]:
        """Get detailed posterior analysis for an arm."""
        if arm_id not in range(self.n_arms):
            raise ValueError(f"Invalid arm_id: {arm_id}")

        model = self.models[arm_id]
        posterior_mean, posterior_cov = model.get_parameters()

        analysis = {
            "posterior_mean": posterior_mean.tolist(),
            "posterior_std": np.sqrt(np.diag(posterior_cov)).tolist(),
            "posterior_trace": float(np.trace(posterior_cov)),
            "n_updates": model.n_updates,
            "parameter_confidence": [
                float(1.96 * np.sqrt(posterior_cov[i, i]))  # 95% CI half-width
                for i in range(self.context_dim)
            ],
        }

        return analysis

    def optimize_hyperparameters(
        self,
        validation_contexts: np.ndarray,
        validation_actions: np.ndarray,
        validation_rewards: np.ndarray,
        hyperparameter_ranges: dict[str, tuple[float, float]],
        num_trials: int = 50,
    ) -> dict[str, float]:
        """Optimize hyperparameters using validation data."""
        logger.info("Starting Thompson Sampling hyperparameter optimization")

        best_params = {}
        best_score = float("-inf")

        list(self.models)  # Backup

        for _trial in range(num_trials):
            # Sample hyperparameters
            trial_params = {}
            for param_name, (min_val, max_val) in hyperparameter_ranges.items():
                if param_name == "noise_precision":
                    trial_params[param_name] = np.random.uniform(min_val, max_val)
                elif param_name == "prior_precision":
                    trial_params[param_name] = np.random.uniform(min_val, max_val)

            # Create new models with trial hyperparameters
            noise_precision = trial_params.get("noise_precision", 1.0)
            prior_precision = trial_params.get("prior_precision", 0.01)

            trial_models = [
                BayesianLinearRegression(
                    context_dim=self.context_dim,
                    prior_precision=np.eye(self.context_dim) * prior_precision,
                    noise_precision=noise_precision,
                )
                for _ in range(self.n_arms)
            ]

            # Evaluate on validation data
            total_reward = 0.0

            for context, action, reward in zip(
                validation_contexts,
                validation_actions,
                validation_rewards,
                strict=False,
            ):
                # Update model
                trial_models[action].update(context, reward)

                # Predict and accumulate reward
                predicted_reward = trial_models[action].predict_mean(context)
                total_reward += predicted_reward

            score = total_reward / len(validation_contexts)

            if score > best_score:
                best_score = score
                best_params = trial_params.copy()

        logger.info(f"Best hyperparameters: {best_params} (score: {best_score:.3f})")
        return best_params

    def _get_algorithm_state(self) -> dict[str, Any]:
        """Get Thompson Sampling specific state for saving."""
        state = {
            "algorithm": "thompson_sampling",
            "exploration_count": self._exploration_count,
            "exploitation_count": self._exploitation_count,
            "models": [],
        }

        # Save each model's state
        for i, model in enumerate(self.models):
            model_state = {
                "arm_id": i,
                "posterior_mean": model.posterior_mean.tolist(),
                "posterior_precision": model.posterior_precision.tolist(),
                "prior_mean": model.prior_mean.tolist(),
                "prior_precision": model.prior_precision.tolist(),
                "noise_precision": model.noise_precision,
                "n_updates": model.n_updates,
            }
            state["models"].append(model_state)

        return state

    def _set_algorithm_state(self, state: dict[str, Any]) -> None:
        """Set Thompson Sampling specific state from loaded data."""
        if "exploration_count" in state:
            self._exploration_count = state["exploration_count"]
        if "exploitation_count" in state:
            self._exploitation_count = state["exploitation_count"]

        if "models" in state:
            # Restore each model
            for model_state in state["models"]:
                arm_id = model_state["arm_id"]

                if arm_id < len(self.models):
                    model = self.models[arm_id]
                    model.posterior_mean = np.array(model_state["posterior_mean"])
                    model.posterior_precision = np.array(
                        model_state["posterior_precision"]
                    )
                    model.prior_mean = np.array(model_state["prior_mean"])
                    model.prior_precision = np.array(model_state["prior_precision"])
                    model.noise_precision = model_state["noise_precision"]
                    model.n_updates = model_state["n_updates"]
