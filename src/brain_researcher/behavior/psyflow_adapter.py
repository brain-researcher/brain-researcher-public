"""Lazy psyflow integration: scaffold writer, validator, and run ingest.

All psyflow access is gated through ``_import_psyflow`` so the core package
remains importable without the ``behavior-task`` extra. The adapter enforces
the planned/run directory split: generate-step artifacts live under
``<out>/planned/<paradigm>/`` while executed psyflow runs are written by
external actors under ``<out>/run/...`` and only read by ``ingest_psyflow_run``.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from brain_researcher.behavior.task_spec import (
    BehaviorTaskSpecV1,
    PsyflowTaskBundleV1,
    spec_digest,
)


class PsyflowNotInstalledError(RuntimeError):
    """Raised when the ``behavior-task`` extra (psyflow) is not installed."""


def _prime_psyflow_version_shim() -> None:
    """Work around psyflow's broken wheel-time version lookup.

    Upstream ``psyflow.__init__`` imports ``psyflow._version`` and that module
    reads ``../pyproject.toml`` relative to the installed package. In wheel
    installs that file is absent, so importing ``psyflow`` raises
    ``FileNotFoundError`` before any useful functionality is available.

    We own a single lazy import boundary here, so synthesize the
    ``psyflow._version`` module from installed distribution metadata first.
    This keeps the workaround local to BR instead of mutating site-packages on
    disk or requiring an editable install.
    """
    if "psyflow._version" in sys.modules:
        return
    try:
        version = importlib.metadata.version("psyflow")
    except importlib.metadata.PackageNotFoundError:
        return
    shim = ModuleType("psyflow._version")
    shim.__version__ = version
    sys.modules["psyflow._version"] = shim


def _import_psyflow():
    """Import ``psyflow`` lazily or raise ``PsyflowNotInstalledError``."""
    try:
        _prime_psyflow_version_shim()
        import psyflow  # type: ignore

        return psyflow
    except ImportError as exc:
        raise PsyflowNotInstalledError(
            "psyflow extra not installed; install with "
            "`pip install brain_researcher[behavior-task]`"
        ) from exc


_MAIN_STUB = (
    '"""Psyflow entrypoint — generated scaffold.\n\n'
    "Replace this stub with a runnable psyflow task. See "
    "`config/config.yaml` and `task_spec.json`.\n"
    '"""\n\n'
    "def main() -> None:\n"
    "    raise SystemExit(\n"
    '        "This is a generated scaffold. Implement or import a psyflow "\n'
    '        "runner to execute the task."\n'
    "    )\n\n\n"
    'if __name__ == "__main__":\n'
    "    main()\n"
)


def write_psyflow_scaffold(
    spec: BehaviorTaskSpecV1,
    out_dir: str | Path,
    config_mapper: Callable[[BehaviorTaskSpecV1], dict[str, Any]],
) -> PsyflowTaskBundleV1:
    """Write a psyflow scaffold under ``<out_dir>/planned/<paradigm>/``.

    Artifacts: ``config/config.yaml``, ``main.py``, ``task_spec.json``,
    ``spec_digest.txt``. Never writes under ``<out_dir>/run/``.
    """
    out_root = Path(out_dir).resolve()
    planned_root = out_root / "planned"
    bundle_dir = planned_root / spec.paradigm
    run_root = out_root / "run"

    # Refuse to write into or under the run tree.
    bundle_resolved = bundle_dir.resolve()
    run_resolved = run_root.resolve()
    try:
        bundle_resolved.relative_to(run_resolved)
    except ValueError:
        # not under run tree — happy path.
        pass
    else:
        raise ValueError(
            "refusing to write scaffold under <out>/run/; "
            "planned scaffolds must live under <out>/planned/"
        )

    (bundle_dir / "config").mkdir(parents=True, exist_ok=True)

    cfg = config_mapper(spec)
    cfg_path = bundle_dir / "config" / "config.yaml"
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=True)

    main_path = bundle_dir / "main.py"
    main_path.write_text(_MAIN_STUB, encoding="utf-8")

    spec_path = bundle_dir / "task_spec.json"
    spec_path.write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    digest = spec_digest(spec)
    (bundle_dir / "spec_digest.txt").write_text(digest, encoding="utf-8")

    files = [
        "config/config.yaml",
        "main.py",
        "task_spec.json",
        "spec_digest.txt",
    ]

    return PsyflowTaskBundleV1(
        spec_digest=digest,
        paradigm=spec.paradigm,
        bundle_dir=str(bundle_dir),
        entrypoint="main.py",
        config_path="config/config.yaml",
        planned_dir=str(bundle_dir),
        run_dir=None,
        files=files,
        created_ts=datetime.now(timezone.utc).isoformat(),
        psyflow_commit=None,
    )


def run_psyflow_validate(bundle: PsyflowTaskBundleV1) -> dict[str, Any]:
    """Best-effort psyflow config validation; requires the extra."""
    psyflow = _import_psyflow()
    cfg = Path(bundle.bundle_dir) / bundle.config_path
    validate_config = getattr(psyflow, "validate_config", None)
    if callable(validate_config):
        try:
            raw_config = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            result = validate_config(raw_config)
            return {"status": "success", "result": result}
        except Exception as exc:  # pragma: no cover - depends on psyflow
            return {"status": "error", "error": str(exc)}

    validator = getattr(psyflow, "validate", None)
    if not callable(validator):
        return {
            "status": "skipped",
            "reason": "psyflow.validate_config / psyflow.validate not available",
        }
    try:
        result = validator(str(cfg))
        return {"status": "success", "result": result}
    except Exception as exc:  # pragma: no cover - depends on psyflow
        return {"status": "error", "error": str(exc)}


def ingest_psyflow_run(
    bundle: PsyflowTaskBundleV1,
    run_data_dir: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Normalize a psyflow run into canonical behavior trials.

    Enforces ``run_data_dir`` lives under ``<out_dir>/run/``.
    """
    out_root = Path(out_dir).resolve()
    run_root = (out_root / "run").resolve()
    run_dir = Path(run_data_dir).resolve()
    try:
        run_dir.relative_to(run_root)
    except ValueError as exc:
        raise ValueError(
            "run_data_dir must live under <out_dir>/run/ (planned vs run split): "
            f"run_data_dir={run_dir} not under {run_root}"
        ) from exc

    # Lazy import to avoid pulling pandas at adapter import time only when needed.
    from brain_researcher.core.behavior_taps_parser import (
        TapsParseError,
        parse_taps_directory,
    )

    try:
        data = parse_taps_directory(str(run_dir))
    except TapsParseError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "planned_dir": bundle.planned_dir,
            "run_dir": str(run_dir),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "planned_dir": bundle.planned_dir,
            "run_dir": str(run_dir),
        }

    trials = data.get("trials") or data.get("n_trials") or data.get("rows") or []
    try:
        n_trials = len(trials) if hasattr(trials, "__len__") else int(trials)
    except (TypeError, ValueError):
        n_trials = 0
    return {
        "status": "success",
        "trials": int(n_trials),
        "policy_id": None,
        "planned_dir": bundle.planned_dir,
        "run_dir": str(run_dir),
        "ingest": data,
    }


__all__ = [
    "PsyflowNotInstalledError",
    "write_psyflow_scaffold",
    "run_psyflow_validate",
    "ingest_psyflow_run",
]
