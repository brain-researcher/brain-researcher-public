#!/usr/bin/env python3
"""Validate tool-related KG YAML files against JSON Schemas.

Checks:
- configs/br-kg/schema/tool.yaml          -> configs/schemas/tool.schema.json
- configs/br-kg/schema/tool_version.yaml  -> configs/schemas/tool_version.schema.json
- configs/br-kg/schema/tool_run.yaml      -> configs/schemas/tool_run.schema.json (optional; skipped if missing)
- configs/br-kg/tool_evidence.yaml structure (basic shape only)
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_instance(yaml_path: Path, schema_path: Path) -> None:
    """Validate a data file against a JSON schema."""

    schema = _load_json(schema_path)
    data = _load_yaml(yaml_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        lines = [f"{yaml_path} invalid against {schema_path}"]
        for err in errors:
            path = "/".join(map(str, err.path)) or "<root>"
            lines.append(f"- {path}: {err.message}")
        raise SystemExit("\n".join(lines))


def validate_schema_yaml_shape(yaml_path: Path) -> None:
    """Ensure KG schema yaml has minimum expected keys (label/key/properties)."""

    data = _load_yaml(yaml_path)
    required_keys = {"label", "key", "properties"}
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise SystemExit(f"{yaml_path} missing required keys: {missing}")


def validate_evidence(evidence_path: Path) -> None:
    data = _load_yaml(evidence_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Evidence must be a mapping: {evidence_path}")
    tools = data.get("tools", {})
    if not isinstance(tools, dict):
        raise SystemExit(f"Evidence.tools must be a mapping: {evidence_path}")
    for tool_id, payload in tools.items():
        if not isinstance(payload, dict):
            raise SystemExit(f"tools[{tool_id}] must be a mapping")
        pubs = payload.get("publications", [])
        if pubs is not None and not isinstance(pubs, list):
            raise SystemExit(f"tools[{tool_id}].publications must be a list")
        validated = payload.get("validated_on_collections", [])
        if validated is not None and not isinstance(validated, list):
            raise SystemExit(f"tools[{tool_id}].validated_on_collections must be a list")


def main() -> None:
    schema_dir = ROOT / "configs/schemas"
    kg_schema_dir = ROOT / "configs/br-kg/schema"
    validate_schema_yaml_shape(kg_schema_dir / "tool.yaml")
    validate_schema_yaml_shape(kg_schema_dir / "tool_version.yaml")
    tool_run_yaml = kg_schema_dir / "tool_run.yaml"
    tool_run_schema = schema_dir / "tool_run.schema.json"
    if tool_run_yaml.exists() and tool_run_schema.exists():
        validate_schema_yaml_shape(tool_run_yaml)
    validate_evidence(ROOT / "configs/br-kg/tool_evidence.yaml")
    print("tool schemas validated ok")


if __name__ == "__main__":
    main()
