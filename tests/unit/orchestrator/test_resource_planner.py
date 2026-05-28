"""Unit tests for resource planner (P3.7)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from brain_researcher.services.orchestrator.resources import (
    ResourcePlanner,
    ResourceRequirements,
    get_resource_planner,
    clear_planner_cache,
)


@pytest.fixture
def test_config():
    """Create a test configuration for resource planner."""
    return {
        "tools": {
            "fsl.bet": {
                "cpu_min": 1,
                "mem_mb_min": 512,
                "gpu": False,
                "time_min_default": 2,
                "description": "Brain extraction",
                "scaling_hints": [
                    {
                        "param": "input_file_size_mb",
                        "mem_mb_per_unit": 2,
                        "time_min_per_unit": 0.01,
                        "unit_description": "MB of input",
                    }
                ],
            },
            "fsl.feat": {
                "cpu_min": 2,
                "mem_mb_min": 2048,
                "gpu": False,
                "time_min_default": 30,
                "description": "fMRI analysis",
                "scaling_hints": [
                    {
                        "param": "n_volumes",
                        "mem_mb_per_unit": 10,
                        "time_min_per_unit": 0.5,
                        "unit_description": "number of volumes",
                    }
                ],
            },
            "gpu_tool": {
                "cpu_min": 4,
                "mem_mb_min": 8192,
                "gpu": True,
                "time_min_default": 60,
                "description": "GPU-accelerated tool",
            },
        },
        "resource_caps": {
            "cpu_max": 32,
            "mem_mb_max": 131072,
            "time_min_max": 2880,
            "gpu_max": 4,
        },
        "default": {
            "cpu_min": 1,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 10,
            "description": "Unknown tool",
        },
    }


@pytest.fixture
def config_file(test_config, tmp_path):
    """Create a temporary config file."""
    config_path = tmp_path / "tool_resources.yaml"
    with open(config_path, "w") as f:
        yaml.dump(test_config, f)
    return str(config_path)


@pytest.fixture
def planner(config_file):
    """Create a resource planner instance."""
    return ResourcePlanner(config_path=config_file)


@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary file with known size."""
    file_path = tmp_path / "test_input.nii.gz"
    file_path.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MB
    return str(file_path)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear planner cache before each test."""
    clear_planner_cache()
    yield
    clear_planner_cache()


class TestResourceRequirements:
    """Test ResourceRequirements dataclass."""

    def test_valid_requirements(self):
        """Test creating valid resource requirements."""
        req = ResourceRequirements(cpu=2, mem_mb=2048, gpu=0, time_min=30)
        assert req.cpu == 2
        assert req.mem_mb == 2048
        assert req.gpu == 0
        assert req.time_min == 30

    def test_invalid_cpu(self):
        """Test that cpu must be >= 1."""
        with pytest.raises(ValueError, match="cpu must be >= 1"):
            ResourceRequirements(cpu=0, mem_mb=1024, gpu=0, time_min=10)

    def test_invalid_mem(self):
        """Test that mem_mb must be >= 1."""
        with pytest.raises(ValueError, match="mem_mb must be >= 1"):
            ResourceRequirements(cpu=1, mem_mb=0, gpu=0, time_min=10)

    def test_invalid_gpu(self):
        """Test that gpu must be >= 0."""
        with pytest.raises(ValueError, match="gpu must be >= 0"):
            ResourceRequirements(cpu=1, mem_mb=1024, gpu=-1, time_min=10)

    def test_invalid_time(self):
        """Test that time_min must be >= 1."""
        with pytest.raises(ValueError, match="time_min must be >= 1"):
            ResourceRequirements(cpu=1, mem_mb=1024, gpu=0, time_min=0)


class TestResourcePlannerInit:
    """Test resource planner initialization."""

    def test_init_with_config_path(self, config_file):
        """Test initialization with explicit config path."""
        planner = ResourcePlanner(config_path=config_file)
        assert planner.config_path == config_file
        assert "fsl.bet" in planner.tools
        assert "fsl.feat" in planner.tools

    def test_init_missing_config(self, tmp_path):
        """Test initialization with missing config file."""
        missing_path = str(tmp_path / "nonexistent.yaml")
        planner = ResourcePlanner(config_path=missing_path)
        # Should not raise, should use empty defaults
        assert planner.tools == {}
        assert planner.caps == {}
        assert planner.default == {}

    def test_list_tools(self, planner):
        """Test listing available tools."""
        tools = planner.list_tools()
        assert "fsl.bet" in tools
        assert "fsl.feat" in tools
        assert "gpu_tool" in tools

    def test_get_tool_metadata(self, planner):
        """Test getting metadata for a specific tool."""
        meta = planner.get_tool_metadata("fsl.bet")
        assert meta["cpu_min"] == 1
        assert meta["mem_mb_min"] == 512
        assert meta["time_min_default"] == 2

    def test_get_tool_metadata_unknown(self, planner):
        """Test getting metadata for unknown tool returns default."""
        meta = planner.get_tool_metadata("unknown.tool")
        assert meta["cpu_min"] == 1
        assert meta["mem_mb_min"] == 1024
        assert meta["time_min_default"] == 10


class TestResourcePlanning:
    """Test resource requirement planning."""

    def test_plan_simple_tool(self, planner):
        """Test planning for a simple tool without scaling."""
        req = planner.plan("fsl.bet", params={}, input_paths=None)
        assert req.cpu == 1
        assert req.mem_mb == 512
        assert req.gpu == 0
        assert req.time_min == 2

    def test_plan_gpu_tool(self, planner):
        """Test planning for a GPU tool."""
        req = planner.plan("gpu_tool", params={}, input_paths=None)
        assert req.cpu == 4
        assert req.mem_mb == 8192
        assert req.gpu == 1
        assert req.time_min == 60

    def test_plan_with_param_scaling(self, planner):
        """Test planning with parameter-based scaling."""
        req = planner.plan("fsl.feat", params={"n_volumes": 100}, input_paths=None)
        # Base: 2048 MB + 100 * 10 = 3048 MB
        assert req.mem_mb == 3048
        # Base: 30 min + 100 * 0.5 = 80 min
        assert req.time_min == 80

    def test_plan_with_file_size_scaling(self, planner, temp_file):
        """Test planning with input file size scaling."""
        req = planner.plan("fsl.bet", params={}, input_paths=[temp_file])
        # File is 10 MB
        # Base: 512 MB + 10 * 2 = 532 MB
        assert req.mem_mb == 532
        # Base: 2 min + 10 * 0.01 = 2.1 min = 2 min (int)
        assert req.time_min == 2

    def test_plan_with_multiple_files(self, planner, tmp_path):
        """Test planning with multiple input files."""
        # Create two 5 MB files
        file1 = tmp_path / "input1.nii.gz"
        file2 = tmp_path / "input2.nii.gz"
        file1.write_bytes(b"x" * (5 * 1024 * 1024))
        file2.write_bytes(b"x" * (5 * 1024 * 1024))

        req = planner.plan("fsl.bet", params={}, input_paths=[str(file1), str(file2)])
        # Total: 10 MB
        # Base: 512 MB + 10 * 2 = 532 MB
        assert req.mem_mb == 532

    def test_plan_unknown_tool_uses_default(self, planner):
        """Test planning for unknown tool uses default values."""
        req = planner.plan("unknown.tool", params={}, input_paths=None)
        assert req.cpu == 1
        assert req.mem_mb == 1024
        assert req.gpu == 0
        assert req.time_min == 10

    def test_plan_with_missing_param(self, planner):
        """Test planning when scaling parameter is missing."""
        req = planner.plan("fsl.feat", params={}, input_paths=None)
        # Should use base values when n_volumes not provided
        assert req.mem_mb == 2048
        assert req.time_min == 30


class TestResourceCaps:
    """Test resource cap enforcement."""

    def test_cpu_cap_enforcement(self, planner):
        """Test that CPU is capped at maximum."""
        # Create a tool that would exceed cap
        planner.tools["huge_tool"] = {
            "cpu_min": 64,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 10,
        }
        req = planner.plan("huge_tool", params={}, input_paths=None)
        assert req.cpu == 32  # Capped at cpu_max

    def test_mem_cap_enforcement(self, planner):
        """Test that memory is capped at maximum."""
        planner.tools["huge_tool"] = {
            "cpu_min": 1,
            "mem_mb_min": 200000,
            "gpu": False,
            "time_min_default": 10,
        }
        req = planner.plan("huge_tool", params={}, input_paths=None)
        assert req.mem_mb == 131072  # Capped at mem_mb_max

    def test_time_cap_enforcement(self, planner):
        """Test that time is capped at maximum."""
        planner.tools["long_tool"] = {
            "cpu_min": 1,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 5000,
        }
        req = planner.plan("long_tool", params={}, input_paths=None)
        assert req.time_min == 2880  # Capped at time_min_max

    def test_gpu_cap_enforcement(self, planner):
        """Test that GPU count is capped at maximum."""
        planner.tools["multi_gpu"] = {
            "cpu_min": 1,
            "mem_mb_min": 1024,
            "gpu": True,
            "time_min_default": 10,
        }
        # Modify caps to allow multiple GPUs
        planner.caps["gpu_max"] = 2
        req = planner.plan("multi_gpu", params={}, input_paths=None)
        assert req.gpu <= 2


class TestMinimumEnforcement:
    """Test minimum resource enforcement."""

    def test_minimum_cpu(self, planner):
        """Test that CPU is at least 1."""
        planner.tools["tiny_tool"] = {
            "cpu_min": 0,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 10,
        }
        req = planner.plan("tiny_tool", params={}, input_paths=None)
        assert req.cpu >= 1

    def test_minimum_mem(self, planner):
        """Test that memory is at least 512 MB."""
        planner.tools["tiny_tool"] = {
            "cpu_min": 1,
            "mem_mb_min": 100,
            "gpu": False,
            "time_min_default": 10,
        }
        req = planner.plan("tiny_tool", params={}, input_paths=None)
        assert req.mem_mb >= 512

    def test_minimum_time(self, planner):
        """Test that time is at least 1 minute."""
        planner.tools["fast_tool"] = {
            "cpu_min": 1,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 0,
        }
        req = planner.plan("fast_tool", params={}, input_paths=None)
        assert req.time_min >= 1


class TestPlannerSingleton:
    """Test global planner instance management."""

    def test_get_resource_planner_singleton(self, config_file):
        """Test that get_resource_planner returns singleton."""
        planner1 = get_resource_planner(config_path=config_file)
        planner2 = get_resource_planner()
        assert planner1 is planner2

    def test_clear_planner_cache(self, config_file):
        """Test that cache clearing works."""
        planner1 = get_resource_planner(config_path=config_file)
        clear_planner_cache()
        planner2 = get_resource_planner(config_path=config_file)
        assert planner1 is not planner2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_plan_with_nonexistent_file(self, planner):
        """Test planning with nonexistent input file."""
        req = planner.plan("fsl.bet", params={}, input_paths=["/nonexistent/file.nii.gz"])
        # Should not crash, should use base values
        assert req.mem_mb == 512
        assert req.time_min == 2

    def test_plan_with_negative_scaling(self, planner):
        """Test planning with negative parameter value."""
        planner.tools["test_tool"] = {
            "cpu_min": 1,
            "mem_mb_min": 1024,
            "gpu": False,
            "time_min_default": 10,
            "scaling_hints": [
                {
                    "param": "n_items",
                    "mem_mb_per_unit": 10,
                    "time_min_per_unit": 1,
                }
            ],
        }
        req = planner.plan("test_tool", params={"n_items": -5}, input_paths=None)
        # Negative scaling should reduce values but not below minimums
        assert req.mem_mb >= 512
        assert req.time_min >= 1

    def test_plan_with_zero_param(self, planner):
        """Test planning with zero parameter value."""
        req = planner.plan("fsl.feat", params={"n_volumes": 0}, input_paths=None)
        # Should use base values
        assert req.mem_mb == 2048
        assert req.time_min == 30
