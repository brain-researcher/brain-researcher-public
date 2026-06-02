#!/usr/bin/env python3
"""Run a lightweight A/B evaluation for legacy vs principle_v0 hypothesis control."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from brain_researcher.services.agent.controller_eval import (  # noqa: E402
    DEFAULT_CASE_TIMEOUT_SECONDS,
    DEFAULT_WORKFLOW_ID,
    apply_eval_case_overrides,
    filter_eval_cases,
    load_eval_cases,
    run_controller_evaluation,
    write_controller_case_result,
    write_controller_evaluation_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run A/B evaluation for workflow_hypothesis_candidate_cards using legacy vs principle_v0."
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "configs" / "evals" / "hypothesis_controller_queries.yaml"),
        help="YAML config with hypothesis controller evaluation cases.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "artifacts" / "hypothesis_controller_eval"),
        help="Directory where JSON, Markdown, and raw workflow outputs are written.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only the specified case id(s). May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List configured case ids and exit.",
    )
    parser.add_argument(
        "--workflow-id",
        default=DEFAULT_WORKFLOW_ID,
        help="Workflow tool id to evaluate.",
    )
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=DEFAULT_CASE_TIMEOUT_SECONDS,
        help="Per-case per-mode timeout in seconds. Use 0 to disable timeout isolation.",
    )
    parser.add_argument(
        "--no-raw-runs",
        action="store_true",
        help="Do not write per-case raw workflow result JSON files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable INFO-level progress logging.",
    )
    parser.add_argument(
        "--trace-steps",
        action="store_true",
        help="Enable workflow step trace logs so hangs can be pinned to a tool.",
    )
    parser.add_argument(
        "--top-k-override",
        type=int,
        default=None,
        help="Optional eval-only override for top_k across selected cases.",
    )
    parser.add_argument(
        "--n-samples-override",
        type=int,
        default=None,
        help="Optional eval-only override for n_samples across selected cases.",
    )
    args = parser.parse_args()

    if args.verbose or args.trace_steps:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    _, cases = load_eval_cases(args.config)
    if args.list_cases:
        print("Configured controller eval cases:")
        for case in cases:
            print(f"  {case['id']}: {case['query']}")
        return 0

    selected_case_ids = [
        token.strip()
        for raw in args.case_id
        for token in str(raw).split(",")
        if token.strip()
    ]
    cases = filter_eval_cases(cases, selected_case_ids)
    cases = apply_eval_case_overrides(
        cases,
        top_k=args.top_k_override,
        n_samples=args.n_samples_override,
    )
    output_dir = Path(args.output_dir)

    if selected_case_ids:
        print("Selected controller eval cases:")
        for case in cases:
            print(f"  {case['id']}: {case['query']}")

    def _flush_case(case_report: dict) -> None:
        paths = write_controller_case_result(
            case_report,
            output_dir=output_dir,
            save_raw_runs=not args.no_raw_runs,
        )
        print(f"  flushed case: {case_report.get('case_id')} -> {paths['case_json_path']}")

    report = run_controller_evaluation(
        cases,
        workflow_id=args.workflow_id,
        case_timeout_seconds=args.case_timeout_seconds,
        on_case_complete=_flush_case,
        trace_steps=args.trace_steps,
    )
    paths = write_controller_evaluation_report(
        report,
        output_dir=output_dir,
        save_raw_runs=not args.no_raw_runs,
    )

    summary = report.get("overall_summary", {})
    print("Hypothesis controller evaluation complete")
    print(f"  workflow: {summary.get('workflow_id')}")
    print(f"  cases: {summary.get('cases_total')}")
    print(
        "  cases with top-candidate change: "
        f"{summary.get('cases_with_top_candidate_change')}"
    )
    print(f"  json: {paths['json_path']}")
    print(f"  markdown: {paths['markdown_path']}")
    if paths.get("raw_dir"):
        print(f"  raw runs: {paths['raw_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
