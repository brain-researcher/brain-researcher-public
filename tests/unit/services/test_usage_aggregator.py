"""Unit tests for LLM usage tracking and aggregation."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from brain_researcher.services.agent.router import LLMRouteMetadata
from brain_researcher.services.agent.usage_aggregator import (
    UsageRecord,
    UsageTracker,
)


@pytest.fixture
def temp_telemetry_dir():
    """Create a temporary directory for telemetry files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def tracker(temp_telemetry_dir):
    """Create a UsageTracker with temp directory."""
    return UsageTracker(telemetry_dir=temp_telemetry_dir)


class TestUsageRecord:
    """Test UsageRecord dataclass."""

    def test_create_record(self):
        """Test creating a usage record."""
        record = UsageRecord(
            timestamp="2025-01-17T12:00:00Z",
            provider="google",
            model="gemini-1.5-flash",
            bill_to="local_oauth",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            estimated_cost=0.0,
        )

        assert record.provider == "google"
        assert record.model == "gemini-1.5-flash"
        assert record.bill_to == "local_oauth"
        assert record.estimated_cost == 0.0

    def test_to_dict_filters_none(self):
        """Test to_dict() filters None values."""
        record = UsageRecord(
            timestamp="2025-01-17T12:00:00Z",
            provider="google",
            model="gemini-1.5-flash",
            workspace_id=None,  # This should be filtered out
        )

        d = record.to_dict()
        assert "workspace_id" not in d
        assert "provider" in d
        assert "model" in d


class TestUsageTracker:
    """Test UsageTracker functionality."""

    def test_initialization(self, temp_telemetry_dir):
        """Test tracker initialization creates directory."""
        tracker = UsageTracker(telemetry_dir=temp_telemetry_dir)
        assert tracker.telemetry_dir.exists()
        assert tracker.usage_file == Path(temp_telemetry_dir) / "llm_usage.ndjson"

    def test_record_usage(self, tracker):
        """Test recording a single usage event."""
        metadata = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            route="primary",
            transport="cli",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            bill_to="local_oauth",
            estimated_cost=0.0,
            latency_ms=1234,
        )

        tracker.record_usage(metadata)

        # Verify file was created and contains the record
        assert tracker.usage_file.exists()
        with open(tracker.usage_file, "r") as f:
            lines = f.readlines()
            assert len(lines) == 1

            record = json.loads(lines[0])
            assert record["provider"] == "google"
            assert record["model"] == "gemini-1.5-flash"
            assert record["bill_to"] == "local_oauth"
            assert record["estimated_cost"] == 0.0
            assert record["usage"]["total_tokens"] == 150

    def test_record_multiple_usage(self, tracker):
        """Test recording multiple usage events."""
        for i in range(5):
            metadata = LLMRouteMetadata(
                provider="google",
                model=f"gemini-1.5-flash",
                usage={"total_tokens": 100 * (i + 1)},
                bill_to="local_oauth",
                estimated_cost=0.0,
            )
            tracker.record_usage(metadata)

        # Verify all records were written
        with open(tracker.usage_file, "r") as f:
            lines = f.readlines()
            assert len(lines) == 5

    def test_record_with_workspace_and_user(self, tracker):
        """Test recording with workspace and user IDs."""
        metadata = LLMRouteMetadata(
            provider="openai",
            model="gpt-4o",
            usage={"total_tokens": 500},
            estimated_cost=0.05,
        )

        tracker.record_usage(metadata, workspace_id="ws-123", user_id="user-456")

        with open(tracker.usage_file, "r") as f:
            record = json.loads(f.read())
            assert record["workspace_id"] == "ws-123"
            assert record["user_id"] == "user-456"

    def test_get_usage_summary_empty(self, tracker):
        """Test summary with no data."""
        summary = tracker.get_usage_summary()

        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost"] == 0.0
        assert summary["by_provider"] == {}
        assert summary["by_model"] == {}
        assert summary["by_bill_to"] == {}
        assert summary["records"] == []

    def test_get_usage_summary_basic(self, tracker):
        """Test basic usage summary."""
        # Record some usage
        metadata1 = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            usage={"total_tokens": 100},
            bill_to="local_oauth",
            estimated_cost=0.0,
        )
        metadata2 = LLMRouteMetadata(
            provider="openai",
            model="gpt-4o",
            usage={"total_tokens": 500},
            bill_to="byok",
            estimated_cost=0.05,
        )

        tracker.record_usage(metadata1)
        tracker.record_usage(metadata2)

        summary = tracker.get_usage_summary()

        assert summary["total_calls"] == 2
        assert summary["total_tokens"] == 600
        assert summary["total_cost"] == 0.05

        # Check provider breakdown
        assert "google" in summary["by_provider"]
        assert "openai" in summary["by_provider"]
        assert summary["by_provider"]["google"]["calls"] == 1
        assert summary["by_provider"]["openai"]["calls"] == 1

    def test_get_usage_summary_with_date_filter(self, tracker):
        """Test summary with date range filter."""
        # Create records with different timestamps
        today = datetime.now().date().isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()

        # Manually write records with specific dates
        with open(tracker.usage_file, "w") as f:
            # Yesterday's record
            record1 = UsageRecord(
                timestamp=f"{yesterday}T12:00:00Z",
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 100},
                estimated_cost=0.0,
            )
            f.write(json.dumps(record1.to_dict()) + "\n")

            # Today's record
            record2 = UsageRecord(
                timestamp=f"{today}T12:00:00Z",
                provider="openai",
                model="gpt-4o",
                usage={"total_tokens": 500},
                estimated_cost=0.05,
            )
            f.write(json.dumps(record2.to_dict()) + "\n")

        # Query only today
        summary = tracker.get_usage_summary(start_date=today, end_date=today)

        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 500
        assert summary["records"][0]["provider"] == "openai"

    def test_get_usage_summary_with_provider_filter(self, tracker):
        """Test summary with provider filter."""
        metadata1 = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            usage={"total_tokens": 100},
            estimated_cost=0.0,
        )
        metadata2 = LLMRouteMetadata(
            provider="openai",
            model="gpt-4o",
            usage={"total_tokens": 500},
            estimated_cost=0.05,
        )

        tracker.record_usage(metadata1)
        tracker.record_usage(metadata2)

        # Filter by provider
        summary = tracker.get_usage_summary(provider="google")

        assert summary["total_calls"] == 1
        assert summary["records"][0]["provider"] == "google"

    def test_get_usage_summary_with_bill_to_filter(self, tracker):
        """Test summary with bill_to filter."""
        metadata1 = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            usage={"total_tokens": 100},
            bill_to="local_oauth",
            estimated_cost=0.0,
        )
        metadata2 = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-pro",
            usage={"total_tokens": 500},
            bill_to="byok",
            estimated_cost=0.05,
        )

        tracker.record_usage(metadata1)
        tracker.record_usage(metadata2)

        # Filter by bill_to
        summary = tracker.get_usage_summary(bill_to="local_oauth")

        assert summary["total_calls"] == 1
        assert summary["records"][0]["bill_to"] == "local_oauth"

    def test_aggregation_by_provider(self, tracker):
        """Test aggregation by provider."""
        # Add multiple records for different providers
        for _ in range(3):
            tracker.record_usage(
                LLMRouteMetadata(
                    provider="google",
                    model="gemini-1.5-flash",
                    usage={"total_tokens": 100},
                    estimated_cost=0.01,
                )
            )

        for _ in range(2):
            tracker.record_usage(
                LLMRouteMetadata(
                    provider="openai",
                    model="gpt-4o",
                    usage={"total_tokens": 200},
                    estimated_cost=0.02,
                )
            )

        summary = tracker.get_usage_summary()

        assert summary["by_provider"]["google"]["calls"] == 3
        assert summary["by_provider"]["google"]["tokens"] == 300
        assert summary["by_provider"]["google"]["cost"] == 0.03

        assert summary["by_provider"]["openai"]["calls"] == 2
        assert summary["by_provider"]["openai"]["tokens"] == 400
        assert summary["by_provider"]["openai"]["cost"] == 0.04

    def test_aggregation_by_model(self, tracker):
        """Test aggregation by model."""
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 100},
                estimated_cost=0.01,
            )
        )
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-pro",
                usage={"total_tokens": 200},
                estimated_cost=0.02,
            )
        )

        summary = tracker.get_usage_summary()

        assert "gemini-1.5-flash" in summary["by_model"]
        assert "gemini-1.5-pro" in summary["by_model"]
        assert summary["by_model"]["gemini-1.5-flash"]["calls"] == 1
        assert summary["by_model"]["gemini-1.5-pro"]["calls"] == 1

    def test_aggregation_by_bill_to(self, tracker):
        """Test aggregation by billing target."""
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 100},
                bill_to="local_oauth",
                estimated_cost=0.0,
            )
        )
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-pro",
                usage={"total_tokens": 200},
                bill_to="byok",
                estimated_cost=0.05,
            )
        )

        summary = tracker.get_usage_summary()

        assert "local_oauth" in summary["by_bill_to"]
        assert "byok" in summary["by_bill_to"]
        assert summary["by_bill_to"]["local_oauth"]["cost"] == 0.0
        assert summary["by_bill_to"]["byok"]["cost"] == 0.05

    def test_get_recent_usage(self, tracker):
        """Test get_recent_usage helper."""
        # Record some usage
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 100},
                estimated_cost=0.0,
            )
        )

        summary = tracker.get_recent_usage(hours=24)

        # Should include today's records
        assert summary["total_calls"] >= 1

    def test_malformed_json_handling(self, tracker):
        """Test that malformed JSON records are skipped."""
        # Write a malformed record
        with open(tracker.usage_file, "w") as f:
            f.write('{"invalid json\n')
            f.write(
                json.dumps(
                    {
                        "timestamp": "2025-01-17T12:00:00Z",
                        "provider": "google",
                        "model": "gemini-1.5-flash",
                        "usage": {"total_tokens": 100},
                        "estimated_cost": 0.0,
                    }
                )
                + "\n"
            )

        summary = tracker.get_usage_summary()

        # Should skip malformed record and process valid one
        assert summary["total_calls"] == 1

    def test_empty_usage_dict(self, tracker):
        """Test recording with empty usage dict."""
        metadata = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            usage={},  # Empty usage
            estimated_cost=0.0,
        )

        tracker.record_usage(metadata)

        summary = tracker.get_usage_summary()
        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 0

    def test_none_values_handling(self, tracker):
        """Test handling None values in metadata."""
        metadata = LLMRouteMetadata(
            provider="google",
            model="gemini-1.5-flash",
            usage={"total_tokens": None},  # None value
            estimated_cost=None,
        )

        tracker.record_usage(metadata)

        summary = tracker.get_usage_summary()
        assert summary["total_calls"] == 1
        assert summary["total_cost"] == 0.0

    def test_workspace_filter(self, tracker):
        """Test filtering by workspace_id."""
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 100},
            ),
            workspace_id="ws-1",
        )
        tracker.record_usage(
            LLMRouteMetadata(
                provider="google",
                model="gemini-1.5-flash",
                usage={"total_tokens": 200},
            ),
            workspace_id="ws-2",
        )

        summary = tracker.get_usage_summary(workspace_id="ws-1")

        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 100

    def test_cost_rounding(self, tracker):
        """Test that total cost is properly rounded."""
        # Add records with small costs that might have floating point issues
        for _ in range(10):
            tracker.record_usage(
                LLMRouteMetadata(
                    provider="google",
                    model="gemini-1.5-flash",
                    usage={"total_tokens": 100},
                    estimated_cost=0.0001,  # Small cost
                )
            )

        summary = tracker.get_usage_summary()

        # Should be properly rounded to 4 decimal places
        assert summary["total_cost"] == 0.001  # 10 * 0.0001 = 0.001
        assert isinstance(summary["total_cost"], float)
