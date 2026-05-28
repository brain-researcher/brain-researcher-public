"""Tests for resource schema generation script."""

import json
import re
from pathlib import Path
import pytest

# Import functions from the generator script
import sys
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root / "scripts" / "ci"))

from generate_resources_schema import extract_resource_types, generate_schema


class TestResourceTypeExtraction:
    """Test extraction of resource types from models.py."""

    def test_extract_from_models_file(self):
        """Test extracting resource types from actual models.py."""
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"

        resource_types = extract_resource_types(models_file)

        # Should have resource types
        assert len(resource_types) > 0

        # Should be sorted and unique
        assert resource_types == sorted(set(resource_types))

        # Check for known resource types
        assert "volume_3d" in resource_types
        assert "volume_4d" in resource_types
        assert "timeseries" in resource_types
        assert "connectivity_matrix" in resource_types

    def test_extraction_handles_multiline_literal(self):
        """Test that extraction works with multiline Literal definitions."""
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"

        # Verify the file has ResourceType definition
        with models_file.open("r", encoding="utf-8") as f:
            content = f.read()

        assert "ResourceType" in content
        assert "Literal[" in content

        resource_types = extract_resource_types(models_file)

        # Should extract successfully
        assert len(resource_types) >= 20  # Should have at least 20 types

    def test_extracted_types_match_expected_count(self):
        """Test that we extract the expected number of resource types."""
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"

        resource_types = extract_resource_types(models_file)

        from brain_researcher.services.shared.planner.models import ResourceType
        assert len(resource_types) == len(ResourceType.get_allowed())


class TestSchemaGeneration:
    """Test schema generation."""

    def test_generate_schema_structure(self):
        """Test that generated schema has correct structure."""
        resource_types = ["volume_3d", "volume_4d", "timeseries"]

        schema = generate_schema(resource_types)

        # Check required fields
        assert "$schema" in schema
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema
        assert "title" in schema
        assert "description" in schema
        assert "$defs" in schema

        # Check resource type definition
        assert "resourceType" in schema["$defs"]
        resource_def = schema["$defs"]["resourceType"]
        assert resource_def["type"] == "string"
        assert "enum" in resource_def
        assert resource_def["enum"] == resource_types

    def test_generate_schema_validates_as_json(self):
        """Test that generated schema is valid JSON."""
        resource_types = ["type1", "type2", "type3"]

        schema = generate_schema(resource_types)

        # Should be serializable
        json_str = json.dumps(schema)

        # Should be deserializable
        parsed = json.loads(json_str)
        assert parsed == schema

    def test_generate_schema_with_actual_types(self):
        """Test schema generation with actual resource types."""
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"
        resource_types = extract_resource_types(models_file)

        schema = generate_schema(resource_types)

        # Check all types are in enum
        enum_values = schema["$defs"]["resourceType"]["enum"]
        assert set(enum_values) == set(resource_types)

        # Check specific known types
        assert "volume_3d" in enum_values
        assert "connectivity_matrix" in enum_values


class TestGeneratedSchemaFile:
    """Test the actual generated schema file."""

    def test_generated_file_exists(self):
        """Test that the generated schema file exists."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"

        assert schema_file.exists()

    def test_generated_file_valid_json(self):
        """Test that generated file is valid JSON."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"

        with schema_file.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        assert isinstance(schema, dict)
        assert "$schema" in schema
        assert "$defs" in schema

    def test_generated_file_contains_all_types(self):
        """Test that generated file contains all resource types from models.py."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"

        # Load generated schema
        with schema_file.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        # Extract types from models.py
        expected_types = extract_resource_types(models_file)

        # Check schema has all types
        actual_types = schema["$defs"]["resourceType"]["enum"]
        assert set(actual_types) == set(expected_types)

    def test_generated_file_has_24_types(self):
        """Test that generated file has the expected 24 resource types."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"

        with schema_file.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        enum_values = schema["$defs"]["resourceType"]["enum"]
        from brain_researcher.services.shared.planner.models import ResourceType
        assert len(enum_values) == len(ResourceType.get_allowed())


class TestSchemaConsistency:
    """Test consistency between schema and code."""

    def test_schema_matches_models_literal(self):
        """Test that schema enum matches ResourceType Literal in models.py."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"
        models_file = repo_root / "src/brain_researcher" / "services" / "shared" / "planner" / "models.py"

        # Load schema
        with schema_file.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        schema_types = set(schema["$defs"]["resourceType"]["enum"])

        # Extract from models
        model_types = set(extract_resource_types(models_file))

        # Should match exactly
        assert schema_types == model_types, (
            f"Schema types don't match models.py\n"
            f"In schema but not models: {schema_types - model_types}\n"
            f"In models but not schema: {model_types - schema_types}"
        )

    def test_known_resource_types_present(self):
        """Test that known resource types are present in both schema and models."""
        schema_file = repo_root / "configs" / "schemas" / "resources.schema.json"

        with schema_file.open("r", encoding="utf-8") as f:
            schema = json.load(f)

        enum_values = schema["$defs"]["resourceType"]["enum"]

        # Check for known types that should always be present
        known_types = [
            "volume_3d",
            "volume_4d",
            "timeseries",
            "connectivity_matrix",
            "bids_root",
            "stat_map",
            "parcellation_labels",
        ]

        for resource_type in known_types:
            assert resource_type in enum_values, f"Expected resource type '{resource_type}' not found in schema"
