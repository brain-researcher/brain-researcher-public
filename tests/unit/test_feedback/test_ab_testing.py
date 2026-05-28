"""Unit tests for A/B Testing Framework."""

import json
import pytest
import redis
from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.feedback.ab_testing import (
    ABTestingFramework,
    StatisticalAnalyzer,
    Experiment,
    ExperimentStatus,
    ExperimentResult
)


class TestStatisticalAnalyzer:
    """Test statistical analysis methods."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.analyzer = StatisticalAnalyzer()
    
    def test_calculate_conversion_rate_basic(self):
        """Test basic conversion rate calculation."""
        rate = self.analyzer.calculate_conversion_rate(10, 100)
        assert 0.0 < rate < 1.0
        assert rate == (10 + 1) / (100 + 2)  # Laplace smoothing
    
    def test_calculate_conversion_rate_zero_trials(self):
        """Test conversion rate with zero trials."""
        rate = self.analyzer.calculate_conversion_rate(0, 0)
        assert rate == 0.0
    
    def test_calculate_conversion_rate_perfect_conversion(self):
        """Test perfect conversion rate."""
        rate = self.analyzer.calculate_conversion_rate(100, 100)
        assert rate == (100 + 1) / (100 + 2)
    
    def test_wilson_confidence_interval_basic(self):
        """Test Wilson confidence interval calculation."""
        lower, upper = self.analyzer.wilson_confidence_interval(50, 100)
        assert 0.0 <= lower <= upper <= 1.0
        assert lower != upper  # Should have non-zero width
    
    def test_wilson_confidence_interval_zero_trials(self):
        """Test confidence interval with zero trials."""
        lower, upper = self.analyzer.wilson_confidence_interval(0, 0)
        assert lower == 0.0
        assert upper == 0.0
    
    def test_wilson_confidence_interval_different_alphas(self):
        """Test confidence intervals with different significance levels."""
        lower_95, upper_95 = self.analyzer.wilson_confidence_interval(50, 100, alpha=0.05)
        lower_99, upper_99 = self.analyzer.wilson_confidence_interval(50, 100, alpha=0.01)
        
        # 99% CI should be wider than 95% CI
        assert (upper_99 - lower_99) > (upper_95 - lower_95)
    
    def test_two_proportion_z_test_basic(self):
        """Test two-proportion z-test."""
        z_stat, p_value = self.analyzer.two_proportion_z_test(50, 100, 30, 100)
        assert isinstance(z_stat, float)
        assert 0.0 <= p_value <= 1.0
    
    def test_two_proportion_z_test_identical_proportions(self):
        """Test z-test with identical proportions."""
        z_stat, p_value = self.analyzer.two_proportion_z_test(50, 100, 50, 100)
        assert abs(z_stat) < 0.01  # Should be close to 0
        assert p_value > 0.9  # Should have high p-value
    
    def test_two_proportion_z_test_zero_trials(self):
        """Test z-test with zero trials."""
        z_stat, p_value = self.analyzer.two_proportion_z_test(0, 0, 10, 100)
        assert z_stat == 0.0
        assert p_value == 1.0
    
    def test_bayesian_probability_basic(self):
        """Test Bayesian probability calculation."""
        prob = self.analyzer.bayesian_probability(60, 100, 40, 100)
        assert 0.0 <= prob <= 1.0
        assert prob > 0.5  # First variant should be better
    
    def test_bayesian_probability_identical(self):
        """Test Bayesian probability with identical performance."""
        prob = self.analyzer.bayesian_probability(50, 100, 50, 100)
        assert 0.4 <= prob <= 0.6  # Should be around 0.5
    
    def test_bayesian_probability_deterministic(self):
        """Test Bayesian probability with clear winner."""
        prob = self.analyzer.bayesian_probability(90, 100, 10, 100)
        assert prob > 0.95  # Should be very confident


class TestExperiment:
    """Test Experiment data class."""
    
    def test_experiment_creation(self):
        """Test experiment creation with defaults."""
        exp = Experiment(
            id="test_exp",
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"],
            status=ExperimentStatus.DRAFT
        )
        
        assert exp.id == "test_exp"
        assert exp.created_at is not None
        assert isinstance(exp.created_at, datetime)
    
    def test_experiment_with_custom_created_at(self):
        """Test experiment with custom creation time."""
        custom_time = datetime(2023, 1, 1)
        exp = Experiment(
            id="test_exp",
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"],
            status=ExperimentStatus.DRAFT,
            created_at=custom_time
        )
        
        assert exp.created_at == custom_time


class TestABTestingFramework:
    """Test A/B Testing Framework."""
    
    def setup_method(self):
        """Setup test fixtures."""
        # Mock Redis client
        self.mock_redis = Mock(spec=redis.Redis)
        self.mock_redis.decode_responses = True
        self.mock_redis.scan_iter.return_value = []
        
        self.framework = ABTestingFramework(redis_client=self.mock_redis)
    
    def test_create_experiment_valid(self):
        """Test creating valid experiment."""
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"],
            sample_size=1000
        )
        
        assert exp.name == "Test Experiment"
        assert exp.status == ExperimentStatus.DRAFT
        assert exp.id in self.framework.experiments
        
        # Verify Redis save was called
        self.mock_redis.hset.assert_called()
    
    def test_create_experiment_invalid_allocation(self):
        """Test creating experiment with invalid allocation."""
        with pytest.raises(ValueError, match="Allocation ratios must sum to 1.0"):
            self.framework.create_experiment(
                name="Invalid Experiment",
                description="Invalid allocation",
                variants=["control", "treatment"],
                allocation={"control": 0.3, "treatment": 0.5},  # Sums to 0.8
                metrics=["conversion_rate"]
            )
    
    def test_create_experiment_mismatched_variants(self):
        """Test creating experiment with mismatched variants."""
        with pytest.raises(ValueError, match="Allocation keys must match variants"):
            self.framework.create_experiment(
                name="Mismatched Experiment",
                description="Mismatched variants",
                variants=["control", "treatment"],
                allocation={"control": 0.5, "variant_b": 0.5},
                metrics=["conversion_rate"]
            )
    
    def test_start_experiment(self):
        """Test starting an experiment."""
        # Create experiment first
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        # Start experiment
        self.framework.start_experiment(exp.id)
        
        assert self.framework.experiments[exp.id].status == ExperimentStatus.RUNNING
        assert self.framework.experiments[exp.id].start_date is not None
    
    def test_start_nonexistent_experiment(self):
        """Test starting non-existent experiment."""
        with pytest.raises(ValueError, match="Experiment nonexistent not found"):
            self.framework.start_experiment("nonexistent")
    
    def test_stop_experiment(self):
        """Test stopping an experiment."""
        # Create and start experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        self.framework.start_experiment(exp.id)
        
        # Stop experiment
        self.framework.stop_experiment(exp.id)
        
        assert self.framework.experiments[exp.id].status == ExperimentStatus.COMPLETED
        assert self.framework.experiments[exp.id].end_date is not None
    
    def test_assign_user_running_experiment(self):
        """Test user assignment for running experiment."""
        # Create and start experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        self.framework.start_experiment(exp.id)
        
        # Mock Redis responses
        self.mock_redis.get.return_value = None  # No existing assignment
        self.mock_redis.setex.return_value = True
        self.mock_redis.sadd.return_value = 1
        
        # Assign user
        variant = self.framework.assign_user("user123", exp.id)
        
        assert variant in ["control", "treatment"]
        self.mock_redis.setex.assert_called()
        self.mock_redis.sadd.assert_called()
    
    def test_assign_user_existing_assignment(self):
        """Test user assignment with existing assignment."""
        # Create and start experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        self.framework.start_experiment(exp.id)
        
        # Mock existing assignment
        self.mock_redis.get.return_value = "treatment"
        
        # Assign user
        variant = self.framework.assign_user("user123", exp.id)
        
        assert variant == "treatment"
        # Should not create new assignment
        self.mock_redis.setex.assert_not_called()
    
    def test_assign_user_non_running_experiment(self):
        """Test user assignment for non-running experiment."""
        # Create experiment (not started)
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        # Assign user
        variant = self.framework.assign_user("user123", exp.id)
        
        # Should return control variant
        assert variant == "control"
    
    def test_assign_user_consistent_hashing(self):
        """Test consistent user assignment."""
        # Create and start experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        self.framework.start_experiment(exp.id)
        
        # Mock Redis responses
        self.mock_redis.get.return_value = None
        self.mock_redis.setex.return_value = True
        self.mock_redis.sadd.return_value = 1
        
        # Same user should get same assignment
        variant1 = self.framework.assign_user("user123", exp.id)
        variant2 = self.framework.assign_user("user123", exp.id)
        
        # Reset mocks to ensure we're testing consistency
        self.mock_redis.reset_mock()
        self.mock_redis.get.return_value = None
        
        variant3 = self.framework.assign_user("user123", exp.id)
        
        # All assignments should be the same due to consistent hashing
        assert variant1 == variant3
    
    def test_get_experiment_status(self):
        """Test getting experiment status."""
        # Create experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"],
            sample_size=1000
        )
        self.framework.start_experiment(exp.id)
        
        # Mock assignment counts
        self.mock_redis.scard.side_effect = [300, 250]  # control: 300, treatment: 250
        
        status = self.framework.get_experiment_status(exp.id)
        
        assert status["experiment"]["id"] == exp.id
        assert status["total_assignments"] == 550
        assert status["variant_assignments"]["control"] == 300
        assert status["variant_assignments"]["treatment"] == 250
        assert status["completion_rate"] == 0.55  # 550/1000
    
    def test_list_experiments_all(self):
        """Test listing all experiments."""
        # Create multiple experiments
        exp1 = self.framework.create_experiment(
            name="Experiment 1",
            description="First experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        exp2 = self.framework.create_experiment(
            name="Experiment 2",
            description="Second experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        # Mock assignment counts
        self.mock_redis.scard.return_value = 100
        
        experiments = self.framework.list_experiments()
        
        assert len(experiments) == 2
        assert any(exp["name"] == "Experiment 1" for exp in experiments)
        assert any(exp["name"] == "Experiment 2" for exp in experiments)
    
    def test_list_experiments_filtered(self):
        """Test listing experiments with status filter."""
        # Create experiments with different statuses
        exp1 = self.framework.create_experiment(
            name="Draft Experiment",
            description="Draft experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        exp2 = self.framework.create_experiment(
            name="Running Experiment",
            description="Running experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        self.framework.start_experiment(exp2.id)
        
        # Mock assignment counts
        self.mock_redis.scard.return_value = 50
        
        # Filter by status
        draft_experiments = self.framework.list_experiments(ExperimentStatus.DRAFT)
        running_experiments = self.framework.list_experiments(ExperimentStatus.RUNNING)
        
        assert len(draft_experiments) == 1
        assert draft_experiments[0]["name"] == "Draft Experiment"
        
        assert len(running_experiments) == 1
        assert running_experiments[0]["name"] == "Running Experiment"
    
    def test_get_experiment_results(self):
        """Test getting experiment results."""
        # Create experiment
        exp = self.framework.create_experiment(
            name="Test Experiment",
            description="A test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
        
        # Mock variant metrics data
        self.framework._get_variant_metrics = Mock()
        self.framework._get_variant_metrics.side_effect = [
            {"conversions": 50, "impressions": 500},  # control
            {"conversions": 65, "impressions": 480}   # treatment
        ]
        
        results = self.framework.get_experiment_results(exp.id)
        
        assert "conversion_rate" in results
        result = results["conversion_rate"]
        
        # Check that statistical analysis was performed
        assert "control_rate" in result
        assert "treatment_rate" in result
        assert "p_value" in result
        assert "significant" in result
    
    @patch('brain_researcher.services.feedback.ab_testing.datetime')
    def test_generate_experiment_id_unique(self, mock_datetime):
        """Test experiment ID generation is unique."""
        mock_datetime.utcnow.return_value = datetime(2023, 1, 1)
        
        with patch('time.time', return_value=1672531200):  # Fixed timestamp
            id1 = self.framework._generate_experiment_id("Test Experiment")
            id2 = self.framework._generate_experiment_id("Another Experiment")
        
        assert id1 != id2
        assert id1.startswith("exp_")
        assert id2.startswith("exp_")


@pytest.mark.integration
class TestABTestingIntegration:
    """Integration tests for A/B testing framework."""
    
    @pytest.fixture
    def redis_client(self):
        """Setup Redis client for integration tests."""
        try:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)
        except ImportError:
            pytest.skip("fakeredis not available for integration tests")
    
    def test_full_experiment_lifecycle(self, redis_client):
        """Test complete experiment lifecycle."""
        framework = ABTestingFramework(redis_client=redis_client)
        
        # Create experiment
        exp = framework.create_experiment(
            name="Integration Test",
            description="Full lifecycle test",
            variants=["control", "treatment"],
            allocation={"control": 0.6, "treatment": 0.4},
            metrics=["conversion_rate"],
            sample_size=1000
        )
        
        # Start experiment
        framework.start_experiment(exp.id)
        
        # Simulate user assignments
        assignments = {}
        for i in range(100):
            user_id = f"user_{i}"
            variant = framework.assign_user(user_id, exp.id)
            assignments[user_id] = variant
        
        # Check assignment distribution
        control_count = sum(1 for v in assignments.values() if v == "control")
        treatment_count = sum(1 for v in assignments.values() if v == "treatment")
        
        # Should roughly follow allocation ratios (60/40)
        assert 45 <= control_count <= 75  # Allow some variance
        assert 25 <= treatment_count <= 55
        
        # Stop experiment
        framework.stop_experiment(exp.id)
        
        # Verify final status
        final_exp = framework.experiments[exp.id]
        assert final_exp.status == ExperimentStatus.COMPLETED
        assert final_exp.end_date is not None
    
    def test_experiment_persistence(self, redis_client):
        """Test experiment persistence across framework instances."""
        # Create experiment with first framework instance
        framework1 = ABTestingFramework(redis_client=redis_client)
        exp = framework1.create_experiment(
            name="Persistence Test",
            description="Test persistence",
            variants=["A", "B"],
            allocation={"A": 0.5, "B": 0.5},
            metrics=["conversion_rate"]
        )
        
        # Create second framework instance
        framework2 = ABTestingFramework(redis_client=redis_client)
        
        # Should load existing experiment
        assert exp.id in framework2.experiments
        assert framework2.experiments[exp.id].name == "Persistence Test"


class TestExperimentResultsAnalysis:
    """Test experiment results analysis."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.mock_redis = Mock(spec=redis.Redis)
        self.framework = ABTestingFramework(redis_client=self.mock_redis)
        
        # Create test experiment
        self.experiment = self.framework.create_experiment(
            name="Test Experiment",
            description="Test experiment",
            variants=["control", "treatment"],
            allocation={"control": 0.5, "treatment": 0.5},
            metrics=["conversion_rate"]
        )
    
    def test_analyze_significant_difference(self):
        """Test analysis with significant difference."""
        # Mock variant data showing significant difference
        variant_data = {
            "control": {"conversions": 50, "impressions": 1000},
            "treatment": {"conversions": 80, "impressions": 1000}
        }
        
        result = self.framework._analyze_metric(
            self.experiment, "conversion_rate", variant_data
        )
        
        assert result["control_rate"] < result["treatment_rate"]
        assert result["lift"] > 0
        assert result["p_value"] < 0.05
        assert result["significant"] is True
        assert result["probability_treatment_better"] > 0.8
    
    def test_analyze_no_difference(self):
        """Test analysis with no significant difference."""
        # Mock variant data showing no difference
        variant_data = {
            "control": {"conversions": 50, "impressions": 1000},
            "treatment": {"conversions": 52, "impressions": 1000}
        }
        
        result = self.framework._analyze_metric(
            self.experiment, "conversion_rate", variant_data
        )
        
        assert abs(result["control_rate"] - result["treatment_rate"]) < 0.01
        assert abs(result["lift"]) < 0.1
        assert result["p_value"] > 0.05
        assert result["significant"] is False
        assert 0.4 < result["probability_treatment_better"] < 0.6
    
    def test_analyze_zero_data(self):
        """Test analysis with zero data."""
        variant_data = {
            "control": {"conversions": 0, "impressions": 0},
            "treatment": {"conversions": 0, "impressions": 0}
        }
        
        result = self.framework._analyze_metric(
            self.experiment, "conversion_rate", variant_data
        )
        
        # Should handle zero data gracefully
        assert result["control_rate"] == 0.0
        assert result["treatment_rate"] == 0.0
        assert result["z_statistic"] == 0.0
        assert result["p_value"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__])