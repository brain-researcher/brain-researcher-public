"""
Enhanced credential resolver for multi-source LLM authentication.

Supports five credential types:
1. managed_gemini: Platform-managed Gemini credentials (budget-controlled)
2. managed_openai: Platform-managed OpenAI credentials (budget-controlled)
3. local_gemini: OAuth via installed Gemini CLI (free credits)
4. byok_gemini: User-provided Gemini API key
5. byok_openai: User-provided OpenAI API key

Credentials are resolved in priority order with fallback support.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import gemini_cli

if TYPE_CHECKING:
    from .managed_credential_pool import ManagedCredentialPool

logger = logging.getLogger(__name__)

CREDENTIAL_HOME_ENV = "BRAIN_RESEARCHER_HOME"
GEMINI_CREDENTIAL_PREFERENCE_ENV = "BR_GEMINI_CREDENTIAL_PREFERENCE"


def get_default_credential_path() -> Path:
    """Resolve the default credential file path honoring the override env var."""
    home_override = os.environ.get(CREDENTIAL_HOME_ENV)
    base_dir = Path(home_override).expanduser() if home_override else Path.home()
    return base_dir / ".brain_researcher" / "credentials.json"


@dataclass
class ResolvedCredential:
    """Resolved credential with type and optional API key."""

    kind: str  # e.g., "managed_gemini", "local_gemini", "byok_gemini", "byok_openai"
    api_key: str | None = None  # For BYOK and managed credentials
    metadata: dict[str, Any] = (
        None  # Additional metadata (source, name, budget_id, allocation_id, is_managed)
    )

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class CredentialResolver:
    """
    Resolve credentials for LLM routing with multi-source support.

    Priority order (Gemini):
    1. Managed (when budget_id provided)
    2. Gemini credential preference order:
       - local_oauth_first (default legacy behavior when USE_GEMINI_CLI=true)
       - byok_first
       - local_oauth_only
       - byok_only

    Other providers (e.g., GPT/OpenAI) retain BYOK-first resolution.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        managed_pool: ManagedCredentialPool | None = None,
    ):
        """Initialize credential resolver.

        Args:
            config_path: Optional path to credentials file. Defaults to ~/.brain_researcher/credentials.json
            managed_pool: Optional managed credential pool for budget-controlled credentials
        """
        self.config_path = config_path or get_default_credential_path()
        self.managed_pool = managed_pool
        self._credentials_cache: dict[str, Any] | None = None

    def _load_credentials(self) -> dict[str, Any]:
        """Load credentials from config file."""
        if self._credentials_cache is not None:
            return self._credentials_cache

        if not self.config_path.exists():
            self._credentials_cache = {}
            return self._credentials_cache

        try:
            with open(self.config_path) as f:
                self._credentials_cache = json.load(f)
                return self._credentials_cache
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load credentials from {self.config_path}: {e}")
            self._credentials_cache = {}
            return self._credentials_cache

    def _save_credentials(self, credentials: dict[str, Any]) -> None:
        """Save credentials to config file with secure permissions."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with restrictive permissions
        with open(self.config_path, "w") as f:
            json.dump(credentials, f, indent=2)

        # Set file permissions to 0600 (owner read/write only)
        self.config_path.chmod(0o600)

        # Clear cache to force reload
        self._credentials_cache = None

    @staticmethod
    def _prefer_local_cli() -> bool:
        """Whether to prefer local Gemini CLI over BYOK when available."""
        return os.environ.get("USE_GEMINI_CLI", "true").lower() == "true"

    @classmethod
    def _gemini_credential_order(cls) -> tuple[str, ...]:
        """Resolve Gemini credential preference order from environment."""
        raw = os.environ.get(GEMINI_CREDENTIAL_PREFERENCE_ENV, "").strip().lower()
        normalized = raw.replace("-", "_")
        aliases = {
            "local": "local_oauth_first",
            "local_first": "local_oauth_first",
            "local_oauth": "local_oauth_first",
            "local_oauth_first": "local_oauth_first",
            "byok": "byok_first",
            "api": "byok_first",
            "api_key": "byok_first",
            "byok_first": "byok_first",
            "local_only": "local_oauth_only",
            "local_oauth_only": "local_oauth_only",
            "byok_only": "byok_only",
        }
        mode = aliases.get(normalized)
        if mode == "local_oauth_first":
            return ("local_oauth", "byok")
        if mode == "byok_first":
            return ("byok", "local_oauth")
        if mode == "local_oauth_only":
            return ("local_oauth",)
        if mode == "byok_only":
            return ("byok",)
        if cls._prefer_local_cli():
            return ("local_oauth", "byok")
        return ("byok", "local_oauth")

    def _configured_byok_credential(self, provider: str) -> ResolvedCredential | None:
        """Return the first configured BYOK credential for a provider, if any."""
        credentials = self._load_credentials()
        if "byok" in credentials:
            for name, info in credentials["byok"].items():
                if info.get("provider") == provider:
                    return ResolvedCredential(
                        kind=f"byok_{provider}",
                        api_key=info["api_key"],
                        metadata={"source": "config", "name": name},
                    )
        return None

    def _gemini_byok_credential(self) -> ResolvedCredential | None:
        """Return Gemini BYOK credentials from env or config."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            return ResolvedCredential(
                kind="byok_gemini",
                api_key=api_key,
                metadata={"source": "environment"},
            )
        return self._configured_byok_credential("gemini")

    def _local_gemini_credential(self) -> ResolvedCredential | None:
        """Return a local Gemini credential if the CLI looks usable."""
        try:
            if gemini_cli.quick_health_check():
                return ResolvedCredential(
                    kind="local_gemini", metadata={"source": "oauth"}
                )
        except Exception:
            # Fall through to the softer check
            pass

        if gemini_cli.is_logged_in():
            return ResolvedCredential(kind="local_gemini", metadata={"source": "oauth"})
        return None

    def add_credential(self, name: str, api_key: str, provider: str) -> None:
        """Add or update a BYOK credential.

        Args:
            name: Credential name (e.g., "personal_gemini")
            api_key: API key value
            provider: Provider type ("gemini" or "openai")
        """
        if provider not in ["gemini", "openai"]:
            raise ValueError(f"Unsupported provider: {provider}")

        credentials = self._load_credentials()
        if "byok" not in credentials:
            credentials["byok"] = {}

        credentials["byok"][name] = {
            "api_key": api_key,
            "provider": provider,
            "created_at": str(
                Path.cwd()
            ),  # Timestamp would be better but keeping it simple
        }

        self._save_credentials(credentials)
        logger.info(f"Added BYOK credential: {name} ({provider})")

    def remove_credential(self, name: str) -> bool:
        """Remove a BYOK credential.

        Args:
            name: Credential name to remove

        Returns:
            True if removed, False if not found
        """
        credentials = self._load_credentials()
        if "byok" in credentials and name in credentials["byok"]:
            del credentials["byok"][name]
            self._save_credentials(credentials)
            logger.info(f"Removed BYOK credential: {name}")
            return True
        return False

    def list_credentials(self) -> dict[str, str]:
        """List all configured credentials (without exposing keys).

        Returns:
            Dict mapping credential names to provider types
        """
        result = {}

        # Check local OAuth
        if gemini_cli.is_logged_in():
            result["local_oauth"] = "gemini"

        # Check BYOK credentials
        credentials = self._load_credentials()
        if "byok" in credentials:
            for name, info in credentials["byok"].items():
                result[f"byok_{name}"] = info["provider"]

        # Check environment variables
        if os.environ.get("GEMINI_API_KEY"):
            result["env_gemini"] = "gemini"
        if os.environ.get("OPENAI_API_KEY"):
            result["env_openai"] = "openai"

        return result

    def resolve_for_chat(
        self,
        model_hint: str | None = None,
        credential_name: str | None = None,
        budget_id: str | None = None,
    ) -> ResolvedCredential | None:
        """Resolve the best credential for a chat request.

        Args:
            model_hint: Optional model name hint (e.g., "gemini-3.1-flash-lite-preview")
            credential_name: Optional specific credential to use
            budget_id: Optional budget ID for managed credential allocation

        Returns:
            ResolvedCredential or None if no suitable credential found
        """
        # If specific credential requested, try to resolve it
        if credential_name:
            return self._resolve_specific(credential_name)

        # Priority 1: Check managed credentials if budget_id provided
        if budget_id and self.managed_pool:
            managed_cred = self.resolve_managed_credential(budget_id, model_hint)
            if managed_cred:
                return managed_cred

        # Provider-specific resolution
        if model_hint and "gemini" in model_hint.lower():
            for source in self._gemini_credential_order():
                if source == "local_oauth":
                    local_cred = self._local_gemini_credential()
                    if local_cred:
                        return local_cred
                elif source == "byok":
                    byok_cred = self._gemini_byok_credential()
                    if byok_cred:
                        return byok_cred
            return None

        if model_hint and "gpt" in model_hint.lower():
            # Environment BYOK
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                return ResolvedCredential(
                    kind="byok_openai",
                    api_key=api_key,
                    metadata={"source": "environment"},
                )

            # Configured BYOK
            configured = self._configured_byok_credential("openai")
            if configured:
                return configured

        return None

    def _resolve_specific(self, credential_name: str) -> ResolvedCredential | None:
        """Resolve a specific named credential."""
        credentials = self._load_credentials()

        # Managed pool lookup for explicitly named managed credentials.
        # ManagedCredentialPool exposes allocation helpers, not a dict-like .get().
        # For an explicit credential name we only need a read-only lookup.
        if self.managed_pool:
            managed = None
            credentials_map = getattr(self.managed_pool, "_credentials", None)
            if isinstance(credentials_map, dict):
                managed = credentials_map.get(credential_name)
            if managed:
                return ResolvedCredential(
                    kind=f"managed_{managed.provider}",
                    api_key=managed.api_key,
                    metadata={
                        "source": "managed",
                        "name": credential_name,
                        "provider": managed.provider,
                        "is_managed": True,
                    },
                )

        # Check BYOK credentials
        if "byok" in credentials and credential_name in credentials["byok"]:
            info = credentials["byok"][credential_name]
            kind = f"byok_{info['provider']}"
            return ResolvedCredential(
                kind=kind,
                api_key=info["api_key"],
                metadata={"source": "config", "name": credential_name},
            )

        # Check special names
        if credential_name == "env_gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                return ResolvedCredential(
                    kind="byok_gemini",
                    api_key=api_key,
                    metadata={"source": "environment", "name": credential_name},
                )

        if credential_name == "env_openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                return ResolvedCredential(
                    kind="byok_openai",
                    api_key=api_key,
                    metadata={"source": "environment", "name": credential_name},
                )

        if credential_name == "local_oauth" and gemini_cli.is_logged_in():
            return ResolvedCredential(kind="local_gemini", metadata={"source": "oauth"})

        return None

    def resolve_managed_credential(
        self, budget_id: str, model_hint: str | None = None
    ) -> ResolvedCredential | None:
        """
        Resolve a managed credential from the pool for a specific budget.

        Args:
            budget_id: Budget ID requesting the credential
            model_hint: Optional model name for provider inference

        Returns:
            ResolvedCredential with managed credential, or None if unavailable
        """
        if not self.managed_pool:
            logger.debug("No managed credential pool configured")
            return None

        try:
            # Infer provider from model hint
            provider_hint = None
            if model_hint:
                model_lower = model_hint.lower()
                if "gemini" in model_lower:
                    provider_hint = "gemini"
                elif "gpt" in model_lower or "davinci" in model_lower:
                    provider_hint = "openai"
                elif "claude" in model_lower:
                    provider_hint = "anthropic"

            # Get credential from pool
            managed_cred = self.managed_pool.get_credential(
                budget_id=budget_id, model_hint=model_hint, provider_hint=provider_hint
            )

            if not managed_cred:
                logger.debug(
                    f"No managed credential available for budget {budget_id}, "
                    f"provider={provider_hint}"
                )
                return None

            # Extract allocation_id from tags
            allocation_id = managed_cred.tags.get("allocation_id", "")

            # Return as ResolvedCredential
            kind = f"managed_{managed_cred.provider}"
            return ResolvedCredential(
                kind=kind,
                api_key=managed_cred.api_key,
                metadata={
                    "source": "managed",
                    "budget_id": budget_id,
                    "allocation_id": allocation_id,
                    "is_managed": True,
                    "provider": managed_cred.provider,
                    "credential_id": managed_cred.credential_id,
                    "name": managed_cred.name or managed_cred.credential_id,
                },
            )

        except Exception as e:
            logger.error(
                f"Error resolving managed credential for budget {budget_id}: {e}"
            )
            return None
