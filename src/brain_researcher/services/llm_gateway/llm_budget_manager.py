"""
LLM Budget Manager for Brain Researcher

This module provides budget management specifically for LLM API usage:
- Token-based and USD-based budget limits (daily, monthly)
- Pre-invocation budget checking with approval/denial
- Post-invocation spend recording and tracking
- Alert thresholds for budget monitoring
- Integration with TokenCounter for cost estimation
"""

import json
import logging
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import redis

from brain_researcher.services.llm_gateway.token_counter import TokenCounter

logger = logging.getLogger(__name__)

# Shared singleton for LLMBudgetManager (process-local, shared Redis)
_shared_llm_budget_manager: Optional["LLMBudgetManager"] = None
_shared_llm_budget_manager_lock = threading.Lock()


class LLMBudgetType(Enum):
    """LLM budget enforcement types"""

    HARD_LIMIT = "hard_limit"  # Block requests when exceeded
    SOFT_LIMIT = "soft_limit"  # Warn but allow override
    ADVISORY = "advisory"  # Track only, no enforcement


class AlertSeverity(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class LLMBudget:
    """LLM budget configuration for a workspace/user"""

    budget_id: str
    name: str
    budget_type: LLMBudgetType = LLMBudgetType.HARD_LIMIT

    # Token limits
    daily_token_limit: int | None = None
    monthly_token_limit: int | None = None

    # USD limits
    daily_usd_limit: Decimal | None = None
    monthly_usd_limit: Decimal | None = None

    # Alert thresholds (percentages)
    alert_thresholds: list[float] = field(default_factory=lambda: [50.0, 80.0, 95.0])

    # Configuration
    workspace_id: str | None = None
    user_id: str | None = None
    notification_emails: list[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)


@dataclass
class LLMSpendingRecord:
    """Individual LLM invocation spend record"""

    record_id: str
    budget_id: str
    allocation_id: str

    # Provider details
    provider: str
    model: str
    bill_to: str  # "managed:{budget_id}", "byok:{name}", "local_oauth"

    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int

    # Cost
    cost_usd: Decimal

    # Context
    credential_kind: str | None = None
    route: str = "primary"  # "primary" or "fallback"
    transport: str = "sdk"  # "cli" or "sdk"
    fallback_reason: str | None = None

    # Timing
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: int | None = None

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class BudgetAllocation:
    """Allocation tracking for pre/post invocation"""

    allocation_id: str
    budget_id: str
    model: str
    estimated_tokens: int
    estimated_cost_usd: Decimal
    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recorded: bool = False


@dataclass
class BudgetDecision:
    """Budget approval/denial decision"""

    approved: bool
    budget_id: str
    allocation_id: str
    reason: str

    # Remaining budget info
    remaining_daily_tokens: int | None = None
    remaining_monthly_tokens: int | None = None
    remaining_daily_usd: Decimal | None = None
    remaining_monthly_usd: Decimal | None = None

    # Alert info
    alerts_triggered: list[str] = field(default_factory=list)


@dataclass
class BudgetStatus:
    """Current budget status"""

    budget_id: str

    # Daily status
    daily_tokens_used: int = 0
    daily_tokens_limit: int | None = None
    daily_usd_spent: Decimal = Decimal("0")
    daily_usd_limit: Decimal | None = None

    # Monthly status
    monthly_tokens_used: int = 0
    monthly_tokens_limit: int | None = None
    monthly_usd_spent: Decimal = Decimal("0")
    monthly_usd_limit: Decimal | None = None

    # Remaining
    daily_tokens_remaining: int | None = None
    monthly_tokens_remaining: int | None = None
    daily_usd_remaining: Decimal | None = None
    monthly_usd_remaining: Decimal | None = None

    # Metadata
    last_reset: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BudgetExhaustedError(Exception):
    """Raised when budget is exhausted and request is denied"""

    pass


class LLMBudgetManager:
    """
    Manages LLM usage budgets with Redis persistence.

    Follows patterns from budget_manager.py but adapted for LLM token/cost tracking.
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        alert_callback: Callable | None = None,
    ):
        """
        Initialize LLM budget manager.

        Args:
            redis_client: Redis client for persistence (uses fakeredis if None)
            alert_callback: Optional callback for budget alerts
        """
        if redis_client is None:
            # Use fakeredis for testing/development
            try:
                import fakeredis

                self.redis = fakeredis.FakeRedis(decode_responses=True)
            except ImportError:
                logger.warning("fakeredis not available, using real Redis")
                self.redis = redis.Redis(decode_responses=True)
        else:
            self.redis = redis_client

        self.alert_callback = alert_callback
        self._allocations: dict[str, BudgetAllocation] = {}

        logger.info("LLMBudgetManager initialized")

    async def create_budget(self, budget: LLMBudget) -> bool:
        """
        Create a new LLM budget.

        Args:
            budget: LLMBudget configuration

        Returns:
            True if created successfully
        """
        try:
            # Store budget configuration
            budget_key = f"llm_budget:{budget.budget_id}:config"
            budget_data = {
                "name": budget.name,
                "budget_type": budget.budget_type.value,
                "daily_token_limit": budget.daily_token_limit,
                "monthly_token_limit": budget.monthly_token_limit,
                "daily_usd_limit": (
                    str(budget.daily_usd_limit) if budget.daily_usd_limit else None
                ),
                "monthly_usd_limit": (
                    str(budget.monthly_usd_limit) if budget.monthly_usd_limit else None
                ),
                "alert_thresholds": json.dumps(budget.alert_thresholds),
                "workspace_id": budget.workspace_id,
                "user_id": budget.user_id,
                "notification_emails": json.dumps(budget.notification_emails),
                "created_at": budget.created_at.isoformat(),
                "tags": json.dumps(budget.tags),
            }

            self.redis.hset(
                budget_key,
                mapping={k: v for k, v in budget_data.items() if v is not None},
            )

            # Initialize spending counters
            await self._init_spending_counters(budget.budget_id)

            logger.info(f"Created LLM budget: {budget.budget_id} ({budget.name})")
            return True

        except Exception as e:
            logger.error(f"Failed to create budget {budget.budget_id}: {e}")
            return False

    async def _init_spending_counters(self, budget_id: str):
        """Initialize spending counters for a budget"""
        today = date.today().isoformat()
        month = today[:7]  # YYYY-MM

        # Daily counters
        self.redis.hset(
            f"llm_budget:{budget_id}:daily:{today}", mapping={"tokens": 0, "usd": "0.0"}
        )

        # Monthly counters
        self.redis.hset(
            f"llm_budget:{budget_id}:monthly:{month}",
            mapping={"tokens": 0, "usd": "0.0"},
        )

    async def pre_invocation_check(
        self,
        budget_id: str,
        model: str,
        estimated_tokens: int,
        provider: str = "google",
    ) -> BudgetDecision:
        """
        Check if budget allows the invocation before calling LLM.

        Args:
            budget_id: Budget identifier
            model: Model name for cost estimation
            estimated_tokens: Estimated total tokens (input + output)
            provider: Provider name

        Returns:
            BudgetDecision with approval status and details
        """
        try:
            # Load budget config
            budget_config = await self._load_budget_config(budget_id)
            if not budget_config:
                return BudgetDecision(
                    approved=False,
                    budget_id=budget_id,
                    allocation_id="",
                    reason="Budget not found",
                )

            # Get current spending
            status = await self.get_budget_status(budget_id)

            # Estimate cost for this invocation
            # Use 50/50 split for input/output estimation
            estimated_input = estimated_tokens // 2
            estimated_output = estimated_tokens // 2
            cost_info = TokenCounter.estimate_cost(
                estimated_input, estimated_output, provider, model
            )
            estimated_cost = Decimal(str(cost_info["total_cost_usd"]))

            # Create allocation
            allocation_id = str(uuid.uuid4())
            allocation = BudgetAllocation(
                allocation_id=allocation_id,
                budget_id=budget_id,
                model=model,
                estimated_tokens=estimated_tokens,
                estimated_cost_usd=estimated_cost,
            )
            self._allocations[allocation_id] = allocation

            # Check budget type
            budget_type = LLMBudgetType(budget_config.get("budget_type", "hard_limit"))

            # Determine if we can approve
            approved = True
            reason = "Budget available"
            alerts = []

            # Check daily token limit
            if budget_config.get("daily_token_limit"):
                daily_limit = int(budget_config["daily_token_limit"])
                if status.daily_tokens_used + estimated_tokens > daily_limit:
                    if budget_type == LLMBudgetType.HARD_LIMIT:
                        approved = False
                        reason = f"Daily token limit exceeded ({status.daily_tokens_used}/{daily_limit})"
                    else:
                        alerts.append("daily_token_limit_exceeded")

            # Check monthly token limit
            if budget_config.get("monthly_token_limit"):
                monthly_limit = int(budget_config["monthly_token_limit"])
                if status.monthly_tokens_used + estimated_tokens > monthly_limit:
                    if budget_type == LLMBudgetType.HARD_LIMIT:
                        approved = False
                        reason = f"Monthly token limit exceeded ({status.monthly_tokens_used}/{monthly_limit})"
                    else:
                        alerts.append("monthly_token_limit_exceeded")

            # Check daily USD limit
            if budget_config.get("daily_usd_limit"):
                daily_limit = Decimal(budget_config["daily_usd_limit"])
                if status.daily_usd_spent + estimated_cost > daily_limit:
                    if budget_type == LLMBudgetType.HARD_LIMIT:
                        approved = False
                        reason = f"Daily USD limit exceeded (${status.daily_usd_spent}/${daily_limit})"
                    else:
                        alerts.append("daily_usd_limit_exceeded")

            # Check monthly USD limit
            if budget_config.get("monthly_usd_limit"):
                monthly_limit = Decimal(budget_config["monthly_usd_limit"])
                if status.monthly_usd_spent + estimated_cost > monthly_limit:
                    if budget_type == LLMBudgetType.HARD_LIMIT:
                        approved = False
                        reason = f"Monthly USD limit exceeded (${status.monthly_usd_spent}/${monthly_limit})"
                    else:
                        alerts.append("monthly_usd_limit_exceeded")

            # Check alert thresholds
            await self._check_alert_thresholds(budget_id, budget_config, status)

            return BudgetDecision(
                approved=approved,
                budget_id=budget_id,
                allocation_id=allocation_id,
                reason=reason,
                remaining_daily_tokens=status.daily_tokens_remaining,
                remaining_monthly_tokens=status.monthly_tokens_remaining,
                remaining_daily_usd=status.daily_usd_remaining,
                remaining_monthly_usd=status.monthly_usd_remaining,
                alerts_triggered=alerts,
            )

        except Exception as e:
            logger.error(f"Error in pre_invocation_check for {budget_id}: {e}")
            return BudgetDecision(
                approved=False,
                budget_id=budget_id,
                allocation_id="",
                reason=f"Budget check failed: {str(e)}",
            )

    async def post_invocation_record(
        self,
        allocation_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        provider: str,
        model: str,
        bill_to: str,
        credential_kind: str | None = None,
        route: str = "primary",
        transport: str = "sdk",
        fallback_reason: str | None = None,
        latency_ms: int | None = None,
    ) -> bool:
        """
        Record actual LLM invocation spend after call completes.

        Args:
            allocation_id: Allocation ID from pre-check
            input_tokens: Actual input tokens used
            output_tokens: Actual output tokens used
            cost_usd: Actual cost in USD
            provider: Provider name
            model: Model name
            bill_to: Billing destination (managed:*, byok:*, local_oauth)
            credential_kind: Credential type used
            route: "primary" or "fallback"
            transport: "cli" or "sdk"
            fallback_reason: Reason for fallback if applicable
            latency_ms: Call latency in milliseconds

        Returns:
            True if recorded successfully
        """
        try:
            # Get allocation
            allocation = self._allocations.get(allocation_id)
            if not allocation:
                logger.warning(
                    f"Allocation {allocation_id} not found, creating new record"
                )
                budget_id = "unknown"
            else:
                budget_id = allocation.budget_id
                allocation.recorded = True

            # Create spending record
            record_id = str(uuid.uuid4())
            record = LLMSpendingRecord(
                record_id=record_id,
                budget_id=budget_id,
                allocation_id=allocation_id,
                provider=provider,
                model=model,
                bill_to=bill_to,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost_usd,
                credential_kind=credential_kind,
                route=route,
                transport=transport,
                fallback_reason=fallback_reason,
                latency_ms=latency_ms,
            )

            # Store record
            await self._store_spending_record(record)

            # Update spending counters
            await self._update_spending_counters(budget_id, record)

            logger.debug(
                f"Recorded LLM spend for {budget_id}: "
                f"{record.total_tokens} tokens, ${cost_usd} via {bill_to}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to record invocation for {allocation_id}: {e}")
            return False

    async def _store_spending_record(self, record: LLMSpendingRecord):
        """Store a spending record in Redis"""
        record_key = f"llm_budget:{record.budget_id}:records:{record.record_id}"
        record_data = {
            "allocation_id": record.allocation_id,
            "provider": record.provider,
            "model": record.model,
            "bill_to": record.bill_to,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "total_tokens": record.total_tokens,
            "cost_usd": str(record.cost_usd),
            "credential_kind": record.credential_kind or "",
            "route": record.route,
            "transport": record.transport,
            "fallback_reason": record.fallback_reason or "",
            "timestamp": record.timestamp.isoformat(),
            "latency_ms": record.latency_ms or 0,
            "tags": json.dumps(record.tags),
        }

        self.redis.hset(record_key, mapping=record_data)

        # Add to sorted set for time-based queries
        timestamp = record.timestamp.timestamp()
        self.redis.zadd(
            f"llm_budget:{record.budget_id}:records_by_time",
            {record.record_id: timestamp},
        )

    async def _update_spending_counters(
        self, budget_id: str, record: LLMSpendingRecord
    ):
        """Update daily and monthly spending counters"""
        today = date.today().isoformat()
        month = today[:7]  # YYYY-MM

        # Update daily counters
        daily_key = f"llm_budget:{budget_id}:daily:{today}"
        self.redis.hincrby(daily_key, "tokens", record.total_tokens)

        # Update USD with atomic increment
        current_daily_usd = Decimal(self.redis.hget(daily_key, "usd") or "0")
        new_daily_usd = current_daily_usd + record.cost_usd
        self.redis.hset(daily_key, "usd", str(new_daily_usd))

        # Update monthly counters
        monthly_key = f"llm_budget:{budget_id}:monthly:{month}"
        self.redis.hincrby(monthly_key, "tokens", record.total_tokens)

        current_monthly_usd = Decimal(self.redis.hget(monthly_key, "usd") or "0")
        new_monthly_usd = current_monthly_usd + record.cost_usd
        self.redis.hset(monthly_key, "usd", str(new_monthly_usd))

    async def get_budget_status(self, budget_id: str) -> BudgetStatus:
        """
        Get current budget status with remaining amounts.

        Args:
            budget_id: Budget identifier

        Returns:
            BudgetStatus with current usage and remaining budget
        """
        try:
            # Load budget config
            budget_config = await self._load_budget_config(budget_id)

            # Get current spending
            today = date.today().isoformat()
            month = today[:7]

            daily_key = f"llm_budget:{budget_id}:daily:{today}"
            monthly_key = f"llm_budget:{budget_id}:monthly:{month}"

            # Get daily stats
            daily_data = self.redis.hgetall(daily_key)
            daily_tokens_used = int(daily_data.get("tokens", 0))
            daily_usd_spent = Decimal(daily_data.get("usd", "0"))

            # Get monthly stats
            monthly_data = self.redis.hgetall(monthly_key)
            monthly_tokens_used = int(monthly_data.get("tokens", 0))
            monthly_usd_spent = Decimal(monthly_data.get("usd", "0"))

            # Calculate remaining
            daily_token_limit = budget_config.get("daily_token_limit")
            monthly_token_limit = budget_config.get("monthly_token_limit")
            daily_usd_limit = budget_config.get("daily_usd_limit")
            monthly_usd_limit = budget_config.get("monthly_usd_limit")

            status = BudgetStatus(
                budget_id=budget_id,
                daily_tokens_used=daily_tokens_used,
                daily_tokens_limit=(
                    int(daily_token_limit) if daily_token_limit else None
                ),
                daily_usd_spent=daily_usd_spent,
                daily_usd_limit=Decimal(daily_usd_limit) if daily_usd_limit else None,
                monthly_tokens_used=monthly_tokens_used,
                monthly_tokens_limit=(
                    int(monthly_token_limit) if monthly_token_limit else None
                ),
                monthly_usd_spent=monthly_usd_spent,
                monthly_usd_limit=(
                    Decimal(monthly_usd_limit) if monthly_usd_limit else None
                ),
            )

            # Calculate remaining
            if status.daily_tokens_limit:
                status.daily_tokens_remaining = max(
                    0, status.daily_tokens_limit - daily_tokens_used
                )

            if status.monthly_tokens_limit:
                status.monthly_tokens_remaining = max(
                    0, status.monthly_tokens_limit - monthly_tokens_used
                )

            if status.daily_usd_limit:
                status.daily_usd_remaining = max(
                    Decimal("0"), status.daily_usd_limit - daily_usd_spent
                )

            if status.monthly_usd_limit:
                status.monthly_usd_remaining = max(
                    Decimal("0"), status.monthly_usd_limit - monthly_usd_spent
                )

            return status

        except Exception as e:
            logger.error(f"Error getting budget status for {budget_id}: {e}")
            return BudgetStatus(budget_id=budget_id)

    async def _load_budget_config(self, budget_id: str) -> dict[str, Any]:
        """Load budget configuration from Redis"""
        budget_key = f"llm_budget:{budget_id}:config"
        config = self.redis.hgetall(budget_key)
        return config if config else {}

    async def _check_alert_thresholds(
        self, budget_id: str, budget_config: dict[str, Any], status: BudgetStatus
    ):
        """Check if alert thresholds have been crossed"""
        try:
            thresholds = json.loads(budget_config.get("alert_thresholds", "[]"))

            # Check each limit type
            for limit_type in [
                "daily_usd",
                "monthly_usd",
                "daily_tokens",
                "monthly_tokens",
            ]:
                limit_value = budget_config.get(f"{limit_type}_limit")
                if not limit_value:
                    continue

                # Get the correct field name (USD uses _spent, tokens use _used)
                if limit_type.endswith("usd"):
                    used_field = f"{limit_type}_spent"
                    limit_value = Decimal(limit_value)
                else:
                    used_field = f"{limit_type}_used"
                    limit_value = int(limit_value)

                used_value = getattr(status, used_field)
                if limit_type.endswith("usd"):
                    used_value = Decimal(used_value)

                percentage = (
                    (float(used_value) / float(limit_value)) * 100
                    if limit_value > 0
                    else 0
                )

                # Check thresholds
                for threshold in thresholds:
                    if percentage >= threshold:
                        # Check if we've already alerted for this threshold
                        alert_key = (
                            f"llm_budget:{budget_id}:alerts:{limit_type}:{threshold}"
                        )
                        if not self.redis.exists(alert_key):
                            await self._trigger_alert(
                                budget_id,
                                limit_type,
                                threshold,
                                percentage,
                                used_value,
                                limit_value,
                            )
                            # Set alert key with 24h expiry
                            self.redis.setex(alert_key, 86400, "1")

        except Exception as e:
            logger.error(f"Error checking alert thresholds for {budget_id}: {e}")

    async def _trigger_alert(
        self,
        budget_id: str,
        limit_type: str,
        threshold: float,
        current_percentage: float,
        used_value: Any,
        limit_value: Any,
    ):
        """Trigger a budget alert"""
        severity = AlertSeverity.INFO
        if threshold >= 95:
            severity = AlertSeverity.CRITICAL
        elif threshold >= 80:
            severity = AlertSeverity.WARNING

        message = (
            f"LLM Budget Alert: {budget_id} has reached {current_percentage:.1f}% "
            f"of {limit_type} limit ({used_value}/{limit_value})"
        )

        logger.warning(message)

        # Call alert callback if provided
        if self.alert_callback:
            try:
                await self.alert_callback(
                    {
                        "budget_id": budget_id,
                        "severity": severity.value,
                        "limit_type": limit_type,
                        "threshold": threshold,
                        "current_percentage": current_percentage,
                        "used_value": str(used_value),
                        "limit_value": str(limit_value),
                        "message": message,
                    }
                )
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")


# ---- Shared factory ----------------------------------------------------------


def get_shared_llm_budget_manager() -> "LLMBudgetManager":
    """Return a process-local singleton LLMBudgetManager using Redis from env if set."""

    global _shared_llm_budget_manager
    if _shared_llm_budget_manager is not None:
        return _shared_llm_budget_manager

    with _shared_llm_budget_manager_lock:
        if _shared_llm_budget_manager is not None:
            return _shared_llm_budget_manager

        redis_url = os.getenv("BR_REDIS_URL") or os.getenv("REDIS_URL")
        client = None
        if redis_url:
            try:
                client = redis.from_url(redis_url)  # type: ignore[arg-type]
            except Exception as exc:  # pragma: no cover - fallback path
                logger.warning("Failed to connect to Redis at %s: %s", redis_url, exc)
                client = None

        _shared_llm_budget_manager = LLMBudgetManager(redis_client=client)
        return _shared_llm_budget_manager
