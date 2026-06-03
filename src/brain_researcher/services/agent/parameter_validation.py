"""
Enhanced Tool Parameter Validation System with API Discovery for Brain Researcher Agent

Provides schema-based validation, type checking, range validation, default value handling,
and automatic API documentation discovery for all tool parameters.
"""

import inspect
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.services.agent.error_handling import (
    AgentError,
    ErrorCategory,
    ErrorSeverity,
)


class ParameterType(str, Enum):
    """Supported parameter types for validation."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    FILE = "file"
    DIRECTORY = "directory"
    LIST = "list"
    DICT = "dict"
    ENUM = "enum"
    ARRAY = "array"  # NumPy array
    NIFTI_FILE = "nifti_file"  # Neuroimaging specific
    BIDS_DATASET = "bids_dataset"  # BIDS directory structure
    MODULE_NAME = "module_name"  # Neurodesk module name


@dataclass
class ValidationRule:
    """Validation rule for a parameter."""

    required: bool = True
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None  # Regex pattern
    choices: list[Any] | None = None  # For enum types
    custom_validator: Callable | None = None
    file_extensions: list[str] | None = None  # For file types
    array_shape: tuple | None = None  # For numpy arrays
    array_dtype: type | None = None


@dataclass
class ParameterSchema:
    """Schema definition for a tool parameter."""

    name: str
    param_type: ParameterType
    description: str
    default: Any = None
    validation_rules: ValidationRule = field(default_factory=ValidationRule)
    neurodesk_module: str | None = None  # Required Neurodesk module
    source: str | None = None  # Where this schema came from
    empirical_advice: str | None = None  # Domain-specific recommendations


class ParameterValidationResult(dict):
    """Validation result that supports both dict and attribute access."""

    def __init__(
        self,
        *args: Any,
        is_valid: bool | None = None,
        value: Any = None,
        message: str = "",
        suggested_value: Any = None,
        warnings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if args and is_valid is None and not any(
            arg is not None for arg in (value, message, suggested_value, warnings, metadata)
        ):
            dict.__init__(self, *args)
            return
        dict.__init__(
            self,
            is_valid=bool(is_valid),
            value=value,
            message=message,
            suggested_value=suggested_value,
            warnings=warnings or [],
            metadata=metadata or {},
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class ValidationSummary(dict):
    """Summary validation result for a tool."""

    def __init__(
        self,
        *args: Any,
        valid: bool | None = None,
        errors: dict[str, str] | None = None,
        warnings: list[str] | None = None,
        results: dict[str, ParameterValidationResult] | None = None,
        validated_params: dict[str, Any] | None = None,
        suggestions: dict[str, Any] | None = None,
    ):
        if args and valid is None and errors is None and warnings is None and results is None and validated_params is None and suggestions is None:
            dict.__init__(self, *args)
            return
        dict.__init__(
            self,
            valid=bool(valid),
            errors=errors or {},
            warnings=warnings or [],
            results=results or {},
            validated_params=validated_params or {},
            suggestions=suggestions or {},
        )

    def __getattr__(self, name: str) -> Any:
        if name == "is_valid":
            return self.get("valid")
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, dict) and not isinstance(other, ValidationSummary):
            return self.get("validated_params", {}) == other
        return dict.__eq__(self, other)

    def __contains__(self, key: object) -> bool:
        if dict.__contains__(self, key):
            return True
        validated = self.get("validated_params", {})
        return key in validated

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        validated = self.get("validated_params", {})
        if key in validated:
            return validated[key]
        return dict.__getitem__(self, key)

    def __len__(self) -> int:  # type: ignore[override]
        validated = self.get("validated_params", {})
        if validated:
            return max(dict.__len__(self), len(validated))
        return dict.__len__(self)


class NeuroimagingValidators:
    """Specialized validators for neuroimaging data."""

    @staticmethod
    def validate_path_security(path: str, strict: bool = True) -> bool:
        """
        Validate path against traversal attacks and suspicious patterns (P3.8).

        Args:
            path: Path to validate
            strict: If True, enforce strict validation rules

        Returns:
            True if path is safe

        Raises:
            ValueError: If path contains security risks
        """
        from brain_researcher.services.shared.path_validation import validate_path

        try:
            validate_path(path, strict=strict)
            return True
        except ValueError as e:
            raise ValueError(f"Path security validation failed: {e}") from e

    @staticmethod
    def validate_nifti_file(path: str) -> bool:
        """
        Validate that a file is a valid NIfTI file.

        Args:
            path: Path to the file

        Returns:
            True if valid NIfTI file

        Raises:
            ValueError: If not a valid NIfTI file
        """
        # P3.8: Check path security first
        NeuroimagingValidators.validate_path_security(path, strict=False)

        path_obj = Path(path)

        # Check file exists
        if not path_obj.exists():
            raise ValueError(f"File does not exist: {path}")

        # Check extension
        valid_extensions = ['.nii', '.nii.gz']
        if not any(str(path).endswith(ext) for ext in valid_extensions):
            raise ValueError(
                f"Invalid NIfTI file extension. Expected {valid_extensions}, got {path_obj.suffix}"
            )

        # Check file is readable
        if not path_obj.is_file():
            raise ValueError(f"Path is not a file: {path}")

        # Could add nibabel validation here if available
        try:
            import nibabel as nib
            nib.load(path)
        except ImportError:
            pass  # nibabel not available, skip deep validation
        except Exception as e:
            raise ValueError(f"Invalid NIfTI file: {e}") from e

        return True

    @staticmethod
    def validate_bids_dataset(path: str) -> bool:
        """
        Validate that a directory follows BIDS structure.

        Args:
            path: Path to the BIDS dataset

        Returns:
            True if valid BIDS dataset

        Raises:
            ValueError: If not a valid BIDS dataset
        """
        path_obj = Path(path)

        # Check directory exists
        if not path_obj.exists():
            raise ValueError(f"Directory does not exist: {path}")

        if not path_obj.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        # Check for required BIDS files
        required_files = ['dataset_description.json']
        for req_file in required_files:
            if not (path_obj / req_file).exists():
                raise ValueError(f"Missing required BIDS file: {req_file}")

        # Check for subject directories
        subject_dirs = list(path_obj.glob('sub-*'))
        if not subject_dirs:
            raise ValueError("No subject directories found (sub-*)")

        return True

    @staticmethod
    def validate_neurodesk_module(module_name: str) -> bool:
        """
        Validate that a Neurodesk module exists.

        Args:
            module_name: Name of the module (e.g., 'fsl/6.0.7.16')

        Returns:
            True if module exists

        Raises:
            ValueError: If module not found
        """
        # Check if module exists by looking in CVMFS
        cvmfs_base = Path('/cvmfs/neurodesk.ardc.edu.au/containers')

        if not cvmfs_base.exists():
            raise ValueError(
                "CVMFS not mounted. Please check your Neurodesk setup."
            )

        # Parse module name
        if '/' in module_name:
            tool, version = module_name.split('/', 1)
            # Look for container directory
            container_pattern = f"{tool}_{version.replace('.', '_')}_*"
            matching_dirs = list(cvmfs_base.glob(container_pattern))

            if not matching_dirs:
                raise ValueError(
                    f"Neurodesk module not found: {module_name}. "
                    f"Run 'module avail {tool}' to see available versions."
                )
        else:
            # Just tool name, check if any version exists
            matching_dirs = list(cvmfs_base.glob(f"{module_name}_*"))
            if not matching_dirs:
                raise ValueError(
                    f"No versions found for module: {module_name}. "
                    f"Run 'module avail' to see available tools."
                )

        return True


class DomainKnowledgeEngine:
    """Neuroimaging domain-specific parameter knowledge."""

    COMMON_RANGES = {
        # Spatial parameters
        "voxel_size": {
            "min": 0.5, "max": 10.0,
            "typical": [1, 2, 3],
            "advice": "Use 1mm for high-res, 2-3mm for standard fMRI"
        },
        "smoothing_fwhm": {
            "min": 0.0, "max": 20.0,
            "single_subject": [4, 6, 8],
            "group_analysis": [6, 8, 10, 12],
            "advice": "Use 2-3x voxel size for smoothing kernel"
        },

        # Temporal parameters
        "repetition_time": {
            "min": 0.5, "max": 5.0,
            "unit": "seconds",
            "typical_fmri": [2.0, 2.5, 3.0],
            "advice": "Shorter TR = better temporal resolution"
        },
        "high_pass": {
            "min": 0.0, "max": 0.01,
            "typical": 0.008,  # 128s
            "advice": "Use 1/128Hz for standard fMRI"
        },

        # Motion parameters
        "motion_threshold": {
            "strict": 0.2,
            "standard": 0.5,
            "lenient": 1.0,
            "unit": "mm",
            "advice": "Use 0.2mm for pediatric, 0.5mm for adults"
        },
        "fd_spike_threshold": {
            "min": 0.0, "max": 5.0,
            "typical": 0.5,
            "advice": "0.5mm is standard for framewise displacement"
        },

        # Statistical parameters
        "p_threshold": {
            "uncorrected": 0.001,
            "fdr": 0.05,
            "fwe": 0.05,
            "advice": "Use FWE for final results, FDR for exploration"
        },
        "cluster_threshold": {
            "min": 0,
            "typical": [10, 20, 50],
            "advice": "Depends on voxel size and smoothing"
        },

        # Resource parameters
        "n_cpus": {
            "min": 1,
            "max": os.cpu_count() or 64,
            "advice": "Use 4-8 for single subject, 2-4 per subject for parallel"
        },
        "mem_gb": {
            "min": 1,
            "max": 256,  # Typical max system memory
            "per_cpu": 2,
            "advice": "Allocate 2-4GB per CPU"
        }
    }

    def suggest_parameters(self, tool_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        Suggest parameters based on analysis context.

        Args:
            tool_name: Name of the tool
            context: Analysis context (e.g., data type, subject count)

        Returns:
            Dictionary of suggested parameters
        """
        suggestions = {}

        # Data type specific suggestions
        data_type = context.get("data_type", "unknown")

        if data_type == "T1w":
            suggestions.update({
                "bet_threshold": 0.5,
                "voxel_size": 1.0,
            })
        elif data_type == "bold":
            suggestions.update({
                "smoothing_fwhm": 6.0,
                "high_pass": 0.008,
                "motion_threshold": 0.5,
            })
        elif data_type == "dwi":
            suggestions.update({
                "b_value": 1000,
                "n_directions": 64,
            })

        # Analysis level suggestions
        analysis_level = context.get("analysis_level", "participant")

        if analysis_level == "group":
            suggestions["smoothing_fwhm"] = 8.0
            suggestions["n_cpus"] = min(8, os.cpu_count() or 8)
        else:
            suggestions["smoothing_fwhm"] = 6.0
            suggestions["n_cpus"] = min(4, os.cpu_count() or 4)

        # Subject count suggestions
        n_subjects = context.get("n_subjects", 1)

        if n_subjects > 10:
            suggestions["n_cpus"] = min(n_subjects, os.cpu_count() or 8)
            suggestions["mem_gb"] = min(n_subjects * 4, 256)

        return suggestions

    def get_empirical_advice(self, param_name: str) -> str | None:
        """Get empirical advice for a parameter."""
        if param_name in self.COMMON_RANGES:
            return self.COMMON_RANGES[param_name].get("advice")
        return None


class DocumentationFetcher:
    """Fetches documentation from multiple sources."""

    def __init__(self):
        self.cache_dir = Path.home() / ".cache" / "brain_researcher" / "docs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(days=7)  # Cache for 7 days

    def fetch_python_api(self, package_name: str) -> dict[str, Any] | None:
        """
        Extract parameter information from Python packages.

        Args:
            package_name: Name of the Python package

        Returns:
            Dictionary of parameter schemas or None
        """
        try:
            # Import the package
            if '.' in package_name:
                # Handle submodules like nilearn.glm
                parts = package_name.split('.')
                module = __import__(parts[0])
                for part in parts[1:]:
                    module = getattr(module, part)
            else:
                module = __import__(package_name)

            # Extract function/class signatures
            parameters = {}

            for name, obj in inspect.getmembers(module):
                if inspect.isfunction(obj) or inspect.isclass(obj):
                    try:
                        sig = inspect.signature(obj)
                        params_info = {}

                        for param_name, param in sig.parameters.items():
                            if param_name in ['self', 'cls']:
                                continue

                            param_info = {
                                "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                                "default": param.default if param.default != inspect.Parameter.empty else None,
                                "required": param.default == inspect.Parameter.empty
                            }

                            # Try to extract from docstring
                            if obj.__doc__:
                                param_info["description"] = self._extract_param_from_docstring(
                                    obj.__doc__, param_name
                                )

                            params_info[param_name] = param_info

                        if params_info:
                            parameters[name] = params_info
                    except Exception:
                        pass  # Skip problematic functions

            return parameters if parameters else None

        except ImportError:
            return None
        except Exception as e:
            print(f"Error fetching Python API docs for {package_name}: {e}")
            return None

    def fetch_all(self, tool_name: str) -> dict[str, Any]:
        """Fetch parameter information from all available sources."""
        results: dict[str, Any] = {}
        python_api = self.fetch_python_api(tool_name)
        if python_api:
            results["python_api"] = python_api

        neurodesk = self.fetch_neurodesk_help(tool_name)
        if neurodesk:
            results["neurodesk"] = neurodesk

        online = self.fetch_online_docs(tool_name)
        if online:
            results["online_docs"] = online

        return results

    def fetch_neurodesk_help(self, tool_name: str) -> dict[str, Any] | None:
        """
        Get help information from Neurodesk containers.

        Args:
            tool_name: Name of the tool

        Returns:
            Dictionary of parameter information or None
        """
        # Check cache first
        cache_file = self.cache_dir / f"{tool_name}_help.json"
        if cache_file.exists():
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - mtime < self.cache_ttl:
                with open(cache_file) as f:
                    return json.load(f)

        # Try to get help from container
        cvmfs_base = Path('/cvmfs/neurodesk.ardc.edu.au/containers')

        if not cvmfs_base.exists():
            return None

        # Find the container
        matching_dirs = list(cvmfs_base.glob(f"{tool_name}_*"))
        if not matching_dirs:
            return None

        container_dir = matching_dirs[0]

        # Try common help flags
        help_flags = ['-h', '--help', '-help', 'help']
        parameters = {}

        for help_flag in help_flags:
            try:
                # Run the tool with help flag
                result = subprocess.run(
                    [str(container_dir / tool_name), help_flag],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0 or result.stdout:
                    # Parse the help output
                    params = self._parse_cli_help(result.stdout or result.stderr)
                    if params:
                        parameters.update(params)
                        break
            except Exception:
                continue

        # Cache the results
        if parameters:
            with open(cache_file, 'w') as f:
                json.dump(parameters, f, indent=2)

        return parameters if parameters else None

    def fetch_online_docs(self, tool_name: str) -> dict[str, Any] | None:
        """
        Fetch documentation from online sources.

        Args:
            tool_name: Name of the tool

        Returns:
            Dictionary of parameter information or None
        """
        # Map tool names to documentation URLs

        # This would require web scraping implementation
        # For now, return None
        return None

    def _extract_param_from_docstring(self, docstring: str, param_name: str) -> str | None:
        """Extract parameter description from docstring."""
        # Simple extraction for NumPy/Google style docstrings
        lines = docstring.split('\n')
        in_params = False

        for i, line in enumerate(lines):
            if 'Parameters' in line:
                in_params = True
                continue

            if in_params:
                if param_name in line:
                    # Try to get the description
                    if ':' in line:
                        return line.split(':', 1)[1].strip()
                    elif i + 1 < len(lines):
                        return lines[i + 1].strip()

        return None

    def _parse_cli_help(self, help_text: str) -> dict[str, Any]:
        """Parse CLI help output to extract parameters."""
        parameters = {}

        # Common patterns in help output
        patterns = [
            r'(-\w+|--[\w-]+)\s+<?(\w+)?>?\s+(.*?)(?:\n|$)',  # -f <value> description
            r'(-\w+|--[\w-]+)\s+(.*?)(?:\n|$)',  # --flag description
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, help_text, re.MULTILINE)
            for match in matches:
                flag = match.group(1)
                description = match.group(-1) if len(match.groups()) > 1 else ""

                # Clean up the flag name
                param_name = flag.lstrip('-').replace('-', '_')

                # Try to extract type and range from description
                param_info = {
                    "flag": flag,
                    "description": description.strip(),
                    "type": "string",  # Default type
                    "required": False,
                }

                # Look for type hints in description
                if 'int' in description.lower():
                    param_info["type"] = "integer"
                elif 'float' in description.lower() or 'number' in description.lower():
                    param_info["type"] = "float"
                elif 'bool' in description.lower() or 'flag' in description.lower():
                    param_info["type"] = "boolean"

                # Look for ranges
                range_match = re.search(r'\[?([\d.]+)-([\d.]+)\]?', description)
                if range_match:
                    param_info["min"] = float(range_match.group(1))
                    param_info["max"] = float(range_match.group(2))

                # Look for defaults
                default_match = re.search(r'default[:\s=]+([\w.]+)', description, re.IGNORECASE)
                if default_match:
                    param_info["default"] = default_match.group(1)

                parameters[param_name] = param_info

        return parameters


class ParameterDatabase:
    """Manages persistent parameter knowledge base."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            from brain_researcher.config.paths import get_repo_root
            db_path = get_repo_root() / "data" / "parameter_db.json"

        self.db_path = Path(db_path)
        self.db_file = self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_database()

    def _load_database(self) -> dict[str, Any]:
        """Load the parameter database from disk."""
        if self.db_path.exists():
            try:
                with open(self.db_path) as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading parameter database: {e}")

        # Return default structure
        return {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "tools": {}
        }

    def save_database(self):
        """Save the parameter database to disk."""
        self.data["last_updated"] = datetime.now().isoformat()

        try:
            with open(self.db_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving parameter database: {e}")

    def save(self) -> None:
        """Public save alias for tests."""
        self.save_database()

    def add_parameter(self, tool_name: str, param_name: str, info: dict[str, Any]) -> None:
        """Add a parameter entry for a tool."""
        if "tools" not in self.data:
            self.data["tools"] = {}
        if tool_name not in self.data["tools"]:
            self.data["tools"][tool_name] = {
                "parameters": {},
                "last_updated": datetime.now().isoformat(),
            }
        self.data["tools"][tool_name]["parameters"][param_name] = dict(info)

    def get_parameter(self, tool_name: str, param_name: str) -> dict[str, Any] | None:
        """Get a single parameter entry."""
        tool_entry = self.data.get("tools", {}).get(tool_name, {})
        return tool_entry.get("parameters", {}).get(param_name)

    def get_tool_parameters(self, tool_name: str) -> dict[str, Any]:
        """Return parameters dict for a tool."""
        tool_entry = self.data.get("tools", {}).get(tool_name, {})
        return tool_entry.get("parameters", {}) or {}

    def update_parameter(self, tool_name: str, param_name: str, info: dict[str, Any]) -> None:
        """Update an existing parameter while preserving fields."""
        existing = self.get_parameter(tool_name, param_name) or {}
        merged = dict(existing)
        merged.update(info)
        self.add_parameter(tool_name, param_name, merged)

    def search_parameters(self, query: str) -> list[dict[str, Any]]:
        """Search parameters by name or description."""
        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        for tool_name, tool_entry in self.data.get("tools", {}).items():
            params = tool_entry.get("parameters", {}) or {}
            for param_name, info in params.items():
                description = str(info.get("description", "")).lower()
                if query_lower in param_name.lower() or query_lower in description:
                    results.append(
                        {
                            "tool": tool_name,
                            "parameter": param_name,
                            "info": info,
                        }
                    )
        return results

    def get_tool_params(self, tool_name: str) -> dict[str, Any] | None:
        """Get cached parameter info for a tool."""
        tool_entry = self.data.get("tools", {}).get(tool_name)
        if not tool_entry:
            return None
        if isinstance(tool_entry, dict) and "parameters" in tool_entry:
            params = tool_entry.get("parameters") or {}
            merged = {"parameters": params}
            merged.update(params)
            return merged
        return tool_entry

    def update_tool_params(self, tool_name: str, params: dict[str, Any]):
        """Update parameter info with new discovery."""
        if "tools" not in self.data:
            self.data["tools"] = {}

        self.data["tools"][tool_name] = {
            "parameters": params,
            "last_updated": datetime.now().isoformat(),
            "source": "auto-discovered"
        }

        self.save_database()


class ParameterValidator:
    """Enhanced parameter validation system with API discovery."""

    def __init__(self):
        """Initialize the enhanced parameter validator."""
        # Original components
        self.schemas: dict[str, list[ParameterSchema]] = {}
        self.neuroimaging_validators = NeuroimagingValidators()

        # NEW: API discovery components
        self.doc_fetcher = DocumentationFetcher()
        self.param_db = ParameterDatabase()
        self.domain_expert = DomainKnowledgeEngine()

        # Cache for discovered schemas
        self.discovery_cache: dict[str, Any] = {}

        # Initialize
        self._register_default_schemas()
        self._load_from_database()

    def _load_from_database(self):
        """Load schemas from the parameter database."""
        # This would load previously discovered schemas
        # For now, just initialize the database
        pass

    def _register_default_schemas(self):
        """Register default validation schemas for common tools."""
        # fMRIPrep schema
        self.register_tool_schema(
            "fmriprep",
            [
                ParameterSchema(
                    name="bids_dir",
                    param_type=ParameterType.BIDS_DATASET,
                    description="Input BIDS dataset directory",
                    validation_rules=ValidationRule(required=True),
                    source="fMRIPrep documentation",
                ),
                ParameterSchema(
                    name="output_dir",
                    param_type=ParameterType.DIRECTORY,
                    description="Output directory for derivatives",
                    validation_rules=ValidationRule(required=True),
                    source="fMRIPrep documentation",
                ),
                ParameterSchema(
                    name="participant_label",
                    param_type=ParameterType.STRING,
                    description="Participant ID to process",
                    default=None,
                    validation_rules=ValidationRule(
                        required=False,
                        pattern=r"^sub-[a-zA-Z0-9]+$"
                    ),
                    source="fMRIPrep documentation",
                ),
                ParameterSchema(
                    name="n_cpus",
                    param_type=ParameterType.INTEGER,
                    description="Number of CPUs to use",
                    default=4,
                    validation_rules=ValidationRule(
                        required=False,
                        min_value=1,
                        max_value=os.cpu_count() or 64
                    ),
                    source="fMRIPrep documentation",
                    empirical_advice="Use 4-8 CPUs for single subject, 2-4 per subject for parallel processing",
                ),
            ]
        )

        # GLM analysis schema
        self.register_tool_schema(
            "glm_analysis",
            [
                ParameterSchema(
                    name="data_file",
                    param_type=ParameterType.NIFTI_FILE,
                    description="4D fMRI data file",
                    validation_rules=ValidationRule(required=True),
                    source="Nilearn documentation",
                ),
                ParameterSchema(
                    name="smoothing_fwhm",
                    param_type=ParameterType.FLOAT,
                    description="Smoothing kernel FWHM in mm",
                    default=6.0,
                    validation_rules=ValidationRule(
                        required=False,
                        min_value=0.0,
                        max_value=20.0
                    ),
                    source="Nilearn documentation",
                    empirical_advice=self.domain_expert.get_empirical_advice("smoothing_fwhm"),
                ),
            ]
        )

        # FSL BET schema
        self.register_tool_schema(
            "fsl_bet",
            [
                ParameterSchema(
                    name="input_file",
                    param_type=ParameterType.NIFTI_FILE,
                    description="Input brain image",
                    validation_rules=ValidationRule(required=True),
                    neurodesk_module="fsl/6.0.7.16",
                    source="FSL documentation",
                ),
                ParameterSchema(
                    name="threshold",
                    param_type=ParameterType.FLOAT,
                    description="Fractional intensity threshold",
                    default=0.5,
                    validation_rules=ValidationRule(
                        required=False,
                        min_value=0.0,
                        max_value=1.0
                    ),
                    source="FSL documentation",
                    empirical_advice="Use 0.3-0.4 for T2, 0.5-0.6 for T1",
                ),
            ]
        )

    def register_tool_schema(self, tool_name: str, schemas: list[ParameterSchema]):
        """
        Register validation schema for a tool.

        Args:
            tool_name: Name of the tool
            schemas: List of parameter schemas
        """
        self.schemas[tool_name] = schemas

    def _validate_parameters_strict(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        apply_defaults: bool = True,
        auto_discover: bool = True,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Enhanced validation with auto-discovery and context-aware suggestions.

        Args:
            tool_name: Name of the tool
            parameters: Parameters to validate
            apply_defaults: Whether to apply default values
            auto_discover: Whether to fetch docs if schema not found
            context: Optional context for parameter suggestions

        Returns:
            Validated and processed parameters

        Raises:
            AgentError: If validation fails
        """
        # Try to discover schema if not found
        if tool_name not in self.schemas and auto_discover:
            self._discover_tool_parameters(tool_name)

        # Apply domain knowledge suggestions if context provided
        if context:
            suggestions = self.domain_expert.suggest_parameters(tool_name, context)
            # Merge suggestions with provided parameters (provided params take precedence)
            for key, value in suggestions.items():
                if key not in parameters:
                    parameters[key] = value

        # If still no schema, pass through with basic validation
        if tool_name not in self.schemas:
            return parameters

        schemas = self.schemas[tool_name]
        validated_params = {}
        errors = []

        # Check each schema
        for schema in schemas:
            param_name = schema.name
            param_value = parameters.get(param_name)

            # Handle missing required parameters
            if param_value is None:
                if schema.validation_rules.required:
                    errors.append(f"Missing required parameter: {param_name}")
                    continue
                elif apply_defaults and schema.default is not None:
                    param_value = schema.default
                else:
                    continue

            # Validate the parameter
            try:
                validated_value = self._validate_single_parameter(
                    param_value,
                    schema
                )
                validated_params[param_name] = validated_value
            except ValueError as e:
                # Add empirical advice if available
                error_msg = f"Parameter '{param_name}': {str(e)}"
                if schema.empirical_advice:
                    error_msg += f"\n  💡 Advice: {schema.empirical_advice}"
                errors.append(error_msg)

        # Check for unknown parameters
        known_params = {s.name for s in schemas}
        unknown_params = set(parameters.keys()) - known_params
        if unknown_params:
            # Just warn, don't fail
            for param in unknown_params:
                validated_params[param] = parameters[param]

        # If there are errors, raise them with helpful suggestions
        if errors:
            suggestions = self._get_parameter_suggestions(tool_name, parameters, errors)

            raise AgentError(
                message=f"Parameter validation failed for {tool_name}:\n" + "\n".join(errors),
                category=ErrorCategory.VALIDATION_ERROR,
                severity=ErrorSeverity.MEDIUM,
                suggestions=suggestions
            )

        return validated_params

    def _infer_type_from_value(self, value: Any) -> str:
        """Infer a simple schema type from a value."""
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "float"
        if isinstance(value, list | tuple):
            return "array"
        return "string"

    def _schema_from_param_schema(self, schema: ParameterSchema) -> dict[str, Any]:
        """Convert ParameterSchema to a dict-based schema."""
        rules = schema.validation_rules
        return {
            "type": schema.param_type.value,
            "range": (
                [rules.min_value, rules.max_value]
                if rules.min_value is not None or rules.max_value is not None
                else None
            ),
            "options": rules.choices,
            "pattern": rules.pattern,
            "required": rules.required,
        }

    def _schema_from_discovery(self, discovery: dict[str, Any], param_name: str) -> dict[str, Any] | None:
        """Find a schema entry from discovery results."""
        for source in discovery.values():
            if not isinstance(source, dict):
                continue
            for key, info in source.items():
                if key == param_name or key.endswith(f".{param_name}"):
                    if isinstance(info, dict):
                        return info
        return None

    def validate_parameter(
        self,
        param_name: str,
        value: Any,
        schema: dict[str, Any] | None = None,
        *,
        tool: str | None = None,
        auto_discover: bool = False,
        context: dict[str, Any] | None = None,
    ) -> ParameterValidationResult:
        """Validate a single parameter using a simple schema dict."""
        warnings: list[str] = []
        metadata: dict[str, Any] = {"param": param_name}
        if tool:
            metadata["tool"] = tool
        metadata["validated_at"] = datetime.now().isoformat()

        # Attempt to resolve schema if missing
        if schema is None:
            if tool and tool in self.schemas:
                for pschema in self.schemas[tool]:
                    if pschema.name == param_name:
                        schema = self._schema_from_param_schema(pschema)
                        break
            if schema is None and auto_discover and tool:
                discovery = self.doc_fetcher.fetch_all(tool)
                schema = self._schema_from_discovery(discovery, param_name)

        if schema is None:
            schema = {"type": self._infer_type_from_value(value)}

        schema_type = (schema.get("type") or "string").lower()
        options = schema.get("options")
        value_range = schema.get("range")
        recommended_range = schema.get("recommended_range")
        element_type = schema.get("element_type")
        expected_length = schema.get("length")

        # Type coercion
        try:
            coerced = value
            if schema_type == "integer":
                coerced = int(value)
            elif schema_type == "float":
                coerced = float(value)
            elif schema_type == "boolean":
                if isinstance(value, bool):
                    coerced = value
                elif isinstance(value, str):
                    coerced = value.lower() in ["true", "1", "yes", "on"]
                else:
                    coerced = bool(value)
            elif schema_type == "array":
                if isinstance(value, str):
                    try:
                        coerced = json.loads(value)
                    except json.JSONDecodeError:
                        coerced = [v.strip() for v in value.split(",") if v.strip()]
                else:
                    coerced = list(value)
            else:
                coerced = str(value)
        except (ValueError, TypeError) as exc:
            return ParameterValidationResult(
                is_valid=False,
                value=value,
                message=f"Invalid type for {param_name}: {exc}",
                metadata=metadata,
            )

        # Element type validation
        if schema_type == "array" and element_type:
            converted: list[Any] = []
            try:
                for item in coerced:
                    if element_type == "float":
                        converted.append(float(item))
                    elif element_type == "integer":
                        converted.append(int(item))
                    else:
                        converted.append(item)
                coerced = converted
            except (ValueError, TypeError) as exc:
                return ParameterValidationResult(
                    is_valid=False,
                    value=value,
                    message=f"Invalid element type for {param_name}: {exc}",
                    metadata=metadata,
                )

        # Length validation
        if schema_type == "array" and expected_length is not None:
            if len(coerced) != expected_length:
                return ParameterValidationResult(
                    is_valid=False,
                    value=coerced,
                    message=f"Expected length {expected_length}",
                    metadata=metadata,
                )

        # Options validation
        if options is not None:
            if coerced not in options:
                suggested = options[0] if options else None
                return ParameterValidationResult(
                    is_valid=False,
                    value=coerced,
                    message="Value not in allowed options",
                    suggested_value=suggested,
                    metadata=metadata,
                )

        # Range validation
        if value_range is not None:
            min_val = value_range[0] if len(value_range) > 0 else None
            max_val = value_range[1] if len(value_range) > 1 else None

            def _out_of_range(val: float) -> bool:
                if min_val is not None and val < min_val:
                    return True
                if max_val is not None and val > max_val:
                    return True
                return False

            if schema_type == "array":
                if any(_out_of_range(v) for v in coerced):
                    suggested = None
                    return ParameterValidationResult(
                        is_valid=False,
                        value=coerced,
                        message="Value out of range",
                        suggested_value=suggested,
                        metadata=metadata,
                    )
            else:
                if isinstance(coerced, int | float) and _out_of_range(coerced):
                    suggested = coerced
                    if min_val is not None:
                        suggested = max(min_val, suggested)
                    if max_val is not None:
                        suggested = min(max_val, suggested)
                    return ParameterValidationResult(
                        is_valid=False,
                        value=coerced,
                        message="Value out of range",
                        suggested_value=suggested,
                        metadata=metadata,
                    )

        # Recommended range warnings
        if recommended_range is not None and isinstance(coerced, int | float):
            rec_min = recommended_range[0]
            rec_max = recommended_range[1]
            if (rec_min is not None and coerced < rec_min) or (
                rec_max is not None and coerced > rec_max
            ):
                warnings.append("Value outside recommended range")

        # Context-aware suggestions
        suggested_value = None
        if context and param_name == "smoothing_fwhm":
            if context.get("task") == "group_analysis" and coerced < 6:
                suggested_value = 6.0

        return ParameterValidationResult(
            is_valid=True,
            value=coerced,
            message="",
            suggested_value=suggested_value,
            warnings=warnings,
            metadata=metadata,
        )

    def validate_tool_parameters(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        auto_discover: bool = True,
    ) -> dict[str, ParameterValidationResult]:
        """Validate a set of tool parameters."""
        results: dict[str, ParameterValidationResult] = {}

        schema_map: dict[str, ParameterSchema] = {
            schema.name: schema for schema in self.schemas.get(tool_name, [])
        }

        # Optional discovery for unknown tools
        discovery_cache: dict[str, Any] | None = None
        if auto_discover and (not schema_map):
            discovery_cache = self.doc_fetcher.fetch_neurodesk_help(tool_name) or {}

        for param_name, value in parameters.items():
            schema_dict: dict[str, Any] | None = None
            if param_name in schema_map:
                schema_dict = self._schema_from_param_schema(schema_map[param_name])
            elif discovery_cache:
                schema_dict = discovery_cache.get(param_name)

            result = self.validate_parameter(
                param_name,
                value,
                schema_dict,
                tool=tool_name,
                auto_discover=auto_discover,
                context=context,
            )
            results[param_name] = result

        return results

    def validate_parameters(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        apply_defaults: bool = True,
        auto_discover: bool = True,
        context: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> ValidationSummary:
        """Validate parameters and return a structured summary."""
        if strict:
            try:
                validated = self._validate_parameters_strict(
                    tool_name,
                    parameters,
                    apply_defaults=apply_defaults,
                    auto_discover=auto_discover,
                    context=context,
                )
                return ValidationSummary(
                    valid=True,
                    errors={},
                    warnings=[],
                    results={
                        name: ParameterValidationResult(is_valid=True, value=value)
                        for name, value in validated.items()
                    },
                    validated_params=validated,
                )
            except AgentError as exc:
                return ValidationSummary(
                    valid=False,
                    errors={"validation": str(exc)},
                    warnings=[],
                    results={},
                )

        results = self.validate_tool_parameters(
            tool_name,
            parameters,
            context=context,
            auto_discover=auto_discover,
        )

        errors: dict[str, str] = {}
        warnings: list[str] = []
        validated_params: dict[str, Any] = {}
        suggestions: dict[str, Any] = {}

        for name, result in results.items():
            warnings.extend(result.warnings or [])
            if result.is_valid:
                validated_params[name] = result.value
            else:
                errors[name] = result.message or "Invalid value"
                if result.suggested_value is not None:
                    suggestions[name] = result.suggested_value

        return ValidationSummary(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            results=results,
            validated_params=validated_params,
            suggestions=suggestions,
        )

    def _discover_tool_parameters(self, tool_name: str):
        """
        Automatically discover parameters for unknown tool.

        Args:
            tool_name: Name of the tool to discover
        """
        # Check cache first
        if tool_name in self.discovery_cache:
            self.schemas[tool_name] = self.discovery_cache[tool_name]
            return

        discovered_schemas = []

        # 1. Check parameter database
        db_params = self.param_db.get_tool_params(tool_name)
        if db_params:
            discovered_schemas = self._convert_db_to_schemas(
                tool_name,
                {"parameters": db_params},
            )

        # 2. Try Python API discovery
        elif self._is_python_package(tool_name):
            api_params = self.doc_fetcher.fetch_python_api(tool_name)
            if api_params:
                discovered_schemas = self._convert_api_to_schemas(tool_name, api_params)
                # Save to database for future use
                self.param_db.update_tool_params(tool_name, api_params)

        # 3. Try Neurodesk discovery
        elif self._is_neurodesk_tool(tool_name):
            help_params = self.doc_fetcher.fetch_neurodesk_help(tool_name)
            if help_params:
                discovered_schemas = self._convert_help_to_schemas(tool_name, help_params)
                # Save to database
                self.param_db.update_tool_params(tool_name, help_params)

        # 4. Try online documentation
        else:
            online_params = self.doc_fetcher.fetch_online_docs(tool_name)
            if online_params:
                discovered_schemas = self._convert_online_to_schemas(tool_name, online_params)
                self.param_db.update_tool_params(tool_name, online_params)

        if discovered_schemas:
            self.schemas[tool_name] = discovered_schemas
            self.discovery_cache[tool_name] = discovered_schemas

    def _is_python_package(self, tool_name: str) -> bool:
        """Check if tool is a Python package."""
        try:
            __import__(tool_name.split('.')[0])
            return True
        except ImportError:
            return False

    def _is_neurodesk_tool(self, tool_name: str) -> bool:
        """Check if tool is available in Neurodesk."""
        cvmfs_base = Path('/cvmfs/neurodesk.ardc.edu.au/containers')
        if cvmfs_base.exists():
            return len(list(cvmfs_base.glob(f"{tool_name}_*"))) > 0
        return False

    def _convert_db_to_schemas(self, tool_name: str, db_params: dict) -> list[ParameterSchema]:
        """Convert database parameters to schemas."""
        schemas = []
        params = db_params.get("parameters", {})

        for param_name, param_info in params.items():
            schema = ParameterSchema(
                name=param_name,
                param_type=self._infer_param_type(param_info.get("type", "string")),
                description=param_info.get("description", ""),
                default=param_info.get("default"),
                validation_rules=ValidationRule(
                    required=param_info.get("required", False),
                    min_value=param_info.get("min"),
                    max_value=param_info.get("max"),
                ),
                source="parameter database"
            )
            schemas.append(schema)

        return schemas

    def _convert_api_to_schemas(self, tool_name: str, api_params: dict) -> list[ParameterSchema]:
        """Convert API parameters to schemas."""
        schemas = []

        # Take the first function/class for now
        for _func_name, params in api_params.items():
            for param_name, param_info in params.items():
                schema = ParameterSchema(
                    name=param_name,
                    param_type=self._infer_param_type(param_info.get("type", "Any")),
                    description=param_info.get("description", ""),
                    default=param_info.get("default"),
                    validation_rules=ValidationRule(
                        required=param_info.get("required", False),
                    ),
                    source=f"Python API: {tool_name}"
                )
                schemas.append(schema)
            break  # Just use first function for now

        return schemas

    def _convert_help_to_schemas(self, tool_name: str, help_params: dict) -> list[ParameterSchema]:
        """Convert CLI help parameters to schemas."""
        schemas = []

        for param_name, param_info in help_params.items():
            schema = ParameterSchema(
                name=param_name,
                param_type=self._infer_param_type(param_info.get("type", "string")),
                description=param_info.get("description", ""),
                default=param_info.get("default"),
                validation_rules=ValidationRule(
                    required=param_info.get("required", False),
                    min_value=param_info.get("min"),
                    max_value=param_info.get("max"),
                ),
                source=f"Neurodesk: {tool_name}",
                neurodesk_module=tool_name
            )
            schemas.append(schema)

        return schemas

    def _convert_online_to_schemas(self, tool_name: str, online_params: dict) -> list[ParameterSchema]:
        """Convert online documentation to schemas."""
        # Similar to other converters
        return []

    def _infer_param_type(self, type_str: str) -> ParameterType:
        """Infer parameter type from string representation."""
        type_str = str(type_str).lower()

        if 'int' in type_str:
            return ParameterType.INTEGER
        elif 'float' in type_str or 'number' in type_str:
            return ParameterType.FLOAT
        elif 'bool' in type_str:
            return ParameterType.BOOLEAN
        elif 'path' in type_str or 'file' in type_str:
            return ParameterType.FILE
        elif 'dir' in type_str:
            return ParameterType.DIRECTORY
        elif 'list' in type_str or 'array' in type_str:
            return ParameterType.LIST
        elif 'dict' in type_str:
            return ParameterType.DICT
        else:
            return ParameterType.STRING

    def _validate_single_parameter(
        self,
        value: Any,
        schema: ParameterSchema
    ) -> Any:
        """
        Validate a single parameter.

        Args:
            value: Parameter value
            schema: Parameter schema

        Returns:
            Validated value

        Raises:
            ValueError: If validation fails
        """
        rules = schema.validation_rules

        # Type validation
        validated_value = self._validate_type(value, schema.param_type, schema)

        # Apply validation rules
        if rules.min_value is not None and validated_value < rules.min_value:
            raise ValueError(f"Value {validated_value} is below minimum {rules.min_value}")

        if rules.max_value is not None and validated_value > rules.max_value:
            raise ValueError(f"Value {validated_value} exceeds maximum {rules.max_value}")

        if rules.min_length is not None and len(validated_value) < rules.min_length:
            raise ValueError(f"Length {len(validated_value)} is below minimum {rules.min_length}")

        if rules.max_length is not None and len(validated_value) > rules.max_length:
            raise ValueError(f"Length {len(validated_value)} exceeds maximum {rules.max_length}")

        if rules.pattern and isinstance(validated_value, str):
            if not re.match(rules.pattern, validated_value):
                raise ValueError(f"Value '{validated_value}' does not match pattern {rules.pattern}")

        if rules.choices is not None and validated_value not in rules.choices:
            raise ValueError(f"Value '{validated_value}' not in allowed choices: {rules.choices}")

        if rules.file_extensions and schema.param_type in [ParameterType.FILE, ParameterType.PATH]:
            if not any(str(validated_value).endswith(ext) for ext in rules.file_extensions):
                raise ValueError(f"File must have extension: {rules.file_extensions}")

        if rules.custom_validator:
            try:
                rules.custom_validator(validated_value)
            except Exception as e:
                raise ValueError(f"Custom validation failed: {str(e)}") from e

        # Check Neurodesk module if specified
        if schema.neurodesk_module:
            try:
                self.neuroimaging_validators.validate_neurodesk_module(schema.neurodesk_module)
            except ValueError:
                raise ValueError(
                    f"Required Neurodesk module not available: {schema.neurodesk_module}. "
                    f"Load it with: module load {schema.neurodesk_module}"
                ) from None

        return validated_value

    def _validate_type(
        self,
        value: Any,
        param_type: ParameterType,
        schema: ParameterSchema
    ) -> Any:
        """
        Validate and convert parameter type.

        Args:
            value: Parameter value
            param_type: Expected type
            schema: Parameter schema

        Returns:
            Type-validated value

        Raises:
            ValueError: If type validation fails
        """
        try:
            if param_type == ParameterType.STRING:
                return str(value)

            elif param_type == ParameterType.INTEGER:
                return int(value)

            elif param_type == ParameterType.FLOAT:
                return float(value)

            elif param_type == ParameterType.BOOLEAN:
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.lower() in ['true', '1', 'yes', 'on']
                return bool(value)

            elif param_type == ParameterType.PATH:
                path = Path(value)
                return str(path.absolute())

            elif param_type == ParameterType.FILE:
                path = Path(value)
                if not path.exists():
                    raise ValueError(f"File does not exist: {value}")
                if not path.is_file():
                    raise ValueError(f"Path is not a file: {value}")
                return str(path.absolute())

            elif param_type == ParameterType.DIRECTORY:
                path = Path(value)
                if not path.exists():
                    # Create directory if it doesn't exist
                    path.mkdir(parents=True, exist_ok=True)
                if not path.is_dir():
                    raise ValueError(f"Path is not a directory: {value}")
                return str(path.absolute())

            elif param_type == ParameterType.LIST:
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    # Try to parse as JSON
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        # Split by comma
                        return [v.strip() for v in value.split(',')]
                return list(value)

            elif param_type == ParameterType.DICT:
                if isinstance(value, dict):
                    return value
                if isinstance(value, str):
                    return json.loads(value)
                raise ValueError("Cannot convert to dictionary")

            elif param_type == ParameterType.ENUM:
                # Handled by choices validation
                return value

            elif param_type == ParameterType.ARRAY:
                if isinstance(value, np.ndarray):
                    return value
                return np.array(value)

            elif param_type == ParameterType.NIFTI_FILE:
                self.neuroimaging_validators.validate_nifti_file(value)
                return str(Path(value).absolute())

            elif param_type == ParameterType.BIDS_DATASET:
                self.neuroimaging_validators.validate_bids_dataset(value)
                return str(Path(value).absolute())

            elif param_type == ParameterType.MODULE_NAME:
                self.neuroimaging_validators.validate_neurodesk_module(value)
                return value

            else:
                return value

        except (ValueError, TypeError) as e:
            raise ValueError(f"Cannot convert to {param_type.value}: {str(e)}") from e

    def _get_parameter_suggestions(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        errors: list[str]
    ) -> list[str]:
        """Get helpful suggestions for parameter errors."""
        suggestions = [
            "Check parameter types and values",
            "Ensure all required parameters are provided",
        ]

        # Add tool-specific help
        if tool_name in self.schemas:
            suggestions.append(f"Run 'br tools describe {tool_name}' for parameter details")

        # Add domain-specific advice
        for error in errors:
            if "smoothing" in error.lower():
                suggestions.append("Smoothing typically 2-3x voxel size (e.g., 6mm for 2mm voxels)")
            elif "threshold" in error.lower():
                suggestions.append("Statistical thresholds: p<0.001 uncorrected, p<0.05 FWE")
            elif "motion" in error.lower():
                suggestions.append("Motion thresholds: 0.2mm (strict), 0.5mm (standard)")

        # Check if Neurodesk module is needed
        if tool_name in self.schemas:
            for schema in self.schemas[tool_name]:
                if schema.neurodesk_module:
                    suggestions.append(f"Ensure Neurodesk module is loaded: module load {schema.neurodesk_module}")
                    break

        return suggestions

    def get_tool_parameters(self, tool_name: str) -> list[ParameterSchema]:
        """
        Get parameter schemas for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of parameter schemas
        """
        # Try to discover if not found
        if tool_name not in self.schemas:
            self._discover_tool_parameters(tool_name)

        return self.schemas.get(tool_name, [])

    def generate_parameter_help(self, tool_name: str, context: dict[str, Any] | None = None) -> str:
        """
        Generate help text for tool parameters with context-aware suggestions.

        Args:
            tool_name: Name of the tool
            context: Optional context for suggestions

        Returns:
            Help text string
        """
        # Ensure we have schemas
        if tool_name not in self.schemas:
            self._discover_tool_parameters(tool_name)

        if tool_name not in self.schemas:
            return f"No parameter information available for {tool_name}"

        schemas = self.schemas[tool_name]
        help_lines = [f"📘 Parameters for {tool_name}:"]

        # Add context-aware suggestions if provided
        if context:
            suggestions = self.domain_expert.suggest_parameters(tool_name, context)
            if suggestions:
                help_lines.append("\n💡 Suggested values based on your context:")
                for param, value in suggestions.items():
                    help_lines.append(f"  • {param}: {value}")
                help_lines.append("")

        # Add parameter details
        help_lines.append("📋 Parameter Details:")

        for schema in schemas:
            required = "required" if schema.validation_rules.required else "optional"
            default = f" (default: {schema.default})" if schema.default is not None else ""

            help_lines.append(
                f"\n  {schema.name} ({schema.param_type.value}, {required}){default}:"
            )
            help_lines.append(f"    {schema.description}")

            rules = schema.validation_rules
            if rules.min_value is not None or rules.max_value is not None:
                range_str = f"    Range: [{rules.min_value or '-∞'}, {rules.max_value or '∞'}]"
                help_lines.append(range_str)

            if rules.choices:
                help_lines.append(f"    Choices: {rules.choices}")

            if rules.pattern:
                help_lines.append(f"    Pattern: {rules.pattern}")

            if schema.empirical_advice:
                help_lines.append(f"    💡 Advice: {schema.empirical_advice}")

            if schema.neurodesk_module:
                help_lines.append(f"    📦 Requires: module load {schema.neurodesk_module}")

            if schema.source:
                help_lines.append(f"    📚 Source: {schema.source}")

        return "\n".join(help_lines)

    def get_parameter_suggestions(self, tool_name: str, failed_params: dict[str, Any]) -> list[str]:
        """
        Get parameter suggestions for failed validation.

        Args:
            tool_name: Name of the tool
            failed_params: Parameters that failed validation

        Returns:
            List of suggestions
        """
        suggestions = []

        # Get domain expert advice
        for param_name, _param_value in failed_params.items():
            advice = self.domain_expert.get_empirical_advice(param_name)
            if advice:
                suggestions.append(f"{param_name}: {advice}")

        # Add schema-based suggestions
        if tool_name in self.schemas:
            for schema in self.schemas[tool_name]:
                if schema.name in failed_params and schema.empirical_advice:
                    suggestions.append(f"{schema.name}: {schema.empirical_advice}")

        return suggestions


# Global validator instance
global_validator = ParameterValidator()
