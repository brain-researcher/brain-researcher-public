#!/usr/bin/env python3
"""Build a dry-run OpenNeuro dataset->publication candidate pack.

This probe does not write graph mutations. It resolves OpenNeuro dataset nodes,
queries Google Search grounding for a small set of exact/related publication
strategies, and emits scored publication-anchor candidates as JSON or JSONL.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.publication_candidates import (
    DatasetPublicationSeed,
    RawPublicationCandidate,
    build_candidate_report,
    build_publication_seed,
    build_search_plans,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    load_dotenv(repo_root / ".env.local", override=False)


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("Missing GEMINI_API_KEY or GOOGLE_API_KEY.")
    return key


def _normalize_dataset_kg_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Dataset id must be non-empty.")
    if text.startswith("ds:openneuro:"):
        return text
    if text.startswith("ds"):
        return f"ds:openneuro:{text}"
    return text


def resolve_dataset_seed_from_kg(dataset_id: str) -> DatasetPublicationSeed:
    from brain_researcher.services.br_kg import query_service

    normalized = _normalize_dataset_kg_id(dataset_id)
    detail = query_service.node_details(normalized)
    if detail is None or str(detail.node_type or "").lower() != "dataset":
        hits = query_service.search_nodes(dataset_id, limit=8, infer_types=True)
        for hit in hits:
            if str(hit.node_type or "").lower() != "dataset":
                continue
            hit_props = hit.properties or {}
            keys = {
                str(hit.kg_id or "").strip(),
                str(hit_props.get("dataset_id") or "").strip(),
                str(hit_props.get("source_repo_id") or "").strip(),
            }
            if normalized in keys or dataset_id in keys:
                detail = hit
                break
    if detail is None:
        raise ValueError(f"Dataset node not found: {dataset_id}")
    if str(detail.node_type or "").lower() != "dataset":
        raise ValueError(f"Resolved node is not a Dataset: {dataset_id}")
    return build_publication_seed(
        kg_id=str(detail.kg_id or normalized),
        label=detail.label,
        properties=detail.properties,
    )


def _candidate_schema(limit: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "maxItems": int(limit),
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "doi": {"type": "string"},
                        "pmid": {"type": "string"},
                        "pmcid": {"type": "string"},
                        "year": {"type": "integer"},
                        "journal": {"type": "string"},
                        "url": {"type": "string"},
                        "legacy_accession": {"type": "string"},
                        "candidate_kind": {
                            "type": "string",
                            "enum": [
                                "exact_openneuro_doi",
                                "exact_title_match",
                                "legacy_openfmri_match",
                                "related_descriptor",
                                "related_analysis",
                                "other",
                            ],
                        },
                        "match_confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "title",
                        "url",
                        "candidate_kind",
                        "match_confidence",
                        "rationale",
                    ],
                },
            }
        },
        "required": ["candidates"],
    }


def _extract_text_from_response(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                return part_text
    return ""


def _extract_payload_from_response(response: Any) -> dict[str, Any] | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    text = _extract_text_from_response(response)
    if not text:
        return None
    try:
        parsed_text = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed_text, dict):
        return parsed_text
    return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class GoogleSearchPublicationCandidateFinder:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_candidates_per_plan: int,
        temperature: float = 0.0,
    ) -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.max_candidates_per_plan = max(1, int(max_candidates_per_plan))
        self.temperature = float(temperature)

    def run_plan(
        self,
        *,
        seed: DatasetPublicationSeed,
        strategy: str,
        query: str,
        rationale: str,
    ) -> list[RawPublicationCandidate]:
        types = self._genai.types
        google_search = types.GoogleSearch()
        tool = types.Tool(google_search=google_search)
        prompt = (
            "Find scholarly publication candidates for an OpenNeuro dataset.\n"
            "Dataset metadata:\n"
            f"- kg_id: {seed.kg_id}\n"
            f"- dataset_id: {seed.dataset_id}\n"
            f"- source_repo_id: {seed.source_repo_id}\n"
            f"- title: {seed.title}\n"
            f"- aliases: {', '.join(seed.aliases) or '(none)'}\n"
            f"- openneuro_dois: {', '.join(seed.openneuro_dois) or '(none)'}\n"
            f"- primary_url: {seed.primary_url or '(none)'}\n\n"
            f"Search strategy: {strategy}\n"
            f"Strategy rationale: {rationale}\n"
            f"Search query to prioritize: {query}\n\n"
            "Return only real scholarly publications, preprints, dataset descriptor papers, "
            "or closely related analysis papers. Exclude dataset landing pages, repositories, "
            "and general webpages unless they clearly identify a scholarly paper.\n"
            "Prefer candidates with DOI or PMID when available."
        )
        config = types.GenerateContentConfig(
            system_instruction=(
                "Use Google Search to ground the answer. Return strict JSON only."
            ),
            tools=[tool],
            response_modalities=["text"],
            response_mime_type="application/json",
            response_schema=_candidate_schema(self.max_candidates_per_plan),
            max_output_tokens=1400,
            temperature=self.temperature,
        )
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        payload = _extract_payload_from_response(response)
        if not isinstance(payload, dict):
            logger.warning("Failed to parse Google Search JSON for %s", strategy)
            return []
        candidates = payload.get("candidates") or []
        out: list[RawPublicationCandidate] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            out.append(
                RawPublicationCandidate(
                    title=str(item.get("title") or "").strip(),
                    doi=str(item.get("doi") or "").strip() or None,
                    pmid=str(item.get("pmid") or "").strip() or None,
                    pmcid=str(item.get("pmcid") or "").strip() or None,
                    year=_safe_int(item.get("year")),
                    journal=str(item.get("journal") or "").strip() or None,
                    url=str(item.get("url") or "").strip(),
                    legacy_accession=str(item.get("legacy_accession") or "").strip()
                    or None,
                    candidate_kind=str(item.get("candidate_kind") or strategy).strip()
                    or strategy,
                    match_confidence=float(item.get("match_confidence") or 0.0),
                    rationale=str(item.get("rationale") or "").strip(),
                )
            )
        return out


def build_publication_candidate_pack(
    dataset_ids: Sequence[str],
    *,
    finder: GoogleSearchPublicationCandidateFinder,
) -> dict[str, Any]:
    dataset_reports: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        seed = resolve_dataset_seed_from_kg(dataset_id)
        plan_hits: dict[str, list[RawPublicationCandidate]] = {}
        for plan in build_search_plans(seed):
            plan_hits[plan.strategy] = finder.run_plan(
                seed=seed,
                strategy=plan.strategy,
                query=plan.query,
                rationale=plan.rationale,
            )
        dataset_reports.append(build_candidate_report(seed, plan_hits))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_reports": dataset_reports,
        "summary": {
            "n_datasets": len(dataset_reports),
            "n_total_candidates": sum(
                len(report.get("candidates") or []) for report in dataset_reports
            ),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dry-run OpenNeuro publication candidate pack."
    )
    parser.add_argument(
        "--dataset-id",
        action="append",
        dest="dataset_ids",
        required=True,
        help="OpenNeuro dataset id or KG id (repeatable).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path (.json or .jsonl).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("DEFAULT_CODING_MODEL", "gemini-3-flash-preview"),
        help="Google model to use with Google Search grounding.",
    )
    parser.add_argument(
        "--max-candidates-per-plan",
        type=int,
        default=5,
        help="Maximum candidates to request per search strategy.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level.",
    )
    return parser.parse_args(argv)


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for report in payload.get("dataset_reports") or []:
                handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO)
    )
    _load_dotenv_if_available()

    finder = GoogleSearchPublicationCandidateFinder(
        api_key=_get_api_key(),
        model=args.model,
        max_candidates_per_plan=args.max_candidates_per_plan,
    )
    payload = build_publication_candidate_pack(args.dataset_ids, finder=finder)
    if args.output is not None:
        _write_output(args.output, payload)
        print(
            json.dumps(
                {
                    "ok": True,
                    "output_path": str(args.output),
                    "summary": payload.get("summary") or {},
                },
                ensure_ascii=False,
            )
        )
        return 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
