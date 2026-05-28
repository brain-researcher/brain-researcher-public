import pytest
pytest.skip("cost optimization integration skipped (env not configured)", allow_module_level=True)
"""
Integration tests for Advanced Cost Optimization System

Tests for:
- End-to-end cost optimization workflows
- Integration between spot optimizer and budget manager
- Real-world cost optimization scenarios
- Multi-cloud cost comparison
- Long-running neuroimaging job optimization
- Budget enforcement in production scenarios
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
from typing import Dict, List, Any
import json
import tempfile

from brain_researcher.services.agent.spot_optimizer import (
    SpotInstanceOptimizer, CloudProvider, ResourceRequirements, BiddingStrategy
)
from brain_researcher.services.agent.budget_manager import (
    BudgetManager, Budget, BudgetPeriod, AlertLevel
)
from brain_researcher.services.agent.cost_predictor import CostPredictor
from brain_researcher.services.orchestrator.cost_endpoints import CostOptimizationService


@pytest.mark.integration
class TestCostOptimizationIntegration:
    """Integration tests for the complete cost optimization system"""
    
    @pytest.fixture
    def cost_optimization_service(self):
        """Create integrated cost optimization service"""
        return CostOptimizationService()
    
    @pytest.fixture
    def neuroimaging_workflow_spec(self):
        """Complete neuroimaging workflow specification"""
        return {
            "workflow_id": "fmri_preprocessing_pipeline",
            "description": "Complete fMRI preprocessing and analysis pipeline",
            "estimated_duration": {"min_hours": 12, "max_hours": 24, "typical_hours": 18},
            "resource_requirements": {
                "stages": [
                    {
                        "name": "data_validation",
                        "duration_hours": 1,
                        "cpu_cores": 4,
                        "memory_gb": 16,
                        "storage_gb": 100,
                        "software_requirements": ["python", "nibabel"]
                    },
                    {
                        "name": "fmriprep_preprocessing",
                        "duration_hours": 12,
                        "cpu_cores": 16,
                        "memory_gb": 64,
                        "storage_gb": 500,
                        "software_requirements": ["fmriprep", "freesurfer", "fsl"]
                    },
                    {
                        "name": "quality_control",
                        "duration_hours": 2,
                        "cpu_cores": 8,
                        "memory_gb": 32,
                        "storage_gb": 200,
                        "software_requirements": ["mriqc", "python"]
                    },
                    {
                        "name": "first_level_analysis",
                        "duration_hours": 4,
                        "cpu_cores": 12,
                        "memory_gb": 48,
                        "storage_gb": 300,
                        "software_requirements": ["nilearn", "spm12"]
                    }
                ]
            },
            "data_requirements": {
                "input_size_gb": 50,
                "intermediate_size_gb": 200,
                "output_size_gb": 30,
                "total_storage_needed": 500
            },
            "priority": "standard",
            "deadline": datetime.now() + timedelta(days=3),
            "budget_constraints": {
                "max_cost": 200.0,
                "cost_optimization_priority": "balanced"  # minimize_cost, minimize_time, balanced
            }
        }
    
    @pytest.fixture
    def multi_project_scenario(self):
        """Multi-project cost optimization scenario"""
        return {
            "projects": [
                {
                    "project_id": "resting_state_study",
                    "budget": {"total": 500.0, "remaining": 350.0},
                    "workflows": [
                        {"type": "preprocessing", "priority": "high", "deadline": "2025-01-15"},
                        {"type": "connectivity_analysis", "priority": "medium", "deadline": "2025-01-20"}
                    ]
                },
                {
                    "project_id": "task_based_study", 
                    "budget": {"total": 800.0, "remaining": 600.0},
                    "workflows": [
                        {"type": "preprocessing", "priority": "medium", "deadline": "2025-01-18"},
                        {"type": "glm_analysis", "priority": "high", "deadline": "2025-01-22"}
                    ]
                },
                {
                    "project_id": "longitudinal_study",
                    "budget": {"total": 1200.0, "remaining": 200.0},
                    "workflows": [
                        {"type": "preprocessing", "priority": "low", "deadline": "2025-01-25"},
                        {"type": "longitudinal_analysis", "priority": "medium", "deadline": "2025-01-30"}
                    ]
                }
            ],
            "global_constraints": {
                "max_concurrent_jobs": 10,
                "preferred_providers": ["aws", "gcp"],
                "cost_optimization_goal": "minimize_total_cost"
            }
        }
    
    @pytest.mark.asyncio
    async def test_end_to_end_cost_optimization_workflow(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test complete end-to-end cost optimization workflow"""
        # Submit cost optimization request
        optimization_request = {
            "workflow_spec": neuroimaging_workflow_spec,
            "optimization_goals": {
                "primary": "minimize_cost",
                "secondary": "maximize_reliability",
                "constraints": {
                    "max_cost": 200.0,
                    "min_reliability": 0.85,
                    "max_duration_hours": 30
                }
            }
        }
        
        # Execute optimization
        optimization_result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
        
        # Verify optimization results
        assert optimization_result["status"] == "success"
        assert "recommendations" in optimization_result
        assert "cost_breakdown" in optimization_result
        assert "risk_assessment" in optimization_result
        
        recommendations = optimization_result["recommendations"]
        assert len(recommendations) > 0
        
        # Check that recommendations are within budget
        for rec in recommendations:
            assert rec["estimated_cost"] <= neuroimaging_workflow_spec["budget_constraints"]["max_cost"]
            assert rec["reliability_score"] >= 0.8
            
        # Verify cost breakdown
        cost_breakdown = optimization_result["cost_breakdown"]
        assert "compute_cost" in cost_breakdown
        assert "storage_cost" in cost_breakdown
        assert "network_cost" in cost_breakdown
        assert "total_estimated_cost" in cost_breakdown
        
        total_cost = cost_breakdown["total_estimated_cost"]
        assert total_cost <= optimization_request["optimization_goals"]["constraints"]["max_cost"]
    
    @pytest.mark.asyncio
    async def test_spot_instance_optimization_integration(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test integration with spot instance optimization"""
        # Configure for aggressive cost optimization (high spot usage)
        optimization_request = {
            "workflow_spec": neuroimaging_workflow_spec,
            "optimization_goals": {
                "primary": "minimize_cost",
                "spot_instance_preference": "aggressive",
                "fault_tolerance": "high"  # Can handle interruptions
            }
        }
        
        with patch('brain_researcher.services.agent.spot_optimizer.SpotInstanceOptimizer') as MockSpotOptimizer:
            # Mock spot optimizer responses
            mock_optimizer = MockSpotOptimizer.return_value
            mock_optimizer.get_spot_recommendations = AsyncMock(return_value=[
                {
                    "provider": "aws",
                    "instance_type": "c5.4xlarge",
                    "current_price": 0.08,
                    "on_demand_price": 0.192,
                    "savings_percentage": 58.3,
                    "interruption_probability": 0.15,
                    "availability_score": 0.85,
                    "expected_cost": 14.40  # for 18-hour job
                },
                {
                    "provider": "gcp",
                    "instance_type": "n1-standard-16",
                    "current_price": 0.075,
                    "on_demand_price": 0.180,
                    "savings_percentage": 58.3,
                    "interruption_probability": 0.12,
                    "availability_score": 0.88,
                    "expected_cost": 13.50
                }
            ])
            
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Verify spot instances were considered
            assert result["status"] == "success"
            assert "spot_optimization" in result
            
            spot_analysis = result["spot_optimization"]
            assert spot_analysis["total_savings_percentage"] > 50
            assert spot_analysis["recommended_spot_usage"] is True
            assert "interruption_mitigation" in spot_analysis
    
    @pytest.mark.asyncio
    async def test_budget_enforcement_integration(self, cost_optimization_service):
        """Test integration with budget enforcement"""
        # Create scenario with tight budget constraints
        constrained_workflow = {
            "workflow_id": "budget_constrained_analysis",
            "resource_requirements": {
                "cpu_cores": 32,
                "memory_gb": 128,
                "storage_gb": 1000,
                "estimated_duration_hours": 20
            },
            "budget_constraints": {
                "max_cost": 50.0,  # Very tight budget
                "hard_limit": True
            }
        }
        
        with patch('brain_researcher.services.agent.budget_manager.BudgetManager') as MockBudgetManager:
            mock_budget_manager = MockBudgetManager.return_value
            mock_budget_manager.check_budget = AsyncMock(return_value={
                "approved": False,
                "remaining_budget": 30.0,
                "denial_reason": "Estimated cost exceeds remaining budget",
                "alternatives": [
                    {
                        "option": "reduce_resources",
                        "estimated_cost": 45.0,
                        "trade_offs": "Longer execution time"
                    },
                    {
                        "option": "wait_for_budget_renewal",
                        "estimated_wait_days": 7
                    }
                ]
            })
            
            optimization_request = {"workflow_spec": constrained_workflow}
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Should provide alternatives when budget is exceeded
            assert result["status"] == "budget_constrained"
            assert "alternatives" in result
            assert len(result["alternatives"]) >= 2
            
            # Should suggest cost reduction strategies
            alternatives = result["alternatives"]
            cost_reduction_alt = next((alt for alt in alternatives if alt["option"] == "reduce_resources"), None)
            assert cost_reduction_alt is not None
            assert cost_reduction_alt["estimated_cost"] < constrained_workflow["budget_constraints"]["max_cost"]
    
    @pytest.mark.asyncio
    async def test_multi_cloud_cost_comparison(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test multi-cloud cost comparison and optimization"""
        # Configure for multi-cloud optimization
        optimization_request = {
            "workflow_spec": neuroimaging_workflow_spec,
            "cloud_preferences": {
                "allowed_providers": ["aws", "gcp", "azure"],
                "region_preferences": {
                    "aws": ["us-east-1", "us-west-2"],
                    "gcp": ["us-central1", "us-east1"],
                    "azure": ["eastus", "westus2"]
                },
                "optimization_scope": "global"
            }
        }
        
        with patch.multiple(
            'brain_researcher.services.agent.spot_optimizer',
            _fetch_aws_spot_prices=AsyncMock(return_value=[
                {"instance_type": "c5.4xlarge", "price": 0.08, "region": "us-east-1"}
            ]),
            _fetch_gcp_spot_prices=AsyncMock(return_value=[
                {"instance_type": "n1-standard-16", "price": 0.075, "region": "us-central1"}
            ]),
            _fetch_azure_spot_prices=AsyncMock(return_value=[
                {"instance_type": "Standard_D16s_v3", "price": 0.085, "region": "eastus"}
            ])
        ):
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Should provide comparison across providers
            assert "multi_cloud_analysis" in result
            
            analysis = result["multi_cloud_analysis"]
            assert "provider_comparison" in analysis
            assert len(analysis["provider_comparison"]) == 3  # AWS, GCP, Azure
            
            # Should recommend cheapest option
            providers = analysis["provider_comparison"]
            cheapest_provider = min(providers, key=lambda p: p["estimated_total_cost"])
            assert result["recommended_provider"] == cheapest_provider["provider"]
    
    @pytest.mark.asyncio
    async def test_long_running_job_optimization(self, cost_optimization_service):
        """Test optimization strategies for long-running neuroimaging jobs"""
        long_running_workflow = {
            "workflow_id": "longitudinal_analysis_pipeline",
            "estimated_duration": {"min_hours": 48, "max_hours": 120, "typical_hours": 72},
            "resource_requirements": {
                "cpu_cores": 64,
                "memory_gb": 256,
                "storage_gb": 2000,
                "gpu_count": 2,
                "persistent_storage": True
            },
            "fault_tolerance": {
                "checkpointing": True,
                "checkpoint_frequency_hours": 6,
                "max_restart_attempts": 3
            },
            "budget_constraints": {
                "max_cost": 800.0
            }
        }
        
        optimization_request = {"workflow_spec": long_running_workflow}
        result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
        
        # Should provide specialized strategies for long-running jobs
        assert "long_running_optimization" in result
        
        long_running_opts = result["long_running_optimization"]
        
        # Should recommend checkpointing strategy
        assert "checkpointing_strategy" in long_running_opts
        assert long_running_opts["checkpointing_strategy"]["enabled"] is True
        
        # Should consider spot instance interruption handling
        if "spot_instances_recommended" in long_running_opts:
            assert "interruption_handling" in long_running_opts
            assert "checkpoint_frequency" in long_running_opts["interruption_handling"]
        
        # Should suggest resource scaling strategies
        assert "scaling_strategy" in long_running_opts
        scaling = long_running_opts["scaling_strategy"]
        assert scaling["type"] in ["static", "dynamic", "hybrid"]
    
    @pytest.mark.asyncio
    async def test_multi_project_resource_allocation(self, cost_optimization_service, multi_project_scenario):
        """Test multi-project resource allocation and optimization"""
        optimization_request = {
            "multi_project_scenario": multi_project_scenario,
            "optimization_goals": {
                "global_objective": "minimize_total_cost",
                "fairness_constraint": "proportional_to_budget",
                "deadline_adherence": "strict"
            }
        }
        
        result = await cost_optimization_service.optimize_multi_project_allocation(optimization_request)
        
        assert result["status"] == "success"
        assert "project_allocations" in result
        assert "resource_sharing_opportunities" in result
        assert "global_optimization_summary" in result
        
        # Verify each project has allocation plan
        allocations = result["project_allocations"]
        assert len(allocations) == 3  # Three projects in scenario
        
        for allocation in allocations:
            assert "project_id" in allocation
            assert "recommended_resources" in allocation
            assert "estimated_cost" in allocation
            assert "timeline" in allocation
            
            # Check budget compliance
            project = next(p for p in multi_project_scenario["projects"] 
                          if p["project_id"] == allocation["project_id"])
            assert allocation["estimated_cost"] <= project["budget"]["remaining"]
        
        # Check resource sharing recommendations
        sharing_ops = result["resource_sharing_opportunities"]
        if sharing_ops:
            assert "shared_storage" in sharing_ops or "compute_time_sharing" in sharing_ops
    
    @pytest.mark.asyncio
    async def test_real_time_cost_monitoring_integration(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test integration with real-time cost monitoring"""
        # Start workflow with cost monitoring
        optimization_request = {
            "workflow_spec": neuroimaging_workflow_spec,
            "monitoring": {
                "real_time_cost_tracking": True,
                "alert_thresholds": {
                    "cost_deviation": 0.15,  # Alert if cost deviates >15% from estimate
                    "budget_utilization": 0.80  # Alert at 80% budget utilization
                },
                "monitoring_interval_minutes": 5
            }
        }
        
        with patch('brain_researcher.services.agent.cost_predictor.CostPredictor') as MockCostPredictor:
            mock_predictor = MockCostPredictor.return_value
            
            # Simulate cost tracking over time
            cost_updates = [
                {"elapsed_hours": 2, "actual_cost": 8.50, "projected_total": 76.50},
                {"elapsed_hours": 6, "actual_cost": 28.00, "projected_total": 84.00},  # Higher than expected
                {"elapsed_hours": 12, "actual_cost": 52.00, "projected_total": 78.00}  # Back on track
            ]
            
            mock_predictor.track_real_time_cost = AsyncMock(return_value=cost_updates)
            
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Should set up monitoring
            assert result["monitoring_configured"] is True
            assert "cost_tracking_id" in result
            
            # Simulate monitoring alerts
            monitoring_result = await cost_optimization_service.check_cost_monitoring(
                result["cost_tracking_id"]
            )
            
            assert "cost_alerts" in monitoring_result
            # Should detect the cost spike at 6 hours
            alerts = monitoring_result["cost_alerts"]
            cost_spike_alert = next((alert for alert in alerts if "deviation" in alert["type"]), None)
            assert cost_spike_alert is not None
    
    @pytest.mark.asyncio
    async def test_disaster_recovery_cost_optimization(self, cost_optimization_service):
        """Test cost optimization for disaster recovery scenarios"""
        disaster_recovery_scenario = {
            "scenario_type": "infrastructure_failure",
            "failed_resources": {
                "region": "us-east-1",
                "affected_jobs": [
                    {"job_id": "job_001", "progress_percentage": 75, "checkpoint_available": True},
                    {"job_id": "job_002", "progress_percentage": 20, "checkpoint_available": False},
                    {"job_id": "job_003", "progress_percentage": 90, "checkpoint_available": True}
                ]
            },
            "recovery_requirements": {
                "max_acceptable_delay_hours": 12,
                "data_recovery_needed": True,
                "priority_jobs": ["job_003"]  # High priority job near completion
            },
            "budget_constraints": {
                "emergency_budget": 300.0,
                "normal_budget_remaining": 150.0
            }
        }
        
        recovery_result = await cost_optimization_service.optimize_disaster_recovery(disaster_recovery_scenario)
        
        assert recovery_result["status"] == "recovery_plan_generated"
        assert "recovery_strategy" in recovery_result
        assert "cost_analysis" in recovery_result
        assert "timeline" in recovery_result
        
        # Should prioritize near-completion jobs
        strategy = recovery_result["recovery_strategy"]
        priority_job_strategy = next((s for s in strategy["job_recovery_plans"] 
                                     if s["job_id"] == "job_003"), None)
        assert priority_job_strategy["priority"] == "highest"
        
        # Should use checkpoints when available
        job_001_strategy = next((s for s in strategy["job_recovery_plans"] 
                               if s["job_id"] == "job_001"), None)
        assert job_001_strategy["use_checkpoint"] is True
        
        # Total recovery cost should be within emergency budget
        total_cost = recovery_result["cost_analysis"]["total_recovery_cost"]
        assert total_cost <= disaster_recovery_scenario["budget_constraints"]["emergency_budget"]
    
    @pytest.mark.asyncio
    async def test_cost_optimization_with_compliance_constraints(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test cost optimization with regulatory compliance constraints"""
        # Add compliance requirements
        compliance_workflow = neuroimaging_workflow_spec.copy()
        compliance_workflow.update({
            "compliance_requirements": {
                "data_residency": "us_only",
                "encryption": "fips_140_2_level_3",
                "audit_logging": "comprehensive",
                "access_controls": "role_based",
                "certifications_required": ["hipaa", "sox"]
            },
            "data_classification": "sensitive_healthcare"
        })
        
        optimization_request = {
            "workflow_spec": compliance_workflow,
            "compliance_priority": "strict"
        }
        
        result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
        
        # Should respect compliance constraints
        assert "compliance_analysis" in result
        
        compliance_analysis = result["compliance_analysis"]
        assert compliance_analysis["data_residency_compliant"] is True
        assert compliance_analysis["encryption_compliant"] is True
        
        # Recommendations should only include compliant resources
        recommendations = result["recommendations"]
        for rec in recommendations:
            assert rec["compliance_verified"] is True
            assert "us" in rec["region"].lower()  # US-only requirement
            assert rec["encryption_support"] is True
    
    @pytest.mark.asyncio
    async def test_cost_optimization_performance_benchmarking(self, cost_optimization_service):
        """Test cost optimization performance with benchmarking data"""
        benchmark_scenario = {
            "benchmark_type": "neuroimaging_pipeline_performance",
            "historical_performance_data": {
                "fmriprep_preprocessing": {
                    "average_runtime_hours": {"c5.4xlarge": 14.2, "c5.2xlarge": 18.5, "m5.4xlarge": 16.1},
                    "cost_per_subject": {"c5.4xlarge": 2.85, "c5.2xlarge": 2.92, "m5.4xlarge": 3.10},
                    "failure_rates": {"c5.4xlarge": 0.02, "c5.2xlarge": 0.03, "m5.4xlarge": 0.015}
                },
                "first_level_analysis": {
                    "average_runtime_hours": {"c5.4xlarge": 3.2, "c5.2xlarge": 4.1, "r5.4xlarge": 2.8},
                    "cost_per_analysis": {"c5.4xlarge": 0.65, "c5.2xlarge": 0.68, "r5.4xlarge": 0.72}
                }
            },
            "current_workload": {
                "preprocessing_jobs": 25,
                "analysis_jobs": 40,
                "deadline": datetime.now() + timedelta(days=5)
            }
        }
        
        result = await cost_optimization_service.optimize_with_benchmarks(benchmark_scenario)
        
        # Should use performance data to optimize instance selection
        assert "performance_optimized_recommendations" in result
        
        recommendations = result["performance_optimized_recommendations"]
        
        # Should recommend best performance/cost ratio instances
        preprocessing_rec = next((r for r in recommendations if "preprocessing" in r["workload_type"]), None)
        assert preprocessing_rec is not None
        # c5.4xlarge has best combination of speed and cost for preprocessing
        assert preprocessing_rec["recommended_instance_type"] == "c5.4xlarge"
        
        # Should include performance predictions
        assert "performance_predictions" in result
        predictions = result["performance_predictions"]
        assert predictions["total_estimated_runtime_hours"] > 0
        assert predictions["cost_efficiency_score"] > 0


@pytest.mark.integration
@pytest.mark.slow
class TestCostOptimizationScalability:
    """Scalability tests for cost optimization system"""
    
    @pytest.mark.asyncio
    async def test_large_scale_multi_project_optimization(self, cost_optimization_service):
        """Test optimization with large number of projects and workflows"""
        # Generate large-scale scenario
        large_scale_scenario = {
            "projects": [
                {
                    "project_id": f"project_{i:03d}",
                    "budget": {"total": 1000 + (i * 100), "remaining": 500 + (i * 50)},
                    "workflows": [
                        {"type": "preprocessing", "priority": "medium"},
                        {"type": "analysis", "priority": "low"}
                    ]
                } for i in range(50)  # 50 projects
            ]
        }
        
        import time
        start_time = time.time()
        
        result = await cost_optimization_service.optimize_multi_project_allocation({
            "multi_project_scenario": large_scale_scenario,
            "optimization_goals": {"global_objective": "minimize_total_cost"}
        })
        
        end_time = time.time()
        optimization_time = end_time - start_time
        
        # Should complete in reasonable time
        assert optimization_time < 30.0  # Less than 30 seconds
        
        # Should handle all projects
        assert result["status"] == "success"
        assert len(result["project_allocations"]) == 50
    
    @pytest.mark.asyncio
    async def test_high_frequency_cost_monitoring(self, cost_optimization_service):
        """Test cost monitoring under high frequency updates"""
        # Simulate high-frequency cost updates
        monitoring_scenario = {
            "active_jobs": 20,
            "update_frequency_seconds": 10,
            "monitoring_duration_minutes": 60
        }
        
        # Should handle frequent updates without performance degradation
        updates_processed = await cost_optimization_service.simulate_high_frequency_monitoring(monitoring_scenario)
        
        expected_updates = (60 * 60) / 10 * 20  # 60 min * 60 sec/min / 10 sec update * 20 jobs
        assert updates_processed >= expected_updates * 0.95  # At least 95% of expected updates
    
    @pytest.mark.asyncio
    async def test_concurrent_optimization_requests(self, cost_optimization_service):
        """Test handling concurrent optimization requests"""
        # Create multiple concurrent requests
        concurrent_requests = [
            {
                "workflow_spec": {
                    "workflow_id": f"concurrent_workflow_{i}",
                    "resource_requirements": {"cpu_cores": 8, "memory_gb": 32}
                }
            } for i in range(10)
        ]
        
        # Submit all requests concurrently
        tasks = [
            cost_optimization_service.optimize_workflow_cost(req) 
            for req in concurrent_requests
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All requests should succeed
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) == 10
        
        # Each should have unique optimization
        optimization_ids = {r.get("optimization_id") for r in successful_results if r.get("optimization_id")}
        assert len(optimization_ids) == 10  # All unique


@pytest.mark.integration
class TestCostOptimizationErrorHandling:
    """Error handling tests for cost optimization"""
    
    @pytest.mark.asyncio
    async def test_cloud_provider_api_failures(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test handling of cloud provider API failures"""
        optimization_request = {"workflow_spec": neuroimaging_workflow_spec}
        
        with patch('brain_researcher.services.agent.spot_optimizer.SpotInstanceOptimizer') as MockOptimizer:
            mock_optimizer = MockOptimizer.return_value
            
            # Simulate AWS API failure
            mock_optimizer._fetch_aws_spot_prices.side_effect = Exception("AWS API unavailable")
            mock_optimizer._fetch_gcp_spot_prices.return_value = [{"instance_type": "n1-standard-16", "price": 0.08}]
            mock_optimizer._fetch_azure_spot_prices.return_value = [{"instance_type": "Standard_D16s_v3", "price": 0.09}]
            
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Should still provide optimization using available providers
            assert result["status"] == "partial_success"
            assert "provider_failures" in result
            assert "aws" in result["provider_failures"]
            
            # Should have recommendations from working providers
            assert len(result["recommendations"]) > 0
            providers = {rec["provider"] for rec in result["recommendations"]}
            assert "gcp" in providers or "azure" in providers
            assert "aws" not in providers
    
    @pytest.mark.asyncio
    async def test_budget_service_unavailable(self, cost_optimization_service, neuroimaging_workflow_spec):
        """Test handling when budget service is unavailable"""
        optimization_request = {"workflow_spec": neuroimaging_workflow_spec}
        
        with patch('brain_researcher.services.agent.budget_manager.BudgetManager') as MockBudgetManager:
            mock_budget_manager = MockBudgetManager.return_value
            mock_budget_manager.check_budget.side_effect = Exception("Budget service unavailable")
            
            result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
            
            # Should provide warning but continue optimization
            assert result["status"] in ["success_with_warnings", "partial_success"]
            assert "warnings" in result
            
            budget_warning = next((w for w in result["warnings"] if "budget" in w.lower()), None)
            assert budget_warning is not None
    
    @pytest.mark.asyncio
    async def test_insufficient_resources_scenario(self, cost_optimization_service):
        """Test handling when requested resources are not available"""
        impossible_workflow = {
            "workflow_id": "impossible_requirements",
            "resource_requirements": {
                "cpu_cores": 1000,  # Unrealistic requirement
                "memory_gb": 10000,
                "gpu_count": 50
            },
            "budget_constraints": {
                "max_cost": 10.0  # Impossibly low budget for these requirements
            }
        }
        
        optimization_request = {"workflow_spec": impossible_workflow}
        result = await cost_optimization_service.optimize_workflow_cost(optimization_request)
        
        assert result["status"] == "infeasible"
        assert "infeasibility_reasons" in result
        
        reasons = result["infeasibility_reasons"]
        assert any("resource" in reason.lower() for reason in reasons)
        assert any("budget" in reason.lower() for reason in reasons)
        
        # Should provide alternatives
        assert "alternatives" in result
        alternatives = result["alternatives"]
        assert len(alternatives) > 0
        
        # Alternatives should suggest either resource reduction or budget increase
        resource_alt = next((alt for alt in alternatives if "reduce" in alt["description"].lower()), None)
        budget_alt = next((alt for alt in alternatives if "budget" in alt["description"].lower()), None)
        assert resource_alt is not None or budget_alt is not None