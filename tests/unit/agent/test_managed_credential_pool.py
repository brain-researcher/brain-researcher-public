"""
Unit tests for Managed Credential Pool

Tests credential registration, allocation, release, load balancing,
budget authorization, and pool management.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from brain_researcher.services.agent.managed_credential_pool import (
    ManagedCredential,
    CredentialAllocation,
    ManagedCredentialPool,
    CredentialStatus,
)


@pytest.fixture
def credential_pool():
    """Provide a fresh credential pool instance"""
    return ManagedCredentialPool()


@pytest.fixture
def sample_gemini_credential():
    """Provide sample Gemini credential data"""
    return {
        "credential_id": "gemini_cred_1",
        "provider": "gemini",
        "api_key": "test_gemini_key_12345",
        "budget_ids": ["budget_1", "budget_2"],
        "name": "Test Gemini Credential",
        "max_concurrent_allocations": 5,
    }


@pytest.fixture
def sample_openai_credential():
    """Provide sample OpenAI credential data"""
    return {
        "credential_id": "openai_cred_1",
        "provider": "openai",
        "api_key": "test_openai_key_67890",
        "budget_ids": ["budget_3"],
        "name": "Test OpenAI Credential",
        "max_concurrent_allocations": 3,
    }


# ============================================================================
# Credential Registration Tests
# ============================================================================


def test_register_credential_success(credential_pool, sample_gemini_credential):
    """Test successful credential registration"""
    result = credential_pool.register_managed_credential(**sample_gemini_credential)

    assert result is True

    # Verify credential is in pool
    assert "gemini_cred_1" in credential_pool._credentials
    cred = credential_pool._credentials["gemini_cred_1"]
    assert cred.provider == "gemini"
    assert cred.api_key == "test_gemini_key_12345"
    assert cred.budget_ids == ["budget_1", "budget_2"]
    assert cred.status == CredentialStatus.AVAILABLE


def test_register_multiple_credentials(credential_pool, sample_gemini_credential, sample_openai_credential):
    """Test registering multiple credentials"""
    result1 = credential_pool.register_managed_credential(**sample_gemini_credential)
    result2 = credential_pool.register_managed_credential(**sample_openai_credential)

    assert result1 is True
    assert result2 is True
    assert len(credential_pool._credentials) == 2


def test_register_credential_update_existing(credential_pool, sample_gemini_credential):
    """Test updating an existing credential"""
    # Register initial
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Update with new budget IDs
    updated = sample_gemini_credential.copy()
    updated["budget_ids"] = ["budget_1", "budget_2", "budget_3"]

    result = credential_pool.register_managed_credential(**updated)

    assert result is True
    cred = credential_pool._credentials["gemini_cred_1"]
    assert cred.budget_ids == ["budget_1", "budget_2", "budget_3"]


def test_register_credential_with_rate_limits(credential_pool):
    """Test registering credential with rate limits"""
    result = credential_pool.register_managed_credential(
        credential_id="rate_limited_cred",
        provider="gemini",
        api_key="test_key",
        rate_limit_rpm=100,
        rate_limit_rpd=10000,
    )

    assert result is True
    cred = credential_pool._credentials["rate_limited_cred"]
    assert cred.rate_limit_rpm == 100
    assert cred.rate_limit_rpd == 10000


def test_register_credential_with_tags(credential_pool):
    """Test registering credential with metadata tags"""
    result = credential_pool.register_managed_credential(
        credential_id="tagged_cred",
        provider="gemini",
        api_key="test_key",
        tags={"environment": "production", "region": "us-west-1"}
    )

    assert result is True
    cred = credential_pool._credentials["tagged_cred"]
    assert cred.tags["environment"] == "production"
    assert cred.tags["region"] == "us-west-1"


# ============================================================================
# Credential Allocation Tests
# ============================================================================


def test_get_credential_success(credential_pool, sample_gemini_credential):
    """Test successful credential allocation"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    allocated_cred = credential_pool.get_credential(
        budget_id="budget_1",
        model_hint="gemini-2.5-pro"
    )

    assert allocated_cred is not None
    assert allocated_cred.provider == "gemini"
    assert allocated_cred.api_key == "test_gemini_key_12345"
    assert "allocation_id" in allocated_cred.tags


def test_get_credential_updates_allocation_count(credential_pool, sample_gemini_credential):
    """Test allocation increments current_allocations"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate once
    cred1 = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")

    # Check internal state
    internal_cred = credential_pool._credentials["gemini_cred_1"]
    assert internal_cred.current_allocations == 1
    assert internal_cred.total_allocations == 1

    # Allocate again
    cred2 = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")

    assert internal_cred.current_allocations == 2
    assert internal_cred.total_allocations == 2


def test_get_credential_none_for_unauthorized_budget(credential_pool, sample_gemini_credential):
    """Test credential not allocated to unauthorized budget"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    allocated_cred = credential_pool.get_credential(
        budget_id="unauthorized_budget",  # Not in budget_ids
        model_hint="gemini-2.5-pro"
    )

    assert allocated_cred is None


def test_get_credential_provider_matching(credential_pool, sample_gemini_credential, sample_openai_credential):
    """Test credential allocation matches provider"""
    credential_pool.register_managed_credential(**sample_gemini_credential)
    credential_pool.register_managed_credential(**sample_openai_credential)

    # Request Gemini model - should get Gemini credential
    gemini_cred = credential_pool.get_credential(
        budget_id="budget_1",
        model_hint="gemini-2.5-flash"
    )
    assert gemini_cred.provider == "gemini"

    # Request OpenAI model - should get OpenAI credential
    openai_cred = credential_pool.get_credential(
        budget_id="budget_3",
        model_hint="gpt-4"
    )
    assert openai_cred.provider == "openai"


def test_get_credential_none_when_max_allocations_reached(credential_pool, sample_gemini_credential):
    """Test credential not allocated when max concurrent reached"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate up to max
    for i in range(5):  # max_concurrent_allocations = 5
        cred = credential_pool.get_credential(
            budget_id="budget_1",
            model_hint="gemini-2.5-pro"
        )
        assert cred is not None

    # Try to allocate beyond max
    cred = credential_pool.get_credential(
        budget_id="budget_1",
        model_hint="gemini-2.5-pro"
    )
    assert cred is None


def test_get_credential_none_when_suspended(credential_pool, sample_gemini_credential):
    """Test credential not allocated when suspended"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Suspend credential
    credential_pool.suspend_credential("gemini_cred_1")

    # Try to allocate
    cred = credential_pool.get_credential(
        budget_id="budget_1",
        model_hint="gemini-2.5-pro"
    )

    assert cred is None


def test_get_credential_load_balancing(credential_pool):
    """Test load balancing across multiple credentials"""
    # Register two credentials for same budget
    credential_pool.register_managed_credential(
        credential_id="gemini_cred_1",
        provider="gemini",
        api_key="key1",
        budget_ids=["budget_1"],
        max_concurrent_allocations=10,
    )
    credential_pool.register_managed_credential(
        credential_id="gemini_cred_2",
        provider="gemini",
        api_key="key2",
        budget_ids=["budget_1"],
        max_concurrent_allocations=10,
    )

    # First allocation should go to credential with least allocations (both at 0, so first)
    cred1 = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    allocation_id_1 = cred1.tags["allocation_id"]

    # Internal state
    internal_1 = credential_pool._credentials["gemini_cred_1"]
    internal_2 = credential_pool._credentials["gemini_cred_2"]

    # One should have 1 allocation, other should have 0
    total_allocations = internal_1.current_allocations + internal_2.current_allocations
    assert total_allocations == 1

    # Next allocation should balance
    cred2 = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")

    # Both should now have 1 allocation each
    assert internal_1.current_allocations == 1
    assert internal_2.current_allocations == 1


def test_get_credential_explicit_provider_hint(credential_pool, sample_gemini_credential):
    """Test allocation with explicit provider hint"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    cred = credential_pool.get_credential(
        budget_id="budget_1",
        provider_hint="gemini"
    )

    assert cred is not None
    assert cred.provider == "gemini"


def test_get_credential_with_empty_budget_ids(credential_pool):
    """Test credential with empty budget_ids allows all budgets"""
    credential_pool.register_managed_credential(
        credential_id="public_cred",
        provider="gemini",
        api_key="public_key",
        budget_ids=[],  # Empty = allow all
    )

    # Should work for any budget
    cred1 = credential_pool.get_credential(budget_id="any_budget_1", model_hint="gemini-2.5-pro")
    cred2 = credential_pool.get_credential(budget_id="any_budget_2", model_hint="gemini-2.5-pro")

    assert cred1 is not None
    assert cred2 is not None


# ============================================================================
# Credential Release Tests
# ============================================================================


def test_release_credential_success(credential_pool, sample_gemini_credential):
    """Test successful credential release"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate
    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    allocation_id = cred.tags["allocation_id"]

    # Release
    result = credential_pool.release_credential(allocation_id)

    assert result is True

    # Check internal state
    internal_cred = credential_pool._credentials["gemini_cred_1"]
    assert internal_cred.current_allocations == 0


def test_release_credential_decrements_count(credential_pool, sample_gemini_credential):
    """Test release decrements allocation count"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate three times
    allocation_ids = []
    for i in range(3):
        cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
        allocation_ids.append(cred.tags["allocation_id"])

    internal_cred = credential_pool._credentials["gemini_cred_1"]
    assert internal_cred.current_allocations == 3

    # Release one
    credential_pool.release_credential(allocation_ids[0])
    assert internal_cred.current_allocations == 2

    # Release another
    credential_pool.release_credential(allocation_ids[1])
    assert internal_cred.current_allocations == 1


def test_release_credential_idempotent(credential_pool, sample_gemini_credential):
    """Test releasing same allocation twice is safe"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    allocation_id = cred.tags["allocation_id"]

    # Release twice
    result1 = credential_pool.release_credential(allocation_id)
    result2 = credential_pool.release_credential(allocation_id)

    assert result1 is True
    assert result2 is True  # Should not error


def test_release_credential_nonexistent_allocation(credential_pool):
    """Test releasing nonexistent allocation"""
    result = credential_pool.release_credential("fake_allocation_id")

    assert result is False


def test_release_allows_new_allocation(credential_pool, sample_gemini_credential):
    """Test releasing credential allows new allocation"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Fill up to max
    allocation_ids = []
    for i in range(5):
        cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
        allocation_ids.append(cred.tags["allocation_id"])

    # Should be full
    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    assert cred is None

    # Release one
    credential_pool.release_credential(allocation_ids[0])

    # Should now be able to allocate again
    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    assert cred is not None


# ============================================================================
# Pool Management Tests
# ============================================================================


def test_unregister_credential_success(credential_pool, sample_gemini_credential):
    """Test successful credential unregistration"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    result = credential_pool.unregister_credential("gemini_cred_1")

    assert result is True
    assert "gemini_cred_1" not in credential_pool._credentials


def test_unregister_credential_with_active_allocations_fails(credential_pool, sample_gemini_credential):
    """Test cannot unregister credential with active allocations"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate
    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")

    # Try to unregister
    result = credential_pool.unregister_credential("gemini_cred_1")

    assert result is False
    assert "gemini_cred_1" in credential_pool._credentials


def test_unregister_nonexistent_credential(credential_pool):
    """Test unregistering nonexistent credential"""
    result = credential_pool.unregister_credential("fake_cred_id")

    assert result is False


def test_suspend_credential_success(credential_pool, sample_gemini_credential):
    """Test suspending credential"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    result = credential_pool.suspend_credential("gemini_cred_1")

    assert result is True

    cred = credential_pool._credentials["gemini_cred_1"]
    assert cred.status == CredentialStatus.SUSPENDED


def test_resume_credential_success(credential_pool, sample_gemini_credential):
    """Test resuming suspended credential"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    credential_pool.suspend_credential("gemini_cred_1")
    result = credential_pool.resume_credential("gemini_cred_1")

    assert result is True

    cred = credential_pool._credentials["gemini_cred_1"]
    assert cred.status == CredentialStatus.AVAILABLE


def test_resume_non_suspended_credential_fails(credential_pool, sample_gemini_credential):
    """Test resuming non-suspended credential"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    result = credential_pool.resume_credential("gemini_cred_1")

    assert result is False


def test_update_credential_budgets_success(credential_pool, sample_gemini_credential):
    """Test updating credential budget authorization"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    new_budgets = ["budget_1", "budget_2", "budget_3", "budget_4"]
    result = credential_pool.update_credential_budgets("gemini_cred_1", new_budgets)

    assert result is True

    cred = credential_pool._credentials["gemini_cred_1"]
    assert cred.budget_ids == new_budgets


# ============================================================================
# Pool Status Tests
# ============================================================================


def test_get_pool_status(credential_pool, sample_gemini_credential, sample_openai_credential):
    """Test getting pool status"""
    credential_pool.register_managed_credential(**sample_gemini_credential)
    credential_pool.register_managed_credential(**sample_openai_credential)

    # Allocate some
    credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
    credential_pool.get_credential(budget_id="budget_3", model_hint="gpt-4")

    status = credential_pool.get_pool_status()

    assert status["total_credentials"] == 2
    assert status["active_allocations"] == 2
    assert "by_provider" in status
    assert "gemini" in status["by_provider"]
    assert "openai" in status["by_provider"]


def test_get_credential_status(credential_pool, sample_gemini_credential):
    """Test getting specific credential status"""
    credential_pool.register_managed_credential(**sample_gemini_credential)

    # Allocate
    cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")

    status = credential_pool.get_credential_status("gemini_cred_1")

    assert status is not None
    assert status["credential_id"] == "gemini_cred_1"
    assert status["provider"] == "gemini"
    assert status["current_allocations"] == 1
    assert status["total_allocations"] == 1
    assert status["last_allocated_at"] is not None


def test_get_credential_status_nonexistent(credential_pool):
    """Test getting status of nonexistent credential"""
    status = credential_pool.get_credential_status("fake_cred_id")

    assert status is None


# ============================================================================
# Provider Inference Tests
# ============================================================================


def test_infer_provider_gemini(credential_pool):
    """Test provider inference for Gemini models"""
    assert credential_pool._infer_provider("gemini-2.5-pro") == "gemini"
    assert credential_pool._infer_provider("gemini-1.5-flash") == "gemini"
    assert credential_pool._infer_provider("palm-2") == "gemini"


def test_infer_provider_openai(credential_pool):
    """Test provider inference for OpenAI models"""
    assert credential_pool._infer_provider("gpt-4") == "openai"
    assert credential_pool._infer_provider("gpt-3.5-turbo") == "openai"
    assert credential_pool._infer_provider("davinci") == "openai"


def test_infer_provider_anthropic(credential_pool):
    """Test provider inference for Anthropic models"""
    assert credential_pool._infer_provider("claude-3-opus") == "anthropic"
    assert credential_pool._infer_provider("claude-2") == "anthropic"


def test_infer_provider_unknown(credential_pool):
    """Test provider inference for unknown models"""
    assert credential_pool._infer_provider("unknown-model") is None


# ============================================================================
# Thread Safety Tests
# ============================================================================


def test_concurrent_allocations_thread_safe(credential_pool, sample_gemini_credential):
    """Test concurrent allocations are thread-safe"""
    import threading

    credential_pool.register_managed_credential(**sample_gemini_credential)

    allocations = []
    errors = []

    def allocate():
        try:
            cred = credential_pool.get_credential(budget_id="budget_1", model_hint="gemini-2.5-pro")
            if cred:
                allocations.append(cred.tags["allocation_id"])
        except Exception as e:
            errors.append(e)

    # Create multiple threads
    threads = [threading.Thread(target=allocate) for _ in range(10)]

    # Start all threads
    for t in threads:
        t.start()

    # Wait for all to complete
    for t in threads:
        t.join()

    # No errors should occur
    assert len(errors) == 0

    # Should have allocated up to max (5)
    assert len(allocations) <= 5

    # All allocation IDs should be unique
    assert len(allocations) == len(set(allocations))


# ============================================================================
# Edge Cases
# ============================================================================


def test_empty_pool(credential_pool):
    """Test operations on empty pool"""
    cred = credential_pool.get_credential(budget_id="any_budget", model_hint="gemini-2.5-pro")
    assert cred is None

    status = credential_pool.get_pool_status()
    assert status["total_credentials"] == 0
    assert status["active_allocations"] == 0


def test_credential_with_no_budget_restriction(credential_pool):
    """Test credential accessible to all budgets"""
    credential_pool.register_managed_credential(
        credential_id="unrestricted_cred",
        provider="gemini",
        api_key="test_key",
        budget_ids=[],  # Empty list = no restriction
    )

    # Should work for any budget
    cred1 = credential_pool.get_credential(budget_id="random_budget_1", model_hint="gemini-2.5-pro")
    cred2 = credential_pool.get_credential(budget_id="random_budget_2", model_hint="gemini-2.5-pro")

    assert cred1 is not None
    assert cred2 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=brain_researcher.services.agent.managed_credential_pool"])
