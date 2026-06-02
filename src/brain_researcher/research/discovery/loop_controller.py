"""Canonical discovery loop-controller wrapper around the live TRIBE controller."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from brain_researcher.research._bundle_emitter import emit_native_bundle
from brain_researcher.research._legacy_project_loader import (
    legacy_project_script_path,
    load_legacy_project_module,
    run_legacy_main,
)

LEGACY_SCRIPT = Path("scripts/controller/run_closed_loop.py")
NATIVE_BUNDLE_HELPER_NAMES = (
    "emit_native_bundle",
    "write_native_bundle",
    "persist_native_bundle",
)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _config_dict(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        return dict(config)
    if is_dataclass(config) and not isinstance(config, type):
        try:
            payload = asdict(config)
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}
    if hasattr(config, "__dict__"):
        return {
            key: value for key, value in vars(config).items() if not key.startswith("_")
        }
    return {}


def _path_or_none(value: Any) -> Path | None:
    text = _text(value)
    if text is None:
        return None
    return Path(text).expanduser().resolve()


def _bundle_run_dir(payload: dict[str, Any], config: Any) -> Path | None:
    for key in ("run_dir", "artifact_root", "output_dir", "bundle_root"):
        if path := _path_or_none(payload.get(key)):
            return path

    config_payload = _config_dict(config)
    for key in ("run_dir", "artifact_root", "output_dir", "bundle_root"):
        if path := _path_or_none(config_payload.get(key)):
            return path

    loop_root = _path_or_none(
        payload.get("loop_root") or config_payload.get("loop_root")
    )
    if loop_root is not None and loop_root.is_absolute():
        return loop_root
    return None


def _bundle_relrefs(
    run_dir: Path,
    refs: Sequence[Any] | None,
) -> list[str]:
    relpaths: list[str] = []
    for ref in refs or ():
        text = _text(ref)
        if text is None:
            continue
        candidate = Path(text).expanduser()
        if candidate.is_absolute():
            try:
                rel = candidate.resolve().relative_to(run_dir.resolve()).as_posix()
            except Exception:
                rel = candidate.name
        else:
            rel = candidate.as_posix()
        if rel and rel not in relpaths:
            relpaths.append(rel)
    return relpaths


def _emit_native_bundle(
    module: Any,
    payload: dict[str, Any],
    *,
    config: Any,
) -> list[Path]:
    for helper_name in NATIVE_BUNDLE_HELPER_NAMES:
        helper = getattr(module, helper_name, None)
        if callable(helper):
            result = helper(payload, config=config)
            if isinstance(result, list):
                return [Path(item) for item in result if item]
            return []

    run_dir = _bundle_run_dir(payload, config)
    if run_dir is None:
        return []

    config_payload = _config_dict(config)
    source_manifests = _bundle_relrefs(
        run_dir,
        payload.get("source_manifests") or config_payload.get("source_manifests") or (),
    )
    inputs_manifest_ref = _text(
        payload.get("inputs_manifest_ref")
        or payload.get("inputs_manifest_json")
        or config_payload.get("inputs_manifest_ref")
        or config_payload.get("inputs_manifest_json")
    )
    qc_summary_ref = _text(
        payload.get("qc_summary_ref")
        or payload.get("qc_summary_json")
        or config_payload.get("qc_summary_ref")
        or config_payload.get("qc_summary_json")
    )
    if inputs_manifest_ref and inputs_manifest_ref not in source_manifests:
        source_manifests.append(inputs_manifest_ref)

    emitted = emit_native_bundle(
        run_dir,
        job_id=(
            _text(payload.get("job_id"))
            or _text(payload.get("run_id"))
            or _text(config_payload.get("run_id"))
            or run_dir.name
        ),
        run_id=(
            _text(payload.get("run_id"))
            or _text(config_payload.get("run_id"))
            or run_dir.name
        ),
        state=_text(payload.get("state") or payload.get("status")) or "succeeded",
        run_card=_dict(payload.get("run_card")) or None,
        provenance=_dict(payload.get("provenance")) or None,
        tool_calls=list(payload.get("steps") or []),
        artifacts=list(payload.get("artifacts") or []),
        violations=list(payload.get("violations") or []),
        policy={
            "source": "discovery_loop_controller",
            "loop_root": str(run_dir),
        },
        created_at_ms=payload.get("created_at_ms"),
        started_at_ms=payload.get("started_at_ms"),
        finished_at_ms=payload.get("finished_at_ms"),
        round_id=(
            _text(payload.get("round_id"))
            or _text(payload.get("current_round_id"))
            or _text(config_payload.get("round_id"))
        ),
        inputs_manifest_ref=inputs_manifest_ref,
        failure_summary=_text(
            payload.get("failure_summary")
            or payload.get("error")
            or payload.get("summary")
        ),
        qc_summary_ref=qc_summary_ref,
        source_manifests=source_manifests,
        evidence_index=list(payload.get("evidence_index") or []),
    )
    return list(emitted.values())


def loop_controller_script_path(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    return legacy_project_script_path(
        "discovery",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def legacy_script_path(*, project_root: Path | str | None = None) -> Path:
    return loop_controller_script_path(project_root=project_root)


def load_implementation(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
):
    return load_legacy_project_module(
        "discovery",
        "brain_researcher_discovery_loop_controller_legacy",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def load_legacy_module(*, project_root: Path | str | None = None):
    return load_implementation(project_root=project_root)


def run_closed_loop(
    config: Any,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> dict[str, Any]:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    payload = module.run_closed_loop(config)
    if isinstance(payload, dict):
        _emit_native_bundle(module, payload, config=config)
    return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> int:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    result = run_legacy_main(
        module,
        script_path=loop_controller_script_path(
            project_root=project_root,
            implementation_path=implementation_path,
        ),
        argv=argv,
    )
    return 0 if result is None else int(result)


__all__ = [
    "legacy_script_path",
    "load_implementation",
    "load_legacy_module",
    "loop_controller_script_path",
    "main",
    "run_closed_loop",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
