"""Metrics collection fixtures for comprehensive testing."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any
import uuid
import random


@pytest.fixture
def sample_events():
    """Sample events for metrics collection testing."""
    base_time = datetime.now() - timedelta(days=7)
    
    events = []
    for i in range(1000):
        event_time = base_time + timedelta(seconds=i * 10)  # Events every 10 seconds
        
        event = {
            'event_id': str(uuid.uuid4()),
            'user_id': f"user_{i % 100:03d}",
            'session_id': f"session_{i % 200:03d}",
            'event_type': np.random.choice([
                'page_view', 'query_submitted', 'result_clicked', 
                'export_requested', 'error_occurred', 'user_signup'
            ], p=[0.4, 0.2, 0.15, 0.1, 0.05, 0.1]),
            'timestamp': event_time,
            'properties': {
                'page_url': np.random.choice([
                    '/search', '/results', '/analysis', '/export', '/profile'
                ]),
                'user_agent': np.random.choice([
                    'Chrome/96.0', 'Firefox/95.0', 'Safari/15.1', 'Edge/96.0'
                ]),
                'experiment_variant': np.random.choice(['control', 'treatment', None], p=[0.4, 0.4, 0.2])
            },
            'metrics': {
                'load_time_ms': np.random.exponential(200),
                'cpu_usage_percent': np.random.beta(2, 8) * 100,  # Skewed toward low usage
                'memory_usage_mb': np.random.gamma(2, 50),
                'query_complexity_score': np.random.poisson(3)
            }
        }
        
        events.append(event)
    
    return events


@pytest.fixture 
def user_behavior_patterns():
    """Realistic user behavior patterns."""
    return {
        'power_user': {
            'daily_sessions': 8,
            'session_duration_minutes': 45,
            'queries_per_session': 12,
            'conversion_rate': 0.15,
            'feature_adoption_rate': 0.8,
            'retention_probability': 0.9
        },
        'casual_user': {
            'daily_sessions': 1,
            'session_duration_minutes': 8,
            'queries_per_session': 2,
            'conversion_rate': 0.05,
            'feature_adoption_rate': 0.2,
            'retention_probability': 0.6
        },
        'researcher': {
            'daily_sessions': 3,
            'session_duration_minutes': 25,
            'queries_per_session': 8,
            'conversion_rate': 0.25,
            'feature_adoption_rate': 0.6,
            'retention_probability': 0.8
        },
        'new_user': {
            'daily_sessions': 0.5,
            'session_duration_minutes': 15,
            'queries_per_session': 4,
            'conversion_rate': 0.08,
            'feature_adoption_rate': 0.3,
            'retention_probability': 0.4
        }
    }


@pytest.fixture
def custom_metrics_definitions():
    """Custom metrics definitions for testing."""
    return {
        'user_engagement_score': {
            'description': 'Composite score measuring user engagement',
            'formula': 'log(sessions) + log(queries) + conversion_events * 2',
            'aggregation': 'mean',
            'time_window': 'daily',
            'dimensions': ['user_segment', 'experiment_variant'],
            'alerts': {
                'threshold_low': 2.0,
                'threshold_high': 10.0,
                'comparison': 'day_over_day'
            }
        },
        'system_health_score': {
            'description': 'Overall system health indicator',
            'formula': '(1 - error_rate) * (1 - (latency_p95 / 1000)) * uptime',
            'aggregation': 'min',  # Use worst performance
            'time_window': 'hourly',
            'dimensions': ['service', 'region'],
            'alerts': {
                'threshold_low': 0.8,
                'comparison': 'absolute'
            }
        },
        'feature_adoption_velocity': {
            'description': 'Rate of feature adoption over time',
            'formula': 'new_feature_users / total_active_users',
            'aggregation': 'sum',
            'time_window': 'weekly',
            'dimensions': ['feature_name', 'user_cohort'],
            'rolling_window': 4  # 4-week rolling average
        },
        'query_success_rate': {
            'description': 'Percentage of successful queries',
            'formula': 'successful_queries / total_queries',
            'aggregation': 'mean',
            'time_window': 'realtime',
            'dimensions': ['query_type', 'data_source'],
            'alerts': {
                'threshold_low': 0.95,
                'comparison': 'hour_over_hour'
            }
        }
    }


@pytest.fixture
def real_time_stream_data():
    """Simulated real-time stream data."""
    def generate_stream(duration_minutes=10, events_per_second=5):
        """Generate a stream of events over time."""
        start_time = datetime.now()
        total_events = duration_minutes * 60 * events_per_second
        
        for i in range(total_events):
            timestamp = start_time + timedelta(seconds=i / events_per_second)
            
            # Simulate varying load throughout the day
            hour = timestamp.hour
            if 9 <= hour <= 17:  # Business hours
                load_multiplier = 2.0
            elif 22 <= hour or hour <= 6:  # Night
                load_multiplier = 0.3
            else:
                load_multiplier = 1.0
            
            yield {
                'timestamp': timestamp,
                'event_type': np.random.choice([
                    'query', 'click', 'export', 'error'
                ], p=[0.5, 0.3, 0.15, 0.05]),
                'user_id': f"user_{np.random.randint(1, 1000):04d}",
                'properties': {
                    'load_factor': load_multiplier,
                    'response_time_ms': np.random.exponential(100 / load_multiplier),
                    'success': np.random.choice([True, False], p=[0.95, 0.05])
                }
            }
    
    return generate_stream


@pytest.fixture
def aggregation_test_cases():
    """Test cases for various aggregation scenarios."""
    return [
        {
            'name': 'simple_count',
            'events': [
                {'user_id': 'user_1', 'event_type': 'click', 'timestamp': datetime.now()},
                {'user_id': 'user_1', 'event_type': 'click', 'timestamp': datetime.now()},
                {'user_id': 'user_2', 'event_type': 'view', 'timestamp': datetime.now()}
            ],
            'aggregation': {'type': 'count', 'group_by': ['event_type']},
            'expected': {'click': 2, 'view': 1}
        },
        {
            'name': 'percentile_calculation',
            'events': [
                {'response_time': t, 'timestamp': datetime.now()} 
                for t in [10, 20, 30, 40, 50, 100, 200, 500, 800, 1000]
            ],
            'aggregation': {'type': 'percentile', 'field': 'response_time', 'percentiles': [50, 95, 99]},
            'expected': {'p50': 50, 'p95': 800, 'p99': 1000}
        },
        {
            'name': 'window_aggregation',
            'events': [
                {'value': i, 'timestamp': datetime.now() - timedelta(minutes=i)} 
                for i in range(60)
            ],
            'aggregation': {
                'type': 'moving_average', 
                'field': 'value', 
                'window_size': 5,
                'time_unit': 'minutes'
            },
            'expected_length': 56  # 60 - 5 + 1 for moving average
        },
        {
            'name': 'cohort_analysis',
            'events': [
                {
                    'user_id': f'user_{i}',
                    'signup_date': datetime.now() - timedelta(days=30),
                    'activity_date': datetime.now() - timedelta(days=d),
                    'event_type': 'activity'
                }
                for i in range(100)
                for d in range(0, 30, 3)  # Active every 3 days
            ],
            'aggregation': {
                'type': 'retention_cohort',
                'cohort_field': 'signup_date',
                'event_field': 'activity_date',
                'periods': [1, 7, 14, 30]
            }
        }
    ]


@pytest.fixture
def performance_benchmarks():
    """Performance benchmarks for metrics system."""
    return {
        'ingestion_targets': {
            'events_per_second': 10000,
            'batch_processing_latency_ms': 100,
            'memory_usage_per_1k_events_mb': 10,
            'storage_compression_ratio': 0.3
        },
        'query_performance': {
            'simple_aggregation_ms': 50,
            'complex_aggregation_ms': 500,
            'real_time_dashboard_refresh_ms': 1000,
            'historical_report_generation_s': 30
        },
        'scalability_limits': {
            'max_concurrent_users': 1000,
            'max_events_per_minute': 600000,
            'max_custom_metrics': 500,
            'max_dimensions_per_metric': 10
        }
    }


@pytest.fixture
def alert_test_scenarios():
    """Scenarios for testing alerting functionality."""
    return {
        'threshold_breach': {
            'metric': 'error_rate',
            'threshold': 0.05,
            'current_value': 0.08,
            'comparison': 'greater_than',
            'expected_alert': True,
            'severity': 'critical'
        },
        'anomaly_detection': {
            'metric': 'query_volume',
            'historical_data': [100, 95, 105, 98, 102, 97, 103],
            'current_value': 150,  # Significant increase
            'detection_method': 'z_score',
            'threshold_std_dev': 2.0,
            'expected_alert': True,
            'severity': 'warning'
        },
        'trend_analysis': {
            'metric': 'conversion_rate',
            'time_series': [0.15, 0.14, 0.13, 0.12, 0.11, 0.10, 0.09],
            'trend_type': 'declining',
            'min_data_points': 5,
            'significance_level': 0.05,
            'expected_alert': True,
            'severity': 'medium'
        },
        'seasonal_adjustment': {
            'metric': 'daily_active_users',
            'seasonal_pattern': 'weekly',  # Lower on weekends
            'current_day': 'saturday',
            'raw_value': 800,
            'seasonal_adjusted_value': 1000,  # Adjusted for weekend
            'threshold': 900,
            'expected_alert': True
        }
    }


@pytest.fixture
def data_quality_test_cases():
    """Test cases for data quality validation."""
    return {
        'missing_fields': [
            {'user_id': None, 'event_type': 'click'},  # Missing user_id
            {'user_id': 'user_1', 'event_type': None}, # Missing event_type
            {'user_id': 'user_2'}                      # Missing event_type entirely
        ],
        'invalid_timestamps': [
            {'timestamp': '2025-13-45T25:70:80'},     # Invalid date
            {'timestamp': 'not_a_date'},               # Invalid format
            {'timestamp': datetime.now() + timedelta(days=1)}  # Future timestamp
        ],
        'outlier_values': [
            {'response_time_ms': -100},                # Negative time
            {'response_time_ms': 1000000},            # Extremely high value
            {'user_age': 200},                        # Unrealistic age
            {'query_length': 0}                       # Zero-length query
        ],
        'duplicate_events': [
            {'event_id': 'evt_001', 'user_id': 'user_1', 'timestamp': datetime.now()},
            {'event_id': 'evt_001', 'user_id': 'user_1', 'timestamp': datetime.now()}, # Duplicate
            {'event_id': 'evt_002', 'user_id': 'user_2', 'timestamp': datetime.now()}
        ]
    }


@pytest.fixture
def dashboard_test_data():
    """Test data for dashboard visualization."""
    return {
        'time_series_chart': {
            'metric': 'query_volume',
            'data_points': [
                {'timestamp': datetime.now() - timedelta(hours=i), 'value': 100 + np.sin(i/4) * 20}
                for i in range(24)
            ],
            'chart_type': 'line',
            'aggregation_interval': 'hourly'
        },
        'funnel_analysis': {
            'steps': [
                {'name': 'Landing Page', 'users': 10000},
                {'name': 'Search Query', 'users': 8500},
                {'name': 'View Results', 'users': 7200},
                {'name': 'Click Result', 'users': 4800},
                {'name': 'Export Data', 'users': 1200}
            ],
            'conversion_rates': [0.85, 0.847, 0.667, 0.25]
        },
        'cohort_heatmap': {
            'cohorts': [
                {'cohort': '2024-01-W1', 'week_0': 1.0, 'week_1': 0.6, 'week_2': 0.4, 'week_3': 0.3},
                {'cohort': '2024-01-W2', 'week_0': 1.0, 'week_1': 0.65, 'week_2': 0.42, 'week_3': 0.32},
                {'cohort': '2024-01-W3', 'week_0': 1.0, 'week_1': 0.62, 'week_2': 0.38}
            ]
        },
        'geographic_distribution': {
            'regions': [
                {'country': 'US', 'users': 5000, 'revenue': 50000},
                {'country': 'UK', 'users': 2000, 'revenue': 18000},
                {'country': 'CA', 'users': 1500, 'revenue': 14000},
                {'country': 'DE', 'users': 1200, 'revenue': 12000},
                {'country': 'FR', 'users': 800, 'revenue': 7500}
            ]
        }
    }


@pytest.fixture
def integration_test_config():
    """Configuration for integration testing."""
    return {
        'test_databases': {
            'primary': 'postgresql://test:test@localhost:5432/metrics_test',
            'analytics': 'clickhouse://test:test@localhost:8123/analytics_test',
            'cache': 'redis://localhost:6379/1'
        },
        'external_services': {
            'kafka_bootstrap_servers': 'localhost:9092',
            'elasticsearch_url': 'http://localhost:9200',
            'grafana_api_url': 'http://localhost:3000/api'
        },
        'test_data_volume': {
            'small': {'events': 1000, 'users': 100, 'duration_days': 1},
            'medium': {'events': 100000, 'users': 1000, 'duration_days': 7},
            'large': {'events': 1000000, 'users': 10000, 'duration_days': 30}
        },
        'performance_sla': {
            'event_ingestion_latency_p99_ms': 200,
            'query_response_time_p95_ms': 500,
            'dashboard_load_time_p90_ms': 2000,
            'alert_detection_delay_s': 60
        }
    }