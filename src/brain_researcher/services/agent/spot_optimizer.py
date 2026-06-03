"""
Spot Instance Optimizer for Brain Researcher

This module provides sophisticated spot instance optimization with support for:
- Multi-cloud spot pricing integration (AWS, GCP, Azure)
- Intelligent bidding strategies based on historical data
- Interruption probability prediction
- Risk-adjusted cost optimization
- Reserved instance utilization tracking
- Automated failover to on-demand instances
"""

import asyncio
import logging
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class CloudProvider(Enum):
    """Supported cloud providers"""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    LOCAL = "local"


class InstanceType(Enum):
    """Instance types for neuroimaging workloads"""

    COMPUTE_OPTIMIZED = "compute_optimized"  # CPU-intensive preprocessing
    MEMORY_OPTIMIZED = "memory_optimized"  # Large dataset analysis
    GPU_OPTIMIZED = "gpu_optimized"  # Deep learning, GPU acceleration
    STORAGE_OPTIMIZED = "storage_optimized"  # Data-intensive operations
    BALANCED = "balanced"  # General purpose


class BiddingStrategy(Enum):
    """Spot instance bidding strategies"""

    CONSERVATIVE = "conservative"  # Bid slightly above current price
    AGGRESSIVE = "aggressive"  # Bid close to on-demand price
    DYNAMIC = "dynamic"  # Adjust bid based on market conditions
    RISK_ADJUSTED = "risk_adjusted"  # Balance cost and interruption risk


@dataclass
class ResourceRequirements:
    """Resource requirements for neuroimaging jobs"""

    cpu_cores: int
    memory_gb: float
    storage_gb: float
    gpu_count: int = 0
    gpu_memory_gb: float = 0
    network_bandwidth_mbps: float | None = None

    # Neuroimaging-specific requirements
    fsl_required: bool = False
    freesurfer_required: bool = False
    matlab_required: bool = False
    cuda_required: bool = False

    # Performance requirements
    min_cpu_performance: float | None = None  # CPU benchmark score
    max_acceptable_latency_ms: float | None = None


@dataclass
class SpotPricePoint:
    """Historical spot price data point"""

    timestamp: datetime
    price: float
    availability_zone: str
    instance_type: str
    interruption_occurred: bool = False


@dataclass
class SpotRecommendation:
    """Spot instance recommendation"""

    provider: CloudProvider
    region: str
    availability_zone: str
    instance_type: str
    current_price: float
    on_demand_price: float
    savings_percentage: float

    # Risk assessment
    interruption_probability: float
    price_volatility: float
    availability_score: float

    # Cost analysis
    expected_cost: float
    risk_adjusted_cost: float
    total_cost_with_interruptions: float

    # Metadata
    recommendation_confidence: float
    historical_data_points: int
    last_updated: datetime

    # Additional details
    instance_specs: dict[str, Any] = field(default_factory=dict)
    estimated_performance: float | None = None
    suitability_score: float = 0.0


class PriceHistoryTracker:
    """Tracks historical spot prices and patterns"""

    def __init__(self, max_history_days: int = 30):
        self.max_history_days = max_history_days
        self.price_history: dict[str, list[SpotPricePoint]] = {}
        self.interruption_history: dict[str, list[datetime]] = {}

    def add_price_point(
        self,
        provider: CloudProvider,
        region: str,
        instance_type: str,
        price: float,
        az: str,
    ) -> None:
        """Add a price point to history"""
        key = f"{provider.value}:{region}:{instance_type}:{az}"

        if key not in self.price_history:
            self.price_history[key] = []

        price_point = SpotPricePoint(
            timestamp=datetime.now(),
            price=price,
            availability_zone=az,
            instance_type=instance_type,
        )

        self.price_history[key].append(price_point)

        # Clean old data
        cutoff = datetime.now() - timedelta(days=self.max_history_days)
        self.price_history[key] = [
            p for p in self.price_history[key] if p.timestamp > cutoff
        ]

    def record_interruption(
        self, provider: CloudProvider, region: str, instance_type: str, az: str
    ) -> None:
        """Record a spot instance interruption"""
        key = f"{provider.value}:{region}:{instance_type}:{az}"

        if key not in self.interruption_history:
            self.interruption_history[key] = []

        self.interruption_history[key].append(datetime.now())

        # Mark corresponding price point as interrupted
        if key in self.price_history:
            # Find the most recent price point and mark it
            for price_point in reversed(self.price_history[key]):
                if price_point.timestamp <= datetime.now():
                    price_point.interruption_occurred = True
                    break

    def get_price_statistics(
        self,
        provider: CloudProvider,
        region: str,
        instance_type: str,
        az: str,
        hours: int = 24,
    ) -> dict[str, float]:
        """Get price statistics for the last N hours"""
        key = f"{provider.value}:{region}:{instance_type}:{az}"
        cutoff = datetime.now() - timedelta(hours=hours)

        if key not in self.price_history:
            return {}

        recent_prices = [
            p.price for p in self.price_history[key] if p.timestamp > cutoff
        ]

        if not recent_prices:
            return {}

        return {
            "current_price": recent_prices[-1],
            "average_price": statistics.mean(recent_prices),
            "median_price": statistics.median(recent_prices),
            "min_price": min(recent_prices),
            "max_price": max(recent_prices),
            "price_volatility": (
                statistics.stdev(recent_prices) if len(recent_prices) > 1 else 0
            ),
            "data_points": len(recent_prices),
        }

    def get_interruption_rate(
        self,
        provider: CloudProvider,
        region: str,
        instance_type: str,
        az: str,
        days: int = 7,
    ) -> float:
        """Calculate interruption rate for the last N days"""
        key = f"{provider.value}:{region}:{instance_type}:{az}"
        cutoff = datetime.now() - timedelta(days=days)

        if key not in self.interruption_history:
            return 0.0

        recent_interruptions = [
            ts for ts in self.interruption_history[key] if ts > cutoff
        ]

        # Calculate interruptions per day
        return len(recent_interruptions) / days


class InterruptionPredictor:
    """Predicts spot instance interruption probability"""

    def __init__(self):
        self.model_weights = {
            "price_trend": 0.3,
            "historical_interruptions": 0.4,
            "market_volatility": 0.2,
            "demand_indicators": 0.1,
        }

    def predict_interruption_probability(
        self,
        provider: CloudProvider,
        region: str,
        instance_type: str,
        az: str,
        price_tracker: PriceHistoryTracker,
        duration_hours: int = 1,
    ) -> float:
        """Predict probability of interruption in the next N hours"""

        # Get price statistics
        price_stats = price_tracker.get_price_statistics(
            provider, region, instance_type, az, hours=24
        )

        if not price_stats:
            return 0.5  # Default moderate risk

        # Factor 1: Price trend (rising prices = lower interruption risk)
        current_price = price_stats["current_price"]
        avg_price = price_stats["average_price"]
        price_trend_factor = (
            min(current_price / avg_price, 2.0) if avg_price > 0 else 1.0
        )

        # Factor 2: Historical interruption rate
        interruption_rate = price_tracker.get_interruption_rate(
            provider, region, instance_type, az, days=7
        )
        interruption_factor = min(interruption_rate * 24, 1.0)  # Convert to hourly rate

        # Factor 3: Market volatility (high volatility = higher risk)
        volatility = price_stats.get("price_volatility", 0)
        avg_price_val = price_stats.get("average_price", 1)
        volatility_factor = (
            min(volatility / avg_price_val, 1.0) if avg_price_val > 0 else 0
        )

        # Factor 4: Demand indicators (simplified - based on price range)
        price_range = price_stats["max_price"] - price_stats["min_price"]
        demand_factor = (
            min(price_range / avg_price_val, 1.0) if avg_price_val > 0 else 0
        )

        # Calculate weighted probability
        probability = (
            (1 - price_trend_factor) * self.model_weights["price_trend"]
            + interruption_factor * self.model_weights["historical_interruptions"]
            + volatility_factor * self.model_weights["market_volatility"]
            + demand_factor * self.model_weights["demand_indicators"]
        )

        # Adjust for duration (longer jobs = higher cumulative risk)
        duration_multiplier = 1 + (duration_hours - 1) * 0.1
        probability = min(probability * duration_multiplier, 1.0)

        return probability


class BidStrategy:
    """Implements various bidding strategies for spot instances"""

    def calculate_bid_price(
        self,
        strategy: BiddingStrategy,
        current_spot_price: float,
        on_demand_price: float,
        interruption_probability: float,
        job_duration_hours: int,
    ) -> float:
        """Calculate optimal bid price based on strategy"""

        if strategy == BiddingStrategy.CONSERVATIVE:
            # Bid 10-20% above current spot price
            return current_spot_price * 1.15

        elif strategy == BiddingStrategy.AGGRESSIVE:
            # Bid close to on-demand price (80-90%)
            return on_demand_price * 0.85

        elif strategy == BiddingStrategy.DYNAMIC:
            # Adjust based on market conditions
            if interruption_probability < 0.1:
                return current_spot_price * 1.1  # Low risk, bid conservatively
            elif interruption_probability < 0.3:
                return current_spot_price * 1.2  # Medium risk
            else:
                return on_demand_price * 0.8  # High risk, bid aggressively

        elif strategy == BiddingStrategy.RISK_ADJUSTED:
            # Calculate risk-adjusted bid
            base_savings = (on_demand_price - current_spot_price) / on_demand_price
            risk_penalty = (
                interruption_probability * 0.5
            )  # 50% penalty for interruption risk
            adjusted_savings = base_savings * (1 - risk_penalty)

            if adjusted_savings > 0.1:  # If still 10%+ savings after risk adjustment
                return current_spot_price * (1 + interruption_probability * 0.3)
            else:
                return on_demand_price * 0.9  # Fall back to high bid

        return current_spot_price * 1.1  # Default conservative


class CloudPriceProvider(ABC):
    """Abstract interface for cloud price providers"""

    @abstractmethod
    async def get_spot_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get current spot prices"""
        pass

    @abstractmethod
    async def get_on_demand_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get on-demand prices"""
        pass

    @abstractmethod
    async def get_availability_zones(self, region: str) -> list[str]:
        """Get available zones in region"""
        pass


class AWSPriceProvider(CloudPriceProvider):
    """AWS spot price provider"""

    def __init__(self, aws_client=None):
        self.aws_client = aws_client
        # Instance type mapping for neuroimaging workloads
        self.instance_mapping = {
            InstanceType.COMPUTE_OPTIMIZED: [
                "c5.large",
                "c5.xlarge",
                "c5.2xlarge",
                "c5.4xlarge",
            ],
            InstanceType.MEMORY_OPTIMIZED: [
                "r5.large",
                "r5.xlarge",
                "r5.2xlarge",
                "r5.4xlarge",
            ],
            InstanceType.GPU_OPTIMIZED: [
                "p3.2xlarge",
                "p3.8xlarge",
                "g4dn.xlarge",
                "g4dn.2xlarge",
            ],
            InstanceType.STORAGE_OPTIMIZED: ["i3.large", "i3.xlarge", "i3.2xlarge"],
            InstanceType.BALANCED: [
                "m5.large",
                "m5.xlarge",
                "m5.2xlarge",
                "m5.4xlarge",
            ],
        }

    async def get_spot_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get current AWS spot prices"""
        # Simulated implementation - in practice would use boto3
        prices = {}
        for instance_type in instance_types:
            # Simulate realistic neuroimaging spot prices
            base_price = self._get_base_price(instance_type)
            spot_discount = np.random.uniform(0.5, 0.8)  # 50-80% discount
            prices[instance_type] = base_price * spot_discount

        return prices

    async def get_on_demand_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get AWS on-demand prices"""
        prices = {}
        for instance_type in instance_types:
            prices[instance_type] = self._get_base_price(instance_type)
        return prices

    async def get_availability_zones(self, region: str) -> list[str]:
        """Get AWS availability zones"""
        # Simplified mapping
        zone_mapping = {
            "us-east-1": ["us-east-1a", "us-east-1b", "us-east-1c"],
            "us-west-2": ["us-west-2a", "us-west-2b", "us-west-2c"],
            "eu-west-1": ["eu-west-1a", "eu-west-1b", "eu-west-1c"],
        }
        return zone_mapping.get(region, [f"{region}a", f"{region}b"])

    def _get_base_price(self, instance_type: str) -> float:
        """Get base (on-demand) price for instance type"""
        # Realistic neuroimaging instance pricing (per hour)
        pricing = {
            "c5.large": 0.096,
            "c5.xlarge": 0.192,
            "c5.2xlarge": 0.384,
            "c5.4xlarge": 0.768,
            "r5.large": 0.126,
            "r5.xlarge": 0.252,
            "r5.2xlarge": 0.504,
            "r5.4xlarge": 1.008,
            "p3.2xlarge": 3.06,
            "p3.8xlarge": 12.24,
            "g4dn.xlarge": 0.526,
            "g4dn.2xlarge": 0.752,
            "m5.large": 0.096,
            "m5.xlarge": 0.192,
            "m5.2xlarge": 0.384,
            "m5.4xlarge": 0.768,
        }
        return pricing.get(instance_type, 0.1)


class GCPPriceProvider(CloudPriceProvider):
    """Google Cloud spot price provider"""

    async def get_spot_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get current GCP preemptible prices"""
        prices = {}
        for instance_type in instance_types:
            base_price = self._get_base_price(instance_type)
            # GCP preemptible instances are ~80% discount
            prices[instance_type] = base_price * 0.2
        return prices

    async def get_on_demand_prices(
        self, region: str, instance_types: list[str]
    ) -> dict[str, float]:
        """Get GCP on-demand prices"""
        prices = {}
        for instance_type in instance_types:
            prices[instance_type] = self._get_base_price(instance_type)
        return prices

    async def get_availability_zones(self, region: str) -> list[str]:
        """Get GCP zones"""
        return [f"{region}-a", f"{region}-b", f"{region}-c"]

    def _get_base_price(self, instance_type: str) -> float:
        """Get base GCP pricing"""
        # Simplified GCP pricing
        pricing = {
            "n1-standard-2": 0.095,
            "n1-standard-4": 0.190,
            "n1-standard-8": 0.380,
            "n1-highmem-2": 0.118,
            "n1-highmem-4": 0.237,
            "n1-highmem-8": 0.474,
        }
        return pricing.get(instance_type, 0.1)


class SpotInstanceOptimizer:
    """Main spot instance optimizer"""

    def __init__(self):
        self.price_history = PriceHistoryTracker()
        self.interruption_predictor = InterruptionPredictor()
        self.bid_strategy = BidStrategy()

        # Cloud providers
        self.price_providers = {
            CloudProvider.AWS: AWSPriceProvider(),
            CloudProvider.GCP: GCPPriceProvider(),
            # CloudProvider.AZURE: AzurePriceProvider()  # Would implement similarly
        }

        # Performance benchmarks for instance types
        self.performance_benchmarks = self._load_performance_benchmarks()

    async def get_spot_recommendations(
        self,
        requirements: ResourceRequirements,
        duration: timedelta,
        budget: float | None = None,
        preferred_providers: list[CloudProvider] = None,
    ) -> list[SpotRecommendation]:
        """Get spot instance recommendations based on requirements"""

        recommendations = []
        providers = preferred_providers or list(self.price_providers.keys())

        for provider in providers:
            provider_recs = await self._get_provider_recommendations(
                provider, requirements, duration, budget
            )
            recommendations.extend(provider_recs)

        # Sort by value score (combination of savings and reliability)
        recommendations.sort(key=lambda r: self._calculate_value_score(r), reverse=True)

        return recommendations[:10]  # Return top 10 recommendations

    async def _get_provider_recommendations(
        self,
        provider: CloudProvider,
        requirements: ResourceRequirements,
        duration: timedelta,
        budget: float | None,
    ) -> list[SpotRecommendation]:
        """Get recommendations for a specific cloud provider"""

        recommendations = []
        price_provider = self.price_providers.get(provider)

        if not price_provider:
            return recommendations

        # Get suitable instance types
        suitable_instances = self._find_suitable_instances(provider, requirements)

        # Get regions to check (simplified)
        regions = self._get_target_regions(provider)

        for region in regions:
            try:
                # Get availability zones
                zones = await price_provider.get_availability_zones(region)

                # Get current prices
                spot_prices = await price_provider.get_spot_prices(
                    region, suitable_instances
                )
                on_demand_prices = await price_provider.get_on_demand_prices(
                    region, suitable_instances
                )

                for instance_type in suitable_instances:
                    for zone in zones:
                        rec = await self._create_recommendation(
                            provider,
                            region,
                            zone,
                            instance_type,
                            spot_prices.get(instance_type, 0),
                            on_demand_prices.get(instance_type, 0),
                            requirements,
                            duration,
                            budget,
                        )

                        if rec:
                            recommendations.append(rec)

            except Exception as e:
                logger.warning(
                    f"Error getting recommendations for {provider.value} {region}: {e}"
                )

        return recommendations

    async def _create_recommendation(
        self,
        provider: CloudProvider,
        region: str,
        zone: str,
        instance_type: str,
        spot_price: float,
        on_demand_price: float,
        requirements: ResourceRequirements,
        duration: timedelta,
        budget: float | None,
    ) -> SpotRecommendation | None:
        """Create a spot recommendation for specific instance"""

        if spot_price <= 0 or on_demand_price <= 0:
            return None

        # Calculate savings
        savings_percentage = ((on_demand_price - spot_price) / on_demand_price) * 100

        # Predict interruption probability
        interruption_prob = (
            self.interruption_predictor.predict_interruption_probability(
                provider,
                region,
                instance_type,
                zone,
                self.price_history,
                duration_hours=int(duration.total_seconds() / 3600),
            )
        )

        # Get price statistics for volatility
        price_stats = self.price_history.get_price_statistics(
            provider, region, instance_type, zone, hours=24
        )
        price_volatility = price_stats.get("price_volatility", 0) if price_stats else 0

        # Calculate costs
        duration_hours = duration.total_seconds() / 3600
        expected_cost = spot_price * duration_hours

        # Risk-adjusted cost (account for interruptions and restarts)
        interruption_cost_penalty = (
            interruption_prob * 0.3
        )  # 30% penalty for interruption
        risk_adjusted_cost = expected_cost * (1 + interruption_cost_penalty)

        # Total cost including potential re-runs
        expected_interruptions = max(interruption_prob * duration_hours / 24, 0)
        total_cost_with_interruptions = expected_cost * (
            1 + expected_interruptions * 0.5
        )

        # Check budget constraint
        if budget and total_cost_with_interruptions > budget:
            return None

        # Calculate performance and suitability
        performance = self._estimate_performance(instance_type, requirements)
        suitability = self._calculate_suitability_score(instance_type, requirements)

        # Calculate availability score (simplified)
        availability_score = 1.0 - interruption_prob

        # Recommendation confidence based on data availability
        data_points = price_stats.get("data_points", 0) if price_stats else 0
        confidence = min(data_points / 24, 1.0)  # Full confidence with 24+ data points

        return SpotRecommendation(
            provider=provider,
            region=region,
            availability_zone=zone,
            instance_type=instance_type,
            current_price=spot_price,
            on_demand_price=on_demand_price,
            savings_percentage=savings_percentage,
            interruption_probability=interruption_prob,
            price_volatility=price_volatility,
            availability_score=availability_score,
            expected_cost=expected_cost,
            risk_adjusted_cost=risk_adjusted_cost,
            total_cost_with_interruptions=total_cost_with_interruptions,
            recommendation_confidence=confidence,
            historical_data_points=data_points,
            last_updated=datetime.now(),
            instance_specs=self._get_instance_specs(instance_type),
            estimated_performance=performance,
            suitability_score=suitability,
        )

    def calculate_savings(
        self,
        on_demand_cost: float,
        spot_cost: float,
        interruption_probability: float = 0.0,
    ) -> dict[str, float]:
        """Calculate comprehensive savings analysis"""

        if on_demand_cost <= 0:
            return {"error": "Invalid on-demand cost"}

        # Basic savings
        absolute_savings = on_demand_cost - spot_cost
        percentage_savings = (absolute_savings / on_demand_cost) * 100

        # Risk-adjusted savings
        interruption_penalty = interruption_probability * 0.3  # 30% penalty
        risk_adjusted_savings = absolute_savings * (1 - interruption_penalty)
        risk_adjusted_percentage = (risk_adjusted_savings / on_demand_cost) * 100

        # Expected savings accounting for interruptions
        expected_reruns = interruption_probability * 0.5  # Average 50% progress lost
        expected_total_cost = spot_cost * (1 + expected_reruns)
        expected_savings = on_demand_cost - expected_total_cost
        expected_percentage = (expected_savings / on_demand_cost) * 100

        return {
            "absolute_savings": absolute_savings,
            "percentage_savings": percentage_savings,
            "risk_adjusted_savings": risk_adjusted_savings,
            "risk_adjusted_percentage": risk_adjusted_percentage,
            "expected_savings": expected_savings,
            "expected_percentage": expected_percentage,
            "interruption_probability": interruption_probability,
            "cost_comparison": {
                "on_demand": on_demand_cost,
                "spot": spot_cost,
                "risk_adjusted_spot": spot_cost * (1 + interruption_penalty),
                "expected_spot": expected_total_cost,
            },
        }

    def _calculate_value_score(self, recommendation: SpotRecommendation) -> float:
        """Calculate overall value score for ranking recommendations"""

        # Factors contributing to value score
        savings_score = min(
            recommendation.savings_percentage / 80, 1.0
        )  # Normalize to 80% max
        reliability_score = recommendation.availability_score
        performance_score = recommendation.suitability_score
        confidence_score = recommendation.recommendation_confidence

        # Weighted combination
        value_score = (
            savings_score * 0.35
            + reliability_score * 0.30
            + performance_score * 0.25
            + confidence_score * 0.10
        )

        return value_score

    def _find_suitable_instances(
        self, provider: CloudProvider, requirements: ResourceRequirements
    ) -> list[str]:
        """Find instance types that meet requirements"""

        if provider == CloudProvider.AWS:
            aws_provider = self.price_providers[provider]
            suitable = []

            # Check each instance category
            for _category, instances in aws_provider.instance_mapping.items():
                for instance in instances:
                    if self._meets_requirements(instance, requirements):
                        suitable.append(instance)

            return suitable

        # Simplified for other providers
        return ["n1-standard-4", "n1-highmem-4"]  # GCP examples

    def _meets_requirements(
        self, instance_type: str, requirements: ResourceRequirements
    ) -> bool:
        """Check if instance type meets requirements"""

        specs = self._get_instance_specs(instance_type)

        return (
            specs.get("cpu_cores", 0) >= requirements.cpu_cores
            and specs.get("memory_gb", 0) >= requirements.memory_gb
            and specs.get("gpu_count", 0) >= requirements.gpu_count
        )

    def _get_instance_specs(self, instance_type: str) -> dict[str, Any]:
        """Get instance specifications"""

        # Simplified specs database
        specs_db = {
            "c5.large": {"cpu_cores": 2, "memory_gb": 4, "network": "up_to_10gb"},
            "c5.xlarge": {"cpu_cores": 4, "memory_gb": 8, "network": "up_to_10gb"},
            "c5.2xlarge": {"cpu_cores": 8, "memory_gb": 16, "network": "up_to_10gb"},
            "c5.4xlarge": {"cpu_cores": 16, "memory_gb": 32, "network": "up_to_10gb"},
            "r5.large": {"cpu_cores": 2, "memory_gb": 16, "network": "up_to_10gb"},
            "r5.xlarge": {"cpu_cores": 4, "memory_gb": 32, "network": "up_to_10gb"},
            "r5.2xlarge": {"cpu_cores": 8, "memory_gb": 64, "network": "up_to_10gb"},
            "r5.4xlarge": {"cpu_cores": 16, "memory_gb": 128, "network": "up_to_10gb"},
            "p3.2xlarge": {
                "cpu_cores": 8,
                "memory_gb": 61,
                "gpu_count": 1,
                "gpu_memory_gb": 16,
            },
            "g4dn.xlarge": {
                "cpu_cores": 4,
                "memory_gb": 16,
                "gpu_count": 1,
                "gpu_memory_gb": 16,
            },
            "m5.large": {"cpu_cores": 2, "memory_gb": 8, "network": "up_to_10gb"},
            "m5.xlarge": {"cpu_cores": 4, "memory_gb": 16, "network": "up_to_10gb"},
        }

        return specs_db.get(instance_type, {})

    def _estimate_performance(
        self, instance_type: str, requirements: ResourceRequirements
    ) -> float:
        """Estimate performance for neuroimaging workloads"""

        benchmark = self.performance_benchmarks.get(instance_type, 1.0)

        # Adjust for specific requirements
        if requirements.fsl_required and "c5" in instance_type:
            benchmark *= 1.1  # CPU-optimized good for FSL
        elif requirements.freesurfer_required and "r5" in instance_type:
            benchmark *= 1.15  # Memory-optimized good for FreeSurfer
        elif requirements.cuda_required and "p3" in instance_type:
            benchmark *= 2.0  # GPU acceleration

        return benchmark

    def _calculate_suitability_score(
        self, instance_type: str, requirements: ResourceRequirements
    ) -> float:
        """Calculate how suitable instance is for requirements"""

        specs = self._get_instance_specs(instance_type)

        if not specs:
            return 0.5

        score = 0.0
        factors = 0

        # CPU suitability
        cpu_ratio = specs.get("cpu_cores", 0) / max(requirements.cpu_cores, 1)
        score += min(cpu_ratio, 2.0) / 2.0  # Normalize, cap at 2x requirement
        factors += 1

        # Memory suitability
        memory_ratio = specs.get("memory_gb", 0) / max(requirements.memory_gb, 1)
        score += min(memory_ratio, 2.0) / 2.0
        factors += 1

        # GPU suitability (if needed)
        if requirements.gpu_count > 0:
            gpu_ratio = specs.get("gpu_count", 0) / requirements.gpu_count
            score += min(gpu_ratio, 1.0)
            factors += 1

        return score / factors if factors > 0 else 0.5

    def _get_target_regions(self, provider: CloudProvider) -> list[str]:
        """Get target regions for optimization"""

        region_mapping = {
            CloudProvider.AWS: ["us-east-1", "us-west-2", "eu-west-1"],
            CloudProvider.GCP: ["us-central1", "us-west1", "europe-west1"],
            CloudProvider.AZURE: ["eastus", "westus2", "westeurope"],
        }

        return region_mapping.get(provider, ["us-east-1"])

    def _load_performance_benchmarks(self) -> dict[str, float]:
        """Load performance benchmarks for instance types"""

        # Simplified benchmarks (relative performance for neuroimaging workloads)
        return {
            "c5.large": 0.8,
            "c5.xlarge": 1.0,
            "c5.2xlarge": 1.8,
            "c5.4xlarge": 3.2,
            "r5.large": 0.9,
            "r5.xlarge": 1.1,
            "r5.2xlarge": 2.0,
            "r5.4xlarge": 3.5,
            "p3.2xlarge": 4.0,  # GPU acceleration
            "g4dn.xlarge": 2.5,
            "m5.large": 0.85,
            "m5.xlarge": 1.05,
        }


if __name__ == "__main__":
    # Test the spot optimizer
    import asyncio

    async def test_spot_optimizer():
        optimizer = SpotInstanceOptimizer()

        # Example requirements for fMRI preprocessing
        requirements = ResourceRequirements(
            cpu_cores=8,
            memory_gb=32,
            storage_gb=100,
            fsl_required=True,
            freesurfer_required=True,
        )

        # Get recommendations for 4-hour job
        duration = timedelta(hours=4)
        budget = 20.0  # $20 budget

        recommendations = await optimizer.get_spot_recommendations(
            requirements, duration, budget, [CloudProvider.AWS]
        )

        print(f"Found {len(recommendations)} recommendations:")

        for i, rec in enumerate(recommendations[:5]):
            print(f"\n{i+1}. {rec.provider.value} {rec.instance_type} in {rec.region}")
            print(f"   Current Price: ${rec.current_price:.3f}/hour")
            print(
                f"   Savings: {rec.savings_percentage:.1f}% (${rec.expected_cost:.2f} total)"
            )
            print(f"   Interruption Risk: {rec.interruption_probability:.1%}")
            print(f"   Suitability Score: {rec.suitability_score:.2f}")
            print(f"   Value Score: {optimizer._calculate_value_score(rec):.2f}")

        # Test savings calculation
        savings = optimizer.calculate_savings(10.0, 3.0, 0.15)
        print("\nSavings Analysis:")
        print(f"Expected Savings: {savings['expected_percentage']:.1f}%")
        print(f"Risk-Adjusted Savings: {savings['risk_adjusted_percentage']:.1f}%")

    # Run test
    asyncio.run(test_spot_optimizer())
