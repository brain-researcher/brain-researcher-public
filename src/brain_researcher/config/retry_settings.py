"""Retry settings configuration for P2.6 Shared Retry/Backoff Taxonomy.

This module provides configuration management for the retry system, including:
- Loading settings from environment variables
- Loading retry taxonomy from YAML
- Caching settings in app state
- Pydantic models for type safety
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class RetryPattern(BaseModel):
    """A single pattern for matching errors to categories."""

    type: str  # exit_code or stderr_regex
    value: int | None = None  # For exit_code patterns
    pattern: str | None = None  # For stderr_regex patterns

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("exit_code", "stderr_regex"):
            raise ValueError(
                f"Pattern type must be 'exit_code' or 'stderr_regex', got: {v}"
            )
        return v

    def matches(self, exit_code: int, stderr: str) -> bool:
        """Check if this pattern matches the given error."""
        if self.type == "exit_code":
            return exit_code == self.value
        elif self.type == "stderr_regex":
            return bool(re.search(self.pattern, stderr, re.IGNORECASE))
        return False


class RetryCategory(BaseModel):
    """Configuration for a specific error category."""

    retryable: bool
    max_attempts: int | None = None  # Overrides default if set
    base_delay: int | None = None  # Overrides default if set
    max_delay: int | None = None  # Overrides default if set
    description: str = ""
    patterns: list[RetryPattern] = Field(default_factory=list)

    def matches(self, exit_code: int, stderr: str) -> bool:
        """Check if any pattern in this category matches."""
        return any(pattern.matches(exit_code, stderr) for pattern in self.patterns)


class RetryDefaults(BaseModel):
    """Default retry settings."""

    base_delay_seconds: int = 10
    max_delay_seconds: int = 300
    jitter_percent: int = 20
    max_attempts: int = 3


class RetryTaxonomy(BaseModel):
    """Complete retry taxonomy from YAML."""

    version: str
    defaults: RetryDefaults
    categories: dict[str, RetryCategory]
    priority: list[str] = Field(default_factory=list)

    def classify_error(self, exit_code: int, stderr: str) -> str:
        """Classify an error based on exit code and stderr.

        Args:
            exit_code: Process exit code
            stderr: Standard error output

        Returns:
            Category name (e.g., 'timeout', 'transient_io', 'unknown')
        """
        stderr = stderr or ""

        # Check categories in priority order
        for category_name in self.priority:
            category = self.categories.get(category_name)
            if category and category.matches(exit_code, stderr):
                return category_name

        # Fallback to unknown
        return "unknown"


class RetrySettings(BaseModel):
    """Global retry settings combining env vars and taxonomy."""

    enabled: bool = Field(default=True)
    base_delay: int = Field(default=10)  # Seconds
    max_delay: int = Field(default=300)  # Seconds
    jitter_percent: int = Field(default=20)  # Percent
    max_attempts: int = Field(default=3)  # Global default
    taxonomy: RetryTaxonomy | None = None

    @classmethod
    def from_env_and_yaml(cls, yaml_path: Path | None = None) -> "RetrySettings":
        """Load settings from environment variables and YAML file.

        Args:
            yaml_path: Path to retry_taxonomy.yaml. If None, uses default location.

        Returns:
            Configured RetrySettings instance
        """
        # Load from environment
        enabled = os.getenv("BR_RETRY_ENABLED", "true").lower() == "true"
        base_delay = int(os.getenv("BR_RETRY_BASE_DELAY", "10"))
        max_delay = int(os.getenv("BR_RETRY_MAX_DELAY", "300"))
        jitter_percent = int(os.getenv("BR_RETRY_JITTER_PERCENT", "20"))
        max_attempts = int(os.getenv("BR_RETRY_MAX_ATTEMPTS", "3"))

        # Load taxonomy from YAML
        if yaml_path is None:
            # Default location: configs/retry_taxonomy.yaml
            project_root = Path(__file__).parent.parent.parent
            yaml_path = project_root / "configs" / "retry_taxonomy.yaml"

        taxonomy = None
        if yaml_path.exists():
            try:
                with open(yaml_path) as f:
                    yaml_data = yaml.safe_load(f)
                    taxonomy = RetryTaxonomy(**yaml_data)

                    # Override global defaults from YAML if not set in env
                    if "BR_RETRY_BASE_DELAY" not in os.environ:
                        base_delay = taxonomy.defaults.base_delay_seconds
                    if "BR_RETRY_MAX_DELAY" not in os.environ:
                        max_delay = taxonomy.defaults.max_delay_seconds
                    if "BR_RETRY_JITTER_PERCENT" not in os.environ:
                        jitter_percent = taxonomy.defaults.jitter_percent
                    if "BR_RETRY_MAX_ATTEMPTS" not in os.environ:
                        max_attempts = taxonomy.defaults.max_attempts

            except Exception as e:
                # Log error but don't fail - use defaults
                import logging

                logging.warning(f"Failed to load retry taxonomy from {yaml_path}: {e}")

        return cls(
            enabled=enabled,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter_percent=jitter_percent,
            max_attempts=max_attempts,
            taxonomy=taxonomy,
        )

    def get_category_settings(self, category: str) -> dict[str, Any]:
        """Get retry settings for a specific category.

        Args:
            category: Category name from taxonomy

        Returns:
            Dict with max_attempts, base_delay, max_delay for this category
        """
        if not self.taxonomy or category not in self.taxonomy.categories:
            # Use global defaults
            return {
                "max_attempts": self.max_attempts,
                "base_delay": self.base_delay,
                "max_delay": self.max_delay,
            }

        cat = self.taxonomy.categories[category]
        return {
            "max_attempts": cat.max_attempts or self.max_attempts,
            "base_delay": cat.base_delay or self.base_delay,
            "max_delay": cat.max_delay or self.max_delay,
        }

    def is_retryable(self, category: str) -> bool:
        """Check if a category is retryable.

        Args:
            category: Category name from taxonomy

        Returns:
            True if category allows retries
        """
        if not self.taxonomy or category not in self.taxonomy.categories:
            # Unknown categories are retryable by default (conservative)
            return True

        return self.taxonomy.categories[category].retryable


# Global cache for settings (populated by get_retry_settings)
_retry_settings_cache: RetrySettings | None = None


def get_retry_settings(reload: bool = False) -> RetrySettings:
    """Get cached retry settings or load from env/YAML.

    This is the primary way to access retry settings. Settings are cached
    globally to avoid repeated file reads.

    Args:
        reload: If True, force reload from disk (default: False)

    Returns:
        RetrySettings instance

    Example:
        >>> settings = get_retry_settings()
        >>> if settings.enabled:
        ...     category = settings.taxonomy.classify_error(exit_code=124, stderr="timeout")
        ...     print(f"Classified as: {category}")
    """
    global _retry_settings_cache

    if _retry_settings_cache is None or reload:
        _retry_settings_cache = RetrySettings.from_env_and_yaml()

    return _retry_settings_cache


def clear_settings_cache():
    """Clear the global settings cache.

    Useful for testing or when configuration files change.
    """
    global _retry_settings_cache
    _retry_settings_cache = None
