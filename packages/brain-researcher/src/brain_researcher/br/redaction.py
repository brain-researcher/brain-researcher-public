"""Stable namespace: log/payload scrubbing for outbound disclosure.

Single source of truth for what gets redacted before crossing the
public-facing boundary; the rules implemented by
`brain_researcher.services.shared.log_scrubber` are documented in
`REDACTION_POLICY.md`.
"""

from brain_researcher.services.shared.log_scrubber import scrub_data, scrub_text

__all__ = ["scrub_data", "scrub_text"]
