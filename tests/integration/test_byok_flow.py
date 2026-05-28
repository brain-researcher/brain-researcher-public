"""
Integration tests for BYOK (Bring Your Own Key) flow.
"""

import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.router import LLMRouter
from brain_researcher.services.agent.credential_resolver import CredentialResolver
from brain_researcher.services.agent.utils import gemini_fallback
from brain_researcher.services.agent.utils.gemini_fallback import chat_with_fallback


class TestBYOKIntegration:
    """Integration tests for BYOK credential flow."""

    @pytest.fixture(autouse=True)
    def skip_dotenv_loading(self, monkeypatch):
        """Prevent tests from reading real developer credentials."""
        monkeypatch.setenv("BRAIN_RESEARCHER_SKIP_DOTENV", "1")

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def router_with_temp_config(self, temp_config_dir):
        """Configure the shared router to use the temp credential file."""
        config_file = temp_config_dir / "credentials.json"
        resolver = CredentialResolver(config_path=config_file)
        router = LLMRouter(credential_resolver=resolver)
        previous_router = gemini_fallback._ROUTER
        gemini_fallback._set_router_for_testing(router)
        try:
            yield resolver, config_file
        finally:
            gemini_fallback._set_router_for_testing(previous_router)

    @pytest.fixture(autouse=True)
    def disable_local_gemini(self):
        """Prevent tests from shelling out to the real Gemini CLI."""
        with patch("brain_researcher.services.agent.utils.gemini_cli.is_logged_in", return_value=False):
            yield

    @pytest.fixture
    def mock_gemini_api(self):
        """Mock the Gemini API."""
        import sys

        google_pkg = ModuleType("google")
        google_pkg.__path__ = []  # Mark as package for import machinery
        genai_module = ModuleType("google.generativeai")
        configure_mock = MagicMock()
        model_mock = MagicMock()
        model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "BYOK Gemini response"
        model_instance.generate_content.return_value = mock_response
        model_mock.return_value = model_instance
        genai_module.configure = configure_mock
        genai_module.GenerativeModel = model_mock
        google_pkg.generativeai = genai_module

        with patch.dict(
            sys.modules,
            {
                "google": google_pkg,
                "google.generativeai": genai_module,
            },
        ):
            yield configure_mock, model_mock

    @pytest.fixture
    def mock_openai_api(self):
        """Mock the OpenAI API."""
        import sys

        stack = ExitStack()
        module_injections = {}

        if "openai" in sys.modules:
            openai_module = sys.modules["openai"]
        else:
            openai_module = ModuleType("openai")
            openai_module.__path__ = []
            module_injections["openai"] = openai_module

        if "openai.resources" in sys.modules:
            resources_module = sys.modules["openai.resources"]
        else:
            resources_module = ModuleType("openai.resources")
            resources_module.__path__ = []
            module_injections["openai.resources"] = resources_module
        if not hasattr(openai_module, "resources"):
            setattr(openai_module, "resources", resources_module)

        if module_injections:
            stack.enter_context(patch.dict(sys.modules, module_injections))

        mock_client = stack.enter_context(patch("openai.OpenAI", create=True))
        mock_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "BYOK OpenAI response"
        mock_response.usage = MagicMock(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        mock_instance.chat.completions.create.return_value = mock_response
        mock_client.return_value = mock_instance

        try:
            yield mock_client
        finally:
            stack.close()

    def test_byok_gemini_flow(self, router_with_temp_config, mock_gemini_api):
        """Test end-to-end BYOK flow with Gemini API."""
        resolver, _ = router_with_temp_config
        
        # Add BYOK Gemini credential
        resolver.add_credential("test_gemini", "test_gemini_key_123", "gemini")
        
        # Clear environment to ensure BYOK is used
        with patch.dict(os.environ, {}, clear=True):
            # Test chat with fallback
            text, provider, model, usage, reason = chat_with_fallback(
                prompt="Test prompt",
                initial_model="gemini-2.5-pro"
            )
        
        # Verify Gemini API was configured with BYOK key
        mock_config, mock_model = mock_gemini_api
        mock_config.assert_called_once_with(api_key="test_gemini_key_123")
        
        # Verify response
        assert text == "BYOK Gemini response"
        assert provider == "google"
        assert model == "gemini-2.5-pro"

    def test_byok_openai_flow(self, router_with_temp_config, mock_openai_api):
        """Test end-to-end BYOK flow with OpenAI API."""
        resolver, _ = router_with_temp_config
        
        # Add BYOK OpenAI credential
        resolver.add_credential("test_openai", "sk-test123", "openai")
        
        with patch.dict(os.environ, {}, clear=True):
            text, provider, model, usage, reason = chat_with_fallback(
                prompt="Test prompt",
                initial_model="gpt-5"
            )

        # Verify OpenAI client was created with BYOK key
        mock_openai_api.assert_called_once_with(api_key="sk-test123")
        
        # Verify response
        assert text == "BYOK OpenAI response"
        assert provider == "openai"
        assert model == "gpt-5"
        assert usage["total_tokens"] == 30

    def test_credential_priority_in_fallback(self, router_with_temp_config, mock_gemini_api):
        """Test that environment variables override config in fallback."""
        resolver, _ = router_with_temp_config
        
        # Add config credential
        resolver.add_credential("config_key", "config_gemini_key", "gemini")
        
        # Set environment variable (should override config)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env_gemini_key"}):
            text, provider, model, usage, reason = chat_with_fallback(
                prompt="Test prompt",
                initial_model="gemini-2.5-pro"
            )
        
        # Verify environment key was used
        mock_config, _ = mock_gemini_api
        mock_config.assert_called_once_with(api_key="env_gemini_key")

    def test_specific_credential_selection(self, router_with_temp_config, mock_gemini_api):
        """Test selecting a specific credential by name."""
        resolver, _ = router_with_temp_config
        
        # Add multiple credentials
        resolver.add_credential("personal", "personal_key", "gemini")
        resolver.add_credential("work", "work_key", "gemini")
        
        # Use specific credential
        with patch.dict(os.environ, {}, clear=True):
            text, provider, model, usage, reason = chat_with_fallback(
                prompt="Test prompt",
                initial_model="gemini-2.5-pro",
                credential_name="work"
            )
        
        # Verify correct key was used
        mock_config, _ = mock_gemini_api
        mock_config.assert_called_once_with(api_key="work_key")

    @patch('brain_researcher.services.agent.utils.gemini_cli.execute_chat')
    @patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in')
    def test_fallback_cascade_with_byok(self, mock_is_logged_in, mock_execute_chat,
                                        router_with_temp_config, mock_openai_api):
        """Test fallback cascade: Gemini CLI → BYOK OpenAI."""
        resolver, _ = router_with_temp_config

        # Add BYOK OpenAI credential
        resolver.add_credential("backup", "sk-backup", "openai")
        
        # Mock Gemini CLI available but fails
        mock_is_logged_in.return_value = True
        mock_execute_chat.side_effect = Exception("Quota exhausted")
        
        with patch.dict(os.environ, {}, clear=True):
            # Should fallback from Gemini CLI to OpenAI BYOK
            text, provider, model, usage, reason = chat_with_fallback(
                prompt="Test prompt",
                initial_model="gemini-2.5-pro"
            )

        # Verify OpenAI was used as fallback
        assert text == "BYOK OpenAI response"
        assert provider == "openai"
        assert model == "gpt-5"  # Last in cascade
        assert reason is not None  # Should have fallback reason

    def test_no_credentials_error(self, router_with_temp_config):
        """Test error when no credentials are available."""
        resolver, _ = router_with_temp_config
        
        with patch.dict(os.environ, {}, clear=True):
            with patch('brain_researcher.services.agent.utils.gemini_cli.is_logged_in', return_value=False):
                with patch('brain_researcher.services.agent.llm.get_llm', side_effect=ValueError("No API key")):
                    # Should raise error when all methods fail
                    with pytest.raises(Exception):
                        chat_with_fallback(
                            prompt="Test prompt",
                            initial_model="gemini-2.5-pro"
                        )


class TestCLIConfigCommands:
    """Test CLI config commands integration."""

    @pytest.fixture(autouse=True)
    def skip_dotenv_loading(self, monkeypatch):
        """Prevent CLI tests from pulling secrets from developer .env."""
        monkeypatch.setenv("BRAIN_RESEARCHER_SKIP_DOTENV", "1")

    @pytest.fixture
    def temp_home_dir(self, monkeypatch):
        """Create temporary home directory for config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home_path = Path(tmpdir)
            monkeypatch.setenv("HOME", tmpdir)
            monkeypatch.setenv("BRAIN_RESEARCHER_HOME", tmpdir)
            with patch.object(Path, "home", return_value=home_path):
                yield home_path

    def test_cli_add_credential(self, temp_home_dir):
        """Test adding credential via CLI command."""
        from brain_researcher.cli.commands.config_commands import add_credential
        from typer.testing import CliRunner
        from typer import Typer
        
        app = Typer()
        app.command()(add_credential)
        runner = CliRunner()
        
        # Run command with all arguments
        result = runner.invoke(
            app,
            ["test_cred", "--provider", "gemini", "--key", "test_key_123"]
        )
        
        # Check credential was saved
        config_file = temp_home_dir / ".brain_researcher" / "credentials.json"
        assert config_file.exists()
        
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        assert "byok" in config
        assert "test_cred" in config["byok"]
        assert config["byok"]["test_cred"]["api_key"] == "test_key_123"

    def test_cli_list_credentials(self, temp_home_dir):
        """Test listing credentials via CLI."""
        # First add some credentials
        resolver = CredentialResolver()
        resolver.add_credential("cred1", "key1", "gemini")
        resolver.add_credential("cred2", "key2", "openai")
        
        from brain_researcher.cli.commands.config_commands import list_credentials
        from typer.testing import CliRunner
        from typer import Typer
        
        app = Typer()
        app.command()(list_credentials)
        runner = CliRunner()
        
        result = runner.invoke(app, [])
        
        # Check output contains credentials
        assert "cred1" in result.stdout
        assert "cred2" in result.stdout
        assert "gemini" in result.stdout
        assert "openai" in result.stdout

    def test_cli_remove_credential(self, temp_home_dir):
        """Test removing credential via CLI."""
        # First add a credential
        resolver = CredentialResolver()
        resolver.add_credential("to_remove", "key", "gemini")
        
        from brain_researcher.cli.commands.config_commands import remove_credential
        from typer.testing import CliRunner
        from typer import Typer
        
        app = Typer()
        app.command()(remove_credential)
        runner = CliRunner()
        
        # Remove with --yes flag
        result = runner.invoke(app, ["to_remove", "--yes"])
        
        # Verify it's removed
        resolver2 = CredentialResolver()
        creds = resolver2.list_credentials()
        assert "byok_to_remove" not in creds


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
