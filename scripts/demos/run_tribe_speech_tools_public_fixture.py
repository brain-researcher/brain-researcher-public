#!/usr/bin/env python3
"""Run the public TRIBE v2 evaluator on deterministic synthetic matrices.

This is a copy-pasteable engineering fixture for the public evaluator and
terminal-artifact contract.  It does not use audio, checkpoints, or protected
TRIBE features, and its resulting evaluation is explicitly marked
``synthetic_fixture_only``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
FIXTURE_SEED = 20260816
REFERENCE_ROWS = 48
EVALUATION_ROWS = 48
FEATURE_DIMENSION = 1152


def _public_contracts() -> tuple[tuple[str, ...], str, str, dict[str, Any]]:
    """Import source-tree contracts without requiring a package installation."""

    source_root = str(SRC_ROOT)
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

    from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.contracts import (
        LOCKED_LAYERS,
        default_inference_config,
    )
    from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.evaluator import (
        PROGRAM_ID,
    )
    from brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution_contract import (
        MANIFEST_SCHEMA_VERSION,
    )

    return (
        tuple(LOCKED_LAYERS),
        PROGRAM_ID,
        MANIFEST_SCHEMA_VERSION,
        default_inference_config(),
    )


def _runtime() -> dict[str, None | str]:
    return {
        "mode": "precomputed_feature_matrices",
        "data_root": None,
        "model_root": None,
        "checkpoint": None,
        "command": None,
        "seed": None,
    }


def _reference_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(REFERENCE_ROWS):
        condition = "speech" if index < 8 else "tools" if index < 16 else "other"
        rows.append({"row_key": f"reference-{index:02d}", "condition": condition})
    return rows


def _evaluation_rows() -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for collection_index in range(4):
        for condition in ("speech", "tools"):
            for position in range(6):
                rows.append(
                    {
                        "row_key": f"candidate-{collection_index}-{condition}-{position}",
                        "collection_key": f"collection-{collection_index}",
                        "condition": condition,
                        "whisperx_segment_count": position + 1,
                    }
                )
    return rows


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _prepare_output_dir(path: Path) -> Path:
    output_dir = path.expanduser()
    if output_dir.is_symlink():
        raise ValueError("output directory must not be a symbolic link")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError("output path must be a directory")
        if any(output_dir.iterdir()):
            raise ValueError("output directory must be empty")
    else:
        output_dir.mkdir(parents=True)
    return output_dir


def _write_inputs(
    output_dir: Path,
    *,
    locked_layers: tuple[str, ...],
    program_id: str,
    manifest_schema_version: str,
    inference: dict[str, Any],
) -> dict[str, Path]:
    inputs_dir = output_dir / "inputs"
    inputs_dir.mkdir()
    reference_rows = _reference_rows()
    evaluation_rows = _evaluation_rows()
    generator = np.random.default_rng(FIXTURE_SEED)
    reference_paths: dict[str, str] = {}
    evaluation_paths: dict[str, str] = {}

    for layer_index, layer_id in enumerate(locked_layers):
        reference_matrix = generator.normal(
            loc=0.0, scale=1.0, size=(REFERENCE_ROWS, FEATURE_DIMENSION)
        )
        reference_matrix[:8, :6] += 0.45
        reference_matrix[8:16, :6] -= 0.45
        evaluation_matrix = generator.normal(
            loc=0.0, scale=1.0, size=(EVALUATION_ROWS, FEATURE_DIMENSION)
        )
        effect = 0.25 if layer_index < 3 else 0.10
        for row_index, row in enumerate(evaluation_rows):
            evaluation_matrix[row_index, :6] += (
                effect if row["condition"] == "speech" else -effect
            )

        reference_name = f"reference-layer-{layer_index:02d}.npy"
        evaluation_name = f"evaluation-layer-{layer_index:02d}.npy"
        np.save(inputs_dir / reference_name, reference_matrix, allow_pickle=False)
        np.save(inputs_dir / evaluation_name, evaluation_matrix, allow_pickle=False)
        reference_paths[layer_id] = reference_name
        evaluation_paths[layer_id] = evaluation_name

    reference_map = inputs_dir / "reference-matrices.json"
    evaluation_map = inputs_dir / "evaluation-matrices.json"
    _write_json(reference_map, reference_paths)
    _write_json(evaluation_map, evaluation_paths)

    for family in inference["family_tests"].values():
        family["draws"] = 7
    manifest = {
        "schema_version": manifest_schema_version,
        "program_id": program_id,
        "execution_kind": "synthetic_fixture",
        "runtime": _runtime(),
        "reference_rows": reference_rows,
        "evaluation_rows": evaluation_rows,
        "inference": inference,
        "compute_inference": True,
    }
    manifest_path = inputs_dir / "synthetic-v2-manifest.json"
    _write_json(manifest_path, manifest)
    return {
        "manifest": manifest_path,
        "reference_map": reference_map,
        "evaluation_map": evaluation_map,
    }


def _execution_command(
    action: str, inputs: dict[str, Path], artifacts: dict[str, Path]
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "brain_researcher.research.discovery.programs.tribe_speech_tools_new_source_asr_covariate_validation_v2.execution",
        action,
        "--manifest",
        str(inputs["manifest"]),
        "--reference-matrix-map",
        str(inputs["reference_map"]),
        "--evaluation-matrix-map",
        str(inputs["evaluation_map"]),
        "--evaluation-artifact",
        str(artifacts["evaluation"]),
        "--state-artifact",
        str(artifacts["state"]),
        "--terminal-artifact",
        str(artifacts["terminal"]),
        "--attempt-artifact",
        str(artifacts["attempt"]),
    ]


def _run(command: list[str]) -> dict[str, Any]:
    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SRC_ROOT) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "public TRIBE evaluator command failed:\n"
            + " ".join(command)
            + "\n"
            + completed.stderr.strip()
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("public TRIBE evaluator did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("public TRIBE evaluator returned a non-object report")
    return payload


def run_fixture(output_dir: Path) -> dict[str, Any]:
    """Create deterministic inputs, then execute and verify the public CLI."""

    destination = _prepare_output_dir(output_dir)
    locked_layers, program_id, manifest_schema_version, inference = _public_contracts()
    inputs = _write_inputs(
        destination,
        locked_layers=locked_layers,
        program_id=program_id,
        manifest_schema_version=manifest_schema_version,
        inference=inference,
    )
    artifacts_dir = destination / "artifacts"
    artifacts_dir.mkdir()
    artifacts = {
        "evaluation": artifacts_dir / "evaluation.json",
        "state": artifacts_dir / "state.json",
        "terminal": artifacts_dir / "terminal.json",
        "attempt": artifacts_dir / "attempt.json",
    }
    evaluated = _run(_execution_command("evaluate", inputs, artifacts))
    verified = _run(_execution_command("verify", inputs, artifacts))
    evaluation = json.loads(artifacts["evaluation"].read_text(encoding="utf-8"))
    if evaluation.get("scientific_evidence") != "synthetic_fixture_only":
        raise RuntimeError("fixture evaluation must remain synthetic_fixture_only")
    if verified.get("status") != "verified":
        raise RuntimeError("fixture terminal evidence was not verified")
    return {
        "fixture": "tribe_speech_tools_public_v2",
        "execution_kind": "synthetic_fixture",
        "scientific_evidence": "synthetic_fixture_only",
        "matrix_file_count": len(locked_layers) * 2,
        "output_dir": str(destination),
        "evaluate": {
            "evaluation_status": evaluated["evaluation"]["evaluation_status"],
            "execution_kind": evaluated["execution_kind"],
            "outcome": evaluated["evaluation"]["outcome"],
        },
        "verify": verified,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New or empty directory for synthetic matrices and artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = run_fixture(args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
