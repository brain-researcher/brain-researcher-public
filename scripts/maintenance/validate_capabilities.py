#!/usr/bin/env python3
"""Maintenance validation script for capabilities catalog.

This script validates the capabilities.yaml file against:
1. JSON Schema (capabilities.schema.json)
2. Pydantic models (via catalog_loader)

Exit codes:
0 - All validations passed
1 - Schema validation failed
2 - Pydantic validation failed
3 - File not found or other error
"""

import sys
import json
import subprocess
import warnings
from pathlib import Path

try:
    import yaml
    import jsonschema
except ImportError as e:
    print(f"ERROR: Missing required package: {e}")
    print("Install with: pip install pyyaml jsonschema")
    sys.exit(3)


def get_repo_root() -> Path:
    """Get repository root directory."""
    script_path = Path(__file__).resolve()
    return script_path.parents[2]  # scripts/maintenance/validate_capabilities.py -> repo root


def validate_schema(
    capabilities_path: Path, schema_path: Path
) -> tuple[bool, list[str]]:
    """Validate capabilities.yaml against JSON schema.

    Args:
        capabilities_path: Path to capabilities.yaml
        schema_path: Path to capabilities.schema.json

    Returns:
        Tuple of (success, error_messages)
    """
    errors = []

    # Load schema
    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        errors.append(f"Failed to load schema: {e}")
        return False, errors

    # Load capabilities as YAML then convert to dict for validation
    try:
        with capabilities_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"Failed to load capabilities YAML: {e}")
        return False, errors

    # Create resolver for local file references
    schema_dir = schema_path.parent
    resources_schema_path = schema_dir / "resources.schema.json"

    # Load referenced schemas
    referenced_schemas = {}
    if resources_schema_path.exists():
        with resources_schema_path.open("r", encoding="utf-8") as f:
            referenced_schemas["resources.schema.json"] = json.load(f)

    # Create a custom resolver (suppress deprecation warning for RefResolver)
    # TODO: Migrate to referencing library when jsonschema removes RefResolver
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        resolver = jsonschema.RefResolver(
            base_uri=schema_path.as_uri(),
            referrer=schema,
            store=referenced_schemas
        )

    # Validate against schema with resolver
    try:
        validator = jsonschema.Draft7Validator(schema, resolver=resolver)
        validator.validate(data)
        return True, []
    except jsonschema.ValidationError as e:
        errors.append(f"Schema validation error: {e.message}")
        errors.append(f"  Path: {' -> '.join(str(p) for p in e.absolute_path)}")
        errors.append(f"  Schema path: {' -> '.join(str(p) for p in e.schema_path)}")
        return False, errors
    except jsonschema.SchemaError as e:
        errors.append(f"Invalid schema: {e.message}")
        return False, errors


def validate_resource_types(capabilities_path: Path) -> tuple[bool, list[str]]:
    """Validate that consumes/produces use only allowed resource types from tool_resources.yaml.

    Args:
        capabilities_path: Path to capabilities.yaml

    Returns:
        Tuple of (success, error_messages)
    """
    errors = []
    repo_root = get_repo_root()

    # Load tool_resources.yaml to get allowed resource types
    resources_yaml_path = repo_root / "configs" / "tool_resources.yaml"
    if not resources_yaml_path.exists():
        errors.append(f"tool_resources.yaml not found at {resources_yaml_path}")
        return False, errors

    try:
        with resources_yaml_path.open("r", encoding="utf-8") as f:
            resources_data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"Failed to load tool_resources.yaml: {e}")
        return False, errors

    # Extract all resource type names from the "tools" section
    # Each tool in tool_resources.yaml can define custom resource types via consumes/produces
    # We also need to check the generated resources.schema.json for the canonical list
    resources_schema_path = repo_root / "configs" / "schemas" / "resources.schema.json"
    allowed_resources = set()

    if resources_schema_path.exists():
        try:
            with resources_schema_path.open("r", encoding="utf-8") as f:
                resources_schema = json.load(f)
                # Extract enum values from the schema
                if "$defs" in resources_schema and "resourceType" in resources_schema["$defs"]:
                    resource_enum = resources_schema["$defs"]["resourceType"].get("enum", [])
                    allowed_resources.update(resource_enum)
        except Exception as e:
            errors.append(f"Warning: Could not load resources.schema.json: {e}")

    if not allowed_resources:
        errors.append("No allowed resource types found in resources.schema.json")
        return False, errors

    # Load capabilities.yaml
    try:
        with capabilities_path.open("r", encoding="utf-8") as f:
            capabilities_data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"Failed to load capabilities.yaml: {e}")
        return False, errors

    # Validate each tool's consumes/produces
    tools = capabilities_data.get("tools", [])
    invalid_count = 0

    for tool in tools:
        tool_id = tool.get("id", "unknown")

        # Check consumes
        for resource in tool.get("consumes", []):
            if resource not in allowed_resources:
                errors.append(
                    f"Tool '{tool_id}' consumes invalid resource type: '{resource}'"
                )
                invalid_count += 1

        # Check produces
        for resource in tool.get("produces", []):
            if resource not in allowed_resources:
                errors.append(
                    f"Tool '{tool_id}' produces invalid resource type: '{resource}'"
                )
                invalid_count += 1

    if invalid_count > 0:
        errors.append(f"\nFound {invalid_count} invalid resource type(s)")
        errors.append(f"Allowed resource types ({len(allowed_resources)}): {', '.join(sorted(allowed_resources))}")
        return False, errors

    print(f"✓ All resource types valid (checked against {len(allowed_resources)} allowed types)")
    return True, []


def validate_pydantic(capabilities_path: Path) -> tuple[bool, list[str]]:
    """Validate capabilities using Pydantic models via catalog_loader.

    Args:
        capabilities_path: Path to capabilities.yaml

    Returns:
        Tuple of (success, error_messages)
    """
    errors = []

    # Import catalog_loader
    try:
        # Add repo root to path to allow imports
        repo_root = get_repo_root()
        sys.path.insert(0, str(repo_root / "src"))

        from brain_researcher.services.agent.planner.catalog_loader import (
            load_capabilities_yaml,
        )
    except ImportError as e:
        errors.append(f"Failed to import catalog_loader: {e}")
        errors.append("Make sure brain_researcher is installed: pip install -e .")
        return False, errors

    # Load and validate via Pydantic
    try:
        tools = load_capabilities_yaml(capabilities_path)
        print(f"✓ Successfully loaded {len(tools)} tools")

        # Print summary
        packages = set(t.package for t in tools)
        modalities = set(m for t in tools for m in t.modality)
        capabilities = set(c for t in tools for c in t.capabilities)

        print(f"  Packages: {', '.join(sorted(packages))}")
        print(f"  Modalities: {', '.join(sorted(modalities))}")
        print(f"  Capabilities: {len(capabilities)} unique tags")

        return True, []
    except Exception as e:
        errors.append(f"Pydantic validation error: {e}")
        return False, errors


def main():
    """Main validation entry point."""
    repo_root = get_repo_root()
    capabilities_path = repo_root / "configs" / "catalog" / "capabilities.yaml"
    schema_path = repo_root / "configs" / "schemas" / "capabilities.schema.json"

    print("=" * 60)
    print("Capabilities Catalog Validation")
    print("=" * 60)

    # Check files exist
    if not capabilities_path.exists():
        print(f"ERROR: Capabilities file not found: {capabilities_path}")
        sys.exit(3)

    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}")
        sys.exit(3)

    print(f"Capabilities: {capabilities_path}")
    print(f"Schema:       {schema_path}")
    print()

    # Run validations
    all_passed = True

    # 0. Generate resources schema
    print("[0/4] Generate Resource Types Schema")
    print("-" * 60)
    generator_script = (
        repo_root / "scripts" / "maintenance" / "generate_resources_schema.py"
    )
    try:
        result = subprocess.run(
            [sys.executable, str(generator_script)],
            capture_output=True,
            text=True,
            check=True
        )
        print("✓ Resource schema generated successfully")
    except subprocess.CalledProcessError as e:
        print("✗ Resource schema generation FAILED")
        print(f"  Error: {e.stderr}")
        all_passed = False
    print()

    # 1. JSON Schema validation
    print("[1/4] JSON Schema Validation")
    print("-" * 60)
    success, errors = validate_schema(capabilities_path, schema_path)
    if success:
        print("✓ Schema validation passed")
    else:
        print("✗ Schema validation FAILED")
        for error in errors:
            print(f"  {error}")
        all_passed = False
    print()

    # 2. Resource type validation (runtime check against tool_resources.yaml)
    print("[2/4] Resource Type Validation")
    print("-" * 60)
    success, errors = validate_resource_types(capabilities_path)
    if not success:
        print("✗ Resource type validation FAILED")
        for error in errors:
            print(f"  {error}")
        all_passed = False
    print()

    # 3. Pydantic validation
    print("[3/4] Pydantic Model Validation")
    print("-" * 60)
    success, errors = validate_pydantic(capabilities_path)
    if not success:
        print("✗ Pydantic validation FAILED")
        for error in errors:
            print(f"  {error}")
        all_passed = False
    print()

    # Final summary
    print("=" * 60)
    if all_passed:
        print("✓ All validations PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("✗ Validation FAILED")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
