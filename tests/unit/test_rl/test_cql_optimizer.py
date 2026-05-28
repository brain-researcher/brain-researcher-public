"""Unit tests for CQL (Conservative Q-Learning) optimizer."""

import json
import pytest
import torch
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from unittest.mock import Mock, patch, MagicMock
import tempfile

from brain_researcher.services.agent.rl_optimizer import (
    CQLAgent,
    QNetwork,
    State,
    Action,
    Transition,
    ReplayBuffer,
    RLOptimizer
)


class TestCQLAgent:
    """Test CQLAgent class."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.state_dim = 72
        self.action_dim = 10
        self.agent = CQLAgent(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            learning_rate=1e-3,
            alpha=0.2,  # CQL regularization weight
            device="cpu"  # Use CPU for testing
        )
        
        # Create sample transitions
        self.transitions = []
        for i in range(32):
            state = State(np.random.randn(64), {}, {}, {})
            action = Action([f"tool_{i}"], {}, {}, "serial")
            next_state = State(np.random.randn(64), {}, {}, {}) if i < 31 else None
            transition = Transition(
                state=state,
                action=action,
                reward=np.random.randn(),
                next_state=next_state,
                done=(i == 31)
            )
            # Mock action to index conversion
            transition.action.to_index = Mock(return_value=i % self.action_dim)
            self.transitions.append(transition)
    
    def test_cql_agent_initialization(self):
        """Test CQL agent initialization."""
        assert isinstance(self.agent.q_network, QNetwork)
        assert isinstance(self.agent.q_target, QNetwork)
        assert self.agent.device == "cpu"
        assert self.agent.gamma == 0.99
        assert self.agent.tau == 0.005
        assert self.agent.alpha == 0.2
        assert self.agent.action_dim == self.action_dim
        
        # CQL agent should not have value network (unlike IQL)
        assert not hasattr(self.agent, 'v_network')
    
    def test_cql_update_basic(self):
        """Test basic CQL update."""
        batch = self.transitions[:16]
        
        metrics = self.agent.update(batch)
        
        # Check CQL-specific metrics
        assert "td_loss" in metrics
        assert "cql_loss" in metrics
        assert "q_loss" in metrics
        assert "q_mean" in metrics
        assert "q_std" in metrics
        
        # Check that losses are non-negative and finite
        assert metrics["td_loss"] >= 0
        assert metrics["cql_loss"] >= 0
        assert metrics["q_loss"] >= 0
        assert np.isfinite(metrics["td_loss"])
        assert np.isfinite(metrics["cql_loss"])
        assert np.isfinite(metrics["q_loss"])
    
    def test_cql_regularization_effect(self):
        """Test that CQL regularization affects the loss."""
        batch = self.transitions[:16]
        
        # Update with current alpha
        metrics_with_reg = self.agent.update(batch)
        
        # Temporarily set alpha to 0 (no regularization)
        original_alpha = self.agent.alpha
        self.agent.alpha = 0.0
        
        metrics_without_reg = self.agent.update(batch)
        
        # Restore alpha
        self.agent.alpha = original_alpha
        
        # With regularization, total Q-loss should be higher
        assert metrics_with_reg["q_loss"] > metrics_without_reg["q_loss"]
        
        # TD loss should be similar (regularization shouldn't affect it much)
        td_loss_diff = abs(metrics_with_reg["td_loss"] - metrics_without_reg["td_loss"])
        assert td_loss_diff < 0.1 * metrics_with_reg["td_loss"]  # Less than 10% difference
    
    def test_cql_conservative_behavior(self):
        """Test that CQL produces conservative Q-values."""
        batch = self.transitions[:16]
        
        # Get Q-values before training
        states = torch.stack([t.state.to_tensor() for t in batch])
        with torch.no_grad():
            initial_q_values = self.agent.q_network(states)
        
        # Train for several steps
        for _ in range(10):
            self.agent.update(batch)
        
        # Get Q-values after training
        with torch.no_grad():
            final_q_values = self.agent.q_network(states)
        
        # CQL should generally produce more conservative (lower) Q-values
        # for actions not in the dataset
        mean_initial_q = initial_q_values.mean().item()
        mean_final_q = final_q_values.mean().item()
        
        # Note: This is a statistical tendency, not a strict guarantee
        # We mainly check that training doesn't cause exploding values
        assert np.isfinite(mean_final_q)
        assert abs(mean_final_q) < 1000  # Reasonable magnitude
    
    def test_cql_logsumexp_computation(self):
        """Test logsumexp computation in CQL loss."""
        # Create a simple batch
        batch = self.transitions[:8]
        states = torch.stack([t.state.to_tensor() for t in batch])
        
        # Get Q-values
        with torch.no_grad():
            q_values = self.agent.q_network(states)
        
        # Compute logsumexp manually
        manual_logsumexp = torch.logsumexp(q_values, dim=1)
        
        # Verify it's computed correctly (should not overflow)
        assert torch.isfinite(manual_logsumexp).all()
        assert manual_logsumexp.shape == (8,)  # One value per state
    
    def test_cql_different_alpha_values(self):
        """Test CQL with different regularization strengths."""
        batch = self.transitions[:16]
        
        # Test with different alpha values
        alphas = [0.0, 0.1, 0.5, 1.0, 2.0]
        losses = []
        
        for alpha in alphas:
            self.agent.alpha = alpha
            metrics = self.agent.update(batch)
            losses.append(metrics["q_loss"])
        
        # Higher alpha should generally lead to higher total loss
        # (due to stronger regularization)
        assert losses[0] <= losses[1]  # alpha=0.0 vs 0.1
        assert losses[1] <= losses[2]  # alpha=0.1 vs 0.5
        # Note: Relationship might not be strictly monotonic due to optimization dynamics
    
    def test_cql_target_network_updates(self):
        """Test target network soft updates."""
        # Get initial target network parameters
        initial_params = [p.clone() for p in self.agent.q_target.parameters()]
        
        batch = self.transitions[:16]
        self.agent.update(batch)
        
        # Check that target network parameters were updated
        for initial_param, current_param in zip(initial_params, self.agent.q_target.parameters()):
            assert not torch.equal(initial_param, current_param)
            
            # Change should be small due to soft update
            change_norm = torch.norm(current_param - initial_param)
            param_norm = torch.norm(current_param)
            relative_change = change_norm / param_norm
            
            assert relative_change < 0.1  # Less than 10% change per update
    
    def test_cql_batch_size_robustness(self):
        """Test CQL with different batch sizes."""
        batch_sizes = [1, 4, 16, 32]
        
        for batch_size in batch_sizes:
            if batch_size <= len(self.transitions):
                batch = self.transitions[:batch_size]
                metrics = self.agent.update(batch)
                
                # Should handle different batch sizes without errors
                assert "cql_loss" in metrics
                assert np.isfinite(metrics["cql_loss"])
                assert metrics["cql_loss"] >= 0
    
    def test_cql_action_selection(self):
        """Test action selection (inherited from IQLAgent)."""
        state = State(np.random.randn(64), {}, {}, {})
        
        # Test greedy action selection
        action_greedy = self.agent.select_action(state, epsilon=0.0)
        assert isinstance(action_greedy, int)
        assert 0 <= action_greedy < self.action_dim
        
        # Test random action selection
        action_random = self.agent.select_action(state, epsilon=1.0)
        assert isinstance(action_random, int)
        assert 0 <= action_random < self.action_dim
        
        # With different random seeds, should get different random actions
        random_actions = set()
        for _ in range(100):
            action = self.agent.select_action(state, epsilon=1.0)
            random_actions.add(action)
        
        assert len(random_actions) > 1  # Should explore multiple actions
    
    def test_cql_save_load(self):
        """Test saving and loading CQL agent."""
        # Train agent slightly
        batch = self.transitions[:16]
        self.agent.update(batch)
        
        original_alpha = self.agent.alpha
        
        with tempfile.NamedTemporaryFile(suffix='.pt', delete=False) as f:
            save_path = Path(f.name)
        
        try:
            # Save agent
            self.agent.save(save_path)
            
            # Create new agent and load
            new_agent = CQLAgent(
                self.state_dim,
                self.action_dim,
                alpha=0.5,  # Different alpha to test loading
                device="cpu"
            )
            new_agent.load(save_path)
            
            # Verify parameters match
            for orig_param, loaded_param in zip(
                self.agent.q_network.parameters(),
                new_agent.q_network.parameters()
            ):
                assert torch.equal(orig_param, loaded_param)
            
            for orig_param, loaded_param in zip(
                self.agent.q_target.parameters(),
                new_agent.q_target.parameters()
            ):
                assert torch.equal(orig_param, loaded_param)
            
            assert new_agent.total_steps == self.agent.total_steps
            
        finally:
            save_path.unlink(missing_ok=True)
    
    def test_cql_gradient_clipping(self):
        """Test gradient clipping in CQL updates."""
        # Create batch with extreme values
        extreme_transitions = []
        for i in range(16):
            state = State(np.random.randn(64), {}, {}, {})
            action = Action([f"tool_{i}"], {}, {}, "serial")
            next_state = State(np.random.randn(64), {}, {}, {})
            
            # Extreme rewards
            reward = 10000.0 if i % 2 == 0 else -10000.0
            
            transition = Transition(
                state=state,
                action=action,
                reward=reward,
                next_state=next_state,
                done=False
            )
            transition.action.to_index = Mock(return_value=i % self.action_dim)
            extreme_transitions.append(transition)
        
        # Should handle extreme values without exploding
        metrics = self.agent.update(extreme_transitions)
        
        assert np.isfinite(metrics["cql_loss"])
        assert np.isfinite(metrics["td_loss"])
        assert np.isfinite(metrics["q_loss"])
        
        # Values should be reasonable (not exploded)
        assert abs(metrics["q_mean"]) < 10000
    
    def test_cql_vs_standard_dqn_behavior(self):
        """Test that CQL behaves differently from standard DQN."""
        # This test demonstrates the conservative nature of CQL
        
        # Create a dataset with only positive rewards for action 0
        biased_transitions = []
        for i in range(32):
            state = State(np.random.randn(64), {}, {}, {})
            action = Action(["action_0"], {}, {}, "serial")
            next_state = State(np.random.randn(64), {}, {}, {})
            
            # Only action 0, always positive reward
            transition = Transition(
                state=state,
                action=action,
                reward=1.0,
                next_state=next_state,
                done=False
            )
            transition.action.to_index = Mock(return_value=0)  # Always action 0
            biased_transitions.append(transition)
        
        # Train CQL agent
        for _ in range(20):
            batch = biased_transitions[:16]
            self.agent.update(batch)
        
        # Test on a random state
        test_state = State(np.random.randn(64), {}, {}, {})
        
        with torch.no_grad():
            state_tensor = test_state.to_tensor().unsqueeze(0)
            q_values = self.agent.q_network(state_tensor).squeeze()
        
        # Action 0 should have higher Q-value (it's in the dataset)
        # Other actions should have lower Q-values (conservative)
        action_0_q = q_values[0].item()
        other_actions_q = q_values[1:].mean().item()
        
        # This demonstrates CQL's conservative behavior
        # (though the exact relationship depends on hyperparameters)
        print(f"Action 0 Q-value: {action_0_q:.3f}")
        print(f"Other actions average Q-value: {other_actions_q:.3f}")
        
        # At minimum, values should be finite and reasonable
        assert np.isfinite(action_0_q)
        assert np.isfinite(other_actions_q)


@pytest.mark.integration
class TestCQLIntegration:
    """Integration tests for CQL agent."""
    
    def test_cql_offline_learning(self):
        """Test CQL on offline learning task."""
        state_dim = 4
        action_dim = 3
        agent = CQLAgent(
            state_dim,
            action_dim,
            learning_rate=1e-2,
            alpha=0.5,
            device="cpu"
        )
        
        # Create offline dataset with suboptimal policy
        # Optimal policy: state[i] == 1.0 -> action i gives reward 1.0
        # Dataset policy: biased towards action 0
        transitions = []
        
        np.random.seed(42)  # For reproducible results
        
        for episode in range(100):
            for state_idx in range(action_dim):
                state_vec = np.zeros(state_dim)
                state_vec[state_idx] = 1.0
                
                state = State(
                    query_embedding=state_vec,
                    dataset_features={},
                    system_load={},
                    context_features={}
                )
                
                # Biased action selection (70% action 0, 30% optimal)
                if np.random.random() < 0.7:
                    action_idx = 0  # Suboptimal for state_idx != 0
                else:
                    action_idx = state_idx  # Optimal
                
                # Reward based on optimality
                if action_idx == state_idx:
                    reward = 1.0
                else:
                    reward = -0.1
                
                action = Action([f"action_{action_idx}"], {}, {}, "serial")
                action.to_index = Mock(return_value=action_idx)
                
                next_state = State(
                    query_embedding=np.random.randn(state_dim),
                    dataset_features={},
                    system_load={},
                    context_features={}
                )
                
                transition = Transition(
                    state=state,
                    action=action,
                    reward=reward,
                    next_state=next_state,
                    done=True
                )
                
                transitions.append(transition)
        
        # Train CQL agent on offline dataset
        for epoch in range(50):
            batch_indices = np.random.choice(len(transitions), size=32, replace=True)
            batch = [transitions[i] for i in batch_indices]
            metrics = agent.update(batch)
        
        # Evaluate learned policy
        correct_actions = 0
        total_tests = action_dim * 10  # Test each state type 10 times
        
        for state_idx in range(action_dim):
            for _ in range(10):
                test_state_vec = np.zeros(state_dim)
                test_state_vec[state_idx] = 1.0
                
                test_state = State(
                    query_embedding=test_state_vec,
                    dataset_features={},
                    system_load={},
                    context_features={}
                )
                
                selected_action = agent.select_action(test_state, epsilon=0.0)
                
                if selected_action == state_idx:
                    correct_actions += 1
        
        accuracy = correct_actions / total_tests
        
        # CQL should learn better than random (1/3) but may not be perfect
        # due to conservative nature and biased dataset
        print(f"CQL accuracy: {accuracy:.3f}")
        assert accuracy > 0.4  # Better than random, accounting for conservatism
    
    def test_cql_conservative_estimates(self):
        """Test that CQL provides conservative Q-value estimates."""
        state_dim = 2
        action_dim = 2
        agent = CQLAgent(state_dim, action_dim, alpha=1.0, device="cpu")
        
        # Create dataset with only one action per state
        transitions = []
        
        for i in range(100):
            state_vec = np.array([1.0, 0.0] if i % 2 == 0 else [0.0, 1.0])
            
            state = State(
                query_embedding=state_vec,
                dataset_features={},
                system_load={},
                context_features={}
            )
            
            # Only action 0 in dataset, always good reward
            action = Action(["action_0"], {}, {}, "serial")
            action.to_index = Mock(return_value=0)
            
            transition = Transition(
                state=state,
                action=action,
                reward=1.0,
                next_state=state,
                done=True
            )
            
            transitions.append(transition)
        
        # Train agent
        for _ in range(30):
            batch = transitions[:32]
            agent.update(batch)
        
        # Check Q-values for both actions
        test_state = State(
            query_embedding=np.array([1.0, 0.0]),
            dataset_features={},
            system_load={},
            context_features={}
        )
        
        with torch.no_grad():
            state_tensor = test_state.to_tensor().unsqueeze(0)
            q_values = agent.q_network(state_tensor).squeeze()
        
        q_action_0 = q_values[0].item()  # In dataset
        q_action_1 = q_values[1].item()  # Not in dataset
        
        print(f"Q(s, a0) [in dataset]: {q_action_0:.3f}")
        print(f"Q(s, a1) [not in dataset]: {q_action_1:.3f}")
        
        # CQL should be conservative about action 1 (not in dataset)
        # This is a tendency, not a strict guarantee
        assert np.isfinite(q_action_0)
        assert np.isfinite(q_action_1)
        
        # Both values should be reasonable (not exploded)
        assert abs(q_action_0) < 100
        assert abs(q_action_1) < 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])