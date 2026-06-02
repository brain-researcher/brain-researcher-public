"""Executor for NiWrap Boutiques tools.

This module handles command-line rendering and execution of NiWrap tools
using Boutiques descriptors and the container_runner infrastructure.

Moved from: archive/mcp_server/executors/niwrap_executor.py
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.tools.runtime_profiles import (
    get_neurodesk_package_profile,
    normalize_runtime_package_name,
)

logger = logging.getLogger(__name__)


# Package-specific parameter alias mappings
PARAMETER_ALIASES = {
    "fsl": {
        "input": "infile",
        "output": "maskfile",
        "input_file": "infile",
        "output_file": "maskfile",
        "brain": "maskfile",
        "thresh": "fractional_intensity",
        "threshold": "fractional_intensity",
        "f": "fractional_intensity",
    },
    "afni": {
        "input": "input_file",
        "output": "output_prefix",
        "prefix": "output_prefix",
        "input_dataset": "input_file",
        "mask_file": "mask",
        "blur": "fwhm",
        "smooth": "fwhm",
    },
    "ants": {
        "fixed": "fixed_image",
        "moving": "moving_image",
        "output_prefix": "output",
        "out": "output",
        "dim": "dimensionality",
        "dimensions": "dimensionality",
    },
    "freesurfer": {
        "input": "inp_volume",
        "output": "out_volume",
        "i": "inp_volume",
        "o": "out_volume",
        "subject": "s",
        "subjid": "s",
    },
}


def _apply_parameter_aliases(
    parameters: Dict[str, Any], package: str
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Apply package-specific parameter aliases.

    Args:
        parameters: User-provided parameters
        package: Package name (e.g., "fsl", "afni")

    Returns:
        Tuple of (mapped_parameters, applied_aliases)
    """
    aliases = PARAMETER_ALIASES.get(package, {})
    if not aliases:
        return parameters, {}

    mapped_params = {}
    applied = {}

    for key, value in parameters.items():
        if key in aliases:
            canonical = aliases[key]
            mapped_params[canonical] = value
            applied[key] = canonical
        else:
            mapped_params[key] = value

    return mapped_params, applied


def _extract_required_params(tool_definition: Dict[str, Any]) -> List[str]:
    """Extract required parameter IDs from tool definition."""
    metadata = tool_definition.get("metadata", {})
    inputs = metadata.get("boutiques_inputs", [])

    required = []
    for input_spec in inputs:
        is_optional = input_spec.get("optional", False)
        input_type = input_spec.get("type", "String")
        input_id = input_spec.get("id")

        if input_type == "Flag":
            continue

        if not is_optional and input_id:
            required.append(input_id)

    return required


def _validate_parameters(
    tool_definition: Dict[str, Any], parameters: Dict[str, Any]
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Validate that all required parameters are provided.

    Returns:
        Tuple of (is_valid, error_dict). If valid, error_dict is None.
    """
    import difflib

    required = _extract_required_params(tool_definition)
    missing = [param for param in required if param not in parameters]

    if not missing:
        return True, None

    # Generate suggestions using fuzzy matching
    provided_keys = list(parameters.keys())
    suggestions = {}

    for missing_param in missing:
        matches = difflib.get_close_matches(
            missing_param, provided_keys, n=1, cutoff=0.6
        )
        if matches:
            suggestions[missing_param] = matches[0]

    error_info = {
        "message": "Missing required parameters",
        "missing": missing,
        "provided": provided_keys,
        "suggestions": suggestions,
        "tool": tool_definition.get("name", "unknown"),
    }

    return False, error_info


def render_boutiques_command(
    command_template: str,
    inputs: List[Dict[str, Any]],
    parameters: Dict[str, Any],
) -> List[str]:
    """Render a Boutiques command-line template with user parameters.

    Args:
        command_template: Boutiques command-line template with value-keys
        inputs: List of Boutiques input descriptors
        parameters: User-provided parameter values

    Returns:
        List of command tokens ready for execution

    Example:
        >>> template = "3dBlurInMask [INPUT] [OUTPUT] -FWHM [FWHM]"
        >>> inputs = [
        ...     {"id": "input", "value-key": "[INPUT]", "type": "File"},
        ...     {"id": "output", "value-key": "[OUTPUT]", "type": "String"},
        ...     {"id": "fwhm", "value-key": "[FWHM]", "type": "Number"},
        ... ]
        >>> params = {"input": "/data/brain.nii", "output": "smooth", "fwhm": 4.0}
        >>> render_boutiques_command(template, inputs, params)
        ['3dBlurInMask', '/data/brain.nii', 'smooth', '-FWHM', '4.0']
    """
    substitutions: Dict[str, str] = {}

    for input_spec in inputs:
        input_id = input_spec.get("id")
        value_key = input_spec.get("value-key")

        if not input_id or not value_key:
            continue

        value = parameters.get(input_id)

        if value is None:
            continue

        input_type = input_spec.get("type", "String")
        is_list = input_spec.get("list", False)

        if input_type == "Flag":
            if value:
                flag = input_spec.get("command-line-flag", "")
                if flag:
                    substitutions[value_key] = flag
                else:
                    substitutions[value_key] = str(value)
            else:
                substitutions[value_key] = ""
        else:
            flag = input_spec.get("command-line-flag")
            if is_list:
                sep = input_spec.get("list-separator", " ")
                values = value if isinstance(value, list) else [value]
                rendered_value = sep.join(str(v) for v in values)
                if flag:
                    substitutions[value_key] = f"{flag} {rendered_value}".strip()
                else:
                    substitutions[value_key] = rendered_value
            else:
                rendered_value = str(value)
                if flag:
                    substitutions[value_key] = f"{flag} {rendered_value}".strip()
                else:
                    substitutions[value_key] = rendered_value

    # Perform substitution in template
    rendered = command_template
    for key, value in substitutions.items():
        rendered = rendered.replace(key, value)

    # Remove unsubstituted value-keys
    rendered = re.sub(r"\[[\w_-]+\]", "", rendered)

    # Split into tokens and filter out empty strings
    tokens = rendered.split()
    return [tok for tok in tokens if tok]


def preview_niwrap_tool(
    tool_definition: Dict[str, Any],
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate a preview of the command that would be executed.

    Args:
        tool_definition: Tool definition with Boutiques metadata
        parameters: User-provided parameter values

    Returns:
        Dictionary with rendered command and metadata
    """
    metadata = tool_definition.get("metadata", {})
    command_template = metadata.get("command_line", "")
    boutiques_inputs = metadata.get("boutiques_inputs", [])

    # Render the command
    command_tokens = render_boutiques_command(
        command_template, boutiques_inputs, parameters
    )

    return {
        "tool": tool_definition["name"],
        "command": " ".join(command_tokens),
        "command_tokens": command_tokens,
        "container": metadata.get("container"),
        "parameters": parameters,
        "preview": True,
    }


def execute_niwrap_tool(
    tool_definition: Optional[Dict[str, Any]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    container_config: Optional[Dict[str, Any]] = None,
    work_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a NiWrap tool with the given parameters.

    Args:
        tool_definition: Tool definition with Boutiques metadata
        parameters: User-provided parameter values
        container_config: Optional container configuration overrides
        work_dir: Working directory for execution
        output_dir: Output directory for artifacts
        tool_name: Backward-compatible short/full tool ID used when wrappers do
            not provide ``tool_definition`` directly.

    Returns:
        Execution result with stdout, stderr, exit_code, and artifacts
    """
    if tool_definition is None:
        if not tool_name:
            raise TypeError(
                "execute_niwrap_tool() requires either tool_definition or tool_name"
            )

        from brain_researcher.services.tools.niwrap.catalog import (
            get_niwrap_tools,
            get_tool_by_name,
        )

        resolved_definition = get_tool_by_name(tool_name)
        if resolved_definition is None and tool_name.endswith(".run"):
            short_name = tool_name[: -len(".run")]
            parts = short_name.split(".")
            if len(parts) >= 2:
                package = parts[0]
                app = parts[-1]
                for candidate in get_niwrap_tools(packages=[package], use_cache=True):
                    candidate_name = str(candidate.get("name", "") or "")
                    if candidate_name.startswith(
                        f"{package}."
                    ) and candidate_name.endswith(f".{app}.run"):
                        resolved_definition = candidate
                        break

        if resolved_definition is None:
            raise ValueError(f"NiWrap tool not found: {tool_name}")
        tool_definition = resolved_definition

    if parameters is None:
        parameters = {}

    metadata = tool_definition.get("metadata", {})
    package = metadata.get("package", "unknown")
    tool_name = tool_definition["name"]
    command_template = metadata.get("command_line", "")
    boutiques_inputs = metadata.get("boutiques_inputs", [])

    # Apply parameter aliases
    mapped_parameters, applied_aliases = _apply_parameter_aliases(parameters, package)

    if applied_aliases:
        alias_info = ", ".join(f"{k}→{v}" for k, v in applied_aliases.items())
        logger.info(f"Applied parameter aliases: {alias_info}")

    # Validate parameters
    is_valid, validation_error = _validate_parameters(
        tool_definition, mapped_parameters
    )
    if not is_valid:
        logger.error(
            f"Parameter validation failed for {tool_name}: {validation_error['message']}"
        )
        validation_error["applied_aliases"] = applied_aliases
        return {
            "tool": tool_name,
            "exit_code": -1,
            "error": validation_error["message"],
            "details": validation_error,
            "preview": False,
        }

    # Render the command
    command_tokens = render_boutiques_command(
        command_template, boutiques_inputs, mapped_parameters
    )

    logger.info(f"Executing {tool_name}: {' '.join(command_tokens)}")

    # Resolve container configuration
    container_spec = _resolve_container_config(package, container_config, metadata)

    start_time = time.time()

    try:
        # Import container execution helpers from unified executors package
        from brain_researcher.services.tools.executors import (
            BindMount,
            ContainerRequest,
            run_container,
        )

        # Build mounts
        mounts = _build_mounts(container_spec.get("binds", []))

        request = ContainerRequest(
            image=container_spec["image"],
            command=command_tokens,
            runtime=container_spec.get("runtime", "apptainer"),
            workdir=work_dir,
            env=container_spec.get("env", {}),
            mounts=mounts,
            network_disabled=container_spec.get("network_disabled", True),
        )

        result = run_container(request)
        execution_time = time.time() - start_time

        return {
            "tool": tool_name,
            "command": " ".join(command_tokens),
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "mode": result.get("mode", "container"),
            "preview": False,
            "execution_time": execution_time,
            "applied_aliases": applied_aliases,
        }

    except ImportError:
        # Fallback to subprocess if container_runner not available
        import subprocess

        logger.warning("Container runner not available, falling back to subprocess")

        try:
            proc = subprocess.run(
                command_tokens,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=3600,  # 1 hour timeout
            )
            execution_time = time.time() - start_time

            return {
                "tool": tool_name,
                "command": " ".join(command_tokens),
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "mode": "subprocess",
                "preview": False,
                "execution_time": execution_time,
                "applied_aliases": applied_aliases,
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": tool_name,
                "command": " ".join(command_tokens),
                "exit_code": -1,
                "stdout": "",
                "stderr": "Execution timed out after 1 hour",
                "mode": "subprocess",
                "preview": False,
                "error": "timeout",
            }
        except Exception as e:
            return {
                "tool": tool_name,
                "command": " ".join(command_tokens),
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "mode": "subprocess",
                "preview": False,
                "error": str(e),
            }

    except Exception as exc:
        execution_time = time.time() - start_time
        logger.error(f"Container execution failed: {exc}", exc_info=True)
        return {
            "tool": tool_name,
            "command": " ".join(command_tokens),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "error": str(exc),
            "preview": False,
            "execution_time": execution_time,
        }


def _resolve_container_config(
    package: str,
    config_override: Optional[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve container configuration for a package."""
    if config_override:
        return config_override

    # Try to use container spec from metadata
    container_meta = metadata.get("container", {})
    if container_meta and container_meta.get("image"):
        image = container_meta["image"]

        # If image is just a package:version tag, resolve to actual path
        if ":" in image and "/" not in image:
            pkg, version = image.split(":", 1)
            image = _resolve_cvmfs_image(pkg, version)

        if os.path.exists(image):
            return {
                "image": image,
                "runtime": container_meta.get("type", "apptainer"),
                "binds": ["/data:/data", "/tmp:/tmp"],
                "env": {},
                "network_disabled": True,
            }

    # Fallback: use package-specific defaults
    return _get_package_defaults(package)


def _resolve_cvmfs_image(package: str, version: str) -> str:
    """Resolve a package:version tag to a CVMFS container path."""
    cvmfs_base = "/cvmfs/neurodesk.ardc.edu.au/containers"
    return f"{cvmfs_base}/{package}_{version}.sif"


def _get_package_defaults(package: str) -> Dict[str, Any]:
    """Get default container configuration for a package."""
    normalized = normalize_runtime_package_name(package)
    profile = get_neurodesk_package_profile(normalized)
    if isinstance(profile, dict):
        config = {
            "image": str(profile.get("container_path")),
            "binds": ["/data:/data", "/tmp:/tmp"],
            "env": dict(profile.get("env") or {}),
        }
    else:
        config = {
            "image": f"/cvmfs/neurodesk.ardc.edu.au/containers/{normalized}_latest.sif",
            "binds": ["/data:/data", "/tmp:/tmp"],
            "env": {},
        }

    config.setdefault("runtime", "apptainer")
    config.setdefault("network_disabled", True)

    return config


def _build_mounts(bind_specs: List[str]) -> List:
    """Convert bind specifications to mount objects."""
    try:
        from brain_researcher.services.tools.executors import BindMount

        mounts = []
        for spec in bind_specs:
            parts = spec.split(":")
            if len(parts) >= 2:
                host_path = parts[0]
                container_path = parts[1]
                read_only = "ro" in parts[2:] if len(parts) > 2 else False
                mounts.append(BindMount(host_path, container_path, read_only))
        return mounts
    except ImportError:
        return []


__all__ = [
    "render_boutiques_command",
    "preview_niwrap_tool",
    "build_command",
    "execute_niwrap_tool",
]


def build_command(
    tool_definition: Dict[str, Any], parameters: Dict[str, Any]
) -> List[str]:
    """Render a NiWrap command for the given tool definition and parameters.

    Thin wrapper around render_boutiques_command so tests can compare commands
    without invoking container execution.
    """
    metadata = tool_definition.get("metadata", {})
    command_template = metadata.get("command_line", "")
    inputs = metadata.get("boutiques_inputs", [])
    return render_boutiques_command(command_template, inputs, parameters)
