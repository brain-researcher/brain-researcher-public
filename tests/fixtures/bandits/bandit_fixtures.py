"""Multi-armed bandit fixtures for comprehensive testing."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional, Callable
from dataclasses import dataclass
from scipy import stats
import json


@dataclass
class BanditArm:
    """Represents a bandit arm with its properties."""
    arm_id: str
    true_mean: float
    true_variance: float
    context_dependency: Dict[str, float]  # How arm performance varies with context
    drift_schedule: Optional[List[Tuple[int, float]]] = None  # (step, new_mean) pairs
    

@dataclass
class BanditContext:
    """Context information for contextual bandits."""
    features: np.ndarray
    metadata: Dict[str, Any]
    timestamp: datetime
    user_segment: str


@dataclass
class BanditAction:
    """Action taken by bandit algorithm."""
    arm_id: str
    confidence: float
    expected_reward: float
    exploration_bonus: float


@dataclass
class BanditReward:
    """Reward received from bandit action."""
    value: float
    arm_id: str
    context: Optional[BanditContext]
    timestamp: datetime
    is_delayed: bool = False


@pytest.fixture
def simple_bandit_arms():
    """Simple multi-armed bandit configuration."""
    return [
        BanditArm(
            arm_id='arm_0',
            true_mean=0.1,
            true_variance=0.02,
            context_dependency={}
        ),
        BanditArm(
            arm_id='arm_1', 
            true_mean=0.15,
            true_variance=0.025,
            context_dependency={}
        ),
        BanditArm(
            arm_id='arm_2',
            true_mean=0.12,
            true_variance=0.03,
            context_dependency={}
        ),
        BanditArm(
            arm_id='arm_3',
            true_mean=0.18,  # Best arm
            true_variance=0.04,
            context_dependency={}
        )
    ]


@pytest.fixture
def contextual_bandit_arms():
    """Contextual bandit configuration where performance depends on context."""
    return [
        BanditArm(
            arm_id='recommendation_algo_a',
            true_mean=0.12,
            true_variance=0.02,
            context_dependency={
                'user_age': 0.001,      # Young users prefer this slightly more
                'session_length': -0.0005,  # Performance decreases with longer sessions
                'is_weekend': 0.02      # Better performance on weekends
            }
        ),
        BanditArm(
            arm_id='recommendation_algo_b',
            true_mean=0.15,
            true_variance=0.03,
            context_dependency={
                'user_age': -0.0008,    # Older users prefer this less
                'session_length': 0.001,   # Performance increases with longer sessions
                'is_weekend': -0.01     # Worse performance on weekends
            }
        ),
        BanditArm(
            arm_id='recommendation_algo_c',
            true_mean=0.10,
            true_variance=0.025,
            context_dependency={
                'user_age': 0.0005,
                'session_length': 0.0002,
                'is_weekend': 0.005
            }
        )
    ]


@pytest.fixture
def drifting_bandit_arms():
    """Bandit arms with concept drift over time."""
    return [
        BanditArm(
            arm_id='stable_arm',
            true_mean=0.12,
            true_variance=0.02,
            context_dependency={},
            drift_schedule=None  # No drift
        ),
        BanditArm(
            arm_id='improving_arm',
            true_mean=0.08,
            true_variance=0.03,
            context_dependency={},
            drift_schedule=[
                (1000, 0.10),   # Improves after 1000 pulls
                (2000, 0.14),   # Improves further 
                (3000, 0.16)    # Becomes best arm
            ]
        ),
        BanditArm(
            arm_id='degrading_arm', 
            true_mean=0.18,
            true_variance=0.025,
            context_dependency={},
            drift_schedule=[
                (800, 0.15),    # Performance drops
                (1600, 0.12),   # Drops further
                (2400, 0.09)    # Becomes worst arm
            ]
        )
    ]


@pytest.fixture
def sample_contexts():
    """Sample contexts for contextual bandit testing."""
    np.random.seed(42)
    
    contexts = []
    for i in range(1000):
        # Generate realistic user features
        user_age = np.random.normal(35, 12)
        session_length = np.random.exponential(180)  # seconds
        is_weekend = np.random.choice([True, False], p=[0.3, 0.7])
        
        # Additional features
        time_of_day = np.random.randint(0, 24)
        device_type = np.random.choice(['mobile', 'desktop', 'tablet'], p=[0.6, 0.3, 0.1])
        user_segment = np.random.choice(['new', 'casual', 'power', 'premium'], p=[0.2, 0.4, 0.3, 0.1])
        
        features = np.array([
            user_age / 100,  # Normalized
            session_length / 1000,  # Normalized
            float(is_weekend),
            time_of_day / 24,
            {'mobile': 0, 'desktop': 1, 'tablet': 2}[device_type] / 2,
        ])
        
        contexts.append(BanditContext(
            features=features,
            metadata={
                'user_age': user_age,
                'session_length': session_length,
                'is_weekend': is_weekend,
                'time_of_day': time_of_day,
                'device_type': device_type
            },
            timestamp=datetime.now() - timedelta(seconds=i * 10),
            user_segment=user_segment
        ))
    
    return contexts


@pytest.fixture
def bandit_reward_functions():
    """Various reward functions for testing different bandit scenarios."""
    
    def bernoulli_reward(arm: BanditArm, context: Optional[BanditContext] = None, 
                        step: int = 0) -> float:
        """Bernoulli (binary) reward function."""
        # Base success probability
        prob = arm.true_mean
        
        # Apply context effects
        if context and arm.context_dependency:
            for feature, weight in arm.context_dependency.items():
                if feature in context.metadata:
                    prob += weight * context.metadata[feature]
        
        # Apply drift effects
        if arm.drift_schedule:
            for drift_step, new_mean in arm.drift_schedule:
                if step >= drift_step:
                    prob = new_mean
        
        prob = np.clip(prob, 0.001, 0.999)  # Avoid extreme probabilities
        return float(np.random.binomial(1, prob))
    
    def gaussian_reward(arm: BanditArm, context: Optional[BanditContext] = None,
                       step: int = 0) -> float:
        """Gaussian reward function."""
        mean = arm.true_mean
        
        # Apply context effects
        if context and arm.context_dependency:
            for feature, weight in arm.context_dependency.items():
                if feature in context.metadata:
                    mean += weight * context.metadata[feature]
        
        # Apply drift effects
        if arm.drift_schedule:
            for drift_step, new_mean in arm.drift_schedule:
                if step >= drift_step:
                    mean = new_mean
        
        std = np.sqrt(arm.true_variance)
        return np.random.normal(mean, std)
    
    def beta_reward(arm: BanditArm, context: Optional[BanditContext] = None,
                   step: int = 0) -> float:
        """Beta-distributed reward function."""
        # Convert mean/variance to alpha/beta parameters
        mean = arm.true_mean
        variance = arm.true_variance
        
        # Apply context effects to mean
        if context and arm.context_dependency:
            for feature, weight in arm.context_dependency.items():
                if feature in context.metadata:
                    mean += weight * context.metadata[feature]
        
        # Apply drift
        if arm.drift_schedule:
            for drift_step, new_mean in arm.drift_schedule:
                if step >= drift_step:
                    mean = new_mean
        
        mean = np.clip(mean, 0.001, 0.999)
        
        # Convert to beta parameters
        if variance >= mean * (1 - mean):
            variance = mean * (1 - mean) * 0.99  # Reduce variance if too high
        
        alpha = mean * (mean * (1 - mean) / variance - 1)
        beta = (1 - mean) * (mean * (1 - mean) / variance - 1)
        
        alpha = max(alpha, 0.1)  # Ensure positive parameters
        beta = max(beta, 0.1)
        
        return np.random.beta(alpha, beta)
    
    return {
        'bernoulli': bernoulli_reward,
        'gaussian': gaussian_reward, 
        'beta': beta_reward
    }


@pytest.fixture
def bandit_algorithms_config():
    """Configuration for various bandit algorithms."""
    return {
        'epsilon_greedy': {
            'epsilon': 0.1,
            'epsilon_decay': 0.99,
            'min_epsilon': 0.01,
            'initialization': 'optimistic'  # Start with high initial values
        },
        'ucb': {
            'confidence_level': 2.0,
            'initialization': 'zero',
            'time_horizon': 10000
        },
        'thompson_sampling': {
            'prior_alpha': 1.0,
            'prior_beta': 1.0,
            'update_rule': 'bayesian',
            'n_samples': 1000
        },
        'linear_ucb': {
            'alpha': 0.2,
            'feature_dim': 5,
            'regularization': 0.01,
            'confidence_scaling': 1.0
        },
        'contextual_thompson': {
            'prior_mean': np.zeros(5),
            'prior_cov': np.eye(5),
            'noise_var': 1.0,
            'n_samples': 100
        }
    }


@pytest.fixture
def evaluation_metrics_config():
    """Configuration for bandit evaluation metrics."""
    return {
        'regret': {
            'type': 'cumulative',
            'baseline': 'optimal_arm',
            'smoothing_window': 100
        },
        'simple_regret': {
            'type': 'instantaneous', 
            'evaluation_frequency': 100,
            'confidence_level': 0.95
        },
        'arm_selection_accuracy': {
            'optimal_arm_threshold': 0.95,  # 95% of optimal performance
            'evaluation_window': 500
        },
        'exploration_efficiency': {
            'metrics': ['arm_pull_distribution', 'exploration_rate'],
            'min_pulls_per_arm': 10
        },
        'adaptation_speed': {
            'drift_detection_delay': 100,  # Steps to detect drift
            'recovery_time': 500,  # Steps to recover performance
            'performance_threshold': 0.9
        }
    }


@pytest.fixture
def simulation_scenarios():
    """Various simulation scenarios for comprehensive testing."""
    return {
        'short_horizon': {
            'n_steps': 1000,
            'n_arms': 5,
            'reward_type': 'bernoulli',
            'difficulty': 'easy',  # Arms well-separated
            'context': False
        },
        'long_horizon': {
            'n_steps': 50000,
            'n_arms': 10,
            'reward_type': 'gaussian',
            'difficulty': 'medium',
            'context': False
        },
        'many_arms': {
            'n_steps': 10000,
            'n_arms': 100,
            'reward_type': 'beta',
            'difficulty': 'hard',  # Arms close together
            'context': False
        },
        'contextual_simple': {
            'n_steps': 5000,
            'n_arms': 3,
            'reward_type': 'bernoulli',
            'context_dim': 5,
            'context': True,
            'context_noise': 0.1
        },
        'contextual_complex': {
            'n_steps': 20000,
            'n_arms': 8,
            'reward_type': 'gaussian', 
            'context_dim': 20,
            'context': True,
            'context_noise': 0.2,
            'nonlinear_effects': True
        },
        'adversarial': {
            'n_steps': 5000,
            'n_arms': 4,
            'reward_type': 'adversarial',
            'switching_probability': 0.01,
            'context': False
        },
        'non_stationary': {
            'n_steps': 10000,
            'n_arms': 5,
            'drift_type': 'gradual',
            'drift_frequency': 2000,  # Drift every 2000 steps
            'drift_magnitude': 0.1
        }
    }


@pytest.fixture
def statistical_tests_config():
    """Configuration for statistical testing of bandit performance."""
    return {
        'confidence_intervals': {
            'methods': ['bootstrap', 'normal_approximation', 'wilson_score'],
            'confidence_levels': [0.90, 0.95, 0.99],
            'bootstrap_samples': 1000
        },
        'hypothesis_tests': {
            'arm_comparison': {
                'test': 'two_sample_t_test',
                'alpha': 0.05,
                'correction': 'bonferroni'  # Multiple comparisons
            },
            'optimality_test': {
                'test': 'one_sample_t_test', 
                'null_value': 'theoretical_optimal',
                'alpha': 0.05
            }
        },
        'effect_size_measures': {
            'cohens_d': True,
            'cliff_delta': True,
            'common_language_effect_size': True
        },
        'power_analysis': {
            'minimum_detectable_effect': 0.05,
            'desired_power': 0.8,
            'alpha': 0.05
        }
    }


@pytest.fixture
def benchmark_datasets():
    """Benchmark datasets for algorithm comparison."""
    
    def generate_benchmark(name: str, n_steps: int = 10000) -> Dict[str, Any]:
        """Generate a benchmark dataset."""
        np.random.seed(hash(name) % 2**32)  # Deterministic but different per benchmark
        
        if name == 'easy_binary':
            arms = [
                {'mean': 0.1, 'variance': 0.01},
                {'mean': 0.3, 'variance': 0.01},  # Clearly best
                {'mean': 0.15, 'variance': 0.01},
                {'mean': 0.2, 'variance': 0.01}
            ]
            reward_type = 'bernoulli'
            
        elif name == 'hard_gaussian':
            arms = [
                {'mean': 0.48, 'variance': 0.1},
                {'mean': 0.52, 'variance': 0.1},  # Barely best
                {'mean': 0.50, 'variance': 0.1},
                {'mean': 0.49, 'variance': 0.1}
            ]
            reward_type = 'gaussian'
            
        elif name == 'high_variance':
            arms = [
                {'mean': 0.2, 'variance': 0.5},
                {'mean': 0.3, 'variance': 0.5}, 
                {'mean': 0.25, 'variance': 0.5}
            ]
            reward_type = 'gaussian'
            
        elif name == 'many_arms_sparse':
            # 50 arms, only 1 is good
            arms = [{'mean': 0.05, 'variance': 0.01} for _ in range(49)]
            arms.append({'mean': 0.15, 'variance': 0.01})  # Single good arm
            reward_type = 'bernoulli'
        
        return {
            'name': name,
            'arms': arms,
            'n_steps': n_steps,
            'reward_type': reward_type,
            'optimal_arm': np.argmax([arm['mean'] for arm in arms]),
            'optimal_value': max(arm['mean'] for arm in arms)
        }
    
    return {
        'easy_binary': generate_benchmark('easy_binary'),
        'hard_gaussian': generate_benchmark('hard_gaussian'),
        'high_variance': generate_benchmark('high_variance'),
        'many_arms_sparse': generate_benchmark('many_arms_sparse', 50000)
    }


@pytest.fixture
def performance_test_data():
    """Data for testing bandit algorithm performance."""
    return {
        'scalability_test': {
            'arm_counts': [5, 10, 50, 100, 500],
            'context_dimensions': [0, 5, 10, 50, 100],
            'batch_sizes': [1, 10, 100, 1000],
            'target_latency_ms': {
                'arm_selection': 10,
                'batch_update': 100,
                'context_processing': 50
            }
        },
        'memory_usage': {
            'max_memory_mb': 500,
            'context_buffer_size': 10000,
            'model_size_limit_mb': 100,
            'memory_growth_rate': 0.01  # Per additional arm
        },
        'concurrent_bandits': {
            'num_bandits': 10,
            'requests_per_second': 1000,
            'shared_context': True,
            'isolation_requirements': True
        }
    }


@pytest.fixture
def edge_case_scenarios():
    """Edge cases for robust bandit testing."""
    return {
        'zero_variance_arm': {
            'arms': [
                {'mean': 0.1, 'variance': 0.0},  # Deterministic arm
                {'mean': 0.15, 'variance': 0.02}
            ],
            'expected_behavior': 'handle_gracefully'
        },
        'negative_rewards': {
            'arms': [
                {'mean': -0.5, 'variance': 0.1},
                {'mean': -0.2, 'variance': 0.1},  # Less negative = better
                {'mean': -0.8, 'variance': 0.1}
            ],
            'expected_behavior': 'find_best_negative'
        },
        'extreme_context': {
            'context_features': [1e6, -1e6, 0, np.inf, -np.inf],
            'expected_behavior': 'robust_handling'
        },
        'missing_rewards': {
            'missing_probability': 0.1,
            'missing_pattern': 'random',
            'expected_behavior': 'impute_or_skip'
        },
        'delayed_rewards': {
            'delay_distribution': 'exponential',
            'mean_delay_steps': 100,
            'max_delay_steps': 1000,
            'expected_behavior': 'handle_delayed_feedback'
        }
    }