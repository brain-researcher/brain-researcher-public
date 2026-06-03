"""
LLM usage tracking and aggregation.

Records each LLM invocation to NDJSON telemetry and provides aggregation
utilities for billing/usage reporting.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_data_root
from brain_researcher.services.agent.router import LLMRouteMetadata


@dataclass
class UsageRecord:
    """Single LLM usage record for telemetry."""

    timestamp: str  # ISO 8601 timestamp
    provider: str
    model: str
    bill_to: str | None = None
    usage: dict[str, Any] = None  # prompt_tokens, completion_tokens, total_tokens
    estimated_cost: float | None = None
    latency_ms: int | None = None
    fallback_reason: str | None = None
    route: str = "primary"
    transport: str = "sdk"
    credential: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, filtering None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class UsageTracker:
    """
    Tracks LLM usage to NDJSON files and provides aggregation queries.

    Storage format: BR_TELEMETRY_DIR/llm_usage.ndjson
    """

    def __init__(self, telemetry_dir: str | None = None):
        """
        Initialize usage tracker.

        Args:
            telemetry_dir: Directory for NDJSON files (defaults to BR_TELEMETRY_DIR or <repo>/data/agent_outputs/sessions)
        """
        if telemetry_dir is None:
            telemetry_dir = os.environ.get(
                "BR_TELEMETRY_DIR",
            ) or str(get_data_root() / "agent_outputs" / "sessions")

        self.telemetry_dir = Path(telemetry_dir).expanduser()
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)

        # Usage file path
        self.usage_file = self.telemetry_dir / "llm_usage.ndjson"

    def record_usage(
        self,
        metadata: LLMRouteMetadata,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """
        Record an LLM invocation to NDJSON.

        Args:
            metadata: LLMRouteMetadata from router
            workspace_id: Optional workspace identifier
            user_id: Optional user identifier
        """
        record = UsageRecord(
            timestamp=datetime.utcnow().isoformat() + "Z",
            provider=metadata.provider,
            model=metadata.model,
            bill_to=metadata.bill_to,
            usage=metadata.usage or {},
            estimated_cost=metadata.estimated_cost,
            latency_ms=metadata.latency_ms,
            fallback_reason=metadata.fallback_reason,
            route=metadata.route,
            transport=metadata.transport,
            credential=metadata.credential,
            workspace_id=workspace_id,
            user_id=user_id,
        )

        # Append to NDJSON
        with open(self.usage_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def get_usage_summary(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        provider: str | None = None,
        bill_to: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Aggregate usage records within a date range.

        Args:
            start_date: ISO date string (YYYY-MM-DD) or None for no lower bound
            end_date: ISO date string (YYYY-MM-DD) or None for no upper bound
            provider: Filter by provider (e.g., "google", "openai")
            bill_to: Filter by billing target (e.g., "local_oauth", "byok")
            workspace_id: Filter by workspace

        Returns:
            Dict with aggregated metrics:
            {
                "total_calls": int,
                "total_tokens": int,
                "total_cost": float,
                "by_provider": {provider: {...}},
                "by_model": {model: {...}},
                "by_bill_to": {bill_to: {...}},
                "records": [...]  # Matching records
            }
        """
        if not self.usage_file.exists():
            return self._empty_summary()

        # Parse date filters
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", ""))
        if end_date:
            # End of day
            end_dt = datetime.fromisoformat(end_date.replace("Z", "")) + timedelta(
                days=1
            )

        # Scan NDJSON and filter
        matching_records = []
        with open(self.usage_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)

                    # Date filter
                    record_dt = datetime.fromisoformat(
                        record["timestamp"].replace("Z", "")
                    )
                    if start_dt and record_dt < start_dt:
                        continue
                    if end_dt and record_dt >= end_dt:
                        continue

                    # Provider filter
                    if provider and record.get("provider") != provider:
                        continue

                    # Bill-to filter
                    if bill_to and record.get("bill_to") != bill_to:
                        continue

                    # Workspace filter
                    if workspace_id and record.get("workspace_id") != workspace_id:
                        continue

                    matching_records.append(record)

                except (json.JSONDecodeError, KeyError):
                    continue  # Skip malformed records

        return self._aggregate_records(matching_records)

    def _empty_summary(self) -> dict[str, Any]:
        """Return empty summary structure."""
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_provider": {},
            "by_model": {},
            "by_bill_to": {},
            "records": [],
        }

    def _aggregate_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate a list of usage records."""
        total_calls = len(records)
        total_tokens = 0
        total_cost = 0.0

        by_provider: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        by_bill_to: dict[str, dict[str, Any]] = {}

        for record in records:
            usage = record.get("usage", {})
            tokens = usage.get("total_tokens", 0) or 0
            cost = record.get("estimated_cost", 0.0) or 0.0

            total_tokens += tokens
            total_cost += cost

            # By provider
            provider = record.get("provider", "unknown")
            if provider not in by_provider:
                by_provider[provider] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_provider[provider]["calls"] += 1
            by_provider[provider]["tokens"] += tokens
            by_provider[provider]["cost"] += cost

            # By model
            model = record.get("model", "unknown")
            if model not in by_model:
                by_model[model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_model[model]["calls"] += 1
            by_model[model]["tokens"] += tokens
            by_model[model]["cost"] += cost

            # By bill_to
            bill_to_val = record.get("bill_to") or "unknown"
            if bill_to_val not in by_bill_to:
                by_bill_to[bill_to_val] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_bill_to[bill_to_val]["calls"] += 1
            by_bill_to[bill_to_val]["tokens"] += tokens
            by_bill_to[bill_to_val]["cost"] += cost

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "by_provider": by_provider,
            "by_model": by_model,
            "by_bill_to": by_bill_to,
            "records": records,
        }

    def get_recent_usage(self, hours: int = 24) -> dict[str, Any]:
        """
        Get usage for the last N hours.

        Args:
            hours: Number of hours to look back (default: 24)

        Returns:
            Aggregated usage summary
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        start_date = start_time.date().isoformat()
        end_date = end_time.date().isoformat()

        return self.get_usage_summary(start_date=start_date, end_date=end_date)
