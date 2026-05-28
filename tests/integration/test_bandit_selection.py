"""Integration tests for bandit selection algorithms."""

import json
import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from brain_researcher.services.agent.bandits.thompson_sampling import ThompsonSampling
from brain_researcher.services.agent.bandits.ucb_algorithm import UCBAlgorithm, LinUCB
from brain_researcher.services.agent.bandits.contextual_bandit import (
    BanditAction,
    Context,
    BanditFeedback
)


@pytest.mark.integration
class TestBanditSelectionIntegration:
    """Integration tests for complete bandit selection pipeline."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.n_arms = 5
        self.context_dim = 4
        
        # Create realistic actions for neuroimaging tasks
        self.actions = [
            BanditAction(
                id=0,
                name="fsl_bet",
                description="FSL Brain Extraction Tool",
                parameters={"fractional_intensity": 0.5},
                cost=10.0,
                expected_time=30.0
            ),
            BanditAction(
                id=1,
                name="fsl_flirt",
                description="FSL Linear Registration",
                parameters={"dof": 12, "cost": "corratio"},
                cost=25.0,
                expected_time=120.0
            ),
            BanditAction(
                id=2,
                name="nilearn_glm",
                description="Nilearn GLM Analysis",
                parameters={"smoothing_fwhm": 6.0},
                cost=50.0,
                expected_time=300.0
            ),
            BanditAction(
                id=3,
                name="connectome_analysis",
                description="Connectome Network Analysis",
                parameters={"atlas": "schaefer"},
                cost=75.0,
                expected_time=600.0
            ),
            BanditAction(
                id=4,
                name="meta_analysis",
                description="Meta-analysis Tool",
                parameters={"method": "ale"},
                cost=100.0,
                expected_time=900.0
            )
        ]
    
    def create_realistic_reward_function(self) -> callable:
        """Create realistic reward function based on context features."""
        def reward_function(context: np.ndarray, action_id: int, add_noise: bool = True) -> float:
            """
            Reward function simulating realistic neuroimaging analysis scenarios.
            
            Context features:
            [0] Dataset size (normalized)
            [1] Data quality score (0-1)
            [2] Computational resources available (0-1)
            [3] Time constraint (0-1, higher = less time pressure)
            """
            dataset_size = context[0]
            quality = context[1]
            resources = context[2]
            time_pressure = context[3]
            
            # Base reward for each action
            base_rewards = {
                0: 0.6,  # FSL BET - generally good, fast
                1: 0.7,  # FSL FLIRT - good for registration
                2: 0.8,  # Nilearn GLM - comprehensive analysis
                3: 0.9,  # Connectome - advanced but resource intensive
                4: 0.85  # Meta-analysis - good but very slow
            }
            
            reward = base_rewards[action_id]
            
            # Adjust based on context
            if action_id == 0:  # FSL BET
                # Works well regardless of dataset size, good for quick preprocessing
                reward += 0.2 * (1 - time_pressure)  # Better when time is tight
                
            elif action_id == 1:  # FSL FLIRT
                # Works better with higher quality data
                reward += 0.3 * quality
                reward -= 0.2 * (1 - resources)  # Needs some computational resources
                
            elif action_id == 2:  # Nilearn GLM
                # Scales well with dataset size, needs good quality
                reward += 0.3 * dataset_size
                reward += 0.2 * quality
                reward -= 0.3 * (1 - resources)  # Computationally intensive
                
            elif action_id == 3:  # Connectome
                # Best for large, high-quality datasets with good resources
                reward += 0.4 * dataset_size
                reward += 0.3 * quality
                reward -= 0.5 * (1 - resources)  # Very resource intensive
                reward -= 0.4 * (1 - time_pressure)  # Slow
                
            elif action_id == 4:  # Meta-analysis
                # Works well with any data size but very slow
                reward += 0.2 * dataset_size
                reward -= 0.6 * (1 - time_pressure)  # Extremely slow
            
            # Add noise if requested
            if add_noise:
                reward += np.random.normal(0, 0.1)
            
            # Ensure reward is in reasonable range
            return np.clip(reward, 0.0, 2.0)
        
        return reward_function
    
    def generate_realistic_contexts(self, n_contexts: int, seed: int = 42) -> List[Context]:
        """Generate realistic contexts for neuroimaging scenarios."""
        np.random.seed(seed)
        contexts = []
        
        for i in range(n_contexts):
            # Generate correlated features that make sense
            
            # Dataset size and quality are somewhat correlated
            quality = np.random.beta(2, 2)  # Tends toward middle values
            dataset_size = np.random.beta(2, 2) + 0.2 * quality + 0.1 * np.random.randn()
            dataset_size = np.clip(dataset_size, 0, 1)
            
            # Resources available
            resources = np.random.beta(3, 2)  # Tends toward higher values
            
            # Time pressure (inversely related to resources sometimes)
            time_pressure = np.random.beta(2, 3) + 0.1 * resources + 0.1 * np.random.randn()
            time_pressure = np.clip(time_pressure, 0, 1)
            
            features = np.array([dataset_size, quality, resources, time_pressure])
            
            # Create metadata
            metadata = {
                "dataset_id": f"ds{i:03d}",
                "session_type": np.random.choice(["training", "validation", "test"]),
                "priority": np.random.choice(["low", "medium", "high"]),
                "user_id": f"user_{np.random.randint(1, 10)}"
            }
            
            context = Context(
                features=features,
                metadata=metadata,
                timestamp=datetime.now() + timedelta(minutes=i),
                user_id=metadata["user_id"],
                session_id=f"session_{i // 10}"
            )
            
            contexts.append(context)
        
        return contexts
    
    def test_single_bandit_learning_performance(self):
        """Test single bandit algorithm learning performance."""
        # Test Thompson Sampling
        ts_bandit = ThompsonSampling(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions,
            noise_precision=5.0,
            prior_precision=0.01
        )
        
        reward_fn = self.create_realistic_reward_function()
        contexts = self.generate_realistic_contexts(200)
        
        ts_rewards = []
        ts_regrets = []
        
        for context in contexts:
            # Select action
            action_id, selection_info = ts_bandit.select_arm(context)
            
            # Get reward
            reward = reward_fn(context.features, action_id)
            ts_rewards.append(reward)
            
            # Calculate regret
            optimal_rewards = [reward_fn(context.features, aid, add_noise=False) for aid in range(self.n_arms)]
            optimal_reward = max(optimal_rewards)
            regret = optimal_reward - reward_fn(context.features, action_id, add_noise=False)
            ts_regrets.append(regret)
            
            # Create detailed feedback
            feedback = BanditFeedback(
                context=context,
                action_id=action_id,
                reward=reward,
                execution_time=self.actions[action_id].expected_time * (1 + 0.1 * np.random.randn()),
                success=reward > 0.5,
                metadata={"context_type": "realistic"},
                timestamp=datetime.now()
            )
            
            # Update bandit
            ts_bandit.update(context, action_id, reward, feedback)
        
        # Analyze performance
        window_size = 50
        early_regret = np.mean(ts_regrets[:window_size])
        late_regret = np.mean(ts_regrets[-window_size:])
        
        print(f"Thompson Sampling - Early regret: {early_regret:.3f}, Late regret: {late_regret:.3f}")
        
        # Should show learning (decreasing regret)
        assert late_regret < early_regret
        assert late_regret < 0.3  # Should achieve reasonably low regret
        
        # Check exploration/exploitation balance
        stats = ts_bandit.get_overall_statistics()
        assert stats["total_pulls"] == 200
        assert 0.1 <= stats["exploration_rate"] <= 0.9  # Should balance exploration and exploitation
    
    def test_multi_algorithm_comparison(self):
        """Test comparing different bandit algorithms on the same task."""
        algorithms = {
            "thompson_sampling": ThompsonSampling(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions,
                noise_precision=2.0
            ),
            "ucb": UCBAlgorithm(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions,
                confidence_level=2.0
            ),
            "linucb": LinUCB(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions,
                alpha=1.0
            )
        }
        
        reward_fn = self.create_realistic_reward_function()
        contexts = self.generate_realistic_contexts(150, seed=42)
        
        results = {}
        
        for name, bandit in algorithms.items():
            rewards = []
            regrets = []
            
            for context in contexts:
                # Select action
                action_id, _ = bandit.select_arm(context)
                
                # Get reward
                reward = reward_fn(context.features, action_id)
                rewards.append(reward)
                
                # Calculate regret
                optimal_rewards = [reward_fn(context.features, aid, add_noise=False) for aid in range(self.n_arms)]
                optimal_reward = max(optimal_rewards)
                regret = optimal_reward - reward_fn(context.features, action_id, add_noise=False)
                regrets.append(regret)
                
                # Update bandit
                bandit.update(context, action_id, reward)
            
            # Store results
            results[name] = {
                "total_reward": sum(rewards),
                "avg_reward": np.mean(rewards),
                "total_regret": sum(regrets),
                "avg_regret": np.mean(regrets),
                "final_regret": np.mean(regrets[-20:])  # Last 20 episodes
            }
        
        # Print comparison
        print("Algorithm Comparison:")
        for name, metrics in results.items():
            print(f"{name}: avg_reward={metrics['avg_reward']:.3f}, final_regret={metrics['final_regret']:.3f}")
        
        # All algorithms should learn (achieve reasonable performance)
        for name, metrics in results.items():
            assert metrics["avg_reward"] > 0.5  # Better than random
            assert metrics["final_regret"] < 0.5  # Should achieve low regret
        
        # LinUCB should generally perform well on contextual tasks
        # (though not guaranteed due to finite samples)
        linucb_performance = results["linucb"]["avg_reward"]
        assert linucb_performance > 0.6
    
    def test_dynamic_environment_adaptation(self):
        """Test bandit adaptation to changing environments."""
        bandit = ThompsonSampling(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions,
            noise_precision=3.0
        )
        
        # Phase 1: Initial environment
        def reward_fn_phase1(context, action_id):
            # Simple function where action 0 is generally best
            base_reward = 0.8 if action_id == 0 else 0.4
            return base_reward + 0.1 * np.random.randn()
        
        # Phase 2: Changed environment
        def reward_fn_phase2(context, action_id):
            # Now action 2 is best, especially with high-quality data
            if action_id == 2 and context[1] > 0.5:  # Quality > 0.5
                return 0.9 + 0.1 * np.random.randn()
            else:
                return 0.3 + 0.1 * np.random.randn()
        
        # Training phase 1
        phase1_contexts = self.generate_realistic_contexts(100, seed=42)
        phase1_rewards = []
        
        for context in phase1_contexts:
            action_id, _ = bandit.select_arm(context)
            reward = reward_fn_phase1(context.features, action_id)
            phase1_rewards.append(reward)
            bandit.update(context, action_id, reward)
        
        # Check that bandit learned phase 1 (should prefer action 0)
        test_context = Context(
            features=np.array([0.5, 0.7, 0.6, 0.5]),
            metadata={},
            timestamp=datetime.now()
        )
        
        phase1_selections = []
        for _ in range(50):
            action_id, _ = bandit.select_arm(test_context, exploit=True)
            phase1_selections.append(action_id)
        
        action0_count_phase1 = phase1_selections.count(0)
        print(f"Phase 1 - Action 0 selected: {action0_count_phase1}/50 times")
        
        # Should prefer action 0 in phase 1
        assert action0_count_phase1 > 25
        
        # Training phase 2 (environment changes)
        phase2_contexts = self.generate_realistic_contexts(100, seed=123)
        phase2_rewards = []
        
        for context in phase2_contexts:
            action_id, _ = bandit.select_arm(context)
            reward = reward_fn_phase2(context.features, action_id)
            phase2_rewards.append(reward)
            bandit.update(context, action_id, reward)
        
        # Check adaptation to phase 2 (should prefer action 2 for high-quality contexts)
        high_quality_context = Context(
            features=np.array([0.5, 0.8, 0.6, 0.5]),  # High quality (feature 1 = 0.8)
            metadata={},
            timestamp=datetime.now()
        )
        
        phase2_selections = []
        for _ in range(50):
            action_id, _ = bandit.select_arm(high_quality_context, exploit=True)
            phase2_selections.append(action_id)
        
        action2_count_phase2 = phase2_selections.count(2)
        print(f"Phase 2 - Action 2 selected: {action2_count_phase2}/50 times")
        
        # Should adapt and prefer action 2 for high-quality contexts in phase 2
        assert action2_count_phase2 > action0_count_phase1 * 0.3  # Some adaptation
        
        # Overall performance should be reasonable
        avg_reward_phase1 = np.mean(phase1_rewards)
        avg_reward_phase2 = np.mean(phase2_rewards)
        
        print(f"Average rewards - Phase 1: {avg_reward_phase1:.3f}, Phase 2: {avg_reward_phase2:.3f}")
        
        assert avg_reward_phase1 > 0.5
        assert avg_reward_phase2 > 0.4  # Might be lower initially due to adaptation
    
    def test_bandit_with_realistic_constraints(self):
        """Test bandit with realistic constraints (time, cost, availability)."""
        bandit = LinUCB(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions,
            alpha=1.0
        )
        
        reward_fn = self.create_realistic_reward_function()
        contexts = self.generate_realistic_contexts(100)
        
        constrained_rewards = []
        constraint_violations = 0
        
        for i, context in enumerate(contexts):
            # Simulate realistic constraints
            
            # Time constraint: only fast methods allowed 20% of the time
            if np.random.random() < 0.2:
                # Only allow fast actions (expected_time < 200)
                available_arms = [
                    aid for aid in range(self.n_arms) 
                    if self.actions[aid].expected_time < 200
                ]
            else:
                available_arms = None
            
            # Cost constraint: only low-cost methods allowed 10% of the time
            if available_arms is None and np.random.random() < 0.1:
                # Only allow low-cost actions (cost < 50)
                available_arms = [
                    aid for aid in range(self.n_arms) 
                    if self.actions[aid].cost < 50
                ]
            
            # Select action with constraints
            if available_arms:
                action_id, selection_info = bandit.select_arm(context, available_arms=available_arms)
                
                # Verify constraint satisfaction
                if action_id not in available_arms:
                    constraint_violations += 1
            else:
                action_id, selection_info = bandit.select_arm(context)
            
            # Get reward (possibly penalized for constraint violations)
            reward = reward_fn(context.features, action_id)
            
            # Add penalty for slow methods under time pressure
            if context.features[3] < 0.3 and self.actions[action_id].expected_time > 300:  # Low time pressure
                reward *= 0.7  # Penalty for slow method when time is tight
            
            constrained_rewards.append(reward)
            
            # Update bandit
            bandit.update(context, action_id, reward)
        
        # Analyze constrained performance
        avg_constrained_reward = np.mean(constrained_rewards)
        
        print(f"Constrained average reward: {avg_constrained_reward:.3f}")
        print(f"Constraint violations: {constraint_violations}")
        
        # Should still achieve reasonable performance despite constraints
        assert avg_constrained_reward > 0.4
        assert constraint_violations == 0  # Should respect constraints
        
        # Check that bandit learned to consider constraints
        stats = bandit.get_overall_statistics()
        arm_distribution = stats["arm_distribution"]
        
        # Should have used multiple arms (not just the theoretically best one)
        used_arms = sum(1 for count in arm_distribution.values() if float(count) > 0.05)
        assert used_arms >= 3
    
    def test_multi_user_bandit_personalization(self):
        """Test bandit behavior across different users/sessions."""
        bandits = {}
        reward_functions = {}
        
        # Create different users with different preferences
        users = ["user_1", "user_2", "user_3"]
        
        for user in users:
            bandits[user] = ThompsonSampling(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions
            )
            
            # Each user has different optimal actions based on their work style
            if user == "user_1":
                # Prefers fast methods
                def user1_reward(context, action_id):
                    base_reward = 0.9 if action_id in [0, 1] else 0.4
                    return base_reward + 0.1 * np.random.randn()
                reward_functions[user] = user1_reward
                
            elif user == "user_2":
                # Prefers comprehensive analysis
                def user2_reward(context, action_id):
                    base_reward = 0.9 if action_id in [2, 3] else 0.4
                    return base_reward + 0.1 * np.random.randn()
                reward_functions[user] = user2_reward
                
            else:  # user_3
                # Context-dependent preference
                def user3_reward(context, action_id):
                    if context[0] > 0.5:  # Large dataset
                        base_reward = 0.9 if action_id in [3, 4] else 0.5
                    else:  # Small dataset
                        base_reward = 0.9 if action_id in [0, 1] else 0.5
                    return base_reward + 0.1 * np.random.randn()
                reward_functions[user] = user3_reward
        
        # Training phase
        all_contexts = self.generate_realistic_contexts(150)
        user_performance = {}
        
        for user in users:
            rewards = []
            
            # Each user gets their own subset of contexts
            user_contexts = [ctx for i, ctx in enumerate(all_contexts) if i % len(users) == users.index(user)]
            
            for context in user_contexts:
                # Update context with user info
                context.user_id = user
                
                # Select action
                action_id, _ = bandits[user].select_arm(context)
                
                # Get user-specific reward
                reward = reward_functions[user](context.features, action_id)
                rewards.append(reward)
                
                # Update user's bandit
                bandits[user].update(context, action_id, reward)
            
            user_performance[user] = {
                "avg_reward": np.mean(rewards),
                "total_interactions": len(user_contexts)
            }
        
        # Analyze personalization
        print("User-specific performance:")
        for user, perf in user_performance.items():
            print(f"{user}: avg_reward={perf['avg_reward']:.3f}, interactions={perf['total_interactions']}")
            
            # Each user should achieve good performance with their preferences
            assert perf["avg_reward"] > 0.6
        
        # Test that each bandit learned user-specific preferences
        test_context = Context(
            features=np.array([0.7, 0.6, 0.8, 0.5]),  # Large dataset, good quality
            metadata={},
            timestamp=datetime.now()
        )
        
        user_preferences = {}
        for user in users:
            selections = []
            for _ in range(50):
                action_id, _ = bandits[user].select_arm(test_context, exploit=True)
                selections.append(action_id)
            
            # Get most preferred action
            most_selected = max(set(selections), key=selections.count)
            user_preferences[user] = most_selected
            
            print(f"{user} most prefers action {most_selected} ({self.actions[most_selected].name})")
        
        # Users should have learned different preferences
        unique_preferences = len(set(user_preferences.values()))
        assert unique_preferences >= 2  # At least some differentiation
    
    def test_bandit_persistence_and_recovery(self):
        """Test saving, loading, and recovery of bandit state."""
        # Train initial bandit
        original_bandit = ThompsonSampling(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions
        )
        
        reward_fn = self.create_realistic_reward_function()
        contexts = self.generate_realistic_contexts(50)
        
        for context in contexts:
            action_id, _ = original_bandit.select_arm(context)
            reward = reward_fn(context.features, action_id)
            original_bandit.update(context, action_id, reward)
        
        # Save state
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            original_bandit.save_state(filepath)
            
            # Create new bandit and load state
            loaded_bandit = ThompsonSampling(
                n_arms=self.n_arms,
                context_dim=self.context_dim,
                actions=self.actions
            )
            loaded_bandit.load_state(filepath)
            
            # Test that loaded bandit behaves identically
            test_contexts = self.generate_realistic_contexts(20, seed=999)
            
            original_selections = []
            loaded_selections = []
            
            for context in test_contexts:
                # Exploit mode for deterministic comparison
                orig_action, orig_info = original_bandit.select_arm(context, exploit=True)
                loaded_action, loaded_info = loaded_bandit.select_arm(context, exploit=True)
                
                original_selections.append(orig_action)
                loaded_selections.append(loaded_action)
                
                # Should make identical selections
                assert orig_action == loaded_action
                
                # Predicted rewards should be very similar
                orig_rewards = orig_info["predicted_rewards"]
                loaded_rewards = loaded_info["predicted_rewards"]
                
                for arm_id in orig_rewards:
                    assert abs(orig_rewards[arm_id] - loaded_rewards[arm_id]) < 1e-6
            
            # Continue training both bandits and verify they stay synchronized
            for context in test_contexts[:10]:
                action_id, _ = original_bandit.select_arm(context)
                reward = reward_fn(context.features, action_id)
                
                original_bandit.update(context, action_id, reward)
                loaded_bandit.update(context, action_id, reward)
                
                # Should still make same selections after updates
                new_context = test_contexts[-1]
                orig_action, _ = original_bandit.select_arm(new_context, exploit=True)
                loaded_action, _ = loaded_bandit.select_arm(new_context, exploit=True)
                assert orig_action == loaded_action
            
        finally:
            Path(filepath).unlink(missing_ok=True)
    
    def test_bandit_scalability_stress_test(self):
        """Test bandit performance under high load."""
        bandit = LinUCB(
            n_arms=self.n_arms,
            context_dim=self.context_dim,
            actions=self.actions,
            alpha=0.5
        )
        
        reward_fn = self.create_realistic_reward_function()
        
        # Generate large number of contexts
        large_contexts = self.generate_realistic_contexts(1000, seed=42)
        
        start_time = datetime.now()
        
        rewards = []
        selection_times = []
        update_times = []
        
        for i, context in enumerate(large_contexts):
            # Time arm selection
            select_start = datetime.now()
            action_id, _ = bandit.select_arm(context)
            select_time = (datetime.now() - select_start).total_seconds()
            selection_times.append(select_time)
            
            # Get reward
            reward = reward_fn(context.features, action_id)
            rewards.append(reward)
            
            # Time update
            update_start = datetime.now()
            bandit.update(context, action_id, reward)
            update_time = (datetime.now() - update_start).total_seconds()
            update_times.append(update_time)
            
            # Progress check
            if (i + 1) % 200 == 0:
                print(f"Processed {i + 1}/1000 contexts")
        
        total_time = (datetime.now() - start_time).total_seconds()
        
        # Performance analysis
        avg_select_time = np.mean(selection_times)
        avg_update_time = np.mean(update_times)
        avg_reward = np.mean(rewards)
        final_reward = np.mean(rewards[-100:])  # Last 100 episodes
        
        print(f"Scalability Test Results:")
        print(f"Total time: {total_time:.2f}s")
        print(f"Average selection time: {avg_select_time*1000:.2f}ms")
        print(f"Average update time: {avg_update_time*1000:.2f}ms")
        print(f"Average reward: {avg_reward:.3f}")
        print(f"Final reward: {final_reward:.3f}")
        
        # Performance requirements
        assert avg_select_time < 0.01  # Selection should be fast (<10ms)
        assert avg_update_time < 0.01   # Update should be fast (<10ms)
        assert total_time < 30          # Should complete in reasonable time
        
        # Learning requirements
        assert avg_reward > 0.5         # Should achieve reasonable performance
        assert final_reward > avg_reward * 0.9  # Should maintain or improve performance
        
        # Check memory usage doesn't explode
        stats = bandit.get_overall_statistics()
        assert stats["total_pulls"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])