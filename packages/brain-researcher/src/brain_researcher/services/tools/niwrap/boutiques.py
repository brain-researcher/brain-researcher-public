"""Boutiques descriptor loader for NiWrap tools.

This module loads Boutiques JSON descriptors from the NiWrap repository and
converts them into tool definitions with JSON Schema validation.

Moved from: archive/mcp_server/adapters/boutiques_loader.py
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContainerSpec:
    """Container image specification for a tool."""

    image: str
    type: str = "apptainer"  # docker, apptainer, singularity
    index: Optional[str] = None
    entrypoint: Optional[str] = None


@dataclass
class NiwrapDescriptor:
    """Parsed representation of a NiWrap Boutiques descriptor."""

    package: str  # e.g., "afni", "fsl", "ants"
    version: str  # e.g., "24.2.06"
    app: str  # e.g., "3dBlurInMask", "bet"
    boutiques: Dict[str, Any]  # Raw Boutiques JSON
    docs: Optional[str] = None  # Optional documentation text
    container: Optional[ContainerSpec] = None

    @property
    def tool_name(self) -> str:
        """Generate versioned tool name: package.version.app.run"""
        return f"{self.package}.{self.version}.{self.app}.run"

    @property
    def tool_alias(self) -> str:
        """Generate stable alias without version: package.app.run"""
        return f"{self.package}.{self.app}.run"


def walk_niwrap_descriptors(
    niwrap_root: Optional[Path] = None,
    packages: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Iterable[NiwrapDescriptor]:
    """Walk the NiWrap directory tree and yield parsed descriptors.

    Args:
        niwrap_root: Root path to NiWrap repository. Defaults to external/niwrap
        packages: Optional list of package names to filter (e.g., ["afni", "fsl"])
        limit: Optional limit on number of descriptors to return (for testing)

    Yields:
        NiwrapDescriptor instances for each boutiques.json found
    """
    if niwrap_root is None:
        # Default to external/niwrap relative to project root
        # This file is at: src/brain_researcher/services/tools/niwrap/boutiques.py
        module_path = Path(__file__).resolve()
        # Go up: niwrap -> tools -> services -> brain_researcher (package) -> brain_researcher (repo)
        project_root = module_path.parents[4]
        niwrap_root = project_root / "external" / "niwrap" / "src" / "niwrap"

    if not niwrap_root.exists():
        logger.warning(f"NiWrap root not found: {niwrap_root}")
        return

    count = 0
    # Directory structure: niwrap/{package}/{version}/{app}/boutiques.json
    for package_dir in sorted(niwrap_root.iterdir()):
        if not package_dir.is_dir():
            continue

        package_name = package_dir.name
        if packages and package_name not in packages:
            continue

        for version_dir in sorted(package_dir.iterdir()):
            if not version_dir.is_dir():
                continue

            version = version_dir.name

            for app_dir in sorted(version_dir.iterdir()):
                if not app_dir.is_dir():
                    continue

                app_name = app_dir.name
                boutiques_file = app_dir / "boutiques.json"

                if not boutiques_file.exists():
                    continue

                try:
                    descriptor = parse_boutiques_descriptor(
                        boutiques_file, package_name, version, app_name
                    )
                    if descriptor:
                        yield descriptor
                        count += 1
                        if limit and count >= limit:
                            return
                except Exception as exc:
                    logger.debug(
                        f"Failed to parse {boutiques_file}: {exc}",
                        exc_info=True,
                    )


def parse_boutiques_descriptor(
    boutiques_path: Path,
    package: str,
    version: str,
    app: str,
) -> Optional[NiwrapDescriptor]:
    """Parse a single Boutiques JSON file into a NiwrapDescriptor.

    Args:
        boutiques_path: Path to boutiques.json file
        package: Package name (e.g., "afni")
        version: Version string (e.g., "24.2.06")
        app: Application name (e.g., "3dBlurInMask")

    Returns:
        NiwrapDescriptor if parsing succeeded, None otherwise
    """
    try:
        with open(boutiques_path, "r", encoding="utf-8") as f:
            boutiques_json = json.load(f)
    except (IOError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to load {boutiques_path}: {exc}")
        return None

    # Extract optional documentation
    docs = None
    docs_file = boutiques_path.parent / "README.md"
    if docs_file.exists():
        try:
            docs = docs_file.read_text(encoding="utf-8")
        except IOError:
            pass

    # Extract container information if available
    container_spec = _extract_container_spec(boutiques_json, package, version)

    return NiwrapDescriptor(
        package=package,
        version=version,
        app=app,
        boutiques=boutiques_json,
        docs=docs,
        container=container_spec,
    )


def _extract_container_spec(
    boutiques: Dict[str, Any], package: str, version: str
) -> Optional[ContainerSpec]:
    """Extract container information from Boutiques descriptor."""
    # Check for container-image in Boutiques spec
    container_image = boutiques.get("container-image")
    if container_image:
        image_dict = container_image if isinstance(container_image, dict) else {}
        return ContainerSpec(
            image=image_dict.get("image", ""),
            type=image_dict.get("type", "docker"),
            index=image_dict.get("index"),
            entrypoint=image_dict.get("entrypoint"),
        )

    # Fallback: generate default container path
    return ContainerSpec(
        image=f"{package}:{version}",
        type="apptainer",
    )


def boutiques_to_json_schema(
    inputs: List[Dict[str, Any]], required_only: bool = False
) -> Dict[str, Any]:
    """Convert Boutiques inputs to JSON Schema format.

    Args:
        inputs: List of Boutiques input descriptors
        required_only: If True, only include required fields

    Returns:
        JSON Schema object with properties and required fields
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for input_spec in inputs:
        input_id = input_spec.get("id")
        if not input_id:
            continue

        # Flags are always optional
        input_type = input_spec.get("type", "String")
        if input_type == "Flag":
            optional = True
        else:
            optional = input_spec.get("optional", False)

        if required_only and optional:
            continue

        # Build property schema
        prop_schema = _boutiques_input_to_property(input_spec)
        properties[input_id] = prop_schema

        # Track required fields
        if not optional:
            required.append(input_id)

    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }

    if required:
        schema["required"] = required

    return schema


def _boutiques_input_to_property(input_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a single Boutiques input to a JSON Schema property."""
    prop: Dict[str, Any] = {}

    # Extract description
    description = input_spec.get("description", input_spec.get("name", ""))
    if description:
        prop["description"] = description

    # Map Boutiques type to JSON Schema type
    boutiques_type = input_spec.get("type", "String")
    is_list = input_spec.get("list", False)

    if boutiques_type == "File":
        base_type = "string"
        prop["format"] = "uri-reference"
    elif boutiques_type == "Number":
        base_type = "number"
    elif boutiques_type == "Flag":
        base_type = "boolean"
    elif boutiques_type == "String":
        base_type = "string"
    else:
        base_type = "string"

    # Handle list parameters
    if is_list:
        prop["type"] = "array"
        item_schema: Dict[str, Any] = {"type": base_type}
        if "format" in prop:
            item_schema["format"] = prop.pop("format")
        prop["items"] = item_schema

        # Handle min/max list entries
        min_entries = input_spec.get("min-list-entries")
        max_entries = input_spec.get("max-list-entries")
        if min_entries is not None:
            prop["minItems"] = min_entries
        if max_entries is not None:
            prop["maxItems"] = max_entries
    else:
        prop["type"] = base_type

    # Handle enums/value-choices
    value_choices = input_spec.get("value-choices")
    if value_choices:
        prop["enum"] = value_choices

    # Handle numeric constraints
    if boutiques_type == "Number" and not is_list:
        minimum = input_spec.get("minimum")
        maximum = input_spec.get("maximum")
        if minimum is not None:
            prop["minimum"] = minimum
        if maximum is not None:
            prop["maximum"] = maximum

    # Handle default value
    default = input_spec.get("default-value")
    if default is not None:
        prop["default"] = default

    return prop


def build_tool_definition(descriptor: NiwrapDescriptor) -> Dict[str, Any]:
    """Build tool definition from a NiwrapDescriptor.

    Args:
        descriptor: Parsed NiWrap descriptor

    Returns:
        Tool definition dictionary with name, description, schemas, etc.
    """
    boutiques = descriptor.boutiques

    # Extract inputs and outputs
    inputs = boutiques.get("inputs", [])
    outputs = boutiques.get("output-files", [])

    # Build schemas
    input_schema = boutiques_to_json_schema(inputs)
    output_schema = _build_output_schema(outputs)

    # Assign tags
    tags = _assign_tags(descriptor)

    # Assign passports
    passports = _assign_passports(descriptor, outputs)

    # Infer resource hints
    resources = _infer_resource_hints(descriptor)

    # Build tool definition
    tool_def = {
        "name": descriptor.tool_name,
        "description": boutiques.get("description", f"{descriptor.app} from {descriptor.package}"),
        "input_schema": input_schema,
        "output_schema": output_schema,
        "tags": tags,
        "metadata": {
            "package": descriptor.package,
            "version": descriptor.version,
            "app": descriptor.app,
            "command_line": boutiques.get("command-line", ""),
            "passports": passports,
            "alias": descriptor.tool_alias,
            "boutiques_inputs": inputs,  # Preserve for command rendering
            "container": descriptor.container.__dict__ if descriptor.container else None,
            "resources": resources,
        },
    }

    # Add documentation if available
    if descriptor.docs:
        tool_def["metadata"]["docs"] = descriptor.docs

    return tool_def


def _build_output_schema(outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build JSON Schema for outputs from Boutiques output-files."""
    if not outputs:
        return {
            "type": "object",
            "properties": {
                "exit_code": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
            },
        }

    properties: Dict[str, Any] = {
        "exit_code": {"type": "integer"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
    }

    for output in outputs:
        output_id = output.get("id")
        if output_id:
            properties[output_id] = {
                "type": "string",
                "description": output.get("description", output.get("name", "Output file")),
                "format": "uri-reference",
            }

    return {"type": "object", "properties": properties}


def _assign_tags(descriptor: NiwrapDescriptor) -> List[str]:
    """Assign tags for a tool based on package and metadata."""
    tags = ["neuro", descriptor.package]

    # Add family-specific tags
    if descriptor.package == "fsl":
        tags.append("fsl")
    elif descriptor.package == "afni":
        tags.append("afni")
    elif descriptor.package == "ants":
        tags.append("ants")
        tags.append("registration")
    elif descriptor.package == "freesurfer":
        tags.append("freesurfer")
        tags.append("segmentation")
    elif descriptor.package == "mrtrix":
        tags.append("mrtrix")
        tags.append("diffusion")

    # Infer additional tags from app name
    app_lower = descriptor.app.lower()
    if "reg" in app_lower or "transform" in app_lower:
        tags.append("registration")
    if "seg" in app_lower or "label" in app_lower:
        tags.append("segmentation")
    if "bet" in app_lower or "skull" in app_lower:
        tags.append("skull-strip")
    if "smooth" in app_lower or "blur" in app_lower:
        tags.append("preprocessing")

    return list(set(tags))


def _assign_passports(
    descriptor: NiwrapDescriptor, outputs: List[Dict[str, Any]]
) -> List[str]:
    """Assign passports (permissions) for a tool."""
    passports: List[str] = []

    if outputs:
        passports.append("write")

    if descriptor.package == "freesurfer":
        passports.append("license:fs")

    boutiques = descriptor.boutiques
    command_line = boutiques.get("command-line", "").lower()
    if "cuda" in command_line or "gpu" in command_line:
        passports.append("gpu")

    return passports


def _infer_resource_hints(descriptor: NiwrapDescriptor) -> Dict[str, Any]:
    """Infer resource requirements and hints from tool metadata."""
    boutiques = descriptor.boutiques
    package = descriptor.package
    app_name = descriptor.app.lower()
    command_line = boutiques.get("command-line", "").lower()
    inputs = boutiques.get("inputs", [])

    resources = {
        "cpu_cores": _infer_cpu_requirement(inputs, command_line),
        "memory_gb": _infer_memory_requirement(package, app_name, command_line),
        "gpu": _infer_gpu_requirement(package, app_name, command_line),
        "runtime_estimate": _infer_runtime_estimate(package, app_name),
    }

    return resources


def _infer_cpu_requirement(inputs: List[Dict], command_line: str) -> Dict[str, int]:
    """Infer CPU core requirements."""
    threading_keywords = ["thread", "parallel", "cores", "cpu", "proc", "jobs", "nthreads"]

    has_threading = False
    for input_spec in inputs:
        input_id = input_spec.get("id", "").lower()
        input_name = input_spec.get("name", "").lower()
        input_desc = input_spec.get("description", "").lower()

        if any(kw in input_id or kw in input_name or kw in input_desc
               for kw in threading_keywords):
            has_threading = True
            break

    if not has_threading:
        has_threading = any(kw in command_line for kw in threading_keywords)

    if has_threading:
        return {"min": 1, "max": 16, "default": 4}
    else:
        return {"min": 1, "max": 1, "default": 1}


def _infer_memory_requirement(package: str, app_name: str, command_line: str) -> Dict[str, float]:
    """Infer memory requirements in GB."""
    package_defaults = {
        "freesurfer": {"min": 4.0, "recommended": 8.0},
        "fsl": {"min": 2.0, "recommended": 4.0},
        "afni": {"min": 2.0, "recommended": 4.0},
        "ants": {"min": 4.0, "recommended": 8.0},
        "mrtrix": {"min": 4.0, "recommended": 8.0},
        "workbench": {"min": 2.0, "recommended": 4.0},
    }

    base = package_defaults.get(package, {"min": 1.0, "recommended": 2.0})

    memory_intensive_keywords = ["registration", "segment", "recon", "tract", "tensor"]
    if any(kw in app_name for kw in memory_intensive_keywords):
        base["min"] *= 2
        base["recommended"] *= 2

    return base


def _infer_gpu_requirement(package: str, app_name: str, command_line: str) -> str:
    """Infer GPU requirements."""
    gpu_keywords = ["cuda", "gpu", "opencl"]
    has_gpu = any(kw in app_name or kw in command_line for kw in gpu_keywords)

    if has_gpu:
        return "optional"
    else:
        return "none"


def _infer_runtime_estimate(package: str, app_name: str) -> str:
    """Estimate typical runtime for a tool."""
    very_slow_keywords = ["recon-all", "reconall", "bedpostx", "probtrackx"]
    if any(kw in app_name for kw in very_slow_keywords):
        return "hours to days"

    slow_keywords = ["registration", "segment", "tract", "tensor", "dti"]
    if any(kw in app_name for kw in slow_keywords):
        return "30 min - 2 hours"

    medium_keywords = ["preprocess", "normalize", "smooth", "realign", "motion"]
    if any(kw in app_name for kw in medium_keywords):
        return "5-30 minutes"

    fast_keywords = ["info", "convert", "extract", "mask", "stats", "calc"]
    if any(kw in app_name for kw in fast_keywords):
        return "< 5 minutes"

    return "5-30 minutes"


__all__ = [
    "NiwrapDescriptor",
    "ContainerSpec",
    "walk_niwrap_descriptors",
    "parse_boutiques_descriptor",
    "boutiques_to_json_schema",
    "build_tool_definition",
]
