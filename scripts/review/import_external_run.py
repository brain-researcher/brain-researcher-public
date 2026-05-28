"""Import an external artifact folder into the BR MCP run store.

Usage:
  python scripts/review/import_external_run.py \
      --source-dir /path/to/external/run \
      --run-id tribe-encoding-001 \
      --task "working memory" \
      --contrast-name "2-back > rest"

This writes a run-like directory under BR_MCP_RUN_ROOT/runs/<run_id> so
run_code_review / run_scientific_review can operate on it through MCP.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.config.run_artifacts import get_mcp_run_root
from brain_researcher.services.review.external_run_import import (
    ExternalRunImportSpec,
    available_external_artifact_adapters,
    stage_external_run_in_mcp_store,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        required=True,
        help="External artifact directory or single summary JSON file",
    )
    parser.add_argument("--run-id", required=True, help="Synthetic run id to register")
    parser.add_argument(
        "--run-root",
        default=None,
        help="Optional explicit BR_MCP_RUN_ROOT override",
    )
    parser.add_argument("--task", default=None)
    parser.add_argument("--contrast-name", default=None)
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--study-id", default=None)
    parser.add_argument("--modality", default=None)
    parser.add_argument("--design-type", default=None)
    parser.add_argument("--statistical-method", default=None)
    parser.add_argument("--tool-id", default="external_import")
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
        help="Whether to symlink or copy the external artifact directory",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing imported run directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing files",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
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
    run_root = Path(args.run_root).expanduser().resolve() if args.run_root else get_mcp_run_root()
    result = stage_external_run_in_mcp_store(
        args.source_dir,
        spec=spec,
        run_root=run_root,
        link_mode=args.link_mode,
        adapter_preference=args.adapter,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    payload = {
        "ok": True,
        "run_root": str(run_root),
        "import": result.to_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
