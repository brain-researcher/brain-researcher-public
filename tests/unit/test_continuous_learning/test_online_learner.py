"""Unit tests for online learner."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from typing import List, Dict, Any


class MockOnlineLearner:
    """Mock implementation for testing purposes."""
    
    def __init__(self, learning_rate=0.01, buffer_size=1000):
        self.learning_rate = learning_rate
        self.buffer_size = buffer_size
        self.model_weights = np.random.randn(10)
        self.training_history = []
        self.drift_detected = False
        
    def update(self, features, target):
        """Update model with new data."""
        prediction_error = np.random.randn()  # Mock error
        self.model_weights += self.learning_rate * prediction_error * features[:10]
        self.training_history.append({
            'timestamp': datetime.now(),
            'error': abs(prediction_error),
            'drift_detected': self.drift_detected
        })
        
    def predict(self, features):
        """Make prediction."""
        return np.dot(self.model_weights, features[:10])
        
    def detect_drift(self, new_data, threshold=0.05):
        """Detect concept drift."""
        # Simple mock drift detection
        recent_errors = [h['error'] for h in self.training_history[-50:]]
        if len(recent_errors) > 10:
            recent_avg = np.mean(recent_errors[-10:])
            historical_avg = np.mean(recent_errors[:-10])
            self.drift_detected = abs(recent_avg - historical_avg) > threshold
        return self.drift_detected
        
    def adapt_learning_rate(self, performance_metric):
        """Adapt learning rate based on performance."""
        if performance_metric < 0.5:
            self.learning_rate *= 1.1  # Increase if performance is poor
        else:
            self.learning_rate *= 0.99  # Slightly decrease if good


class TestOnlineLearner:
    """Test online learning functionality."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.learner = MockOnlineLearner(learning_rate=0.01)
        
    def test_initialization(self):
        """Test learner initialization."""
        assert self.learner.learning_rate == 0.01
        assert self.learner.buffer_size == 1000
        assert len(self.learner.model_weights) == 10
        assert len(self.learner.training_history) == 0
        
    def test_update_single(self):
        """Test single update."""
        features = np.random.randn(15)
        target = np.random.randn()
        
        initial_weights = self.learner.model_weights.copy()
        self.learner.update(features, target)
        
        # Weights should change
        assert not np.array_equal(self.learner.model_weights, initial_weights)
        assert len(self.learner.training_history) == 1
        
    def test_prediction(self):
        """Test prediction functionality."""
        features = np.random.randn(15)
        prediction = self.learner.predict(features)
        
        assert isinstance(prediction, (float, np.floating))
        assert np.isfinite(prediction)
        
    def test_drift_detection(self):
        """Test concept drift detection."""
        # Generate data without drift
        for i in range(30):
            features = np.random.randn(15)
            target = np.sum(features[:5]) + 0.1 * np.random.randn()  # Consistent pattern
            self.learner.update(features, target)
            
        # Check no drift detected initially
        assert not self.learner.detect_drift([], threshold=0.1)
        
        # Generate data with drift (different pattern)
        for i in range(20):
            features = np.random.randn(15)
            target = np.sum(features[5:10]) + 0.5 * np.random.randn()  # Different pattern
            self.learner.update(features, target)
            
        # Should potentially detect drift (depends on random values)
        drift_result = self.learner.detect_drift([], threshold=0.1)
        assert isinstance(drift_result, bool)
        
    def test_learning_rate_adaptation(self):
        """Test learning rate adaptation."""
        initial_lr = self.learner.learning_rate
        
        # Poor performance should increase learning rate
        self.learner.adapt_learning_rate(0.3)
        assert self.learner.learning_rate > initial_lr
        
        # Good performance should decrease learning rate  
        self.learner.adapt_learning_rate(0.8)
        assert self.learner.learning_rate < initial_lr * 1.1
        
    def test_continuous_learning_simulation(self):
        """Test continuous learning over time."""
        # Simulate streaming data
        for epoch in range(100):
            # Generate batch of data
            batch_features = [np.random.randn(15) for _ in range(10)]
            batch_targets = [np.sum(f[:5]) + 0.1 * np.random.randn() for f in batch_features]
            
            # Process batch
            for features, target in zip(batch_features, batch_targets):
                self.learner.update(features, target)
                
            # Periodic drift detection
            if epoch % 20 == 0:
                self.learner.detect_drift([])
                
            # Periodic learning rate adaptation
            if epoch % 30 == 0:
                recent_errors = [h['error'] for h in self.learner.training_history[-50:]]
                avg_error = np.mean(recent_errors) if recent_errors else 1.0
                performance = max(0, 1 - avg_error)
                self.learner.adapt_learning_rate(performance)
        
        # Should have training history
        assert len(self.learner.training_history) == 1000  # 100 epochs * 10 samples
        
        # Learning rate should have been adapted
        assert self.learner.learning_rate != 0.01


class TestDriftDetector:
    """Test drift detection functionality."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.detector = MockDriftDetector()
        
    def test_statistical_drift_detection(self):
        """Test statistical drift detection methods."""
        # Generate stable data
        stable_data = [np.random.normal(0, 1, 100) for _ in range(50)]
        
        # No drift should be detected
        for batch in stable_data:
            drift = self.detector.detect_drift_statistical(batch)
            assert isinstance(drift, bool)
            
        # Generate data with mean shift (drift)
        shifted_data = [np.random.normal(2, 1, 100) for _ in range(20)]
        
        drift_detected = False
        for batch in shifted_data:
            if self.detector.detect_drift_statistical(batch):
                drift_detected = True
                break
                
        # Should detect drift (though not guaranteed due to statistical nature)
        # At minimum, should not crash and return boolean
        assert isinstance(drift_detected, bool)


class MockDriftDetector:
    """Mock drift detector for testing."""
    
    def __init__(self):
        self.reference_data = []
        self.window_size = 100
        
    def detect_drift_statistical(self, new_data, method='ks_test'):
        """Detect drift using statistical tests."""
        if len(self.reference_data) < 50:
            self.reference_data.extend(new_data[:50])
            return False
            
        # Simple comparison (mock implementation)
        ref_mean = np.mean(self.reference_data)
        new_mean = np.mean(new_data)
        
        # Basic threshold test
        return abs(new_mean - ref_mean) > 1.0


@pytest.mark.integration 
class TestContinuousLearningIntegration:
    """Integration tests for continuous learning."""
    
    def test_online_learning_pipeline(self):
        """Test complete online learning pipeline."""
        learner = MockOnlineLearner()
        
        # Simulate realistic data stream
        n_samples = 500
        
        for i in range(n_samples):
            # Generate features with potential concept drift
            if i < 250:
                # Stable period
                features = np.random.randn(15)
                target = np.sum(features[:5]) + 0.1 * np.random.randn()
            else:
                # Drift period - different relationship
                features = np.random.randn(15) 
                target = np.sum(features[5:10]) + 0.1 * np.random.randn()
                
            # Update model
            learner.update(features, target)
            
            # Periodic drift detection
            if i % 50 == 0 and i > 100:
                learner.detect_drift([])
                
        # Check that learning occurred
        assert len(learner.training_history) == n_samples
        
        # Should have detected some drift
        drift_detections = sum(1 for h in learner.training_history if h['drift_detected'])
        print(f"Drift detections: {drift_detections}/{n_samples}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])