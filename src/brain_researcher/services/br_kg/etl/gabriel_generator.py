"""Sharded GABRIEL generator and ingester for BR-KG."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.scholarly_metadata_loader import (
    DEFAULT_CACHE_DIR,
    ScholarlyMetadataLoader,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.llm_gateway.router import LLMRouter

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = Path("data/br-kg/raw/gabriel")
DEFAULT_RUN_PREFIX = "gabriel"
GENERATOR_VERSION = "gabriel-generator/v1"
PROMPT_TEMPLATE_VERSION = "gabriel-prompt/v2"
LOADER_VERSION = "gabriel-loader/v1"

PROMPT_TEMPLATE = """You are extracting GABRIEL measurement candidates from a publication.
Return JSON only and do not include markdown fences.

Required top-level schema:
{
  "records": [
    {
      "target": {"type": "Concept|Region|Task", "label": "string", "id": "optional", "atlas": "optional"},
      "mapping": {"canonical_id": "optional", "mapping_type": "exact|related|unknown", "mapping_confidence": 0.0},
      "claim": {"text": "string", "polarity": "supports|refutes|mixed|uncertain", "claim_strength": 0.0},
      "evidence": {
        "quote": "string",
        "section": "title|abstract|methods|results|discussion|unknown",
        "page": null,
        "char_start": null,
        "char_end": null,
        "has_statistical_detail": false,
        "locatable": true,
        "direct_quote": false
      },
      "method": {
        "preregistration": {
          "status": "yes|no|unknown",
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown",
          "registry": null
        },
        "threshold_correction": {
          "status": "yes|no|unknown",
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown",
          "correction_type": null
        },
        "sample_size": {
          "status": "reported|not_reported|unknown",
          "reported_n": null,
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown"
        },
        "roi_definition": {
          "status": "clear|unclear|unknown",
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown"
        },
        "operationalization": {
          "status": "clear|unclear|unknown",
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown"
        },
        "open_data_or_code": {
          "status": "yes|no|unknown",
          "artifact": "data|code|both|unspecified|unknown",
          "quote": null,
          "section": "abstract|methods|results|discussion|unknown"
        }
      },
      "signals": {
        "mention_frequency": 1,
        "max_frequency": 5,
        "title_hit": false,
        "abstract_hit": false,
        "semantic_similarity": 0.0,
        "ontology_match": false,
        "context_overlap": 0.0,
        "modal_density": 0.0,
        "statistical_density": 0.0,
        "assertive_verb_ratio": 0.0,
        "preregistration": false,
        "threshold_correction_reported": false,
        "sample_size_adequacy": 0.0,
        "roi_definition_clear": false,
        "open_data_or_code": false
      }
    }
  ]
}

Rules:
1. Return at most {max_records} records.
2. Use only claims supported by the supplied publication metadata.
3. Keep claim text and evidence quote concise and literal.
4. Set conservative confidence when information is missing.
5. If abstract or body text is available, do not use the title as the evidence quote.
6. Prefer section-level evidence from abstract, methods, results, or discussion over title-level summaries.
7. If only title-level evidence is available, mark it conservative: `section="title"`, `claim_strength <= 0.35`, `mapping_confidence <= 0.35`.
8. Keep claim evidence and method evidence separate. The `method` block may cite a different quote/section than the claim evidence.
9. Do not infer method absence from omission. Use `unknown` when preregistration, threshold correction, sample size reporting, ROI definition, operationalization clarity, or open data/code are not explicitly stated.
10. For `Region` claims prefer `roi_definition`; for `Task` or `Concept` claims prefer `operationalization`.
11. If a method field is `yes`, `no`, `reported`, or `clear`, include a literal supporting quote and the best section label available.
"""

REGION_RULES: list[tuple[str, str, str]] = [
    (
        "dorsolateral prefrontal cortex",
        "Dorsolateral Prefrontal Cortex",
        "region:dorsolateral_prefrontal_cortex",
    ),
    (
        "dlpfc",
        "Dorsolateral Prefrontal Cortex",
        "region:dorsolateral_prefrontal_cortex",
    ),
    (
        "anterior cingulate",
        "Anterior Cingulate Cortex",
        "region:anterior_cingulate_cortex",
    ),
    ("amygdala", "Amygdala", "region:amygdala"),
    ("hippocampus", "Hippocampus", "region:hippocampus"),
    ("insula", "Insula", "region:insula"),
    ("precuneus", "Precuneus", "region:precuneus"),
]

TASK_RULES: list[tuple[str, str, str]] = [
    ("n-back", "N-back", "task:n_back"),
    ("stroop", "Stroop", "task:stroop"),
    ("go/no-go", "Go/No-Go", "task:go_no_go"),
    ("go no go", "Go/No-Go", "task:go_no_go"),
    ("flanker", "Flanker", "task:flanker"),
    ("oddball", "Oddball", "task:oddball"),
]

CONCEPT_RULES: list[tuple[str, str, str]] = [
    ("working memory", "Working Memory", "concept:working_memory"),
    ("executive", "Executive Control", "concept:executive_control"),
    ("attention", "Attention", "concept:attention"),
    ("emotion", "Emotion Regulation", "concept:emotion_regulation"),
    ("reward", "Reward Processing", "concept:reward_processing"),
    ("default mode", "Default Mode Network", "concept:default_mode_network"),
    ("language", "Language Processing", "concept:language_processing"),
]

NEGATIVE_CLAIM_TOKENS = ("decrease", "reduced", "reduction", "suppressed", "lower")
UNCERTAIN_TOKENS = ("may", "might", "possible", "possibly", "suggest", "trend")
ASSERTIVE_TOKENS = (
    "increased",
    "decreased",
    "associated",
    "predicts",
    "showed",
    "demonstrated",
)
STAT_DETAIL_PATTERN = re.compile(
    r"\b(p\s*[<=>]|fwe|fdr|t\(|z\(|f\(|confidence interval)\b",
    flags=re.IGNORECASE,
)
THRESHOLD_CORRECTION_PATTERN = re.compile(
    r"\b(fwe|fdr|bonferroni|holm|hochberg|family[- ]wise|false discovery rate|multiple comparisons?|cluster[- ]level corrected|small[- ]volume correction|svc|corrected)\b",
    flags=re.IGNORECASE,
)
PREREGISTRATION_PATTERN = re.compile(
    r"\b(preregistered|pre-registered|preregistration|registered report|clinicaltrials\.gov|osf preregistration)\b",
    flags=re.IGNORECASE,
)
SAMPLE_SIZE_PATTERN = re.compile(
    r"\b(?:n\s*=\s*(\d{1,4})|(\d{1,4})\s+(?:participants?|subjects?|patients?|controls?|healthy controls?))\b",
    flags=re.IGNORECASE,
)
OPEN_DATA_PATTERN = re.compile(
    r"\b(open data|open code|code available|data available|data availability|source code|github|gitlab|osf|openneuro|neurovault)\b",
    flags=re.IGNORECASE,
)
OPERATIONALIZATION_PATTERN = re.compile(
    r"\b(task|paradigm|contrast|condition|stimuli|stimulus|reading|localizer|go/no-go|go no go|n-back|flanker|oddball|rating|memory task|semantic|phonological|decision-making|response inhibition)\b",
    flags=re.IGNORECASE,
)


@dataclass
class PublicationSeed:
    """Minimal publication payload used by the generator."""

    paper_id: str
    title: str
    abstract: str
    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    year: int | None = None
    journal: str | None = None
    keywords: str = ""
    body: str = ""
    coordinate_space: str | None = None
    coordinate_count: int | None = None
    source: str = "neo4j"

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "pmid": self.pmid,
            "doi": self.doi,
            "pmcid": self.pmcid,
            "title": self.title,
            "keywords": self.keywords,
            "abstract": self.abstract,
            "body": self.body,
            "year": self.year,
            "journal": self.journal,
            "coordinate_space": self.coordinate_space,
            "coordinate_count": self.coordinate_count,
            "source": self.source,
        }

    def to_record_paper(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.paper_id,
            "pmid": self.pmid,
            "doi": self.doi,
            "pmcid": self.pmcid,
            "title": self.title,
            "year": self.year,
            "journal": self.journal,
            "source": self.source,
        }
        return _clean_none(payload)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "unknown"


def _clean_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and (not isinstance(value, str) or value != "")
    }


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _clamp01_optional(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _sample_size_adequacy_from_n(value: int | None) -> float | None:
    if value is None or value <= 0:
        return None
    if value >= 100:
        return 0.85
    if value >= 50:
        return 0.70
    if value >= 25:
        return 0.55
    return 0.35


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _chunked(
    items: list[PublicationSeed], size: int
) -> Iterable[list[PublicationSeed]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _increment_reason_count(counter: dict[str, int], reason: str | None) -> None:
    if not reason:
        return
    key = reason.strip().lower()
    if not key:
        return
    counter[key] = int(counter.get(key, 0)) + 1


def _normalized_reason_counts(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in payload.items():
        reason = str(key).strip().lower()
        if not reason:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        normalized[reason] = count
    return normalized


def _extract_balanced_json_block(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
            continue
        if ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def find_latest_manifest(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path | None:
    """Return latest manifest path under output_root/runs, if any."""

    runs_dir = Path(output_root) / "runs"
    if not runs_dir.exists():
        return None

    candidates = sorted(
        runs_dir.glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def resolve_manifest_path(
    manifest_path: Path | str | None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Resolve explicit manifest or infer latest from output root."""

    if manifest_path is not None:
        resolved = Path(manifest_path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Manifest not found: {resolved}")
        return resolved

    inferred = find_latest_manifest(output_root)
    if inferred is None:
        raise FileNotFoundError(
            f"No manifest found under {(Path(output_root) / 'runs').resolve()}"
        )
    return inferred.resolve()


def load_manifest_status(manifest_path: Path | str) -> dict[str, Any]:
    """Load manifest and compute up-to-date shard status from disk."""

    resolved = Path(manifest_path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Manifest not found: {resolved}")

    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    shards = manifest.get("shards", [])

    shard_statuses: list[dict[str, Any]] = []
    total_records_on_disk = 0
    total_records_ingested = 0
    complete_ingest_shards = 0

    for shard in shards:
        shard_path_raw = str(shard.get("path") or "").strip()
        shard_path = (
            Path(shard_path_raw).expanduser().resolve() if shard_path_raw else None
        )
        on_disk = _line_count(shard_path) if shard_path and shard_path.is_file() else 0
        total_records_on_disk += on_disk

        ingest_info = shard.get("ingest") or {}
        ingest_status = str(ingest_info.get("status") or "pending")
        ingest_records = int(ingest_info.get("records_ingested") or 0)
        total_records_ingested += ingest_records
        if ingest_status == "completed":
            complete_ingest_shards += 1

        shard_statuses.append(
            {
                "shard_id": int(shard.get("shard_id", 0)),
                "path": str(shard_path) if shard_path else "",
                "raw_dir": str(shard.get("raw_dir", "")),
                "records_expected": int(shard.get("records", 0)),
                "records_on_disk": on_disk,
                "ingest_status": ingest_status,
                "records_ingested": ingest_records,
                "errors": int(shard.get("errors", 0)),
            }
        )

    failure_reasons = _normalized_reason_counts(
        (manifest.get("counts") or {}).get("llm_failure_reasons")
    )
    if not failure_reasons:
        for shard in shards:
            shard_reasons = _normalized_reason_counts(shard.get("failure_reasons"))
            for reason, count in shard_reasons.items():
                failure_reasons[reason] = int(failure_reasons.get(reason, 0)) + count

    return {
        "manifest_path": str(resolved),
        "run_id": manifest.get("run_id"),
        "created_at": manifest.get("created_at"),
        "source": manifest.get("source"),
        "generator_version": manifest.get("generator_version"),
        "manifest_ingest_status": (manifest.get("ingest") or {}).get(
            "status", "not_started"
        ),
        "summary": {
            "shards_total": len(shards),
            "shards_ingested": complete_ingest_shards,
            "records_expected": int(
                (manifest.get("counts") or {}).get("records_generated", 0)
            ),
            "records_on_disk": total_records_on_disk,
            "records_ingested": total_records_ingested,
            "records_llm": int((manifest.get("counts") or {}).get("records_llm", 0)),
            "records_heuristic": int(
                (manifest.get("counts") or {}).get("records_heuristic", 0)
            ),
            "llm_errors": int((manifest.get("counts") or {}).get("llm_errors", 0)),
            "llm_failure_reasons": failure_reasons,
        },
        "shards": shard_statuses,
    }


def _manifest_promotion_strategy(manifest: dict[str, Any]) -> str:
    source_details = manifest.get("source_details") or {}
    return str(source_details.get("promotion_strategy") or "").strip().lower()


class GabrielPipelineGenerator:
    """Generate and ingest sharded GABRIEL measurement records."""

    def __init__(
        self,
        *,
        output_root: Path | str = DEFAULT_OUTPUT_ROOT,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        model_hint: str | None = None,
        max_records_per_publication: int = 1,
    ) -> None:
        self.output_root = Path(output_root)
        self.cache_dir = Path(cache_dir)
        self.model_hint = model_hint
        self.max_records_per_publication = max(1, int(max_records_per_publication))
        self.router = LLMRouter()

    def generate(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        shard_size: int = 25,
        run_id: str | None = None,
        use_cache_fallback: bool = True,
        force_heuristic: bool = False,
        overwrite: bool = False,
        pubget_extracted_dir: Path | str | None = None,
        pubget_include_body: bool = True,
        pubget_body_char_limit: int = 12000,
    ) -> dict[str, Any]:
        """Generate sharded JSONL records and manifest for GABRIEL ingestion."""

        if limit < 0:
            raise ValueError("limit must be >= 0 (use 0 for all)")
        if shard_size <= 0:
            raise ValueError("shard_size must be > 0")
        if pubget_body_char_limit < 0:
            raise ValueError("pubget_body_char_limit must be >= 0")

        if pubget_extracted_dir:
            publications, source_info = self._load_publications_from_pubget(
                extracted_dir=pubget_extracted_dir,
                limit=limit,
                offset=offset,
                include_body=pubget_include_body,
                body_char_limit=pubget_body_char_limit,
            )
        else:
            publications, source_info = self._load_publications(
                limit=limit,
                offset=offset,
                use_cache_fallback=use_cache_fallback,
            )
        if not publications:
            raise RuntimeError("No publications available for generation.")

        run_name = run_id or self._default_run_id()
        run_dir = (self.output_root / "runs" / run_name).resolve()
        shard_dir = run_dir / "shards"
        raw_dir = run_dir / "raw"
        manifest_path = run_dir / "manifest.json"

        if run_dir.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Run directory already exists: {run_dir}. Use overwrite=True to replace it."
                )
            shutil.rmtree(run_dir)

        shard_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        generated_at = _utc_now_iso()
        template_hash = _stable_hash(PROMPT_TEMPLATE)

        manifest: dict[str, Any] = {
            "run_id": run_name,
            "created_at": generated_at,
            "generator_version": GENERATOR_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "source": source_info["source"],
            "source_details": source_info,
            "query": {
                "limit": limit,
                "offset": offset,
                "shard_size": shard_size,
            },
            "options": {
                "cache_fallback": bool(use_cache_fallback),
                "force_heuristic": bool(force_heuristic),
                "model_hint": self.model_hint,
                "max_records_per_publication": self.max_records_per_publication,
                "pubget_extracted_dir": (
                    str(Path(pubget_extracted_dir).expanduser().resolve())
                    if pubget_extracted_dir
                    else None
                ),
                "pubget_include_body": bool(pubget_include_body),
                "pubget_body_char_limit": int(pubget_body_char_limit),
            },
            "paths": {
                "run_dir": str(run_dir),
                "shard_dir": str(shard_dir),
                "raw_dir": str(raw_dir),
                "manifest_path": str(manifest_path),
            },
            "counts": {
                "publications_selected": len(publications),
                "shards": 0,
                "records_generated": 0,
                "records_llm": 0,
                "records_heuristic": 0,
                "llm_errors": 0,
                "llm_failure_reasons": {},
            },
            "shards": [],
            "ingest": {
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "records_ingested": 0,
                "shards_completed": 0,
                "shards_failed": 0,
            },
        }

        publication_counter = 0

        for shard_index, publication_chunk in enumerate(
            _chunked(publications, shard_size)
        ):
            shard_path = (shard_dir / f"shard_{shard_index:04d}.jsonl").resolve()
            raw_shard_dir = (raw_dir / f"shard_{shard_index:04d}").resolve()
            raw_shard_dir.mkdir(parents=True, exist_ok=True)

            shard_records = 0
            shard_llm_records = 0
            shard_heuristic_records = 0
            shard_errors = 0
            shard_failure_reasons: dict[str, int] = {}

            with shard_path.open("w", encoding="utf-8") as shard_handle:
                for publication in publication_chunk:
                    publication_counter += 1
                    publication_run_id = f"{run_name}-p{publication_counter:07d}"
                    prompt = self._build_prompt(publication)
                    prompt_hash = _stable_hash(prompt)
                    raw_file_path = (
                        raw_shard_dir / f"pub_{publication_counter:07d}.json"
                    ).resolve()

                    (
                        records,
                        mode,
                        response_text,
                        response_meta,
                        error_message,
                        failure_reason,
                    ) = self._generate_publication_records(
                        publication=publication,
                        prompt=prompt,
                        prompt_hash=prompt_hash,
                        force_heuristic=force_heuristic,
                    )

                    if mode == "heuristic" and error_message:
                        shard_errors += 1
                        _increment_reason_count(shard_failure_reasons, failure_reason)

                    raw_payload = {
                        "run_id": publication_run_id,
                        "paper_id": publication.paper_id,
                        "generated_at": _utc_now_iso(),
                        "mode": mode,
                        "prompt_hash": prompt_hash,
                        "template_hash": template_hash,
                        "prompt": prompt,
                        "response_text": response_text,
                        "response_meta": response_meta,
                        "error": error_message,
                        "failure_reason": failure_reason,
                    }
                    raw_file_path.write_text(
                        json.dumps(raw_payload, ensure_ascii=True, indent=2),
                        encoding="utf-8",
                    )

                    timestamp = _utc_now_iso()
                    for measurement_index, base_record in enumerate(records, start=1):
                        finalized = self._finalize_record(
                            publication=publication,
                            base_record=base_record,
                            run_id=publication_run_id,
                            raw_response_path=str(raw_file_path),
                            prompt_hash=prompt_hash,
                            template_hash=template_hash,
                            model_name=str(
                                response_meta.get("model")
                                or self.model_hint
                                or "heuristic-fallback"
                            ),
                            timestamp=timestamp,
                            measurement_index=measurement_index,
                        )
                        shard_handle.write(
                            json.dumps(finalized, ensure_ascii=True) + "\n"
                        )
                        shard_records += 1
                        if mode == "llm":
                            shard_llm_records += 1
                        else:
                            shard_heuristic_records += 1

            manifest["counts"]["records_generated"] += shard_records
            manifest["counts"]["records_llm"] += shard_llm_records
            manifest["counts"]["records_heuristic"] += shard_heuristic_records
            manifest["counts"]["llm_errors"] += shard_errors
            manifest_failure_reasons = manifest["counts"].setdefault(
                "llm_failure_reasons", {}
            )
            for reason, count in shard_failure_reasons.items():
                manifest_failure_reasons[reason] = int(
                    manifest_failure_reasons.get(reason, 0)
                ) + int(count)
            manifest["shards"].append(
                {
                    "shard_id": shard_index,
                    "path": str(shard_path),
                    "raw_dir": str(raw_shard_dir),
                    "publications": len(publication_chunk),
                    "records": shard_records,
                    "records_llm": shard_llm_records,
                    "records_heuristic": shard_heuristic_records,
                    "errors": shard_errors,
                    "failure_reasons": shard_failure_reasons,
                    "ingest": {
                        "status": "pending",
                        "records_ingested": 0,
                        "completed_at": None,
                        "error": None,
                    },
                }
            )

        manifest["counts"]["shards"] = len(manifest["shards"])
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        logger.info("GABRIEL generation complete: %s", manifest_path)
        return manifest

    def ingest(
        self,
        *,
        manifest_path: Path | str | None = None,
        mode: str = "spine",
        resume: bool = True,
        quality_profile: str = "balanced",
        ingest_checkpoint_path: Path | str | None = None,
        create_missing_targets: bool = True,
        progress_log_every: int = 100,
        stall_warn_seconds: int = 180,
        log_timing_breakdown: bool = False,
        progress_log_level: str = "info",
    ) -> dict[str, Any]:
        """Ingest generated shards using GabrielMeasurementLoader."""

        resolved_manifest = resolve_manifest_path(manifest_path, self.output_root)
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        promotion_strategy = _manifest_promotion_strategy(manifest)
        if promotion_strategy == "exact_id_migration_only":
            raise RuntimeError(
                "Manifest is marked promotion_strategy=exact_id_migration_only. "
                "Skip ordinary ingest and use migrate_task_panel_exact_ids.py "
                "with --exact-prefix concept: instead."
            )

        shards = manifest.get("shards") or []
        if not shards:
            raise RuntimeError(f"No shards found in manifest: {resolved_manifest}")

        review_queue_path = (
            Path(manifest.get("paths", {}).get("run_dir", resolved_manifest.parent))
            / "review_queue.jsonl"
        ).resolve()
        candidate_only_review_queue_path = (
            Path(manifest.get("paths", {}).get("run_dir", resolved_manifest.parent))
            / "review_queue_candidate_only.jsonl"
        ).resolve()

        manifest_ingest = manifest.setdefault("ingest", {})
        manifest_ingest["status"] = "running"
        manifest_ingest["started_at"] = _utc_now_iso()

        total_records_ingested = 0
        shards_completed = 0
        shards_failed = 0
        shards_skipped = 0
        aggregated_stats: dict[str, int] = {
            "records_total": 0,
            "records_parsed": 0,
            "records_accepted": 0,
            "records_rejected": 0,
            "review_queue_items": 0,
            "nodes_created": 0,
            "relationships_created": 0,
            "parse_errors": 0,
        }

        run_dir = Path(
            manifest.get("paths", {}).get("run_dir", resolved_manifest.parent)
        )
        checkpoint_path = (
            Path(ingest_checkpoint_path).expanduser().resolve()
            if ingest_checkpoint_path is not None
            else (run_dir / "ingest_checkpoint.json").resolve()
        )

        shard_lookup_by_resolved_path: dict[str, dict[str, Any]] = {}
        input_paths: list[str] = []

        for shard in shards:
            ingest_state = (shard.get("ingest") or {}).get("status")
            if resume and ingest_state == "completed":
                shards_skipped += 1
                total_records_ingested += int(
                    (shard.get("ingest") or {}).get("records_ingested") or 0
                )
                continue

            shard_path_raw = str(shard.get("path") or "").strip()
            shard_path = (
                Path(shard_path_raw).expanduser().resolve() if shard_path_raw else None
            )
            shard_ingest: dict[str, Any] = {
                "status": "failed",
                "records_ingested": 0,
                "completed_at": None,
                "error": None,
            }

            if shard_path is None:
                shard_ingest["error"] = "Shard path missing in manifest"
                shards_failed += 1
                shard["ingest"] = shard_ingest
                continue

            if not shard_path.exists() or not shard_path.is_file():
                shard_ingest["error"] = f"Shard missing: {shard_path}"
                shards_failed += 1
                shard["ingest"] = shard_ingest
                continue

            shard_lookup_by_resolved_path[str(shard_path)] = shard
            input_paths.append(str(shard_path))

        loader_stats: dict[str, Any] = {}
        loader_error: str | None = None
        if input_paths:
            db = require_neo4j_db(preload_cache=False)
            try:
                loader = GabrielMeasurementLoader(
                    db,
                    config={
                        "input_paths": input_paths,
                        "review_queue_path": str(review_queue_path),
                        "candidate_only_review_queue_path": str(
                            candidate_only_review_queue_path
                        ),
                        "loader_version": LOADER_VERSION,
                        "quality_profile": quality_profile,
                        "ingest_checkpoint_path": str(checkpoint_path),
                        "create_missing_targets": bool(create_missing_targets),
                        "progress_log_every": int(progress_log_every),
                        "stall_warn_seconds": int(stall_warn_seconds),
                        "log_timing_breakdown": bool(log_timing_breakdown),
                        "progress_log_level": str(progress_log_level or "info"),
                    },
                )
                loader_stats = loader.load(mode=mode)
            except Exception as exc:  # pragma: no cover - defensive
                loader_error = str(exc)
                logger.exception("Batch shard ingest failed")
            finally:
                db.close()

        checkpoint_state = _read_json_file(checkpoint_path)
        checkpoint_files = (
            checkpoint_state.get("files", {})
            if isinstance(checkpoint_state, dict)
            else {}
        )
        per_file_stats = (
            loader_stats.get("per_file", {}) if isinstance(loader_stats, dict) else {}
        )

        for resolved_path, shard in shard_lookup_by_resolved_path.items():
            checkpoint_entry = checkpoint_files.get(resolved_path)
            file_key = str(Path(resolved_path))
            file_stats = per_file_stats.get(file_key) or {}
            accepted = int(file_stats.get("records_accepted", 0) or 0)
            total_records_ingested += accepted

            for key in aggregated_stats:
                aggregated_stats[key] += int(file_stats.get(key, 0) or 0)

            ingest_payload: dict[str, Any] = {
                "status": "completed",
                "records_ingested": accepted,
                "completed_at": _utc_now_iso(),
                "error": None,
                "stats": file_stats,
            }

            if loader_error:
                ingest_payload.update(
                    {
                        "status": "failed",
                        "records_ingested": 0,
                        "error": loader_error,
                    }
                )
            elif isinstance(checkpoint_entry, dict):
                checkpoint_status = str(checkpoint_entry.get("status") or "").lower()
                if checkpoint_status == "failed":
                    ingest_payload["status"] = "failed"
                    ingest_payload["error"] = checkpoint_entry.get("error")
                if checkpoint_entry.get("finished_at"):
                    ingest_payload["completed_at"] = str(
                        checkpoint_entry["finished_at"]
                    )

            shard["ingest"] = ingest_payload
            if ingest_payload["status"] == "completed":
                shards_completed += 1
            else:
                shards_failed += 1

        ingest_status = "completed" if shards_failed == 0 else "partial"
        manifest_ingest.update(
            {
                "status": ingest_status,
                "completed_at": _utc_now_iso(),
                "records_ingested": total_records_ingested,
                "shards_completed": shards_completed,
                "shards_failed": shards_failed,
                "shards_skipped": shards_skipped,
                "mode": mode,
                "review_queue_path": str(review_queue_path),
                "candidate_only_review_queue_path": str(
                    candidate_only_review_queue_path
                ),
                "quality_profile": quality_profile,
                "create_missing_targets": bool(create_missing_targets),
                "ingest_checkpoint_path": str(checkpoint_path),
                "stats": aggregated_stats,
            }
        )

        resolved_manifest.write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        return {
            "manifest_path": str(resolved_manifest),
            "status": ingest_status,
            "quality_profile": quality_profile,
            "create_missing_targets": bool(create_missing_targets),
            "shards_total": len(shards),
            "shards_completed": shards_completed,
            "shards_failed": shards_failed,
            "shards_skipped": shards_skipped,
            "records_ingested": total_records_ingested,
            "review_queue_path": str(review_queue_path),
            "candidate_only_review_queue_path": str(candidate_only_review_queue_path),
            "ingest_checkpoint_path": str(checkpoint_path),
            "stats": aggregated_stats,
        }

    def ingest_candidate_only(
        self,
        *,
        manifest_path: Path | str | None = None,
        queue_path: Path | str | None = None,
        source_quality_profile: str = "candidate_only",
        create_missing_targets: bool = True,
    ) -> dict[str, Any]:
        """Load candidate-only review queue rows into the live Neo4j graph."""

        resolved_manifest: Path | None = None
        manifest: dict[str, Any] | None = None
        if queue_path is None:
            resolved_manifest = resolve_manifest_path(manifest_path, self.output_root)
            manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))

        if queue_path is not None:
            resolved_queue_path = Path(queue_path).expanduser().resolve()
        elif manifest is not None and resolved_manifest is not None:
            resolved_queue_path = (
                Path(manifest.get("paths", {}).get("run_dir", resolved_manifest.parent))
                / "review_queue_candidate_only.jsonl"
            ).resolve()
        else:  # pragma: no cover - defensive fallback
            raise RuntimeError("Unable to resolve candidate-only queue path")

        if not resolved_queue_path.exists() or not resolved_queue_path.is_file():
            raise RuntimeError(
                f"Candidate-only review queue not found: {resolved_queue_path}"
            )

        db = require_neo4j_db(preload_cache=False)
        try:
            loader = GabrielMeasurementLoader(
                db,
                config={
                    "candidate_only_review_queue_path": str(resolved_queue_path),
                    "loader_version": LOADER_VERSION,
                    "create_missing_targets": bool(create_missing_targets),
                },
            )
            candidate_stats = loader.load_candidate_only_queue(
                queue_paths=[resolved_queue_path],
                source_quality_profile=source_quality_profile,
            )
        finally:
            db.close()

        result = {
            "queue_path": str(resolved_queue_path),
            "source_quality_profile": source_quality_profile,
            "create_missing_targets": bool(create_missing_targets),
            "status": (
                "failed"
                if int(candidate_stats.get("files_failed") or 0) > 0
                else "completed"
            ),
            "stats": candidate_stats,
        }

        if manifest is not None and resolved_manifest is not None:
            manifest["candidate_lane_ingest"] = {
                "status": result["status"],
                "completed_at": _utc_now_iso(),
                "queue_path": str(resolved_queue_path),
                "source_quality_profile": source_quality_profile,
                "create_missing_targets": bool(create_missing_targets),
                "stats": candidate_stats,
            }
            resolved_manifest.write_text(
                json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
            )
            result["manifest_path"] = str(resolved_manifest)

        return result

    def _default_run_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{DEFAULT_RUN_PREFIX}-{stamp}"

    def _load_publications(
        self,
        *,
        limit: int,
        offset: int,
        use_cache_fallback: bool,
    ) -> tuple[list[PublicationSeed], dict[str, Any]]:
        publications = self._query_publications(limit=limit, offset=offset)
        if publications:
            source_info: dict[str, Any] = {
                "source": "neo4j",
                "count": len(publications),
            }
            if use_cache_fallback:
                publications, enrich_stats = self._enrich_publications_from_cache(
                    publications
                )
                source_info["cache_enrichment"] = enrich_stats
            return publications, source_info

        if use_cache_fallback:
            cached = self._load_cached_publications(limit=limit, offset=offset)
            if cached:
                return cached, {
                    "source": "scholarly_metadata_cache",
                    "cache_dir": str(self.cache_dir.resolve()),
                    "count": len(cached),
                }

        return [], {"source": "none", "count": 0}

    def _load_publications_from_pubget(
        self,
        *,
        extracted_dir: Path | str,
        limit: int,
        offset: int,
        include_body: bool,
        body_char_limit: int,
    ) -> tuple[list[PublicationSeed], dict[str, Any]]:
        extracted_path = Path(extracted_dir).expanduser().resolve()
        metadata_csv = extracted_path / "metadata.csv"
        text_csv = extracted_path / "text.csv"
        coordinates_csv = extracted_path / "coordinates.csv"
        coordinate_space_csv = extracted_path / "coordinate_space.csv"

        if not metadata_csv.exists():
            raise FileNotFoundError(f"Missing file: {metadata_csv}")
        if not text_csv.exists():
            raise FileNotFoundError(f"Missing file: {text_csv}")

        _configure_csv_field_size_limit()

        metadata_by_pmcid: dict[str, dict[str, Any]] = {}
        with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pmcid = _normalize_pmcid(row.get("pmcid"))
                if not pmcid:
                    continue
                metadata_by_pmcid[pmcid] = {
                    "pmid": _normalize_pmid(row.get("pmid")),
                    "doi": _normalize_doi(row.get("doi")),
                    "title": _clean_text(row.get("title")),
                    "journal": _clean_text(row.get("journal")),
                    "year": _coerce_int(row.get("publication_year") or row.get("year")),
                }

        coordinate_counts_by_pmcid: dict[str, int] = {}
        if coordinates_csv.exists():
            with coordinates_csv.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    pmcid = _normalize_pmcid(row.get("pmcid"))
                    if not pmcid:
                        continue
                    coordinate_counts_by_pmcid[pmcid] = (
                        int(coordinate_counts_by_pmcid.get(pmcid, 0)) + 1
                    )

        coordinate_space_by_pmcid: dict[str, str] = {}
        if coordinate_space_csv.exists():
            with coordinate_space_csv.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    pmcid = _normalize_pmcid(row.get("pmcid"))
                    if not pmcid:
                        continue
                    coord_space = _clean_text(row.get("coordinate_space"))
                    if coord_space:
                        coordinate_space_by_pmcid[pmcid] = coord_space

        text_rows = 0
        seeds_by_id: dict[str, PublicationSeed] = {}
        with text_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                text_rows += 1
                pmcid = _normalize_pmcid(row.get("pmcid"))
                metadata = metadata_by_pmcid.get(pmcid or "", {})

                pmid = _normalize_pmid(row.get("pmid")) or _normalize_pmid(
                    metadata.get("pmid")
                )
                doi = _normalize_doi(row.get("doi")) or _normalize_doi(
                    metadata.get("doi")
                )
                title = _clean_text(row.get("title")) or _clean_text(
                    metadata.get("title")
                )
                keywords = _clean_text(row.get("keywords")) or ""
                abstract = _clean_text(row.get("abstract")) or ""
                body = _clean_text(row.get("body")) or ""
                if include_body and body_char_limit > 0 and body:
                    body = body[:body_char_limit]
                elif not include_body:
                    body = ""

                year = _coerce_int(
                    row.get("publication_year") or row.get("year")
                ) or _coerce_int(metadata.get("year"))
                journal = _clean_text(row.get("journal")) or _clean_text(
                    metadata.get("journal")
                )

                if pmid:
                    paper_id = f"pmid:{pmid}"
                elif doi:
                    paper_id = f"doi:{doi}"
                elif pmcid:
                    paper_id = f"pmcid:{pmcid}"
                else:
                    paper_id = _normalize_paper_id(
                        None,
                        pmid=None,
                        doi=None,
                        title=(title or abstract or "unknown"),
                    )

                resolved_title = title or _first_sentence(abstract) or paper_id
                if not resolved_title and not abstract and not body:
                    continue

                seed = PublicationSeed(
                    paper_id=paper_id,
                    title=resolved_title,
                    abstract=abstract,
                    pmid=pmid,
                    doi=doi,
                    pmcid=pmcid,
                    year=year,
                    journal=journal,
                    keywords=keywords,
                    body=body,
                    coordinate_space=(
                        coordinate_space_by_pmcid.get(pmcid) if pmcid else None
                    ),
                    coordinate_count=(
                        coordinate_counts_by_pmcid.get(pmcid) if pmcid else None
                    ),
                    source="pubget_extracted_data",
                )
                current = seeds_by_id.get(paper_id)
                if current is None or self._publication_richness(
                    seed
                ) > self._publication_richness(current):
                    seeds_by_id[paper_id] = seed

        publications = list(seeds_by_id.values())
        publications.sort(
            key=lambda item: (
                item.year if item.year is not None else -1,
                item.paper_id,
            ),
            reverse=True,
        )

        if offset > 0:
            publications = publications[offset:]
        if limit > 0:
            publications = publications[:limit]

        source_info = _clean_none(
            {
                "source": "pubget_extracted_data",
                "count": len(publications),
                "extracted_dir": str(extracted_path),
                "metadata_csv": str(metadata_csv),
                "text_csv": str(text_csv),
                "coordinates_csv": (
                    str(coordinates_csv) if coordinates_csv.exists() else None
                ),
                "coordinate_space_csv": (
                    str(coordinate_space_csv) if coordinate_space_csv.exists() else None
                ),
                "records_text_rows": text_rows,
                "records_metadata_rows": len(metadata_by_pmcid),
                "records_unique_publications": len(seeds_by_id),
                "include_body": bool(include_body),
                "body_char_limit": int(body_char_limit),
            }
        )
        return publications, source_info

    @staticmethod
    def _publication_richness(seed: PublicationSeed) -> int:
        return (
            len(seed.title)
            + len(seed.abstract)
            + len(seed.keywords or "")
            + len(seed.body or "")
        )

    def _enrich_publications_from_cache(
        self,
        publications: list[PublicationSeed],
    ) -> tuple[list[PublicationSeed], dict[str, Any]]:
        """Fill missing abstract/year/journal fields from cache for Neo4j seeds."""

        needing_cache: set[str] = set()
        for publication in publications:
            if not publication.doi:
                continue
            needs_text = not bool(publication.abstract.strip())
            needs_meta = publication.year is None or not publication.journal
            if needs_text or needs_meta:
                needing_cache.add(publication.doi)

        if not needing_cache:
            return publications, {
                "dois_considered": 0,
                "dois_matched": 0,
                "publications_enriched": 0,
            }

        cache_index = self._load_cache_seed_index_for_dois(needing_cache)
        if not cache_index:
            return publications, {
                "dois_considered": len(needing_cache),
                "dois_matched": 0,
                "publications_enriched": 0,
            }

        enriched_publications: list[PublicationSeed] = []
        enriched_count = 0
        matched_dois = 0

        for publication in publications:
            cached = cache_index.get(publication.doi or "")
            if cached is None:
                enriched_publications.append(publication)
                continue

            matched_dois += 1
            abstract = publication.abstract or cached.abstract
            year = publication.year if publication.year is not None else cached.year
            journal = publication.journal or cached.journal
            source = publication.source

            if (
                abstract != publication.abstract
                or year != publication.year
                or journal != publication.journal
            ):
                enriched_count += 1
                source = f"{publication.source}+cache"

            enriched_publications.append(
                PublicationSeed(
                    paper_id=publication.paper_id,
                    title=publication.title,
                    abstract=abstract,
                    pmid=publication.pmid,
                    doi=publication.doi,
                    year=year,
                    journal=journal,
                    source=source,
                )
            )

        return enriched_publications, {
            "dois_considered": len(needing_cache),
            "dois_matched": matched_dois,
            "publications_enriched": enriched_count,
        }

    def _load_cache_seed_index_for_dois(
        self,
        dois: set[str],
    ) -> dict[str, PublicationSeed]:
        """Read only cache records matching requested DOIs."""

        if not dois or not self.cache_dir.exists():
            return {}

        files = sorted(
            path
            for path in self.cache_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".ndjson"}
        )

        resolved: dict[str, PublicationSeed] = {}
        remaining = set(dois)

        for metadata_file in files:
            if not remaining:
                break
            for record in _iter_metadata_records(metadata_file):
                if not isinstance(record, dict):
                    continue
                doi = _normalize_doi(record.get("doi") or record.get("DOI"))
                if not doi or doi not in remaining:
                    continue
                seed = self._publication_from_metadata_record(record)
                if seed is None:
                    continue
                resolved[doi] = seed
                remaining.discard(doi)

        return resolved

    def _query_publications(self, *, limit: int, offset: int) -> list[PublicationSeed]:
        limit_clause = "LIMIT $limit" if limit > 0 else ""
        query = f"""
        MATCH (p:Publication)
        RETURN
            coalesce(p.id, '') AS paper_id,
            p.pmid AS pmid,
            p.doi AS doi,
            coalesce(p.title, p.name, '') AS title,
            coalesce(
                p.abstract,
                p.summary,
                p.description,
                ''
            ) AS abstract,
            coalesce(p.year, p.publication_year) AS year,
            coalesce(p.journal, p.source) AS journal
        ORDER BY
            coalesce(toInteger(p.year), toInteger(p.publication_year), 0) DESC,
            coalesce(p.id, p.doi, p.pmid, p.title, '')
        SKIP $offset
        {limit_clause}
        """

        db = None
        try:
            db = require_neo4j_db(preload_cache=False)
            params: dict[str, Any] = {"offset": int(offset)}
            if limit > 0:
                params["limit"] = int(limit)
            rows = db.execute_query(query, params)
        except Exception as exc:
            logger.warning("Neo4j publication query failed: %s", exc)
            return []
        finally:
            if db is not None:
                db.close()

        seen_ids: set[str] = set()
        publications: list[PublicationSeed] = []
        for row in rows:
            title = str(row.get("title") or "").strip()
            doi = _normalize_doi(row.get("doi"))
            pmid = _normalize_pmid(row.get("pmid"))
            paper_id = _normalize_paper_id(
                row.get("paper_id"),
                pmid=pmid,
                doi=doi,
                title=title,
            )
            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)

            publications.append(
                PublicationSeed(
                    paper_id=paper_id,
                    title=title or paper_id,
                    abstract=str(row.get("abstract") or "").strip(),
                    pmid=pmid,
                    doi=doi,
                    year=_coerce_int(row.get("year")),
                    journal=_clean_text(row.get("journal")),
                    source="neo4j",
                )
            )
        return publications

    def _load_cached_publications(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[PublicationSeed]:
        if not self.cache_dir.exists():
            logger.warning("Scholarly cache directory not found: %s", self.cache_dir)
            return []

        loader = ScholarlyMetadataLoader(cache_dir=str(self.cache_dir))
        files = sorted(
            path
            for path in self.cache_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".ndjson"}
        )

        seeds_by_key: dict[str, PublicationSeed] = {}

        for metadata_file in files:
            try:
                records = loader.load_records(metadata_path=str(metadata_file))
            except Exception:
                logger.debug(
                    "Failed to parse cache file: %s", metadata_file, exc_info=True
                )
                continue

            if isinstance(records, dict):
                iterable_records = [records]
            elif isinstance(records, list):
                iterable_records = records
            else:
                iterable_records = []

            for record in iterable_records:
                if not isinstance(record, dict):
                    continue
                seed = self._publication_from_metadata_record(record)
                if seed is None:
                    continue
                dedupe_key = seed.doi or seed.paper_id
                if dedupe_key not in seeds_by_key:
                    seeds_by_key[dedupe_key] = seed

        seeds = list(seeds_by_key.values())
        seeds.sort(
            key=lambda item: (
                item.year if item.year is not None else -1,
                item.paper_id,
            ),
            reverse=True,
        )

        if limit <= 0:
            return seeds[offset:]
        return seeds[offset : offset + limit]

    def _publication_from_metadata_record(
        self, record: dict[str, Any]
    ) -> PublicationSeed | None:
        title = _extract_title(record)
        doi = _normalize_doi(record.get("doi") or record.get("DOI"))
        if not title and not doi:
            return None

        pmid = _normalize_pmid(record.get("pmid"))
        abstract = (
            _clean_text(record.get("abstract"))
            or _openalex_abstract_to_text(record.get("abstract_inverted_index"))
            or ""
        )
        year = _extract_year(record)
        journal = _extract_journal(record)
        paper_id = _normalize_paper_id(
            record.get("id") or record.get("paper_id"),
            pmid=pmid,
            doi=doi,
            title=title,
        )
        return PublicationSeed(
            paper_id=paper_id,
            title=title or paper_id,
            abstract=abstract,
            pmid=pmid,
            doi=doi,
            year=year,
            journal=journal,
            source="scholarly_cache",
        )

    def _build_prompt(self, publication: PublicationSeed) -> str:
        schema = PROMPT_TEMPLATE.replace(
            "{max_records}",
            str(self.max_records_per_publication),
        )
        payload = json.dumps(
            publication.to_prompt_payload(), ensure_ascii=True, indent=2
        )
        return (
            f"{schema}\n\n"
            f"Publication metadata:\n{payload}\n\n"
            "Return strict JSON now. Do not include markdown fences, comments, prose, or trailing commas."
        )

    def _generate_publication_records(
        self,
        *,
        publication: PublicationSeed,
        prompt: str,
        prompt_hash: str,
        force_heuristic: bool,
    ) -> tuple[list[dict[str, Any]], str, str, dict[str, Any], str | None, str | None]:
        use_llm = self._can_use_llm(force_heuristic=force_heuristic)
        if use_llm:
            attempts = self._llm_retry_limit()
            last_error: Exception | None = None
            last_response_text = ""
            last_response_meta: dict[str, Any] = {}
            failure_reason: str | None = None
            llm_prompt = prompt

            for attempt_index in range(1, attempts + 1):
                try:
                    result = self.router.route_chat(
                        prompt=llm_prompt,
                        model_hint=self.model_hint,
                        strict_json=True,
                    )
                    last_response_text = result.text or ""
                    last_response_meta = {
                        "provider": result.metadata.provider,
                        "model": result.metadata.model,
                        "route": result.metadata.route,
                        "transport": result.metadata.transport,
                        "fallback_reason": result.metadata.fallback_reason,
                        "usage": result.metadata.usage or {},
                        "prompt_hash": prompt_hash,
                        "attempt": attempt_index,
                        "attempts": attempts,
                    }

                    payload = self._parse_json_payload(last_response_text)
                    records = self._extract_records(payload)
                    if not records:
                        raise ValueError("LLM returned zero records")

                    return (
                        records,
                        "llm",
                        last_response_text,
                        last_response_meta,
                        None,
                        None,
                    )
                except Exception as exc:
                    last_error = exc
                    failure_reason = self._classify_llm_failure(exc)
                    logger.warning(
                        "Falling back to heuristic extraction for %s (attempt %s/%s): %s",
                        publication.paper_id,
                        attempt_index,
                        attempts,
                        exc,
                    )
                    if attempt_index < attempts and self._is_retryable_failure(
                        failure_reason
                    ):
                        llm_prompt = self._build_retry_prompt(
                            prompt=prompt,
                            attempt=attempt_index + 1,
                            failure_reason=failure_reason,
                        )
                        continue
                    break

            heuristic = self._heuristic_record(publication)
            fallback_meta = {
                "provider": "heuristic",
                "model": "heuristic-fallback",
                "route": "local",
                "transport": "python",
                "usage": {},
                "prompt_hash": prompt_hash,
                "attempts": attempts,
                "failure_reason": failure_reason,
            }
            if last_response_meta:
                fallback_meta["last_llm_meta"] = last_response_meta
            return (
                [heuristic],
                "heuristic",
                last_response_text,
                fallback_meta,
                str(last_error) if last_error else None,
                failure_reason,
            )

        heuristic = self._heuristic_record(publication)
        return (
            [heuristic],
            "heuristic",
            "",
            {
                "provider": "heuristic",
                "model": "heuristic-fallback",
                "route": "local",
                "transport": "python",
                "usage": {},
                "prompt_hash": prompt_hash,
            },
            None,
            "forced_heuristic",
        )

    def _can_use_llm(self, *, force_heuristic: bool) -> bool:
        if force_heuristic:
            return False

        if self.model_hint and self.model_hint.lower() in {
            "none",
            "off",
            "heuristic",
            "heuristic-fallback",
        }:
            return False

        if os.environ.get("USE_GEMINI_CLI", "true").lower() in {"1", "true", "yes"}:
            return True

        key_envs = (
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
        )
        return any(bool(os.environ.get(name)) for name in key_envs)

    def _parse_json_payload(self, response_text: str) -> Any:
        candidate = response_text.strip()
        if not candidate:
            raise ValueError("LLM returned empty response")

        parse_errors: list[json.JSONDecodeError] = []
        for raw_candidate in self._json_parse_candidates(candidate):
            cleaned = self._normalize_json_candidate(raw_candidate)
            if not cleaned:
                continue
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                parse_errors.append(exc)

        if parse_errors:
            raise parse_errors[-1]
        raise ValueError("Failed to parse JSON payload")

    def _json_parse_candidates(self, response_text: str) -> list[str]:
        candidates: list[str] = []

        def add(value: str) -> None:
            candidate = value.strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        stripped = response_text.strip().lstrip("\ufeff")
        add(stripped)

        for match in re.findall(
            r"```(?:json)?\s*(.*?)```",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            add(match)

        without_fences = re.sub(r"```(?:json)?", "", stripped, flags=re.IGNORECASE)
        without_fences = without_fences.replace("```", "").strip()
        add(without_fences)

        for base in list(candidates):
            add(
                re.sub(
                    r"^\s*(?:json|response|output|answer)\s*[:：]\s*",
                    "",
                    base,
                    flags=re.IGNORECASE,
                )
            )
            object_block = _extract_balanced_json_block(base, "{", "}")
            if object_block:
                add(object_block)
            array_block = _extract_balanced_json_block(base, "[", "]")
            if array_block:
                add(array_block)

        return candidates

    def _normalize_json_candidate(self, candidate: str) -> str:
        cleaned = candidate.strip()
        cleaned = re.sub(
            r"^\s*(?:json|response|output|answer)\s*[:：]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        return cleaned.strip()

    def _llm_retry_limit(self) -> int:
        if self.model_hint and "gemini" in self.model_hint.lower():
            return 2
        if not self.model_hint and os.environ.get("USE_GEMINI_CLI", "true").lower() in {
            "1",
            "true",
            "yes",
        }:
            return 2
        return 1

    def _build_retry_prompt(
        self, *, prompt: str, attempt: int, failure_reason: str
    ) -> str:
        return (
            f"{prompt}\n\n"
            "Your previous response was not valid strict JSON.\n"
            f"Retry attempt: {attempt}. Failure reason: {failure_reason}.\n"
            "Return JSON only with the required top-level schema and `records` array. "
            "Do not include markdown fences, explanations, or trailing commas."
        )

    def _classify_llm_failure(self, exc: Exception) -> str:
        if isinstance(exc, json.JSONDecodeError):
            return "parse_error"

        message = str(exc).lower()
        if "empty response" in message:
            return "empty_response"
        if "zero records" in message or "no records" in message:
            return "zero_records"
        if "json" in message and ("decode" in message or "parse" in message):
            return "parse_error"
        if "quota" in message or "rate" in message or "429" in message:
            return "quota_or_rate_limit"
        if "timeout" in message:
            return "timeout"
        return "llm_error"

    def _is_retryable_failure(self, failure_reason: str | None) -> bool:
        return failure_reason in {"parse_error", "empty_response", "zero_records"}

    def _extract_records(self, payload: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        raw_records: list[Any]

        if isinstance(payload, dict):
            if isinstance(payload.get("records"), list):
                raw_records = payload["records"]
            elif isinstance(payload.get("measurements"), list):
                raw_records = payload["measurements"]
            elif all(key in payload for key in ("target", "claim", "evidence")):
                raw_records = [payload]
            else:
                raw_records = []
        elif isinstance(payload, list):
            raw_records = payload
        else:
            raw_records = []

        for item in raw_records[: self.max_records_per_publication]:
            if isinstance(item, dict):
                records.append(item)
        return records

    def _heuristic_record(self, publication: PublicationSeed) -> dict[str, Any]:
        text = _publication_blob(publication).lower()
        title_lower = publication.title.lower()
        abstract_lower = f"{publication.abstract} {publication.body}".lower()

        target_type = "Concept"
        target_label = "Cognitive Control"
        target_id = "concept:cognitive_control"
        trigger = "cognitive control"
        ontology_match = False
        mapping_confidence = 0.55

        region_hit = _first_rule_hit(text, REGION_RULES)
        task_hit = _first_rule_hit(text, TASK_RULES)
        concept_hit = _first_rule_hit(text, CONCEPT_RULES)

        if region_hit:
            target_type = "Region"
            target_label = region_hit[1]
            target_id = region_hit[2]
            trigger = region_hit[0]
            ontology_match = True
            mapping_confidence = 0.88
        elif task_hit:
            target_type = "Task"
            target_label = task_hit[1]
            target_id = task_hit[2]
            trigger = task_hit[0]
            ontology_match = True
            mapping_confidence = 0.84
        elif concept_hit:
            target_type = "Concept"
            target_label = concept_hit[1]
            target_id = concept_hit[2]
            trigger = concept_hit[0]
            ontology_match = True
            mapping_confidence = 0.80

        grounded_quote, grounded_section, grounded = _best_grounded_quote(
            publication,
            trigger=trigger,
            target_label=target_label,
        )
        if grounded:
            quote = grounded_quote
            section = grounded_section
        else:
            target_type = "Concept"
            target_label = "Cognitive Control"
            target_id = "concept:cognitive_control"
            trigger = "cognitive control"
            ontology_match = False
            mapping_confidence = 0.30
            quote = (
                _first_sentence(publication.abstract)
                or _first_sentence(publication.body)
                or publication.title
                or target_label
            )
            section = (
                "abstract"
                if publication.abstract
                else ("unknown" if publication.body else "title")
            )

        quote_lower = quote.lower()
        has_stats = bool(STAT_DETAIL_PATTERN.search(quote))
        mention_frequency = max(1, min(5, text.count(trigger)))
        title_hit = trigger in title_lower if trigger else False
        abstract_hit = trigger in abstract_lower if trigger else False

        polarity = "supports"
        if not grounded:
            polarity = "uncertain"
        elif any(token in quote_lower for token in NEGATIVE_CLAIM_TOKENS):
            polarity = "refutes"
        elif any(token in quote_lower for token in UNCERTAIN_TOKENS):
            polarity = "uncertain"

        uncertain = polarity == "uncertain"
        claim_strength = 0.35 if not grounded else (0.52 if uncertain else 0.72)
        modal_density = 0.82 if uncertain else 0.24
        assertive_ratio = 0.18 if uncertain else 0.63
        stat_density = 0.72 if has_stats else (0.18 if not grounded else 0.32)
        sample_size = 0.30 if not grounded else (0.66 if has_stats else 0.45)

        claim_text = (
            _clean_text(quote)
            if grounded
            else f"Manual review required to confirm a grounded claim about {target_label}."
        )
        claim_kind = _infer_claim_kind(quote_lower)
        assumption_meta = _infer_assumption_metadata(
            text=quote,
            target_label=target_label,
            claim_kind=claim_kind,
            grounded=grounded,
        )
        title_only_evidence = section == "title"
        section_level_evidence = section in {
            "abstract",
            "methods",
            "results",
            "discussion",
        }
        unverifiable_snippet = section == "unknown" and not has_stats and not grounded

        return {
            "target": {
                "type": target_type,
                "id": target_id,
                "label": target_label,
                "atlas": None,
            },
            "mapping": {
                "canonical_id": target_id,
                "mapping_type": "exact" if ontology_match else "unknown",
                "mapping_confidence": mapping_confidence,
            },
            "claim": {
                "text": claim_text,
                "polarity": polarity,
                "claim_strength": claim_strength,
                "claim_kind": claim_kind,
                "main_assumption_text": assumption_meta["main_assumption_text"],
                "assumption_type": assumption_meta["assumption_type"],
                "assumption_scope": assumption_meta["assumption_scope"],
                "defaultness_score": assumption_meta["defaultness_score"],
                "challengeability_score": assumption_meta["challengeability_score"],
                "assumption_confidence": assumption_meta["assumption_confidence"],
                "assumption_status": assumption_meta["assumption_status"],
            },
            "evidence": {
                "quote": quote,
                "section": section,
                "page": None,
                "char_start": None,
                "char_end": None,
                "has_statistical_detail": has_stats,
                "locatable": section != "unknown",
                "direct_quote": True,
            },
            "method": self._heuristic_method(
                publication=publication,
                quote=quote,
                section=section,
                target_type=target_type,
                grounded=grounded,
            ),
            "signals": {
                "mention_frequency": mention_frequency,
                "max_frequency": 5,
                "title_hit": title_hit,
                "abstract_hit": abstract_hit,
                "semantic_similarity": mapping_confidence,
                "ontology_match": ontology_match,
                "context_overlap": 0.68 if ontology_match else 0.35,
                "modal_density": modal_density,
                "statistical_density": stat_density,
                "assertive_verb_ratio": assertive_ratio,
                "preregistration": False,
                "threshold_correction_reported": has_stats,
                "sample_size_adequacy": sample_size,
                "roi_definition_clear": target_type == "Region",
                "operationalization_clear": (
                    grounded if target_type in {"Task", "Concept"} else None
                ),
                "open_data_or_code": False,
                "grounded_trigger_match": grounded,
                "title_only_evidence": title_only_evidence,
                "section_level_evidence": section_level_evidence,
                "unverifiable_snippet": unverifiable_snippet,
            },
        }

    def _finalize_record(
        self,
        *,
        publication: PublicationSeed,
        base_record: dict[str, Any],
        run_id: str,
        raw_response_path: str,
        prompt_hash: str,
        template_hash: str,
        model_name: str,
        timestamp: str,
        measurement_index: int,
    ) -> dict[str, Any]:
        target = self._normalize_target(base_record.get("target"))
        mapping = self._normalize_mapping(base_record.get("mapping"), target["id"])
        claim = self._normalize_claim(
            base_record.get("claim"),
            paper_id=publication.paper_id,
            target_id=target["id"],
            measurement_index=measurement_index,
        )
        evidence = self._normalize_evidence(
            base_record.get("evidence"),
            claim_id=claim["id"],
            publication=publication,
            measurement_index=measurement_index,
        )
        method = self._normalize_method(
            base_record.get("method"),
            raw_signals=base_record.get("signals"),
            publication=publication,
        )
        signals = self._normalize_signals(
            base_record.get("signals"),
            target_label=target["label"],
            publication=publication,
            evidence=evidence,
            mapping_confidence=_clamp01(
                mapping.get("mapping_confidence"), default=0.55
            ),
            method=method,
        )
        mapping, claim, evidence, signals = self._apply_evidence_depth_guards(
            publication=publication,
            mapping=mapping,
            claim=claim,
            evidence=evidence,
            signals=signals,
        )

        prov = {
            "run_id": run_id,
            "prompt_hash": prompt_hash,
            "template_hash": template_hash,
            "model": model_name,
            "raw_response_path": raw_response_path,
            "loader_version": LOADER_VERSION,
            "timestamp": timestamp,
        }

        return {
            "run": {
                "run_id": run_id,
                "tool": "extract",
                "model": model_name,
                "prompt_hash": prompt_hash,
                "template_hash": template_hash,
                "raw_response_path": raw_response_path,
                "loader_version": LOADER_VERSION,
                "timestamp": timestamp,
                "status": "completed",
            },
            "paper": publication.to_record_paper(),
            "target": target,
            "mapping": mapping,
            "claim": claim,
            "evidence": evidence,
            "method": method,
            "signals": signals,
            "prov": prov,
            "timestamp": timestamp,
            "prompt_hash": prompt_hash,
            "template_hash": template_hash,
            "model": model_name,
            "raw_response_path": raw_response_path,
        }

    def _apply_evidence_depth_guards(
        self,
        *,
        publication: PublicationSeed,
        mapping: dict[str, Any],
        claim: dict[str, Any],
        evidence: dict[str, Any],
        signals: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        title_only_evidence = _is_title_only_evidence(publication, evidence)
        has_non_title_text = bool(publication.abstract or publication.body)
        unverifiable_snippet = (
            not bool(evidence.get("locatable"))
            and not bool(evidence.get("direct_quote"))
            and not bool(evidence.get("has_statistical_detail"))
        )

        signals["title_only_evidence"] = title_only_evidence
        signals["section_level_evidence"] = evidence.get("section") in {
            "abstract",
            "methods",
            "results",
            "discussion",
        }
        signals["unverifiable_snippet"] = unverifiable_snippet

        if title_only_evidence and has_non_title_text:
            evidence["locatable"] = False
            mapping["mapping_confidence"] = min(
                _clamp01(mapping.get("mapping_confidence"), default=0.35), 0.35
            )
            claim["claim_strength"] = min(
                _clamp01(claim.get("claim_strength"), default=0.35), 0.35
            )
            signals["semantic_similarity"] = min(
                _clamp01(signals.get("semantic_similarity"), default=0.35), 0.35
            )
            signals["context_overlap"] = min(
                _clamp01(signals.get("context_overlap"), default=0.25), 0.25
            )
            signals["statistical_density"] = min(
                _clamp01(signals.get("statistical_density"), default=0.05), 0.05
            )
            signals["assertive_verb_ratio"] = min(
                _clamp01(signals.get("assertive_verb_ratio"), default=0.15), 0.15
            )
            signals["modal_density"] = max(
                _clamp01(signals.get("modal_density"), default=0.80), 0.80
            )

        return mapping, claim, evidence, signals

    def _normalize_target(self, value: Any) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        raw_type = str(payload.get("type") or "Concept")
        norm_type = raw_type.strip().lower()
        if norm_type in {"region", "brainregion"}:
            target_type = "Region"
            prefix = "region"
        elif norm_type in {"task", "paradigm", "taskparadigm"}:
            target_type = "Task"
            prefix = "task"
        else:
            target_type = "Concept"
            prefix = "concept"

        label = _clean_text(payload.get("label") or payload.get("name")) or "Unknown"
        target_id = _clean_text(payload.get("id"))
        if target_id:
            if ":" not in target_id:
                target_id = f"{prefix}:{_slugify(target_id)}"
        else:
            target_id = f"{prefix}:{_slugify(label)}"

        normalized: dict[str, Any] = {
            "type": target_type,
            "id": target_id,
            "label": label,
        }
        atlas = _clean_text(payload.get("atlas"))
        if atlas:
            normalized["atlas"] = atlas
        return normalized

    def _normalize_mapping(self, value: Any, target_id: str) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        canonical_id = _clean_text(payload.get("canonical_id")) or target_id
        mapping_type = _clean_text(payload.get("mapping_type")) or (
            "exact" if canonical_id == target_id else "related"
        )
        return {
            "canonical_id": canonical_id,
            "mapping_type": mapping_type,
            "mapping_confidence": _clamp01(
                payload.get("mapping_confidence"),
                default=0.85 if mapping_type == "exact" else 0.60,
            ),
        }

    def _normalize_claim(
        self,
        value: Any,
        *,
        paper_id: str,
        target_id: str,
        measurement_index: int,
    ) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        claim_text = (
            _clean_text(payload.get("text"))
            or _clean_text(payload.get("claim_text"))
            or f"Claim extracted for {paper_id} and {target_id}."
        )
        claim_id = _clean_text(payload.get("id")) or _clean_text(
            payload.get("claim_id")
        )
        if not claim_id:
            claim_id = _claim_id(paper_id, target_id, claim_text, measurement_index)
        elif ":" not in claim_id:
            claim_id = f"claim:{_slugify(claim_id)}"

        return {
            "id": claim_id,
            "text": claim_text,
            "polarity": _normalize_polarity(payload.get("polarity")),
            "claim_strength": _clamp01(payload.get("claim_strength"), default=0.60),
            "claim_kind": _normalize_claim_kind(payload.get("claim_kind")),
            "related_claim_id": _clean_text(payload.get("related_claim_id")),
            "main_assumption_text": _clean_text(payload.get("main_assumption_text")),
            "main_assumption_id": _clean_text(payload.get("main_assumption_id")),
            "assumption_type": _clean_text(payload.get("assumption_type")),
            "assumption_scope": _clean_text(payload.get("assumption_scope")),
            "defaultness_score": _clamp01(
                payload.get("defaultness_score"),
                default=0.55,
            ),
            "challengeability_score": _clamp01(
                payload.get("challengeability_score"),
                default=0.45,
            ),
            "assumption_confidence": _clamp01(
                payload.get("assumption_confidence"),
                default=0.45,
            ),
            "assumption_status": _normalize_assumption_status(
                payload.get("assumption_status")
            ),
        }

    def _normalize_evidence(
        self,
        value: Any,
        *,
        claim_id: str,
        publication: PublicationSeed,
        measurement_index: int,
    ) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        quote = (
            _clean_text(payload.get("quote"))
            or _clean_text(payload.get("text"))
            or _first_sentence(publication.abstract)
            or _first_sentence(publication.body)
            or publication.title
            or "(no evidence quote provided)"
        )
        span_id = _clean_text(payload.get("span_id")) or _clean_text(payload.get("id"))
        if not span_id:
            span_id = _evidence_id(claim_id, quote, measurement_index)
        elif ":" not in span_id:
            span_id = f"evidence:{_slugify(span_id)}"

        section = _clean_text(payload.get("section"))
        if not section:
            section = (
                "abstract"
                if publication.abstract
                else ("unknown" if publication.body else "title")
            )

        has_stats = _coerce_bool(payload.get("has_statistical_detail"), default=None)
        if has_stats is None:
            has_stats = bool(STAT_DETAIL_PATTERN.search(quote))

        locatable = _coerce_bool(
            payload.get("locatable"),
            default=bool(publication.abstract or publication.body),
        )
        direct_quote = _coerce_bool(payload.get("direct_quote"), default=False)

        return {
            "span_id": span_id,
            "quote": quote,
            "section": section,
            "page": _coerce_int(payload.get("page")),
            "char_start": _coerce_int(payload.get("char_start")),
            "char_end": _coerce_int(payload.get("char_end")),
            "has_statistical_detail": has_stats,
            "locatable": locatable,
            "direct_quote": direct_quote,
        }

    def _normalize_method(
        self,
        value: Any,
        *,
        raw_signals: Any,
        publication: PublicationSeed,
    ) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        signal_payload = raw_signals if isinstance(raw_signals, dict) else {}

        return {
            "preregistration": _normalize_method_boolean_block(
                payload.get("preregistration"),
                fallback=(
                    signal_payload.get("preregistration")
                    if "preregistration" in signal_payload
                    else None
                ),
                registry=_clean_text(payload.get("preregistration_registry"))
                or _clean_text(payload.get("registry")),
            ),
            "threshold_correction": _normalize_method_boolean_block(
                payload.get("threshold_correction"),
                fallback=(
                    signal_payload.get("threshold_correction_reported")
                    if "threshold_correction_reported" in signal_payload
                    else None
                ),
                extra_field_name="correction_type",
                extra_field_default=(
                    _clean_text(payload.get("correction_type"))
                    or _clean_text(payload.get("threshold_correction_type"))
                ),
            ),
            "sample_size": _normalize_method_sample_size_block(
                payload.get("sample_size"),
                publication=publication,
            ),
            "roi_definition": _normalize_method_roi_block(
                payload.get("roi_definition"),
                fallback=(
                    signal_payload.get("roi_definition_clear")
                    if "roi_definition_clear" in signal_payload
                    else None
                ),
            ),
            "operationalization": _normalize_method_roi_block(
                payload.get("operationalization"),
                fallback=(
                    signal_payload.get("operationalization_clear")
                    if "operationalization_clear" in signal_payload
                    else None
                ),
            ),
            "open_data_or_code": _normalize_method_open_block(
                payload.get("open_data_or_code"),
                fallback=(
                    signal_payload.get("open_data_or_code")
                    if "open_data_or_code" in signal_payload
                    else None
                ),
            ),
        }

    def _normalize_signals(
        self,
        value: Any,
        *,
        target_label: str,
        publication: PublicationSeed,
        evidence: dict[str, Any],
        mapping_confidence: float,
        method: dict[str, Any],
    ) -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        title_lower = publication.title.lower()
        abstract_lower = f"{publication.abstract} {publication.body}".lower()
        label_lower = target_label.lower()
        full_text = f"{title_lower} {publication.keywords.lower()} {abstract_lower}"

        mention_frequency = _coerce_int(payload.get("mention_frequency"))
        if mention_frequency is None:
            mention_frequency = max(1, min(5, full_text.count(label_lower)))

        max_frequency = _coerce_int(payload.get("max_frequency"))
        if max_frequency is None or max_frequency <= 0:
            max_frequency = 5

        title_hit = _coerce_bool(
            payload.get("title_hit"), default=label_lower in title_lower
        )
        abstract_hit = _coerce_bool(
            payload.get("abstract_hit"), default=label_lower in abstract_lower
        )

        statistical_density = _clamp01(
            payload.get("statistical_density"),
            default=0.72 if evidence.get("has_statistical_detail") else 0.30,
        )
        modal_density = _clamp01(
            payload.get("modal_density"),
            default=(
                0.75 if any(token in full_text for token in UNCERTAIN_TOKENS) else 0.25
            ),
        )

        assertive_default = (
            0.65 if any(token in full_text for token in ASSERTIVE_TOKENS) else 0.40
        )
        prereg_status = _method_block_status(method.get("preregistration"))
        threshold_status = _method_block_status(method.get("threshold_correction"))
        sample_size_block = (
            method.get("sample_size") if isinstance(method, dict) else {}
        )
        sample_size_status = _method_block_status(sample_size_block, default="unknown")
        sample_size_n = _coerce_int(
            sample_size_block.get("reported_n")
            if isinstance(sample_size_block, dict)
            else None
        )
        roi_status = _method_block_status(
            method.get("roi_definition"), default="unknown"
        )
        operationalization_status = _method_block_status(
            method.get("operationalization"),
            default="unknown",
        )
        open_block = method.get("open_data_or_code") if isinstance(method, dict) else {}
        open_status = _method_block_status(open_block, default="unknown")
        open_artifact = (
            _clean_text(
                open_block.get("artifact") if isinstance(open_block, dict) else None
            )
            or "unknown"
        )
        method_blocks = [
            method.get("sample_size", {}) if isinstance(method, dict) else {},
            method.get("threshold_correction", {}) if isinstance(method, dict) else {},
            method.get("operationalization", {}) if isinstance(method, dict) else {},
            method.get("roi_definition", {}) if isinstance(method, dict) else {},
            method.get("open_data_or_code", {}) if isinstance(method, dict) else {},
            method.get("preregistration", {}) if isinstance(method, dict) else {},
        ]
        method_quote = ""
        method_section = "unknown"
        for block in method_blocks:
            if not isinstance(block, dict):
                continue
            quote_candidate = _clean_text(block.get("quote"))
            section_candidate = _normalize_method_section(block.get("section"))
            if quote_candidate and not method_quote:
                method_quote = quote_candidate
                method_section = section_candidate or "unknown"
                break
            if method_section == "unknown" and section_candidate != "unknown":
                method_section = section_candidate

        prereg_default = (
            True
            if prereg_status == "yes"
            else (False if prereg_status == "no" else None)
        )
        threshold_default = (
            True
            if threshold_status == "yes"
            else (False if threshold_status == "no" else None)
        )
        roi_default = (
            True
            if roi_status == "clear"
            else (False if roi_status == "unclear" else None)
        )
        operationalization_default = (
            True
            if operationalization_status == "clear"
            else (False if operationalization_status == "unclear" else None)
        )
        open_default = (
            True if open_status == "yes" else (False if open_status == "no" else None)
        )

        return {
            "mention_frequency": mention_frequency,
            "max_frequency": max_frequency,
            "title_hit": title_hit,
            "abstract_hit": abstract_hit,
            "semantic_similarity": _clamp01(
                payload.get("semantic_similarity"),
                default=mapping_confidence,
            ),
            "ontology_match": _coerce_bool(
                payload.get("ontology_match"), default=mapping_confidence >= 0.80
            ),
            "context_overlap": _clamp01(
                payload.get("context_overlap"),
                default=0.70 if (publication.abstract or publication.body) else 0.35,
            ),
            "modal_density": modal_density,
            "statistical_density": statistical_density,
            "assertive_verb_ratio": _clamp01(
                payload.get("assertive_verb_ratio"),
                default=assertive_default,
            ),
            "preregistration": _coerce_bool(
                payload.get("preregistration"),
                default=prereg_default,
            ),
            "preregistration_status": prereg_status,
            "threshold_correction_reported": _coerce_bool(
                payload.get("threshold_correction_reported"),
                default=threshold_default,
            ),
            "threshold_correction_status": threshold_status,
            "threshold_correction_type": _clean_text(
                method.get("threshold_correction", {}).get("correction_type")
                if isinstance(method, dict)
                else None
            ),
            "sample_size_adequacy": _clamp01_optional(
                payload.get("sample_size_adequacy"),
                default=(
                    _sample_size_adequacy_from_n(sample_size_n)
                    if sample_size_status == "reported"
                    else None
                ),
            ),
            "sample_size_status": sample_size_status,
            "sample_size_reported_n": sample_size_n,
            "roi_definition_clear": _coerce_bool(
                payload.get("roi_definition_clear"),
                default=roi_default,
            ),
            "roi_definition_status": roi_status,
            "operationalization_clear": _coerce_bool(
                payload.get("operationalization_clear"),
                default=operationalization_default,
            ),
            "operationalization_status": operationalization_status,
            "open_data_or_code": _coerce_bool(
                payload.get("open_data_or_code"),
                default=open_default,
            ),
            "open_data_or_code_status": open_status,
            "open_data_or_code_artifact": open_artifact,
            "method_quote": method_quote or evidence.get("quote"),
            "method_section": (
                method_section
                if method_section != "unknown"
                else evidence.get("section", "unknown")
            ),
        }

    def _heuristic_method(
        self,
        *,
        publication: PublicationSeed,
        quote: str,
        section: str,
        target_type: str,
        grounded: bool,
    ) -> dict[str, Any]:
        prereg_quote, prereg_section = _first_matching_sentence(
            publication,
            PREREGISTRATION_PATTERN,
        )
        threshold_quote, threshold_section = _first_matching_sentence(
            publication,
            THRESHOLD_CORRECTION_PATTERN,
        )
        sample_quote, sample_section = _first_matching_sentence(
            publication,
            SAMPLE_SIZE_PATTERN,
        )
        open_quote, open_section = _first_matching_sentence(
            publication,
            OPEN_DATA_PATTERN,
        )
        operationalization_quote = (
            quote
            if grounded
            and target_type in {"Task", "Concept"}
            and section in {"abstract", "methods", "results", "discussion"}
            else None
        )

        sample_match = SAMPLE_SIZE_PATTERN.search(
            sample_quote or _publication_blob(publication)
        )
        sample_n = _sample_size_from_match(sample_match)

        return {
            "preregistration": {
                "status": "yes" if prereg_quote else "unknown",
                "quote": prereg_quote,
                "section": prereg_section if prereg_quote else "unknown",
                "registry": None,
            },
            "threshold_correction": {
                "status": "yes" if threshold_quote else "unknown",
                "quote": threshold_quote,
                "section": threshold_section if threshold_quote else "unknown",
                "correction_type": _infer_threshold_correction_type(threshold_quote),
            },
            "sample_size": {
                "status": "reported" if sample_n is not None else "unknown",
                "reported_n": sample_n,
                "quote": sample_quote,
                "section": sample_section if sample_n is not None else "unknown",
            },
            "roi_definition": {
                "status": (
                    "clear" if target_type == "Region" and grounded else "unknown"
                ),
                "quote": quote if target_type == "Region" and grounded else None,
                "section": (
                    section if target_type == "Region" and grounded else "unknown"
                ),
            },
            "operationalization": {
                "status": (
                    "clear"
                    if grounded and target_type in {"Task", "Concept"}
                    else "unknown"
                ),
                "quote": operationalization_quote,
                "section": section if operationalization_quote else "unknown",
            },
            "open_data_or_code": {
                "status": "yes" if open_quote else "unknown",
                "artifact": _infer_open_artifact(open_quote),
                "quote": open_quote,
                "section": open_section if open_quote else "unknown",
            },
        }


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _publication_blob(publication: PublicationSeed) -> str:
    chunks = [
        publication.title,
        publication.keywords,
        publication.abstract,
        publication.body,
    ]
    return " ".join(
        chunk.strip() for chunk in chunks if isinstance(chunk, str) and chunk.strip()
    )


def _normalize_doi(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    cleaned = text.lower().replace("https://doi.org/", "").replace("doi:", "")
    return cleaned.strip() or None


def _normalize_pmid(value: Any) -> str | None:
    text = _clean_text(value)
    return text if text else None


def _normalize_pmcid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.lower().replace("pmcid:", "").replace("pmc", "")
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized or None


def _extract_title(record: dict[str, Any]) -> str:
    title = record.get("title")
    if isinstance(title, str):
        return title.strip()
    if isinstance(title, list):
        chunks = [str(item).strip() for item in title if str(item).strip()]
        if chunks:
            return chunks[0]
    return ""


def _extract_journal(record: dict[str, Any]) -> str | None:
    direct = _clean_text(record.get("journal"))
    if direct:
        return direct

    container = record.get("container-title")
    if isinstance(container, list):
        first = next((str(item).strip() for item in container if str(item).strip()), "")
        if first:
            return first

    host_venue = record.get("host_venue")
    if isinstance(host_venue, dict):
        display_name = _clean_text(host_venue.get("display_name"))
        if display_name:
            return display_name

    return None


def _extract_year(record: dict[str, Any]) -> int | None:
    direct = _coerce_int(record.get("publication_year") or record.get("year"))
    if direct is not None:
        return direct

    issued = record.get("issued")
    if isinstance(issued, dict):
        date_parts = issued.get("date-parts")
        if isinstance(date_parts, list) and date_parts:
            first = date_parts[0]
            if isinstance(first, list) and first:
                return _coerce_int(first[0])
    return None


def _openalex_abstract_to_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return None

    position_to_token: dict[int, str] = {}
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for pos in positions:
            idx = _coerce_int(pos)
            if idx is None or idx < 0:
                continue
            position_to_token[idx] = token

    if not position_to_token:
        return None

    tokens = [position_to_token[idx] for idx in sorted(position_to_token.keys())]
    text = " ".join(tokens).strip()
    return text or None


def _normalize_paper_id(
    raw_id: Any,
    *,
    pmid: str | None,
    doi: str | None,
    title: str,
) -> str:
    paper_id = _clean_text(raw_id)
    if paper_id:
        if ":" in paper_id:
            return paper_id
        return f"paper:{_slugify(paper_id)}"

    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    return f"paper:{_slugify(title)}"


from brain_researcher.services.br_kg.etl.gabriel_claim_helpers import (  # noqa: F401,E402
    _best_grounded_quote,
    _claim_id,
    _content_tokens,
    _evidence_id,
    _first_rule_hit,
    _first_sentence,
    _infer_assumption_metadata,
    _infer_claim_kind,
    _is_title_only_evidence,
    _normalize_assumption_status,
    _normalize_claim_kind,
    _normalize_polarity,
    _sentence_candidates,
)
from brain_researcher.services.br_kg.etl.gabriel_method_normalizers import (  # noqa: F401,E402
    _coerce_bool,
    _first_matching_sentence,
    _infer_open_artifact,
    _infer_threshold_correction_type,
    _method_block_status,
    _normalize_method_boolean_block,
    _normalize_method_evidence_fields,
    _normalize_method_open_block,
    _normalize_method_roi_block,
    _normalize_method_sample_size_block,
    _normalize_method_section,
    _normalize_method_status,
    _sample_size_from_match,
)


def _configure_csv_field_size_limit() -> None:
    """Set CSV field size limit high enough for long full-text rows."""
    max_size = sys.maxsize
    while max_size > 0:
        try:
            csv.field_size_limit(max_size)
            return
        except OverflowError:
            max_size //= 10


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _iter_metadata_records(path: Path) -> Iterable[dict[str, Any]]:
    """Yield record-like objects from json/jsonl/ndjson cache files."""

    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        payload = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        yield payload
            return

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Failed to parse metadata file: %s", path, exc_info=True)
        return

    if isinstance(payload, dict):
        yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
