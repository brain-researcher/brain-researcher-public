"""Unit tests for Thompson Sampling algorithm."""

import json
import pytest
import numpy as np
from datetime import datetime
from typing import Dict, List
from unittest.mock import Mock, patch, MagicMock
import tempfile
from pathlib import Path

from brain_researcher.services.agent.bandits.thompson_sampling import (
    ThompsonSampling,
    BayesianLinearRegression
)
from brain_researcher.services.agent.bandits.contextual_bandit import (
    BanditAction,
    Context,
    BanditFeedback
)


class TestBayesianLinearRegression:
    """Test Bayesian Linear Regression component."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.context_dim = 5
        self.model = BayesianLinearRegression(
            context_dim=self.context_dim,
            noise_precision=1.0
        )
    
    def test_initialization(self):
        """Test model initialization."""
        assert self.model.context_dim == self.context_dim
        assert self.model.noise_precision == 1.0
        assert self.model.n_updates == 0
        
        # Check prior parameters
        assert self.model.prior_mean.shape == (self.context_dim,)
        assert self.model.prior_precision.shape == (self.context_dim, self.context_dim)
        
        # Check posterior initialization
        np.testing.assert_array_equal(self.model.posterior_mean, self.model.prior_mean)
        np.testing.assert_array_equal(self.model.posterior_precision, self.model.prior_precision)
    
    def test_update_single_observation(self):
        """Test updating with single observation."""
        context = np.array([1.0, 0.5, -0.2, 0.8, -0.3])
        reward = 2.5
        
        # Store initial state
        initial_mean = self.model.posterior_mean.copy()
        initial_precision = self.model.posterior_precision.copy()
        
        # Update
        self.model.update(context, reward)
        
        # Check that parameters changed
        assert not np.array_equal(self.model.posterior_mean, initial_mean)
        assert not np.array_equal(self.model.posterior_precision, initial_precision)
        assert self.model.n_updates == 1
    
    def test_update_multiple_observations(self):
        """Test updating with multiple observations."""
        observations = [
            (np.array([1.0, 0.0, 0.0, 0.0, 0.0]), 1.0),
            (np.array([0.0, 1.0, 0.0, 0.0, 0.0]), 0.5),
            (np.array([0.0, 0.0, 1.0, 0.0, 0.0]), -0.2),
        ]
        
        for context, reward in observations:
            self.model.update(context, reward)
        
        assert self.model.n_updates == 3
        
        # Posterior should be different from prior
        assert not np.allclose(self.model.posterior_mean, self.model.prior_mean)
    
    def test_predict_mean(self):
        """Test mean prediction."""
        # Update with some data
        context1 = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        self.model.update(context1, 1.0)
        
        # Predict
        prediction = self.model.predict_mean(context1)
        assert isinstance(prediction, (float, np.floating))
        
        # Should be close to observed reward for same context
        context2 = np.array([2.0, 0.0, 0.0, 0.0, 0.0])  # Scaled version
        prediction2 = self.model.predict_mean(context2)
        assert prediction2 != prediction  # Different context should give different prediction
    
    def test_predict_std(self):
        """Test standard deviation prediction."""
        context = np.array([1.0, 0.5, -0.2, 0.8, -0.3])
        
        # Initial uncertainty should be high
        initial_std = self.model.predict_std(context)
        assert initial_std > 0
        
        # Update with data
        self.model.update(context, 1.0)
        
        # Uncertainty should decrease
        updated_std = self.model.predict_std(context)
        assert updated_std < initial_std
        assert updated_std > 0
    
    def test_sample_parameters(self):
        """Test parameter sampling."""
        # Sample multiple times
        samples = [self.model.sample_parameters() for _ in range(10)]
        
        # All samples should have correct dimension
        for sample in samples:
            assert sample.shape == (self.context_dim,)
        
        # Samples should be different (with high probability)
        assert not all(np.array_equal(samples[0], sample) for sample in samples[1:])
    
    def test_sample_prediction(self):
        """Test prediction sampling."""
        context = np.array([1.0, 0.5, -0.2, 0.8, -0.3])
        
        # Sample predictions
        predictions = [self.model.sample_prediction(context) for _ in range(100)]
        
        # Should all be finite
        assert all(np.isfinite(pred) for pred in predictions)
        
        # Should have some variance
        assert np.std(predictions) > 0
    
    def test_get_parameters(self):
        """Test parameter retrieval."""
        mean, cov = self.model.get_parameters()
        
        assert mean.shape == (self.context_dim,)
        assert cov.shape == (self.context_dim, self.context_dim)
        assert np.allclose(cov, cov.T)  # Should be symmetric
    
    def test_reset(self):
        """Test model reset."""
        # Make some updates
        context = np.array([1.0, 0.5, -0.2, 0.8, -0.3])
        self.model.update(context, 1.0)
        self.model.update(context * 2, 0.5)
        
        assert self.model.n_updates == 2
        
        # Reset
        self.model.reset()
        
        # Should be back to prior
        np.testing.assert_array_equal(self.model.posterior_mean, self.model.prior_mean)
        np.testing.assert_array_equal(self.model.posterior_precision, self.model.prior_precision)
        assert self.model.n_updates == 0
    
    def test_numerical_stability(self):
        """Test numerical stability with extreme inputs."""
        # Test with very large context values
        large_context = np.array([1e6, 1e6, 1e6, 1e6, 1e6])
        self.model.update(large_context, 1.0)
        
        # Should still be able to sample
        sample = self.model.sample_parameters()
        assert np.all(np.isfinite(sample))
        
        # Test with very small context values
        small_context = np.array([1e-10, 1e-10, 1e-10, 1e-10, 1e-10])
        self.model.update(small_context, 1.0)
        
        sample = self.model.sample_parameters()
        assert np.all(np.isfinite(sample))


class TestThompsonSampling:
    """Test Thompson Sampling algorithm."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.n_arms = 4
        self.context_dim = 3
        
        # Create test actions
        self.actions = [
            BanditAction(
                id=i,
                name=f"action_{i}",
                description=f"Test action {i}",
                parameters={"param": i}
            )
            for i in range(self.n_arms)
        ]
        
        self.bandit = ThompsonSampling(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions,
            noise_precision=1.0,
            prior_precision=0.01
        )
    
    def test_initialization(self):
        """Test Thompson Sampling initialization."""
        assert self.bandit.n_arms == self.n_arms
        assert self.bandit.context_dim == self.context_dim
        assert len(self.bandit.models) == self.n_arms
        assert len(self.bandit.actions) == self.n_arms
        
        # Check that models are initialized
        for model in self.bandit.models:
            assert isinstance(model, BayesianLinearRegression)
            assert model.context_dim == self.context_dim
    
    def test_select_arm_exploit(self):
        """Test arm selection in exploit mode."""
        context = Context(
            features=np.array([1.0, 0.5, -0.2]),
            metadata={},
            timestamp=datetime.now()
        )
        
        arm, info = self.bandit.select_arm(context, exploit=True)
        
        assert 0 <= arm < self.n_arms
        assert info["method"] == "exploit"
        assert "predicted_rewards" in info
        assert "selected_reward" in info
        assert len(info["predicted_rewards"]) == self.n_arms
    
    def test_select_arm_thompson_sampling(self):
        """Test arm selection using Thompson Sampling."""
        context = Context(
            features=np.array([1.0, 0.5, -0.2]),
            metadata={},
            timestamp=datetime.now()
        )
        
        arm, info = self.bandit.select_arm(context, exploit=False)
        
        assert 0 <= arm < self.n_arms
        assert info["method"] == "thompson_sampling"
        assert "sampled_rewards" in info
        assert "parameter_sample" in info
        assert "uncertainties" in info
        assert len(info["sampled_rewards"]) == self.n_arms
    
    def test_select_arm_available_arms(self):
        """Test arm selection with limited available arms."""
        context = Context(
            features=np.array([1.0, 0.5, -0.2]),
            metadata={},
            timestamp=datetime.now()
        )
        
        available_arms = [0, 2]
        arm, info = self.bandit.select_arm(context, available_arms=available_arms)
        
        assert arm in available_arms
        assert info["available_arms"] == available_arms
        assert len(info["sampled_rewards"]) == len(available_arms)
    
    def test_update_single(self):
        """Test updating with single observation."""
        context = Context(
            features=np.array([1.0, 0.5, -0.2]),
            metadata={},
            timestamp=datetime.now()
        )
        
        action = 1
        reward = 0.8
        
        # Update
        self.bandit.update(context, action, reward)
        
        # Check that statistics were updated
        assert self.bandit.action_counts[action] == 1
        assert self.bandit.total_rewards[action] == reward
        assert len(self.bandit.contexts) == 1
        assert len(self.bandit.action_history) == 1
        assert len(self.bandit.rewards) == 1
    
    def test_update_with_feedback(self):
        """Test updating with detailed feedback."""
        context = Context(
            features=np.array([1.0, 0.5, -0.2]),
            metadata={},
            timestamp=datetime.now()
        )
        
        feedback = BanditFeedback(
            context=context,
            action_id=1,
            reward=0.8,
            execution_time=120.0,
            success=True,
            metadata={"quality": "high"},
            timestamp=datetime.now()
        )
        
        self.bandit.update(context, 1, 0.8, feedback)
        
        # Check performance tracking
        perf = self.bandit.action_performance[1]
        assert perf["success_rate"] == 1.0
        assert perf["avg_execution_time"] == 120.0
    
    def test_predict_rewards(self):
        """Test reward prediction."""
        # Add some training data
        contexts = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0])
        ]
        
        for i, context in enumerate(contexts):
            self.bandit.update(context, i % self.n_arms, float(i))
        
        # Predict
        test_contexts = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0]
        ])
        
        predictions = self.bandit.predict_rewards(test_contexts)
        
        assert predictions.shape == (len(test_contexts), self.n_arms)
        assert np.all(np.isfinite(predictions))
    
    def test_get_uncertainty_estimates(self):
        """Test uncertainty estimation."""
        # Add some training data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)
        
        test_contexts = np.array([
            [1.0, 0.5, -0.2],
            [0.0, 0.0, 1.0]
        ])
        
        uncertainties = self.bandit.get_uncertainty_estimates(test_contexts)
        
        assert uncertainties.shape == (len(test_contexts), self.n_arms)
        assert np.all(uncertainties >= 0)  # Uncertainties should be non-negative
        
        # Uncertainty for trained arm should be lower
        trained_uncertainty = uncertainties[0, 0]  # Same context as training
        untrained_uncertainty = uncertainties[1, 1]  # Different context, different arm
        assert trained_uncertainty <= untrained_uncertainty
    
    def test_get_feature_importance(self):
        """Test feature importance calculation."""
        # Add some training data with clear patterns
        for i in range(self.n_arms):
            context = np.zeros(self.context_dim)
            context[i % self.context_dim] = 1.0
            self.bandit.update(context, i, float(i + 1))
        
        importance = self.bandit.get_feature_importance()
        
        assert len(importance) == self.context_dim
        assert all(0 <= v <= 1 for v in importance.values())
        assert abs(sum(importance.values()) - 1.0) < 1e-6  # Should sum to 1
    
    def test_sample_arm_preferences(self):
        """Test arm preference sampling."""
        # Add some training data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)  # Arm 0 gets good reward
        self.bandit.update(context, 1, 0.2)  # Arm 1 gets poor reward
        
        preferences = self.bandit.sample_arm_preferences(context, num_samples=1000)
        
        assert len(preferences) == self.n_arms
        assert all(0 <= p <= 1 for p in preferences.values())
        assert abs(sum(preferences.values()) - 1.0) < 1e-6  # Should sum to 1
        
        # Arm 0 should be preferred more often
        assert preferences[0] > preferences[1]
    
    def test_get_posterior_analysis(self):
        """Test posterior analysis."""
        # Add some training data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)
        
        analysis = self.bandit.get_posterior_analysis(0)
        
        assert "posterior_mean" in analysis
        assert "posterior_std" in analysis
        assert "parameter_confidence" in analysis
        assert "n_updates" in analysis
        
        assert len(analysis["posterior_mean"]) == self.context_dim
        assert len(analysis["posterior_std"]) == self.context_dim
        assert analysis["n_updates"] == 1
    
    def test_get_arm_statistics(self):
        """Test arm statistics retrieval."""
        # Add some data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)
        self.bandit.update(context, 0, 0.8)
        
        stats = self.bandit.get_arm_statistics(0)
        
        assert stats["total_pulls"] == 2
        assert stats["total_reward"] == 1.8
        assert stats["average_reward"] == 0.9
        assert 0 <= stats["confidence"] <= 1
    
    def test_get_overall_statistics(self):
        """Test overall statistics retrieval."""
        # Add some data
        contexts = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])]
        actions = [0, 1]
        rewards = [1.0, 0.5]
        
        for context, action, reward in zip(contexts, actions, rewards):
            self.bandit.update(context, action, reward)
        
        stats = self.bandit.get_overall_statistics()
        
        assert stats["total_pulls"] == 2
        assert stats["total_reward"] == 1.5
        assert stats["average_reward"] == 0.75
        assert "best_arm" in stats
        assert "exploration_rate" in stats
    
    def test_save_load_state(self):
        """Test saving and loading bandit state."""
        # Add some training data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)
        self.bandit.update(context, 1, 0.5)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            # Save state
            self.bandit.save_state(filepath)
            
            # Create new bandit and load state
            new_bandit = ThompsonSampling(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions
            )
            new_bandit.load_state(filepath)
            
            # Verify state was loaded correctly
            assert new_bandit.n_arms == self.bandit.n_arms
            assert new_bandit.context_dim == self.bandit.context_dim
            np.testing.assert_array_equal(new_bandit.action_counts, self.bandit.action_counts)
            np.testing.assert_array_equal(new_bandit.total_rewards, self.bandit.total_rewards)
            
            # Test that models produce similar results
            test_context = context
            pred1 = self.bandit.predict_rewards(test_context.reshape(1, -1))
            pred2 = new_bandit.predict_rewards(test_context.reshape(1, -1))
            
            np.testing.assert_allclose(pred1, pred2, rtol=1e-10)
            
        finally:
            Path(filepath).unlink(missing_ok=True)
    
    def test_reset(self):
        """Test bandit reset."""
        # Add some data
        context = np.array([1.0, 0.5, -0.2])
        self.bandit.update(context, 0, 1.0)
        self.bandit.update(context, 1, 0.5)
        
        assert np.sum(self.bandit.action_counts) > 0
        
        # Reset
        self.bandit.reset()
        
        # Should be back to initial state
        assert np.sum(self.bandit.action_counts) == 0
        assert np.sum(self.bandit.total_rewards) == 0
        assert len(self.bandit.contexts) == 0
        assert len(self.bandit.action_history) == 0
        
        # Models should be reset too
        for model in self.bandit.models:
            assert model.n_updates == 0
    
    def test_hyperparameter_optimization(self):
        """Test hyperparameter optimization."""
        # Create validation data
        np.random.seed(42)
        validation_contexts = np.random.randn(50, self.context_dim)
        validation_actions = np.random.randint(0, self.n_arms, 50)
        validation_rewards = np.random.randn(50)
        
        hyperparameter_ranges = {
            "noise_precision": (0.1, 2.0),
            "prior_precision": (0.001, 0.1)
        }
        
        best_params = self.bandit.optimize_hyperparameters(
            validation_contexts,
            validation_actions,
            validation_rewards,
            hyperparameter_ranges,
            num_trials=5  # Small number for testing
        )
        
        assert "noise_precision" in best_params
        assert "prior_precision" in best_params
        assert 0.1 <= best_params["noise_precision"] <= 2.0
        assert 0.001 <= best_params["prior_precision"] <= 0.1


@pytest.mark.integration
class TestThompsonSamplingIntegration:
    """Integration tests for Thompson Sampling."""
    
    def test_learning_on_simple_task(self):
        """Test learning on a simple contextual task."""
        n_arms = 3
        context_dim = 2
        
        # Create true reward function: arm i is best when context[i % context_dim] > 0
        def true_reward(context, arm):
            if context[arm % context_dim] > 0:
                return 1.0 + 0.1 * np.random.randn()
            else:
                return 0.5 + 0.1 * np.random.randn()
        
        bandit = ThompsonSampling(
            n_arms=n_arms,
            context_dim=context_dim,
            noise_precision=10.0,  # Low noise for clear learning
            prior_precision=0.01
        )
        
        # Training
        np.random.seed(42)
        for episode in range(200):
            # Generate random context
            context = np.random.randn(context_dim)
            
            # Select arm
            selected_arm, _ = bandit.select_arm(context)
            
            # Get reward
            reward = true_reward(context, selected_arm)
            
            # Update
            bandit.update(context, selected_arm, reward)
        
        # Test learned policy
        correct_selections = 0
        total_tests = 100
        
        np.random.seed(123)  # Different seed for testing
        for _ in range(total_tests):
            context = np.random.randn(context_dim)
            
            # Determine optimal arm
            optimal_arm = 0 if context[0] > 0 else 1  # Simple rule for testing
            
            # Select arm greedily
            selected_arm, _ = bandit.select_arm(context, exploit=True)
            
            if selected_arm == optimal_arm:
                correct_selections += 1
        
        accuracy = correct_selections / total_tests
        print(f"Thompson Sampling accuracy: {accuracy:.3f}")
        
        # Should perform better than random (1/3)
        assert accuracy > 0.4
    
    def test_bandit_vs_bandit_comparison(self):
        """Test comparing different Thompson Sampling configurations."""
        n_arms = 2
        context_dim = 3
        
        # Create two bandits with different hyperparameters
        bandit1 = ThompsonSampling(
            n_arms=n_arms,
            context_dim=context_dim,
            noise_precision=1.0,
            prior_precision=0.01
        )
        
        bandit2 = ThompsonSampling(
            n_arms=n_arms,
            context_dim=context_dim,
            noise_precision=5.0,  # Higher noise precision (more confident)
            prior_precision=0.1   # Higher prior precision (stronger prior)
        )
        
        # Simple reward function: arm 0 is better when context[0] > 0
        def reward_function(context, arm):
            if arm == 0 and context[0] > 0:
                return 1.0
            elif arm == 1 and context[0] <= 0:
                return 1.0
            else:
                return 0.2
        
        # Train both bandits on the same data
        np.random.seed(42)
        contexts = [np.random.randn(context_dim) for _ in range(100)]
        
        rewards1 = []
        rewards2 = []
        
        for context in contexts:
            # Bandit 1
            arm1, _ = bandit1.select_arm(context)
            reward1 = reward_function(context, arm1)
            bandit1.update(context, arm1, reward1)
            rewards1.append(reward1)
            
            # Bandit 2
            arm2, _ = bandit2.select_arm(context)
            reward2 = reward_function(context, arm2)
            bandit2.update(context, arm2, reward2)
            rewards2.append(reward2)
        
        # Both should learn, but may have different performance
        avg_reward1 = np.mean(rewards1)
        avg_reward2 = np.mean(rewards2)
        
        print(f"Bandit 1 average reward: {avg_reward1:.3f}")
        print(f"Bandit 2 average reward: {avg_reward2:.3f}")
        
        # Both should perform better than random (0.6 = 0.5 * 1.0 + 0.5 * 0.2)
        assert avg_reward1 > 0.6
        assert avg_reward2 > 0.6
        
        # Get final statistics
        stats1 = bandit1.get_overall_statistics()
        stats2 = bandit2.get_overall_statistics()
        
        assert stats1["total_pulls"] == 100
        assert stats2["total_pulls"] == 100
    
    def test_exploration_exploitation_balance(self):
        """Test exploration vs exploitation balance."""
        n_arms = 4
        context_dim = 2
        
        bandit = ThompsonSampling(
            n_arms=n_arms,
            context_dim=context_dim,
            noise_precision=1.0,
            prior_precision=0.01
        )
        
        # Fixed context for testing
        context = np.array([1.0, 0.0])
        
        # Make arm 0 clearly the best
        for _ in range(20):
            bandit.update(context, 0, 1.0)  # High reward for arm 0
        
        for arm in range(1, n_arms):
            for _ in range(5):
                bandit.update(context, arm, 0.2)  # Low reward for other arms
        
        # Now test selection behavior
        selections = []
        for _ in range(100):
            arm, info = bandit.select_arm(context)
            selections.append(arm)
        
        # Should mostly select arm 0, but with some exploration
        arm_0_count = selections.count(0)
        exploration_rate = (100 - arm_0_count) / 100
        
        print(f"Arm 0 selected: {arm_0_count}/100 times")
        print(f"Exploration rate: {exploration_rate:.3f}")
        
        # Should prefer arm 0 most of the time but still explore
        assert arm_0_count > 70  # Mostly exploit
        assert exploration_rate > 0.05  # But still explore


if __name__ == "__main__":
    pytest.main([__file__, "-v"])