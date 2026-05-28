"""Policy reference contract (v1)."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field


class PolicyRefV1(BaseModel):
    """Reference to the policy that governed a run/event."""

    schema_version: Literal["policy-ref-v1"] = "policy-ref-v1"

    policy_id: str | None = Field(default=None, description="Policy identifier")
    policy_hash: str | None = Field(
        default=None, description="Checksum in the form sha256:<hex> when available"
    )
    policy_source: str | None = Field(
        default=None, description="Where the policy came from (file/env/url)"
    )
    thresholds: dict[str, Any] | None = Field(
        default=None, description="Optional thresholds used by the policy"
    )
    notes: str | None = Field(default=None, description="Human-readable notes")


def build_policy_ref_v1() -> PolicyRefV1:
    """Best-effort default policy reference from environment.

    The platform may not have a fully centralized policy system yet; this helper
    ensures a stable, non-empty object for downstream correlation.
    """
    policy_id = (
        os.getenv("BR_POLICY_ID")
        or os.getenv("POLICY_ID")
        or os.getenv("BR_POLICY")
        or "default"
    )
    policy_hash = os.getenv("BR_POLICY_HASH") or os.getenv("BR_POLICY_SHA256")
    policy_source = os.getenv("BR_POLICY_SOURCE")
    return PolicyRefV1(
        policy_id=policy_id,
        policy_hash=policy_hash,
        policy_source=policy_source,
    )


__all__ = ["PolicyRefV1", "build_policy_ref_v1"]

