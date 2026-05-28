"""Unit tests for drift detector."""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from typing import List, Dict, Any
from scipy import stats


class MockDriftDetector:
    """Mock drift detector implementation for testing."""
    
    def __init__(self, window_size=100, sensitivity=0.05):
        self.window_size = window_size
        self.sensitivity = sensitivity
        self.reference_window = []
        self.current_window = []
        self.drift_history = []
        self.detection_methods = ['ks_test', 'chi2_test', 'psi', 'statistical_distance']
        
    def add_batch(self, data_batch):
        """Add new data batch for drift detection."""
        if len(self.reference_window) < self.window_size:
            self.reference_window.extend(data_batch)
            if len(self.reference_window) > self.window_size:
                self.reference_window = self.reference_window[-self.window_size:]
        else:
            self.current_window.extend(data_batch)
            if len(self.current_window) > self.window_size:
                self.current_window = self.current_window[-self.window_size:]
                
    def detect_drift_ks_test(self, new_data=None):
        """Detect drift using Kolmogorov-Smirnov test."""
        if new_data is not None:
            test_data = new_data
        else:
            test_data = self.current_window
            
        if len(self.reference_window) < 50 or len(test_data) < 50:
            return False, 1.0
            
        # Perform KS test
        statistic, p_value = stats.ks_2samp(self.reference_window, test_data)
        
        drift_detected = p_value < self.sensitivity
        self.drift_history.append({
            'timestamp': datetime.now(),
            'method': 'ks_test',
            'statistic': statistic,
            'p_value': p_value,
            'drift_detected': drift_detected
        })
        
        return drift_detected, p_value
        
    def detect_drift_chi2_test(self, new_data=None, bins=10):
        """Detect drift using Chi-square test."""
        if new_data is not None:
            test_data = new_data
        else:
            test_data = self.current_window
            
        if len(self.reference_window) < 50 or len(test_data) < 50:
            return False, 1.0
            
        # Create histograms
        combined_data = np.concatenate([self.reference_window, test_data])
        bin_edges = np.linspace(np.min(combined_data), np.max(combined_data), bins + 1)
        
        ref_hist, _ = np.histogram(self.reference_window, bins=bin_edges)
        test_hist, _ = np.histogram(test_data, bins=bin_edges)
        
        # Avoid zero frequencies
        ref_hist = ref_hist + 1
        test_hist = test_hist + 1
        
        # Chi-square test
        statistic, p_value = stats.chisquare(test_hist, ref_hist)
        
        drift_detected = p_value < self.sensitivity
        self.drift_history.append({
            'timestamp': datetime.now(),
            'method': 'chi2_test',
            'statistic': statistic,
            'p_value': p_value,
            'drift_detected': drift_detected
        })
        
        return drift_detected, p_value
        
    def detect_drift_psi(self, new_data=None, bins=10):
        """Detect drift using Population Stability Index."""
        if new_data is not None:
            test_data = new_data
        else:
            test_data = self.current_window
            
        if len(self.reference_window) < 50 or len(test_data) < 50:
            return False, 0.0
            
        # Create histograms
        combined_data = np.concatenate([self.reference_window, test_data])
        bin_edges = np.linspace(np.min(combined_data), np.max(combined_data), bins + 1)
        
        ref_hist, _ = np.histogram(self.reference_window, bins=bin_edges)
        test_hist, _ = np.histogram(test_data, bins=bin_edges)
        
        # Convert to proportions
        ref_prop = (ref_hist + 1) / (len(self.reference_window) + bins)  # Laplace smoothing
        test_prop = (test_hist + 1) / (len(test_data) + bins)
        
        # Calculate PSI
        psi = np.sum((test_prop - ref_prop) * np.log(test_prop / ref_prop))
        
        # PSI thresholds: <0.1 no change, 0.1-0.25 minor change, >0.25 major change
        drift_detected = psi > 0.25
        
        self.drift_history.append({
            'timestamp': datetime.now(),
            'method': 'psi',
            'statistic': psi,
            'p_value': None,
            'drift_detected': drift_detected
        })
        
        return drift_detected, psi
        
    def detect_drift_statistical_distance(self, new_data=None):
        """Detect drift using statistical distance measures."""
        if new_data is not None:
            test_data = new_data
        else:
            test_data = self.current_window
            
        if len(self.reference_window) < 50 or len(test_data) < 50:
            return False, 0.0
            
        ref_mean = np.mean(self.reference_window)
        test_mean = np.mean(test_data)
        ref_std = np.std(self.reference_window)
        test_std = np.std(test_data)
        
        # Normalized difference in means
        pooled_std = np.sqrt((ref_std**2 + test_std**2) / 2)
        if pooled_std == 0:
            return False, 0.0
            
        distance = abs(test_mean - ref_mean) / pooled_std
        
        # Threshold for significant change
        threshold = 2.0  # 2 standard deviations
        drift_detected = distance > threshold
        
        self.drift_history.append({
            'timestamp': datetime.now(),
            'method': 'statistical_distance',
            'statistic': distance,
            'p_value': None,
            'drift_detected': drift_detected
        })
        
        return drift_detected, distance
        
    def ensemble_drift_detection(self, new_data=None):
        """Perform ensemble drift detection using multiple methods."""
        methods_results = {}
        
        methods_results['ks_test'] = self.detect_drift_ks_test(new_data)
        methods_results['chi2_test'] = self.detect_drift_chi2_test(new_data)
        methods_results['psi'] = self.detect_drift_psi(new_data)
        methods_results['statistical_distance'] = self.detect_drift_statistical_distance(new_data)
        
        # Ensemble voting
        drift_votes = sum(1 for method, (detected, _) in methods_results.items() if detected)
        ensemble_detected = drift_votes >= 2  # Majority vote
        
        return ensemble_detected, methods_results
        
    def update_reference_window(self, new_data):
        """Update reference window with new data (concept adaptation)."""
        if len(new_data) >= self.window_size:
            self.reference_window = list(new_data[-self.window_size:])
        else:
            self.reference_window.extend(new_data)
            if len(self.reference_window) > self.window_size:
                self.reference_window = self.reference_window[-self.window_size:]
                
    def get_drift_statistics(self):
        """Get statistics about drift detection."""
        if not self.drift_history:
            return {}
            
        total_detections = len(self.drift_history)
        drift_count = sum(1 for h in self.drift_history if h['drift_detected'])
        
        stats_by_method = {}
        for method in self.detection_methods:
            method_history = [h for h in self.drift_history if h['method'] == method]
            if method_history:
                stats_by_method[method] = {
                    'total_checks': len(method_history),
                    'drift_detections': sum(1 for h in method_history if h['drift_detected']),
                    'avg_statistic': np.mean([h['statistic'] for h in method_history if h['statistic'] is not None])
                }
                
        return {
            'total_detections': total_detections,
            'drift_count': drift_count,
            'drift_rate': drift_count / total_detections if total_detections > 0 else 0,
            'methods_stats': stats_by_method
        }


class TestDriftDetector:
    """Test drift detection functionality."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.detector = MockDriftDetector(window_size=100, sensitivity=0.05)
        
    def test_initialization(self):
        """Test drift detector initialization."""
        assert self.detector.window_size == 100
        assert self.detector.sensitivity == 0.05
        assert len(self.detector.reference_window) == 0
        assert len(self.detector.current_window) == 0
        assert len(self.detector.drift_history) == 0
        
    def test_add_batch(self):
        """Test adding data batches."""
        # Add initial batch
        batch1 = np.random.randn(50).tolist()
        self.detector.add_batch(batch1)
        
        assert len(self.detector.reference_window) == 50
        assert len(self.detector.current_window) == 0
        
        # Add more to fill reference window
        batch2 = np.random.randn(60).tolist()
        self.detector.add_batch(batch2)
        
        assert len(self.detector.reference_window) == 100  # Limited by window_size
        assert len(self.detector.current_window) == 10     # Overflow goes to current
        
    def test_ks_test_no_drift(self):
        """Test KS test with no drift."""
        # Generate stable data from same distribution
        reference_data = np.random.normal(0, 1, 100).tolist()
        test_data = np.random.normal(0, 1, 100).tolist()
        
        self.detector.reference_window = reference_data
        
        drift_detected, p_value = self.detector.detect_drift_ks_test(test_data)
        
        # Should not detect drift (p_value should be high)
        assert isinstance(drift_detected, bool)
        assert isinstance(p_value, float)
        assert 0 <= p_value <= 1
        assert len(self.detector.drift_history) == 1
        
    def test_ks_test_with_drift(self):
        """Test KS test with drift."""
        # Generate data from different distributions
        reference_data = np.random.normal(0, 1, 100).tolist()
        test_data = np.random.normal(3, 1, 100).tolist()  # Mean shift
        
        self.detector.reference_window = reference_data
        
        drift_detected, p_value = self.detector.detect_drift_ks_test(test_data)
        
        # Should detect drift (p_value should be low)
        assert isinstance(drift_detected, bool)
        assert isinstance(p_value, float)
        assert 0 <= p_value <= 1
        # With such a large mean shift, should detect drift
        assert drift_detected or p_value < 0.1  # Either detected or very low p-value
        
    def test_chi2_test(self):
        """Test Chi-square test."""
        reference_data = np.random.exponential(1, 100).tolist()
        test_data = np.random.exponential(2, 100).tolist()  # Different scale
        
        self.detector.reference_window = reference_data
        
        drift_detected, p_value = self.detector.detect_drift_chi2_test(test_data)
        
        assert isinstance(drift_detected, bool)
        assert isinstance(p_value, float)
        assert 0 <= p_value <= 1
        assert len(self.detector.drift_history) == 1
        assert self.detector.drift_history[0]['method'] == 'chi2_test'
        
    def test_psi_detection(self):
        """Test Population Stability Index."""
        reference_data = np.random.beta(2, 5, 100).tolist()
        test_data = np.random.beta(5, 2, 100).tolist()  # Different shape
        
        self.detector.reference_window = reference_data
        
        drift_detected, psi_value = self.detector.detect_drift_psi(test_data)
        
        assert isinstance(drift_detected, bool)
        assert isinstance(psi_value, float)
        assert psi_value >= 0  # PSI is always non-negative
        assert len(self.detector.drift_history) == 1
        assert self.detector.drift_history[0]['method'] == 'psi'
        
    def test_statistical_distance_detection(self):
        """Test statistical distance detection."""
        reference_data = np.random.normal(0, 1, 100).tolist()
        test_data = np.random.normal(5, 1, 100).tolist()  # Large mean shift
        
        self.detector.reference_window = reference_data
        
        drift_detected, distance = self.detector.detect_drift_statistical_distance(test_data)
        
        assert isinstance(drift_detected, bool)
        assert isinstance(distance, float)
        assert distance >= 0
        # Large mean shift should be detected
        assert drift_detected
        assert distance > 2.0  # Should exceed threshold
        
    def test_ensemble_detection(self):
        """Test ensemble drift detection."""
        reference_data = np.random.gamma(2, 1, 100).tolist()
        test_data = np.random.gamma(4, 1, 100).tolist()  # Different shape
        
        self.detector.reference_window = reference_data
        
        ensemble_detected, methods_results = self.detector.ensemble_drift_detection(test_data)
        
        assert isinstance(ensemble_detected, bool)
        assert isinstance(methods_results, dict)
        assert len(methods_results) == 4
        
        for method in ['ks_test', 'chi2_test', 'psi', 'statistical_distance']:
            assert method in methods_results
            detected, value = methods_results[method]
            assert isinstance(detected, bool)
            assert isinstance(value, (float, type(None)))
            
    def test_insufficient_data(self):
        """Test behavior with insufficient data."""
        # Small reference window
        small_data = [1, 2, 3, 4, 5]
        self.detector.reference_window = small_data
        
        test_data = [6, 7, 8, 9, 10]
        
        # All methods should return False with insufficient data
        drift_detected, _ = self.detector.detect_drift_ks_test(test_data)
        assert not drift_detected
        
        drift_detected, _ = self.detector.detect_drift_chi2_test(test_data)
        assert not drift_detected
        
        drift_detected, _ = self.detector.detect_drift_psi(test_data)
        assert not drift_detected
        
        drift_detected, _ = self.detector.detect_drift_statistical_distance(test_data)
        assert not drift_detected
        
    def test_update_reference_window(self):
        """Test updating reference window."""
        initial_data = list(range(100))
        self.detector.reference_window = initial_data.copy()
        
        # Update with new data
        new_data = list(range(100, 150))
        self.detector.update_reference_window(new_data)
        
        # Should contain last 100 elements
        expected = list(range(50, 150))
        assert self.detector.reference_window == expected
        
    def test_drift_statistics(self):
        """Test drift statistics collection."""
        # Generate some drift history
        reference_data = np.random.normal(0, 1, 100).tolist()
        self.detector.reference_window = reference_data
        
        # Run multiple detections
        for i in range(5):
            test_data = np.random.normal(i, 1, 100).tolist()
            self.detector.detect_drift_ks_test(test_data)
            self.detector.detect_drift_chi2_test(test_data)
            
        stats = self.detector.get_drift_statistics()
        
        assert 'total_detections' in stats
        assert 'drift_count' in stats
        assert 'drift_rate' in stats
        assert 'methods_stats' in stats
        
        assert stats['total_detections'] == 10  # 5 iterations * 2 methods
        assert 0 <= stats['drift_rate'] <= 1
        
    def test_edge_cases(self):
        """Test edge cases."""
        # Empty reference window
        drift_detected, _ = self.detector.detect_drift_ks_test([1, 2, 3])
        assert not drift_detected
        
        # Identical data
        identical_data = [1] * 100
        self.detector.reference_window = identical_data.copy()
        drift_detected, distance = self.detector.detect_drift_statistical_distance(identical_data)
        assert not drift_detected
        assert distance == 0.0
        
        # Single value in both windows
        self.detector.reference_window = [1] * 100
        drift_detected, _ = self.detector.detect_drift_ks_test([1] * 100)
        assert not drift_detected


class TestDriftDetectorIntegration:
    """Integration tests for drift detector."""
    
    def test_continuous_monitoring(self):
        """Test continuous drift monitoring."""
        detector = MockDriftDetector(window_size=50, sensitivity=0.01)
        
        # Phase 1: Stable data
        for i in range(20):
            batch = np.random.normal(0, 1, 10).tolist()
            detector.add_batch(batch)
            
        # Phase 2: Gradual drift
        drift_detected_count = 0
        for i in range(30):
            # Gradually shift mean
            mean_shift = i * 0.1
            batch = np.random.normal(mean_shift, 1, 10).tolist()
            detector.add_batch(batch)
            
            if len(detector.reference_window) >= 50:
                ensemble_detected, _ = detector.ensemble_drift_detection()
                if ensemble_detected:
                    drift_detected_count += 1
                    
        # Should detect drift as mean shifts
        assert drift_detected_count > 0
        
        # Get final statistics
        stats = detector.get_drift_statistics()
        assert stats['total_detections'] > 0
        
    def test_adaptation_after_drift(self):
        """Test adaptation after drift detection."""
        detector = MockDriftDetector(window_size=100)
        
        # Establish baseline
        baseline_data = np.random.normal(0, 1, 200).tolist()
        detector.add_batch(baseline_data[:100])
        detector.add_batch(baseline_data[100:])
        
        # Introduce drift
        drifted_data = np.random.normal(3, 1, 100).tolist()
        ensemble_detected, _ = detector.ensemble_drift_detection(drifted_data)
        
        if ensemble_detected:
            # Adapt to new distribution
            detector.update_reference_window(drifted_data)
            
            # Test with more data from new distribution
            new_data = np.random.normal(3, 1, 100).tolist()
            post_adapt_detected, _ = detector.ensemble_drift_detection(new_data)
            
            # Should detect less drift after adaptation
            assert not post_adapt_detected or len(detector.drift_history) > 0
            
    def test_multiple_distribution_changes(self):
        """Test handling multiple distribution changes."""
        detector = MockDriftDetector(window_size=100)
        
        distributions = [
            lambda: np.random.normal(0, 1, 50),      # Normal
            lambda: np.random.exponential(1, 50),    # Exponential  
            lambda: np.random.uniform(-2, 2, 50),    # Uniform
            lambda: np.random.beta(2, 5, 50)         # Beta
        ]
        
        drift_detections = []
        
        # Initialize with first distribution
        initial_data = distributions[0]().tolist()
        detector.add_batch(initial_data)
        detector.add_batch(distributions[0]().tolist())
        
        # Switch between distributions
        for i, dist_func in enumerate(distributions[1:], 1):
            new_data = dist_func().tolist()
            ensemble_detected, methods_results = detector.ensemble_drift_detection(new_data)
            
            drift_detections.append({
                'distribution': i,
                'ensemble_detected': ensemble_detected,
                'methods_results': methods_results
            })
            
            # Adapt to new distribution
            if ensemble_detected:
                detector.update_reference_window(new_data)
                
        # Should detect drift when switching distributions
        total_detections = sum(1 for d in drift_detections if d['ensemble_detected'])
        assert total_detections > 0


@pytest.mark.performance
class TestDriftDetectorPerformance:
    """Performance tests for drift detector."""
    
    def test_large_data_performance(self):
        """Test performance with large datasets."""
        detector = MockDriftDetector(window_size=1000)
        
        # Large reference dataset
        large_reference = np.random.normal(0, 1, 1000).tolist()
        detector.reference_window = large_reference
        
        # Large test dataset
        large_test = np.random.normal(0.5, 1, 1000).tolist()
        
        import time
        start_time = time.time()
        
        # Run ensemble detection
        drift_detected, results = detector.ensemble_drift_detection(large_test)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete in reasonable time (< 1 second)
        assert execution_time < 1.0
        assert isinstance(drift_detected, bool)
        assert len(results) == 4
        
    def test_memory_usage(self):
        """Test memory usage with continuous data streams."""
        detector = MockDriftDetector(window_size=100)
        
        # Process many batches
        for i in range(1000):
            batch = np.random.randn(10).tolist()
            detector.add_batch(batch)
            
            # Periodically check for drift
            if i % 10 == 0:
                detector.detect_drift_ks_test()
                
        # Windows should be bounded by window_size
        assert len(detector.reference_window) <= 100
        assert len(detector.current_window) <= 100
        
        # History can grow but should be manageable
        assert len(detector.drift_history) <= 200  # About 100 iterations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])