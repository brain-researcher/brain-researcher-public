"""
Lightweight validity checks for GLM specs and design matrices.

The goal is to produce structured, explainable results that agents can act on
instead of raising opaque errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

try:  # optional dependency
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "warn" | "fail"
    details: str
    value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "details": self.details,
        }
        if self.value is not None:
            d["value"] = self.value
        return d


def _status_from_checks(checks: List[CheckResult]) -> str:
    if any(c.status == "fail" for c in checks):
        return "fail"
    if any(c.status == "warn" for c in checks):
        return "warn"
    return "pass"


def validate_spec(model: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a BIDS Stats Model at the spec level (no data needed)."""
    checks: List[CheckResult] = []

    required_top = ["Name", "BIDSModelVersion", "Input", "Nodes"]
    missing = [k for k in required_top if k not in model]
    if missing:
        checks.append(CheckResult("required_keys", "fail", f"Missing keys: {missing}"))
    else:
        checks.append(
            CheckResult("required_keys", "pass", "All required top-level keys present")
        )

    if not isinstance(model.get("Nodes"), list) or not model.get("Nodes"):
        checks.append(
            CheckResult("nodes_present", "fail", "Nodes must be a non-empty list")
        )
    else:
        checks.append(CheckResult("nodes_present", "pass", "Nodes present"))

    # JSON schema (optional)
    if jsonschema:
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["Name", "BIDSModelVersion", "Input", "Nodes"],
        }
        try:
            jsonschema.validate(model, schema)
            checks.append(CheckResult("jsonschema", "pass", "Passed minimal schema"))
        except Exception as exc:  # pragma: no cover - defensive
            checks.append(
                CheckResult("jsonschema", "warn", f"Schema validation warning: {exc}")
            )
    else:
        checks.append(
            CheckResult("jsonschema", "warn", "jsonschema not installed; skipped")
        )

    # Run node sanity: existence and X length
    run_node = None
    for node in model.get("Nodes", []):
        if str(node.get("Level", "")).lower() == "run":
            run_node = node
            break
    if not run_node:
        checks.append(CheckResult("run_node", "fail", "Missing run-level node"))
    else:
        x = run_node.get("Model", {}).get("X", [])
        if not isinstance(x, list) or len(x) == 0:
            checks.append(
                CheckResult("design_x", "fail", "Run Model.X is empty or not a list")
            )
        else:
            checks.append(
                CheckResult("design_x", "pass", f"{len(x)} regressors in run Model.X")
            )
        if len(x) > 200:
            checks.append(
                CheckResult(
                    "design_regressor_cap", "warn", f"Regressor count high ({len(x)})"
                )
            )
        tx = run_node.get("Transformations", {})
        if tx and "Instructions" not in tx:
            checks.append(
                CheckResult(
                    "transformations_shape",
                    "warn",
                    "Transformations missing Instructions list",
                )
            )
        else:
            checks.append(
                CheckResult("transformations_shape", "pass", "Transformations shape OK")
            )

    return {
        "status": _status_from_checks(checks),
        "checks": [c.to_dict() for c in checks],
    }


def validate_design(design_matrix: np.ndarray, tol: float = 1e-8) -> Dict[str, Any]:
    """Validate design matrix rank and condition number."""
    checks: List[CheckResult] = []
    if design_matrix.size == 0:
        checks.append(CheckResult("design_empty", "fail", "Design matrix is empty"))
        return {"status": "fail", "checks": [c.to_dict() for c in checks]}

    # Rank
    try:
        rank = np.linalg.matrix_rank(design_matrix, tol=tol)
        full_rank = rank == min(design_matrix.shape)
        status = "pass" if full_rank else "warn"
        checks.append(CheckResult("design_rank", status, f"rank={rank}", value=rank))
    except Exception as exc:  # pragma: no cover
        checks.append(
            CheckResult("design_rank", "warn", f"Failed to compute rank: {exc}")
        )

    # Condition number
    try:
        cond = np.linalg.cond(design_matrix)
        cond_status = "pass"
        if cond > 1e4:
            cond_status = "warn"
        if cond > 1e6:
            cond_status = "fail"
        checks.append(
            CheckResult(
                "condition_number", cond_status, f"cond={cond:.2e}", value=float(cond)
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(
            CheckResult("condition_number", "warn", f"Failed to compute cond: {exc}")
        )

    return {
        "status": _status_from_checks(checks),
        "checks": [c.to_dict() for c in checks],
    }


def validate_contrast(contrast: Any, design_matrix: np.ndarray) -> Dict[str, Any]:
    """Validate a contrast vector against design matrix."""
    checks: List[CheckResult] = []
    c = np.asarray(contrast)
    if c.ndim != 1:
        checks.append(CheckResult("contrast_shape", "fail", "Contrast must be 1-D"))
    elif c.shape[0] != design_matrix.shape[1]:
        checks.append(
            CheckResult(
                "contrast_length",
                "fail",
                f"Contrast length {c.shape[0]} != design columns {design_matrix.shape[1]}",
                value=int(c.shape[0]),
            )
        )
    else:
        checks.append(
            CheckResult("contrast_length", "pass", "Contrast length matches design")
        )
        if np.allclose(c, 0):
            checks.append(
                CheckResult("contrast_nonzero", "fail", "Contrast is all zeros")
            )
        else:
            checks.append(
                CheckResult("contrast_nonzero", "pass", "Contrast has non-zero weights")
            )

    return {
        "status": _status_from_checks(checks),
        "checks": [c.to_dict() for c in checks],
    }
