"""Python execution-pack assembly for public MCP tool recipes.

Carved out of ``mcp/execution_recipes.py``: the helpers that assemble the
portable Python "execution pack" — manifests (base / local / embedded), the
generated runner script, the pack contract, input bindings / confounds policy /
handoff, the run-pack environment + prerequisites, and the recipe run-pack
payload. The shared lower-level helpers and ``_PACK_*`` constants these use stay
in ``execution_recipes`` and are imported back lazily, so this module imports
nothing from ``execution_recipes`` at load (cycle-free). ``execution_recipes``
re-exports these so existing importers (and build_execution_recipe) keep
resolving.
"""

from __future__ import annotations

import shlex
from textwrap import dedent
from typing import Any

from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_recipe_context,
)
from brain_researcher.services.tools.spec import ToolSpec


def _pack_input_bindings(params: dict[str, Any]) -> list[dict[str, Any]]:
    from brain_researcher.services.tools.execution_recipes import (
        _PACK_PRECHECK_INPUT_HINTS,
    )

    bindings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for param_name, kind in _PACK_PRECHECK_INPUT_HINTS.items():
        if param_name not in params:
            continue
        key = (param_name, kind)
        if key in seen:
            continue
        seen.add(key)
        bindings.append({"param": param_name, "kind": kind})
    return bindings


def _pack_confounds_policy(tool_id: str) -> str | None:
    if str(tool_id or "").strip() == "clean_confounds":
        return "sanitize_non_finite_to_zero"
    return None


def _base_python_pack_manifest(
    *,
    tool_id: str,
    metadata: dict[str, Any],
    required_env_vars: list[str],
    step: dict[str, Any],
    params: dict[str, Any],
    handoff: dict[str, Any],
) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _PACK_CONTRACT_SCHEMA_VERSION,
        _compact_optional_fields,
        _normalize_dict,
        _slugify,
    )

    return {
        "schema_version": _PACK_CONTRACT_SCHEMA_VERSION,
        "pack_id": f"{_slugify(tool_id)}_python_pack",
        "tool_id": tool_id,
        "target_runtime": "python",
        "generator": {
            "kind": "execution_recipe",
            "config_path": metadata.get("config_path"),
        },
        "required_env_vars": required_env_vars,
        "resource_profile": _normalize_dict(metadata.get("resource_profile")),
        "resume_policy": "skip_if_log_success_and_outputs_exist",
        "preflight": {
            "blocking_levels": ["L1", "L2"],
            "advisory_levels": ["L3"],
            "inputs": _pack_input_bindings(params),
        },
        "provenance": _compact_optional_fields(
            {
                "execution_story_kind": metadata.get("execution_story_kind"),
                "hosted_via_br_mcp_service": bool(
                    metadata.get("hosted_via_br_mcp_service")
                ),
                "source_repo": metadata.get("source_repo"),
                "source_paper": metadata.get("source_paper"),
                "runbook": metadata.get("runbook"),
            },
            "source_repo",
            "source_paper",
        ),
        "handoff": handoff,
        "steps": [step],
    }


def _pack_handoff(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    workflow_entry: dict[str, Any] | None,
    target_runtime: str = "python",
) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _normalize_dict,
    )

    existing = metadata.get("handoff") or metadata.get("plan_handoff")
    if isinstance(existing, dict) and existing:
        return _normalize_dict(existing)
    workflow_id = str((workflow_entry or {}).get("id") or "").strip() or None
    return build_handoff_from_recipe_context(
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        workflow_id=workflow_id,
        target_runtime=target_runtime,
    )


def _local_tool_pack_manifest(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    required_env_vars: list[str],
) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _declared_output_bindings,
        _maybe_tool_schema_hash,
    )

    tool_manifest = {
        "tool_id": tool_id,
        "required": True,
        "schema_hash": _maybe_tool_schema_hash(
            tool_id, spec=spec, workflow_entry=workflow_entry
        ),
    }
    step = {
        "id": "run_tool",
        "label": tool_id,
        "execution_mode": "local_tool",
        "log_file": "logs/01_run_tool.json",
        "tool_manifest": tool_manifest,
        "declared_outputs": _declared_output_bindings(params, metadata),
        "provenance": {
            "kind": "local_br_tool",
            "execution_origin": "local_pack",
            "declarative_only": True,
        },
    }
    confounds_policy = _pack_confounds_policy(tool_id)
    if confounds_policy:
        step["domain_policy"] = {"confounds_non_finite": confounds_policy}
    return _base_python_pack_manifest(
        tool_id=tool_id,
        metadata=metadata,
        required_env_vars=required_env_vars,
        step=step,
        params=params,
        handoff=_pack_handoff(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            workflow_entry=workflow_entry,
        ),
    )


def _embedded_python_pack_manifest(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    required_env_vars: list[str],
    workflow_entry: dict[str, Any] | None,
    script_name: str,
    script_text: str,
) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _declared_output_bindings,
        _stable_json_hash,
    )

    declared_outputs = _declared_output_bindings(params, metadata)
    step = {
        "id": "run_embedded_python",
        "label": tool_id,
        "execution_mode": "embedded_python",
        "log_file": "logs/01_run_embedded_python.json",
        "script": script_name,
        "contract_hash": _stable_json_hash(
            {
                "tool_id": tool_id,
                "script_name": script_name,
                "script": script_text,
                "declared_outputs": declared_outputs,
            }
        ),
        "declared_outputs": declared_outputs,
        "provenance": {
            "kind": "embedded_python",
            "execution_origin": "local_pack",
            "declarative_only": True,
        },
    }
    return _base_python_pack_manifest(
        tool_id=tool_id,
        metadata=metadata,
        required_env_vars=required_env_vars,
        step=step,
        params=params,
        handoff=_pack_handoff(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            workflow_entry=workflow_entry,
        ),
    )


def _generated_python_pack_runner() -> str:
    return dedent(
        """
        from __future__ import annotations

        import argparse
        import hashlib
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path
        from typing import Any


        PACK_MANIFEST_FILE = "pack_manifest.json"
        PACK_RUNTIME_MANIFEST_SCHEMA_VERSION = "br-pack-runtime-manifest-v1"


        def _read_json(path: Path) -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8"))


        def _write_json(path: Path, payload: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


        def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base)
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = _merge_dicts(merged[key], value)
                else:
                    merged[key] = value
            return merged


        def _stable_json_hash(payload: Any) -> str:
            return hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()


        def _resolve_path(base_dir: Path, value: str | None) -> Path | None:
            if not value:
                return None
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = (base_dir / candidate).resolve()
            return candidate.resolve()


        def _resolve_binding_paths(base_dir: Path, params: dict[str, Any], binding: dict[str, Any]) -> list[Path]:
            kind = str(binding.get("kind") or "").strip()
            param_name = str(binding.get("param") or "").strip()
            value = params.get(param_name)
            if kind == "param_path":
                if isinstance(value, list):
                    return [
                        resolved
                        for item in value
                        if isinstance(item, str)
                        for resolved in [_resolve_path(base_dir, item)]
                        if resolved is not None
                    ]
                if isinstance(value, str):
                    resolved = _resolve_path(base_dir, value)
                    return [resolved] if resolved is not None else []
                return []
            if kind == "output_dir_artifact" and isinstance(value, str):
                base_path = _resolve_path(base_dir, value)
                if base_path is None:
                    return []
                return [(base_path / str(binding.get("relative_path") or "")).resolve()]
            return []


        def _closest_existing_parent(path: Path) -> Path:
            current = path if path.is_dir() else path.parent
            while not current.exists() and current != current.parent:
                current = current.parent
            return current


        def _tool_schema_hash(tool: Any) -> str:
            schema_class = tool.get_args_schema()
            if hasattr(schema_class, "model_json_schema"):
                json_schema = schema_class.model_json_schema()
            else:
                json_schema = {}
            payload = {
                "tool_id": tool.get_tool_name(),
                "json_schema": json_schema,
                "required": list(json_schema.get("required") or []),
            }
            return _stable_json_hash(payload)


        def _issue(level: str, code: str, message: str, *, blocking: bool) -> dict[str, Any]:
            return {
                "level": level,
                "code": code,
                "message": message,
                "blocking": blocking,
            }


        def _run_preflight(pack_dir: Path, manifest: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
            issues: list[dict[str, Any]] = []
            blocking_levels = set(manifest.get("preflight", {}).get("blocking_levels") or [])
            advisory_levels = set(manifest.get("preflight", {}).get("advisory_levels") or [])
            del advisory_levels
            input_cache: dict[str, Any] = {}

            for env_var in manifest.get("required_env_vars") or []:
                if not os.getenv(str(env_var)):
                    issues.append(
                        _issue(
                            "L1",
                            "missing_env_var",
                            f"Required environment variable '{env_var}' is not set.",
                            blocking="L1" in blocking_levels,
                        )
                    )

            registry = None
            for step in manifest.get("steps") or []:
                if step.get("execution_mode") != "local_tool":
                    continue
                if registry is None:
                    from brain_researcher.services.tools.tool_registry import ToolRegistry

                    registry = ToolRegistry.from_env(light_mode=True)
                tool_manifest = step.get("tool_manifest") if isinstance(step, dict) else {}
                tool_id = str((tool_manifest or {}).get("tool_id") or "").strip()
                tool = registry.get_tool(tool_id) if tool_id else None
                if tool is None:
                    issues.append(
                        _issue(
                            "L1",
                            "tool_unavailable",
                            f"Declared local tool '{tool_id}' is not available in the current runtime.",
                            blocking="L1" in blocking_levels,
                        )
                    )
                    continue
                expected_hash = str((tool_manifest or {}).get("schema_hash") or "").strip()
                if expected_hash:
                    observed_hash = _tool_schema_hash(tool)
                    if observed_hash != expected_hash:
                        issues.append(
                            _issue(
                                "L1",
                                "tool_schema_mismatch",
                                (
                                    f"Tool '{tool_id}' schema hash mismatch: expected {expected_hash}, "
                                    f"observed {observed_hash}."
                                ),
                                blocking="L1" in blocking_levels,
                            )
                        )

            nifti_kinds = {"nifti_image", "nifti_list"}
            table_kinds = {"table"}
            array_kinds = {"array_or_table"}
            img_path = None
            atlas_path = None

            for binding in manifest.get("preflight", {}).get("inputs") or []:
                kind = str(binding.get("kind") or "").strip()
                param_name = str(binding.get("param") or "").strip()
                resolved_paths = _resolve_binding_paths(pack_dir, params, binding)
                if not resolved_paths:
                    continue
                for path in resolved_paths:
                    if not path.exists():
                        issues.append(
                            _issue(
                                "L1",
                                "missing_input_path",
                                f"Input path for '{param_name}' does not exist: {path}",
                                blocking="L1" in blocking_levels,
                            )
                        )
                        continue
                    if kind in nifti_kinds:
                        try:
                            import nibabel as nib

                            image = nib.load(str(path))
                            input_cache[param_name] = image
                            if param_name in {"img", "fmri_path", "func_file", "volume_img", "stat_map", "contrast_map"}:
                                img_path = path
                            if param_name in {"atlas", "atlas_path"}:
                                atlas_path = path
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L1",
                                    "invalid_nifti",
                                    f"Failed to read NIfTI input '{param_name}' at {path}: {exc}",
                                    blocking="L1" in blocking_levels,
                                )
                            )
                    elif kind in table_kinds:
                        try:
                            import pandas as pd

                            sep = "\\t" if path.suffix.lower() == ".tsv" else ","
                            table = pd.read_csv(path, sep=sep)
                            input_cache[param_name] = table
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L2",
                                    "invalid_table",
                                    f"Failed to parse table input '{param_name}' at {path}: {exc}",
                                    blocking="L2" in blocking_levels,
                                )
                            )
                    elif kind in array_kinds:
                        try:
                            import numpy as np

                            if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
                                delimiter = "," if path.suffix.lower() == ".csv" else "\\t"
                                np.loadtxt(path, delimiter=delimiter)
                            else:
                                np.load(path)
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L1",
                                    "invalid_array",
                                    f"Failed to load array-like input '{param_name}' at {path}: {exc}",
                                    blocking="L1" in blocking_levels,
                                )
                            )

            output_candidates = []
            output_file = params.get("output_file")
            if isinstance(output_file, str) and output_file.strip():
                resolved = _resolve_path(pack_dir, output_file)
                if resolved is not None:
                    output_candidates.append(resolved)
            output_dir = params.get("output_dir")
            if isinstance(output_dir, str) and output_dir.strip():
                resolved_dir = _resolve_path(pack_dir, output_dir)
                if resolved_dir is not None:
                    output_candidates.append(resolved_dir)
            for candidate in output_candidates:
                parent = _closest_existing_parent(candidate)
                if not os.access(parent, os.W_OK):
                    issues.append(
                        _issue(
                            "L1",
                            "output_not_writable",
                            f"Output location is not writable: {candidate}",
                            blocking="L1" in blocking_levels,
                        )
                    )

            has_filter = any(
                params.get(name) is not None for name in ("high_pass", "low_pass")
            )
            has_tr = any(params.get(name) is not None for name in ("t_r", "tr", "repetition_time"))
            image_for_tr = input_cache.get("img")
            if has_filter and not has_tr and image_for_tr is not None:
                zooms = image_for_tr.header.get_zooms()
                if len(zooms) < 4:
                    issues.append(
                        _issue(
                            "L2",
                            "missing_tr",
                            "Filtering is requested but TR cannot be inferred from the input image header.",
                            blocking="L2" in blocking_levels,
                        )
                    )

            if img_path is not None and atlas_path is not None:
                img = input_cache.get("img")
                atlas = input_cache.get("atlas") or input_cache.get("atlas_path")
                if img is not None and atlas is not None:
                    if tuple(img.shape[:3]) != tuple(atlas.shape[:3]):
                        issues.append(
                            _issue(
                                "L2",
                                "atlas_bold_shape_mismatch",
                                (
                                    "Atlas and image have incompatible spatial shapes: "
                                    f"{tuple(img.shape[:3])} vs {tuple(atlas.shape[:3])}."
                                ),
                                blocking="L2" in blocking_levels,
                            )
                        )

            confounds_table = input_cache.get("confounds") or input_cache.get("confounds_file")
            confounds_policy = None
            for step in manifest.get("steps") or []:
                domain_policy = step.get("domain_policy") if isinstance(step, dict) else {}
                if isinstance(domain_policy, dict) and domain_policy.get("confounds_non_finite"):
                    confounds_policy = str(domain_policy.get("confounds_non_finite"))
            if confounds_table is not None:
                numeric = confounds_table.select_dtypes(include=["number"])
                if not numeric.empty:
                    import numpy as np

                    invalid = ~np.isfinite(numeric.to_numpy(dtype=float, copy=False))
                    if invalid.any():
                        columns = numeric.columns[invalid.any(axis=0)].tolist()
                        if confounds_policy == "sanitize_non_finite_to_zero":
                            issues.append(
                                _issue(
                                    "L2",
                                    "confounds_non_finite_handled",
                                    (
                                        "Confounds contain non-finite values, but the pack declares "
                                        f"policy '{confounds_policy}' for columns {columns}."
                                    ),
                                    blocking=False,
                                )
                            )
                        else:
                            issues.append(
                                _issue(
                                    "L2",
                                    "confounds_non_finite",
                                    (
                                        "Confounds contain non-finite values and no sanitizer policy "
                                        f"is declared. Columns: {columns}"
                                    ),
                                    blocking="L2" in blocking_levels,
                                )
                            )

            if img_path is not None:
                try:
                    size_gb = img_path.stat().st_size / (1024 ** 3)
                    profile = manifest.get("resource_profile") if isinstance(manifest.get("resource_profile"), dict) else {}
                    est = profile.get("est_runtime")
                    if size_gb >= 0.5 or est:
                        issues.append(
                            _issue(
                                "L3",
                                "resource_estimate",
                                (
                                    f"Input image is approximately {size_gb:.2f} GiB. "
                                    f"Declared resource profile: {profile or {'est_runtime': est}}"
                                ),
                                blocking=False,
                            )
                        )
                except FileNotFoundError:
                    pass

            blocking_issues = [issue for issue in issues if issue.get("blocking")]
            return {
                "schema_version": "br-pack-preflight-v1",
                "passed": not blocking_issues,
                "issues": issues,
                "blocking_issue_count": len(blocking_issues),
            }


        def _tool_result_to_dict(result: Any) -> dict[str, Any]:
            if hasattr(result, "model_dump"):
                return result.model_dump(mode="python")
            if isinstance(result, dict):
                return result
            return {"status": "success", "data": result}


        def _extract_outputs(payload: dict[str, Any]) -> dict[str, Any]:
            if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("outputs"), dict):
                return dict(payload["data"]["outputs"])
            if isinstance(payload.get("outputs"), dict):
                return dict(payload["outputs"])
            return {}


        def _step_log_path(pack_dir: Path, step: dict[str, Any]) -> Path:
            return (pack_dir / str(step.get("log_file") or f"logs/{step.get('id')}.json")).resolve()


        def _declared_output_paths(pack_dir: Path, params: dict[str, Any], step: dict[str, Any]) -> list[Path]:
            paths: list[Path] = []
            for binding in step.get("declared_outputs") or []:
                paths.extend(_resolve_binding_paths(pack_dir, params, binding))
            deduped: list[Path] = []
            seen: set[Path] = set()
            for path in paths:
                if path in seen:
                    continue
                seen.add(path)
                deduped.append(path)
            return deduped


        def _can_resume(pack_dir: Path, params: dict[str, Any], step: dict[str, Any]) -> bool:
            log_path = _step_log_path(pack_dir, step)
            if not log_path.exists():
                return False
            try:
                payload = _read_json(log_path)
            except Exception:
                return False
            if str(payload.get("status") or "").strip() != "success":
                return False
            outputs = _declared_output_paths(pack_dir, params, step)
            if not outputs:
                return False
            return all(path.exists() for path in outputs)


        def _run_local_tool_step(step: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
            from brain_researcher.services.tools.runner import execute_tool

            tool_id = str(step.get("tool_manifest", {}).get("tool_id") or "").strip()
            return _tool_result_to_dict(execute_tool(tool_id, params))


        def _run_embedded_python_step(
            pack_dir: Path,
            step: dict[str, Any],
            params: dict[str, Any],
            params_file: Path,
        ) -> dict[str, Any]:
            script_name = str(step.get("script") or "").strip()
            if not script_name:
                raise RuntimeError(f"Embedded step {step.get('id')} is missing a script.")
            params_json_path = pack_dir / "params.json"
            original_params_text = (
                params_json_path.read_text(encoding="utf-8")
                if params_json_path.exists()
                else None
            )
            params_json_path.write_text(
                json.dumps(params, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            try:
                proc = subprocess.run(
                    [sys.executable, script_name],
                    cwd=str(pack_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                    env=os.environ.copy(),
                )
            finally:
                if original_params_text is not None:
                    params_json_path.write_text(
                        original_params_text, encoding="utf-8"
                    )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "error": f"Embedded script exited with code {proc.returncode}",
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            if not stdout:
                return {
                    "status": "error",
                    "error": "Embedded script did not emit JSON output.",
                    "data": {
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError as exc:
                return {
                    "status": "error",
                    "error": f"Embedded script emitted non-JSON stdout: {exc}",
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            return {
                "status": "success",
                "data": payload,
                "stdout": stdout,
                "stderr": stderr,
            }


        def _run_step(pack_dir: Path, step: dict[str, Any], params: dict[str, Any], params_file: Path) -> dict[str, Any]:
            mode = str(step.get("execution_mode") or "").strip()
            if mode == "local_tool":
                return _run_local_tool_step(step, params)
            if mode == "embedded_python":
                return _run_embedded_python_step(pack_dir, step, params, params_file)
            raise RuntimeError(f"Unsupported execution_mode: {mode}")


        def _runtime_manifest(
            pack_dir: Path,
            manifest: dict[str, Any],
            params_file: Path,
            effective_params_path: Path,
            preflight_report: dict[str, Any],
            step_records: list[dict[str, Any]],
        ) -> dict[str, Any]:
            return {
                "schema_version": PACK_RUNTIME_MANIFEST_SCHEMA_VERSION,
                "pack_id": manifest.get("pack_id"),
                "tool_id": manifest.get("tool_id"),
                "target_runtime": manifest.get("target_runtime"),
                "workspace_root": str(pack_dir),
                "params_file": str(params_file),
                "effective_params": str(effective_params_path),
                "preflight": preflight_report,
                "steps": step_records,
                "step_logs": {
                    record["id"]: record["log_file"]
                    for record in step_records
                },
            }


        def parse_args() -> argparse.Namespace:
            parser = argparse.ArgumentParser(description="Run a Brain Researcher local execution pack.")
            parser.add_argument("--params", default="params.json", help="Optional override params file.")
            parser.add_argument("--dry-run", action="store_true", help="Write effective params and exit.")
            parser.add_argument("--preflight", action="store_true", help="Run preflight only.")
            parser.add_argument("--force", action="store_true", help="Ignore resume and rerun all steps.")
            return parser.parse_args()


        def main() -> None:
            args = parse_args()
            pack_dir = Path(__file__).resolve().parent
            manifest = _read_json(pack_dir / PACK_MANIFEST_FILE)
            base_params = _read_json(pack_dir / "params.json")
            params_path = _resolve_path(pack_dir, args.params)
            override_params = (
                _read_json(params_path)
                if params_path is not None and params_path.exists() and params_path.name != "params.json"
                else {}
            )
            effective_params = _merge_dicts(base_params, override_params)
            effective_params_path = (pack_dir / "effective_params.json").resolve()
            _write_json(effective_params_path, effective_params)

            preflight_report = _run_preflight(pack_dir, manifest, effective_params)
            if args.dry_run:
                print(json.dumps({
                    "status": "dry_run",
                    "pack_manifest": str((pack_dir / PACK_MANIFEST_FILE).resolve()),
                    "effective_params": str(effective_params_path),
                    "preflight": preflight_report,
                }, indent=2, sort_keys=True))
                return
            if args.preflight:
                print(json.dumps(preflight_report, indent=2, sort_keys=True))
                raise SystemExit(0 if preflight_report.get("passed") else 1)
            if not preflight_report.get("passed"):
                print(json.dumps(preflight_report, indent=2, sort_keys=True))
                raise SystemExit(1)

            step_records: list[dict[str, Any]] = []
            for step in manifest.get("steps") or []:
                log_path = _step_log_path(pack_dir, step)
                if not args.force and _can_resume(pack_dir, effective_params, step):
                    step_records.append(
                        {
                            "id": step.get("id"),
                            "status": "skipped",
                            "reason": "resume_from_success_log",
                            "log_file": str(log_path),
                            "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                        }
                    )
                    continue

                payload = _run_step(pack_dir, step, effective_params, effective_params_path)
                _write_json(log_path, payload)
                if str(payload.get("status") or "").strip() != "success":
                    runtime_manifest = _runtime_manifest(
                        pack_dir,
                        manifest,
                        params_path or (pack_dir / "params.json"),
                        effective_params_path,
                        preflight_report,
                        step_records
                        + [
                            {
                                "id": step.get("id"),
                                "status": "error",
                                "log_file": str(log_path),
                                "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                            }
                        ],
                    )
                    _write_json(pack_dir / "manifest.json", runtime_manifest)
                    raise RuntimeError(
                        f"Step {step.get('id')} failed: {payload.get('error') or payload}"
                    )

                step_records.append(
                    {
                        "id": step.get("id"),
                        "status": "success",
                        "log_file": str(log_path),
                        "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                        "outputs": _extract_outputs(payload),
                    }
                )

            runtime_manifest = _runtime_manifest(
                pack_dir,
                manifest,
                params_path or (pack_dir / "params.json"),
                effective_params_path,
                preflight_report,
                step_records,
            )
            _write_json(pack_dir / "manifest.json", runtime_manifest)
            print(json.dumps(runtime_manifest, indent=2, sort_keys=True))


        if __name__ == "__main__":
            main()
        """
    ).lstrip()


def _attach_python_pack_contract(
    recipe: dict[str, Any],
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    execution_mode: str,
    script_name: str | None = None,
) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _PACK_MANIFEST_FILE,
        _PACK_RUNNER_FILE,
        _json_text,
    )

    files = dict(recipe.get("files") or {})
    required_env_vars = [
        str(name).strip()
        for name in (recipe.get("required_env_vars") or [])
        if str(name).strip()
    ]
    if execution_mode == "embedded_python":
        if not script_name or script_name not in files:
            raise ValueError(
                f"Embedded python pack for '{tool_id}' requires script '{script_name}'."
            )
        manifest = _embedded_python_pack_manifest(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            required_env_vars=required_env_vars,
            workflow_entry=workflow_entry,
            script_name=script_name,
            script_text=str(files[script_name]),
        )
    else:
        manifest = _local_tool_pack_manifest(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            spec=spec,
            workflow_entry=workflow_entry,
            required_env_vars=required_env_vars,
        )
    files[_PACK_MANIFEST_FILE] = _json_text(manifest)
    files[_PACK_RUNNER_FILE] = _generated_python_pack_runner()
    recipe["files"] = files
    recipe["pack_contract"] = manifest
    recipe["run_pack_command"] = f"python {_PACK_RUNNER_FILE}"
    return recipe


def _run_pack_environment(required_env_vars: list[str]) -> dict[str, Any]:
    from brain_researcher.services.tools.execution_recipes import (
        _RUN_PACK_ENV_HINTS,
        _env_exports,
    )

    required: list[dict[str, Any]] = []
    for name in required_env_vars:
        hint = dict(_RUN_PACK_ENV_HINTS.get(name, {}))
        required.append(
            {
                "name": name,
                "required": True,
                "kind": hint.get("kind", "string"),
                "secret": bool(hint.get("secret", False)),
                "description": hint.get(
                    "description", f"Set {name} before running this recipe."
                ),
                "example": hint.get("example", "<set-me>"),
                "how_to_get": hint.get("how_to_get"),
                "export_line": f'export {name}="<set-me>"',
            }
        )
    return {
        "required": required,
        "optional": [],
        "export_lines": _env_exports(required_env_vars),
    }


def _run_pack_prerequisites(
    *,
    target_runtime: str,
    required_env_vars: list[str],
) -> dict[str, list[str]]:
    from brain_researcher.services.tools.execution_recipes import (
        _dedupe,
        normalize_recipe_target,
    )

    normalized_target = normalize_recipe_target(target_runtime)
    setup_once: list[str] = []
    checks: list[str] = []
    if normalized_target == "python":
        setup_once.append(
            "Create or activate a local conda environment or Python venv before running the recipe commands."
        )
        checks.append("python --version")
    elif normalized_target == "neurodesk":
        setup_once.append(
            "Open a Neurodesk shell with the required modules available before running the recipe commands."
        )
        checks.append("bash -lc 'type module'")
    elif normalized_target == "container":
        setup_once.append(
            "Install Docker or a compatible container runtime before running the recipe commands."
        )
        checks.append("docker --version")
    elif normalized_target == "slurm":
        setup_once.append(
            "Run from a cluster login node with scheduler access before submitting the recipe."
        )
        checks.append("command -v sbatch")

    for name in required_env_vars:
        if name == "FS_LICENSE":
            checks.append('test -f "$FS_LICENSE"')
        elif name == "BRAIN_RESEARCHER_REPO":
            checks.append('test -d "$BRAIN_RESEARCHER_REPO"')
        else:
            checks.append(f'test -n "${name}"')

    return {
        "setup_once": _dedupe(setup_once),
        "check_commands": _dedupe(checks),
    }


def _recipe_run_pack_payload(
    tool_id: str,
    target_runtime: str,
    recipe: dict[str, Any] | None,
) -> dict[str, Any] | None:
    from brain_researcher.services.tools.execution_recipes import (
        _PACK_MANIFEST_FILE,
        _PACK_RUNNER_FILE,
        _env_exports,
        _normalize_dict,
        _normalize_list,
        _slugify,
        normalize_recipe_target,
    )

    if not isinstance(recipe, dict):
        return None
    files = recipe.get("files")
    if not isinstance(files, dict) or not files:
        return None

    normalized_target = normalize_recipe_target(target_runtime)
    workspace = f"./{_slugify(tool_id)}_{normalized_target}_recipe"
    write_files = [str(name) for name in files.keys()]
    shell_files = [name for name in write_files if name.endswith(".sh")]
    required_env_vars = [
        str(name).strip()
        for name in (recipe.get("required_env_vars") or [])
        if str(name).strip()
    ]
    if any(
        "${BRAIN_RESEARCHER_REPO}" in str(cmd)
        for cmd in (recipe.get("setup_commands") or [])
    ):
        if "BRAIN_RESEARCHER_REPO" not in required_env_vars:
            required_env_vars.append("BRAIN_RESEARCHER_REPO")
    env_exports = _env_exports(required_env_vars)
    commands: list[str] = []
    if shell_files:
        commands.append(
            "chmod +x " + " ".join(shlex.quote(name) for name in shell_files)
        )
    commands.extend(
        str(item).strip()
        for item in (recipe.get("setup_commands") or [])
        if str(item).strip()
    )
    run_command = str(recipe.get("run_command") or "").strip()
    run_pack_command = str(recipe.get("run_pack_command") or "").strip()
    if run_pack_command:
        commands.append(run_pack_command)
    elif run_command:
        commands.append(run_command)

    shell_lines = [
        "# Write recipe['files'] into this directory first.",
        f"mkdir -p {shlex.quote(workspace)}",
        f"cd {shlex.quote(workspace)}",
        *(
            ["# Required environment variables:"]
            + [f"# {line}" for line in env_exports]
            if env_exports
            else []
        ),
        *commands,
    ]
    materialize_python = dedent(
        f"""
        from pathlib import Path

        recipe_resp = ...  # JSON returned by get_execution_recipe(...)
        recipe = recipe_resp["recipe"]
        workspace = Path({workspace!r})
        workspace.mkdir(parents=True, exist_ok=True)

        for name, text in recipe["files"].items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if path.suffix == ".sh":
                path.chmod(path.stat().st_mode | 0o111)

        print("Wrote recipe files to", workspace)
        if {env_exports!r}:
            print("Set required environment variables before running:")
            for line in {env_exports!r}:
                print(line)
        print("Run locally:")
        for cmd in {commands!r}:
            print(cmd)
        """
    ).strip()

    pack_contract = (
        recipe.get("pack_contract")
        if isinstance(recipe.get("pack_contract"), dict)
        else {}
    )
    preflight_contract = (
        pack_contract.get("preflight")
        if isinstance(pack_contract.get("preflight"), dict)
        else {}
    )

    return {
        "schema_version": "1",
        "runtime": {
            "target": normalized_target,
            "launcher": "shell_script" if shell_files else "command",
        },
        "workspace": workspace,
        "write_files": write_files,
        "commands": commands,
        "entrypoint": _PACK_RUNNER_FILE if _PACK_RUNNER_FILE in write_files else None,
        "pack_manifest_file": (
            _PACK_MANIFEST_FILE if _PACK_MANIFEST_FILE in write_files else None
        ),
        "handoff": (
            _normalize_dict(pack_contract.get("handoff"))
            if isinstance(pack_contract.get("handoff"), dict)
            else None
        ),
        "resume_supported": bool(pack_contract),
        "preflight": (
            {
                "blocking_levels": _normalize_list(
                    preflight_contract.get("blocking_levels")
                ),
                "advisory_levels": _normalize_list(
                    preflight_contract.get("advisory_levels")
                ),
            }
            if pack_contract
            else None
        ),
        "prerequisites": _run_pack_prerequisites(
            target_runtime=normalized_target,
            required_env_vars=required_env_vars,
        ),
        "environment": _run_pack_environment(required_env_vars),
        "required_env_vars": required_env_vars,
        "env_exports": env_exports,
        "shell_snippet": "\n".join(shell_lines),
        "materialize_python": materialize_python,
    }
