"""Lightweight loader for behavior outlier policies.

Relocated from ``services/agent/resources/behavior_policies`` into the shared
layer so that both ``services/tools`` and ``services/agent`` can depend on it
without creating a tools -> agent back-edge. The original module re-exports
these symbols for backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.paths import resolve_from_config

DEFAULT_POLICY_PATH = resolve_from_config("behavior_outlier_policy.yaml")
DEFAULT_POLICY_DIR = resolve_from_config("behavior_policies")


def _iter_candidate_paths(paths: list[str] | None) -> list[Path]:
    cands: list[Path] = []
    raw_inputs = paths or [str(DEFAULT_POLICY_PATH), str(DEFAULT_POLICY_DIR)]
    for raw in raw_inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            cands.extend(sorted(path.glob("*.yaml")))
            cands.extend(sorted(path.glob("*.yml")))
            cands.extend(sorted(path.glob("*.json")))
        elif path.exists():
            cands.append(path)
    return cands


def load_behavior_policies(paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Load one or more behavior policy YAML/JSON files (dedup by policy_id)."""
    policies: dict[str, dict[str, Any]] = {}
    for path in _iter_candidate_paths(paths):
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            continue
        pid = data.get("policy_id") or path.stem
        data["policy_id"] = pid
        policies[pid] = data
    return list(policies.values())


__all__ = ["load_behavior_policies", "DEFAULT_POLICY_PATH", "DEFAULT_POLICY_DIR"]
