"""Resource planner for neuroimaging tools.

Infers CPU, memory, GPU, and time requirements from tool metadata and job parameters.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ResourceRequirements:
    """Resource requirements for a job."""

    cpu: int  # Number of CPU cores
    mem_mb: int  # Memory in MB
    gpu: int  # Number of GPUs (0 if not required)
    time_min: int  # Estimated time in minutes

    def __post_init__(self):
        """Validate resource values."""
        if self.cpu < 1:
            raise ValueError(f"cpu must be >= 1, got {self.cpu}")
        if self.mem_mb < 1:
            raise ValueError(f"mem_mb must be >= 1, got {self.mem_mb}")
        if self.gpu < 0:
            raise ValueError(f"gpu must be >= 0, got {self.gpu}")
        if self.time_min < 1:
            raise ValueError(f"time_min must be >= 1, got {self.time_min}")


class ResourcePlanner:
    """Plans resource requirements for neuroimaging tool execution."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize resource planner.

        Args:
            config_path: Path to tool_resources.yaml. If None, uses default location.
        """
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
        self.tools = self.config.get("tools", {})
        self.caps = self.config.get("resource_caps", {})
        self.default = self.config.get("default", {})

    def _get_default_config_path(self) -> str:
        """Get default config path using importlib.resources."""
        try:
            # Try Python 3.9+ importlib.resources API
            from importlib.resources import files

            config_dir = files("brain_researcher").joinpath("../configs")
            config_path = config_dir / "tool_resources.yaml"
            return str(config_path)
        except (ImportError, AttributeError):
            # Fallback to legacy approach for Python 3.7-3.8
            import importlib.resources as pkg_resources

            with pkg_resources.path("brain_researcher", "__init__.py") as p:
                return str(p.parent.parent / "configs" / "tool_resources.yaml")

    def _load_config(self) -> Dict[str, Any]:
        """Load tool resource configuration."""
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded tool resource config from {self.config_path}")
            return config
        except FileNotFoundError:
            logger.warning(
                f"Tool resource config not found at {self.config_path}, using defaults"
            )
            return {"tools": {}, "resource_caps": {}, "default": {}}
        except Exception as e:
            logger.error(f"Failed to load tool resource config: {e}")
            return {"tools": {}, "resource_caps": {}, "default": {}}

    def plan(
        self,
        tool_name: str,
        params: Dict[str, Any],
        input_paths: Optional[List[str]] = None,
    ) -> ResourceRequirements:
        """Plan resource requirements for a tool execution.

        Args:
            tool_name: Name of the tool (e.g., "fsl.bet", "freesurfer.recon-all")
            params: Tool parameters that may affect resource scaling
            input_paths: List of input file paths for size-based scaling

        Returns:
            ResourceRequirements with estimated CPU, memory, GPU, and time
        """
        # Get baseline requirements for this tool
        tool_meta = self.tools.get(tool_name, self.default)

        cpu = tool_meta.get("cpu_min", self.default.get("cpu_min", 1))
        mem_mb = tool_meta.get("mem_mb_min", self.default.get("mem_mb_min", 1024))
        gpu = 1 if tool_meta.get("gpu", self.default.get("gpu", False)) else 0
        time_min = tool_meta.get(
            "time_min_default", self.default.get("time_min_default", 10)
        )

        # Apply scaling hints based on parameters
        scaling_hints = tool_meta.get("scaling_hints", [])
        for hint in scaling_hints:
            param_name = hint.get("param")
            if not param_name:
                continue

            # Handle special parameter: input_file_size_mb
            if param_name == "input_file_size_mb" and input_paths:
                param_value = self._compute_total_file_size_mb(input_paths)
            else:
                param_value = params.get(param_name)

            if param_value is None:
                continue

            # Apply scaling
            mem_scale = hint.get("mem_mb_per_unit", 0)
            time_scale = hint.get("time_min_per_unit", 0)

            mem_mb += int(param_value * mem_scale)
            time_min += int(param_value * time_scale)

            logger.debug(
                f"Scaling: {param_name}={param_value} → mem+{int(param_value * mem_scale)}MB, time+{int(param_value * time_scale)}min"
            )

        # Apply resource caps
        cpu = min(cpu, self.caps.get("cpu_max", 32))
        mem_mb = min(mem_mb, self.caps.get("mem_mb_max", 131072))
        gpu = min(gpu, self.caps.get("gpu_max", 4))
        time_min = min(time_min, self.caps.get("time_min_max", 2880))

        # Ensure minimums
        cpu = max(cpu, 1)
        mem_mb = max(mem_mb, 512)
        time_min = max(time_min, 1)

        requirements = ResourceRequirements(
            cpu=cpu, mem_mb=mem_mb, gpu=gpu, time_min=time_min
        )

        logger.info(
            f"Resource plan for {tool_name}: cpu={cpu}, mem={mem_mb}MB, gpu={gpu}, time={time_min}min"
        )

        return requirements

    def _compute_total_file_size_mb(self, input_paths: List[str]) -> float:
        """Compute total size of input files in MB."""
        total_bytes = 0
        for path in input_paths:
            try:
                if os.path.exists(path):
                    total_bytes += os.path.getsize(path)
            except Exception as e:
                logger.warning(f"Failed to get size of {path}: {e}")
        return total_bytes / (1024 * 1024)

    def get_tool_metadata(self, tool_name: str) -> Dict[str, Any]:
        """Get metadata for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool metadata dict, or default if tool not found
        """
        return self.tools.get(tool_name, self.default)

    def list_tools(self) -> List[str]:
        """List all tools with resource metadata.

        Returns:
            List of tool names
        """
        return list(self.tools.keys())


# Global planner instance
_planner: Optional[ResourcePlanner] = None


def get_resource_planner(config_path: Optional[str] = None) -> ResourcePlanner:
    """Get or create global resource planner instance.

    Args:
        config_path: Optional config path to override default

    Returns:
        ResourcePlanner instance
    """
    global _planner
    if _planner is None or config_path is not None:
        _planner = ResourcePlanner(config_path=config_path)
    return _planner


def clear_planner_cache():
    """Clear the global planner instance (useful for testing)."""
    global _planner
    _planner = None
