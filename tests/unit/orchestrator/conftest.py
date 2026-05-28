"""
Pytest configuration for orchestrator tests.

Provides fixtures and hooks for test isolation.
"""

import pytest
from brain_researcher.config.retry_settings import clear_settings_cache


@pytest.fixture(autouse=True)
def reset_retry_settings_cache():
    """Clear retry settings cache after each test to ensure test isolation.

    This fixture runs automatically after every test to prevent settings
    cache pollution between tests. This is especially important when tests
    modify BR_RETRY_ENABLED or other retry configuration via monkeypatch.
    """
    yield  # Run the test
    clear_settings_cache()  # Clean up after the test
