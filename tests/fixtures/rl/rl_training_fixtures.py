"""Reinforcement Learning training fixtures for comprehensive testing."""

import pytest
import numpy as np
import torch
import torch.nn as nn
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from collections import deque


@dataclass
class State:
    """State representation for RL testing."""
    observation: np.ndarray
    metadata: Dict[str, Any]
    timestamp: datetime
    
    def to_tensor(self):
        return torch.FloatTensor(self.observation)


@dataclass
class Action:
    """Action representation for RL testing."""
    value: np.ndarray
    action_type: str
    confidence: float
    
    def to_tensor(self):
        return torch.FloatTensor(self.value)


@dataclass
class Transition:
    """Transition tuple for RL experience replay."""
    state: State
    action: Action
    reward: float
    next_state: Optional[State]
    done: bool
    info: Dict[str, Any]


@pytest.fixture
def sample_states():
    """Sample states for RL testing."""
    np.random.seed(42)
    
    states = []
    for i in range(100):
        observation = np.random.randn(10)  # 10-dimensional state space
        metadata = {
            'step': i,
            'episode': i // 20,
            'context': np.random.choice(['exploration', 'exploitation', 'evaluation']),
            'difficulty': np.random.uniform(0.1, 1.0)
        }
        
        states.append(State(
            observation=observation,
            metadata=metadata,
            timestamp=datetime.now() - timedelta(seconds=i)
        ))
    
    return states


@pytest.fixture  
def sample_actions():
    """Sample actions for RL testing."""
    np.random.seed(42)
    
    actions = []
    action_types = ['query_optimization', 'resource_allocation', 'parameter_tuning']
    
    for i in range(100):
        action_type = np.random.choice(action_types)
        
        if action_type == 'query_optimization':
            value = np.random.randint(0, 5, size=3)  # Discrete action space
        elif action_type == 'resource_allocation':
            value = np.random.dirichlet([1, 1, 1])   # Continuous action space (probabilities)
        else:  # parameter_tuning
            value = np.random.uniform(-1, 1, size=2)  # Continuous bounded action space
            
        actions.append(Action(
            value=value,
            action_type=action_type,
            confidence=np.random.uniform(0.5, 1.0)
        ))
    
    return actions


@pytest.fixture
def sample_transitions():
    """Sample transitions for experience replay testing."""
    np.random.seed(42)
    
    transitions = []
    
    for episode in range(10):
        episode_length = np.random.randint(10, 50)
        
        for step in range(episode_length):
            # Create state
            state_obs = np.random.randn(10)
            state = State(
                observation=state_obs,
                metadata={'episode': episode, 'step': step},
                timestamp=datetime.now() - timedelta(seconds=episode*100 + step)
            )
            
            # Create action
            action = Action(
                value=np.random.uniform(-1, 1, size=3),
                action_type='continuous',
                confidence=np.random.uniform(0.6, 1.0)
            )
            
            # Calculate reward (mock reward function)
            base_reward = np.sum(state_obs[:3] * action.value)
            noise = np.random.normal(0, 0.1)
            reward = base_reward + noise
            
            # Create next state (or None if terminal)
            if step == episode_length - 1:
                next_state = None
                done = True
            else:
                next_state_obs = state_obs + np.random.randn(10) * 0.1  # Small transition
                next_state = State(
                    observation=next_state_obs,
                    metadata={'episode': episode, 'step': step + 1},
                    timestamp=datetime.now() - timedelta(seconds=episode*100 + step + 1)
                )
                done = False
            
            transitions.append(Transition(
                state=state,
                action=action,
                reward=reward,
                next_state=next_state,
                done=done,
                info={'episode_reward': np.random.uniform(0, 100)}
            ))
    
    return transitions


@pytest.fixture
def mock_environments():
    """Mock environments for RL testing."""
    
    class MockDiscreteEnv:
        """Mock discrete action environment."""
        
        def __init__(self):
            self.state_dim = 8
            self.action_dim = 4
            self.max_steps = 50
            self.current_step = 0
            self.state = self.reset()
            
        def reset(self):
            self.current_step = 0
            self.state = np.random.randn(self.state_dim)
            return self.state
            
        def step(self, action):
            self.current_step += 1
            
            # Mock dynamics
            noise = np.random.randn(self.state_dim) * 0.1
            self.state = self.state + noise
            
            # Mock reward function
            reward = -np.sum(self.state**2) - 0.01 * action  # Negative quadratic cost
            
            done = self.current_step >= self.max_steps or np.sum(self.state**2) > 100
            
            info = {'step': self.current_step, 'state_norm': np.linalg.norm(self.state)}
            
            return self.state, reward, done, info
    
    class MockContinuousEnv:
        """Mock continuous action environment."""
        
        def __init__(self):
            self.state_dim = 6
            self.action_dim = 2
            self.max_steps = 100
            self.current_step = 0
            self.target = np.array([1.0, -0.5])  # Target state
            self.state = self.reset()
            
        def reset(self):
            self.current_step = 0
            self.state = np.random.uniform(-2, 2, self.state_dim)
            return self.state
            
        def step(self, action):
            self.current_step += 1
            
            # Mock dynamics with action influence
            action = np.clip(action, -1, 1)  # Bounded actions
            self.state[:2] += action * 0.1
            self.state[2:] += np.random.randn(4) * 0.05
            
            # Reward based on distance to target
            distance = np.linalg.norm(self.state[:2] - self.target)
            reward = -distance - 0.001 * np.sum(action**2)  # Distance penalty + action cost
            
            done = self.current_step >= self.max_steps or distance < 0.1
            
            info = {
                'step': self.current_step, 
                'distance_to_target': distance,
                'action_magnitude': np.linalg.norm(action)
            }
            
            return self.state, reward, done, info
    
    return {
        'discrete': MockDiscreteEnv(),
        'continuous': MockContinuousEnv()
    }


@pytest.fixture
def neural_network_architectures():
    """Various neural network architectures for testing."""
    
    class SimpleQNetwork(nn.Module):
        """Simple Q-network for discrete actions."""
        
        def __init__(self, state_dim=8, action_dim=4, hidden_dim=64):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, action_dim)
            )
            
        def forward(self, x):
            return self.network(x)
    
    class PolicyNetwork(nn.Module):
        """Policy network for continuous actions."""
        
        def __init__(self, state_dim=6, action_dim=2, hidden_dim=64):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU()
            )
            
            self.mean_head = nn.Linear(hidden_dim, action_dim)
            self.log_std_head = nn.Linear(hidden_dim, action_dim)
            
        def forward(self, x):
            shared_features = self.shared(x)
            mean = torch.tanh(self.mean_head(shared_features))  # Bounded actions
            log_std = self.log_std_head(shared_features)
            log_std = torch.clamp(log_std, -10, 2)  # Limit std range
            
            return mean, log_std
    
    class ValueNetwork(nn.Module):
        """Value network for state value estimation."""
        
        def __init__(self, state_dim=6, hidden_dim=64):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, 1)
            )
            
        def forward(self, x):
            return self.network(x)
    
    class CriticNetwork(nn.Module):
        """Critic network for actor-critic methods."""
        
        def __init__(self, state_dim=6, action_dim=2, hidden_dim=64):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(state_dim + action_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, 1)
            )
            
        def forward(self, state, action):
            x = torch.cat([state, action], dim=-1)
            return self.network(x)
    
    return {
        'q_network': SimpleQNetwork,
        'policy_network': PolicyNetwork,
        'value_network': ValueNetwork,
        'critic_network': CriticNetwork
    }


@pytest.fixture
def training_configurations():
    """Various training configurations for testing."""
    return {
        'dqn_config': {
            'algorithm': 'DQN',
            'learning_rate': 0.001,
            'batch_size': 32,
            'buffer_size': 10000,
            'target_update_freq': 100,
            'epsilon_start': 1.0,
            'epsilon_end': 0.01,
            'epsilon_decay': 1000,
            'gamma': 0.99,
            'double_q': True
        },
        'iql_config': {
            'algorithm': 'IQL',
            'learning_rate': 0.0003,
            'batch_size': 256,
            'buffer_size': 50000,
            'tau': 0.7,  # IQL temperature parameter
            'beta': 3.0,  # Advantage weight
            'gamma': 0.99,
            'target_update_rate': 0.005,
            'expectile': 0.8
        },
        'cql_config': {
            'algorithm': 'CQL',
            'learning_rate': 0.0003,
            'batch_size': 256,
            'buffer_size': 100000,
            'cql_alpha': 1.0,  # CQL regularization weight
            'target_update_rate': 0.005,
            'gamma': 0.99,
            'min_q_weight': 1.0,
            'temp': 1.0
        },
        'offline_config': {
            'algorithm': 'Offline',
            'dataset_size': 100000,
            'behavior_policy': 'random',
            'learning_rate': 0.0003,
            'batch_size': 256,
            'num_epochs': 100,
            'validation_split': 0.2
        }
    }


@pytest.fixture
def evaluation_scenarios():
    """Scenarios for evaluating RL algorithms."""
    return {
        'standard_evaluation': {
            'num_episodes': 100,
            'max_steps_per_episode': 200,
            'metrics': ['episode_return', 'episode_length', 'success_rate'],
            'deterministic': True,  # Use deterministic policy for evaluation
            'render': False
        },
        'curriculum_evaluation': {
            'difficulty_levels': [0.1, 0.3, 0.5, 0.7, 1.0],
            'episodes_per_level': 20,
            'success_threshold': 0.8,
            'metrics': ['success_rate_per_level', 'transfer_performance']
        },
        'robustness_testing': {
            'noise_levels': [0.0, 0.1, 0.2, 0.5],
            'episodes_per_noise': 50,
            'noise_type': 'gaussian',
            'metrics': ['performance_degradation', 'stability']
        },
        'online_adaptation': {
            'environment_changes': [
                {'step': 1000, 'change': 'reward_scaling', 'factor': 0.5},
                {'step': 2000, 'change': 'dynamics_shift', 'magnitude': 0.2},
                {'step': 3000, 'change': 'observation_noise', 'std': 0.1}
            ],
            'adaptation_window': 500,
            'metrics': ['adaptation_speed', 'final_performance']
        }
    }


@pytest.fixture
def hyperparameter_search_spaces():
    """Hyperparameter search spaces for optimization."""
    return {
        'learning_rate_search': {
            'type': 'log_uniform',
            'low': 1e-5,
            'high': 1e-2,
            'n_samples': 20
        },
        'architecture_search': {
            'hidden_dims': [32, 64, 128, 256],
            'num_layers': [2, 3, 4],
            'activation': ['relu', 'tanh', 'elu'],
            'dropout_rate': [0.0, 0.1, 0.2, 0.3]
        },
        'regularization_search': {
            'l2_weight': [0.0, 1e-5, 1e-4, 1e-3],
            'gradient_clip': [0.5, 1.0, 2.0, 5.0],
            'batch_norm': [True, False],
            'layer_norm': [True, False]
        },
        'algorithm_specific': {
            'iql': {
                'tau': [0.5, 0.6, 0.7, 0.8, 0.9],
                'beta': [1.0, 3.0, 10.0, 30.0],
                'expectile': [0.7, 0.8, 0.9, 0.95]
            },
            'cql': {
                'alpha': [0.1, 1.0, 5.0, 10.0],
                'min_q_weight': [0.1, 1.0, 10.0],
                'temperature': [0.1, 1.0, 10.0]
            }
        }
    }


@pytest.fixture
def convergence_test_data():
    """Data for testing training convergence."""
    
    def generate_learning_curve(algorithm_type='stable', num_steps=10000):
        """Generate synthetic learning curves."""
        steps = np.arange(num_steps)
        
        if algorithm_type == 'stable':
            # Smooth convergence
            returns = -10 * np.exp(-steps / 2000) + 50 + np.random.normal(0, 1, num_steps)
            
        elif algorithm_type == 'unstable':
            # Oscillating convergence
            returns = 40 + 10 * np.sin(steps / 500) * np.exp(-steps / 5000) + np.random.normal(0, 2, num_steps)
            
        elif algorithm_type == 'divergent':
            # Diverging performance
            returns = 30 - steps / 1000 + np.random.normal(0, 1, num_steps)
            
        elif algorithm_type == 'plateau':
            # Early plateau
            returns = 40 * (1 - np.exp(-steps / 1000)) + np.random.normal(0, 1, num_steps)
            returns[steps > 3000] = 38 + np.random.normal(0, 1, sum(steps > 3000))
            
        else:  # 'noisy'
            returns = 35 + np.random.normal(0, 5, num_steps)
        
        return list(zip(steps, returns))
    
    return {
        'stable_convergence': generate_learning_curve('stable'),
        'unstable_convergence': generate_learning_curve('unstable'),
        'divergent_training': generate_learning_curve('divergent'),
        'early_plateau': generate_learning_curve('plateau'),
        'high_variance': generate_learning_curve('noisy')
    }


@pytest.fixture
def offline_datasets():
    """Offline datasets for batch RL testing."""
    np.random.seed(42)
    
    def generate_dataset(quality='mixed', size=10000):
        """Generate offline dataset with varying quality."""
        
        states = np.random.randn(size, 8)
        actions = np.random.randint(0, 4, size)
        rewards = np.random.randn(size)
        next_states = states + np.random.randn(size, 8) * 0.1
        dones = np.random.choice([True, False], size, p=[0.05, 0.95])
        
        if quality == 'expert':
            # High-quality expert demonstrations
            rewards = np.abs(rewards) + 5  # Higher rewards
            actions = np.where(rewards > 6, actions, np.random.randint(0, 4, size))  # Better actions
            
        elif quality == 'random':
            # Random policy data
            rewards = np.random.uniform(-1, 1, size)
            
        elif quality == 'mixed':
            # Mix of good and bad data
            expert_mask = np.random.choice([True, False], size, p=[0.3, 0.7])
            rewards[expert_mask] = np.abs(rewards[expert_mask]) + 3
            rewards[~expert_mask] = -np.abs(rewards[~expert_mask])
            
        return {
            'states': states,
            'actions': actions,
            'rewards': rewards,
            'next_states': next_states,
            'dones': dones,
            'dataset_info': {
                'size': size,
                'quality': quality,
                'mean_reward': np.mean(rewards),
                'return_distribution': np.histogram(rewards, bins=20)
            }
        }
    
    return {
        'expert_data': generate_dataset('expert', 5000),
        'random_data': generate_dataset('random', 10000),
        'mixed_data': generate_dataset('mixed', 20000)
    }


@pytest.fixture
def performance_benchmarks():
    """Performance benchmarks for RL training."""
    return {
        'training_speed': {
            'steps_per_second': 1000,
            'samples_per_update': 256,
            'gpu_memory_usage_gb': 2.0,
            'cpu_utilization_percent': 70
        },
        'convergence_criteria': {
            'min_episodes': 100,
            'success_threshold': 0.8,
            'stability_window': 100,
            'max_training_time_hours': 12
        },
        'memory_efficiency': {
            'buffer_memory_gb': 1.0,
            'model_size_mb': 50,
            'batch_processing_time_ms': 100
        },
        'scalability_targets': {
            'parallel_environments': 16,
            'distributed_workers': 4,
            'maximum_buffer_size': 1000000,
            'checkpoint_frequency': 1000
        }
    }