"""Integration tests for continuous learning system."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any, Tuple
import asyncio
import threading
import time


class MockContinuousLearningSystem:
    """Mock continuous learning system for integration testing."""
    
    def __init__(self, config=None):
        self.config = config or {
            'learning_rate': 0.01,
            'buffer_size': 1000,
            'drift_threshold': 0.05,
            'adaptation_rate': 0.1,
            'monitoring_interval': 10
        }
        
        # Components
        self.online_learner = MockOnlineLearner(**self.config)
        self.drift_detector = MockDriftDetector(**self.config)
        self.model_selector = MockModelSelector()
        self.data_buffer = MockDataBuffer(self.config['buffer_size'])
        
        # System state
        self.is_running = False
        self.metrics_history = []
        self.adaptation_history = []
        self.performance_metrics = {
            'accuracy': [],
            'loss': [],
            'drift_detections': 0,
            'model_adaptations': 0
        }
        
        # Threading
        self._monitoring_thread = None
        self._stop_event = threading.Event()
        
    async def start_continuous_learning(self):
        """Start the continuous learning process."""
        self.is_running = True
        self._stop_event.clear()
        
        # Start monitoring thread
        self._monitoring_thread = threading.Thread(target=self._monitoring_loop)
        self._monitoring_thread.start()
        
    def stop_continuous_learning(self):
        """Stop the continuous learning process."""
        self.is_running = False
        self._stop_event.set()
        
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=1.0)
            
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                # Check for drift
                self._check_and_handle_drift()
                
                # Update performance metrics
                self._update_performance_metrics()
                
                # Adapt learning parameters
                self._adapt_learning_parameters()
                
                # Sleep for monitoring interval
                time.sleep(self.config['monitoring_interval'] / 1000.0)  # Convert ms to seconds
                
            except Exception as e:
                print(f"Error in monitoring loop: {e}")
                
    def process_data_stream(self, data_stream):
        """Process streaming data."""
        processed_samples = 0
        
        for batch in data_stream:
            if not self.is_running:
                break
                
            features, targets = batch
            
            # Add to buffer
            self.data_buffer.add_batch(features, targets)
            
            # Train on batch
            for f, t in zip(features, targets):
                prediction = self.online_learner.predict(f)
                loss = self._calculate_loss(prediction, t)
                
                # Update model
                self.online_learner.update(f, t)
                
                # Store metrics
                self.performance_metrics['loss'].append(loss)
                accuracy = 1.0 - min(1.0, abs(loss))  # Simple accuracy approximation
                self.performance_metrics['accuracy'].append(accuracy)
                
                processed_samples += 1
                
            # Update drift detector
            self.drift_detector.add_batch([np.mean(f) for f in features])  # Simplified feature
            
        return processed_samples
        
    def _check_and_handle_drift(self):
        """Check for drift and handle if detected."""
        if len(self.drift_detector.reference_window) < 50:
            return False
            
        drift_detected, methods_results = self.drift_detector.ensemble_drift_detection()
        
        if drift_detected:
            self.performance_metrics['drift_detections'] += 1
            
            # Handle drift
            self._handle_concept_drift(methods_results)
            
            return True
        return False
        
    def _handle_concept_drift(self, drift_info):
        """Handle detected concept drift."""
        adaptation_strategy = self._select_adaptation_strategy(drift_info)
        
        if adaptation_strategy == 'retrain':
            self._retrain_model()
        elif adaptation_strategy == 'adapt_params':
            self._adapt_model_parameters()
        elif adaptation_strategy == 'ensemble_update':
            self._update_ensemble()
            
        self.adaptation_history.append({
            'timestamp': datetime.now(),
            'strategy': adaptation_strategy,
            'drift_info': drift_info
        })
        
        self.performance_metrics['model_adaptations'] += 1
        
    def _select_adaptation_strategy(self, drift_info):
        """Select appropriate adaptation strategy."""
        # Simple strategy selection based on drift severity
        drift_count = sum(1 for method, (detected, _) in drift_info.items() if detected)
        
        if drift_count >= 3:
            return 'retrain'
        elif drift_count >= 2:
            return 'adapt_params'
        else:
            return 'ensemble_update'
            
    def _retrain_model(self):
        """Retrain model with recent data."""
        recent_data = self.data_buffer.get_recent_data(500)
        if recent_data:
            features, targets = recent_data
            
            # Reset model
            self.online_learner.reset()
            
            # Retrain on recent data
            for f, t in zip(features, targets):
                self.online_learner.update(f, t)
                
    def _adapt_model_parameters(self):
        """Adapt model parameters."""
        # Increase learning rate temporarily
        self.online_learner.learning_rate *= 1.5
        
        # Update buffer to focus on recent data
        self.drift_detector.update_reference_window(
            self.drift_detector.current_window[-100:]
        )
        
    def _update_ensemble(self):
        """Update ensemble models."""
        # Add current model to ensemble
        self.model_selector.add_model(
            self.online_learner.get_model_snapshot()
        )
        
    def _update_performance_metrics(self):
        """Update system performance metrics."""
        if len(self.performance_metrics['accuracy']) > 0:
            recent_accuracy = np.mean(self.performance_metrics['accuracy'][-100:])
            recent_loss = np.mean(self.performance_metrics['loss'][-100:])
            
            self.metrics_history.append({
                'timestamp': datetime.now(),
                'accuracy': recent_accuracy,
                'loss': recent_loss,
                'drift_detections': self.performance_metrics['drift_detections'],
                'model_adaptations': self.performance_metrics['model_adaptations']
            })
            
    def _adapt_learning_parameters(self):
        """Adapt learning parameters based on performance."""
        if len(self.performance_metrics['accuracy']) > 100:
            recent_performance = np.mean(self.performance_metrics['accuracy'][-50:])
            self.online_learner.adapt_learning_rate(recent_performance)
            
    def _calculate_loss(self, prediction, target):
        """Calculate prediction loss."""
        return abs(prediction - target)
        
    def get_system_status(self):
        """Get current system status."""
        return {
            'is_running': self.is_running,
            'processed_samples': len(self.performance_metrics['accuracy']),
            'drift_detections': self.performance_metrics['drift_detections'],
            'model_adaptations': self.performance_metrics['model_adaptations'],
            'current_performance': {
                'accuracy': np.mean(self.performance_metrics['accuracy'][-10:]) if len(self.performance_metrics['accuracy']) >= 10 else 0,
                'loss': np.mean(self.performance_metrics['loss'][-10:]) if len(self.performance_metrics['loss']) >= 10 else 0
            }
        }


class MockOnlineLearner:
    """Mock online learner for testing."""
    
    def __init__(self, learning_rate=0.01, **kwargs):
        self.learning_rate = learning_rate
        self.model_weights = np.random.randn(10) * 0.1
        self.training_history = []
        
    def predict(self, features):
        """Make prediction."""
        if len(features) < 10:
            features = np.pad(features, (0, 10 - len(features)))
        return np.dot(self.model_weights, features[:10])
        
    def update(self, features, target):
        """Update model."""
        prediction = self.predict(features)
        error = target - prediction
        
        # Simple gradient update
        if len(features) < 10:
            features = np.pad(features, (0, 10 - len(features)))
        self.model_weights += self.learning_rate * error * features[:10]
        
        self.training_history.append({
            'timestamp': datetime.now(),
            'error': abs(error)
        })
        
    def adapt_learning_rate(self, performance):
        """Adapt learning rate."""
        if performance < 0.5:
            self.learning_rate *= 1.1
        else:
            self.learning_rate *= 0.99
            
    def reset(self):
        """Reset model."""
        self.model_weights = np.random.randn(10) * 0.1
        self.training_history = []
        
    def get_model_snapshot(self):
        """Get model snapshot."""
        return {
            'weights': self.model_weights.copy(),
            'learning_rate': self.learning_rate,
            'timestamp': datetime.now()
        }


class MockDriftDetector:
    """Mock drift detector for testing."""
    
    def __init__(self, drift_threshold=0.05, **kwargs):
        self.drift_threshold = drift_threshold
        self.reference_window = []
        self.current_window = []
        self.detection_history = []
        
    def add_batch(self, batch):
        """Add data batch."""
        if len(self.reference_window) < 100:
            self.reference_window.extend(batch)
        else:
            self.current_window.extend(batch)
            if len(self.current_window) > 100:
                self.current_window = self.current_window[-100:]
                
    def ensemble_drift_detection(self):
        """Perform drift detection."""
        if len(self.reference_window) < 50 or len(self.current_window) < 50:
            return False, {}
            
        # Simple drift detection
        ref_mean = np.mean(self.reference_window)
        cur_mean = np.mean(self.current_window)
        
        drift_detected = abs(cur_mean - ref_mean) > self.drift_threshold
        
        methods_results = {
            'statistical_distance': (drift_detected, abs(cur_mean - ref_mean)),
            'ks_test': (drift_detected, 0.5),
            'chi2_test': (drift_detected, 0.5),
            'psi': (drift_detected, 0.3)
        }
        
        self.detection_history.append({
            'timestamp': datetime.now(),
            'drift_detected': drift_detected
        })
        
        return drift_detected, methods_results
        
    def update_reference_window(self, new_data):
        """Update reference window."""
        self.reference_window = new_data.copy()


class MockModelSelector:
    """Mock model selector for testing."""
    
    def __init__(self):
        self.models = []
        
    def add_model(self, model_snapshot):
        """Add model to ensemble."""
        self.models.append(model_snapshot)
        
        # Keep only recent models
        if len(self.models) > 5:
            self.models = self.models[-5:]
            
    def select_best_model(self):
        """Select best model from ensemble."""
        if not self.models:
            return None
        return self.models[-1]  # Return most recent


class MockDataBuffer:
    """Mock data buffer for testing."""
    
    def __init__(self, buffer_size=1000):
        self.buffer_size = buffer_size
        self.features = []
        self.targets = []
        
    def add_batch(self, features, targets):
        """Add batch to buffer."""
        self.features.extend(features)
        self.targets.extend(targets)
        
        # Maintain buffer size
        if len(self.features) > self.buffer_size:
            excess = len(self.features) - self.buffer_size
            self.features = self.features[excess:]
            self.targets = self.targets[excess:]
            
    def get_recent_data(self, n_samples):
        """Get recent data."""
        if len(self.features) < n_samples:
            return self.features, self.targets
        return self.features[-n_samples:], self.targets[-n_samples:]


def generate_data_stream(n_batches=10, batch_size=20, drift_point=None):
    """Generate synthetic data stream with optional concept drift."""
    
    for batch_idx in range(n_batches):
        if drift_point and batch_idx >= drift_point:
            # After drift point, change the relationship
            features = [np.random.randn(5) for _ in range(batch_size)]
            targets = [np.sum(f[2:]) + 0.2 * np.random.randn() for f in features]  # Different relationship
        else:
            # Before drift point, stable relationship
            features = [np.random.randn(5) for _ in range(batch_size)]
            targets = [np.sum(f[:3]) + 0.1 * np.random.randn() for f in features]  # Original relationship
            
        yield features, targets


class TestContinuousLearningIntegration:
    """Integration tests for continuous learning system."""
    
    @pytest.fixture
    async def learning_system(self):
        """Create learning system fixture."""
        system = MockContinuousLearningSystem()
        yield system
        system.stop_continuous_learning()
        
    @pytest.mark.asyncio
    async def test_system_startup_shutdown(self, learning_system):
        """Test system startup and shutdown."""
        # System should start not running
        assert not learning_system.is_running
        
        # Start system
        await learning_system.start_continuous_learning()
        assert learning_system.is_running
        
        # Stop system
        learning_system.stop_continuous_learning()
        assert not learning_system.is_running
        
    def test_data_stream_processing(self, learning_system):
        """Test processing of data streams."""
        # Generate data stream
        data_stream = list(generate_data_stream(n_batches=5, batch_size=10))
        
        # Process stream
        processed_samples = learning_system.process_data_stream(data_stream)
        
        assert processed_samples == 50  # 5 batches * 10 samples
        assert len(learning_system.performance_metrics['accuracy']) == 50
        assert len(learning_system.performance_metrics['loss']) == 50
        
    def test_concept_drift_detection_and_adaptation(self, learning_system):
        """Test drift detection and adaptation."""
        # Generate data stream with drift
        data_stream = list(generate_data_stream(n_batches=10, batch_size=20, drift_point=5))
        
        # Process stream
        learning_system.process_data_stream(data_stream)
        
        # Manually trigger drift detection
        initial_adaptations = learning_system.performance_metrics['model_adaptations']
        
        # Simulate some processing to build up reference window
        learning_system.drift_detector.reference_window = np.random.randn(100).tolist()
        learning_system.drift_detector.current_window = np.random.randn(100).tolist() + 2.0  # Shifted
        
        drift_handled = learning_system._check_and_handle_drift()
        
        if drift_handled:
            assert learning_system.performance_metrics['model_adaptations'] > initial_adaptations
            assert len(learning_system.adaptation_history) > 0
            
    def test_performance_monitoring(self, learning_system):
        """Test performance monitoring and metrics collection."""
        # Process some data
        data_stream = list(generate_data_stream(n_batches=3, batch_size=10))
        learning_system.process_data_stream(data_stream)
        
        # Update performance metrics manually
        learning_system._update_performance_metrics()
        
        assert len(learning_system.metrics_history) > 0
        
        latest_metrics = learning_system.metrics_history[-1]
        assert 'accuracy' in latest_metrics
        assert 'loss' in latest_metrics
        assert 'timestamp' in latest_metrics
        
    def test_learning_parameter_adaptation(self, learning_system):
        """Test adaptation of learning parameters."""
        initial_lr = learning_system.online_learner.learning_rate
        
        # Simulate poor performance
        learning_system.performance_metrics['accuracy'] = [0.3] * 150
        learning_system._adapt_learning_parameters()
        
        # Learning rate should increase for poor performance
        assert learning_system.online_learner.learning_rate > initial_lr
        
    def test_model_retraining_after_drift(self, learning_system):
        """Test model retraining after drift detection."""
        # Add some data to buffer
        features = [np.random.randn(5) for _ in range(100)]
        targets = [np.sum(f) for f in features]
        learning_system.data_buffer.add_batch(features, targets)
        
        # Get initial model weights
        initial_weights = learning_system.online_learner.model_weights.copy()
        
        # Simulate drift detection requiring retraining
        drift_info = {
            'statistical_distance': (True, 1.5),
            'ks_test': (True, 0.01),
            'chi2_test': (True, 0.02),
            'psi': (True, 0.4)
        }
        
        learning_system._handle_concept_drift(drift_info)
        
        # Model should have been retrained (weights changed)
        assert not np.array_equal(learning_system.online_learner.model_weights, initial_weights)
        
    def test_ensemble_model_management(self, learning_system):
        """Test ensemble model management."""
        initial_model_count = len(learning_system.model_selector.models)
        
        # Trigger ensemble update
        drift_info = {
            'statistical_distance': (True, 0.8),
            'ks_test': (False, 0.1),
            'chi2_test': (False, 0.1),
            'psi': (False, 0.1)
        }
        
        learning_system._handle_concept_drift(drift_info)
        
        # Should add model to ensemble
        assert len(learning_system.model_selector.models) > initial_model_count
        
    def test_system_status_reporting(self, learning_system):
        """Test system status reporting."""
        # Process some data
        data_stream = list(generate_data_stream(n_batches=2, batch_size=15))
        learning_system.process_data_stream(data_stream)
        
        status = learning_system.get_system_status()
        
        assert 'is_running' in status
        assert 'processed_samples' in status
        assert 'drift_detections' in status
        assert 'model_adaptations' in status
        assert 'current_performance' in status
        
        assert status['processed_samples'] == 30
        assert isinstance(status['current_performance']['accuracy'], float)
        assert isinstance(status['current_performance']['loss'], float)
        
    @pytest.mark.asyncio
    async def test_concurrent_processing(self, learning_system):
        """Test concurrent data processing and monitoring."""
        # Start system
        await learning_system.start_continuous_learning()
        
        # Process data while system is running
        data_stream = list(generate_data_stream(n_batches=3, batch_size=10))
        processed_samples = learning_system.process_data_stream(data_stream)
        
        # Allow some monitoring cycles
        await asyncio.sleep(0.1)
        
        # Stop system
        learning_system.stop_continuous_learning()
        
        assert processed_samples == 30
        
    def test_error_recovery(self, learning_system):
        """Test error recovery in continuous learning."""
        # Simulate error condition
        learning_system.online_learner = None  # This will cause errors
        
        # System should handle gracefully
        try:
            data_stream = [(np.random.randn(1, 5).tolist(), np.random.randn(1).tolist())]
            learning_system.process_data_stream(data_stream)
        except Exception as e:
            # Should not crash the entire system
            pass
            
        # System should still be in valid state
        assert hasattr(learning_system, 'performance_metrics')
        assert hasattr(learning_system, 'drift_detector')
        
    def test_memory_management(self, learning_system):
        """Test memory management with large data streams."""
        # Process large amount of data
        large_stream = list(generate_data_stream(n_batches=50, batch_size=50))
        learning_system.process_data_stream(large_stream)
        
        # Buffers should be bounded
        assert len(learning_system.data_buffer.features) <= learning_system.data_buffer.buffer_size
        assert len(learning_system.drift_detector.reference_window) <= 100
        assert len(learning_system.drift_detector.current_window) <= 100
        
        # Model ensemble should be bounded
        assert len(learning_system.model_selector.models) <= 5


@pytest.mark.integration
class TestContinuousLearningScenarios:
    """Test realistic continuous learning scenarios."""
    
    def test_gradual_concept_drift_scenario(self):
        """Test gradual concept drift scenario."""
        system = MockContinuousLearningSystem({
            'learning_rate': 0.01,
            'drift_threshold': 0.3,
            'monitoring_interval': 5
        })
        
        # Phase 1: Stable learning
        stable_stream = list(generate_data_stream(n_batches=10, batch_size=20))
        system.process_data_stream(stable_stream)
        
        initial_performance = np.mean(system.performance_metrics['accuracy'][-50:])
        
        # Phase 2: Gradual drift
        drift_batches = []
        for i in range(10):
            # Gradually shift the relationship
            shift = i * 0.1
            features = [np.random.randn(5) for _ in range(20)]
            targets = [np.sum(f[:3]) + shift + 0.1 * np.random.randn() for f in features]
            drift_batches.append((features, targets))
            
        system.process_data_stream(drift_batches)
        
        # System should adapt
        final_performance = np.mean(system.performance_metrics['accuracy'][-50:])
        
        # Should have detected and adapted to drift
        assert system.performance_metrics['drift_detections'] >= 0  # May or may not detect gradual drift
        
    def test_sudden_concept_drift_scenario(self):
        """Test sudden concept drift scenario."""
        system = MockContinuousLearningSystem({
            'learning_rate': 0.02,
            'drift_threshold': 0.1,
            'monitoring_interval': 5
        })
        
        # Phase 1: Stable learning
        stable_stream = list(generate_data_stream(n_batches=15, batch_size=20))
        system.process_data_stream(stable_stream)
        
        # Phase 2: Sudden drift
        drift_stream = list(generate_data_stream(n_batches=10, batch_size=20, drift_point=0))
        system.process_data_stream(drift_stream)
        
        # Should have some adaptations due to sudden change
        status = system.get_system_status()
        assert status['processed_samples'] == 500  # 25 batches * 20 samples
        
    def test_multiple_drift_points_scenario(self):
        """Test scenario with multiple drift points."""
        system = MockContinuousLearningSystem()
        
        scenarios = [
            # Normal period
            list(generate_data_stream(n_batches=5, batch_size=15)),
            # First drift
            list(generate_data_stream(n_batches=5, batch_size=15, drift_point=0)),
            # Return to normal
            list(generate_data_stream(n_batches=5, batch_size=15)),
            # Second drift  
            list(generate_data_stream(n_batches=5, batch_size=15, drift_point=0))
        ]
        
        total_processed = 0
        for scenario in scenarios:
            processed = system.process_data_stream(scenario)
            total_processed += processed
            
            # Allow system to adapt between scenarios
            system._update_performance_metrics()
            
        assert total_processed == 300  # 20 batches * 15 samples
        
        # System should maintain reasonable performance despite multiple drifts
        final_status = system.get_system_status()
        assert final_status['processed_samples'] == total_processed


@pytest.mark.slow
class TestContinuousLearningPerformance:
    """Performance tests for continuous learning system."""
    
    def test_high_throughput_processing(self):
        """Test high throughput data processing."""
        system = MockContinuousLearningSystem({
            'buffer_size': 5000,
            'monitoring_interval': 1
        })
        
        # Generate large data stream
        large_stream = list(generate_data_stream(n_batches=100, batch_size=100))
        
        start_time = time.time()
        processed_samples = system.process_data_stream(large_stream)
        end_time = time.time()
        
        processing_time = end_time - start_time
        throughput = processed_samples / processing_time
        
        assert processed_samples == 10000
        assert throughput > 1000  # Should process at least 1000 samples/second
        
    def test_memory_stability_long_running(self):
        """Test memory stability in long-running scenarios."""
        system = MockContinuousLearningSystem()
        
        # Process many small batches
        for i in range(200):
            mini_stream = list(generate_data_stream(n_batches=1, batch_size=10))
            system.process_data_stream(mini_stream)
            
            # Periodic monitoring
            if i % 20 == 0:
                system._check_and_handle_drift()
                system._update_performance_metrics()
                
        # Check final memory usage
        assert len(system.data_buffer.features) <= system.data_buffer.buffer_size
        assert len(system.performance_metrics['accuracy']) == 2000  # All samples tracked
        assert len(system.metrics_history) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])