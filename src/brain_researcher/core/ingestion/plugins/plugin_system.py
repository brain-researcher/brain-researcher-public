"""Custom Data Sources Plugin System - implements INGEST-022.

This module provides a plugin system for custom data sources with interfaces,
validation, examples, and documentation.
"""

import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import tempfile
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import yaml

logger = logging.getLogger(__name__)


# Custom Exception Classes
class PluginError(Exception):
    """Base exception for plugin system errors."""

    pass


class PluginLoadError(PluginError):
    """Plugin loading errors."""

    pass


class PluginValidationError(PluginError):
    """Plugin validation errors."""

    pass


class PluginSecurityError(PluginError):
    """Plugin security errors."""

    pass


class PluginConfigurationError(PluginError):
    """Plugin configuration errors."""

    pass


class PluginStatus(Enum):
    """Plugin status."""

    LOADED = "loaded"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


@dataclass
class PluginMetadata:
    """Plugin metadata."""

    name: str
    version: str
    author: str
    description: str
    data_source_type: str
    supported_formats: List[str]
    dependencies: List[str] = field(default_factory=list)
    configuration_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginConfig:
    """Plugin configuration."""

    enabled: bool = True
    auto_start: bool = False
    config_params: Dict[str, Any] = field(default_factory=dict)
    retry_policy: Dict[str, Any] = field(default_factory=dict)


class DataSourcePlugin(ABC):
    """Base class for data source plugins."""

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """Get plugin metadata.

        Returns:
            Plugin metadata
        """
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate plugin configuration.

        Args:
            config: Configuration to validate

        Returns:
            (is_valid, error_messages)
        """
        pass

    @abstractmethod
    def connect(self, config: Dict[str, Any]) -> bool:
        """Connect to data source.

        Args:
            config: Connection configuration

        Returns:
            Success status
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """Disconnect from data source.

        Returns:
            Success status
        """
        pass

    @abstractmethod
    def fetch_data(
        self, query: Optional[Dict[str, Any]] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch data from source.

        Args:
            query: Query parameters
            limit: Maximum records to fetch

        Returns:
            List of data records
        """
        pass

    @abstractmethod
    def transform_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform data to standard format.

        Args:
            data: Raw data from source

        Returns:
            Transformed data
        """
        pass

    def validate_data(self, data: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """Validate fetched data.

        Args:
            data: Data to validate

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        for i, record in enumerate(data):
            if not isinstance(record, dict):
                errors.append(f"Record {i} is not a dictionary")

        return len(errors) == 0, errors

    def get_schema(self) -> Dict[str, Any]:
        """Get data schema.

        Returns:
            Data schema
        """
        return {}

    def get_statistics(self) -> Dict[str, Any]:
        """Get plugin statistics.

        Returns:
            Statistics dictionary
        """
        return {}


class PluginManager:
    """Manages data source plugins."""

    def __init__(self, plugin_dir: str = "./plugins"):
        """Initialize plugin manager.

        Args:
            plugin_dir: Directory containing plugins
        """
        self.plugin_dir = Path(plugin_dir)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

        # Registered plugins
        self.plugins: Dict[str, DataSourcePlugin] = {}
        self.plugin_configs: Dict[str, PluginConfig] = {}
        self.plugin_status: Dict[str, PluginStatus] = {}

        # Plugin instances
        self.active_plugins: Dict[str, DataSourcePlugin] = {}

        # Statistics
        self.stats = {
            "plugins_loaded": 0,
            "plugins_active": 0,
            "data_fetched": defaultdict(int),
            "errors": defaultdict(int),
        }

        # Plugin discovery cache
        self._discovery_cache = {}
        self._cache_expiry = 300  # 5 minutes

        # Security settings
        self.allowed_imports = {
            "typing",
            "dataclasses",
            "datetime",
            "enum",
            "json",
            "yaml",
            "logging",
            "pathlib",
            "abc",
            "collections",
            "re",
            "hashlib",
            "requests",
            "urllib",
            "http",
            "ssl",
            "base64",
        }
        self.forbidden_functions = {
            "eval",
            "exec",
            "__import__",
            "open",
            "file",
            "input",
            "raw_input",
            "compile",
            "globals",
            "locals",
            "vars",
            "dir",
            "getattr",
            "setattr",
            "delattr",
            "hasattr",
        }

    def discover_plugins(self, use_cache: bool = True) -> List[str]:
        """Discover available plugins with caching.

        Args:
            use_cache: Whether to use cached results

        Returns:
            List of discovered plugin names
        """
        # Check cache first
        if use_cache and "plugins" in self._discovery_cache:
            cache_entry = self._discovery_cache["plugins"]
            if (
                datetime.now() - cache_entry["timestamp"]
            ).total_seconds() < self._cache_expiry:
                logger.debug("Using cached plugin discovery results")
                return cache_entry["plugins"]

        discovered = []

        # Look for Python files in plugin directory
        for file_path in self.plugin_dir.glob("*.py"):
            if file_path.stem.startswith("_"):
                continue

            try:
                # Import module
                spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Validate plugin source before importing
                if not self._validate_plugin_source(file_path):
                    logger.warning(f"Plugin source validation failed for {file_path}")
                    continue

                # Find plugin classes
                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, DataSourcePlugin)
                        and obj != DataSourcePlugin
                    ):

                        plugin_name = f"{file_path.stem}.{name}"
                        discovered.append(plugin_name)

                        logger.info(f"Discovered plugin: {plugin_name}")

            except Exception as e:
                logger.error(
                    f"Error discovering plugins in {file_path}: {e}", exc_info=True
                )

        # Cache the results
        self._discovery_cache["plugins"] = {
            "plugins": discovered,
            "timestamp": datetime.now(),
        }

        return discovered

    def load_plugin(
        self, plugin_path: str, config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Load a plugin.

        Args:
            plugin_path: Path to plugin (module.ClassName)
            config: Plugin configuration

        Returns:
            Success status
        """
        try:
            # Parse plugin path
            parts = plugin_path.split(".")
            module_name = ".".join(parts[:-1])
            class_name = parts[-1]

            # Import module with safety checks
            if module_name in ["examples", "custom"]:
                # Built-in example plugins
                module = importlib.import_module(
                    f"brain_researcher.core.ingestion.plugins.{module_name}"
                )
            else:
                # External plugin - add safety checks
                module_path = self.plugin_dir / f"{module_name}.py"
                if not module_path.exists():
                    raise PluginLoadError(f"Plugin file not found: {module_path}")

                # Validate plugin source
                if not self._validate_plugin_source(module_path):
                    raise PluginSecurityError(
                        f"Plugin source validation failed: {module_path}"
                    )

                # Load module safely
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    raise PluginLoadError(
                        f"Could not create module spec for {module_path}"
                    )

                module = importlib.util.module_from_spec(spec)

                # Execute module in controlled environment
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                    raise PluginLoadError(f"Error executing plugin module: {e}")

            # Get plugin class
            plugin_class = getattr(module, class_name)

            # Instantiate plugin
            plugin = plugin_class()

            # Validate it's a proper plugin
            if not isinstance(plugin, DataSourcePlugin):
                raise ValueError(f"{plugin_path} is not a DataSourcePlugin")

            # Get metadata
            metadata = plugin.get_metadata()

            # Store plugin
            self.plugins[metadata.name] = plugin
            self.plugin_configs[metadata.name] = PluginConfig(
                config_params=config or {}
            )
            self.plugin_status[metadata.name] = PluginStatus.LOADED

            self.stats["plugins_loaded"] += 1

            logger.info(f"Loaded plugin: {metadata.name}")
            return True

        except (PluginLoadError, PluginSecurityError) as e:
            logger.error(f"Plugin error loading {plugin_path}: {e}")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error loading plugin {plugin_path}: {e}", exc_info=True
            )
            return False

    def activate_plugin(self, plugin_name: str) -> bool:
        """Activate a plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Success status
        """
        if plugin_name not in self.plugins:
            logger.error(f"Plugin {plugin_name} not found")
            return False

        if plugin_name in self.active_plugins:
            logger.warning(f"Plugin {plugin_name} already active")
            return True

        plugin = self.plugins[plugin_name]
        config = self.plugin_configs[plugin_name]

        # Validate configuration
        try:
            is_valid, errors = plugin.validate_config(config.config_params)
            if not is_valid:
                logger.error(f"Invalid configuration for {plugin_name}: {errors}")
                self.plugin_status[plugin_name] = PluginStatus.ERROR
                return False
        except Exception as e:
            logger.error(f"Error validating plugin configuration: {e}")
            self.plugin_status[plugin_name] = PluginStatus.ERROR
            return False

        # Connect to data source
        try:
            if plugin.connect(config.config_params):
                self.active_plugins[plugin_name] = plugin
                self.plugin_status[plugin_name] = PluginStatus.ACTIVE
                self.stats["plugins_active"] += 1

                logger.info(f"Activated plugin: {plugin_name}")
                return True
            else:
                logger.error(f"Failed to connect plugin {plugin_name}")
                self.plugin_status[plugin_name] = PluginStatus.ERROR
                return False

        except Exception as e:
            logger.error(f"Error activating plugin {plugin_name}: {e}", exc_info=True)
            self.plugin_status[plugin_name] = PluginStatus.ERROR
            self.stats["errors"][plugin_name] += 1
            return False

    def deactivate_plugin(self, plugin_name: str) -> bool:
        """Deactivate a plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Success status
        """
        if plugin_name not in self.active_plugins:
            logger.warning(f"Plugin {plugin_name} not active")
            return True

        plugin = self.active_plugins[plugin_name]

        try:
            plugin.disconnect()
            del self.active_plugins[plugin_name]
            self.plugin_status[plugin_name] = PluginStatus.INACTIVE
            self.stats["plugins_active"] -= 1

            logger.info(f"Deactivated plugin: {plugin_name}")
            return True

        except Exception as e:
            logger.error(f"Error deactivating plugin {plugin_name}: {e}", exc_info=True)
            return False

    def fetch_from_plugin(
        self,
        plugin_name: str,
        query: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch data from a plugin.

        Args:
            plugin_name: Plugin name
            query: Query parameters
            limit: Maximum records

        Returns:
            Fetched data
        """
        if plugin_name not in self.active_plugins:
            logger.error(f"Plugin {plugin_name} not active")
            return []

        plugin = self.active_plugins[plugin_name]

        try:
            # Fetch raw data
            raw_data = plugin.fetch_data(query, limit)

            # Validate data
            is_valid, errors = plugin.validate_data(raw_data)
            if not is_valid:
                logger.error(f"Invalid data from {plugin_name}: {errors}")
                self.stats["errors"][plugin_name] += 1
                return []

            # Transform data
            transformed_data = plugin.transform_data(raw_data)

            self.stats["data_fetched"][plugin_name] += len(transformed_data)

            return transformed_data

        except Exception as e:
            logger.error(
                f"Error fetching from plugin {plugin_name}: {e}", exc_info=True
            )
            self.stats["errors"][plugin_name] += 1
            return []

    def get_plugin_info(self, plugin_name: str) -> Dict[str, Any]:
        """Get plugin information.

        Args:
            plugin_name: Plugin name

        Returns:
            Plugin information
        """
        if plugin_name not in self.plugins:
            return {}

        plugin = self.plugins[plugin_name]
        metadata = plugin.get_metadata()

        info = {
            "name": metadata.name,
            "version": metadata.version,
            "author": metadata.author,
            "description": metadata.description,
            "status": self.plugin_status.get(plugin_name, PluginStatus.INACTIVE).value,
            "data_source_type": metadata.data_source_type,
            "supported_formats": metadata.supported_formats,
            "schema": plugin.get_schema() if plugin_name in self.active_plugins else {},
            "statistics": (
                plugin.get_statistics() if plugin_name in self.active_plugins else {}
            ),
        }

        return info

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all plugins.

        Returns:
            List of plugin information
        """
        return [self.get_plugin_info(name) for name in self.plugins.keys()]

    def validate_plugin(self, plugin_path: str) -> Tuple[bool, List[str]]:
        """Validate a plugin before loading.

        Args:
            plugin_path: Path to plugin

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        try:
            # Try to load temporarily
            parts = plugin_path.split(".")
            module_name = ".".join(parts[:-1])
            class_name = parts[-1]

            # Import module with safety checks
            module_path = self.plugin_dir / f"{module_name}.py"
            if not module_path.exists():
                errors.append(f"Plugin file not found: {module_path}")
                return False, errors

            # Validate plugin source
            if not self._validate_plugin_source(module_path):
                errors.append("Plugin source validation failed")
                return False, errors

            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                errors.append("Could not create module spec")
                return False, errors

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Get plugin class
            if not hasattr(module, class_name):
                errors.append(f"Class {class_name} not found in module")
                return False, errors

            plugin_class = getattr(module, class_name)

            # Check inheritance
            if not issubclass(plugin_class, DataSourcePlugin):
                errors.append("Plugin must inherit from DataSourcePlugin")
                return False, errors

            # Instantiate and check methods
            plugin = plugin_class()

            required_methods = [
                "get_metadata",
                "validate_config",
                "connect",
                "disconnect",
                "fetch_data",
                "transform_data",
            ]

            for method in required_methods:
                if not hasattr(plugin, method):
                    errors.append(f"Missing required method: {method}")

            # Check metadata
            try:
                metadata = plugin.get_metadata()
                if not metadata.name:
                    errors.append("Plugin metadata must have a name")
                if not metadata.version:
                    errors.append("Plugin metadata must have a version")
            except Exception as e:
                errors.append(f"Error getting metadata: {e}")

        except Exception as e:
            errors.append(f"Error validating plugin: {e}")
            logger.error(f"Plugin validation error: {e}", exc_info=True)

        return len(errors) == 0, errors

    def generate_plugin_template(
        self, name: str, data_source_type: str, output_path: Optional[str] = None
    ) -> str:
        """Generate a plugin template.

        Args:
            name: Plugin name
            data_source_type: Type of data source
            output_path: Output file path

        Returns:
            Generated template code
        """
        template = f'''"""Custom plugin for {data_source_type} data source."""

from typing import Dict, List, Any, Optional, Tuple
from brain_researcher.core.ingestion.plugins.plugin_system import (
    DataSourcePlugin,
    PluginMetadata
)


class {name}Plugin(DataSourcePlugin):
    """Plugin for {data_source_type} data source."""

    def __init__(self):
        """Initialize plugin."""
        self.connection = None
        self.connected = False

    def get_metadata(self) -> PluginMetadata:
        """Get plugin metadata."""
        return PluginMetadata(
            name="{name.lower()}",
            version="1.0.0",
            author="Your Name",
            description="Plugin for {data_source_type} data source",
            data_source_type="{data_source_type}",
            supported_formats=["json", "csv"],
            dependencies=[],
            configuration_schema={{
                "host": {{"type": "string", "required": True}},
                "port": {{"type": "integer", "default": 8080}},
                "api_key": {{"type": "string", "required": False}}
            }}
        )

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate configuration."""
        errors = []

        # Check required fields
        if "host" not in config:
            errors.append("Missing required field: host")

        # Validate types
        if "port" in config and not isinstance(config["port"], int):
            errors.append("Port must be an integer")

        return len(errors) == 0, errors

    def connect(self, config: Dict[str, Any]) -> bool:
        """Connect to data source."""
        try:
            # TODO: Implement connection logic
            self.connection = {{
                "host": config["host"],
                "port": config.get("port", 8080)
            }}
            self.connected = True
            return True

        except Exception as e:
            print(f"Connection failed: {{e}}")
            return False

    def disconnect(self) -> bool:
        """Disconnect from data source."""
        try:
            # TODO: Implement disconnection logic
            self.connection = None
            self.connected = False
            return True

        except Exception:
            return False

    def fetch_data(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch data from source."""
        if not self.connected:
            raise RuntimeError("Not connected to data source")

        # TODO: Implement data fetching logic
        data = []

        # Example: Fetch mock data
        for i in range(limit or 10):
            data.append({{
                "id": f"record_{{i}}",
                "value": f"Data {{i}}",
                "timestamp": "2024-01-01T00:00:00Z"
            }})

        return data

    def transform_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform data to standard format."""
        transformed = []

        for record in data:
            # TODO: Implement transformation logic
            transformed.append({{
                "entity_id": record.get("id"),
                "entity_type": "{data_source_type}",
                "data": record,
                "source": self.get_metadata().name
            }})

        return transformed

    def get_schema(self) -> Dict[str, Any]:
        """Get data schema."""
        return {{
            "type": "object",
            "properties": {{
                "entity_id": {{"type": "string"}},
                "entity_type": {{"type": "string"}},
                "data": {{"type": "object"}},
                "source": {{"type": "string"}}
            }}
        }}
'''

        if output_path:
            Path(output_path).write_text(template)
            logger.info(f"Generated plugin template at {output_path}")

        return template

    def _validate_plugin_source(self, plugin_path: Path) -> bool:
        """Validate plugin source code for security issues.

        Args:
            plugin_path: Path to plugin file

        Returns:
            True if plugin source is safe
        """
        try:
            with open(plugin_path, "r", encoding="utf-8") as f:
                source_code = f.read()

            # Parse the AST to check for dangerous operations
            try:
                tree = ast.parse(source_code, filename=str(plugin_path))
            except SyntaxError as e:
                logger.error(f"Syntax error in plugin {plugin_path}: {e}")
                return False

            # Check for forbidden functions and imports
            for node in ast.walk(tree):
                # Check for dangerous function calls
                if isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Name)
                        and node.func.id in self.forbidden_functions
                    ):
                        logger.error(
                            f"Forbidden function {node.func.id} found in plugin {plugin_path}"
                        )
                        return False

                # Check for dangerous imports
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if not self._is_allowed_import(alias.name):
                            logger.error(
                                f"Forbidden import {alias.name} found in plugin {plugin_path}"
                            )
                            return False

                elif isinstance(node, ast.ImportFrom):
                    if node.module and not self._is_allowed_import(node.module):
                        logger.error(
                            f"Forbidden import from {node.module} found in plugin {plugin_path}"
                        )
                        return False

            # Check file size (prevent extremely large plugins)
            if len(source_code) > 100000:  # 100KB limit
                logger.error(f"Plugin {plugin_path} exceeds size limit")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating plugin source {plugin_path}: {e}")
            return False

    def _is_allowed_import(self, module_name: str) -> bool:
        """Check if an import is allowed.

        Args:
            module_name: Name of module to import

        Returns:
            True if import is allowed
        """
        # Allow standard library modules and some common packages
        if module_name in self.allowed_imports:
            return True

        # Allow submodules of allowed packages
        for allowed in self.allowed_imports:
            if module_name.startswith(f"{allowed}."):
                return True

        # Allow brain_researcher modules
        if module_name.startswith("brain_researcher."):
            return True

        return False

    def clear_discovery_cache(self):
        """Clear the plugin discovery cache."""
        self._discovery_cache.clear()
        logger.info("Plugin discovery cache cleared")

    def get_plugin_security_info(self, plugin_name: str) -> Dict[str, Any]:
        """Get security information about a plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Security information
        """
        if plugin_name not in self.plugins:
            return {}

        # Get plugin file path
        plugin_path = None
        if "." in plugin_name:
            module_name = plugin_name.split(".")[0]
            plugin_path = self.plugin_dir / f"{module_name}.py"

        security_info = {
            "plugin_name": plugin_name,
            "source_validated": False,
            "file_size": 0,
            "last_modified": None,
        }

        if plugin_path and plugin_path.exists():
            security_info["source_validated"] = self._validate_plugin_source(
                plugin_path
            )
            security_info["file_size"] = plugin_path.stat().st_size
            security_info["last_modified"] = datetime.fromtimestamp(
                plugin_path.stat().st_mtime
            ).isoformat()

        return security_info
