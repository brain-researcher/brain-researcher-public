"""
Package Resolver for Neuroimaging Tools

Detects and manages neuroimaging software packages from various sources.
Follows fallback chain: Environment Module → Container → Local Installation → Pure Python
Supports CVMFS/Neurodesk, local installations, and Python packages.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# CVMFS paths - configurable via environment
CVMFS_ROOT = os.getenv("BR_CVMFS_ROOT", "/cvmfs")
NEURODESK = os.path.join(CVMFS_ROOT, "neurodesk.ardc.edu.au")
NEURODESK_CONTAINERS = f"{NEURODESK}/containers"
NEURODESK_MODULES = f"{NEURODESK}/neurodesk-modules"


class BackendType(Enum):
    """Available backend types for tool execution."""
    MODULE = "module"  # Module-loaded tool (e.g., from CVMFS)
    CONTAINER = "container"  # Container execution (e.g., Apptainer/Docker)
    LOCAL = "local"  # Local installation
    PYTHON = "python"  # Pure Python implementation


@dataclass
class ToolBackend:
    """Information about an available tool backend."""
    type: BackendType
    name: str
    version: str
    path: Optional[str] = None
    module_name: Optional[str] = None
    container_path: Optional[str] = None
    python_module: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def priority(self) -> int:
        """Return priority for backend selection (lower is better)."""
        priorities = {
            BackendType.MODULE: 1,
            BackendType.CONTAINER: 2,
            BackendType.LOCAL: 3,
            BackendType.PYTHON: 4
        }
        return priorities.get(self.type, 999)
    
    def __str__(self) -> str:
        return f"{self.name}/{self.version} ({self.type.value})"


class PackageResolver:
    """Resolves neuroimaging software packages from multiple sources including CVMFS/Neurodesk."""
    
    def __init__(self):
        """Initialize the package resolver."""
        self._cvmfs_available = self._check_cvmfs()
        self._module_system = self._check_module_system()
        self._apptainer_available = self._check_apptainer()
        
        # Cache for discovered tools
        self._tool_cache: Dict[str, List[ToolBackend]] = {}
        
        logger.info(f"CVMFS available: {self._cvmfs_available}")
        logger.info(f"Module system: {self._module_system}")
        logger.info(f"Apptainer available: {self._apptainer_available}")
    
    def _check_cvmfs(self) -> bool:
        """Check if CVMFS is mounted and accessible."""
        try:
            neurodesk_path = Path(NEURODESK)
            if neurodesk_path.exists() and neurodesk_path.is_dir():
                # Check if containers directory exists
                containers_path = Path(NEURODESK_CONTAINERS)
                return containers_path.exists() and containers_path.is_dir()
        except Exception as e:
            logger.debug(f"CVMFS check failed: {e}")
        return False
    
    def _check_module_system(self) -> Optional[str]:
        """Check which module system is available (Lmod or Environment Modules)."""
        # Check for Lmod
        try:
            result = subprocess.run(
                ["module", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                if "Lmod" in result.stderr or "Lmod" in result.stdout:
                    return "lmod"
                else:
                    return "environment-modules"
        except Exception:
            pass
        
        # Check for Environment Modules
        try:
            result = subprocess.run(
                ["modulecmd", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return "environment-modules"
        except Exception:
            pass
        
        return None
    
    def _check_apptainer(self) -> bool:
        """Check if Apptainer (or Singularity) is available."""
        for cmd in ["apptainer", "singularity"]:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    return True
            except Exception:
                continue
        return False
    
    def find_tool(self, tool_name: str, version: Optional[str] = None) -> List[ToolBackend]:
        """
        Find all available backends for a tool.
        
        Args:
            tool_name: Name of the tool (e.g., "fsl", "mrtrix3")
            version: Optional specific version to find
            
        Returns:
            List of available backends sorted by priority
        """
        # Check cache first
        cache_key = f"{tool_name}:{version or 'latest'}"
        if cache_key in self._tool_cache:
            return self._tool_cache[cache_key]
        
        backends = []
        
        # 1. Check CVMFS modules
        if self._cvmfs_available and self._module_system:
            module_backends = self._find_cvmfs_modules(tool_name, version)
            backends.extend(module_backends)
        
        # 2. Check CVMFS containers directly
        if self._cvmfs_available and self._apptainer_available:
            container_backends = self._find_cvmfs_containers(tool_name, version)
            backends.extend(container_backends)
        
        # 3. Check local installations
        local_backends = self._find_local_installations(tool_name, version)
        backends.extend(local_backends)
        
        # 4. Check Python packages
        python_backends = self._find_python_packages(tool_name, version)
        backends.extend(python_backends)
        
        # Sort by priority
        backends.sort(key=lambda b: b.priority)
        
        # Cache the results
        self._tool_cache[cache_key] = backends
        
        return backends
    
    def _find_cvmfs_modules(self, tool_name: str, version: Optional[str] = None) -> List[ToolBackend]:
        """Find available CVMFS modules for a tool."""
        backends = []
        
        if not self._module_system:
            return backends
        
        try:
            # List available modules
            result = subprocess.run(
                ["module", "avail", tool_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Parse module output (usually in stderr for module avail)
            output = result.stderr + result.stdout
            
            for line in output.split('\n'):
                if tool_name in line.lower():
                    # Extract module name and version
                    # Format is usually: tool/version or tool-version
                    parts = line.strip().split()
                    for part in parts:
                        if '/' in part and tool_name in part.lower():
                            module_parts = part.split('/')
                            if len(module_parts) == 2:
                                mod_name, mod_version = module_parts
                                if version is None or version == mod_version:
                                    backend = ToolBackend(
                                        type=BackendType.MODULE,
                                        name=mod_name,
                                        version=mod_version,
                                        module_name=part,
                                        metadata={"module_system": self._module_system}
                                    )
                                    backends.append(backend)
        
        except Exception as e:
            logger.debug(f"Failed to search CVMFS modules: {e}")
        
        return backends
    
    def _find_cvmfs_containers(self, tool_name: str, version: Optional[str] = None) -> List[ToolBackend]:
        """Find available CVMFS containers for a tool."""
        backends = []
        
        if not self._cvmfs_available:
            return backends
        
        try:
            containers_path = Path(NEURODESK_CONTAINERS)
            
            # Search for matching directories
            for container_dir in containers_path.iterdir():
                if container_dir.is_dir() and tool_name in container_dir.name.lower():
                    # Directory format: tool_version_date
                    dir_name = container_dir.name
                    parts = dir_name.split('_')
                    
                    if len(parts) >= 2:
                        cont_name = parts[0]
                        cont_version = parts[1] if len(parts) > 1 else "unknown"
                        
                        # Check for .sif files
                        sif_files = list(container_dir.glob("*.sif"))
                        if sif_files:
                            if version is None or version in cont_version:
                                backend = ToolBackend(
                                    type=BackendType.CONTAINER,
                                    name=cont_name,
                                    version=cont_version,
                                    container_path=str(sif_files[0]),
                                    path=str(container_dir),
                                    metadata={"container_format": "singularity"}
                                )
                                backends.append(backend)
        
        except Exception as e:
            logger.debug(f"Failed to search CVMFS containers: {e}")
        
        return backends
    
    def _find_local_installations(self, tool_name: str, version: Optional[str] = None) -> List[ToolBackend]:
        """Find local installations of a tool."""
        backends = []
        
        # Common installation paths
        search_paths = [
            "/usr/local/bin",
            "/usr/bin",
            "/opt",
            os.path.expanduser("~/.local/bin"),
            "/usr/local/fsl/bin",  # FSL specific
            "/opt/freesurfer/bin",  # FreeSurfer specific
        ]
        
        # Add paths from PATH environment
        if "PATH" in os.environ:
            search_paths.extend(os.environ["PATH"].split(":"))
        
        for search_path in search_paths:
            path = Path(search_path)
            if path.exists():
                # Look for tool executables
                for executable in path.glob(f"{tool_name}*"):
                    if executable.is_file() and os.access(executable, os.X_OK):
                        # Try to get version
                        tool_version = self._get_local_tool_version(executable)
                        if version is None or version == tool_version:
                            backend = ToolBackend(
                                type=BackendType.LOCAL,
                                name=tool_name,
                                version=tool_version or "unknown",
                                path=str(executable),
                                metadata={"installation_path": str(path)}
                            )
                            backends.append(backend)
                            break  # Only need one local installation
        
        return backends
    
    def _find_python_packages(self, tool_name: str, version: Optional[str] = None) -> List[ToolBackend]:
        """Find Python package implementations."""
        backends = []
        
        # Mapping of tools to Python packages
        python_mappings = {
            "fsl": "nipype.interfaces.fsl",
            "ants": "antspyx",
            "freesurfer": "nipype.interfaces.freesurfer",
            "spm": "nipype.interfaces.spm",
            "mrtrix": "nipype.interfaces.mrtrix3",
            "afni": "nipype.interfaces.afni",
        }
        
        if tool_name.lower() in python_mappings:
            package = python_mappings[tool_name.lower()]
            try:
                # Try to import the package
                import importlib
                module = importlib.import_module(package)
                
                # Get version if available
                pkg_version = "unknown"
                try:
                    if hasattr(module, "__version__"):
                        pkg_version = module.__version__
                    else:
                        # Try parent package
                        parent_pkg = package.split(".")[0]
                        parent_module = importlib.import_module(parent_pkg)
                        if hasattr(parent_module, "__version__"):
                            pkg_version = parent_module.__version__
                except Exception:
                    pass
                
                if version is None or version == pkg_version:
                    backend = ToolBackend(
                        type=BackendType.PYTHON,
                        name=tool_name,
                        version=pkg_version,
                        python_module=package,
                        metadata={"python_package": package}
                    )
                    backends.append(backend)
            
            except ImportError:
                pass
        
        return backends
    
    def _get_local_tool_version(self, executable: Path) -> Optional[str]:
        """Try to get version of a local tool."""
        try:
            # Common version flags
            for flag in ["--version", "-version", "-v", "version"]:
                result = subprocess.run(
                    [str(executable), flag],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    # Parse version from output
                    output = result.stdout + result.stderr
                    lines = output.split('\n')
                    for line in lines:
                        if "version" in line.lower():
                            # Extract version number
                            import re
                            version_match = re.search(r'(\d+\.?\d*\.?\d*)', line)
                            if version_match:
                                return version_match.group(1)
                    return "unknown"
        except Exception:
            pass
        return None
    
    def _get_latest_version(self, backends: List[ToolBackend]) -> Optional[ToolBackend]:
        """Get the latest version from a list of backends."""
        if not backends:
            return None
        
        # Sort by version (simple string comparison for now)
        # In production, use proper version comparison
        sorted_backends = sorted(
            backends,
            key=lambda b: b.version if b.version != "unknown" else "0",
            reverse=True
        )
        return sorted_backends[0]
    
    def get_best_backend(
        self, 
        tool_name: str, 
        version: Optional[str] = None,
        prefer_backend: Optional[BackendType] = None
    ) -> Optional[ToolBackend]:
        """
        Get the best available backend for a tool.
        
        Args:
            tool_name: Name of the tool
            version: Optional specific version
            prefer_backend: Optional preferred backend type
            
        Returns:
            Best available backend or None if not found
        """
        backends = self.find_tool(tool_name, version)
        
        if not backends:
            return None
        
        # If preference specified, try to find matching backend
        if prefer_backend:
            for backend in backends:
                if backend.type == prefer_backend:
                    return backend
        
        # Return highest priority (lowest number)
        return backends[0] if backends else None
    
    def list_available_tools(self) -> Dict[str, List[ToolBackend]]:
        """List all available neuroimaging tools."""
        tools = {}
        
        # Common neuroimaging tools to search for
        common_tools = [
            "fsl", "freesurfer", "ants", "mrtrix3", "afni",
            "spm", "conn", "fmriprep", "mriqc", "qsiprep",
            "xcpd", "tedana", "micapipe", "fastsurfer"
        ]
        
        for tool in common_tools:
            backends = self.find_tool(tool)
            if backends:
                tools[tool] = backends
        
        return tools