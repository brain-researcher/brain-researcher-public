"""A/B Testing fixtures for comprehensive testing."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any
import json


@pytest.fixture
def sample_ab_experiments():
    """Sample A/B testing experiments."""
    return [
        {
            'experiment_id': 'exp_001',
            'name': 'Search UI Redesign',
            'description': 'Testing new search interface design',
            'hypothesis': 'New search UI will increase query completion rate',
            'variants': [
                {'id': 'control', 'name': 'Current UI', 'traffic_allocation': 0.5},
                {'id': 'treatment', 'name': 'New Search UI', 'traffic_allocation': 0.5}
            ],
            'success_metrics': ['query_completion_rate', 'time_to_result'],
            'sample_size': 1000,
            'confidence_level': 0.95,
            'power': 0.8,
            'start_date': '2025-01-01',
            'end_date': '2025-01-31',
            'status': 'running'
        },
        {
            'experiment_id': 'exp_002',
            'name': 'Result Display Format',
            'description': 'Testing card vs list view for results',
            'hypothesis': 'Card view will improve user engagement',
            'variants': [
                {'id': 'control', 'name': 'List View', 'traffic_allocation': 0.6},
                {'id': 'treatment', 'name': 'Card View', 'traffic_allocation': 0.4}
            ],
            'success_metrics': ['click_through_rate', 'session_duration'],
            'sample_size': 1500,
            'confidence_level': 0.99,
            'power': 0.85,
            'start_date': '2025-01-15',
            'end_date': '2025-02-15',
            'status': 'completed'
        }
    ]


@pytest.fixture
def sample_user_assignments():
    """Sample user assignments for A/B tests."""
    np.random.seed(42)  # For reproducible results
    
    assignments = []
    for i in range(1000):
        user_id = f"user_{i:04d}"
        experiment_id = np.random.choice(['exp_001', 'exp_002'])
        
        if experiment_id == 'exp_001':
            variant = np.random.choice(['control', 'treatment'], p=[0.5, 0.5])
        else:
            variant = np.random.choice(['control', 'treatment'], p=[0.6, 0.4])
            
        assignments.append({
            'user_id': user_id,
            'experiment_id': experiment_id,
            'variant': variant,
            'assignment_time': datetime.now() - timedelta(days=np.random.randint(0, 30)),
            'is_returning_user': np.random.choice([True, False], p=[0.7, 0.3])
        })
    
    return assignments


@pytest.fixture
def sample_conversion_events():
    """Sample conversion events for experiments."""
    np.random.seed(42)
    
    events = []
    for i in range(500):
        user_id = f"user_{i % 1000:04d}"
        experiment_id = np.random.choice(['exp_001', 'exp_002'])
        
        # Simulate different conversion rates for control vs treatment
        if experiment_id == 'exp_001':
            variant = np.random.choice(['control', 'treatment'])
            # Treatment performs better
            converted = np.random.choice([True, False], 
                                       p=[0.15, 0.85] if variant == 'control' else [0.22, 0.78])
        else:
            variant = np.random.choice(['control', 'treatment'])
            # Control performs better in this case
            converted = np.random.choice([True, False], 
                                       p=[0.18, 0.82] if variant == 'control' else [0.14, 0.86])
        
        if converted:
            events.append({
                'user_id': user_id,
                'experiment_id': experiment_id,
                'variant': variant,
                'event_type': 'conversion',
                'timestamp': datetime.now() - timedelta(days=np.random.randint(0, 30)),
                'value': np.random.exponential(100),  # Revenue value
                'metadata': {
                    'page': np.random.choice(['search', 'results', 'detail']),
                    'session_duration': np.random.exponential(180)  # seconds
                }
            })
    
    return events


@pytest.fixture
def statistical_test_scenarios():
    """Scenarios for statistical testing validation."""
    return [
        {
            'name': 'clear_winner',
            'description': 'Treatment clearly outperforms control',
            'control_data': {'successes': 150, 'trials': 1000, 'mean': 0.15},
            'treatment_data': {'successes': 220, 'trials': 1000, 'mean': 0.22},
            'expected_significance': True,
            'expected_confidence_interval': (0.05, 0.09),
            'test_type': 'proportion'
        },
        {
            'name': 'no_difference',
            'description': 'No significant difference between variants',
            'control_data': {'successes': 180, 'trials': 1000, 'mean': 0.18},
            'treatment_data': {'successes': 175, 'trials': 1000, 'mean': 0.175},
            'expected_significance': False,
            'expected_confidence_interval': (-0.02, 0.03),
            'test_type': 'proportion'
        },
        {
            'name': 'continuous_metric',
            'description': 'Testing continuous metrics like time',
            'control_data': {'values': np.random.normal(120, 30, 500), 'mean': 120},
            'treatment_data': {'values': np.random.normal(110, 25, 500), 'mean': 110},
            'expected_significance': True,
            'expected_effect_size': 0.37,
            'test_type': 'continuous'
        }
    ]


@pytest.fixture
def experiment_configurations():
    """Various experiment configuration scenarios."""
    return {
        'minimal_config': {
            'name': 'Minimal Test',
            'variants': [
                {'id': 'control', 'traffic_allocation': 0.5},
                {'id': 'treatment', 'traffic_allocation': 0.5}
            ],
            'success_metrics': ['conversion_rate']
        },
        'multi_variant_config': {
            'name': 'Multi-variant Test',
            'variants': [
                {'id': 'control', 'traffic_allocation': 0.4},
                {'id': 'variant_a', 'traffic_allocation': 0.3},
                {'id': 'variant_b', 'traffic_allocation': 0.3}
            ],
            'success_metrics': ['conversion_rate', 'revenue_per_user'],
            'stratification': ['user_segment', 'device_type']
        },
        'complex_config': {
            'name': 'Complex Experiment',
            'variants': [
                {'id': 'control', 'traffic_allocation': 0.25, 'features': {'ui': 'old', 'algorithm': 'v1'}},
                {'id': 'ui_only', 'traffic_allocation': 0.25, 'features': {'ui': 'new', 'algorithm': 'v1'}},
                {'id': 'algo_only', 'traffic_allocation': 0.25, 'features': {'ui': 'old', 'algorithm': 'v2'}},
                {'id': 'combined', 'traffic_allocation': 0.25, 'features': {'ui': 'new', 'algorithm': 'v2'}}
            ],
            'success_metrics': ['conversion_rate', 'engagement_score', 'satisfaction'],
            'stratification': ['user_segment', 'geographic_region'],
            'guardrail_metrics': ['error_rate', 'latency'],
            'minimum_detectable_effect': 0.05
        }
    }


@pytest.fixture
def bayesian_test_data():
    """Data for Bayesian A/B testing scenarios."""
    return {
        'conjugate_prior': {
            'name': 'Beta-Binomial Conjugate Prior',
            'prior': {'alpha': 1, 'beta': 1},  # Uniform prior
            'control_data': {'successes': 45, 'failures': 155},
            'treatment_data': {'successes': 62, 'failures': 138},
            'expected_probability_treatment_better': 0.95
        },
        'informative_prior': {
            'name': 'Informative Prior Based on Historical Data',
            'prior': {'alpha': 15, 'beta': 85},  # Prior belief of 15% conversion
            'control_data': {'successes': 18, 'failures': 82},
            'treatment_data': {'successes': 25, 'failures': 75},
            'expected_probability_treatment_better': 0.82
        },
        'gaussian_model': {
            'name': 'Gaussian Model for Continuous Metrics',
            'prior': {'mu': 100, 'tau': 0.01},  # Weak prior
            'control_data': np.random.normal(98, 15, 200),
            'treatment_data': np.random.normal(105, 18, 200),
            'expected_lift': 0.071
        }
    }


@pytest.fixture
def sequential_testing_data():
    """Data for sequential/adaptive testing scenarios."""
    return {
        'daily_observations': [
            {'day': 1, 'control': {'visitors': 100, 'conversions': 15}, 'treatment': {'visitors': 100, 'conversions': 18}},
            {'day': 2, 'control': {'visitors': 120, 'conversions': 16}, 'treatment': {'visitors': 118, 'conversions': 23}},
            {'day': 3, 'control': {'visitors': 95, 'conversions': 14}, 'treatment': {'visitors': 102, 'conversions': 19}},
            {'day': 4, 'control': {'visitors': 110, 'conversions': 17}, 'treatment': {'visitors': 108, 'conversions': 24}},
            {'day': 5, 'control': {'visitors': 105, 'conversions': 16}, 'treatment': {'visitors': 107, 'conversions': 22}},
        ],
        'stopping_boundaries': {
            'efficacy_boundary': 4.0,  # Z-score for early stopping (winner)
            'futility_boundary': 0.5,  # Z-score for early stopping (no difference)
            'alpha_spending_function': 'obrien_fleming'
        },
        'adaptive_parameters': {
            'initial_allocation': {'control': 0.5, 'treatment': 0.5},
            'adaptation_frequency': 'daily',
            'min_sample_per_variant': 50,
            'max_sample_total': 10000
        }
    }


@pytest.fixture
def performance_test_data():
    """Data for testing A/B system performance."""
    return {
        'large_user_base': {
            'num_users': 100000,
            'num_experiments': 50,
            'assignment_rate': 0.8,  # 80% of users get assigned
            'event_rate_per_user_per_day': 5,
            'test_duration_days': 30
        },
        'concurrent_experiments': [
            {'id': f'exp_{i:03d}', 'traffic': 0.1, 'priority': i % 3} 
            for i in range(20)
        ],
        'real_time_requirements': {
            'assignment_latency_ms': 10,
            'event_ingestion_latency_ms': 100,
            'analysis_refresh_interval_minutes': 15,
            'dashboard_load_time_ms': 2000
        }
    }


@pytest.fixture
def edge_case_scenarios():
    """Edge cases and error conditions for A/B testing."""
    return {
        'zero_variance': {
            'control_data': [1.0] * 100,  # All identical values
            'treatment_data': [1.0] * 100,
            'expected_behavior': 'handle_gracefully'
        },
        'extreme_imbalance': {
            'control_size': 10000,
            'treatment_size': 50,
            'expected_behavior': 'warn_and_proceed'
        },
        'missing_data': {
            'user_assignments': [
                {'user_id': 'user_001', 'variant': 'control'},
                {'user_id': 'user_002', 'variant': None},  # Missing variant
                {'user_id': None, 'variant': 'treatment'}   # Missing user_id
            ],
            'expected_behavior': 'filter_invalid'
        },
        'overlapping_experiments': {
            'user_id': 'user_123',
            'experiments': [
                {'id': 'exp_001', 'variant': 'control'},
                {'id': 'exp_002', 'variant': 'treatment'}
            ],
            'expected_behavior': 'handle_isolation'
        }
    }


@pytest.fixture
def metric_definitions():
    """Standard metric definitions for testing."""
    return {
        'conversion_rate': {
            'type': 'proportion',
            'numerator': 'conversions',
            'denominator': 'visitors',
            'higher_is_better': True,
            'minimum_detectable_effect': 0.05
        },
        'revenue_per_user': {
            'type': 'continuous',
            'aggregation': 'mean',
            'higher_is_better': True,
            'minimum_detectable_effect': 5.0,
            'outlier_threshold': 3  # Standard deviations
        },
        'session_duration': {
            'type': 'continuous',
            'aggregation': 'median',  # Less sensitive to outliers
            'higher_is_better': True,
            'minimum_detectable_effect': 10.0,  # seconds
            'log_transform': True
        },
        'error_rate': {
            'type': 'proportion',
            'numerator': 'errors',
            'denominator': 'requests',
            'higher_is_better': False,
            'guardrail_threshold': 0.05  # Stop experiment if error rate > 5%
        }
    }