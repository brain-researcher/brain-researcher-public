#!/usr/bin/env python3
"""Generate evaluator-ready KGGEN candidates from a Gabriel manifest.

This script reads paper IDs from a Gabriel `manifest.json` run, reconstructs
paper text from title/abstract (+ optional scholarly metadata cache), runs
KGGEN, and writes JSONL payloads consumable by:

    br gabriel eval-kggen --kggen-input <output.jsonl> ...

The output JSONL shape is one object per paper:
{
  "paper": {...},
  "relations": [{"subject": "...", "predicate": "...", "object": "...", ...}],
  "model": "gemini/gemini-2.5-flash",
  "generator_version": "kggen-manifest/v1"
}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("kggen_manifest")
REEXEC_FLAG = "KGGEN_MANIFEST_REEXEC"


@dataclass
class PaperSeed:
    paper_id: str
    title: str
    doi: str | None = None
    pmid: str | None = None
    year: int | None = None
    journal: str | None = None
    abstract: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_doi(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.lower().replace("https://doi.org/", "").replace("doi:", "")
    normalized = normalized.strip()
    return normalized or None


def _normalize_pmid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    if "pubmed.ncbi.nlm.nih.gov/" in lowered:
        tail = lowered.split("pubmed.ncbi.nlm.nih.gov/")[-1].strip("/")
        return tail or None
    return text


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "unknown"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_paper_id(raw_id: Any, *, doi: str | None, pmid: str | None, title: str) -> str:
    cleaned = _clean_text(raw_id)
    if cleaned:
        return cleaned
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    return f"paper:{_slugify(title)}"


def _openalex_abstract_to_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return None

    indexed: dict[int, str] = {}
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for pos in positions:
            idx = _safe_int(pos)
            if idx is None or idx < 0:
                continue
            indexed[idx] = token

    if not indexed:
        return None

    text = " ".join(indexed[idx] for idx in sorted(indexed))
    return _clean_text(text)


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    without_entities = (
        without_tags.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", without_entities).strip()


def _extract_title(record: dict[str, Any]) -> str | None:
    title = record.get("title")
    if isinstance(title, str):
        return _clean_text(title)
    if isinstance(title, list):
        for item in title:
            value = _clean_text(item)
            if value:
                return value
    return _clean_text(record.get("display_name"))


def _extract_year(record: dict[str, Any]) -> int | None:
    direct = _safe_int(record.get("year") or record.get("publication_year"))
    if direct is not None:
        return direct

    issued = record.get("issued")
    if isinstance(issued, dict):
        date_parts = issued.get("date-parts")
        if isinstance(date_parts, list) and date_parts:
            first = date_parts[0]
            if isinstance(first, list) and first:
                return _safe_int(first[0])
    return None


def _extract_journal(record: dict[str, Any]) -> str | None:
    for key in ("journal", "container-title"):
        value = record.get(key)
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
        if isinstance(value, list):
            for item in value:
                cleaned = _clean_text(item)
                if cleaned:
                    return cleaned
    host = record.get("host_venue")
    if isinstance(host, dict):
        return _clean_text(host.get("display_name"))
    primary_location = record.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict):
            return _clean_text(source.get("display_name"))
    return None


def _extract_pmid(record: dict[str, Any]) -> str | None:
    for key in ("pmid",):
        pmid = _normalize_pmid(record.get(key))
        if pmid:
            return pmid

    ids = record.get("ids")
    if isinstance(ids, dict):
        pmid = _normalize_pmid(ids.get("pmid"))
        if pmid:
            return pmid
    return None


def _extract_abstract(record: dict[str, Any]) -> str | None:
    direct = _clean_text(record.get("abstract"))
    if direct:
        return _strip_html(direct)
    summary = _clean_text(record.get("summary"))
    if summary:
        return summary
    reconstructed = _openalex_abstract_to_text(record.get("abstract_inverted_index"))
    if reconstructed:
        return reconstructed
    return None


def _manifest_latest(output_root: Path) -> Path:
    runs_dir = (output_root / "runs").resolve()
    candidates = sorted(
        runs_dir.glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No manifest found under {runs_dir}")
    return candidates[-1]


def _resolve_manifest(manifest: Path | None, output_root: Path) -> Path:
    if manifest:
        resolved = manifest.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Manifest not found: {resolved}")
        return resolved
    return _manifest_latest(output_root)


def _load_manifest_papers(manifest_path: Path) -> tuple[list[PaperSeed], dict[str, int]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id: dict[str, PaperSeed] = {}
    parse_errors = 0
    records_seen = 0

    for shard in manifest.get("shards", []):
        shard_path_raw = _clean_text(shard.get("path"))
        if not shard_path_raw:
            continue
        shard_path = Path(shard_path_raw).expanduser().resolve()
        if not shard_path.exists():
            LOGGER.warning("Skipping missing shard: %s", shard_path)
            continue
        with shard_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                records_seen += 1
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(payload, dict):
                    parse_errors += 1
                    continue
                paper = payload.get("paper")
                if not isinstance(paper, dict):
                    parse_errors += 1
                    continue

                title = _clean_text(paper.get("title")) or "Untitled publication"
                doi = _normalize_doi(paper.get("doi"))
                pmid = _normalize_pmid(paper.get("pmid"))
                paper_id = _normalize_paper_id(
                    paper.get("id"),
                    doi=doi,
                    pmid=pmid,
                    title=title,
                )

                seed = by_id.get(paper_id)
                if seed is None:
                    by_id[paper_id] = PaperSeed(
                        paper_id=paper_id,
                        title=title,
                        doi=doi,
                        pmid=pmid,
                        year=_safe_int(paper.get("year")),
                        journal=_clean_text(paper.get("journal")),
                        abstract=_clean_text(paper.get("abstract")),
                    )
                    continue

                if not seed.title and title:
                    seed.title = title
                if not seed.doi and doi:
                    seed.doi = doi
                if not seed.pmid and pmid:
                    seed.pmid = pmid
                if seed.year is None:
                    seed.year = _safe_int(paper.get("year"))
                if not seed.journal:
                    seed.journal = _clean_text(paper.get("journal"))
                if not seed.abstract:
                    seed.abstract = _clean_text(paper.get("abstract"))

    papers = sorted(by_id.values(), key=lambda item: item.paper_id)
    stats = {
        "records_seen": records_seen,
        "records_parse_errors": parse_errors,
        "papers_discovered": len(papers),
    }
    return papers, stats


class MetadataCache:
    """Lazy DOI/PMID metadata lookup from scholarly cache files."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir.expanduser().resolve()
        self._doi_cache: dict[str, dict[str, Any]] = {}
        self._pmid_cache: dict[str, dict[str, Any]] = {}

    def lookup(self, *, doi: str | None, pmid: str | None) -> dict[str, Any]:
        if doi:
            normalized = _normalize_doi(doi)
            if normalized:
                cached = self._doi_cache.get(normalized)
                if cached is not None:
                    return cached
                payload = self._lookup_by_doi(normalized)
                self._doi_cache[normalized] = payload
                if payload:
                    pmid_value = _normalize_pmid(payload.get("pmid"))
                    if pmid_value:
                        self._pmid_cache[pmid_value] = payload
                    return payload

        if pmid:
            normalized_pmid = _normalize_pmid(pmid)
            if normalized_pmid:
                cached = self._pmid_cache.get(normalized_pmid)
                if cached is not None:
                    return cached
        return {}

    def _lookup_by_doi(self, doi: str) -> dict[str, Any]:
        if not self.cache_dir.exists():
            return {}

        slug = _slugify(doi)
        candidates = [
            self.cache_dir / f"openalex_{slug}.json",
            self.cache_dir / f"crossref_{slug}.json",
        ]

        records: list[dict[str, Any]] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                LOGGER.debug("Skipping invalid metadata cache file: %s", path)
                continue
            if isinstance(raw, dict):
                records.append(raw)

        if not records:
            return {}
        return _merge_metadata_records(records)


def _merge_metadata_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    abstracts: list[str] = []

    for record in records:
        doi = _normalize_doi(record.get("doi") or record.get("DOI"))
        pmid = _extract_pmid(record)
        title = _extract_title(record)
        abstract = _extract_abstract(record)
        year = _extract_year(record)
        journal = _extract_journal(record)

        if doi and not merged.get("doi"):
            merged["doi"] = doi
        if pmid and not merged.get("pmid"):
            merged["pmid"] = pmid
        if title and not merged.get("title"):
            merged["title"] = title
        if year is not None and merged.get("year") is None:
            merged["year"] = year
        if journal and not merged.get("journal"):
            merged["journal"] = journal
        if abstract:
            abstracts.append(abstract)

    if abstracts:
        merged["abstract"] = max(abstracts, key=len)
    return merged


def _build_input_text(seed: PaperSeed, metadata: dict[str, Any], max_chars: int) -> tuple[str, bool]:
    title = _clean_text(seed.title) or _clean_text(metadata.get("title")) or seed.paper_id
    abstract = (
        _clean_text(seed.abstract)
        or _clean_text(metadata.get("abstract"))
        or ""
    )

    lines = [f"Title: {title}"]
    has_abstract = bool(abstract)
    if has_abstract:
        lines.append(f"Abstract: {abstract}")

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text, has_abstract


def _load_kggen_class(venv_python: Path):
    try:
        from kg_gen import KGGen  # type: ignore
        return KGGen
    except Exception as exc:  # pragma: no cover - depends on runtime env
        candidate = venv_python.expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).absolute()
        if os.environ.get(REEXEC_FLAG) == "1":
            raise RuntimeError(
                f"Unable to import kg_gen even after re-exec with {candidate}: {exc}"
            ) from exc
        if not candidate.exists():
            raise RuntimeError(
                "kg_gen is not importable and venv python was not found at "
                f"{candidate}. Install KGGEN or pass --venv-python."
            ) from exc

        env = dict(os.environ)
        env[REEXEC_FLAG] = "1"
        argv = [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]]
        os.execve(str(candidate), argv, env)
        raise RuntimeError("re-exec failed unexpectedly") from exc


_WEAK_RELATION_PREDICATES = {
    "related_to",
    "associated_with",
    "linked_to",
    "correlates_with",
}
_NEUROANATOMY_HINT_TERMS = (
    "cortex",
    "gyrus",
    "sulcus",
    "insula",
    "hippocamp",
    "amygdala",
    "thalam",
    "striat",
    "cerebell",
    "prefrontal",
    "frontal",
    "parietal",
    "temporal",
    "occipital",
    "precuneus",
)


def _is_specific_predicate(predicate: str) -> bool:
    return predicate.strip().lower() not in _WEAK_RELATION_PREDICATES


def _mentions_neuroanatomy(text: str) -> bool:
    lowered = text.strip().lower()
    return any(term in lowered for term in _NEUROANATOMY_HINT_TERMS)


def _kggen_relations_to_rows(
    relations: list[tuple[str, str, str]],
    *,
    has_abstract: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subject, predicate, obj in relations:
        subj = _clean_text(subject)
        pred = _clean_text(predicate)
        tail = _clean_text(obj)
        if not subj or not pred or not tail:
            continue
        claim_text = f"{subj} {pred} {tail}"
        specific_predicate = _is_specific_predicate(pred)
        anatomical_object = _mentions_neuroanatomy(tail)

        confidence = 0.70 if has_abstract else 0.58
        confidence += 0.08 if specific_predicate else -0.04
        confidence += 0.05 if anatomical_object else 0.0
        confidence = max(0.0, min(1.0, confidence))

        statistical_density = 0.52 if has_abstract else 0.24
        statistical_density += 0.08 if specific_predicate else -0.05
        statistical_density = max(0.0, min(1.0, statistical_density))

        context_overlap = 0.68 if has_abstract else 0.44
        context_overlap += 0.08 if anatomical_object else 0.0
        context_overlap = max(0.0, min(1.0, context_overlap))

        assertive_verb_ratio = 0.60 if has_abstract else 0.45
        assertive_verb_ratio += 0.12 if specific_predicate else -0.08
        assertive_verb_ratio = max(0.0, min(1.0, assertive_verb_ratio))

        sample_size_adequacy = 0.50 if has_abstract else 0.40
        sample_size_adequacy += 0.10 if specific_predicate else 0.0
        sample_size_adequacy = max(0.0, min(1.0, sample_size_adequacy))

        roi_definition_clear = bool(has_abstract and anatomical_object)
        has_statistical_detail = bool(
            has_abstract and specific_predicate and statistical_density >= 0.55
        )

        rows.append(
            {
                "subject": subj,
                "predicate": pred,
                "object": tail,
                "confidence": confidence,
                "claim_text": claim_text,
                "evidence_quote": claim_text,
                "section": "abstract" if has_abstract else "title",
                "mention_frequency": 1,
                "max_frequency": 5,
                "title_hit": True,
                "abstract_hit": bool(has_abstract),
                "context_overlap": context_overlap,
                "modal_density": 0.30,
                "statistical_density": statistical_density,
                "assertive_verb_ratio": assertive_verb_ratio,
                "sample_size_adequacy": sample_size_adequacy,
                "roi_definition_clear": roi_definition_clear,
                "has_statistical_detail": has_statistical_detail,
                "threshold_correction_reported": False,
                "preregistration": False,
                "open_data_or_code": False,
                "polarity": "supports",
            }
        )
    return rows


def _dry_run_relations(seed: PaperSeed) -> list[tuple[str, str, str]]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]+", seed.title or "")
    if len(words) < 3:
        words = [seed.paper_id.replace(":", " ")]
    subject = " ".join(words[: min(5, len(words))])
    obj = " ".join(words[max(0, len(words) - 4) :]) or "neural finding"
    return [(subject, "related_to", obj)]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate real KGGEN candidates aligned to a Gabriel manifest.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to Gabriel manifest.json. Defaults to latest under output-root/runs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/br-kg/raw/gabriel"),
        help="Gabriel output root used for latest manifest discovery.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/br-kg/raw/scholarly_metadata"),
        help="Scholarly metadata cache directory for abstract enrichment.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/br-kg/raw/kggen/real_from_manifest.jsonl"),
        help="Output JSONL path.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Optional summary JSON path. Defaults to <output>.summary.json.",
    )
    parser.add_argument(
        "--model",
        default="gemini/gemini-2.5-flash",
        help="KGGEN model (LiteLLM format).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key passed directly to KGGEN.",
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="Optional API base URL passed directly to KGGEN.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for KGGEN.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Optional reasoning effort passed to KGGEN.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8000,
        help="Chunk size for long texts passed to KGGEN generate().",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=12000,
        help="Hard cap for composed paper text.",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=0,
        help="Max papers to process (0 = all).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Paper offset after deterministic sort.",
    )
    parser.add_argument(
        "--max-relations-per-paper",
        type=int,
        default=60,
        help="Max KGGEN relations retained per paper.",
    )
    parser.add_argument(
        "--context",
        default="Neuroscience publication metadata (title/abstract).",
        help="Context hint passed to KGGEN.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional sleep between paper calls.",
    )
    parser.add_argument(
        "--require-abstract",
        action="store_true",
        help="Skip papers without abstract text.",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable KGGEN deduplication step.",
    )
    parser.add_argument(
        "--no-dspy",
        action="store_true",
        help="Use KGGEN LiteLLM prompt mode (no DSPy wrappers).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call model; generate one synthetic relation per paper.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output/summary if they exist.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on first paper error.",
    )
    parser.add_argument(
        "--venv-python",
        type=Path,
        default=Path("external/kg-gen/.venv/bin/python"),
        help="Python binary used for auto re-exec when kg_gen is unavailable.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summary as JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    manifest_path = _resolve_manifest(args.manifest, args.output_root)
    papers, manifest_stats = _load_manifest_papers(manifest_path)
    if not papers:
        raise RuntimeError(f"No papers found in manifest shards: {manifest_path}")

    start = max(0, int(args.offset))
    selected = papers[start:]
    if args.max_papers > 0:
        selected = selected[: args.max_papers]
    if not selected:
        raise RuntimeError("No papers selected after applying offset/max-papers.")

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = (
        args.summary_output.expanduser().resolve()
        if args.summary_output
        else output_path.with_suffix(".summary.json")
    )

    if not args.overwrite and output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path} (use --overwrite)")
    if not args.overwrite and summary_path.exists():
        raise FileExistsError(f"Summary already exists: {summary_path} (use --overwrite)")

    metadata_cache = MetadataCache(args.cache_dir)

    KGGen = None
    dedup_method = None
    kg = None
    if not args.dry_run:
        KGGen = _load_kggen_class(args.venv_python)
        if not args.no_dedup:
            from kg_gen.steps._3_deduplicate import (  # type: ignore
                DeduplicateMethod,
            )

            dedup_method = DeduplicateMethod.SEMHASH
        kg = KGGen(
            model=args.model,
            temperature=float(args.temperature),
            reasoning_effort=args.reasoning_effort,
            api_key=args.api_key,
            api_base=args.api_base,
        )

    counters = {
        "papers_selected": len(selected),
        "papers_written": 0,
        "papers_skipped_no_abstract": 0,
        "papers_skipped_no_text": 0,
        "papers_with_errors": 0,
        "relations_written": 0,
    }
    errors: list[dict[str, Any]] = []
    started_at = _utc_now_iso()
    start_time = time.time()

    with output_path.open("w", encoding="utf-8") as handle:
        for index, seed in enumerate(selected, start=1):
            metadata = metadata_cache.lookup(doi=seed.doi, pmid=seed.pmid)
            text, has_abstract = _build_input_text(
                seed,
                metadata,
                max_chars=max(500, int(args.max_text_chars)),
            )
            if not text:
                counters["papers_skipped_no_text"] += 1
                continue
            if args.require_abstract and not has_abstract:
                counters["papers_skipped_no_abstract"] += 1
                continue

            paper_payload = {
                "id": seed.paper_id,
                "title": seed.title or metadata.get("title") or seed.paper_id,
                "doi": _normalize_doi(seed.doi or metadata.get("doi")),
                "pmid": _normalize_pmid(seed.pmid or metadata.get("pmid")),
                "year": seed.year if seed.year is not None else metadata.get("year"),
                "journal": seed.journal or metadata.get("journal"),
            }
            paper_payload = {
                k: v
                for k, v in paper_payload.items()
                if v is not None and not (isinstance(v, str) and not v.strip())
            }

            try:
                if args.dry_run:
                    raw_relations = _dry_run_relations(seed)
                else:
                    assert kg is not None
                    try:
                        graph = kg.generate(
                            input_data=text,
                            context=args.context,
                            chunk_size=max(0, int(args.chunk_size)) or None,
                            deduplication_method=dedup_method,
                            no_dspy=bool(args.no_dspy),
                        )
                    except Exception as dedup_exc:
                        if dedup_method is None:
                            raise
                        if "DeduplicationResult" not in str(dedup_exc):
                            raise
                        LOGGER.warning(
                            "Deduplication failed for %s (%s); retrying without dedup",
                            seed.paper_id,
                            dedup_exc,
                        )
                        graph = kg.generate(
                            input_data=text,
                            context=args.context,
                            chunk_size=max(0, int(args.chunk_size)) or None,
                            deduplication_method=None,
                            no_dspy=bool(args.no_dspy),
                        )
                    raw_relations = sorted(
                        (str(s), str(p), str(o))
                        for s, p, o in (graph.relations or [])
                    )
            except Exception as exc:  # pragma: no cover - runtime dependent
                counters["papers_with_errors"] += 1
                error_payload = {
                    "paper_id": seed.paper_id,
                    "title": seed.title,
                    "error": str(exc),
                }
                errors.append(error_payload)
                LOGGER.warning("KGGEN failed for %s: %s", seed.paper_id, exc)
                if args.fail_fast:
                    raise
                continue

            if args.max_relations_per_paper > 0:
                raw_relations = raw_relations[: args.max_relations_per_paper]

            relation_rows = _kggen_relations_to_rows(
                raw_relations,
                has_abstract=has_abstract,
            )

            payload = {
                "paper": paper_payload,
                "relations": relation_rows,
                "model": args.model,
                "generator_version": "kggen-manifest/v1",
                "generated_at": _utc_now_iso(),
                "source_text_meta": {
                    "has_abstract": has_abstract,
                    "text_chars": len(text),
                    "dry_run": bool(args.dry_run),
                },
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

            counters["papers_written"] += 1
            counters["relations_written"] += len(relation_rows)

            if index % 10 == 0:
                LOGGER.info(
                    "Progress %d/%d papers, %d relations written",
                    index,
                    len(selected),
                    counters["relations_written"],
                )
            if args.sleep_seconds > 0:
                time.sleep(float(args.sleep_seconds))

    summary = {
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "duration_seconds": round(time.time() - start_time, 3),
        "manifest_path": str(manifest_path),
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "cache_dir": str(args.cache_dir.expanduser().resolve()),
        "configuration": {
            "model": args.model,
            "temperature": float(args.temperature),
            "reasoning_effort": args.reasoning_effort,
            "chunk_size": int(args.chunk_size),
            "max_text_chars": int(args.max_text_chars),
            "max_papers": int(args.max_papers),
            "offset": int(args.offset),
            "max_relations_per_paper": int(args.max_relations_per_paper),
            "require_abstract": bool(args.require_abstract),
            "dry_run": bool(args.dry_run),
            "no_dedup": bool(args.no_dedup),
            "no_dspy": bool(args.no_dspy),
        },
        "manifest_stats": manifest_stats,
        "counters": counters,
        "errors": errors[:100],
        "errors_truncated": len(errors) > 100,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, ensure_ascii=True, indent=2))
    else:
        LOGGER.info(
            "Wrote %d papers / %d relations to %s",
            counters["papers_written"],
            counters["relations_written"],
            output_path,
        )
        LOGGER.info("Summary: %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
