"""Config loader for closed-loop priors.

Reads optional YAML at configs/closed_loop_priors.yaml with tunable knobs:
- min_samples: dataset_id/dataset_family/global
- smoothing: alpha/beta
- latency: fast_ms/slow_ms
- weights: evidence_prior/kg_prior
- constraints: mode/auto_relax

Falls back to sane defaults if file is missing or malformed.
"""

from __future__ import annotations

from typing import Any

import yaml

from brain_researcher.config.paths import resolve_from_config

_DEFAULTS: dict[str, Any] = {
    "min_samples": {"dataset_id": 5, "dataset_family": 5, "global": 0},
    "smoothing": {"alpha": 1.0, "beta": 1.0},
    "latency": {"fast_ms": 1000, "slow_ms": 60000},
    "weights": {"evidence_prior": 0.15, "kg_prior": 0.05},
    "constraints": {"mode": "relaxed", "auto_relax": True},
}


def load_prior_config() -> dict[str, Any]:
    path = resolve_from_config("closed_loop_priors.yaml")
    cfg: dict[str, Any] = {}
    try:
        if path.exists():
            cfg = yaml.safe_load(path.read_text()) or {}
    except Exception:
        cfg = {}

    def _merge(
        default: dict[str, Any], override: dict[str, Any] | None
    ) -> dict[str, Any]:
        out = dict(default)
        for k, v in (override or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
        return out

    return _merge(_DEFAULTS, cfg)


__all__ = ["load_prior_config"]
