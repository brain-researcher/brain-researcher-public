#!/usr/bin/env python3
"""Bridge deep-research outputs into Gabriel/KGGEN manifest seeds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.br_kg.etl.deep_research_bridge import (
    load_deep_research_result,
    write_gabriel_manifest_from_deep_research,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a deep-research result into a Gabriel/KGGEN manifest."
    )
    parser.add_argument(
        "--interaction-id",
        type=str,
        default=None,
        help="Gemini interaction ID to fetch via deep_research_get().",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        default=None,
        help="Existing deep-research result JSON path (cached result or MCP wrapper payload).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write manifest.json and seed.jsonl.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional explicit manifest run_id.",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=0,
        help="Maximum sources to keep (0 = all).",
    )
    parser.add_argument(
        "--max-snippets-per-source",
        type=int,
        default=4,
        help="Maximum citation-grounded snippets per source seed.",
    )
    parser.add_argument(
        "--snippet-context-chars",
        type=int,
        default=220,
        help="Context radius around each annotation span.",
    )
    parser.add_argument(
        "--max-abstract-chars",
        type=int,
        default=4000,
        help="Maximum abstract text written per source seed.",
    )
    parser.add_argument(
        "--resolve-redirects",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resolve Google grounding redirect URLs to final destinations.",
    )
    parser.add_argument(
        "--resolve-timeout-sec",
        type=float,
        default=10.0,
        help="Per-source redirect resolution timeout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print bridge summary as JSON.",
    )
    args = parser.parse_args()

    result = load_deep_research_result(
        interaction_id=args.interaction_id,
        result_json_path=args.result_json,
    )
    summary = write_gabriel_manifest_from_deep_research(
        result,
        output_dir=args.output_dir,
        run_id=args.run_id,
        interaction_id=args.interaction_id,
        max_sources=max(0, int(args.max_sources)),
        max_snippets_per_source=max(1, int(args.max_snippets_per_source)),
        snippet_context_chars=max(0, int(args.snippet_context_chars)),
        max_abstract_chars=max(500, int(args.max_abstract_chars)),
        resolve_redirects=bool(args.resolve_redirects),
        resolve_timeout_sec=max(1.0, float(args.resolve_timeout_sec)),
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return
    print("Deep research bridge complete")
    print(f"Manifest: {summary['artifacts']['manifest_path']}")
    print(f"Seeds: {summary['artifacts']['seed_path']}")
    print(f"Summary: {summary['artifacts']['bridge_summary_path']}")


if __name__ == "__main__":
    main()
