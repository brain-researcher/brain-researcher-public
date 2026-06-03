"""Experiment Management for A/B testing and feature rollouts."""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import redis

from .ab_testing import ABTestingFramework, Experiment, ExperimentStatus

logger = logging.getLogger(__name__)


@dataclass
class FeatureFlag:
    name: str
    description: str
    enabled: bool
    rollout_percentage: float
    target_groups: list[str]
    conditions: dict[str, any]
    created_at: datetime
    updated_at: datetime


@dataclass
class ExperimentRule:
    experiment_id: str
    priority: int
    conditions: dict[str, any]
    enabled: bool


class ExperimentManager:
    """High-level experiment management and coordination."""

    def __init__(
        self,
        ab_framework: ABTestingFramework,
        redis_client: redis.Redis | None = None,
    ):
        self.ab_framework = ab_framework
        self.redis_client = redis_client or redis.Redis(decode_responses=True)
        self.feature_flags: dict[str, FeatureFlag] = {}
        self.experiment_rules: list[ExperimentRule] = []

        # Load existing data
        self._load_feature_flags()
        self._load_experiment_rules()

    # Feature Flag Management

    def create_feature_flag(
        self,
        name: str,
        description: str,
        enabled: bool = False,
        rollout_percentage: float = 0.0,
        target_groups: list[str] | None = None,
        conditions: dict[str, any] | None = None,
    ) -> FeatureFlag:
        """Create a new feature flag."""
        flag = FeatureFlag(
            name=name,
            description=description,
            enabled=enabled,
            rollout_percentage=rollout_percentage,
            target_groups=target_groups or [],
            conditions=conditions or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        self.feature_flags[name] = flag
        self._save_feature_flag(flag)

        logger.info(f"Created feature flag: {name}")
        return flag

    def update_feature_flag(
        self,
        name: str,
        enabled: bool | None = None,
        rollout_percentage: float | None = None,
        target_groups: list[str] | None = None,
        conditions: dict[str, any] | None = None,
    ) -> FeatureFlag:
        """Update an existing feature flag."""
        if name not in self.feature_flags:
            raise ValueError(f"Feature flag {name} not found")

        flag = self.feature_flags[name]

        if enabled is not None:
            flag.enabled = enabled
        if rollout_percentage is not None:
            flag.rollout_percentage = rollout_percentage
        if target_groups is not None:
            flag.target_groups = target_groups
        if conditions is not None:
            flag.conditions = conditions

        flag.updated_at = datetime.utcnow()

        self._save_feature_flag(flag)
        logger.info(f"Updated feature flag: {name}")

        return flag

    def is_feature_enabled(
        self, flag_name: str, user_id: str, context: dict | None = None
    ) -> bool:
        """Check if a feature is enabled for a user."""
        if flag_name not in self.feature_flags:
            return False

        flag = self.feature_flags[flag_name]

        if not flag.enabled:
            return False

        context = context or {}

        # Check conditions
        if not self._evaluate_conditions(flag.conditions, user_id, context):
            return False

        # Check target groups
        if flag.target_groups:
            user_groups = context.get("groups", [])
            if not any(group in flag.target_groups for group in user_groups):
                return False

        # Check rollout percentage
        if flag.rollout_percentage < 100:
            user_hash = hash(f"{flag_name}:{user_id}") % 100
            if user_hash >= flag.rollout_percentage:
                return False

        return True

    def get_feature_flags(self, enabled_only: bool = False) -> list[dict]:
        """Get all feature flags."""
        flags = []

        for flag in self.feature_flags.values():
            if enabled_only and not flag.enabled:
                continue

            flag_dict = asdict(flag)
            flag_dict["created_at"] = flag.created_at.isoformat()
            flag_dict["updated_at"] = flag.updated_at.isoformat()
            flags.append(flag_dict)

        return sorted(flags, key=lambda x: x["created_at"], reverse=True)

    # Experiment Coordination

    def create_experiment_with_flags(
        self,
        name: str,
        description: str,
        variants: list[str],
        allocation: dict[str, float],
        metrics: list[str],
        feature_flags: list[str],
        conditions: dict[str, any] | None = None,
        priority: int = 1,
    ) -> Experiment:
        """Create an experiment with associated feature flags."""
        # Create the A/B test
        experiment = self.ab_framework.create_experiment(
            name=name,
            description=description,
            variants=variants,
            allocation=allocation,
            metrics=metrics,
        )

        # Create experiment rule
        rule = ExperimentRule(
            experiment_id=experiment.id,
            priority=priority,
            conditions=conditions or {},
            enabled=True,
        )

        self.experiment_rules.append(rule)
        self._save_experiment_rule(rule)

        # Enable associated feature flags for experiment variants
        for flag_name in feature_flags:
            if flag_name not in self.feature_flags:
                # Create flag if it doesn't exist
                self.create_feature_flag(
                    name=flag_name,
                    description=f"Feature flag for experiment {name}",
                    enabled=True,
                    rollout_percentage=100,
                )

        logger.info(
            f"Created experiment {experiment.id} with {len(feature_flags)} feature flags"
        )
        return experiment

    def get_user_experiments(
        self, user_id: str, context: dict | None = None
    ) -> list[dict]:
        """Get all active experiments for a user."""
        context = context or {}
        user_experiments = []

        # Sort rules by priority
        sorted_rules = sorted(
            [rule for rule in self.experiment_rules if rule.enabled],
            key=lambda x: x.priority,
        )

        for rule in sorted_rules:
            if not self._evaluate_conditions(rule.conditions, user_id, context):
                continue

            try:
                experiment = self.ab_framework.experiments[rule.experiment_id]

                if experiment.status != ExperimentStatus.RUNNING:
                    continue

                variant = self.ab_framework.assign_user(user_id, experiment.id)

                user_experiments.append(
                    {
                        "experiment_id": experiment.id,
                        "experiment_name": experiment.name,
                        "variant": variant,
                        "priority": rule.priority,
                    }
                )

            except Exception as e:
                logger.error(
                    f"Error processing experiment {rule.experiment_id} for user {user_id}: {e}"
                )

        return user_experiments

    def get_user_variant(
        self, user_id: str, experiment_name: str, context: dict | None = None
    ) -> str | None:
        """Get user's variant for a specific experiment."""
        # Find experiment by name
        experiment = None
        for exp in self.ab_framework.experiments.values():
            if exp.name == experiment_name:
                experiment = exp
                break

        if not experiment:
            return None

        # Check if user qualifies for experiment
        rule = None
        for r in self.experiment_rules:
            if r.experiment_id == experiment.id and r.enabled:
                rule = r
                break

        if not rule:
            return None

        context = context or {}
        if not self._evaluate_conditions(rule.conditions, user_id, context):
            return None

        return self.ab_framework.assign_user(user_id, experiment.id)

    # Automated Experiment Management

    def auto_promote_winners(self, min_significance: float = 0.95) -> list[dict]:
        """Automatically promote winning variants to 100% traffic."""
        promoted = []

        for experiment in self.ab_framework.experiments.values():
            if experiment.status != ExperimentStatus.RUNNING:
                continue

            # Check if experiment has enough data
            status = self.ab_framework.get_experiment_status(experiment.id)
            if status["total_assignments"] < 1000:  # Minimum sample size
                continue

            # Analyze results
            results = self.ab_framework.get_experiment_results(experiment.id)

            # Check for clear winners
            for metric, result in results.items():
                if (
                    result.get("significant")
                    and result.get("probability_treatment_better", 0) > min_significance
                    and result.get("lift", 0) > 0.05  # 5% minimum lift
                ):
                    # Promote winner
                    winner = "treatment"  # Assuming binary test

                    self._promote_variant(experiment.id, winner)

                    promoted.append(
                        {
                            "experiment_id": experiment.id,
                            "experiment_name": experiment.name,
                            "winning_variant": winner,
                            "metric": metric,
                            "lift": result.get("lift", 0),
                            "significance": result.get(
                                "probability_treatment_better", 0
                            ),
                        }
                    )

                    logger.info(
                        f"Auto-promoted experiment {experiment.id} variant {winner}"
                    )
                    break

        return promoted

    def auto_stop_experiments(self, max_duration_days: int = 30) -> list[str]:
        """Automatically stop experiments that have run too long."""
        stopped = []
        cutoff_date = datetime.utcnow() - timedelta(days=max_duration_days)

        for experiment in self.ab_framework.experiments.values():
            if (
                experiment.status == ExperimentStatus.RUNNING
                and experiment.start_date
                and experiment.start_date < cutoff_date
            ):
                self.ab_framework.stop_experiment(experiment.id)
                stopped.append(experiment.id)
                logger.info(f"Auto-stopped long-running experiment {experiment.id}")

        return stopped

    # Health Monitoring

    def get_system_health(self) -> dict:
        """Get overall system health metrics."""
        total_experiments = len(self.ab_framework.experiments)
        running_experiments = sum(
            1
            for exp in self.ab_framework.experiments.values()
            if exp.status == ExperimentStatus.RUNNING
        )

        total_flags = len(self.feature_flags)
        enabled_flags = sum(1 for flag in self.feature_flags.values() if flag.enabled)

        # Check Redis connectivity
        try:
            self.redis_client.ping()
            redis_healthy = True
        except Exception:
            redis_healthy = False

        return {
            "experiments": {
                "total": total_experiments,
                "running": running_experiments,
                "completed": total_experiments - running_experiments,
            },
            "feature_flags": {"total": total_flags, "enabled": enabled_flags},
            "redis_healthy": redis_healthy,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Private Methods

    def _evaluate_conditions(
        self, conditions: dict, user_id: str, context: dict
    ) -> bool:
        """Evaluate experiment/flag conditions for a user."""
        for condition_type, condition_value in conditions.items():
            if condition_type == "user_id":
                if isinstance(condition_value, list):
                    if user_id not in condition_value:
                        return False
                elif user_id != condition_value:
                    return False

            elif condition_type == "user_attribute":
                attr_name, expected_value = (
                    condition_value["attribute"],
                    condition_value["value"],
                )
                user_value = context.get("user_attributes", {}).get(attr_name)
                if user_value != expected_value:
                    return False

            elif condition_type == "percentage":
                user_hash = hash(f"condition:{user_id}") % 100
                if user_hash >= condition_value:
                    return False

            elif condition_type == "date_range":
                now = datetime.utcnow()
                start = datetime.fromisoformat(condition_value["start"])
                end = datetime.fromisoformat(condition_value["end"])
                if not (start <= now <= end):
                    return False

        return True

    def _promote_variant(self, experiment_id: str, winning_variant: str) -> None:
        """Promote a winning variant to full traffic."""
        # Stop the experiment
        self.ab_framework.stop_experiment(experiment_id)

        # Update associated feature flags
        self.ab_framework.experiments[experiment_id]

        # This would integrate with feature deployment system
        # For now, just log the promotion
        logger.info(
            f"Promoted variant {winning_variant} for experiment {experiment_id}"
        )

    def _save_feature_flag(self, flag: FeatureFlag) -> None:
        """Save feature flag to Redis."""
        key = f"feature_flag:{flag.name}"
        data = asdict(flag)
        data["created_at"] = flag.created_at.isoformat()
        data["updated_at"] = flag.updated_at.isoformat()

        self.redis_client.hset(
            key,
            mapping={
                k: json.dumps(v) if isinstance(v, dict | list) else str(v)
                for k, v in data.items()
            },
        )

    def _load_feature_flags(self) -> None:
        """Load feature flags from Redis."""
        pattern = "feature_flag:*"

        for key in self.redis_client.scan_iter(match=pattern):
            try:
                data = self.redis_client.hgetall(key)

                # Parse JSON fields
                for field in ["target_groups", "conditions"]:
                    if field in data:
                        data[field] = json.loads(data[field])

                # Parse datetime fields
                for field in ["created_at", "updated_at"]:
                    if field in data:
                        data[field] = datetime.fromisoformat(data[field])

                # Parse boolean and numeric fields
                data["enabled"] = data["enabled"].lower() == "true"
                data["rollout_percentage"] = float(data["rollout_percentage"])

                flag = FeatureFlag(**data)
                self.feature_flags[flag.name] = flag

            except Exception as e:
                logger.error(f"Failed to load feature flag from {key}: {e}")

    def _save_experiment_rule(self, rule: ExperimentRule) -> None:
        """Save experiment rule to Redis."""
        key = f"experiment_rule:{rule.experiment_id}"
        data = asdict(rule)

        self.redis_client.hset(
            key,
            mapping={
                k: json.dumps(v) if isinstance(v, dict) else str(v)
                for k, v in data.items()
            },
        )

    def _load_experiment_rules(self) -> None:
        """Load experiment rules from Redis."""
        pattern = "experiment_rule:*"

        for key in self.redis_client.scan_iter(match=pattern):
            try:
                data = self.redis_client.hgetall(key)

                # Parse fields
                data["priority"] = int(data["priority"])
                data["enabled"] = data["enabled"].lower() == "true"
                data["conditions"] = json.loads(data["conditions"])

                rule = ExperimentRule(**data)
                self.experiment_rules.append(rule)

            except Exception as e:
                logger.error(f"Failed to load experiment rule from {key}: {e}")
