"""
Unit tests for LLM Budget Manager

Tests budget creation, pre/post invocation tracking, budget enforcement,
alert thresholds, and spending aggregation.
"""

import pytest
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch
import fakeredis

from brain_researcher.services.agent.llm_budget_manager import (
    LLMBudget,
    LLMSpendingRecord,
    BudgetAllocation,
    BudgetDecision,
    BudgetStatus,
    LLMBudgetManager,
    LLMBudgetType,
    BudgetExhaustedError,
)


@pytest.fixture
def fake_redis():
    """Provide a fake Redis client for testing"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def budget_manager(fake_redis):
    """Provide a budget manager instance with fake Redis"""
    return LLMBudgetManager(redis_client=fake_redis)


@pytest.fixture
def sample_budget():
    """Provide a sample budget configuration"""
    return LLMBudget(
        budget_id="test_budget_123",
        name="Test Budget",
        budget_type=LLMBudgetType.HARD_LIMIT,
        daily_token_limit=10000,
        monthly_token_limit=100000,
        daily_usd_limit=Decimal("5.00"),
        monthly_usd_limit=Decimal("50.00"),
        alert_thresholds=[50.0, 80.0, 95.0],
        workspace_id="workspace_1",
        user_id="user_1",
    )


@pytest.fixture
def soft_limit_budget():
    """Provide a soft limit budget configuration"""
    return LLMBudget(
        budget_id="soft_budget_456",
        name="Soft Limit Budget",
        budget_type=LLMBudgetType.SOFT_LIMIT,
        daily_token_limit=5000,
        daily_usd_limit=Decimal("2.00"),
    )


# ============================================================================
# Budget Creation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_budget_success(budget_manager, sample_budget):
    """Test successful budget creation"""
    result = await budget_manager.create_budget(sample_budget)

    assert result is True

    # Verify budget config was stored
    config = await budget_manager._load_budget_config(sample_budget.budget_id)
    assert config["name"] == "Test Budget"
    assert config["budget_type"] == "hard_limit"
    assert int(config["daily_token_limit"]) == 10000
    assert int(config["monthly_token_limit"]) == 100000
    assert Decimal(config["daily_usd_limit"]) == Decimal("5.00")
    assert Decimal(config["monthly_usd_limit"]) == Decimal("50.00")


@pytest.mark.asyncio
async def test_create_budget_initializes_counters(budget_manager, sample_budget):
    """Test that budget creation initializes spending counters"""
    await budget_manager.create_budget(sample_budget)

    today = date.today().isoformat()
    month = today[:7]

    # Check daily counters
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    daily_data = budget_manager.redis.hgetall(daily_key)
    assert int(daily_data["tokens"]) == 0
    assert Decimal(daily_data["usd"]) == Decimal("0.0")

    # Check monthly counters
    monthly_key = f"llm_budget:{sample_budget.budget_id}:monthly:{month}"
    monthly_data = budget_manager.redis.hgetall(monthly_key)
    assert int(monthly_data["tokens"]) == 0
    assert Decimal(monthly_data["usd"]) == Decimal("0.0")


# ============================================================================
# Pre-Invocation Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_pre_check_approved_sufficient_budget(budget_manager, sample_budget):
    """Test pre-check approves when budget is sufficient"""
    await budget_manager.create_budget(sample_budget)

    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,
        provider="google"
    )

    assert decision.approved is True
    assert decision.budget_id == sample_budget.budget_id
    assert decision.allocation_id is not None
    assert decision.reason == "Budget available"
    assert decision.remaining_daily_tokens == 10000
    assert decision.remaining_monthly_tokens == 100000


@pytest.mark.asyncio
async def test_pre_check_denied_daily_token_exceeded(budget_manager, sample_budget):
    """Test pre-check denies when daily token limit exceeded"""
    await budget_manager.create_budget(sample_budget)

    # Use up daily token budget
    today = date.today().isoformat()
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    budget_manager.redis.hset(daily_key, "tokens", 9500)

    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,  # Would exceed 10000 limit
        provider="google"
    )

    assert decision.approved is False
    assert "Daily token limit exceeded" in decision.reason


@pytest.mark.asyncio
async def test_pre_check_denied_monthly_token_exceeded(budget_manager, sample_budget):
    """Test pre-check denies when monthly token limit exceeded"""
    await budget_manager.create_budget(sample_budget)

    # Use up monthly token budget
    today = date.today().isoformat()
    month = today[:7]
    monthly_key = f"llm_budget:{sample_budget.budget_id}:monthly:{month}"
    budget_manager.redis.hset(monthly_key, "tokens", 99500)

    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,  # Would exceed 100000 limit
        provider="google"
    )

    assert decision.approved is False
    assert "Monthly token limit exceeded" in decision.reason


@pytest.mark.asyncio
async def test_pre_check_denied_daily_usd_exceeded(budget_manager, sample_budget):
    """Test pre-check denies when daily USD limit exceeded"""
    await budget_manager.create_budget(sample_budget)

    # Use up daily USD budget
    today = date.today().isoformat()
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    budget_manager.redis.hset(daily_key, "usd", "4.90")

    # Request that would cost ~$0.20 (exceeds $5 limit)
    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-1.5-pro",  # More expensive model
        estimated_tokens=100000,
        provider="google"
    )

    assert decision.approved is False
    assert "Daily USD limit exceeded" in decision.reason


@pytest.mark.asyncio
async def test_pre_check_denied_monthly_usd_exceeded(budget_manager, sample_budget):
    """Test pre-check denies when monthly USD limit exceeded"""
    await budget_manager.create_budget(sample_budget)

    # Use up monthly USD budget
    today = date.today().isoformat()
    month = today[:7]
    monthly_key = f"llm_budget:{sample_budget.budget_id}:monthly:{month}"
    budget_manager.redis.hset(monthly_key, "usd", "49.90")

    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-1.5-pro",
        estimated_tokens=50000,
        provider="google"
    )

    assert decision.approved is False
    assert "Monthly USD limit exceeded" in decision.reason


@pytest.mark.asyncio
async def test_pre_check_soft_limit_allows_override(budget_manager, soft_limit_budget):
    """Test soft limit budget allows override with warning"""
    await budget_manager.create_budget(soft_limit_budget)

    # Use up daily budget
    today = date.today().isoformat()
    daily_key = f"llm_budget:{soft_limit_budget.budget_id}:daily:{today}"
    budget_manager.redis.hset(daily_key, "tokens", 5500)

    decision = await budget_manager.pre_invocation_check(
        budget_id=soft_limit_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,
        provider="google"
    )

    # Soft limit should still approve
    assert decision.approved is True
    assert "daily_token_limit_exceeded" in decision.alerts_triggered


@pytest.mark.asyncio
async def test_pre_check_budget_not_found(budget_manager):
    """Test pre-check returns error when budget not found"""
    decision = await budget_manager.pre_invocation_check(
        budget_id="nonexistent_budget",
        model="gemini-2.5-pro",
        estimated_tokens=1000,
        provider="google"
    )

    assert decision.approved is False
    assert decision.reason == "Budget not found"


# ============================================================================
# Post-Invocation Recording Tests
# ============================================================================


@pytest.mark.asyncio
async def test_post_record_updates_spend(budget_manager, sample_budget):
    """Test post-invocation recording updates spending counters"""
    await budget_manager.create_budget(sample_budget)

    # Get allocation
    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,
        provider="google"
    )

    # Record actual usage
    result = await budget_manager.post_invocation_record(
        allocation_id=decision.allocation_id,
        input_tokens=500,
        output_tokens=300,
        cost_usd=Decimal("0.001"),
        provider="google",
        model="gemini-2.5-pro",
        bill_to="managed:test_budget_123",
        credential_kind="managed_gemini",
        route="primary",
        transport="sdk",
        latency_ms=1500
    )

    assert result is True

    # Verify counters updated
    status = await budget_manager.get_budget_status(sample_budget.budget_id)
    assert status.daily_tokens_used == 800
    assert status.monthly_tokens_used == 800
    assert status.daily_usd_spent == Decimal("0.001")
    assert status.monthly_usd_spent == Decimal("0.001")


@pytest.mark.asyncio
async def test_post_record_creates_spending_record(budget_manager, sample_budget):
    """Test post-invocation creates spending record in Redis"""
    await budget_manager.create_budget(sample_budget)

    decision = await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-pro",
        estimated_tokens=1000,
        provider="google"
    )

    await budget_manager.post_invocation_record(
        allocation_id=decision.allocation_id,
        input_tokens=500,
        output_tokens=300,
        cost_usd=Decimal("0.001"),
        provider="google",
        model="gemini-2.5-pro",
        bill_to="managed:test_budget_123",
    )

    # Verify record exists (check the sorted set)
    records_key = f"llm_budget:{sample_budget.budget_id}:records_by_time"
    record_count = budget_manager.redis.zcard(records_key)
    assert record_count == 1


@pytest.mark.asyncio
async def test_post_record_multiple_calls_aggregate(budget_manager, sample_budget):
    """Test multiple post-invocation calls aggregate correctly"""
    await budget_manager.create_budget(sample_budget)

    # Make three calls
    for i in range(3):
        decision = await budget_manager.pre_invocation_check(
            budget_id=sample_budget.budget_id,
            model="gemini-2.5-flash",
            estimated_tokens=500,
            provider="google"
        )

        await budget_manager.post_invocation_record(
            allocation_id=decision.allocation_id,
            input_tokens=200,
            output_tokens=150,
            cost_usd=Decimal("0.0001"),
            provider="google",
            model="gemini-2.5-flash",
            bill_to="managed:test_budget_123",
        )

    # Verify aggregated spending
    status = await budget_manager.get_budget_status(sample_budget.budget_id)
    assert status.daily_tokens_used == 1050  # 350 * 3
    assert status.monthly_tokens_used == 1050
    assert status.daily_usd_spent == Decimal("0.0003")  # 0.0001 * 3
    assert status.monthly_usd_spent == Decimal("0.0003")


@pytest.mark.asyncio
async def test_post_record_without_allocation(budget_manager, sample_budget):
    """Test post-invocation recording works without pre-allocation"""
    await budget_manager.create_budget(sample_budget)

    # Record without pre-check allocation
    result = await budget_manager.post_invocation_record(
        allocation_id="manual_allocation_id",
        input_tokens=100,
        output_tokens=50,
        cost_usd=Decimal("0.0001"),
        provider="google",
        model="gemini-2.5-flash",
        bill_to="byok:user_key",
    )

    # Should still work but log warning
    assert result is True


# ============================================================================
# Budget Status Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_budget_status_calculates_remaining(budget_manager, sample_budget):
    """Test budget status calculates remaining amounts correctly"""
    await budget_manager.create_budget(sample_budget)

    # Use some budget
    today = date.today().isoformat()
    month = today[:7]
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    monthly_key = f"llm_budget:{sample_budget.budget_id}:monthly:{month}"

    budget_manager.redis.hset(daily_key, "tokens", 3000)
    budget_manager.redis.hset(daily_key, "usd", "1.50")
    budget_manager.redis.hset(monthly_key, "tokens", 15000)
    budget_manager.redis.hset(monthly_key, "usd", "7.50")

    status = await budget_manager.get_budget_status(sample_budget.budget_id)

    assert status.daily_tokens_used == 3000
    assert status.daily_tokens_remaining == 7000
    assert status.daily_usd_spent == Decimal("1.50")
    assert status.daily_usd_remaining == Decimal("3.50")

    assert status.monthly_tokens_used == 15000
    assert status.monthly_tokens_remaining == 85000
    assert status.monthly_usd_spent == Decimal("7.50")
    assert status.monthly_usd_remaining == Decimal("42.50")


@pytest.mark.asyncio
async def test_get_budget_status_no_limits(budget_manager):
    """Test budget status with no limits set"""
    budget = LLMBudget(
        budget_id="unlimited_budget",
        name="Unlimited Budget",
        budget_type=LLMBudgetType.ADVISORY
    )
    await budget_manager.create_budget(budget)

    status = await budget_manager.get_budget_status(budget.budget_id)

    assert status.daily_tokens_limit is None
    assert status.monthly_tokens_limit is None
    assert status.daily_usd_limit is None
    assert status.monthly_usd_limit is None
    assert status.daily_tokens_remaining is None
    assert status.monthly_tokens_remaining is None


# ============================================================================
# Alert Threshold Tests
# ============================================================================


@pytest.mark.asyncio
async def test_alert_triggered_at_threshold(budget_manager, sample_budget):
    """Test alert is triggered when threshold crossed"""
    alert_callback = AsyncMock()
    budget_manager.alert_callback = alert_callback

    await budget_manager.create_budget(sample_budget)

    # Use 85% of daily USD budget (crosses 80% threshold)
    today = date.today().isoformat()
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    budget_manager.redis.hset(daily_key, "usd", "4.25")  # 85% of $5

    # Pre-check should trigger alert
    await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=100,
        provider="google"
    )

    # Verify alert callback was called
    assert alert_callback.called
    call_args = alert_callback.call_args[0][0]
    assert call_args["budget_id"] == sample_budget.budget_id
    assert call_args["threshold"] == 80.0
    assert "daily_usd" in call_args["limit_type"]


@pytest.mark.asyncio
async def test_alert_not_repeated(budget_manager, sample_budget):
    """Test alert is not repeated for same threshold"""
    alert_callback = AsyncMock()
    budget_manager.alert_callback = alert_callback

    await budget_manager.create_budget(sample_budget)

    # Cross threshold
    today = date.today().isoformat()
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"
    budget_manager.redis.hset(daily_key, "usd", "4.25")

    # First check - should alert
    await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=100,
        provider="google"
    )
    first_call_count = alert_callback.call_count

    # Second check - should not alert again
    await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=100,
        provider="google"
    )

    # Call count should not increase
    assert alert_callback.call_count == first_call_count


@pytest.mark.asyncio
async def test_multiple_thresholds_triggered(budget_manager, sample_budget):
    """Test multiple alert thresholds can be triggered"""
    alert_callback = AsyncMock()
    budget_manager.alert_callback = alert_callback

    await budget_manager.create_budget(sample_budget)

    today = date.today().isoformat()
    daily_key = f"llm_budget:{sample_budget.budget_id}:daily:{today}"

    # Cross 50% threshold
    budget_manager.redis.hset(daily_key, "usd", "2.60")
    await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=100,
        provider="google"
    )
    threshold_50_calls = alert_callback.call_count

    # Cross 80% threshold
    budget_manager.redis.hset(daily_key, "usd", "4.10")
    await budget_manager.pre_invocation_check(
        budget_id=sample_budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=100,
        provider="google"
    )

    # Should have triggered both thresholds
    assert alert_callback.call_count > threshold_50_calls


# ============================================================================
# Edge Cases and Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_budget_with_zero_limits(budget_manager):
    """Test budget with zero limits blocks all requests"""
    budget = LLMBudget(
        budget_id="zero_budget",
        name="Zero Budget",
        budget_type=LLMBudgetType.HARD_LIMIT,
        daily_token_limit=0,
        daily_usd_limit=Decimal("0")
    )
    await budget_manager.create_budget(budget)

    decision = await budget_manager.pre_invocation_check(
        budget_id=budget.budget_id,
        model="gemini-2.5-flash",
        estimated_tokens=1,
        provider="google"
    )

    assert decision.approved is False


@pytest.mark.asyncio
async def test_budget_status_empty_redis(budget_manager):
    """Test budget status when no data in Redis yet"""
    budget = LLMBudget(
        budget_id="new_budget",
        name="New Budget",
        budget_type=LLMBudgetType.HARD_LIMIT,
        daily_token_limit=1000
    )
    await budget_manager.create_budget(budget)

    status = await budget_manager.get_budget_status(budget.budget_id)

    assert status.daily_tokens_used == 0
    assert status.daily_usd_spent == Decimal("0")


@pytest.mark.asyncio
async def test_concurrent_budget_checks(budget_manager, sample_budget):
    """Test budget manager handles concurrent checks correctly"""
    await budget_manager.create_budget(sample_budget)

    import asyncio

    # Run multiple concurrent pre-checks
    tasks = [
        budget_manager.pre_invocation_check(
            budget_id=sample_budget.budget_id,
            model="gemini-2.5-flash",
            estimated_tokens=1000,
            provider="google"
        )
        for _ in range(5)
    ]

    results = await asyncio.gather(*tasks)

    # All should be approved (budget is sufficient)
    assert all(r.approved for r in results)
    # All should have unique allocation IDs
    allocation_ids = [r.allocation_id for r in results]
    assert len(allocation_ids) == len(set(allocation_ids))


@pytest.mark.asyncio
async def test_cost_estimation_with_different_providers(budget_manager, sample_budget):
    """Test cost estimation works with different providers"""
    await budget_manager.create_budget(sample_budget)

    providers = ["google", "openai", "anthropic"]
    models = ["gemini-2.5-pro", "gpt-4", "claude-3-sonnet"]

    for provider, model in zip(providers, models):
        decision = await budget_manager.pre_invocation_check(
            budget_id=sample_budget.budget_id,
            model=model,
            estimated_tokens=1000,
            provider=provider
        )

        assert decision.approved is True
        assert decision.allocation_id is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=brain_researcher.services.agent.llm_budget_manager"])
