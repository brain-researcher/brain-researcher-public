"""
Unit tests for Budget Manager

Tests for:
- Budget setting and validation
- Spending tracking and monitoring
- Alert threshold management
- Budget enforcement decisions
- Cost prediction and projection
- Multi-project budget allocation
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
from typing import Dict, List, Any
import asyncio

from brain_researcher.services.agent.budget_manager import (
    BudgetManager, Budget, BudgetPeriod, BudgetDecision, AlertLevel,
    SpendingTracker, AlertSystem, BudgetStatus, ProjectBudget
)


class TestBudgetManager:
    """Test suite for BudgetManager"""
    
    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client for testing"""
        redis = Mock()
        redis.get.return_value = None
        redis.set.return_value = True
        redis.hget.return_value = None
        redis.hset.return_value = True
        return redis
    
    @pytest.fixture
    def mock_alert_system(self):
        """Mock alert system"""
        alert_system = Mock()
        alert_system.send_alert = AsyncMock()
        alert_system.check_alert_conditions.return_value = []
        return alert_system
    
    @pytest.fixture
    def mock_spending_tracker(self):
        """Mock spending tracker"""
        tracker = Mock()
        tracker.get_current_spending.return_value = 250.0
        tracker.get_spending_trend.return_value = {"daily_rate": 35.0, "trend": "stable"}
        tracker.record_expense.return_value = True
        return tracker
    
    @pytest.fixture
    def budget_manager(self, mock_redis_client, mock_alert_system, mock_spending_tracker):
        """Create budget manager with mocked dependencies"""
        manager = BudgetManager(mock_redis_client)
        manager.alerts = mock_alert_system
        manager.spending_tracker = mock_spending_tracker
        return manager
    
    @pytest.fixture
    def sample_budget(self):
        """Sample budget configuration"""
        return Budget(
            project_id="neuroimaging_study_001",
            total_amount=1000.0,
            period=BudgetPeriod.MONTHLY,
            start_date=datetime.now() - timedelta(days=10),
            end_date=datetime.now() + timedelta(days=20),
            alert_thresholds={
                AlertLevel.WARNING: 0.5,    # 50%
                AlertLevel.CAUTION: 0.8,    # 80%
                AlertLevel.CRITICAL: 0.95   # 95%
            },
            hard_limit=True,
            categories={
                "compute": 600.0,
                "storage": 200.0,
                "network": 100.0,
                "software": 100.0
            }
        )
    
    @pytest.mark.unit
    def test_set_budget(self, budget_manager, sample_budget):
        """Test budget setting and validation"""
        success = budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        assert success
        assert sample_budget.project_id in budget_manager.budgets
        
        stored_budget = budget_manager.budgets[sample_budget.project_id]
        assert stored_budget.total_amount == sample_budget.total_amount
        assert stored_budget.period == sample_budget.period
        assert stored_budget.hard_limit == sample_budget.hard_limit
    
    @pytest.mark.unit
    def test_budget_validation(self, budget_manager):
        """Test budget validation logic"""
        # Invalid budget - negative amount
        invalid_budget = Budget(
            project_id="invalid_project",
            total_amount=-100.0,
            period=BudgetPeriod.MONTHLY
        )
        
        with pytest.raises(ValueError, match="Budget amount must be positive"):
            budget_manager.set_budget(invalid_budget.project_id, invalid_budget)
        
        # Invalid budget - end date before start date
        invalid_dates_budget = Budget(
            project_id="invalid_dates",
            total_amount=1000.0,
            period=BudgetPeriod.MONTHLY,
            start_date=datetime.now(),
            end_date=datetime.now() - timedelta(days=1)
        )
        
        with pytest.raises(ValueError, match="End date must be after start date"):
            budget_manager.set_budget(invalid_dates_budget.project_id, invalid_dates_budget)
    
    @pytest.mark.unit
    async def test_check_budget_within_limits(self, budget_manager, sample_budget):
        """Test budget check when within limits"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock current spending at 30% of budget
        budget_manager.spending_tracker.get_current_spending.return_value = 300.0
        
        estimated_cost = 50.0  # Small additional cost
        decision = await budget_manager.check_budget(sample_budget.project_id, estimated_cost)
        
        assert isinstance(decision, BudgetDecision)
        assert decision.approved is True
        assert decision.remaining_budget == 700.0  # 1000 - 300
        assert decision.projected_total == 350.0   # 300 + 50
        assert AlertLevel.WARNING not in [alert.level for alert in decision.alerts]
    
    @pytest.mark.unit
    async def test_check_budget_warning_threshold(self, budget_manager, sample_budget):
        """Test budget check at warning threshold"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock current spending at 60% of budget (above 50% warning threshold)
        budget_manager.spending_tracker.get_current_spending.return_value = 600.0
        
        estimated_cost = 50.0
        decision = await budget_manager.check_budget(sample_budget.project_id, estimated_cost)
        
        assert decision.approved is True  # Still approved but with warning
        assert any(alert.level == AlertLevel.WARNING for alert in decision.alerts)
        assert decision.budget_utilization >= 0.5
    
    @pytest.mark.unit
    async def test_check_budget_hard_limit_enforcement(self, budget_manager, sample_budget):
        """Test hard limit enforcement"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock current spending at 95% of budget
        budget_manager.spending_tracker.get_current_spending.return_value = 950.0
        
        # Large estimated cost that would exceed budget
        estimated_cost = 100.0
        decision = await budget_manager.check_budget(sample_budget.project_id, estimated_cost)
        
        assert decision.approved is False  # Should be denied due to hard limit
        assert decision.denial_reason == "Would exceed budget hard limit"
        assert any(alert.level == AlertLevel.CRITICAL for alert in decision.alerts)
    
    @pytest.mark.unit
    async def test_check_budget_soft_limit_warning(self, budget_manager, sample_budget):
        """Test soft limit warning behavior"""
        # Create budget with soft limit
        soft_limit_budget = sample_budget
        soft_limit_budget.hard_limit = False
        budget_manager.set_budget(soft_limit_budget.project_id, soft_limit_budget)
        
        # Mock spending that would exceed budget
        budget_manager.spending_tracker.get_current_spending.return_value = 950.0
        
        estimated_cost = 100.0
        decision = await budget_manager.check_budget(soft_limit_budget.project_id, estimated_cost)
        
        # Should approve but with strong warning
        assert decision.approved is True
        assert decision.requires_approval is True
        assert any(alert.level == AlertLevel.CRITICAL for alert in decision.alerts)
    
    @pytest.mark.unit
    async def test_budget_projection_accuracy(self, budget_manager, sample_budget):
        """Test budget projection and burn rate calculation"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock spending data with trend
        budget_manager.spending_tracker.get_current_spending.return_value = 400.0
        budget_manager.spending_tracker.get_spending_trend.return_value = {
            "daily_rate": 25.0,
            "trend": "increasing",
            "acceleration": 1.1
        }
        
        # Budget period has 20 days remaining
        days_remaining = (sample_budget.end_date - datetime.now()).days
        
        decision = await budget_manager.check_budget(sample_budget.project_id, 50.0)
        
        # Should project future spending based on burn rate
        projected_spending = 25.0 * days_remaining * 1.1  # With acceleration
        assert decision.projected_end_of_period_spending > 400.0
        assert decision.budget_overrun_risk is not None
    
    @pytest.mark.unit
    def test_generate_budget_report(self, budget_manager, sample_budget):
        """Test budget report generation"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock spending data
        budget_manager.spending_tracker.get_current_spending.return_value = 600.0
        budget_manager.spending_tracker.get_spending_trend.return_value = {
            "daily_rate": 30.0,
            "weekly_rate": 210.0,
            "trend": "stable"
        }
        budget_manager.spending_tracker.get_category_breakdown.return_value = {
            "compute": 350.0,
            "storage": 150.0,
            "network": 70.0,
            "software": 30.0
        }
        
        report = budget_manager.generate_budget_report(sample_budget.project_id, "monthly")
        
        assert report["project_id"] == sample_budget.project_id
        assert report["total_budget"] == 1000.0
        assert report["spent"] == 600.0
        assert report["remaining"] == 400.0
        assert report["utilization_percentage"] == 60.0
        assert "burn_rate" in report
        assert "category_breakdown" in report
        assert "projected_overrun" in report
        assert "top_consumers" in report
        assert "recommendations" in report
    
    @pytest.mark.unit
    def test_category_budget_tracking(self, budget_manager, sample_budget):
        """Test category-specific budget tracking"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock category spending
        budget_manager.spending_tracker.get_category_spending.return_value = {
            "compute": 400.0,  # 66% of compute budget (600)
            "storage": 180.0,  # 90% of storage budget (200) - should alert
            "network": 50.0,   # 50% of network budget
            "software": 20.0   # 20% of software budget
        }
        
        category_status = budget_manager.get_category_budget_status(sample_budget.project_id)
        
        assert "compute" in category_status
        assert "storage" in category_status
        
        # Storage should be flagged as high utilization
        storage_status = category_status["storage"]
        assert storage_status["utilization"] == 0.9
        assert storage_status["alert_level"] == AlertLevel.CAUTION
    
    @pytest.mark.unit
    async def test_alert_system_integration(self, budget_manager, sample_budget):
        """Test integration with alert system"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock spending that triggers alerts
        budget_manager.spending_tracker.get_current_spending.return_value = 850.0  # 85% utilization
        
        decision = await budget_manager.check_budget(sample_budget.project_id, 20.0)
        
        # Should trigger alert sending
        assert len(decision.alerts) > 0
        
        # Verify alert system was called
        budget_manager.alerts.send_alert.assert_called()
        
        # Check alert content
        call_args = budget_manager.alerts.send_alert.call_args[1]
        assert call_args["alert_level"] in [AlertLevel.WARNING, AlertLevel.CAUTION, AlertLevel.CRITICAL]
        assert call_args["project_id"] == sample_budget.project_id
    
    @pytest.mark.unit
    async def test_multi_project_budget_management(self, budget_manager):
        """Test managing budgets across multiple projects"""
        # Create multiple project budgets
        projects = {
            "project_a": Budget(
                project_id="project_a",
                total_amount=500.0,
                period=BudgetPeriod.MONTHLY
            ),
            "project_b": Budget(
                project_id="project_b", 
                total_amount=750.0,
                period=BudgetPeriod.MONTHLY
            ),
            "project_c": Budget(
                project_id="project_c",
                total_amount=1200.0,
                period=BudgetPeriod.QUARTERLY
            )
        }
        
        # Set budgets for all projects
        for project_id, budget in projects.items():
            budget_manager.set_budget(project_id, budget)
        
        # Mock different spending levels
        def mock_get_spending(project_id):
            spending_levels = {
                "project_a": 400.0,  # 80% - caution level
                "project_b": 300.0,  # 40% - okay
                "project_c": 1000.0  # 83% - caution level
            }
            return spending_levels.get(project_id, 0.0)
        
        budget_manager.spending_tracker.get_current_spending.side_effect = mock_get_spending
        
        # Generate consolidated report
        consolidated_report = budget_manager.generate_consolidated_report()
        
        assert len(consolidated_report["projects"]) == 3
        assert consolidated_report["total_allocated"] == 2450.0  # Sum of all budgets
        assert consolidated_report["total_spent"] == 1700.0     # Sum of all spending
        assert len(consolidated_report["alerts"]) >= 2          # Projects A and C should have alerts
    
    @pytest.mark.unit
    async def test_budget_rollover_handling(self, budget_manager):
        """Test budget rollover between periods"""
        # Create budget that's ending soon
        ending_budget = Budget(
            project_id="ending_project",
            total_amount=1000.0,
            period=BudgetPeriod.MONTHLY,
            start_date=datetime.now() - timedelta(days=29),
            end_date=datetime.now() + timedelta(days=1),  # Ending tomorrow
            allow_rollover=True,
            rollover_percentage=0.8  # 80% of unspent can rollover
        )
        
        budget_manager.set_budget(ending_budget.project_id, ending_budget)
        
        # Mock current spending leaving 300 unspent
        budget_manager.spending_tracker.get_current_spending.return_value = 700.0
        
        # Calculate rollover
        rollover_amount = budget_manager.calculate_rollover(ending_budget.project_id)
        
        expected_rollover = 300.0 * 0.8  # 80% of 300 unspent
        assert rollover_amount == expected_rollover
        
        # Test rollover application to new budget period
        new_budget = Budget(
            project_id="ending_project",
            total_amount=1000.0,
            period=BudgetPeriod.MONTHLY,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=30),
            rollover_amount=rollover_amount
        )
        
        budget_manager.apply_rollover(new_budget)
        
        # Total available should be base + rollover
        assert new_budget.total_available == 1000.0 + rollover_amount
    
    @pytest.mark.unit
    async def test_emergency_budget_override(self, budget_manager, sample_budget):
        """Test emergency budget override functionality"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock spending at limit
        budget_manager.spending_tracker.get_current_spending.return_value = 995.0
        
        # Normal check should deny large expense
        large_expense = 100.0
        normal_decision = await budget_manager.check_budget(sample_budget.project_id, large_expense)
        assert normal_decision.approved is False
        
        # Emergency override should allow it
        emergency_decision = await budget_manager.check_budget(
            sample_budget.project_id, 
            large_expense,
            emergency_override=True,
            override_reason="Critical system failure requires immediate resources"
        )
        
        assert emergency_decision.approved is True
        assert emergency_decision.is_emergency_override is True
        assert emergency_decision.override_reason is not None
        
        # Should still generate critical alerts
        assert any(alert.level == AlertLevel.CRITICAL for alert in emergency_decision.alerts)
    
    @pytest.mark.unit
    async def test_cost_forecast_integration(self, budget_manager, sample_budget):
        """Test integration with cost forecasting"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock cost forecasting data
        with patch.object(budget_manager, '_get_cost_forecast') as mock_forecast:
            mock_forecast.return_value = {
                "next_7_days": 180.0,
                "next_30_days": 650.0,
                "confidence_interval": (580.0, 720.0),
                "forecast_accuracy": 0.85
            }
            
            decision = await budget_manager.check_budget(sample_budget.project_id, 50.0)
            
            # Should include forecast in decision
            assert decision.cost_forecast is not None
            assert decision.cost_forecast["next_30_days"] == 650.0
            assert decision.forecast_confidence == 0.85
    
    @pytest.mark.unit
    async def test_budget_optimization_suggestions(self, budget_manager, sample_budget):
        """Test budget optimization suggestions"""
        budget_manager.set_budget(sample_budget.project_id, sample_budget)
        
        # Mock spending data showing inefficiencies
        budget_manager.spending_tracker.get_detailed_spending.return_value = {
            "spot_instances": 200.0,
            "on_demand_instances": 300.0,  # Could be optimized
            "reserved_instances": 50.0,
            "storage_standard": 100.0,
            "storage_archive": 20.0,
            "network_transfer": 80.0
        }
        
        report = budget_manager.generate_budget_report(sample_budget.project_id, "monthly")
        
        # Should include optimization recommendations
        recommendations = report["recommendations"]
        assert len(recommendations) > 0
        
        # Should suggest spot instance usage
        spot_recommendation = next((r for r in recommendations if "spot" in r.lower()), None)
        assert spot_recommendation is not None
        
        # Should suggest storage optimization
        storage_recommendation = next((r for r in recommendations if "storage" in r.lower()), None)
        assert storage_recommendation is not None


class TestSpendingTracker:
    """Test suite for SpendingTracker"""
    
    @pytest.fixture
    def spending_tracker(self, mock_redis_client):
        return SpendingTracker(mock_redis_client)
    
    @pytest.mark.unit
    def test_record_expense(self, spending_tracker):
        """Test expense recording"""
        expense = {
            "project_id": "test_project",
            "amount": 25.50,
            "category": "compute",
            "resource_type": "ec2_instance",
            "timestamp": datetime.now(),
            "metadata": {"instance_id": "i-1234567890abcdef0"}
        }
        
        success = spending_tracker.record_expense(expense)
        assert success
        
        # Verify Redis calls were made
        spending_tracker.redis_client.hset.assert_called()
    
    @pytest.mark.unit
    def test_get_current_spending(self, spending_tracker):
        """Test current spending retrieval"""
        project_id = "test_project"
        
        # Mock Redis responses
        spending_tracker.redis_client.hgetall.return_value = {
            "total": "750.25",
            "compute": "450.00", 
            "storage": "200.25",
            "network": "100.00"
        }
        
        total_spending = spending_tracker.get_current_spending(project_id)
        assert total_spending == 750.25
        
        category_spending = spending_tracker.get_category_spending(project_id)
        assert category_spending["compute"] == 450.00
        assert category_spending["storage"] == 200.25
    
    @pytest.mark.unit
    def test_spending_trend_analysis(self, spending_tracker):
        """Test spending trend analysis"""
        project_id = "test_project"
        
        # Mock historical spending data
        with patch.object(spending_tracker, '_get_historical_spending') as mock_historical:
            mock_historical.return_value = [
                {"date": "2025-01-01", "amount": 20.0},
                {"date": "2025-01-02", "amount": 25.0},
                {"date": "2025-01-03", "amount": 30.0},
                {"date": "2025-01-04", "amount": 28.0},
                {"date": "2025-01-05", "amount": 32.0}
            ]
            
            trend = spending_tracker.get_spending_trend(project_id, days=5)
            
            assert "daily_rate" in trend
            assert "trend" in trend
            assert trend["trend"] in ["increasing", "decreasing", "stable"]
            assert trend["daily_rate"] > 0


class TestAlertSystem:
    """Test suite for AlertSystem"""
    
    @pytest.fixture
    def alert_system(self):
        return AlertSystem()
    
    @pytest.mark.unit
    async def test_send_alert(self, alert_system):
        """Test alert sending"""
        with patch.object(alert_system, '_send_email_alert') as mock_email, \
             patch.object(alert_system, '_send_slack_alert') as mock_slack:
            
            await alert_system.send_alert(
                alert_level=AlertLevel.WARNING,
                project_id="test_project",
                message="Budget threshold exceeded",
                recipients=["admin@example.com"],
                channels=["#budget-alerts"]
            )
            
            mock_email.assert_called_once()
            mock_slack.assert_called_once()
    
    @pytest.mark.unit
    def test_alert_condition_checking(self, alert_system):
        """Test alert condition evaluation"""
        budget_status = {
            "utilization": 0.85,
            "projected_overrun": True,
            "days_remaining": 5,
            "burn_rate": 50.0
        }
        
        alert_conditions = alert_system.check_alert_conditions(budget_status)
        
        # Should detect high utilization and projected overrun
        assert len(alert_conditions) >= 2
        assert any(condition["type"] == "high_utilization" for condition in alert_conditions)
        assert any(condition["type"] == "projected_overrun" for condition in alert_conditions)


# Integration tests
@pytest.mark.integration
class TestBudgetManagerIntegration:
    """Integration tests for budget management system"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_budget_workflow(self):
        """Test complete budget management workflow"""
        # Would test with actual Redis and notification systems
        pass
    
    @pytest.mark.asyncio
    async def test_multi_user_budget_management(self):
        """Test budget management with multiple concurrent users"""
        # Would test concurrent access and updates
        pass
    
    @pytest.mark.asyncio
    async def test_budget_persistence_and_recovery(self):
        """Test budget data persistence and recovery"""
        # Would test data persistence across system restarts
        pass


# Performance tests
@pytest.mark.performance
class TestBudgetManagerPerformance:
    """Performance tests for budget management"""
    
    def test_high_volume_expense_tracking(self):
        """Test performance with high volume of expense records"""
        # Would test with thousands of expense records
        pass
    
    def test_concurrent_budget_checks(self):
        """Test concurrent budget check performance"""
        # Would test multiple simultaneous budget checks
        pass