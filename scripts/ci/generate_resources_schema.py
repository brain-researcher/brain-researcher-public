#!/usr/bin/env python3
"""Generate resources.schema.json from canonical ResourceType enum.

This script extracts all resource types from the ResourceType Literal in
src/brain_researcher/services/shared/planner/models.py and generates a JSON
schema file that can be referenced by capabilities.schema.json.

This ensures the schema stays in sync with the canonical resource type list.
"""

import json
import sys
from pathlib import Path

import yaml

# Ensure project modules are importable when run directly
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "src"))
from brain_researcher.services.shared.planner.models import ResourceType


def get_repo_root() -> Path:
    """Get repository root directory."""
    script_path = Path(__file__).resolve()
    return script_path.parents[2]  # scripts/ci/generate_resources_schema.py -> repo root


def load_resource_types_from_yaml(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text()) or {}
    names = [entry.get("name") for entry in data.get("resources", []) if entry.get("name")]
    if not names:
        raise ValueError(f"No resources found in {path}")
    return sorted(set(names))


def generate_schema(resource_types: list[str]) -> dict:
    """Generate JSON schema for resource types.

    Args:
        resource_types: List of resource type strings

    Returns:
        JSON schema dict
    """
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://brain-researcher.org/schemas/resources.schema.json",
        "title": "Brain Researcher Resource Types Schema",
        "description": "Auto-generated schema defining valid resource types",
        "$defs": {
            "resourceType": {
                "type": "string",
                "enum": resource_types,
                "description": "Valid resource type identifier"
            }
        }
    }


def extract_resource_types(models_file: Path) -> list[str]:
    """Return sorted unique resource types from canonical model (ignores file path)."""
    # Single source of truth lives in ResourceType._ALLOWED
    return sorted(ResourceType.get_allowed())


def main():
    """Main entry point."""
    repo_root = get_repo_root()

    # Paths
    models_file = (
        repo_root
        / "src"
        / "brain_researcher"
        / "services"
        / "shared"
        / "planner"
        / "models.py"
    )
    output_file = repo_root / "configs" / "schemas" / "resources.schema.json"

    print("=" * 70)
    print("Resource Schema Generator")
    print("=" * 70)
    print(f"Source: {models_file}")
    print(f"Output: {output_file}")
    print()

    # Check source exists
    if not models_file.exists():
        print(f"ERROR: Planner models file not found: {models_file}")
        sys.exit(1)

    # Extract resource types
    try:
        resource_types = extract_resource_types(models_file)
        print(f"✓ Loaded {len(resource_types)} resource types from {models_file}")
        print(f"  Types: {', '.join(resource_types[:10])}")
        if len(resource_types) > 10:
            print(f"         ...and {len(resource_types) - 10} more")
        print()
    except Exception as e:
        print(f"ERROR: Failed to extract resource types: {e}")
        sys.exit(1)

    # Generate schema
    schema = generate_schema(resource_types)
    print(f"✓ Generated schema with {len(resource_types)} enum values")
    print()

    # Write to file
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
            f.write("\n")  # Add trailing newline
        print(f"✓ Wrote schema to {output_file}")
    except Exception as e:
        print(f"ERROR: Failed to write schema: {e}")
        sys.exit(1)

    print()
    print("=" * 70)
    print("✓ Resource schema generation complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
