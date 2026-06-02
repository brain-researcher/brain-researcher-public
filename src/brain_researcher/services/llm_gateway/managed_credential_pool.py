"""
Managed Credential Pool for Brain Researcher

This module manages a pool of managed (platform-provided) LLM credentials
that can be allocated to budgets/workspaces for shared usage:
- Credential registration and pool management
- Allocation to specific budgets with tracking
- Load balancing across multiple credentials
- Credential rotation and deallocation
"""

import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Shared singleton for managed credentials
_shared_managed_pool: Optional["ManagedCredentialPool"] = None
_shared_managed_pool_lock = threading.Lock()


class CredentialStatus(Enum):
    """Managed credential status"""

    AVAILABLE = "available"
    ALLOCATED = "allocated"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class ManagedCredential:
    """Managed credential with budget association"""

    credential_id: str
    provider: str  # "gemini", "openai", "anthropic"
    api_key: str

    # Budget association
    budget_ids: List[str] = field(
        default_factory=list
    )  # Budgets allowed to use this credential

    # Status
    status: CredentialStatus = CredentialStatus.AVAILABLE

    # Allocation tracking
    current_allocations: int = 0  # Number of active allocations
    max_concurrent_allocations: int = 10  # Max simultaneous uses
    total_allocations: int = 0  # Lifetime allocation count

    # Rate limiting (optional, enforced at pool level)
    rate_limit_rpm: Optional[int] = None  # Requests per minute
    rate_limit_rpd: Optional[int] = None  # Requests per day

    # Metadata
    name: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)

    # Tracking
    last_allocated_at: Optional[datetime] = None
    last_released_at: Optional[datetime] = None


@dataclass
class CredentialAllocation:
    """Tracks an active allocation of a managed credential"""

    allocation_id: str
    credential_id: str
    budget_id: str
    model: str

    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    released: bool = False
    released_at: Optional[datetime] = None


class ManagedCredentialPool:
    """
    Manages a pool of managed credentials that can be shared across budgets.

    Provides allocation, load balancing, and tracking for managed LLM credentials.
    """

    def __init__(self):
        """Initialize the managed credential pool"""
        self._credentials: Dict[str, ManagedCredential] = {}
        self._allocations: Dict[str, CredentialAllocation] = {}
        self._lock = threading.Lock()

        logger.info("ManagedCredentialPool initialized")

    def register_managed_credential(
        self,
        credential_id: str,
        provider: str,
        api_key: str,
        budget_ids: Optional[List[str]] = None,
        name: Optional[str] = None,
        max_concurrent_allocations: int = 10,
        rate_limit_rpm: Optional[int] = None,
        rate_limit_rpd: Optional[int] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Register a managed credential in the pool.

        Args:
            credential_id: Unique credential identifier
            provider: Provider name ("gemini", "openai", etc.)
            api_key: API key value
            budget_ids: List of budget IDs allowed to use this credential
            name: Human-readable name
            max_concurrent_allocations: Max simultaneous allocations
            rate_limit_rpm: Requests per minute limit
            rate_limit_rpd: Requests per day limit
            tags: Additional metadata tags

        Returns:
            True if registered successfully
        """
        try:
            with self._lock:
                if credential_id in self._credentials:
                    logger.warning(
                        f"Credential {credential_id} already registered, updating"
                    )

                credential = ManagedCredential(
                    credential_id=credential_id,
                    provider=provider,
                    api_key=api_key,
                    budget_ids=budget_ids or [],
                    name=name,
                    max_concurrent_allocations=max_concurrent_allocations,
                    rate_limit_rpm=rate_limit_rpm,
                    rate_limit_rpd=rate_limit_rpd,
                    tags=tags or {},
                )

                self._credentials[credential_id] = credential

                logger.info(
                    f"Registered managed credential {credential_id} ({provider}) "
                    f"for budgets: {budget_ids or 'all'}"
                )

                return True

        except Exception as e:
            logger.error(f"Failed to register credential {credential_id}: {e}")
            return False

    def unregister_credential(self, credential_id: str) -> bool:
        """
        Unregister a credential from the pool.

        Args:
            credential_id: Credential to remove

        Returns:
            True if removed successfully
        """
        try:
            with self._lock:
                if credential_id not in self._credentials:
                    logger.warning(f"Credential {credential_id} not found")
                    return False

                credential = self._credentials[credential_id]

                # Check for active allocations
                if credential.current_allocations > 0:
                    logger.error(
                        f"Cannot unregister {credential_id}: {credential.current_allocations} "
                        "active allocations"
                    )
                    return False

                del self._credentials[credential_id]
                logger.info(f"Unregistered credential {credential_id}")

                return True

        except Exception as e:
            logger.error(f"Failed to unregister credential {credential_id}: {e}")
            return False

    def get_credential(
        self,
        budget_id: str,
        model_hint: Optional[str] = None,
        provider_hint: Optional[str] = None,
    ) -> Optional[ManagedCredential]:
        """
        Allocate a managed credential for a budget.

        Args:
            budget_id: Budget requesting the credential
            model_hint: Model name hint for provider selection
            provider_hint: Explicit provider hint ("gemini", "openai")

        Returns:
            ManagedCredential if available, None otherwise
        """
        try:
            with self._lock:
                # Determine provider from hints
                target_provider = provider_hint
                if not target_provider and model_hint:
                    target_provider = self._infer_provider(model_hint)

                # Find available credentials for this budget and provider
                candidates = []
                for cred_id, cred in self._credentials.items():
                    # Check status
                    if cred.status != CredentialStatus.AVAILABLE:
                        continue

                    # Check provider match
                    if target_provider and cred.provider != target_provider:
                        continue

                    # Check budget authorization
                    if cred.budget_ids and budget_id not in cred.budget_ids:
                        continue

                    # Check capacity
                    if cred.current_allocations >= cred.max_concurrent_allocations:
                        continue

                    candidates.append(cred)

                if not candidates:
                    logger.warning(
                        f"No managed credentials available for budget {budget_id}, "
                        f"provider={target_provider}"
                    )
                    return None

                # Select credential with least allocations (load balancing)
                selected = min(candidates, key=lambda c: c.current_allocations)

                # Create allocation
                allocation_id = str(uuid.uuid4())
                allocation = CredentialAllocation(
                    allocation_id=allocation_id,
                    credential_id=selected.credential_id,
                    budget_id=budget_id,
                    model=model_hint or "unknown",
                )

                # Update credential state
                selected.current_allocations += 1
                selected.total_allocations += 1
                selected.last_allocated_at = datetime.now(timezone.utc)

                # Store allocation
                self._allocations[allocation_id] = allocation

                logger.debug(
                    f"Allocated credential {selected.credential_id} to budget {budget_id} "
                    f"(allocation {allocation_id}, {selected.current_allocations}/"
                    f"{selected.max_concurrent_allocations} active)"
                )

                # Return copy with allocation_id embedded in metadata
                result = ManagedCredential(
                    credential_id=selected.credential_id,
                    provider=selected.provider,
                    api_key=selected.api_key,
                    budget_ids=selected.budget_ids,
                    status=selected.status,
                    name=selected.name,
                    tags={**selected.tags, "allocation_id": allocation_id},
                )

                return result

        except Exception as e:
            logger.error(f"Failed to allocate credential for budget {budget_id}: {e}")
            return None

    def release_credential(self, allocation_id: str) -> bool:
        """
        Release a credential allocation.

        Args:
            allocation_id: Allocation to release

        Returns:
            True if released successfully
        """
        try:
            with self._lock:
                if allocation_id not in self._allocations:
                    logger.warning(f"Allocation {allocation_id} not found")
                    return False

                allocation = self._allocations[allocation_id]

                if allocation.released:
                    logger.warning(f"Allocation {allocation_id} already released")
                    return True

                # Find credential
                credential = self._credentials.get(allocation.credential_id)
                if not credential:
                    logger.error(
                        f"Credential {allocation.credential_id} not found for allocation "
                        f"{allocation_id}"
                    )
                    return False

                # Update credential state
                credential.current_allocations = max(
                    0, credential.current_allocations - 1
                )
                credential.last_released_at = datetime.now(timezone.utc)

                # Mark allocation as released
                allocation.released = True
                allocation.released_at = datetime.now(timezone.utc)

                logger.debug(
                    f"Released credential {credential.credential_id} allocation {allocation_id} "
                    f"({credential.current_allocations}/{credential.max_concurrent_allocations} "
                    "remaining)"
                )

                return True

        except Exception as e:
            logger.error(f"Failed to release allocation {allocation_id}: {e}")
            return False

    def get_pool_status(self) -> Dict[str, Any]:
        """
        Get status of the credential pool.

        Returns:
            Dictionary with pool statistics
        """
        with self._lock:
            total_credentials = len(self._credentials)
            available_credentials = sum(
                1
                for c in self._credentials.values()
                if c.status == CredentialStatus.AVAILABLE
                and c.current_allocations < c.max_concurrent_allocations
            )

            active_allocations = sum(
                1 for a in self._allocations.values() if not a.released
            )

            by_provider = {}
            for cred in self._credentials.values():
                if cred.provider not in by_provider:
                    by_provider[cred.provider] = {
                        "total": 0,
                        "available": 0,
                        "allocations": 0,
                    }

                by_provider[cred.provider]["total"] += 1
                if (
                    cred.status == CredentialStatus.AVAILABLE
                    and cred.current_allocations < cred.max_concurrent_allocations
                ):
                    by_provider[cred.provider]["available"] += 1
                by_provider[cred.provider]["allocations"] += cred.current_allocations

            return {
                "total_credentials": total_credentials,
                "available_credentials": available_credentials,
                "active_allocations": active_allocations,
                "total_allocations": len(self._allocations),
                "by_provider": by_provider,
            }

    def get_credential_status(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific credential.

        Args:
            credential_id: Credential to query

        Returns:
            Credential status dict or None
        """
        with self._lock:
            credential = self._credentials.get(credential_id)
            if not credential:
                return None

            return {
                "credential_id": credential.credential_id,
                "provider": credential.provider,
                "status": credential.status.value,
                "budget_ids": credential.budget_ids,
                "current_allocations": credential.current_allocations,
                "max_concurrent_allocations": credential.max_concurrent_allocations,
                "total_allocations": credential.total_allocations,
                "name": credential.name,
                "last_allocated_at": (
                    credential.last_allocated_at.isoformat()
                    if credential.last_allocated_at
                    else None
                ),
                "last_released_at": (
                    credential.last_released_at.isoformat()
                    if credential.last_released_at
                    else None
                ),
                "tags": credential.tags,
            }

    def update_credential_budgets(
        self, credential_id: str, budget_ids: List[str]
    ) -> bool:
        """
        Update which budgets can use a credential.

        Args:
            credential_id: Credential to update
            budget_ids: New list of authorized budget IDs

        Returns:
            True if updated successfully
        """
        try:
            with self._lock:
                credential = self._credentials.get(credential_id)
                if not credential:
                    logger.error(f"Credential {credential_id} not found")
                    return False

                credential.budget_ids = budget_ids

                logger.info(
                    f"Updated budget authorization for credential {credential_id}: {budget_ids}"
                )

                return True

        except Exception as e:
            logger.error(
                f"Failed to update credential budgets for {credential_id}: {e}"
            )
            return False

    def suspend_credential(self, credential_id: str) -> bool:
        """
        Suspend a credential (prevent new allocations).

        Args:
            credential_id: Credential to suspend

        Returns:
            True if suspended successfully
        """
        try:
            with self._lock:
                credential = self._credentials.get(credential_id)
                if not credential:
                    logger.error(f"Credential {credential_id} not found")
                    return False

                credential.status = CredentialStatus.SUSPENDED

                logger.info(f"Suspended credential {credential_id}")

                return True

        except Exception as e:
            logger.error(f"Failed to suspend credential {credential_id}: {e}")
            return False

    def resume_credential(self, credential_id: str) -> bool:
        """
        Resume a suspended credential.

        Args:
            credential_id: Credential to resume

        Returns:
            True if resumed successfully
        """
        try:
            with self._lock:
                credential = self._credentials.get(credential_id)
                if not credential:
                    logger.error(f"Credential {credential_id} not found")
                    return False

                if credential.status != CredentialStatus.SUSPENDED:
                    logger.warning(
                        f"Credential {credential_id} is not suspended "
                        f"(status: {credential.status.value})"
                    )
                    return False

                credential.status = CredentialStatus.AVAILABLE

                logger.info(f"Resumed credential {credential_id}")

                return True

        except Exception as e:
            logger.error(f"Failed to resume credential {credential_id}: {e}")
            return False

    @staticmethod
    def _infer_provider(model: str) -> Optional[str]:
        """Infer provider from model name"""
        model_lower = model.lower()

        if "gemini" in model_lower or "palm" in model_lower:
            return "gemini"
        elif "gpt" in model_lower or "davinci" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"

        return None


# ---- Shared factory ----------------------------------------------------------


def get_shared_managed_pool() -> "ManagedCredentialPool":
    """Process-local singleton managed credential pool.

    Seeds the pool from environment variables if provided:
      MANAGED_GEMINI_API_KEY, MANAGED_OPENAI_API_KEY
      Optional: MANAGED_BUDGET_IDS (comma list) to restrict budgets
    """

    global _shared_managed_pool
    if _shared_managed_pool is not None:
        return _shared_managed_pool

    with _shared_managed_pool_lock:
        if _shared_managed_pool is not None:
            return _shared_managed_pool

        pool = ManagedCredentialPool()

        budget_ids_env = os.getenv("MANAGED_BUDGET_IDS", "").strip()
        budget_ids = (
            [b.strip() for b in budget_ids_env.split(",") if b.strip()]
            if budget_ids_env
            else []
        )

        gem_key = os.getenv("MANAGED_GEMINI_API_KEY")
        if gem_key:
            pool.register_managed_credential(
                credential_id="managed_gemini_default",
                provider="gemini",
                api_key=gem_key,
                budget_ids=budget_ids or None,
                name="managed_gemini_default",
            )

        openai_key = os.getenv("MANAGED_OPENAI_API_KEY")
        if openai_key:
            pool.register_managed_credential(
                credential_id="managed_openai_default",
                provider="openai",
                api_key=openai_key,
                budget_ids=budget_ids or None,
                name="managed_openai_default",
            )

        _shared_managed_pool = pool
        return _shared_managed_pool
