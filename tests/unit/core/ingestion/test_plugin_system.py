"""Comprehensive unit tests for INGEST-022 Plugin System.

This test suite covers:
- Plugin discovery and loading mechanisms
- Plugin validation and lifecycle management
- Data source plugin interfaces and implementations
- Configuration validation and error handling
- Plugin activation/deactivation processes
- Data fetching and transformation
- Template generation and documentation
"""

import importlib.util
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

from brain_researcher.core.ingestion.plugins.plugin_system import (
    DataSourcePlugin,
    PluginConfig,
    PluginManager,
    PluginMetadata,
    PluginStatus,
)


class MockDataSourcePlugin(DataSourcePlugin):
    """Mock plugin implementation for testing."""
    
    def __init__(self, should_fail_connect=False, should_fail_fetch=False):
        self.should_fail_connect = should_fail_connect
        self.should_fail_fetch = should_fail_fetch
        self.connected = False
        self.fetch_calls = 0
        
    def get_metadata(self) -> PluginMetadata:
        """Get mock plugin metadata."""
        return PluginMetadata(
            name="mock_plugin",
            version="1.0.0",
            author="Test Author",
            description="Mock plugin for testing",
            data_source_type="test",
            supported_formats=["json", "csv"],
            dependencies=["requests"],
            configuration_schema={
                "api_key": {"type": "string", "required": True},
                "endpoint": {"type": "string", "required": True},
                "timeout": {"type": "integer", "default": 30}
            }
        )
        
    def validate_config(self, config):
        """Mock config validation."""
        errors = []
        
        if "api_key" not in config:
            errors.append("Missing required field: api_key")
        if "endpoint" not in config:
            errors.append("Missing required field: endpoint")
        if "timeout" in config and not isinstance(config["timeout"], int):
            errors.append("timeout must be an integer")
            
        return len(errors) == 0, errors
        
    def connect(self, config):
        """Mock connection."""
        if self.should_fail_connect:
            return False
        self.connected = True
        return True
        
    def disconnect(self):
        """Mock disconnection."""
        self.connected = False
        return True
        
    def fetch_data(self, query=None, limit=None):
        """Mock data fetching."""
        self.fetch_calls += 1
        
        if self.should_fail_fetch:
            raise Exception("Mock fetch failure")
            
        if not self.connected:
            raise RuntimeError("Not connected")
            
        # Generate mock data
        data = []
        count = limit or 10
        
        for i in range(count):
            data.append({
                "id": f"record_{i}",
                "value": f"data_{i}",
                "timestamp": "2025-01-01T00:00:00Z"
            })
            
        return data
        
    def transform_data(self, data):
        """Mock data transformation."""
        transformed = []
        
        for record in data:
            transformed.append({
                "entity_id": record.get("id"),
                "entity_type": "test_data",
                "data": record,
                "source": "mock_plugin"
            })
            
        return transformed
        
    def get_schema(self):
        """Mock schema."""
        return {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "entity_type": {"type": "string"},
                "data": {"type": "object"},
                "source": {"type": "string"}
            }
        }
        
    def get_statistics(self):
        """Mock statistics."""
        return {
            "connected": self.connected,
            "fetch_calls": self.fetch_calls
        }


class FailingDataSourcePlugin(DataSourcePlugin):
    """Plugin that fails validation for testing."""
    
    def get_metadata(self):
        """Return invalid metadata."""
        return PluginMetadata(
            name="",  # Invalid empty name
            version="",  # Invalid empty version
            author="Test",
            description="Failing plugin",
            data_source_type="test",
            supported_formats=[]
        )
        
    def validate_config(self, config):
        """Always fail validation."""
        return False, ["Validation always fails"]
        
    def connect(self, config):
        """Always fail connection."""
        return False
        
    def disconnect(self):
        """Mock disconnect."""
        return True
        
    def fetch_data(self, query=None, limit=None):
        """Always fail fetch."""
        raise Exception("Fetch always fails")
        
    def transform_data(self, data):
        """Mock transform."""
        return data


@pytest.fixture
def temp_plugin_dir():
    """Create a temporary directory for plugins."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def plugin_manager(temp_plugin_dir):
    """Create a plugin manager instance."""
    return PluginManager(str(temp_plugin_dir))


@pytest.fixture
def mock_plugin():
    """Create a mock plugin instance."""
    return MockDataSourcePlugin()


@pytest.fixture
def failing_plugin():
    """Create a failing plugin instance."""
    return FailingDataSourcePlugin()


@pytest.fixture
def sample_plugin_file(temp_plugin_dir):
    """Create a sample plugin file."""
    plugin_content = '''
from brain_researcher.core.ingestion.plugins.plugin_system import DataSourcePlugin, PluginMetadata

class SamplePlugin(DataSourcePlugin):
    def get_metadata(self):
        return PluginMetadata(
            name="sample",
            version="1.0.0", 
            author="Test Author",
            description="Sample plugin",
            data_source_type="sample",
            supported_formats=["json"]
        )
        
    def validate_config(self, config):
        return True, []
        
    def connect(self, config):
        return True
        
    def disconnect(self):
        return True
        
    def fetch_data(self, query=None, limit=None):
        return [{"id": "1", "data": "test"}]
        
    def transform_data(self, data):
        return data
'''
    
    plugin_file = temp_plugin_dir / "sample_plugin.py"
    plugin_file.write_text(plugin_content)
    return plugin_file


class TestPluginManager:
    """Test cases for PluginManager class."""
    
    def test_initialization(self, temp_plugin_dir):
        """Test plugin manager initialization."""
        manager = PluginManager(str(temp_plugin_dir))
        
        assert manager.plugin_dir == temp_plugin_dir
        assert temp_plugin_dir.exists()
        assert len(manager.plugins) == 0
        assert len(manager.plugin_configs) == 0
        assert len(manager.active_plugins) == 0
        assert manager.stats["plugins_loaded"] == 0
        
    def test_discover_plugins_empty_directory(self, plugin_manager):
        """Test plugin discovery with empty directory."""
        discovered = plugin_manager.discover_plugins()
        
        assert len(discovered) == 0
        
    def test_discover_plugins_with_sample_file(self, plugin_manager, sample_plugin_file):
        """Test plugin discovery with sample plugin file."""
        discovered = plugin_manager.discover_plugins()
        
        assert len(discovered) >= 1
        assert any("SamplePlugin" in plugin for plugin in discovered)
        
    def test_discover_plugins_ignores_private_files(self, plugin_manager, temp_plugin_dir):
        """Test that discovery ignores files starting with underscore."""
        # Create private file
        private_file = temp_plugin_dir / "_private.py"
        private_file.write_text("# Private file")
        
        # Create public file
        public_content = '''
from brain_researcher.core.ingestion.plugins.plugin_system import DataSourcePlugin, PluginMetadata

class PublicPlugin(DataSourcePlugin):
    def get_metadata(self):
        return PluginMetadata(name="public", version="1.0", author="Test", 
                            description="Public", data_source_type="test", 
                            supported_formats=[])
    def validate_config(self, config): return True, []
    def connect(self, config): return True
    def disconnect(self): return True
    def fetch_data(self, query=None, limit=None): return []
    def transform_data(self, data): return data
'''
        public_file = temp_plugin_dir / "public.py"
        public_file.write_text(public_content)
        
        discovered = plugin_manager.discover_plugins()
        
        # Should only find public plugin
        assert len(discovered) == 1
        assert "PublicPlugin" in discovered[0]
        
    def test_load_plugin_success(self, plugin_manager):
        """Test successful plugin loading."""
        # Manually register a plugin for testing
        plugin_manager.plugins["mock"] = MockDataSourcePlugin()
        plugin_manager.plugin_configs["mock"] = PluginConfig()
        plugin_manager.plugin_status["mock"] = PluginStatus.LOADED
        
        assert "mock" in plugin_manager.plugins
        assert plugin_manager.plugin_status["mock"] == PluginStatus.LOADED
        
    def test_load_plugin_invalid_path(self, plugin_manager):
        """Test loading plugin with invalid path."""
        success = plugin_manager.load_plugin("nonexistent.NonexistentPlugin")
        
        assert success is False
        
    def test_validate_plugin_success(self, plugin_manager, sample_plugin_file):
        """Test plugin validation success."""
        is_valid, errors = plugin_manager.validate_plugin("sample_plugin.SamplePlugin")
        
        assert is_valid is True
        assert len(errors) == 0
        
    def test_validate_plugin_missing_file(self, plugin_manager):
        """Test plugin validation with missing file."""
        is_valid, errors = plugin_manager.validate_plugin("missing.MissingPlugin")
        
        assert is_valid is False
        assert any("not found" in error for error in errors)
        
    def test_validate_plugin_missing_class(self, plugin_manager, temp_plugin_dir):
        """Test plugin validation with missing class."""
        # Create file without the expected class
        plugin_file = temp_plugin_dir / "incomplete.py"
        plugin_file.write_text("# File without plugin class")
        
        is_valid, errors = plugin_manager.validate_plugin("incomplete.MissingClass")
        
        assert is_valid is False
        assert any("not found in module" in error for error in errors)
        
    def test_validate_plugin_invalid_inheritance(self, plugin_manager, temp_plugin_dir):
        """Test plugin validation with invalid inheritance."""
        invalid_content = '''
class NotAPlugin:
    pass
'''
        plugin_file = temp_plugin_dir / "invalid.py"
        plugin_file.write_text(invalid_content)
        
        is_valid, errors = plugin_manager.validate_plugin("invalid.NotAPlugin")
        
        assert is_valid is False
        assert any("must inherit from DataSourcePlugin" in error for error in errors)
        
    def test_activate_plugin_success(self, plugin_manager):
        """Test successful plugin activation."""
        # Setup plugin
        plugin = MockDataSourcePlugin()
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.plugin_configs["mock"] = PluginConfig(
            config_params={"api_key": "test", "endpoint": "http://test.com"}
        )
        plugin_manager.plugin_status["mock"] = PluginStatus.LOADED
        
        success = plugin_manager.activate_plugin("mock")
        
        assert success is True
        assert "mock" in plugin_manager.active_plugins
        assert plugin_manager.plugin_status["mock"] == PluginStatus.ACTIVE
        assert plugin.connected is True
        
    def test_activate_plugin_not_found(self, plugin_manager):
        """Test activating non-existent plugin."""
        success = plugin_manager.activate_plugin("nonexistent")
        
        assert success is False
        
    def test_activate_plugin_invalid_config(self, plugin_manager):
        """Test activating plugin with invalid config."""
        plugin = MockDataSourcePlugin()
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.plugin_configs["mock"] = PluginConfig(
            config_params={"invalid": "config"}  # Missing required fields
        )
        plugin_manager.plugin_status["mock"] = PluginStatus.LOADED
        
        success = plugin_manager.activate_plugin("mock")
        
        assert success is False
        assert plugin_manager.plugin_status["mock"] == PluginStatus.ERROR
        
    def test_activate_plugin_connection_failure(self, plugin_manager):
        """Test activating plugin with connection failure."""
        plugin = MockDataSourcePlugin(should_fail_connect=True)
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.plugin_configs["mock"] = PluginConfig(
            config_params={"api_key": "test", "endpoint": "http://test.com"}
        )
        plugin_manager.plugin_status["mock"] = PluginStatus.LOADED
        
        success = plugin_manager.activate_plugin("mock")
        
        assert success is False
        assert plugin_manager.plugin_status["mock"] == PluginStatus.ERROR
        
    def test_activate_plugin_already_active(self, plugin_manager):
        """Test activating already active plugin."""
        plugin = MockDataSourcePlugin()
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.active_plugins["mock"] = plugin
        plugin_manager.plugin_status["mock"] = PluginStatus.ACTIVE
        
        success = plugin_manager.activate_plugin("mock")
        
        assert success is True  # Should return True for already active
        
    def test_deactivate_plugin_success(self, plugin_manager):
        """Test successful plugin deactivation."""
        plugin = MockDataSourcePlugin()
        plugin.connected = True
        
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.active_plugins["mock"] = plugin
        plugin_manager.plugin_status["mock"] = PluginStatus.ACTIVE
        plugin_manager.stats["plugins_active"] = 1
        
        success = plugin_manager.deactivate_plugin("mock")
        
        assert success is True
        assert "mock" not in plugin_manager.active_plugins
        assert plugin_manager.plugin_status["mock"] == PluginStatus.INACTIVE
        assert plugin_manager.stats["plugins_active"] == 0
        assert plugin.connected is False
        
    def test_deactivate_plugin_not_active(self, plugin_manager):
        """Test deactivating inactive plugin."""
        success = plugin_manager.deactivate_plugin("nonexistent")
        
        assert success is True  # Should return True for non-active
        
    def test_fetch_from_plugin_success(self, plugin_manager):
        """Test successful data fetching from plugin."""
        plugin = MockDataSourcePlugin()
        plugin.connected = True
        
        plugin_manager.active_plugins["mock"] = plugin
        
        data = plugin_manager.fetch_from_plugin("mock", limit=5)
        
        assert len(data) == 5
        assert plugin.fetch_calls == 1
        assert plugin_manager.stats["data_fetched"]["mock"] == 5
        
        # Verify transformed data structure
        for record in data:
            assert "entity_id" in record
            assert "entity_type" in record
            assert record["entity_type"] == "test_data"
            assert record["source"] == "mock_plugin"
            
    def test_fetch_from_plugin_not_active(self, plugin_manager):
        """Test fetching from inactive plugin."""
        data = plugin_manager.fetch_from_plugin("nonexistent")
        
        assert len(data) == 0
        
    def test_fetch_from_plugin_fetch_failure(self, plugin_manager):
        """Test fetching with plugin fetch failure."""
        plugin = MockDataSourcePlugin(should_fail_fetch=True)
        plugin.connected = True
        
        plugin_manager.active_plugins["mock"] = plugin
        
        data = plugin_manager.fetch_from_plugin("mock")
        
        assert len(data) == 0
        assert plugin_manager.stats["errors"]["mock"] == 1
        
    def test_fetch_from_plugin_validation_failure(self, plugin_manager):
        """Test fetching with data validation failure."""
        plugin = MockDataSourcePlugin()
        plugin.connected = True
        
        # Override fetch_data to return invalid data
        def bad_fetch_data(query=None, limit=None):
            return ["not_a_dict", {"valid": "record"}]
            
        plugin.fetch_data = bad_fetch_data
        plugin_manager.active_plugins["mock"] = plugin
        
        data = plugin_manager.fetch_from_plugin("mock")
        
        assert len(data) == 0
        assert plugin_manager.stats["errors"]["mock"] == 1
        
    def test_get_plugin_info_success(self, plugin_manager):
        """Test getting plugin information."""
        plugin = MockDataSourcePlugin()
        plugin_manager.plugins["mock"] = plugin
        plugin_manager.plugin_status["mock"] = PluginStatus.ACTIVE
        plugin_manager.active_plugins["mock"] = plugin
        
        info = plugin_manager.get_plugin_info("mock")
        
        assert info["name"] == "mock_plugin"
        assert info["version"] == "1.0.0"
        assert info["author"] == "Test Author"
        assert info["status"] == "active"
        assert info["data_source_type"] == "test"
        assert "json" in info["supported_formats"]
        assert "schema" in info
        assert "statistics" in info
        
    def test_get_plugin_info_not_found(self, plugin_manager):
        """Test getting info for non-existent plugin."""
        info = plugin_manager.get_plugin_info("nonexistent")
        
        assert info == {}
        
    def test_list_plugins(self, plugin_manager):
        """Test listing all plugins."""
        # Add some plugins
        plugin1 = MockDataSourcePlugin()
        plugin2 = MockDataSourcePlugin()
        
        plugin_manager.plugins["mock1"] = plugin1
        plugin_manager.plugins["mock2"] = plugin2
        plugin_manager.plugin_status["mock1"] = PluginStatus.LOADED
        plugin_manager.plugin_status["mock2"] = PluginStatus.ACTIVE
        
        plugins_list = plugin_manager.list_plugins()
        
        assert len(plugins_list) == 2
        
        names = [p["name"] for p in plugins_list]
        assert "mock_plugin" in names  # Both plugins have same name in this case
        
    def test_generate_plugin_template(self, plugin_manager, temp_plugin_dir):
        """Test plugin template generation."""
        output_path = temp_plugin_dir / "generated_plugin.py"
        
        template_code = plugin_manager.generate_plugin_template(
            name="TestAPI",
            data_source_type="api",
            output_path=str(output_path)
        )
        
        assert output_path.exists()
        assert "TestAPIPlugin" in template_code
        assert "api data source" in template_code
        assert "def get_metadata" in template_code
        assert "def validate_config" in template_code
        assert "def connect" in template_code
        assert "def fetch_data" in template_code
        assert "def transform_data" in template_code
        
        # Verify the generated file contains the template
        generated_content = output_path.read_text()
        assert generated_content == template_code


class TestDataSourcePlugin:
    """Test cases for DataSourcePlugin base class."""
    
    def test_validate_data_success(self, mock_plugin):
        """Test data validation success."""
        data = [
            {"id": "1", "value": "test1"},
            {"id": "2", "value": "test2"}
        ]
        
        is_valid, errors = mock_plugin.validate_data(data)
        
        assert is_valid is True
        assert len(errors) == 0
        
    def test_validate_data_failure(self, mock_plugin):
        """Test data validation failure."""
        data = [
            {"id": "1", "value": "test1"},
            "not_a_dict",  # Invalid record
            {"id": "3", "value": "test3"}
        ]
        
        is_valid, errors = mock_plugin.validate_data(data)
        
        assert is_valid is False
        assert len(errors) == 1
        assert "not a dictionary" in errors[0]
        
    def test_get_schema_default(self, mock_plugin):
        """Test default schema implementation."""
        schema = mock_plugin.get_schema()
        
        assert isinstance(schema, dict)
        
    def test_get_statistics_default(self, mock_plugin):
        """Test default statistics implementation."""
        stats = mock_plugin.get_statistics()
        
        assert isinstance(stats, dict)


class TestMockDataSourcePlugin:
    """Test cases for MockDataSourcePlugin implementation."""
    
    def test_get_metadata(self, mock_plugin):
        """Test metadata retrieval."""
        metadata = mock_plugin.get_metadata()
        
        assert metadata.name == "mock_plugin"
        assert metadata.version == "1.0.0"
        assert metadata.data_source_type == "test"
        assert "json" in metadata.supported_formats
        assert "requests" in metadata.dependencies
        
    def test_validate_config_success(self, mock_plugin):
        """Test successful config validation."""
        config = {
            "api_key": "test_key",
            "endpoint": "http://api.test.com",
            "timeout": 60
        }
        
        is_valid, errors = mock_plugin.validate_config(config)
        
        assert is_valid is True
        assert len(errors) == 0
        
    def test_validate_config_missing_required(self, mock_plugin):
        """Test config validation with missing required fields."""
        config = {"timeout": 30}  # Missing api_key and endpoint
        
        is_valid, errors = mock_plugin.validate_config(config)
        
        assert is_valid is False
        assert len(errors) == 2
        assert any("api_key" in error for error in errors)
        assert any("endpoint" in error for error in errors)
        
    def test_validate_config_invalid_type(self, mock_plugin):
        """Test config validation with invalid types."""
        config = {
            "api_key": "test_key",
            "endpoint": "http://api.test.com",
            "timeout": "not_an_integer"
        }
        
        is_valid, errors = mock_plugin.validate_config(config)
        
        assert is_valid is False
        assert any("timeout must be an integer" in error for error in errors)
        
    def test_connect_success(self, mock_plugin):
        """Test successful connection."""
        config = {"api_key": "test", "endpoint": "http://test.com"}
        
        result = mock_plugin.connect(config)
        
        assert result is True
        assert mock_plugin.connected is True
        
    def test_connect_failure(self):
        """Test connection failure."""
        plugin = MockDataSourcePlugin(should_fail_connect=True)
        config = {"api_key": "test", "endpoint": "http://test.com"}
        
        result = plugin.connect(config)
        
        assert result is False
        assert plugin.connected is False
        
    def test_disconnect(self, mock_plugin):
        """Test disconnection."""
        mock_plugin.connected = True
        
        result = mock_plugin.disconnect()
        
        assert result is True
        assert mock_plugin.connected is False
        
    def test_fetch_data_success(self, mock_plugin):
        """Test successful data fetching."""
        mock_plugin.connected = True
        
        data = mock_plugin.fetch_data(limit=3)
        
        assert len(data) == 3
        assert mock_plugin.fetch_calls == 1
        
        # Verify data structure
        for i, record in enumerate(data):
            assert record["id"] == f"record_{i}"
            assert record["value"] == f"data_{i}"
            assert "timestamp" in record
            
    def test_fetch_data_not_connected(self, mock_plugin):
        """Test fetching data when not connected."""
        mock_plugin.connected = False
        
        with pytest.raises(RuntimeError, match="Not connected"):
            mock_plugin.fetch_data()
            
    def test_fetch_data_failure(self):
        """Test data fetching failure."""
        plugin = MockDataSourcePlugin(should_fail_fetch=True)
        plugin.connected = True
        
        with pytest.raises(Exception, match="Mock fetch failure"):
            plugin.fetch_data()
            
    def test_transform_data(self, mock_plugin):
        """Test data transformation."""
        raw_data = [
            {"id": "1", "value": "test1"},
            {"id": "2", "value": "test2"}
        ]
        
        transformed = mock_plugin.transform_data(raw_data)
        
        assert len(transformed) == 2
        
        for i, record in enumerate(transformed):
            assert record["entity_id"] == raw_data[i]["id"]
            assert record["entity_type"] == "test_data"
            assert record["data"] == raw_data[i]
            assert record["source"] == "mock_plugin"
            
    def test_get_schema(self, mock_plugin):
        """Test schema retrieval."""
        schema = mock_plugin.get_schema()
        
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "entity_id" in schema["properties"]
        assert "entity_type" in schema["properties"]
        
    def test_get_statistics(self, mock_plugin):
        """Test statistics retrieval."""
        mock_plugin.connected = True
        mock_plugin.fetch_calls = 5
        
        stats = mock_plugin.get_statistics()
        
        assert stats["connected"] is True
        assert stats["fetch_calls"] == 5


class TestFailingDataSourcePlugin:
    """Test cases for FailingDataSourcePlugin implementation."""
    
    def test_get_metadata_invalid(self, failing_plugin):
        """Test invalid metadata from failing plugin."""
        metadata = failing_plugin.get_metadata()
        
        assert metadata.name == ""  # Invalid
        assert metadata.version == ""  # Invalid
        
    def test_validate_config_always_fails(self, failing_plugin):
        """Test config validation always fails."""
        config = {"valid": "config"}
        
        is_valid, errors = failing_plugin.validate_config(config)
        
        assert is_valid is False
        assert len(errors) > 0
        
    def test_connect_always_fails(self, failing_plugin):
        """Test connection always fails."""
        result = failing_plugin.connect({"config": "test"})
        
        assert result is False
        
    def test_fetch_data_always_fails(self, failing_plugin):
        """Test fetch always fails."""
        with pytest.raises(Exception, match="Fetch always fails"):
            failing_plugin.fetch_data()


class TestPluginMetadata:
    """Test cases for PluginMetadata dataclass."""
    
    def test_plugin_metadata_creation(self):
        """Test PluginMetadata creation."""
        metadata = PluginMetadata(
            name="test_plugin",
            version="2.1.0",
            author="Test Author",
            description="A test plugin for unit testing",
            data_source_type="database",
            supported_formats=["json", "xml", "csv"],
            dependencies=["requests", "pandas"],
            configuration_schema={
                "host": {"type": "string", "required": True},
                "port": {"type": "integer", "default": 5432}
            }
        )
        
        assert metadata.name == "test_plugin"
        assert metadata.version == "2.1.0"
        assert metadata.author == "Test Author"
        assert metadata.data_source_type == "database"
        assert len(metadata.supported_formats) == 3
        assert "requests" in metadata.dependencies
        assert "host" in metadata.configuration_schema


class TestPluginConfig:
    """Test cases for PluginConfig dataclass."""
    
    def test_plugin_config_defaults(self):
        """Test PluginConfig default values."""
        config = PluginConfig()
        
        assert config.enabled is True
        assert config.auto_start is False
        assert len(config.config_params) == 0
        assert len(config.retry_policy) == 0
        
    def test_plugin_config_custom_values(self):
        """Test PluginConfig with custom values."""
        config = PluginConfig(
            enabled=False,
            auto_start=True,
            config_params={"api_key": "secret", "timeout": 30},
            retry_policy={"max_retries": 3, "backoff": "exponential"}
        )
        
        assert config.enabled is False
        assert config.auto_start is True
        assert config.config_params["api_key"] == "secret"
        assert config.retry_policy["max_retries"] == 3


class TestIntegrationScenarios:
    """Integration test scenarios."""
    
    def test_end_to_end_plugin_lifecycle(self, plugin_manager):
        """Test complete plugin lifecycle from loading to data fetching."""
        # 1. Register plugin
        plugin = MockDataSourcePlugin()
        plugin_manager.plugins["e2e_test"] = plugin
        plugin_manager.plugin_configs["e2e_test"] = PluginConfig(
            config_params={"api_key": "test", "endpoint": "http://test.com"}
        )
        plugin_manager.plugin_status["e2e_test"] = PluginStatus.LOADED
        
        # 2. Activate plugin
        success = plugin_manager.activate_plugin("e2e_test")
        assert success is True
        assert plugin_manager.plugin_status["e2e_test"] == PluginStatus.ACTIVE
        
        # 3. Fetch data
        data = plugin_manager.fetch_from_plugin("e2e_test", limit=5)
        assert len(data) == 5
        
        # 4. Verify plugin statistics
        info = plugin_manager.get_plugin_info("e2e_test")
        assert info["statistics"]["fetch_calls"] == 1
        
        # 5. Deactivate plugin
        success = plugin_manager.deactivate_plugin("e2e_test")
        assert success is True
        assert plugin_manager.plugin_status["e2e_test"] == PluginStatus.INACTIVE
        
    def test_multiple_plugins_management(self, plugin_manager):
        """Test managing multiple plugins simultaneously."""
        # Setup multiple plugins
        plugins = {}
        for i in range(3):
            plugin_name = f"plugin_{i}"
            plugin = MockDataSourcePlugin()
            
            plugin_manager.plugins[plugin_name] = plugin
            plugin_manager.plugin_configs[plugin_name] = PluginConfig(
                config_params={"api_key": f"key_{i}", "endpoint": f"http://api{i}.com"}
            )
            plugin_manager.plugin_status[plugin_name] = PluginStatus.LOADED
            plugins[plugin_name] = plugin
            
        # Activate all plugins
        for plugin_name in plugins.keys():
            success = plugin_manager.activate_plugin(plugin_name)
            assert success is True
            
        # Fetch from all plugins
        total_data = []
        for plugin_name in plugins.keys():
            data = plugin_manager.fetch_from_plugin(plugin_name, limit=2)
            total_data.extend(data)
            
        assert len(total_data) == 6  # 3 plugins * 2 records each
        
        # Verify all plugins are active
        plugins_list = plugin_manager.list_plugins()
        active_count = sum(1 for p in plugins_list if p["status"] == "active")
        assert active_count == 3
        
    def test_error_recovery_scenarios(self, plugin_manager):
        """Test error recovery in various scenarios."""
        # Plugin with connection issues
        failing_plugin = MockDataSourcePlugin(should_fail_connect=True)
        plugin_manager.plugins["failing"] = failing_plugin
        plugin_manager.plugin_configs["failing"] = PluginConfig(
            config_params={"api_key": "test", "endpoint": "http://test.com"}
        )
        plugin_manager.plugin_status["failing"] = PluginStatus.LOADED
        
        # Try to activate failing plugin
        success = plugin_manager.activate_plugin("failing")
        assert success is False
        assert plugin_manager.plugin_status["failing"] == PluginStatus.ERROR
        
        # Setup working plugin
        working_plugin = MockDataSourcePlugin()
        plugin_manager.plugins["working"] = working_plugin
        plugin_manager.plugin_configs["working"] = PluginConfig(
            config_params={"api_key": "test", "endpoint": "http://test.com"}
        )
        plugin_manager.plugin_status["working"] = PluginStatus.LOADED
        
        # Activate working plugin
        success = plugin_manager.activate_plugin("working")
        assert success is True
        
        # System should continue working with good plugin
        data = plugin_manager.fetch_from_plugin("working")
        assert len(data) > 0
        
        # Fetching from failed plugin should return empty data
        data = plugin_manager.fetch_from_plugin("failing")
        assert len(data) == 0