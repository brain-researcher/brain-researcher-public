"""
Unit tests for the enhanced credential resolver with BYOK support.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.credential_resolver import (
    CredentialResolver,
    ResolvedCredential,
)


class TestCredentialResolver:
    """Test suite for CredentialResolver."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    @pytest.fixture
    def resolver_with_temp_config(self, temp_config_file):
        """Create a resolver with temporary config file."""
        return CredentialResolver(config_path=temp_config_file)

    def test_resolved_credential_init(self):
        """Test ResolvedCredential initialization."""
        cred = ResolvedCredential(kind="local_gemini")
        assert cred.kind == "local_gemini"
        assert cred.api_key is None
        assert cred.metadata == {}

        cred_with_key = ResolvedCredential(
            kind="byok_gemini",
            api_key="test_key",
            metadata={"source": "test"}
        )
        assert cred_with_key.kind == "byok_gemini"
        assert cred_with_key.api_key == "test_key"
        assert cred_with_key.metadata == {"source": "test"}

    def test_add_credential(self, resolver_with_temp_config):
        """Test adding BYOK credentials."""
        resolver = resolver_with_temp_config
        
        # Add Gemini credential
        resolver.add_credential("test_gemini", "gemini_key_123", "gemini")
        
        # Verify it was saved
        with open(resolver.config_path, 'r') as f:
            config = json.load(f)
        
        assert "byok" in config
        assert "test_gemini" in config["byok"]
        assert config["byok"]["test_gemini"]["api_key"] == "gemini_key_123"
        assert config["byok"]["test_gemini"]["provider"] == "gemini"

        # Add OpenAI credential
        resolver.add_credential("test_openai", "sk-test123", "openai")
        
        with open(resolver.config_path, 'r') as f:
            config = json.load(f)
        
        assert "test_openai" in config["byok"]
        assert config["byok"]["test_openai"]["api_key"] == "sk-test123"
        assert config["byok"]["test_openai"]["provider"] == "openai"

    def test_add_credential_invalid_provider(self, resolver_with_temp_config):
        """Test adding credential with invalid provider."""
        resolver = resolver_with_temp_config
        
        with pytest.raises(ValueError, match="Unsupported provider"):
            resolver.add_credential("test", "key", "invalid_provider")

    def test_remove_credential(self, resolver_with_temp_config):
        """Test removing BYOK credentials."""
        resolver = resolver_with_temp_config
        
        # Add then remove
        resolver.add_credential("test_cred", "key123", "gemini")
        assert resolver.remove_credential("test_cred") is True
        
        # Verify it's gone
        with open(resolver.config_path, 'r') as f:
            config = json.load(f)
        
        assert "test_cred" not in config.get("byok", {})
        
        # Try removing non-existent
        assert resolver.remove_credential("non_existent") is False

    @patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in')
    def test_list_credentials(self, mock_is_logged_in, resolver_with_temp_config):
        """Test listing all credentials."""
        resolver = resolver_with_temp_config
        mock_is_logged_in.return_value = True
        
        # Add some BYOK credentials
        resolver.add_credential("personal", "key1", "gemini")
        resolver.add_credential("work", "key2", "openai")
        
        # Mock environment variables
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env_key"}):
            creds = resolver.list_credentials()
        
        assert "local_oauth" in creds
        assert creds["local_oauth"] == "gemini"
        assert "byok_personal" in creds
        assert creds["byok_personal"] == "gemini"
        assert "byok_work" in creds
        assert creds["byok_work"] == "openai"
        assert "env_gemini" in creds
        assert creds["env_gemini"] == "gemini"

    @patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in')
    def test_resolve_for_chat_local_oauth(self, mock_is_logged_in, resolver_with_temp_config):
        """Test resolving local OAuth credential."""
        resolver = resolver_with_temp_config
        mock_is_logged_in.return_value = True
        
        cred = resolver.resolve_for_chat(model_hint="gemini-2.5-pro")
        
        assert cred is not None
        assert cred.kind == "local_gemini"
        assert cred.metadata["source"] == "oauth"

    @patch('brain_researcher.services.agent.utils.gemini_cli.quick_health_check')
    @patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in')
    def test_resolve_for_chat_gemini_byok_first_beats_local_oauth(
        self, mock_is_logged_in, mock_quick_health_check, resolver_with_temp_config
    ):
        """Explicit byok_first should override local Gemini OAuth."""
        resolver = resolver_with_temp_config
        mock_quick_health_check.return_value = True
        mock_is_logged_in.return_value = True

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "env_gemini_key",
                "BR_GEMINI_CREDENTIAL_PREFERENCE": "byok_first",
                "USE_GEMINI_CLI": "true",
            },
            clear=True,
        ):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-flash")

        assert cred is not None
        assert cred.kind == "byok_gemini"
        assert cred.api_key == "env_gemini_key"
        assert cred.metadata["source"] == "environment"

    @patch('brain_researcher.services.agent.utils.gemini_cli.quick_health_check')
    @patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in')
    def test_resolve_for_chat_gemini_byok_only_disables_local_fallback(
        self, mock_is_logged_in, mock_quick_health_check, resolver_with_temp_config
    ):
        """Explicit byok_only should not fall back to local OAuth."""
        resolver = resolver_with_temp_config
        mock_quick_health_check.return_value = True
        mock_is_logged_in.return_value = True

        with patch.dict(
            os.environ,
            {
                "BR_GEMINI_CREDENTIAL_PREFERENCE": "byok_only",
                "USE_GEMINI_CLI": "true",
            },
            clear=True,
        ):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-flash")

        assert cred is None

    def test_resolve_for_chat_env_override(self, resolver_with_temp_config):
        """Test environment variable override with explicit BYOK preference."""
        resolver = resolver_with_temp_config
        
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "env_gemini_key",
                "BR_GEMINI_CREDENTIAL_PREFERENCE": "byok_first",
            },
        ):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-flash")
        
        assert cred is not None
        assert cred.kind == "byok_gemini"
        assert cred.api_key == "env_gemini_key"
        assert cred.metadata["source"] == "environment"

    def test_resolve_for_chat_byok_config(self, resolver_with_temp_config):
        """Test resolving BYOK from config."""
        resolver = resolver_with_temp_config
        
        # Add BYOK credential
        resolver.add_credential("my_gemini", "config_key", "gemini")
        
        # Clear env to ensure config is used
        with patch.dict(os.environ, {}, clear=True):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-pro")
        
        assert cred is not None
        assert cred.kind == "byok_gemini"
        assert cred.api_key == "config_key"
        assert cred.metadata["source"] == "config"
        assert cred.metadata["name"] == "my_gemini"

    def test_resolve_for_chat_specific_credential(self, resolver_with_temp_config):
        """Test resolving a specific named credential."""
        resolver = resolver_with_temp_config
        
        # Add multiple credentials
        resolver.add_credential("personal", "personal_key", "gemini")
        resolver.add_credential("work", "work_key", "openai")
        
        # Request specific credential
        cred = resolver.resolve_for_chat(credential_name="work")
        
        assert cred is not None
        assert cred.kind == "byok_openai"
        assert cred.api_key == "work_key"
        assert cred.metadata["name"] == "work"

    def test_resolve_for_chat_env_specific_credential(self, resolver_with_temp_config):
        """Test resolving explicit environment-backed credential names."""
        resolver = resolver_with_temp_config

        with patch.dict(os.environ, {"GEMINI_API_KEY": "env_gemini_key"}):
            cred = resolver.resolve_for_chat(credential_name="env_gemini")

        assert cred is not None
        assert cred.kind == "byok_gemini"
        assert cred.api_key == "env_gemini_key"
        assert cred.metadata["name"] == "env_gemini"

    def test_resolve_for_chat_env_specific_credential_with_managed_pool(self, temp_config_file):
        """Explicit env credentials should not crash when a managed pool is attached."""
        from brain_researcher.services.agent.managed_credential_pool import ManagedCredentialPool

        resolver = CredentialResolver(
            config_path=temp_config_file,
            managed_pool=ManagedCredentialPool(),
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "env_gemini_key"}):
            cred = resolver.resolve_for_chat(credential_name="env_gemini")

        assert cred is not None
        assert cred.kind == "byok_gemini"
        assert cred.api_key == "env_gemini_key"
        assert cred.metadata["source"] == "environment"
        assert cred.metadata["name"] == "env_gemini"

    def test_resolve_for_chat_no_credential(self, resolver_with_temp_config):
        """Test when no credential is available."""
        resolver = resolver_with_temp_config
        
        with patch.dict(os.environ, {}, clear=True):
            with patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=False):
                cred = resolver.resolve_for_chat(model_hint="gemini-2.5-pro")
        
        assert cred is None

    def test_credential_priority_order(self, resolver_with_temp_config):
        """Test credential resolution priority order under byok_first."""
        resolver = resolver_with_temp_config
        
        # Add config credential
        resolver.add_credential("config_cred", "config_key", "gemini")
        
        # Test priority: env > config > oauth
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "env_key",
                "BR_GEMINI_CREDENTIAL_PREFERENCE": "byok_first",
            },
        ):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-pro")
            assert cred.api_key == "env_key"
            assert cred.metadata["source"] == "environment"
        
        # Without env, should use config
        with patch.dict(
            os.environ,
            {"BR_GEMINI_CREDENTIAL_PREFERENCE": "byok_first"},
            clear=True,
        ):
            cred = resolver.resolve_for_chat(model_hint="gemini-2.5-pro")
            assert cred.api_key == "config_key"
            assert cred.metadata["source"] == "config"

    def test_file_permissions(self, resolver_with_temp_config):
        """Test that credential file has secure permissions."""
        resolver = resolver_with_temp_config
        
        # Add a credential to trigger file creation
        resolver.add_credential("test", "key", "gemini")
        
        # Check file permissions (should be 0600)
        stat_info = os.stat(resolver.config_path)
        mode = stat_info.st_mode & 0o777
        assert mode == 0o600, f"File permissions {oct(mode)} are not secure (expected 0o600)"

    def test_credential_caching(self, resolver_with_temp_config):
        """Test that credentials are cached after first load."""
        resolver = resolver_with_temp_config
        
        # Add credential
        resolver.add_credential("test", "key", "gemini")
        
        # First load
        creds1 = resolver._load_credentials()
        
        # Modify file directly (bypass cache)
        with open(resolver.config_path, 'w') as f:
            json.dump({"byok": {"modified": {"api_key": "new", "provider": "openai"}}}, f)
        
        # Should still get cached version
        creds2 = resolver._load_credentials()
        assert creds1 == creds2
        
        # After save, cache should be cleared
        resolver.add_credential("another", "key2", "openai")
        creds3 = resolver._load_credentials()
        assert "another" in creds3["byok"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
