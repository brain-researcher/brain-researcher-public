#!/usr/bin/env python
"""Generate idea cards from deep-research output plus raw KGGEN relations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.agent.deep_research_idea_cards import (
    build_deep_research_idea_cards,
)
from brain_researcher.services.br_kg.etl.deep_research_bridge import (
    load_deep_research_result,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deep-research grounded idea cards from KGGEN output."
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
        help="Optional deep-research result JSON file.",
    )
    parser.add_argument(
        "--kggen-input",
        type=Path,
        required=True,
        help="Raw KGGEN JSONL generated from a Gabriel/bridge manifest.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Optional query/context override for card phrasing.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Maximum idea cards to emit.",
    )
    parser.add_argument(
        "--min-supporting-papers",
        type=int,
        default=2,
        help="Minimum distinct papers required for one cluster to become a card.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result JSON to stdout.",
    )
    args = parser.parse_args()

    result = load_deep_research_result(
        interaction_id=args.interaction_id,
        result_json_path=args.result_json,
    )
    payload = build_deep_research_idea_cards(
        deep_research_result=result,
        kggen_input=args.kggen_input,
        query=args.query,
        top_n=args.top_n,
        min_supporting_papers=args.min_supporting_papers,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "summary": payload.get("summary", {}),
                    "titles": [
                        card.get("title")
                        for card in payload.get("candidate_cards", [])
                    ],
                    "output_path": str(args.output) if args.output else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
