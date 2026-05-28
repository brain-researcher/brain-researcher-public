#!/usr/bin/env python3
"""Generate JSONSchema artifacts for core contract models.

This is intentionally lightweight and avoids extra build tooling so the schema
files can be kept in sync via a simple CI check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_contract_models():
    # Ensure repo root wins over any installed package.
    src_root = REPO_ROOT / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    # Avoid importing heavy tool registries during schema generation.
    os.environ.setdefault("BR_DISABLE_TOOL_RUNNER_IMPORT", "1")

    from brain_researcher.core.contracts.analysis_bundle import AnalysisBundleV1
    from brain_researcher.core.contracts.analysis_stream import AnalysisStreamEventV1
    from brain_researcher.core.contracts.artifact import ArtifactV1
    from brain_researcher.core.contracts.evaluation import EvaluationV1
    from brain_researcher.core.contracts.execution_manifest import ExecutionManifestV1
    from brain_researcher.core.contracts.ids import IdsV1
    from brain_researcher.core.contracts.job import JobRecordV1, JobSpecV1
    from brain_researcher.core.contracts.observation import ObservationSpecV1
    from brain_researcher.core.contracts.policy_ref import PolicyRefV1
    from brain_researcher.core.contracts.provenance import ProvenanceV1
    from brain_researcher.core.contracts.run_card import RunCardV1
    from brain_researcher.core.contracts.scorecard import ScorecardV1
    from brain_researcher.core.contracts.stream_event import StreamEventV1
    from brain_researcher.core.contracts.task_spec import TaskSpecV1
    from brain_researcher.core.contracts.trace_event import TraceEventV1
    from brain_researcher.core.contracts.trajectory_atif import ATIFTrajectory
    from brain_researcher.core.contracts.version_ref import VersionRefV1

    return {
        "analysis_bundle": AnalysisBundleV1,
        "analysis_stream_event": AnalysisStreamEventV1,
        "artifact": ArtifactV1,
        "evaluation": EvaluationV1,
        "execution_manifest": ExecutionManifestV1,
        "ids": IdsV1,
        "job_record": JobRecordV1,
        "job_spec": JobSpecV1,
        "observation": ObservationSpecV1,
        "policy_ref": PolicyRefV1,
        "provenance": ProvenanceV1,
        "run_card": RunCardV1,
        "scorecard": ScorecardV1,
        "stream_event": StreamEventV1,
        "task_spec": TaskSpecV1,
        "trace_event": TraceEventV1,
        "trajectory_atif": ATIFTrajectory,
        "version_ref": VersionRefV1,
    }


def _render_schema(model) -> str:
    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    else:
        schema = TypeAdapter(model).json_schema()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate_schema_files() -> dict[Path, str]:
    models = _import_contract_models()

    out_dir = REPO_ROOT / "src/brain_researcher" / "core" / "contracts" / "schemas"
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping: dict[Path, str] = {}

    for name, model in models.items():
        if name == "observation":
            path = (
                REPO_ROOT
                / "src/brain_researcher"
                / "core"
                / "contracts"
                / "observation.schema.json"
            )
        else:
            path = out_dir / f"{name}.schema.json"
        mapping[path] = _render_schema(model)

    return mapping


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if any schema file would change (CI mode).",
    )
    args = parser.parse_args(argv)

    mapping = generate_schema_files()
    changed: list[Path] = []
    for path, content in mapping.items():
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            changed.append(path)
            if not args.check:
                _write(path, content)

    if args.check and changed:
        rel = [str(p.relative_to(REPO_ROOT)) for p in changed]
        print("Schemas out of date:\n" + "\n".join(rel), file=sys.stderr)
        print(
            "Run: python scripts/contracts/generate_schemas.py",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
