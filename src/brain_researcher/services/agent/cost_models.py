"""
Cost Models for Plan Optimization (AGENT-013)

This module implements cloud pricing models for AWS, GCP, and Azure
to support cost-optimized execution planning.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.agent.planning import ResourceType, WorkflowStep

logger = logging.getLogger(__name__)


class CloudProvider(str, Enum):
    """Supported cloud providers."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    ON_PREMISE = "on_premise"


class InstanceType(str, Enum):
    """Instance type categories."""

    GENERAL_PURPOSE = "general_purpose"
    COMPUTE_OPTIMIZED = "compute_optimized"
    MEMORY_OPTIMIZED = "memory_optimized"
    STORAGE_OPTIMIZED = "storage_optimized"
    GPU_ACCELERATED = "gpu_accelerated"


class PricingModel(str, Enum):
    """Pricing models for cloud resources."""

    ON_DEMAND = "on_demand"
    RESERVED = "reserved"
    SPOT = "spot"
    PREEMPTIBLE = "preemptible"  # GCP equivalent of spot


@dataclass
class InstanceSpec:
    """Specification for a cloud instance."""

    instance_type: InstanceType
    vcpus: int
    memory_gb: float
    storage_gb: float
    gpu_count: int = 0
    network_performance: str = "moderate"

    def __post_init__(self):
        """Validate instance specification."""
        if self.vcpus <= 0 or self.memory_gb <= 0:
            raise ValueError("Instance must have positive CPU and memory")


@dataclass
class PricingInfo:
    """Pricing information for a resource."""

    on_demand_price: float  # $/hour
    reserved_price: Optional[float] = None  # $/hour (1-year term)
    spot_price: Optional[float] = None  # $/hour
    storage_price: float = 0.0  # $/GB/month
    network_price: float = 0.0  # $/GB

    def get_price(self, pricing_model: PricingModel) -> float:
        """Get price for specific pricing model."""
        if pricing_model == PricingModel.ON_DEMAND:
            return self.on_demand_price
        elif pricing_model == PricingModel.RESERVED and self.reserved_price:
            return self.reserved_price
        elif pricing_model == PricingModel.SPOT and self.spot_price:
            return self.spot_price
        elif pricing_model == PricingModel.PREEMPTIBLE and self.spot_price:
            return self.spot_price
        else:
            return self.on_demand_price


class CostModel:
    """
    Base class for cloud cost models.

    Provides pricing information for different instance types and resources
    across cloud providers.
    """

    def __init__(self, provider: CloudProvider, region: str = "us-east-1"):
        """
        Initialize cost model.

        Args:
            provider: Cloud provider
            region: Cloud region for pricing
        """
        self.provider = provider
        self.region = region
        self.instance_catalog: Dict[str, Tuple[InstanceSpec, PricingInfo]] = {}
        self._initialize_catalog()

    def _initialize_catalog(self):
        """Initialize instance catalog with pricing."""
        raise NotImplementedError("Subclasses must implement catalog initialization")

    def get_instance_options(
        self,
        min_cpu: float,
        min_memory: float,
        instance_type: Optional[InstanceType] = None,
        gpu_required: bool = False,
    ) -> List[Tuple[str, InstanceSpec, PricingInfo]]:
        """
        Get suitable instance options for requirements.

        Args:
            min_cpu: Minimum CPU cores required
            min_memory: Minimum memory in GB required
            instance_type: Preferred instance type category
            gpu_required: Whether GPU is required

        Returns:
            List of (instance_name, spec, pricing) tuples
        """
        options = []

        for instance_name, (spec, pricing) in self.instance_catalog.items():
            # Check basic requirements
            if spec.vcpus < min_cpu or spec.memory_gb < min_memory:
                continue

            # Check GPU requirement
            if gpu_required and spec.gpu_count == 0:
                continue

            # Check instance type preference
            if instance_type and spec.instance_type != instance_type:
                continue

            options.append((instance_name, spec, pricing))

        # Sort by cost efficiency (performance/price ratio)
        options.sort(key=lambda x: self._calculate_efficiency(x[1], x[2]))

        return options

    def _calculate_efficiency(self, spec: InstanceSpec, pricing: PricingInfo) -> float:
        """Calculate cost efficiency metric for an instance."""
        # Performance score based on CPU and memory
        performance_score = spec.vcpus + (spec.memory_gb / 4)  # Weight memory lower

        # Use spot pricing if available, otherwise on-demand
        price = pricing.spot_price if pricing.spot_price else pricing.on_demand_price

        return performance_score / max(price, 0.001)  # Avoid division by zero

    def get_storage_cost(self, storage_gb: float, duration_hours: float) -> float:
        """
        Get storage cost.

        Args:
            storage_gb: Storage amount in GB
            duration_hours: Duration in hours

        Returns:
            Total storage cost
        """
        # Convert hours to months for pricing
        duration_months = duration_hours / (24 * 30)
        return storage_gb * self.get_storage_price_per_gb_month() * duration_months

    def get_storage_price_per_gb_month(self) -> float:
        """Get storage price per GB per month."""
        return 0.023  # Default $0.023/GB/month (AWS S3 Standard)

    def get_network_cost(self, data_gb: float) -> float:
        """
        Get network transfer cost.

        Args:
            data_gb: Data transfer in GB

        Returns:
            Network transfer cost
        """
        return data_gb * self.get_network_price_per_gb()

    def get_network_price_per_gb(self) -> float:
        """Get network transfer price per GB."""
        return 0.09  # Default $0.09/GB for data transfer out


class AWSCostModel(CostModel):
    """AWS cost model with EC2 instance pricing."""

    def _initialize_catalog(self):
        """Initialize AWS EC2 instance catalog."""
        # General Purpose instances (t3, m5, m6i)
        self.instance_catalog.update(
            {
                "t3.medium": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 4.0, 20.0),
                    PricingInfo(0.0416, 0.025, 0.0125, 0.10, 0.09),
                ),
                "t3.large": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 8.0, 20.0),
                    PricingInfo(0.0832, 0.050, 0.025, 0.10, 0.09),
                ),
                "m5.large": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 8.0, 50.0),
                    PricingInfo(0.096, 0.058, 0.029, 0.10, 0.09),
                ),
                "m5.xlarge": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 4, 16.0, 50.0),
                    PricingInfo(0.192, 0.115, 0.058, 0.10, 0.09),
                ),
                "m5.2xlarge": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 8, 32.0, 50.0),
                    PricingInfo(0.384, 0.23, 0.115, 0.10, 0.09),
                ),
                "m5.4xlarge": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 16, 64.0, 50.0),
                    PricingInfo(0.768, 0.461, 0.23, 0.10, 0.09),
                ),
            }
        )

        # Compute Optimized instances (c5, c6i)
        self.instance_catalog.update(
            {
                "c5.large": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 2, 4.0, 50.0),
                    PricingInfo(0.085, 0.051, 0.026, 0.10, 0.09),
                ),
                "c5.xlarge": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 4, 8.0, 50.0),
                    PricingInfo(0.17, 0.102, 0.051, 0.10, 0.09),
                ),
                "c5.2xlarge": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 8, 16.0, 50.0),
                    PricingInfo(0.34, 0.204, 0.102, 0.10, 0.09),
                ),
                "c5.4xlarge": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 16, 32.0, 50.0),
                    PricingInfo(0.68, 0.408, 0.204, 0.10, 0.09),
                ),
            }
        )

        # Memory Optimized instances (r5, x1e)
        self.instance_catalog.update(
            {
                "r5.large": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 2, 16.0, 50.0),
                    PricingInfo(0.126, 0.076, 0.038, 0.10, 0.09),
                ),
                "r5.xlarge": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 4, 32.0, 50.0),
                    PricingInfo(0.252, 0.151, 0.076, 0.10, 0.09),
                ),
                "r5.2xlarge": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 8, 64.0, 50.0),
                    PricingInfo(0.504, 0.302, 0.151, 0.10, 0.09),
                ),
                "r5.4xlarge": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 16, 128.0, 50.0),
                    PricingInfo(1.008, 0.605, 0.302, 0.10, 0.09),
                ),
            }
        )

        # GPU instances (p3, g4dn)
        self.instance_catalog.update(
            {
                "g4dn.xlarge": (
                    InstanceSpec(InstanceType.GPU_ACCELERATED, 4, 16.0, 125.0, 1),
                    PricingInfo(0.526, 0.316, 0.158, 0.10, 0.09),
                ),
                "g4dn.2xlarge": (
                    InstanceSpec(InstanceType.GPU_ACCELERATED, 8, 32.0, 225.0, 1),
                    PricingInfo(0.752, 0.451, 0.226, 0.10, 0.09),
                ),
                "p3.2xlarge": (
                    InstanceSpec(InstanceType.GPU_ACCELERATED, 8, 61.0, 100.0, 1),
                    PricingInfo(3.06, 1.836, 0.918, 0.10, 0.09),
                ),
            }
        )

    def get_storage_price_per_gb_month(self) -> float:
        """AWS S3 Standard storage pricing."""
        return 0.023  # $0.023/GB/month

    def get_network_price_per_gb(self) -> float:
        """AWS data transfer out pricing."""
        return 0.09  # $0.09/GB for first 10TB


class GCPCostModel(CostModel):
    """GCP cost model with Compute Engine pricing."""

    def _initialize_catalog(self):
        """Initialize GCP Compute Engine instance catalog."""
        # General Purpose (n1, n2, e2)
        self.instance_catalog.update(
            {
                "e2-medium": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 1, 4.0, 10.0),
                    PricingInfo(0.033, 0.020, 0.010, 0.040, 0.12),
                ),
                "n1-standard-2": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 7.5, 10.0),
                    PricingInfo(0.095, 0.057, 0.029, 0.040, 0.12),
                ),
                "n1-standard-4": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 4, 15.0, 10.0),
                    PricingInfo(0.190, 0.114, 0.057, 0.040, 0.12),
                ),
                "n1-standard-8": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 8, 30.0, 10.0),
                    PricingInfo(0.380, 0.228, 0.114, 0.040, 0.12),
                ),
                "n1-standard-16": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 16, 60.0, 10.0),
                    PricingInfo(0.760, 0.456, 0.228, 0.040, 0.12),
                ),
            }
        )

        # Compute Optimized (c2)
        self.instance_catalog.update(
            {
                "c2-standard-4": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 4, 16.0, 10.0),
                    PricingInfo(0.196, 0.118, 0.059, 0.040, 0.12),
                ),
                "c2-standard-8": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 8, 32.0, 10.0),
                    PricingInfo(0.393, 0.236, 0.118, 0.040, 0.12),
                ),
                "c2-standard-16": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 16, 64.0, 10.0),
                    PricingInfo(0.786, 0.472, 0.236, 0.040, 0.12),
                ),
            }
        )

        # Memory Optimized (n1-highmem, n1-megamem)
        self.instance_catalog.update(
            {
                "n1-highmem-2": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 2, 13.0, 10.0),
                    PricingInfo(0.118, 0.071, 0.035, 0.040, 0.12),
                ),
                "n1-highmem-4": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 4, 26.0, 10.0),
                    PricingInfo(0.237, 0.142, 0.071, 0.040, 0.12),
                ),
                "n1-highmem-8": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 8, 52.0, 10.0),
                    PricingInfo(0.474, 0.284, 0.142, 0.040, 0.12),
                ),
            }
        )

    def get_storage_price_per_gb_month(self) -> float:
        """GCP Cloud Storage Standard pricing."""
        return 0.020  # $0.020/GB/month

    def get_network_price_per_gb(self) -> float:
        """GCP network egress pricing."""
        return 0.12  # $0.12/GB for general network egress


class AzureCostModel(CostModel):
    """Azure cost model with Virtual Machine pricing."""

    def _initialize_catalog(self):
        """Initialize Azure VM instance catalog."""
        # General Purpose (B, D, A series)
        self.instance_catalog.update(
            {
                "Standard_B2s": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 4.0, 8.0),
                    PricingInfo(0.041, 0.025, 0.012, 0.048, 0.087),
                ),
                "Standard_D2s_v3": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 2, 8.0, 16.0),
                    PricingInfo(0.096, 0.058, 0.029, 0.048, 0.087),
                ),
                "Standard_D4s_v3": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 4, 16.0, 32.0),
                    PricingInfo(0.192, 0.115, 0.058, 0.048, 0.087),
                ),
                "Standard_D8s_v3": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 8, 32.0, 64.0),
                    PricingInfo(0.384, 0.230, 0.115, 0.048, 0.087),
                ),
            }
        )

        # Compute Optimized (F series)
        self.instance_catalog.update(
            {
                "Standard_F2s_v2": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 2, 4.0, 16.0),
                    PricingInfo(0.085, 0.051, 0.026, 0.048, 0.087),
                ),
                "Standard_F4s_v2": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 4, 8.0, 32.0),
                    PricingInfo(0.169, 0.101, 0.051, 0.048, 0.087),
                ),
                "Standard_F8s_v2": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 8, 16.0, 64.0),
                    PricingInfo(0.338, 0.203, 0.101, 0.048, 0.087),
                ),
            }
        )

        # Memory Optimized (E series)
        self.instance_catalog.update(
            {
                "Standard_E2s_v3": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 2, 16.0, 32.0),
                    PricingInfo(0.126, 0.076, 0.038, 0.048, 0.087),
                ),
                "Standard_E4s_v3": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 4, 32.0, 64.0),
                    PricingInfo(0.252, 0.151, 0.076, 0.048, 0.087),
                ),
                "Standard_E8s_v3": (
                    InstanceSpec(InstanceType.MEMORY_OPTIMIZED, 8, 64.0, 128.0),
                    PricingInfo(0.504, 0.302, 0.151, 0.048, 0.087),
                ),
            }
        )

    def get_storage_price_per_gb_month(self) -> float:
        """Azure Blob Storage Hot tier pricing."""
        return 0.0184  # $0.0184/GB/month

    def get_network_price_per_gb(self) -> float:
        """Azure bandwidth pricing."""
        return 0.087  # $0.087/GB for zone 1


class OnPremiseCostModel(CostModel):
    """On-premise cost model for comparison."""

    def _initialize_catalog(self):
        """Initialize on-premise instance catalog."""
        # Simplified on-premise instances
        self.instance_catalog.update(
            {
                "workstation_small": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 4, 16.0, 500.0),
                    PricingInfo(
                        0.05, 0.05, 0.05, 0.001, 0.0
                    ),  # Low cost, no spot pricing
                ),
                "workstation_medium": (
                    InstanceSpec(InstanceType.GENERAL_PURPOSE, 8, 32.0, 1000.0),
                    PricingInfo(0.10, 0.10, 0.10, 0.001, 0.0),
                ),
                "server_large": (
                    InstanceSpec(InstanceType.COMPUTE_OPTIMIZED, 16, 64.0, 2000.0),
                    PricingInfo(0.20, 0.20, 0.20, 0.001, 0.0),
                ),
                "gpu_workstation": (
                    InstanceSpec(InstanceType.GPU_ACCELERATED, 8, 32.0, 1000.0, 1),
                    PricingInfo(0.50, 0.50, 0.50, 0.001, 0.0),
                ),
            }
        )

    def get_storage_price_per_gb_month(self) -> float:
        """On-premise storage cost (amortized)."""
        return 0.005  # $0.005/GB/month (very low)

    def get_network_price_per_gb(self) -> float:
        """On-premise network cost (essentially free)."""
        return 0.0


class ResourceCostCalculator:
    """
    Calculator for total resource costs using cost models.
    """

    def __init__(self, cost_model: CostModel):
        """
        Initialize cost calculator.

        Args:
            cost_model: Cost model to use for calculations
        """
        self.cost_model = cost_model
        self.spot_interruption_rate = 0.1  # 10% interruption rate for spot instances

    def calculate_step_cost(
        self, step: WorkflowStep, pricing_model: PricingModel = PricingModel.ON_DEMAND
    ) -> Dict[str, float]:
        """
        Calculate cost for a single workflow step.

        Args:
            step: Workflow step
            pricing_model: Pricing model to use

        Returns:
            Dictionary of cost components
        """
        # Extract resource requirements
        cpu_req = step.resource_requirements.get("cpu", 1.0)
        memory_req = step.resource_requirements.get("memory", 4.0)
        storage_req = step.resource_requirements.get("storage", 10.0)
        gpu_req = step.resource_requirements.get("gpu", 0.0) > 0

        # Get preferred instance type from tool args
        preferred_type_str = step.tool_args.get(
            "preferred_instance_type", "general_purpose"
        )
        try:
            preferred_type = InstanceType(preferred_type_str)
        except ValueError:
            preferred_type = InstanceType.GENERAL_PURPOSE

        # Check if spot instances are enabled
        use_spot = step.tool_args.get("use_spot_instances", False)
        if use_spot:
            pricing_model = PricingModel.SPOT

        # Find suitable instances
        instance_options = self.cost_model.get_instance_options(
            min_cpu=cpu_req,
            min_memory=memory_req,
            instance_type=preferred_type,
            gpu_required=gpu_req,
        )

        if not instance_options:
            # Fallback to any suitable instance
            instance_options = self.cost_model.get_instance_options(
                min_cpu=cpu_req, min_memory=memory_req, gpu_required=gpu_req
            )

        if not instance_options:
            logger.warning(f"No suitable instances found for step {step.step_id}")
            return {"compute": 0.0, "storage": 0.0, "network": 0.0, "total": 0.0}

        # Use most cost-efficient instance
        instance_name, instance_spec, pricing_info = instance_options[0]

        # Calculate compute cost
        duration_hours = step.estimated_time_seconds / 3600
        compute_cost = pricing_info.get_price(pricing_model) * duration_hours

        # Apply spot interruption penalty if using spot instances
        if pricing_model == PricingModel.SPOT:
            # Account for potential interruptions requiring restarts
            interruption_penalty = compute_cost * self.spot_interruption_rate
            compute_cost += interruption_penalty

        # Calculate storage cost
        storage_cost = self.cost_model.get_storage_cost(storage_req, duration_hours)

        # Calculate network cost (estimated data transfer)
        estimated_data_transfer = max(
            1.0, storage_req * 0.1
        )  # 10% of storage as network transfer
        network_cost = self.cost_model.get_network_cost(estimated_data_transfer)

        total_cost = compute_cost + storage_cost + network_cost

        return {
            "compute": compute_cost,
            "storage": storage_cost,
            "network": network_cost,
            "total": total_cost,
            "instance_used": instance_name,
            "pricing_model": pricing_model.value,
        }

    def calculate_total_cost(
        self, steps: List[WorkflowStep], consider_parallelism: bool = True
    ) -> float:
        """
        Calculate total cost for a list of workflow steps.

        Args:
            steps: List of workflow steps
            consider_parallelism: Whether to account for parallel execution

        Returns:
            Total estimated cost
        """
        total_cost = 0.0

        if consider_parallelism:
            # Group steps by dependencies to estimate parallel execution cost
            total_cost = self._calculate_parallel_cost(steps)
        else:
            # Sequential execution cost
            for step in steps:
                step_costs = self.calculate_step_cost(step)
                total_cost += step_costs["total"]

        return total_cost

    def _calculate_parallel_cost(self, steps: List[WorkflowStep]) -> float:
        """Calculate cost considering parallel execution."""
        from brain_researcher.services.agent.dependency_resolver import (
            DependencyResolver,
            Task,
        )

        resolver = DependencyResolver()

        # Convert steps to tasks for batch analysis
        tasks = []
        for step in steps:
            task = Task(
                task_id=step.step_id,
                name=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                dependencies=step.dependencies,
                estimated_duration=step.estimated_time_seconds,
            )
            tasks.append(task)

        try:
            batches = resolver.create_execution_batches(tasks)

            total_cost = 0.0
            for batch in batches:
                # Calculate cost for each batch (parallel execution)
                batch_cost = 0.0
                for task in batch.tasks:
                    # Find corresponding step
                    step = next(s for s in steps if s.step_id == task.task_id)
                    step_costs = self.calculate_step_cost(step)
                    batch_cost += step_costs["total"]

                total_cost += batch_cost

            return total_cost

        except Exception as e:
            logger.warning(
                f"Failed to calculate parallel cost: {e}, falling back to sequential"
            )
            # Fallback to sequential calculation
            return sum(self.calculate_step_cost(step)["total"] for step in steps)

    def estimate_cost_savings(
        self, steps: List[WorkflowStep], optimization_strategies: List[str]
    ) -> Dict[str, float]:
        """
        Estimate cost savings from various optimization strategies.

        Args:
            steps: Workflow steps
            optimization_strategies: List of strategies to evaluate

        Returns:
            Dictionary of strategy -> estimated savings
        """
        baseline_cost = self.calculate_total_cost(steps)
        savings = {}

        for strategy in optimization_strategies:
            if strategy == "spot_instances":
                # Enable spot instances for eligible steps
                spot_cost = 0.0
                for step in steps:
                    if step.tool_name.lower() not in [
                        "preprocessing",
                        "critical_analysis",
                    ]:
                        step_copy = WorkflowStep(**step.__dict__)
                        step_copy.tool_args["use_spot_instances"] = True
                        step_costs = self.calculate_step_cost(
                            step_copy, PricingModel.SPOT
                        )
                        spot_cost += step_costs["total"]
                    else:
                        step_costs = self.calculate_step_cost(step)
                        spot_cost += step_costs["total"]

                savings[strategy] = baseline_cost - spot_cost

            elif strategy == "reserved_instances":
                # Use reserved pricing
                reserved_cost = 0.0
                for step in steps:
                    step_costs = self.calculate_step_cost(step, PricingModel.RESERVED)
                    reserved_cost += step_costs["total"]

                savings[strategy] = baseline_cost - reserved_cost

            elif strategy == "right_sizing":
                # Optimize instance sizes (assume 20% savings)
                savings[strategy] = baseline_cost * 0.20

            elif strategy == "parallelization":
                # Compare parallel vs sequential costs
                sequential_cost = self.calculate_total_cost(
                    steps, consider_parallelism=False
                )
                parallel_cost = self.calculate_total_cost(
                    steps, consider_parallelism=True
                )
                savings[strategy] = max(0, sequential_cost - parallel_cost)

        return savings


# Factory functions
def create_cost_model(provider: CloudProvider, region: str = "us-east-1") -> CostModel:
    """
    Create a cost model for the specified provider.

    Args:
        provider: Cloud provider
        region: Cloud region

    Returns:
        Cost model instance
    """
    if provider == CloudProvider.AWS:
        return AWSCostModel(provider, region)
    elif provider == CloudProvider.GCP:
        return GCPCostModel(provider, region)
    elif provider == CloudProvider.AZURE:
        return AzureCostModel(provider, region)
    elif provider == CloudProvider.ON_PREMISE:
        return OnPremiseCostModel(provider, region)
    else:
        raise ValueError(f"Unsupported cloud provider: {provider}")


def create_cost_calculator(
    provider: CloudProvider = CloudProvider.AWS, region: str = "us-east-1"
) -> ResourceCostCalculator:
    """
    Create a resource cost calculator.

    Args:
        provider: Cloud provider
        region: Cloud region

    Returns:
        Resource cost calculator instance
    """
    cost_model = create_cost_model(provider, region)
    return ResourceCostCalculator(cost_model)
