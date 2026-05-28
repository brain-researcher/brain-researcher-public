"""Run code/scientific review directly on an external artifact folder.

Usage:
  python scripts/review/direct_review_external_run.py \
      --source-dir /path/to/external/run \
      --run-id tribe-encoding-001 \
      --task "working memory" \
      --contrast-name "2-back > rest"

This script stages a temporary run-like directory with synthetic run.json /
provenance.json when needed, then calls the internal review APIs directly via
run_dir=... without importing into the MCP run store.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from brain_researcher.services.review.distill_review import (
    distill_review_records,
    distill_scientific_review_records,
)
from brain_researcher.services.review.external_run_import import (
    ExternalRunImportSpec,
    available_external_artifact_adapters,
    stage_external_run,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        required=True,
        help="External artifact directory or single summary JSON file",
    )
    parser.add_argument("--run-id", required=True, help="Synthetic run id for review")
    parser.add_argument("--task", default=None, help="Optional task label injected into run.json")
    parser.add_argument(
        "--contrast-name",
        default=None,
        help="Optional contrast label injected into run.json",
    )
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--study-id", default=None)
    parser.add_argument("--modality", default=None)
    parser.add_argument("--design-type", default=None)
    parser.add_argument("--statistical-method", default=None)
    parser.add_argument(
        "--tool-id",
        default="external_import",
        help="Synthetic tool id to place in run.json when no native run.json exists",
    )
    parser.add_argument(
        "--adapter",
        default="auto",
        help=(
            "Adapter selection: auto, none, or one of "
            + ", ".join(adapter["name"] for adapter in available_external_artifact_adapters())
        ),
    )
    parser.add_argument(
        "--link-mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="How to stage external artifacts into the temporary review directory",
    )
    parser.add_argument(
        "--skip-scientific-review",
        action="store_true",
        help="Only compute code review",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional output path for the combined review payload",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    source_dir = Path(args.source_dir).expanduser().resolve()
    spec = ExternalRunImportSpec(
        run_id=args.run_id,
        tool_id=args.tool_id,
        task=args.task,
        contrast_name=args.contrast_name,
        dataset_id=args.dataset_id,
        study_id=args.study_id,
        modality=args.modality,
        design_type=args.design_type,
        statistical_method=args.statistical_method,
    )

    with tempfile.TemporaryDirectory(prefix=f"br-review-{args.run_id}-") as tmp:
        staged_run_dir = Path(tmp) / args.run_id
        import_result = stage_external_run(
            source_dir,
            staged_run_dir,
            spec=spec,
            link_mode=args.link_mode,
            adapter_preference=args.adapter,
            overwrite=True,
        )
        code_review = distill_review_records(
            args.run_id,
            run_dir=staged_run_dir,
            force_recompute=True,
        )
        scientific_review: Any | None = None
        if not args.skip_scientific_review:
            scientific_review = distill_scientific_review_records(
                args.run_id,
                run_dir=staged_run_dir,
                use_judgment_critic=True,
                force_recompute=True,
            )

        payload = {
            "ok": True,
            "source_dir": str(source_dir),
            "staged_run_dir": str(staged_run_dir),
            "import": import_result.to_dict(),
            "code_review": {
                "verdict": (
                    code_review.verdict.model_dump() if code_review.verdict is not None else None
                ),
                "warnings": code_review.warnings,
                "kg_context": code_review.bundle.kg_context if code_review.bundle else {},
                "stats_metrics": (
                    code_review.bundle.stats_metrics if code_review.bundle else {}
                ),
            },
            "scientific_review": (
                scientific_review.model_dump() if scientific_review is not None else None
            ),
        }

        if args.json_out:
            output_path = Path(args.json_out).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
