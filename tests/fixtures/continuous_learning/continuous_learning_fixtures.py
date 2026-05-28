"""Continuous learning fixtures for comprehensive testing."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Callable, Generator, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import json


class DriftType(Enum):
    """Types of concept drift."""
    SUDDEN = "sudden"
    GRADUAL = "gradual"
    INCREMENTAL = "incremental"
    RECURRING = "recurring"
    CYCLICAL = "cyclical"


class LearningMode(Enum):
    """Learning modes for online learning."""
    PASSIVE = "passive"
    ACTIVE = "active" 
    SEMI_SUPERVISED = "semi_supervised"
    REINFORCEMENT = "reinforcement"


@dataclass
class DataStream:
    """Represents a data stream with concept drift."""
    name: str
    n_samples: int
    n_features: int
    n_classes: int
    drift_points: List[int]
    drift_types: List[DriftType]
    noise_level: float
    class_imbalance_ratio: float


@dataclass
class LearningConfig:
    """Configuration for online learning algorithms."""
    algorithm: str
    learning_rate: float
    batch_size: int
    buffer_size: int
    adaptation_strategy: str
    drift_detection_method: str
    performance_metric: str


@dataclass
class PerformanceMetrics:
    """Performance metrics for continuous learning."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    kappa: float
    drift_detection_delay: int
    adaptation_time: int
    memory_usage_mb: float
    processing_time_ms: float


@pytest.fixture
def synthetic_data_streams():
    """Synthetic data streams with various drift patterns."""
    
    def generate_classification_stream(n_samples: int, n_features: int = 20, 
                                     drift_type: DriftType = DriftType.SUDDEN,
                                     drift_point: int = None, noise_level: float = 0.1):
        """Generate synthetic classification stream with concept drift."""
        np.random.seed(42)
        
        if drift_point is None:
            drift_point = n_samples // 2
            
        X = np.random.randn(n_samples, n_features)
        y = np.zeros(n_samples, dtype=int)
        
        # Pre-drift concept
        weights_1 = np.random.randn(n_features)
        weights_1[:5] = [2, -1.5, 1.8, -2.2, 1.2]  # Strong signal in first 5 features
        
        # Post-drift concept
        weights_2 = np.random.randn(n_features)
        if drift_type == DriftType.SUDDEN:
            weights_2[5:10] = [2.1, -1.8, 1.6, -2.0, 1.4]  # Signal shifts to features 5-9
        elif drift_type == DriftType.GRADUAL:
            weights_2 = 0.7 * weights_1 + 0.3 * np.random.randn(n_features)
        
        for i in range(n_samples):
            if i < drift_point:
                decision = np.dot(X[i], weights_1)
            else:
                if drift_type == DriftType.GRADUAL:
                    # Gradual transition
                    progress = (i - drift_point) / (n_samples - drift_point)
                    mixed_weights = (1 - progress) * weights_1 + progress * weights_2
                    decision = np.dot(X[i], mixed_weights)
                else:
                    decision = np.dot(X[i], weights_2)
            
            y[i] = 1 if decision + np.random.normal(0, noise_level) > 0 else 0
        
        return X, y, drift_point
    
    def generate_regression_stream(n_samples: int, n_features: int = 15,
                                 drift_type: DriftType = DriftType.SUDDEN,
                                 drift_point: int = None):
        """Generate synthetic regression stream with concept drift."""
        np.random.seed(42)
        
        if drift_point is None:
            drift_point = n_samples // 2
            
        X = np.random.randn(n_samples, n_features)
        y = np.zeros(n_samples)
        
        # Pre-drift: linear relationship
        weights_1 = np.array([2, -1, 1.5, -0.5, 1] + [0] * (n_features - 5))
        
        # Post-drift: different relationship
        if drift_type == DriftType.SUDDEN:
            weights_2 = np.array([0] * 5 + [1.8, -1.2, 2.1, -1.8, 0.9] + [0] * (n_features - 10))
        else:
            weights_2 = weights_1 * 0.5 + np.random.randn(n_features) * 0.3
        
        for i in range(n_samples):
            if i < drift_point:
                y[i] = np.dot(X[i], weights_1) + np.random.normal(0, 0.5)
            else:
                y[i] = np.dot(X[i], weights_2) + np.random.normal(0, 0.5)
        
        return X, y, drift_point
    
    streams = {}
    
    # Classification streams
    streams['sudden_drift_classification'] = DataStream(
        name='sudden_drift_classification',
        n_samples=5000,
        n_features=20,
        n_classes=2,
        drift_points=[2500],
        drift_types=[DriftType.SUDDEN],
        noise_level=0.1,
        class_imbalance_ratio=1.0
    )
    
    streams['gradual_drift_classification'] = DataStream(
        name='gradual_drift_classification', 
        n_samples=6000,
        n_features=25,
        n_classes=2,
        drift_points=[2000],
        drift_types=[DriftType.GRADUAL],
        noise_level=0.15,
        class_imbalance_ratio=1.2
    )
    
    streams['multiple_drifts'] = DataStream(
        name='multiple_drifts',
        n_samples=10000,
        n_features=30,
        n_classes=3,
        drift_points=[3000, 6000, 8000],
        drift_types=[DriftType.SUDDEN, DriftType.GRADUAL, DriftType.SUDDEN],
        noise_level=0.2,
        class_imbalance_ratio=2.0
    )
    
    streams['high_dimensional'] = DataStream(
        name='high_dimensional',
        n_samples=8000,
        n_features=100,
        n_classes=5,
        drift_points=[4000],
        drift_types=[DriftType.SUDDEN],
        noise_level=0.1,
        class_imbalance_ratio=1.5
    )
    
    return streams


@pytest.fixture
def drift_detection_scenarios():
    """Scenarios for testing drift detection algorithms."""
    return {
        'adwin_test': {
            'description': 'ADWIN drift detection test',
            'algorithm': 'ADWIN',
            'parameters': {'delta': 0.002, 'max_buckets': 5},
            'expected_detections': [2500],
            'tolerance': 100
        },
        'ddm_test': {
            'description': 'Drift Detection Method test',
            'algorithm': 'DDM',
            'parameters': {'min_instances': 30, 'warning_level': 2.0, 'out_control_level': 3.0},
            'expected_detections': [2500],
            'tolerance': 200
        },
        'eddm_test': {
            'description': 'Early Drift Detection Method test',
            'algorithm': 'EDDM',
            'parameters': {'min_instances': 30, 'warning_level': 0.95, 'out_control_level': 0.90},
            'expected_detections': [2500],
            'tolerance': 150
        },
        'page_hinkley_test': {
            'description': 'Page-Hinkley drift detection test',
            'algorithm': 'PageHinkley',
            'parameters': {'min_instances': 30, 'delta': 0.005, 'threshold': 50, 'alpha': 0.9999},
            'expected_detections': [2500],
            'tolerance': 300
        },
        'kswin_test': {
            'description': 'Kolmogorov-Smirnov Windowing test',
            'algorithm': 'KSWIN',
            'parameters': {'alpha': 0.005, 'window_size': 100, 'stat_size': 30},
            'expected_detections': [2500],
            'tolerance': 250
        }
    }


@pytest.fixture
def online_learning_algorithms():
    """Configuration for various online learning algorithms."""
    return {
        'naive_bayes': {
            'algorithm': 'GaussianNaiveBayes',
            'parameters': {},
            'suitable_for': ['classification'],
            'adaptation_strategy': 'incremental_update'
        },
        'hoeffding_tree': {
            'algorithm': 'HoeffdingTreeClassifier',
            'parameters': {
                'grace_period': 200,
                'split_criterion': 'gini',
                'split_confidence': 0.0000001,
                'tie_threshold': 0.05,
                'binary_split': False,
                'stop_mem_management': False,
                'remove_poor_atts': False,
                'leaf_prediction': 'nba',
                'nb_threshold': 0,
                'nominal_attributes': None
            },
            'suitable_for': ['classification'],
            'adaptation_strategy': 'tree_growth'
        },
        'adaptive_random_forest': {
            'algorithm': 'AdaptiveRandomForestClassifier',
            'parameters': {
                'n_estimators': 10,
                'max_features': 'sqrt',
                'lambda_value': 6,
                'performance_metric': 'acc',
                'disable_weighted_vote': False,
                'drift_detection_method': 'ADWIN',
                'warning_detection_method': 'ADWIN'
            },
            'suitable_for': ['classification'],
            'adaptation_strategy': 'ensemble_adaptation'
        },
        'sam_knn': {
            'algorithm': 'SAMKNNClassifier',
            'parameters': {
                'n_neighbors': 5,
                'max_window_size': 1000,
                'stm_size_option': 'maxACCApprox',
                'use_ltm': False
            },
            'suitable_for': ['classification'],
            'adaptation_strategy': 'memory_adaptation'
        },
        'perceptron': {
            'algorithm': 'PerceptronMask',
            'parameters': {
                'random_state': 112,
                'shuffle': True,
                'learning_rate': 0.01
            },
            'suitable_for': ['classification'],
            'adaptation_strategy': 'gradient_update'
        },
        'sgd_regressor': {
            'algorithm': 'SGDRegressor',
            'parameters': {
                'loss': 'squared_loss',
                'learning_rate': 'constant',
                'eta0': 0.01,
                'alpha': 0.0001
            },
            'suitable_for': ['regression'],
            'adaptation_strategy': 'gradient_update'
        }
    }


@pytest.fixture
def evaluation_protocols():
    """Evaluation protocols for continuous learning."""
    return {
        'prequential': {
            'description': 'Test-then-train (prequential) evaluation',
            'method': 'test_then_train',
            'parameters': {
                'max_samples': 10000,
                'pretrain_size': 0,
                'show_plot': False,
                'metrics': ['accuracy', 'kappa', 'kappa_t', 'kappa_m']
            }
        },
        'holdout': {
            'description': 'Holdout evaluation with periodic retraining',
            'method': 'holdout',
            'parameters': {
                'test_size': 0.2,
                'dynamic': True,
                'max_samples': 10000,
                'metrics': ['accuracy', 'precision', 'recall', 'f1']
            }
        },
        'sliding_window': {
            'description': 'Sliding window evaluation',
            'method': 'sliding_window',
            'parameters': {
                'window_size': 1000,
                'step_size': 100,
                'metrics': ['accuracy', 'kappa']
            }
        },
        'forgetting_factor': {
            'description': 'Evaluation with forgetting factor',
            'method': 'fading_factor',
            'parameters': {
                'alpha': 0.98,
                'metrics': ['weighted_accuracy', 'weighted_kappa']
            }
        }
    }


@pytest.fixture
def adaptation_strategies():
    """Strategies for adapting to concept drift."""
    return {
        'naive_retrain': {
            'strategy': 'retrain_all',
            'description': 'Retrain model from scratch when drift detected',
            'parameters': {
                'detection_delay_tolerance': 100,
                'retrain_window': 'all'
            },
            'pros': ['Simple', 'Forgets old concept completely'],
            'cons': ['Slow', 'Loses all historical knowledge']
        },
        'windowed_retrain': {
            'strategy': 'retrain_window',
            'description': 'Retrain on recent window when drift detected',
            'parameters': {
                'window_size': 1000,
                'overlap': 0.1
            },
            'pros': ['Faster than full retrain', 'Adapts to recent concept'],
            'cons': ['May lose useful historical patterns']
        },
        'ensemble_adaptation': {
            'strategy': 'ensemble',
            'description': 'Maintain ensemble of models and adapt weights',
            'parameters': {
                'max_ensemble_size': 5,
                'weight_update_rule': 'performance_weighted',
                'diversity_measure': 'disagreement'
            },
            'pros': ['Maintains multiple hypotheses', 'Smooth adaptation'],
            'cons': ['Higher memory usage', 'Complex weight management']
        },
        'incremental_adaptation': {
            'strategy': 'incremental',
            'description': 'Incrementally update model parameters',
            'parameters': {
                'learning_rate_decay': 0.99,
                'adaptation_rate': 0.1,
                'momentum': 0.9
            },
            'pros': ['Fast adaptation', 'Low memory overhead'],
            'cons': ['May be slow to adapt to major drifts']
        },
        'meta_learning': {
            'strategy': 'meta',
            'description': 'Learn how to adapt using meta-learning',
            'parameters': {
                'meta_learning_rate': 0.001,
                'inner_steps': 5,
                'task_batch_size': 4
            },
            'pros': ['Learns adaptation strategy', 'Fast adaptation to new concepts'],
            'cons': ['Complex', 'Requires diverse training tasks']
        }
    }


@pytest.fixture
def performance_benchmarks():
    """Performance benchmarks for continuous learning systems."""
    return {
        'accuracy_benchmarks': {
            'excellent': {'threshold': 0.90, 'description': 'Near-optimal performance'},
            'good': {'threshold': 0.85, 'description': 'Good performance with some degradation'},
            'acceptable': {'threshold': 0.80, 'description': 'Acceptable performance'},
            'poor': {'threshold': 0.70, 'description': 'Poor performance, needs improvement'}
        },
        'adaptation_speed': {
            'fast': {'steps': 100, 'description': 'Quick adaptation to new concepts'},
            'medium': {'steps': 500, 'description': 'Reasonable adaptation speed'},
            'slow': {'steps': 1000, 'description': 'Slow but eventual adaptation'},
            'very_slow': {'steps': 2000, 'description': 'Very slow adaptation'}
        },
        'memory_efficiency': {
            'excellent': {'mb_per_1k_samples': 1, 'description': 'Very memory efficient'},
            'good': {'mb_per_1k_samples': 5, 'description': 'Good memory usage'},
            'acceptable': {'mb_per_1k_samples': 20, 'description': 'Acceptable memory usage'},
            'poor': {'mb_per_1k_samples': 100, 'description': 'High memory usage'}
        },
        'processing_speed': {
            'real_time': {'ms_per_sample': 1, 'description': 'Real-time processing'},
            'near_real_time': {'ms_per_sample': 10, 'description': 'Near real-time processing'},
            'batch_suitable': {'ms_per_sample': 100, 'description': 'Suitable for batch processing'},
            'offline_only': {'ms_per_sample': 1000, 'description': 'Offline processing only'}
        }
    }


@pytest.fixture
def real_world_datasets():
    """Real-world dataset characteristics for testing.""" 
    return {
        'electricity': {
            'name': 'Electricity Market Dataset',
            'samples': 45312,
            'features': 8,
            'classes': 2,
            'drift_type': 'gradual',
            'description': 'Electricity prices in Australian market',
            'characteristics': ['temporal_correlation', 'seasonal_patterns', 'gradual_drift']
        },
        'covertype': {
            'name': 'Forest Cover Type Dataset',
            'samples': 581012,
            'features': 54,
            'classes': 7,
            'drift_type': 'sudden',
            'description': 'Forest cover type from cartographic variables',
            'characteristics': ['high_dimensional', 'imbalanced_classes', 'sudden_changes']
        },
        'weather': {
            'name': 'Weather Prediction Dataset',
            'samples': 18159,
            'features': 8,
            'classes': 2,
            'drift_type': 'seasonal',
            'description': 'Weather prediction based on atmospheric conditions',
            'characteristics': ['seasonal_drift', 'weather_dependencies', 'cyclical_patterns']
        },
        'airlines': {
            'name': 'Airlines Dataset', 
            'samples': 539383,
            'features': 7,
            'classes': 2,
            'drift_type': 'abrupt',
            'description': 'Airline delay prediction',
            'characteristics': ['large_scale', 'temporal_dependencies', 'external_factors']
        }
    }


@pytest.fixture
def stress_test_scenarios():
    """Stress testing scenarios for robustness evaluation."""
    return {
        'high_frequency_drift': {
            'description': 'Very frequent concept drifts',
            'drift_frequency': 500,  # Every 500 samples
            'n_drifts': 20,
            'drift_magnitude': 'medium',
            'expected_challenge': 'Constant adaptation required'
        },
        'extreme_noise': {
            'description': 'High noise levels that may mask drift',
            'noise_level': 0.5,
            'noise_type': 'gaussian',
            'drift_points': [5000],
            'expected_challenge': 'Drift detection in noisy environment'
        },
        'class_imbalance_shift': {
            'description': 'Severe class imbalance that changes over time',
            'initial_ratio': 0.95,  # 95% majority class
            'final_ratio': 0.05,    # 5% majority class (complete flip)
            'transition_type': 'gradual',
            'expected_challenge': 'Adaptation to changing class distribution'
        },
        'feature_space_expansion': {
            'description': 'New features appear over time',
            'initial_features': 10,
            'final_features': 50,
            'expansion_schedule': [1000, 2000, 3000, 4000],
            'expected_challenge': 'Handling increasing dimensionality'
        },
        'missing_data_streams': {
            'description': 'Increasing missing data rates',
            'initial_missing_rate': 0.05,
            'final_missing_rate': 0.30,
            'missing_pattern': 'MCAR',  # Missing Completely At Random
            'expected_challenge': 'Learning with incomplete information'
        },
        'adversarial_drift': {
            'description': 'Adversarially crafted concept drift',
            'attack_type': 'backdoor_gradual',
            'trigger_frequency': 0.10,
            'drift_stealth': 'high',
            'expected_challenge': 'Detecting hidden malicious patterns'
        }
    }


@pytest.fixture
def hardware_resource_limits():
    """Hardware resource constraints for realistic testing."""
    return {
        'memory_constrained': {
            'max_memory_mb': 100,
            'buffer_size_limit': 1000,
            'model_size_limit_mb': 10,
            'description': 'Edge device constraints'
        },
        'compute_constrained': {
            'max_processing_time_ms': 10,
            'max_batch_size': 10,
            'cpu_cores': 1,
            'description': 'Real-time processing constraints'
        },
        'bandwidth_constrained': {
            'max_data_rate_kbps': 100,
            'compression_required': True,
            'batch_transmission': True,
            'description': 'IoT/Mobile network constraints'
        },
        'power_constrained': {
            'max_power_mw': 1000,
            'sleep_mode_available': True,
            'duty_cycle': 0.1,
            'description': 'Battery-powered device constraints'
        }
    }


@pytest.fixture
def multi_modal_streams():
    """Multi-modal data streams for complex scenarios."""
    return {
        'text_image_stream': {
            'modalities': ['text', 'image'],
            'text_features': 100,  # TF-IDF or embeddings
            'image_features': 2048,  # CNN features
            'fusion_strategy': 'late_fusion',
            'drift_affects': ['text', 'image'],  # Both modalities drift
            'synchronization': 'aligned'
        },
        'sensor_fusion_stream': {
            'modalities': ['accelerometer', 'gyroscope', 'magnetometer'],
            'feature_dims': [3, 3, 3],
            'sampling_rates': [100, 100, 50],  # Hz
            'fusion_strategy': 'early_fusion',
            'drift_affects': ['accelerometer'],  # Only one sensor drifts
            'synchronization': 'timestamp_based'
        },
        'audio_video_stream': {
            'modalities': ['audio', 'video'],
            'audio_features': 13,  # MFCC features
            'video_features': 512,  # Video CNN features
            'temporal_alignment': 'frame_level',
            'drift_type': 'asynchronous',  # Different drift timing
            'quality_degradation': True
        }
    }


@pytest.fixture
def evaluation_frameworks():
    """Complete evaluation frameworks for continuous learning."""
    return {
        'river_framework': {
            'library': 'river',
            'evaluation_method': 'progressive_val_score',
            'metrics': ['Accuracy', 'LogLoss', 'Precision', 'Recall', 'F1'],
            'drift_detectors': ['ADWIN', 'DDM', 'EDDM', 'PageHinkley'],
            'algorithms': ['HoeffdingTree', 'AdaptiveRandomForest', 'OnlineBagging']
        },
        'scikit_multiflow': {
            'library': 'scikit-multiflow', 
            'evaluation_method': 'EvaluatePrequential',
            'metrics': ['accuracy', 'kappa', 'kappa_t', 'kappa_m'],
            'drift_detectors': ['ADWIN', 'DDM', 'EDDM', 'PageHinkley', 'KSWIN'],
            'algorithms': ['HoeffdingTreeClassifier', 'SAMKNNClassifier', 'LeveragingBaggingClassifier']
        },
        'custom_framework': {
            'library': 'custom',
            'evaluation_method': 'sliding_window_validation',
            'metrics': ['balanced_accuracy', 'roc_auc', 'pr_auc', 'adaptation_speed'],
            'drift_detectors': ['ensemble_detector', 'statistical_test', 'ml_detector'],
            'algorithms': ['neural_network', 'ensemble_methods', 'meta_learners']
        }
    }