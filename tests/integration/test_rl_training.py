"""Integration tests for RL training pipeline."""

import json
import pytest
import torch
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import tempfile
from unittest.mock import Mock, patch

from brain_researcher.services.agent.rl_optimizer import (
    RLOptimizer,
    IQLAgent,
    CQLAgent,
    State,
    Action,
    Transition,
    create_rl_optimizer
)


@pytest.mark.integration
class TestRLTrainingIntegration:
    """Integration tests for complete RL training pipeline."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.state_dim = 32
        self.action_dim = 8
        self.temp_dir = Path(tempfile.mkdtemp())
    
    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_sample_transitions(self, num_transitions: int = 200) -> List[Transition]:
        """Create sample transitions for testing."""
        transitions = []
        np.random.seed(42)  # For reproducible results
        
        for i in range(num_transitions):
            # Create state with some pattern
            state_vec = np.random.randn(self.state_dim - 8)  # Reserve space for features
            
            # Add some structured features
            dataset_features = np.array([
                np.random.uniform(1, 100),      # size_gb
                np.random.randint(10, 200),     # num_subjects
                np.random.randint(50, 500),     # num_sessions
                np.random.choice([0, 1])        # has_derivatives
            ])
            
            system_features = np.array([
                np.random.uniform(0, 100),      # cpu_percent
                np.random.uniform(0, 100),      # memory_percent
                np.random.uniform(0, 100),      # gpu_percent
                np.random.uniform(0, 20)        # queue_length
            ])
            
            full_state_vec = np.concatenate([state_vec, dataset_features, system_features])
            
            state = State(
                query_embedding=full_state_vec,
                dataset_features={
                    'size_gb': dataset_features[0],
                    'num_subjects': int(dataset_features[1]),
                    'num_sessions': int(dataset_features[2]),
                    'has_derivatives': dataset_features[3]
                },
                system_load={
                    'cpu_percent': system_features[0],
                    'memory_percent': system_features[1],
                    'gpu_percent': system_features[2],
                    'queue_length': system_features[3]
                },
                context_features={'priority': 'medium'}
            )
            
            # Create action
            action_idx = np.random.randint(0, self.action_dim)
            action = Action(
                tool_sequence=[f"tool_{action_idx}", "postprocess"],
                parameters={"param": f"value_{action_idx}"},
                resource_allocation={"cpu": 0.5, "memory": 0.3},
                parallelization_strategy="distributed" if action_idx % 2 == 0 else "serial"
            )
            
            # Mock action.to_index method
            action.to_index = Mock(return_value=action_idx)
            
            # Create reward with some pattern
            # Higher reward for certain state-action combinations
            base_reward = np.random.normal(0, 1)
            if state_vec[0] > 0 and action_idx < self.action_dim // 2:
                reward = base_reward + 1.0  # Bonus for good combination
            else:
                reward = base_reward
            
            # Create next state
            next_state_vec = np.random.randn(self.state_dim - 8)
            next_dataset_features = np.array([
                np.random.uniform(1, 100),
                np.random.randint(10, 200),
                np.random.randint(50, 500),
                np.random.choice([0, 1])
            ])
            next_system_features = np.array([
                np.random.uniform(0, 100),
                np.random.uniform(0, 100),
                np.random.uniform(0, 100),
                np.random.uniform(0, 20)
            ])
            
            next_full_state_vec = np.concatenate([
                next_state_vec, next_dataset_features, next_system_features
            ])
            
            next_state = State(
                query_embedding=next_full_state_vec,
                dataset_features={
                    'size_gb': next_dataset_features[0],
                    'num_subjects': int(next_dataset_features[1]),
                    'num_sessions': int(next_dataset_features[2]),
                    'has_derivatives': next_dataset_features[3]
                },
                system_load={
                    'cpu_percent': next_system_features[0],
                    'memory_percent': next_system_features[1],
                    'gpu_percent': next_system_features[2],
                    'queue_length': next_system_features[3]
                },
                context_features={'priority': 'medium'}
            )
            
            # Create transition
            transition = Transition(
                state=state,
                action=action,
                reward=reward,
                next_state=next_state,
                done=(i == num_transitions - 1),
                info={'execution_time': np.random.uniform(10, 300)}
            )
            
            transitions.append(transition)
        
        return transitions
    
    def test_iql_training_pipeline(self):
        """Test complete IQL training pipeline."""
        # Create optimizer
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            buffer_size=1000,
            model_dir=self.temp_dir / "iql_models"
        )
        
        # Generate training data
        transitions = self.create_sample_transitions(500)
        
        # Add experiences to buffer
        for transition in transitions:
            optimizer.add_experience(transition)
        
        # Verify buffer is populated
        assert len(optimizer.buffer) == 500
        
        # Train the agent
        stats = optimizer.train(
            num_epochs=20,
            batch_size=32,
            save_interval=10
        )
        
        # Verify training statistics
        assert len(stats) == 20
        assert all('epoch' in s for s in stats)
        assert all('q_loss' in s for s in stats)
        assert all('v_loss' in s for s in stats)
        
        # Check that losses are decreasing (at least not exploding)
        first_loss = stats[0]['q_loss']
        last_loss = stats[-1]['q_loss']
        assert np.isfinite(first_loss)
        assert np.isfinite(last_loss)
        assert last_loss < first_loss * 10  # Not exploding
        
        # Verify model files were saved
        model_files = list((self.temp_dir / "iql_models").glob("*.pt"))
        assert len(model_files) >= 2  # At least checkpoint and final
        
        # Test inference
        test_state = transitions[0].state
        test_actions = [t.action for t in transitions[:self.action_dim]]
        
        best_action, best_value = optimizer.optimize_plan(test_state, test_actions)
        
        assert isinstance(best_action, Action)
        assert isinstance(best_value, (int, float))
        assert np.isfinite(best_value)
    
    def test_cql_training_pipeline(self):
        """Test complete CQL training pipeline."""
        # Create optimizer
        optimizer = RLOptimizer(
            algorithm="cql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            buffer_size=1000,
            model_dir=self.temp_dir / "cql_models"
        )
        
        # Generate training data
        transitions = self.create_sample_transitions(500)
        
        # Add experiences to buffer
        for transition in transitions:
            optimizer.add_experience(transition)
        
        # Train the agent
        stats = optimizer.train(
            num_epochs=20,
            batch_size=32,
            save_interval=10
        )
        
        # Verify training statistics
        assert len(stats) == 20
        assert all('epoch' in s for s in stats)
        assert all('q_loss' in s for s in stats)
        assert all('td_loss' in s for s in stats)
        assert all('cql_loss' in s for s in stats)
        
        # Check CQL-specific metrics
        for stat in stats:
            assert stat['cql_loss'] >= 0  # CQL loss should be non-negative
            assert np.isfinite(stat['cql_loss'])
        
        # Test conservative behavior
        test_state = transitions[0].state
        test_actions = [t.action for t in transitions[:self.action_dim]]
        
        best_action, best_value = optimizer.optimize_plan(test_state, test_actions)
        
        assert isinstance(best_action, Action)
        assert isinstance(best_value, (int, float))
        # CQL values might be more conservative (lower)
        assert np.isfinite(best_value)
    
    def test_optimizer_persistence(self):
        """Test optimizer state persistence."""
        # Create and train first optimizer
        optimizer1 = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "persistence_test"
        )
        
        transitions = self.create_sample_transitions(100)
        for transition in transitions:
            optimizer1.add_experience(transition)
        
        # Train briefly
        stats1 = optimizer1.train(num_epochs=5, batch_size=16)
        
        # Save optimizer
        save_path = self.temp_dir / "persistence_test" / "saved_model.pt"
        optimizer1.save(save_path)
        
        # Create new optimizer and load
        optimizer2 = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "persistence_test"
        )
        optimizer2.load(save_path)
        
        # Verify loaded state
        assert len(optimizer2.buffer) == len(optimizer1.buffer)
        assert len(optimizer2.training_stats) == len(optimizer1.training_stats)
        
        # Test that inference produces same results
        test_state = transitions[0].state
        test_actions = [t.action for t in transitions[:self.action_dim]]
        
        action1, value1 = optimizer1.optimize_plan(test_state, test_actions)
        action2, value2 = optimizer2.optimize_plan(test_state, test_actions)
        
        # Should produce identical results
        assert action1.tool_sequence == action2.tool_sequence
        assert abs(value1 - value2) < 1e-6
    
    def test_performance_evaluation(self):
        """Test performance evaluation functionality."""
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "eval_test"
        )
        
        # Create training and test data
        train_transitions = self.create_sample_transitions(300)
        test_transitions = self.create_sample_transitions(50)
        
        # Train optimizer
        for transition in train_transitions:
            optimizer.add_experience(transition)
        
        optimizer.train(num_epochs=10, batch_size=32)
        
        # Evaluate performance
        performance = optimizer.evaluate_performance(test_transitions)
        
        # Verify performance metrics
        assert 'total_reward' in performance
        assert 'avg_reward' in performance
        assert 'avg_value' in performance
        assert 'value_std' in performance
        assert 'num_episodes' in performance
        
        assert performance['num_episodes'] == 50
        assert np.isfinite(performance['total_reward'])
        assert np.isfinite(performance['avg_reward'])
        assert np.isfinite(performance['avg_value'])
        assert performance['value_std'] >= 0
    
    def test_insufficient_data_handling(self):
        """Test handling of insufficient training data."""
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "insufficient_data"
        )
        
        # Add very few transitions
        transitions = self.create_sample_transitions(10)
        for transition in transitions:
            optimizer.add_experience(transition)
        
        # Try to train with insufficient data
        stats = optimizer.train(num_epochs=5, batch_size=32)
        
        # Should handle gracefully (return empty stats)
        assert len(stats) == 0
        
        # Warning should have been logged (but test continues)
    
    def test_online_learning_simulation(self):
        """Test simulation of online learning scenario."""
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "online_learning"
        )
        
        # Simulate online learning with periodic updates
        all_transitions = self.create_sample_transitions(1000)
        
        # Initial training
        initial_transitions = all_transitions[:200]
        for transition in initial_transitions:
            optimizer.add_experience(transition)
        
        optimizer.train(num_epochs=10, batch_size=32)
        
        # Simulate online updates
        batch_size = 50
        for i in range(200, 1000, batch_size):
            # Add new batch of experiences
            batch = all_transitions[i:i+batch_size]
            for transition in batch:
                optimizer.add_experience(transition)
            
            # Incremental training
            if i % 200 == 0:  # Train every 200 samples
                stats = optimizer.train(num_epochs=5, batch_size=32)
                
                if stats:  # If training occurred
                    assert len(stats) == 5
                    assert all(np.isfinite(s['q_loss']) for s in stats)
        
        # Final evaluation
        test_transitions = self.create_sample_transitions(50)
        performance = optimizer.evaluate_performance(test_transitions)
        
        assert performance['num_episodes'] == 50
        assert np.isfinite(performance['avg_reward'])
    
    def test_hyperparameter_sensitivity(self):
        """Test sensitivity to different hyperparameters."""
        configs = [
            {"algorithm": "iql", "state_dim": self.state_dim, "action_dim": self.action_dim},
            {"algorithm": "cql", "state_dim": self.state_dim, "action_dim": self.action_dim},
        ]
        
        transitions = self.create_sample_transitions(200)
        
        results = {}
        
        for i, config in enumerate(configs):
            config["model_dir"] = self.temp_dir / f"hyperparam_test_{i}"
            optimizer = create_rl_optimizer(config)
            
            # Add same data to all optimizers
            for transition in transitions:
                optimizer.add_experience(transition)
            
            # Train
            stats = optimizer.train(num_epochs=10, batch_size=32)
            
            if stats:  # If training occurred
                final_loss = stats[-1].get('q_loss', float('inf'))
                results[config['algorithm']] = final_loss
        
        # Both algorithms should achieve reasonable performance
        for algorithm, loss in results.items():
            print(f"{algorithm.upper()} final Q-loss: {loss:.4f}")
            assert np.isfinite(loss)
            assert loss < 100  # Reasonable magnitude
    
    def test_action_space_optimization(self):
        """Test optimization over different action spaces."""
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "action_space_test"
        )
        
        # Train optimizer
        transitions = self.create_sample_transitions(200)
        for transition in transitions:
            optimizer.add_experience(transition)
        
        optimizer.train(num_epochs=15, batch_size=32)
        
        # Test with different action spaces
        test_state = transitions[0].state
        
        # Small action space
        small_actions = [transitions[i].action for i in range(3)]
        best_action_small, value_small = optimizer.optimize_plan(test_state, small_actions)
        
        # Large action space
        large_actions = [transitions[i].action for i in range(min(10, len(transitions)))]
        best_action_large, value_large = optimizer.optimize_plan(test_state, large_actions)
        
        # Both should return valid actions
        assert best_action_small in small_actions
        assert best_action_large in large_actions
        
        # Values should be finite
        assert np.isfinite(value_small)
        assert np.isfinite(value_large)
        
        # Larger action space might have better value (more options)
        # But this isn't guaranteed due to approximation
        print(f"Small action space best value: {value_small:.4f}")
        print(f"Large action space best value: {value_large:.4f}")
    
    def test_training_convergence_monitoring(self):
        """Test monitoring of training convergence."""
        optimizer = RLOptimizer(
            algorithm="iql",
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            model_dir=self.temp_dir / "convergence_test"
        )
        
        # Create structured data for easier convergence
        np.random.seed(42)
        transitions = []
        
        for i in range(300):
            # Simple state with clear pattern
            state_vec = np.zeros(self.state_dim - 8)
            state_vec[0] = 1.0 if i % 2 == 0 else -1.0
            
            # Add features
            dataset_features = np.array([10.0, 50.0, 100.0, 1.0])
            system_features = np.array([50.0, 60.0, 30.0, 5.0])
            full_state_vec = np.concatenate([state_vec, dataset_features, system_features])
            
            state = State(
                query_embedding=full_state_vec,
                dataset_features={},
                system_load={},
                context_features={}
            )
            
            # Simple action selection
            action_idx = 0 if state_vec[0] > 0 else 1
            action = Action([f"tool_{action_idx}"], {}, {}, "serial")
            action.to_index = Mock(return_value=action_idx)
            
            # Reward based on state-action match
            reward = 1.0 if action_idx == (0 if state_vec[0] > 0 else 1) else -1.0
            
            # Simple next state
            next_state_vec = np.concatenate([np.random.randn(self.state_dim - 8), dataset_features, system_features])
            next_state = State(
                query_embedding=next_state_vec,
                dataset_features={},
                system_load={},
                context_features={}
            )
            
            transition = Transition(state, action, reward, next_state, False)
            transitions.append(transition)
        
        # Add transitions and train
        for transition in transitions:
            optimizer.add_experience(transition)
        
        stats = optimizer.train(num_epochs=30, batch_size=32)
        
        # Monitor convergence
        if stats:
            q_losses = [s['q_loss'] for s in stats]
            
            # Check that losses are generally decreasing or stabilizing
            early_avg = np.mean(q_losses[:5])
            late_avg = np.mean(q_losses[-5:])
            
            print(f"Early average Q-loss: {early_avg:.4f}")
            print(f"Late average Q-loss: {late_avg:.4f}")
            
            # Late losses should not be much higher than early ones
            assert late_avg < early_avg * 2.0  # Allow some variance
            
            # All losses should be finite
            assert all(np.isfinite(loss) for loss in q_losses)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])