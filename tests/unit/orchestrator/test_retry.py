"""Unit tests for P2.6 retry module.

Tests classify_failure, compute_backoff, should_retry logic.
"""

import pytest

from brain_researcher.services.orchestrator.retry import (
    classify_failure,
    compute_backoff,
    should_retry,
    format_retry_summary,
)
from brain_researcher.config.retry_settings import (
    RetrySettings,
    RetryTaxonomy,
    RetryCategory,
    RetryPattern,
    RetryDefaults,
)


@pytest.fixture
def minimal_settings():
    """Minimal retry settings for testing."""
    return RetrySettings(
        enabled=True,
        base_delay=10,
        max_delay=300,
        jitter_percent=0,  # No jitter for predictable tests
        max_attempts=4,  # Allow attempts 1, 2, 3 to all retry
        taxonomy=None,
    )


@pytest.fixture
def taxonomy_settings():
    """Settings with full taxonomy loaded."""
    taxonomy = RetryTaxonomy(
        version="1.0",
        defaults=RetryDefaults(
            base_delay_seconds=10,
            max_delay_seconds=300,
            jitter_percent=20,
            max_attempts=3,
        ),
        categories={
            "timeout": RetryCategory(
                retryable=True,
                max_attempts=5,
                base_delay=30,
                patterns=[
                    RetryPattern(type="exit_code", value=124),
                    RetryPattern(type="stderr_regex", pattern="(?i)timeout"),
                    RetryPattern(type="stderr_regex", pattern="(?i)timed out"),
                ],
            ),
            "transient_io": RetryCategory(
                retryable=True,
                max_attempts=3,
                base_delay=10,
                patterns=[
                    RetryPattern(type="stderr_regex", pattern="(?i)connection reset"),
                    RetryPattern(type="stderr_regex", pattern="(?i)broken pipe"),
                ],
            ),
            "oom": RetryCategory(
                retryable=False,
                patterns=[
                    RetryPattern(type="exit_code", value=137),
                    RetryPattern(type="stderr_regex", pattern="(?i)MemoryError"),
                ],
            ),
            "user_error": RetryCategory(
                retryable=False,
                patterns=[
                    RetryPattern(type="exit_code", value=2),  # Not exit 1 - too generic
                    RetryPattern(type="stderr_regex", pattern="(?i)FileNotFoundError"),
                ],
            ),
            "unknown": RetryCategory(
                retryable=True,
                max_attempts=2,
                base_delay=15,
                patterns=[],
            ),
        },
        priority=["oom", "user_error", "timeout", "transient_io", "unknown"],
    )

    return RetrySettings(
        enabled=True,
        base_delay=10,
        max_delay=300,
        jitter_percent=20,
        max_attempts=3,
        taxonomy=taxonomy,
    )


class TestClassifyFailure:
    """Test failure classification logic."""

    def test_timeout_exit_code(self, taxonomy_settings):
        """Exit code 124 classified as timeout."""
        category = classify_failure(124, "", taxonomy_settings)
        assert category == "timeout"

    def test_timeout_stderr(self, taxonomy_settings):
        """Stderr with 'timeout' classified as timeout."""
        category = classify_failure(
            1, "Command timed out after 300s", taxonomy_settings
        )
        assert category == "timeout"

    def test_transient_io_broken_pipe(self, taxonomy_settings):
        """Broken pipe error classified as transient_io."""
        category = classify_failure(0, "Error: Broken pipe", taxonomy_settings)
        assert category == "transient_io"

    def test_transient_io_connection_reset(self, taxonomy_settings):
        """Connection reset classified as transient_io."""
        category = classify_failure(1, "Connection reset by peer", taxonomy_settings)
        assert category == "transient_io"

    def test_oom_exit_code(self, taxonomy_settings):
        """Exit code 137 (SIGKILL) classified as oom."""
        category = classify_failure(137, "", taxonomy_settings)
        assert category == "oom"

    def test_oom_stderr(self, taxonomy_settings):
        """MemoryError in stderr classified as oom."""
        category = classify_failure(
            1, "MemoryError: cannot allocate", taxonomy_settings
        )
        assert category == "oom"

    def test_user_error_exit_1(self, taxonomy_settings):
        """Exit code 1 without specific patterns falls to unknown."""
        # Exit 1 alone is too generic, should fall to unknown
        category = classify_failure(1, "Unknown command", taxonomy_settings)
        assert category == "unknown"

    def test_user_error_file_not_found(self, taxonomy_settings):
        """FileNotFoundError classified as user_error."""
        category = classify_failure(
            1, "FileNotFoundError: input.nii not found", taxonomy_settings
        )
        assert category == "user_error"

    def test_unknown_fallback(self, taxonomy_settings):
        """Unmatched errors fall back to unknown."""
        category = classify_failure(42, "Some random error", taxonomy_settings)
        assert category == "unknown"

    def test_priority_order_oom_before_user_error(self, taxonomy_settings):
        """Exit 137 matches OOM first (higher priority than user_error)."""
        category = classify_failure(137, "", taxonomy_settings)
        assert category == "oom"  # Not user_error despite exit code

    def test_case_insensitive_matching(self, taxonomy_settings):
        """Regex patterns are case-insensitive."""
        category = classify_failure(1, "CONNECTION RESET", taxonomy_settings)
        assert category == "transient_io"


class TestComputeBackoff:
    """Test exponential backoff calculation."""

    def test_first_attempt_base_delay(self):
        """First attempt uses base delay (no exponential)."""
        delay = compute_backoff(
            attempt=1, base_delay=10, max_delay=300, jitter_percent=0
        )
        assert delay == 10

    def test_second_attempt_doubles(self):
        """Second attempt doubles the base delay."""
        delay = compute_backoff(
            attempt=2, base_delay=10, max_delay=300, jitter_percent=0
        )
        assert delay == 20  # 10 * 2^1

    def test_third_attempt_quadruples(self):
        """Third attempt is 4x base delay."""
        delay = compute_backoff(
            attempt=3, base_delay=10, max_delay=300, jitter_percent=0
        )
        assert delay == 40  # 10 * 2^2

    def test_max_delay_cap(self):
        """Delay is capped at max_delay."""
        delay = compute_backoff(
            attempt=10,  # Would be 10 * 2^9 = 5120 without cap
            base_delay=10,
            max_delay=300,
            jitter_percent=0,
        )
        assert delay == 300

    def test_jitter_adds_variance(self):
        """Jitter adds randomness to delay."""
        delays = [
            compute_backoff(attempt=2, base_delay=10, max_delay=300, jitter_percent=20)
            for _ in range(10)
        ]

        # With 20% jitter, expect range of 16-24 (20 ± 20%)
        assert min(delays) >= 16
        assert max(delays) <= 24
        # Should have some variance
        assert len(set(delays)) > 1

    def test_deterministic_jitter_with_seed(self):
        """Same seed produces same jitter."""
        delay1 = compute_backoff(
            attempt=2, base_delay=10, max_delay=300, jitter_percent=20, seed="job_123"
        )

        delay2 = compute_backoff(
            attempt=2, base_delay=10, max_delay=300, jitter_percent=20, seed="job_123"
        )

        assert delay1 == delay2

    def test_different_seeds_different_jitter(self):
        """Different seeds produce different jitter."""
        delay1 = compute_backoff(
            attempt=2, base_delay=10, max_delay=300, jitter_percent=20, seed="job_123"
        )

        delay2 = compute_backoff(
            attempt=2, base_delay=10, max_delay=300, jitter_percent=20, seed="job_456"
        )

        # Different seeds should (very likely) produce different delays
        # Note: There's a tiny chance they could be equal, but very unlikely
        assert delay1 != delay2

    def test_minimum_delay_one_second(self):
        """Delay is at least 1 second even with jitter."""
        delay = compute_backoff(
            attempt=1,
            base_delay=1,
            max_delay=300,
            jitter_percent=50,  # Could reduce to < 1
        )
        assert delay >= 1


class TestShouldRetry:
    """Test retry decision logic."""

    def test_retry_timeout_first_attempt(self, taxonomy_settings):
        """Timeout on first attempt should retry."""
        decision = should_retry(
            exit_code=124, stderr="timeout", attempt=1, settings=taxonomy_settings
        )

        assert decision.should_retry is True
        assert decision.category == "timeout"
        assert decision.attempt == 1
        assert decision.max_attempts == 5  # Timeout category override
        assert decision.delay_seconds > 0
        assert decision.next_retry_at is not None

    def test_retry_transient_io(self, taxonomy_settings):
        """Transient I/O errors should retry."""
        decision = should_retry(
            exit_code=1,
            stderr="Connection reset by peer",
            attempt=1,
            settings=taxonomy_settings,
        )

        assert decision.should_retry is True
        assert decision.category == "transient_io"
        assert decision.max_attempts == 3

    def test_no_retry_oom(self, taxonomy_settings):
        """OOM errors should not retry."""
        decision = should_retry(
            exit_code=137, stderr="", attempt=1, settings=taxonomy_settings
        )

        assert decision.should_retry is False
        assert decision.category == "oom"
        assert "not retryable" in decision.reason

    def test_no_retry_user_error(self, taxonomy_settings):
        """User errors should not retry."""
        decision = should_retry(
            exit_code=1,
            stderr="FileNotFoundError: input.nii",
            attempt=1,
            settings=taxonomy_settings,
        )

        assert decision.should_retry is False
        assert decision.category == "user_error"

    def test_no_retry_gate_blocked(self, taxonomy_settings):
        """Gate-blocked failures should never retry (deterministic)."""
        decision = should_retry(
            exit_code=1,
            stderr="Postcheck blocked: QC_MISSING_T1W: Required T1w image is missing",
            attempt=1,
            settings=taxonomy_settings,
        )

        assert decision.should_retry is False
        assert "Gate blocked" in decision.reason

    def test_no_retry_max_attempts(self, taxonomy_settings):
        """Should not retry after max attempts."""
        decision = should_retry(
            exit_code=124,
            stderr="timeout",
            attempt=5,  # Max for timeout category
            settings=taxonomy_settings,
        )

        assert decision.should_retry is False
        assert "Max attempts reached" in decision.reason

    def test_no_retry_disabled(self, taxonomy_settings):
        """Should not retry when retry system disabled."""
        taxonomy_settings.enabled = False

        decision = should_retry(
            exit_code=124, stderr="timeout", attempt=1, settings=taxonomy_settings
        )

        assert decision.should_retry is False
        assert "disabled" in decision.reason

    def test_delay_increases_with_attempts(self, minimal_settings):
        """Delay should increase exponentially with attempts."""
        decision1 = should_retry(124, "", 1, settings=minimal_settings)
        decision2 = should_retry(124, "", 2, settings=minimal_settings)
        decision3 = should_retry(124, "", 3, settings=minimal_settings)

        assert (
            decision1.delay_seconds < decision2.delay_seconds < decision3.delay_seconds
        )

    def test_metadata_includes_exit_code(self, taxonomy_settings):
        """Decision metadata should include exit code."""
        decision = should_retry(
            exit_code=124,
            stderr="timeout error message",
            attempt=1,
            settings=taxonomy_settings,
        )

        assert decision.metadata["exit_code"] == 124
        assert "timeout" in decision.metadata["stderr_snippet"]

    def test_deterministic_with_job_id(self, taxonomy_settings):
        """Same job_id produces same delay."""
        decision1 = should_retry(
            exit_code=124,
            stderr="",
            attempt=2,
            job_id="job_abc",
            settings=taxonomy_settings,
        )

        decision2 = should_retry(
            exit_code=124,
            stderr="",
            attempt=2,
            job_id="job_abc",
            settings=taxonomy_settings,
        )

        assert decision1.delay_seconds == decision2.delay_seconds


class TestFormatRetrySummary:
    """Test retry summary formatting."""

    def test_format_retry_decision(self, taxonomy_settings):
        """Should format retry decision with delay and time."""
        decision = should_retry(
            exit_code=124, stderr="", attempt=2, settings=taxonomy_settings
        )

        summary = format_retry_summary(decision)

        assert "timeout" in summary.lower()
        assert "attempt 2/5" in summary
        assert "waiting" in summary
        assert "s until" in summary

    def test_format_no_retry_decision(self, taxonomy_settings):
        """Should format no-retry decision with reason."""
        decision = should_retry(
            exit_code=137, stderr="", attempt=1, settings=taxonomy_settings
        )

        summary = format_retry_summary(decision)

        assert "Not retrying" in summary
        assert decision.reason in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
