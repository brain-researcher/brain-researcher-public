"""Agent Plugin System Integration.

This module integrates the plugin system (INGEST-022) with the agent service
to provide custom data source capabilities through plugins.
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional, Type, Tuple
from dataclasses import dataclass
from datetime import datetime

from brain_researcher.core.ingestion.plugins.plugin_system import (
    PluginManager,
    DataSourcePlugin,
    PluginMetadata,
    PluginConfig,
    PluginStatus
)
from brain_researcher.services.tools.tool_base import NeuroKGToolWrapper

logger = logging.getLogger(__name__)


@dataclass
class AgentPluginConfig:
    """Configuration for agent plugin integration."""
    
    auto_discover: bool = True
    auto_activate: bool = False
    plugin_directory: str = "./plugins"
    max_concurrent_plugins: int = 10
    plugin_timeout: int = 30  # seconds


class PluginDataSourceTool(NeuroKGToolWrapper):
    """Agent tool that wraps a data source plugin."""
    
    def __init__(self, plugin: DataSourcePlugin, plugin_manager):
        """Initialize plugin tool.
        
        Args:
            plugin: Data source plugin
            plugin_manager: Plugin manager instance
        """
        self.plugin = plugin
        self.plugin_manager = plugin_manager
        self.metadata = plugin.get_metadata()
        
    def get_tool_name(self) -> str:
        """Get tool name."""
        return f"plugin_{self.metadata.name}"
        
    def get_tool_description(self) -> str:
        """Get tool description."""
        return f"Data source plugin: {self.metadata.description}"
        
    async def run(self, **kwargs) -> Dict[str, Any]:
        """Execute plugin data fetching."""
        try:
            # Ensure plugin is active
            if not await self._ensure_plugin_active():
                return {
                    "error": f"Plugin {self.metadata.name} could not be activated",
                    "status": "failed"
                }
                
            # Extract parameters
            query = kwargs.get("query", {})
            limit = kwargs.get("limit", 100)
            
            # Fetch data from plugin
            raw_data = await asyncio.to_thread(
                self.plugin.fetch_data,
                query=query,
                limit=limit
            )
            
            # Transform data
            transformed_data = await asyncio.to_thread(
                self.plugin.transform_data,
                raw_data
            )
            
            # Validate data
            is_valid, errors = self.plugin.validate_data(transformed_data)
            
            if not is_valid:
                logger.warning(f"Data validation failed for plugin {self.metadata.name}: {errors}")
                
            return {
                "status": "success",
                "data": transformed_data,
                "plugin_name": self.metadata.name,
                "data_source_type": self.metadata.data_source_type,
                "validation_errors": errors if not is_valid else None,
                "record_count": len(transformed_data)
            }
            
        except Exception as e:
            logger.error(f"Error executing plugin {self.metadata.name}: {e}", exc_info=True)
            return {
                "error": str(e),
                "status": "failed",
                "plugin_name": self.metadata.name
            }
            
    async def _ensure_plugin_active(self) -> bool:
        """Ensure plugin is active."""
        plugin_name = self.metadata.name
        
        # Check if already active
        if plugin_name in self.plugin_manager.active_plugins:
            return True
            
        # Try to activate
        return self.plugin_manager.activate_plugin(plugin_name)
        
    def as_langchain_tool(self):
        """Convert to LangChain tool."""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:  # pragma: no cover
            pass # Fallback removed as langchain_core is the correct one
        
        return StructuredTool.from_function(
            func=self.run,
            name=self.get_tool_name(),
            description=self.get_tool_description()
        )


class AgentPluginManager:
    """Manages plugin integration with agent service."""
    
    def __init__(self, config: Optional[AgentPluginConfig] = None):
        """Initialize agent plugin manager.
        
        Args:
            config: Optional configuration
        """
        self.config = config or AgentPluginConfig()
        
        # Create core plugin manager
        self.plugin_manager = PluginManager(
            plugin_dir=self.config.plugin_directory
        )
        
        # Plugin tools
        self.plugin_tools: Dict[str, PluginDataSourceTool] = {}
        
        # Statistics
        self.stats = {
            "plugins_discovered": 0,
            "plugins_loaded": 0,
            "plugins_active": 0,
            "plugin_executions": 0,
            "execution_errors": 0
        }
        
    async def initialize(self) -> bool:
        """Initialize the plugin system.
        
        Returns:
            Success status
        """
        try:
            # Discover plugins
            if self.config.auto_discover:
                discovered = self.plugin_manager.discover_plugins()
                self.stats["plugins_discovered"] = len(discovered)
                
                logger.info(f"Discovered {len(discovered)} plugins")
                
                # Load discovered plugins
                for plugin_path in discovered:
                    success = self.plugin_manager.load_plugin(plugin_path)
                    if success:
                        self.stats["plugins_loaded"] += 1
                        
                        # Auto-activate if configured
                        if self.config.auto_activate:
                            plugin_name = plugin_path.split(".")[-2]  # Extract plugin name
                            if self.plugin_manager.activate_plugin(plugin_name):
                                self.stats["plugins_active"] += 1
                                
            # Create tools for active plugins
            await self._create_plugin_tools()
            
            logger.info(f"Plugin system initialized: {self.stats}")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing plugin system: {e}", exc_info=True)
            return False
            
    async def _create_plugin_tools(self):
        """Create agent tools for active plugins."""
        for plugin_name, plugin in self.plugin_manager.plugins.items():
            try:
                tool = PluginDataSourceTool(plugin, self.plugin_manager)
                self.plugin_tools[plugin_name] = tool
                
                logger.debug(f"Created tool for plugin: {plugin_name}")
                
            except Exception as e:
                logger.error(f"Error creating tool for plugin {plugin_name}: {e}")
                
    async def load_plugin(self, plugin_path: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """Load a specific plugin.
        
        Args:
            plugin_path: Path to plugin
            config: Optional plugin configuration
            
        Returns:
            Success status
        """
        try:
            success = self.plugin_manager.load_plugin(plugin_path, config)
            
            if success:
                self.stats["plugins_loaded"] += 1
                
                # Create tool for the new plugin
                plugin_name = plugin_path.split(".")[-2]
                if plugin_name in self.plugin_manager.plugins:
                    plugin = self.plugin_manager.plugins[plugin_name]
                    tool = PluginDataSourceTool(plugin, self.plugin_manager)
                    self.plugin_tools[plugin_name] = tool
                    
                logger.info(f"Loaded plugin: {plugin_path}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error loading plugin {plugin_path}: {e}")
            return False
            
    async def activate_plugin(self, plugin_name: str) -> bool:
        """Activate a plugin.
        
        Args:
            plugin_name: Plugin name
            
        Returns:
            Success status
        """
        try:
            success = self.plugin_manager.activate_plugin(plugin_name)
            
            if success:
                self.stats["plugins_active"] += 1
                logger.info(f"Activated plugin: {plugin_name}")
            else:
                logger.warning(f"Failed to activate plugin: {plugin_name}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error activating plugin {plugin_name}: {e}")
            return False
            
    async def deactivate_plugin(self, plugin_name: str) -> bool:
        """Deactivate a plugin.
        
        Args:
            plugin_name: Plugin name
            
        Returns:
            Success status
        """
        try:
            success = self.plugin_manager.deactivate_plugin(plugin_name)
            
            if success:
                self.stats["plugins_active"] -= 1
                logger.info(f"Deactivated plugin: {plugin_name}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error deactivating plugin {plugin_name}: {e}")
            return False
            
    async def execute_plugin(
        self,
        plugin_name: str,
        query: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Execute a plugin to fetch data.
        
        Args:
            plugin_name: Plugin name
            query: Query parameters
            limit: Maximum records
            
        Returns:
            Fetched data
        """
        try:
            self.stats["plugin_executions"] += 1
            
            data = await asyncio.to_thread(
                self.plugin_manager.fetch_from_plugin,
                plugin_name,
                query,
                limit
            )
            
            logger.debug(f"Executed plugin {plugin_name}, got {len(data)} records")
            return data
            
        except Exception as e:
            self.stats["execution_errors"] += 1
            logger.error(f"Error executing plugin {plugin_name}: {e}")
            raise
            
    def get_plugin_tools(self) -> List[PluginDataSourceTool]:
        """Get all plugin tools.
        
        Returns:
            List of plugin tools
        """
        return list(self.plugin_tools.values())
        
    def get_plugin_info(self, plugin_name: str) -> Dict[str, Any]:
        """Get information about a plugin.
        
        Args:
            plugin_name: Plugin name
            
        Returns:
            Plugin information
        """
        return self.plugin_manager.get_plugin_info(plugin_name)
        
    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all plugins.
        
        Returns:
            List of plugin information
        """
        return self.plugin_manager.list_plugins()
        
    async def validate_plugin(self, plugin_path: str) -> Tuple[bool, List[str]]:
        """Validate a plugin.
        
        Args:
            plugin_path: Plugin path
            
        Returns:
            (is_valid, error_messages)
        """
        return self.plugin_manager.validate_plugin(plugin_path)
        
    def generate_plugin_template(
        self,
        name: str,
        data_source_type: str,
        output_path: Optional[str] = None
    ) -> str:
        """Generate a plugin template.
        
        Args:
            name: Plugin name
            data_source_type: Data source type
            output_path: Output path
            
        Returns:
            Template code
        """
        return self.plugin_manager.generate_plugin_template(
            name, data_source_type, output_path
        )
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get plugin system statistics."""
        core_stats = self.plugin_manager.stats
        
        return {
            "agent_stats": self.stats,
            "core_stats": core_stats,
            "active_plugin_count": len(self.plugin_manager.active_plugins),
            "total_plugin_count": len(self.plugin_manager.plugins),
            "plugin_tools_count": len(self.plugin_tools)
        }


# Plugin tool registration helpers
class PluginToolRegistry:
    """Registry for plugin-based tools."""
    
    def __init__(self, agent_plugin_manager: AgentPluginManager):
        """Initialize registry.
        
        Args:
            agent_plugin_manager: Plugin manager
        """
        self.plugin_manager = agent_plugin_manager
        self.registered_tools: Dict[str, PluginDataSourceTool] = {}
        
    async def register_all_plugins(self, tool_registry) -> int:
        """Register all available plugins as tools.
        
        Args:
            tool_registry: Main tool registry
            
        Returns:
            Number of tools registered
        """
        plugin_tools = self.plugin_manager.get_plugin_tools()
        registered_count = 0
        
        for tool in plugin_tools:
            try:
                tool_registry.register_tool(tool)
                self.registered_tools[tool.get_tool_name()] = tool
                registered_count += 1
                
                logger.debug(f"Registered plugin tool: {tool.get_tool_name()}")
                
            except Exception as e:
                logger.error(f"Error registering plugin tool {tool.get_tool_name()}: {e}")
                
        logger.info(f"Registered {registered_count} plugin tools")
        return registered_count
        
    async def register_plugin(self, plugin_name: str, tool_registry) -> bool:
        """Register a specific plugin as a tool.
        
        Args:
            plugin_name: Plugin name
            tool_registry: Main tool registry
            
        Returns:
            Success status
        """
        if plugin_name in self.plugin_manager.plugin_tools:
            try:
                tool = self.plugin_manager.plugin_tools[plugin_name]
                tool_registry.register_tool(tool)
                self.registered_tools[tool.get_tool_name()] = tool
                
                logger.info(f"Registered plugin tool: {tool.get_tool_name()}")
                return True
                
            except Exception as e:
                logger.error(f"Error registering plugin tool {plugin_name}: {e}")
                
        return False
        
    def unregister_plugin(self, plugin_name: str, tool_registry) -> bool:
        """Unregister a plugin tool.
        
        Args:
            plugin_name: Plugin name
            tool_registry: Main tool registry
            
        Returns:
            Success status
        """
        tool_name = f"plugin_{plugin_name}"
        
        if tool_name in tool_registry.tools:
            del tool_registry.tools[tool_name]
            self.registered_tools.pop(tool_name, None)
            
            logger.info(f"Unregistered plugin tool: {tool_name}")
            return True
            
        return False


# Integration helper functions
async def setup_agent_plugins(
    agent_state_machine,
    config: Optional[AgentPluginConfig] = None
) -> AgentPluginManager:
    """Set up agent plugin integration.
    
    Args:
        agent_state_machine: Core agent state machine
        config: Optional plugin configuration
        
    Returns:
        Agent plugin manager
    """
    # Create plugin manager
    plugin_manager = AgentPluginManager(config)
    
    # Initialize plugin system
    success = await plugin_manager.initialize()
    
    if not success:
        logger.warning("Plugin system initialization failed")
        
    # Add to state machine
    agent_state_machine.plugin_manager = plugin_manager
    
    # Create tool registry helper
    tool_registry_helper = PluginToolRegistry(plugin_manager)
    agent_state_machine.plugin_tool_registry = tool_registry_helper
    
    logger.info("Agent plugin integration setup completed")
    
    return plugin_manager


async def register_plugins_with_tools(
    agent_state_machine,
    tool_registry
) -> int:
    """Register all plugins as tools in the tool registry.
    
    Args:
        agent_state_machine: Agent state machine with plugin manager
        tool_registry: Tool registry to add plugins to
        
    Returns:
        Number of plugins registered
    """
    if not hasattr(agent_state_machine, 'plugin_tool_registry'):
        logger.warning("Plugin tool registry not found in agent state machine")
        return 0
        
    return await agent_state_machine.plugin_tool_registry.register_all_plugins(tool_registry)


# Example plugin implementations
class ExampleAPIPlugin(DataSourcePlugin):
    """Example plugin for API data source."""
    
    def __init__(self):
        self.connected = False
        self.api_client = None
        
    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="example_api",
            version="1.0.0",
            author="Brain Researcher Team",
            description="Example API data source plugin",
            data_source_type="api",
            supported_formats=["json"],
            configuration_schema={
                "api_url": {"type": "string", "required": True},
                "api_key": {"type": "string", "required": False}
            }
        )
        
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = []
        
        if "api_url" not in config:
            errors.append("api_url is required")
            
        return len(errors) == 0, errors
        
    def connect(self, config: Dict[str, Any]) -> bool:
        try:
            # Mock connection
            self.api_client = {
                "url": config["api_url"],
                "key": config.get("api_key")
            }
            self.connected = True
            return True
        except Exception:
            return False
            
    def disconnect(self) -> bool:
        self.api_client = None
        self.connected = False
        return True
        
    def fetch_data(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("Not connected")
            
        # Mock data fetching
        data = []
        for i in range(min(limit or 10, 10)):
            data.append({
                "id": f"record_{i}",
                "title": f"Example Record {i}",
                "value": i * 10,
                "source": "example_api"
            })
            
        return data
        
    def transform_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Transform to standard format
        transformed = []
        
        for record in data:
            transformed.append({
                "entity_id": record["id"],
                "entity_type": "example_record",
                "title": record["title"],
                "properties": {
                    "value": record["value"],
                    "source": record["source"]
                },
                "metadata": {
                    "plugin": "example_api",
                    "fetched_at": datetime.now().isoformat()
                }
            })
            
        return transformed
