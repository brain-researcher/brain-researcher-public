"""A/B Testing Framework for feature experimentation and RL data collection."""

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum

import numpy as np
import redis
from scipy import stats

logger = logging.getLogger(__name__)


class ExperimentStatus(Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass
class Experiment:
    id: str
    name: str
    description: str
    variants: list[str]
    allocation: dict[str, float]  # variant -> allocation ratio
    metrics: list[str]
    status: ExperimentStatus
    start_date: datetime | None = None
    end_date: datetime | None = None
    sample_size: int | None = None
    significance_level: float = 0.05
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class ExperimentResult:
    experiment_id: str
    variant: str
    metrics: dict[str, float]
    sample_size: int
    confidence_intervals: dict[str, tuple[float, float]]
    statistical_significance: dict[str, bool]
    p_values: dict[str, float]


class StatisticalAnalyzer:
    """Statistical analysis for A/B test results."""

    @staticmethod
    def calculate_conversion_rate(successes: int, trials: int) -> float:
        """Calculate conversion rate with Laplace smoothing."""
        if trials == 0:
            return 0.0
        return (successes + 1) / (trials + 2)

    @staticmethod
    def wilson_confidence_interval(
        successes: int, trials: int, alpha: float = 0.05
    ) -> tuple[float, float]:
        """Calculate Wilson confidence interval for conversion rate."""
        if trials == 0:
            return 0.0, 0.0

        z = stats.norm.ppf(1 - alpha / 2)
        p = successes / trials

        center = (p + z**2 / (2 * trials)) / (1 + z**2 / trials)
        margin = (
            z
            * np.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2))
            / (1 + z**2 / trials)
        )

        return max(0, center - margin), min(1, center + margin)

    @staticmethod
    def two_proportion_z_test(
        x1: int, n1: int, x2: int, n2: int
    ) -> tuple[float, float]:
        """Perform two-proportion z-test."""
        if n1 == 0 or n2 == 0:
            return 0.0, 1.0

        p1 = x1 / n1
        p2 = x2 / n2
        p_pool = (x1 + x2) / (n1 + n2)

        se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))

        if se == 0:
            return 0.0, 1.0

        z = (p1 - p2) / se
        p_value = 2 * (1 - stats.norm.cdf(abs(z)))

        return z, p_value

    @staticmethod
    def bayesian_probability(x1: int, n1: int, x2: int, n2: int) -> float:
        """Calculate Bayesian probability that variant A > variant B."""
        # Beta-binomial model
        alpha1, beta1 = x1 + 1, n1 - x1 + 1
        alpha2, beta2 = x2 + 1, n2 - x2 + 1

        # Monte Carlo integration
        samples_a = np.random.beta(alpha1, beta1, 10000)
        samples_b = np.random.beta(alpha2, beta2, 10000)

        return np.mean(samples_a > samples_b)


class ABTestingFramework:
    """Main A/B testing framework for experiment management and analysis."""

    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis_client = redis_client or redis.Redis(decode_responses=True)
        self.experiments: dict[str, Experiment] = {}
        self.assignments: dict[str, dict[str, str]] = (
            {}
        )  # user_id -> {experiment_id: variant}
        self.stats = StatisticalAnalyzer()

        # Load existing experiments
        self._load_experiments()

    def create_experiment(
        self,
        name: str,
        description: str,
        variants: list[str],
        allocation: dict[str, float],
        metrics: list[str],
        sample_size: int | None = None,
        significance_level: float = 0.05,
    ) -> Experiment:
        """Create a new A/B test experiment."""
        # Validate allocation ratios
        if abs(sum(allocation.values()) - 1.0) > 1e-6:
            raise ValueError("Allocation ratios must sum to 1.0")

        if set(allocation.keys()) != set(variants):
            raise ValueError("Allocation keys must match variants")

        experiment_id = self._generate_experiment_id(name)
        experiment = Experiment(
            id=experiment_id,
            name=name,
            description=description,
            variants=variants,
            allocation=allocation,
            metrics=metrics,
            status=ExperimentStatus.DRAFT,
            sample_size=sample_size,
            significance_level=significance_level,
        )

        self.experiments[experiment_id] = experiment
        self._save_experiment(experiment)

        logger.info(f"Created experiment {experiment_id}: {name}")
        return experiment

    def start_experiment(self, experiment_id: str) -> None:
        """Start running an experiment."""
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self.experiments[experiment_id]
        experiment.status = ExperimentStatus.RUNNING
        experiment.start_date = datetime.utcnow()

        self._save_experiment(experiment)
        logger.info(f"Started experiment {experiment_id}")

    def stop_experiment(self, experiment_id: str) -> None:
        """Stop a running experiment."""
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self.experiments[experiment_id]
        experiment.status = ExperimentStatus.COMPLETED
        experiment.end_date = datetime.utcnow()

        self._save_experiment(experiment)
        logger.info(f"Stopped experiment {experiment_id}")

    def assign_user(self, user_id: str, experiment_id: str) -> str:
        """Assign user to a variant using hash-based assignment for consistency."""
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self.experiments[experiment_id]

        if experiment.status != ExperimentStatus.RUNNING:
            # Return control variant for non-running experiments
            return experiment.variants[0]

        # Check existing assignment
        assignment_key = f"assignment:{user_id}:{experiment_id}"
        existing_assignment = self.redis_client.get(assignment_key)

        if existing_assignment:
            return existing_assignment

        # Hash-based assignment for consistency
        hash_input = f"{user_id}:{experiment_id}".encode()
        hash_value = hashlib.md5(hash_input).hexdigest()
        random_value = int(hash_value[:8], 16) / (16**8)

        # Assign based on allocation ratios
        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += experiment.allocation[variant]
            if random_value <= cumulative:
                # Store assignment
                self.redis_client.setex(assignment_key, timedelta(days=30), variant)

                # Track assignment
                self._track_assignment(user_id, experiment_id, variant)

                logger.debug(
                    f"Assigned user {user_id} to variant {variant} in experiment {experiment_id}"
                )
                return variant

        # Fallback to first variant
        return experiment.variants[0]

    def get_experiment_results(self, experiment_id: str) -> dict[str, ExperimentResult]:
        """Get statistical analysis results for an experiment."""
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self.experiments[experiment_id]
        results = {}

        # Get metrics data for each variant
        variant_data = {}
        for variant in experiment.variants:
            variant_data[variant] = self._get_variant_metrics(experiment_id, variant)

        # Analyze each metric
        for metric in experiment.metrics:
            results[metric] = self._analyze_metric(experiment, metric, variant_data)

        return results

    def get_experiment_status(self, experiment_id: str) -> dict:
        """Get current status and progress of an experiment."""
        if experiment_id not in self.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self.experiments[experiment_id]

        # Count assignments
        assignment_counts = {}
        for variant in experiment.variants:
            count = self._count_variant_assignments(experiment_id, variant)
            assignment_counts[variant] = count

        total_assignments = sum(assignment_counts.values())

        status = {
            "experiment": asdict(experiment),
            "total_assignments": total_assignments,
            "variant_assignments": assignment_counts,
            "completion_rate": (
                total_assignments / experiment.sample_size
                if experiment.sample_size
                else None
            ),
            "days_running": (
                (datetime.utcnow() - experiment.start_date).days
                if experiment.start_date
                else None
            ),
        }

        return status

    def list_experiments(self, status: ExperimentStatus | None = None) -> list[dict]:
        """List all experiments, optionally filtered by status."""
        experiments = []

        for experiment in self.experiments.values():
            if status is None or experiment.status == status:
                experiments.append(
                    {
                        **asdict(experiment),
                        "total_assignments": sum(
                            self._count_variant_assignments(experiment.id, variant)
                            for variant in experiment.variants
                        ),
                    }
                )

        return sorted(experiments, key=lambda x: x["created_at"], reverse=True)

    def _generate_experiment_id(self, name: str) -> str:
        """Generate unique experiment ID."""
        timestamp = str(int(time.time()))
        name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
        return f"exp_{name_hash}_{timestamp}"

    def _save_experiment(self, experiment: Experiment) -> None:
        """Save experiment to Redis."""
        key = f"experiment:{experiment.id}"
        data = asdict(experiment)

        # Convert datetime objects to ISO strings
        for field in ["created_at", "start_date", "end_date"]:
            if data[field]:
                data[field] = data[field].isoformat()

        data["status"] = experiment.status.value

        self.redis_client.hset(
            key,
            mapping={
                k: json.dumps(v) if isinstance(v, dict | list) else str(v)
                for k, v in data.items()
            },
        )

    def _load_experiments(self) -> None:
        """Load experiments from Redis."""
        pattern = "experiment:*"

        for key in self.redis_client.scan_iter(match=pattern):
            try:
                data = self.redis_client.hgetall(key)

                # Parse JSON fields
                for field in ["variants", "allocation", "metrics"]:
                    if field in data:
                        data[field] = json.loads(data[field])

                # Parse datetime fields
                for field in ["created_at", "start_date", "end_date"]:
                    if data.get(field) and data[field] != "None":
                        data[field] = datetime.fromisoformat(data[field])
                    else:
                        data[field] = None

                # Parse enum
                if "status" in data:
                    data["status"] = ExperimentStatus(data["status"])

                # Parse numeric fields
                if "significance_level" in data:
                    data["significance_level"] = float(data["significance_level"])

                if data.get("sample_size") and data["sample_size"] != "None":
                    data["sample_size"] = int(data["sample_size"])
                else:
                    data["sample_size"] = None

                experiment = Experiment(**data)
                self.experiments[experiment.id] = experiment

            except Exception as e:
                logger.error(f"Failed to load experiment from {key}: {e}")

    def _track_assignment(self, user_id: str, experiment_id: str, variant: str) -> None:
        """Track user assignment for analytics."""
        key = f"assignments:{experiment_id}:{variant}"
        self.redis_client.sadd(key, user_id)

        # Also track timestamp
        timestamp_key = f"assignment_time:{user_id}:{experiment_id}"
        self.redis_client.setex(
            timestamp_key, timedelta(days=30), str(int(time.time()))
        )

    def _count_variant_assignments(self, experiment_id: str, variant: str) -> int:
        """Count assignments for a variant."""
        key = f"assignments:{experiment_id}:{variant}"
        return self.redis_client.scard(key)

    def _get_variant_metrics(self, experiment_id: str, variant: str) -> dict:
        """Get metrics data for a variant."""
        # This would integrate with MetricsCollector
        # For now, return mock data
        key = f"metrics:{experiment_id}:{variant}"
        data = self.redis_client.hgetall(key)

        return {
            "conversions": int(data.get("conversions", 0)),
            "impressions": int(data.get("impressions", 0)),
            "revenue": float(data.get("revenue", 0.0)),
            "engagement_time": float(data.get("engagement_time", 0.0)),
        }

    def _analyze_metric(
        self, experiment: Experiment, metric: str, variant_data: dict
    ) -> dict:
        """Perform statistical analysis for a metric across variants."""
        if len(experiment.variants) != 2:
            # Multi-variant testing not implemented
            return {}

        control, treatment = experiment.variants
        control_data = variant_data[control]
        treatment_data = variant_data[treatment]

        if metric == "conversion_rate":
            control_conversions = control_data.get("conversions", 0)
            control_impressions = control_data.get("impressions", 0)
            treatment_conversions = treatment_data.get("conversions", 0)
            treatment_impressions = treatment_data.get("impressions", 0)

            # Calculate rates
            control_rate = self.stats.calculate_conversion_rate(
                control_conversions, control_impressions
            )
            treatment_rate = self.stats.calculate_conversion_rate(
                treatment_conversions, treatment_impressions
            )

            # Statistical test
            z_stat, p_value = self.stats.two_proportion_z_test(
                control_conversions,
                control_impressions,
                treatment_conversions,
                treatment_impressions,
            )

            # Confidence intervals
            control_ci = self.stats.wilson_confidence_interval(
                control_conversions, control_impressions, experiment.significance_level
            )
            treatment_ci = self.stats.wilson_confidence_interval(
                treatment_conversions,
                treatment_impressions,
                experiment.significance_level,
            )

            # Bayesian probability
            prob_treatment_better = self.stats.bayesian_probability(
                treatment_conversions,
                treatment_impressions,
                control_conversions,
                control_impressions,
            )

            return {
                "control_rate": control_rate,
                "treatment_rate": treatment_rate,
                "lift": (
                    (treatment_rate - control_rate) / control_rate
                    if control_rate > 0
                    else 0
                ),
                "z_statistic": z_stat,
                "p_value": p_value,
                "significant": p_value < experiment.significance_level,
                "control_ci": control_ci,
                "treatment_ci": treatment_ci,
                "probability_treatment_better": prob_treatment_better,
                "control_sample_size": control_impressions,
                "treatment_sample_size": treatment_impressions,
            }

        # Add more metric types as needed
        return {}
