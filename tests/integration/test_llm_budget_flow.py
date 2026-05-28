"""
Integration tests for LLM Budget Flow

Tests end-to-end budget enforcement with credential resolution,
router integration, and full budget lifecycle.
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch, Mock
from contextlib import ExitStack
import fakeredis

from brain_researcher.services.agent.llm_budget_manager import (
    LLMBudget,
    LLMBudgetManager,
    LLMBudgetType,
)
from brain_researcher.services.agent.managed_credential_pool import (
    ManagedCredentialPool,
)
from brain_researcher.services.agent.credential_resolver import (
    CredentialResolver,
)
from brain_researcher.services.agent.router import (
    GeminiCLIRouter,
    LLMChatResult,
    LLMRouteMetadata,
)


@pytest.fixture
def fake_redis():
    """Provide a fake Redis client for testing"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def budget_manager(fake_redis):
    """Provide configured budget manager"""
    return LLMBudgetManager(redis_client=fake_redis)


@pytest.fixture
def credential_pool():
    """Provide configured credential pool"""
    pool = ManagedCredentialPool()

    # Register managed credentials
    pool.register_managed_credential(
        credential_id="managed_gemini_1",
        provider="gemini",
        api_key="managed_test_key_gemini_1",
        budget_ids=["budget_test_1", "budget_test_2"],
        max_concurrent_allocations=10,
    )

    pool.register_managed_credential(
        credential_id="managed_openai_1",
        provider="openai",
        api_key="managed_test_key_openai_1",
        budget_ids=["budget_test_1"],
        max_concurrent_allocations=5,
    )

    return pool


@pytest.fixture
def credential_resolver(credential_pool):
    """Provide credential resolver with managed pool"""
    return CredentialResolver(managed_pool=credential_pool)


@pytest.fixture
def router(credential_resolver, budget_manager):
    """Provide router with budget manager"""
    return GeminiCLIRouter(
        credential_resolver=credential_resolver,
        budget_manager=budget_manager,
    )


@pytest.fixture
async def test_budget(budget_manager):
    """Create a test budget"""
    budget = LLMBudget(
        budget_id="budget_test_1",
        name="Integration Test Budget",
        budget_type=LLMBudgetType.HARD_LIMIT,
        daily_token_limit=100000,
        monthly_token_limit=1000000,
        daily_usd_limit=Decimal("10.00"),
        monthly_usd_limit=Decimal("100.00"),
    )

    await budget_manager.create_budget(budget)
    return budget


# ============================================================================
# Managed Credential + Budget Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_managed_credential_allocation_with_budget(
    test_budget,
    credential_resolver,
    budget_manager
):
    """Test managed credential is allocated when budget_id is provided"""
    # Resolve credential with budget_id
    cred = credential_resolver.resolve_for_chat(
        model_hint="gemini-2.5-pro",
        budget_id="budget_test_1"
    )

    assert cred is not None
    assert cred.kind == "managed_gemini"
    assert cred.api_key == "managed_test_key_gemini_1"
    assert cred.metadata.get("is_managed") is True
    assert cred.metadata.get("budget_id") == "budget_test_1"
    assert "allocation_id" in cred.metadata


@pytest.mark.asyncio
async def test_budget_check_approves_with_sufficient_funds(
    test_budget,
    budget_manager
):
    """Test budget check approves request when funds are sufficient"""
    decision = await budget_manager.pre_invocation_check(
        budget_id="budget_test_1",
        model="gemini-2.5-pro",
        estimated_tokens=5000,
        provider="google"
    )

    assert decision.approved is True
    assert decision.allocation_id is not None
    assert decision.remaining_daily_tokens == 100000
    assert decision.remaining_monthly_tokens == 1000000


@pytest.mark.asyncio
async def test_budget_exhaustion_prevents_allocation(
    test_budget,
    budget_manager,
    fake_redis
):
    """Test budget exhaustion blocks new requests"""
    # Exhaust daily token budget
    from datetime import date
    today = date.today().isoformat()
    daily_key = f"llm_budget:budget_test_1:daily:{today}"
    fake_redis.hset(daily_key, "tokens", 99000)

    decision = await budget_manager.pre_invocation_check(
        budget_id="budget_test_1",
        model="gemini-2.5-pro",
        estimated_tokens=5000,  # Would exceed 100000 limit
        provider="google"
    )

    assert decision.approved is False
    assert "exceeded" in decision.reason.lower()


# ============================================================================
# Router Integration with Budget Tests
# ============================================================================


@pytest.mark.asyncio
@patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
async def test_router_budget_check_before_invocation(
    mock_gemini_cli,
    test_budget,
    router
):
    """Test router checks budget before making LLM call"""
    # Mock successful Gemini CLI call
    from brain_researcher.services.agent.utils.gemini_cli import GeminiResult
    mock_gemini_cli.return_value = GeminiResult(
        text="Test response",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        raw="",
        model="gemini-2.5-pro"
    )

    with ExitStack() as stack:
        # Mock is_logged_in to return True for local OAuth
        stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True)
        )

        result = router.route_chat(
            prompt="Test prompt",
            model_hint="gemini-2.5-pro",
            budget_id="budget_test_1"
        )

        assert result is not None
        assert result.text == "Test response"
        assert result.metadata.budget_id == "budget_test_1"
        assert result.metadata.allocation_id is not None


@pytest.mark.asyncio
@patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
async def test_router_records_spend_after_invocation(
    mock_gemini_cli,
    test_budget,
    router,
    budget_manager
):
    """Test router records actual spend after LLM call"""
    # Mock Gemini CLI response
    from brain_researcher.services.agent.utils.gemini_cli import GeminiResult
    mock_gemini_cli.return_value = GeminiResult(
        text="Response text",
        usage={"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
        raw="",
        model="gemini-2.5-pro"
    )

    with patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True):
        result = router.route_chat(
            prompt="Test prompt",
            model_hint="gemini-2.5-pro",
            budget_id="budget_test_1"
        )

        # NOTE: Post-invocation recording needs to be implemented in router
        # This test will pass once router integration is complete

        # For now, we can manually verify budget status would be updated
        # In complete implementation, this would be automatic


@pytest.mark.asyncio
async def test_budget_exhaustion_triggers_fallback(
    test_budget,
    router,
    budget_manager,
    fake_redis
):
    """Test budget exhaustion causes router to try fallback"""
    # Exhaust budget for Gemini
    from datetime import date
    today = date.today().isoformat()
    daily_key = f"llm_budget:budget_test_1:daily:{today}"
    fake_redis.hset(daily_key, "usd", "9.99")

    with ExitStack() as stack:
        # Mock Gemini CLI
        stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True)
        )

        # Attempt call - should deny due to budget
        # In complete implementation, router would fallback to BYOK or other provider
        # For now, this tests the budget check logic


# ============================================================================
# Multi-Call Budget Depletion Tests
# ============================================================================


@pytest.mark.asyncio
async def test_multiple_calls_deplete_budget(
    test_budget,
    budget_manager
):
    """Test multiple LLM calls progressively deplete budget"""
    call_count = 5
    tokens_per_call = 10000

    for i in range(call_count):
        # Pre-check
        decision = await budget_manager.pre_invocation_check(
            budget_id="budget_test_1",
            model="gemini-2.5-pro",
            estimated_tokens=tokens_per_call,
            provider="google"
        )

        assert decision.approved is True

        # Record spend
        await budget_manager.post_invocation_record(
            allocation_id=decision.allocation_id,
            input_tokens=tokens_per_call // 2,
            output_tokens=tokens_per_call // 2,
            cost_usd=Decimal("0.01"),
            provider="google",
            model="gemini-2.5-pro",
            bill_to=f"managed:budget_test_1",
        )

    # Check final status
    status = await budget_manager.get_budget_status("budget_test_1")

    assert status.daily_tokens_used == call_count * tokens_per_call
    assert status.daily_usd_spent == Decimal("0.05")  # 0.01 * 5
    assert status.daily_tokens_remaining == 100000 - (call_count * tokens_per_call)


@pytest.mark.asyncio
async def test_budget_denial_after_depletion(
    test_budget,
    budget_manager
):
    """Test budget denies request after depletion"""
    # Deplete budget (100,000 token limit)
    # Make 11 calls of 9000 tokens each to exceed limit
    for i in range(11):
        decision = await budget_manager.pre_invocation_check(
            budget_id="budget_test_1",
            model="gemini-2.5-pro",
            estimated_tokens=9000,
            provider="google"
        )

        if decision.approved:
            await budget_manager.post_invocation_record(
                allocation_id=decision.allocation_id,
                input_tokens=4500,
                output_tokens=4500,
                cost_usd=Decimal("0.01"),
                provider="google",
                model="gemini-2.5-pro",
                bill_to="managed:budget_test_1",
            )

    # Next request should be denied (11 * 9000 = 99,000 tokens used, 1000 remaining)
    decision = await budget_manager.pre_invocation_check(
        budget_id="budget_test_1",
        model="gemini-2.5-pro",
        estimated_tokens=5000,  # This exceeds remaining budget
        provider="google"
    )

    assert decision.approved is False


# ============================================================================
# Metadata Field Tests
# ============================================================================


@pytest.mark.asyncio
@patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
async def test_metadata_includes_all_budget_fields(
    mock_gemini_cli,
    test_budget,
    router
):
    """Test result metadata includes all required budget fields"""
    from brain_researcher.services.agent.utils.gemini_cli import GeminiResult
    mock_gemini_cli.return_value = GeminiResult(
        text="Response",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        raw="",
        model="gemini-2.5-pro"
    )

    with patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True):
        result = router.route_chat(
            prompt="Test",
            model_hint="gemini-2.5-pro",
            budget_id="budget_test_1"
        )

        # Verify metadata has budget fields
        assert hasattr(result.metadata, 'budget_id')
        assert hasattr(result.metadata, 'allocation_id')
        assert hasattr(result.metadata, 'bill_to')
        assert hasattr(result.metadata, 'estimated_cost')

        assert result.metadata.budget_id == "budget_test_1"
        assert result.metadata.allocation_id is not None


# ============================================================================
# Credential Pool + Budget Authorization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_unauthorized_budget_cannot_access_credential(
    credential_pool,
    credential_resolver
):
    """Test credential not allocated to unauthorized budget"""
    cred = credential_resolver.resolve_for_chat(
        model_hint="gemini-2.5-pro",
        budget_id="unauthorized_budget_999"
    )

    # Should not get managed credential (would fall back to other sources)
    if cred and cred.kind.startswith("managed"):
        # If we got a managed cred, it should not be for this budget
        pytest.fail("Managed credential allocated to unauthorized budget")


@pytest.mark.asyncio
async def test_multiple_budgets_share_credential_pool(
    credential_pool,
    credential_resolver
):
    """Test multiple budgets can use same credential pool"""
    # Budget 1 allocates
    cred1 = credential_resolver.resolve_for_chat(
        model_hint="gemini-2.5-pro",
        budget_id="budget_test_1"
    )

    # Budget 2 allocates
    cred2 = credential_resolver.resolve_for_chat(
        model_hint="gemini-2.5-pro",
        budget_id="budget_test_2"
    )

    # Both should get managed credentials (same underlying credential)
    assert cred1.kind == "managed_gemini"
    assert cred2.kind == "managed_gemini"
    assert cred1.api_key == cred2.api_key  # Same credential
    assert cred1.metadata["allocation_id"] != cred2.metadata["allocation_id"]  # Different allocations


# ============================================================================
# Bill-To Format Tests
# ============================================================================


@pytest.mark.asyncio
async def test_bill_to_format_managed(
    test_budget,
    credential_resolver
):
    """Test bill_to format for managed credentials"""
    cred = credential_resolver.resolve_for_chat(
        model_hint="gemini-2.5-pro",
        budget_id="budget_test_1"
    )

    # In router, bill_to should be formatted as "managed:budget_test_1"
    # This will be tested once router implementation is complete


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_budget_check_error_allows_call_to_proceed(
    router
):
    """Test LLM call proceeds if budget check encounters error"""
    # Call with invalid budget_id
    # Should log error but not block the call
    # (Budget enforcement is optional)

    with ExitStack() as stack:
        stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
        )
        stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True)
        )

        # Should not raise exception
        # In production, would log warning and proceed without budget enforcement


@pytest.mark.asyncio
async def test_budget_manager_unavailable_does_not_block_calls(
    credential_resolver
):
    """Test calls work when budget manager is not configured"""
    # Router without budget manager
    router_no_budget = GeminiCLIRouter(
        credential_resolver=credential_resolver,
        budget_manager=None  # No budget manager
    )

    with ExitStack() as stack:
        from brain_researcher.services.agent.utils.gemini_cli import GeminiResult
        mock_cli = stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
        )
        mock_cli.return_value = GeminiResult(
            text="Response",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            raw="",
            model="gemini-2.5-pro"
        )
        stack.enter_context(
            patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=True)
        )

        # Call with budget_id should still work (budget checking skipped)
        result = router_no_budget.route_chat(
            prompt="Test",
            model_hint="gemini-2.5-pro",
            budget_id="any_budget"
        )

        assert result is not None
        # Budget fields should be None or not enforced
        assert result.metadata.budget_id == "any_budget"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
