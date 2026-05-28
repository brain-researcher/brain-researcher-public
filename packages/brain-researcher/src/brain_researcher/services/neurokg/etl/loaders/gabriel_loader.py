"""Offline loader for GABRIEL-derived BR-KG measurements.

This loader ingests normalized JSONL records and materializes auditable
paper->evidence->claim->concept/region structures with high-precision gating.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from glob import glob
from pathlib import Path
from typing import Any

from .gabriel_measurements import (
    DEFAULT_HIGH_PRECISION_THRESHOLDS,
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    GabrielVariables,
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

logger = logging.getLogger(__name__)


def _candidate_lane_flag(props: Mapping[str, Any] | None) -> bool:
    if not isinstance(props, Mapping):
        return False
    value = props.get("candidate_lane_present")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}


class GabrielMeasurementLoader:
    """Load GABRIEL outputs into BR-KG."""

    TASK_EXACT_ID_PREFIXES = ("task:subfamily:", "task:family:")
    BENCHMARK_TITLE_ONLY_SUPPRESSION_PROFILES = {
        "high_precision",
        "balanced",
        "balanced_marginal",
    }
    TITLE_ONLY_GENERIC_CONCEPT_IDS = {
        "concept:fmri",
        "concept:fmri_study",
        "concept:eeg",
        "concept:simultaneous_eeg_fmri",
        "concept:multi_voxel_pattern_analysis",
        "concept:brain_activity",
        "concept:brain_atrophy",
        "concept:brain_functional_connectivity",
        "concept:brain_gray_matter_volume",
        "concept:effective_connectivity",
        "concept:functional_brain_networks",
        "concept:functional_connectivity",
        "concept:functional_connectivity_change_between_posterior_cingulate_cortex_and_ventral_attention_network",
        "concept:functional_connectivity_of_the_default_mode_and_left_frontoparietal_networks",
        "concept:functional_mri_activity",
        "concept:functional_neural_correlates",
        "concept:intrinsic_network_connectivity_patterns",
        "concept:neural_activation",
        "concept:neural_codes",
        "concept:neural_connectivity",
        "concept:neural_correlates",
        "concept:neural_correlates_of_sexual_preference_under_cognitive_demand",
        "concept:neural_processing_of_positive_and_negative_emotions",
        "concept:neural_representation_of_future_events",
        "concept:neural_response",
        "concept:regional_homogeneity",
        "concept:volitional_recall_of_motor_imagery_related_brain_activation_patterns",
    }
    DEFAULT_INPUT_PATH = "data/neurokg/raw/gabriel/measurements.jsonl"
    QUALITY_PROFILES = {
        "high_precision": dict(DEFAULT_HIGH_PRECISION_THRESHOLDS),
        "balanced": {
            "mention_strength_min": 0.60,
            "mapping_confidence_min": 0.75,
            "claim_strength_min": 0.55,
            "method_rigor_min": 0.40,
            "provenance_completeness_min": 0.80,
            "allow_low_evidence_quality": False,
        },
        "balanced_marginal": {
            # Slightly relaxed version of "balanced" for near-threshold
            # backfills where title/abstract signals understate rigor.
            "mention_strength_min": 0.55,
            "mapping_confidence_min": 0.75,
            "claim_strength_min": 0.50,
            "method_rigor_min": 0.35,
            "provenance_completeness_min": 0.80,
            "allow_low_evidence_quality": False,
        },
        "kg_bootstrap": {
            # Intended for first-pass backfills where many studies lack method detail
            # in title/abstract-only records. Downstream curation can tighten later.
            "mention_strength_min": 0.40,
            "mapping_confidence_min": 0.00,
            "claim_strength_min": 0.00,
            "method_rigor_min": 0.00,
            "provenance_completeness_min": 0.80,
            "allow_low_evidence_quality": True,
        },
        "kg_task_panel": {
            # Tuned for KGGEN->ONVOC task panel ingest where ontology mapping is
            # strongly constrained, but mention/method signals are often sparse.
            "mention_strength_min": 0.30,
            "mapping_confidence_min": 0.82,
            "claim_strength_min": 0.40,
            "method_rigor_min": 0.10,
            "provenance_completeness_min": 0.80,
            "allow_low_evidence_quality": True,
        },
    }
    FILE_STAT_KEYS = (
        "records_total",
        "records_parsed",
        "records_accepted",
        "records_rejected",
        "review_queue_items",
        "nodes_created",
        "relationships_created",
        "parse_errors",
    )
    CANDIDATE_QUEUE_STAT_KEYS = (
        "queue_rows_total",
        "queue_rows_loaded",
        "queue_rows_skipped",
        "overlay_conflicts",
        "nodes_created",
        "relationships_created",
        "parse_errors",
    )
    TOOL_TO_METHOD = {
        "codify": "llm_codify",
        "extract": "llm_extract",
        "merge": "llm_merge",
        "deduplicate": "llm_deduplicate",
    }

    def __init__(self, db, config: dict[str, Any] | None = None):
        self.db = db
        self.config = config or {}
        self.input_path = Path(self.config.get("input_path", self.DEFAULT_INPUT_PATH))
        raw_input_paths = self.config.get("input_paths")
        self.input_paths = (
            tuple(
                Path(path)
                for path in raw_input_paths
                if isinstance(path, str) and path.strip()
            )
            if isinstance(raw_input_paths, list | tuple)
            else ()
        )
        self.input_path_glob = (
            str(self.config.get("input_path_glob")).strip()
            if self.config.get("input_path_glob")
            else None
        )
        self.review_queue_path = Path(
            self.config.get(
                "review_queue_path", "data/neurokg/raw/gabriel/review_queue.jsonl"
            )
        )
        configured_candidate_only = self.config.get("candidate_only_review_queue_path")
        self.candidate_only_review_queue_path = (
            Path(configured_candidate_only)
            if configured_candidate_only
            else self.review_queue_path.with_name(
                f"{self.review_queue_path.stem}_candidate_only"
                f"{self.review_queue_path.suffix}"
            )
        )
        self.loader_version = self.config.get("loader_version", "gabriel-loader/v1")
        self.required_provenance_fields = tuple(
            self.config.get(
                "required_provenance_fields", DEFAULT_REQUIRED_PROVENANCE_FIELDS
            )
        )
        requested_quality_profile = (
            str(self.config.get("quality_profile", "high_precision")).strip().lower()
        )
        if requested_quality_profile not in self.QUALITY_PROFILES:
            logger.warning(
                "Unknown GABRIEL quality profile '%s'; falling back to high_precision",
                requested_quality_profile,
            )
            requested_quality_profile = "high_precision"
        self.quality_profile = requested_quality_profile

        profile_gate = self.QUALITY_PROFILES.get(
            self.quality_profile, DEFAULT_HIGH_PRECISION_THRESHOLDS
        )
        self.gate_thresholds = {
            **DEFAULT_HIGH_PRECISION_THRESHOLDS,
            **profile_gate,
            **(self.config.get("quality_gate") or {}),
        }
        checkpoint_path = self.config.get("ingest_checkpoint_path")
        self.ingest_checkpoint_path = (
            Path(str(checkpoint_path).strip())
            if checkpoint_path and str(checkpoint_path).strip()
            else None
        )
        self.create_missing_targets = bool(
            self.config.get("create_missing_targets", True)
        )
        self.progress_log_every = self._coerce_int_config(
            self.config.get("progress_log_every"),
            default=100,
            minimum=1,
        )
        self.stall_warn_seconds = self._coerce_int_config(
            self.config.get("stall_warn_seconds"),
            default=180,
            minimum=0,
        )
        self.log_timing_breakdown = bool(self.config.get("log_timing_breakdown", False))
        requested_progress_level = (
            str(self.config.get("progress_log_level", "info")).strip().lower()
        )
        if requested_progress_level == "debug":
            self.progress_log_level = logging.DEBUG
        else:
            if requested_progress_level not in {"info", ""}:
                logger.warning(
                    "Unknown progress_log_level '%s'; falling back to 'info'",
                    requested_progress_level,
                )
            self.progress_log_level = logging.INFO
        self._seen_run_nodes: set[str] = set()
        self._target_resolution_cache: dict[tuple[str, str, str], str | None] = {}
        self._publication_resolution_cache: dict[
            tuple[str, str, str, str], str | None
        ] = {}

    def load(self, mode: str = "spine") -> dict[str, Any]:
        """Load records from disk and write accepted entities to the graph."""

        input_paths = self._resolve_input_paths()
        if not input_paths:
            logger.warning(
                "No GABRIEL input files found (input_path=%s, input_path_glob=%s)",
                self.input_path,
                self.input_path_glob,
            )
            return {
                "skipped": True,
                "reason": "missing-input",
                "input_path": str(self.input_path),
                "input_paths": [],
                "input_path_glob": self.input_path_glob,
            }

        stats = {
            "mode": mode,
            "quality_profile": self.quality_profile,
            "input_path": str(self.input_path),
            "input_path_glob": self.input_path_glob,
            "input_paths": [str(path) for path in input_paths],
            "files_discovered": len(input_paths),
            "files_processed": 0,
            "files_failed": 0,
            "per_file": {},
            "records_total": 0,
            "records_parsed": 0,
            "records_accepted": 0,
            "records_rejected": 0,
            "review_queue_items": 0,
            "nodes_created": 0,
            "relationships_created": 0,
            "parse_errors": 0,
        }
        if self.ingest_checkpoint_path:
            stats["ingest_checkpoint_path"] = str(self.ingest_checkpoint_path)

        run_started_monotonic = time.monotonic()
        logger.info(
            "event=ingest_run_start files_discovered=%d quality_profile=%s mode=%s "
            "progress_log_every=%d stall_warn_seconds=%d log_timing_breakdown=%s",
            len(input_paths),
            self.quality_profile,
            mode,
            self.progress_log_every,
            self.stall_warn_seconds,
            self.log_timing_breakdown,
        )

        checkpoint_state = self._load_checkpoint_state(mode)

        for input_path in input_paths:
            file_stats = self._new_stat_block()
            file_key = str(input_path)
            stats["per_file"][file_key] = file_stats
            started_at = datetime.now(timezone.utc).isoformat()
            shard_started_monotonic = time.monotonic()
            self._update_checkpoint_state(
                checkpoint_state,
                input_path=input_path,
                status="in_progress",
                started_at=started_at,
            )
            self._progress_log(
                "event=ingest_shard_start shard=%s mode=%s quality_profile=%s "
                "file_index=%d/%d",
                input_path,
                mode,
                self.quality_profile,
                len(stats["per_file"]),
                len(input_paths),
            )

            timing_totals: dict[str, float] = {
                "compute_variables": 0.0,
                "evaluate_gate": 0.0,
                "queue_for_review": 0.0,
                "ingest_record": 0.0,
            }
            timing_counts: dict[str, int] = {
                "compute_variables": 0,
                "evaluate_gate": 0,
                "queue_for_review": 0,
                "ingest_record": 0,
            }
            progress_state: dict[str, Any] = {
                "last_activity_monotonic": time.monotonic(),
                "records_total": 0,
                "records_parsed": 0,
                "records_accepted": 0,
                "records_rejected": 0,
                "review_queue_items": 0,
                "nodes_created": 0,
                "relationships_created": 0,
            }
            progress_lock = threading.Lock()
            stall_stop_event = threading.Event()
            stall_watchdog: threading.Thread | None = None
            if self.stall_warn_seconds > 0:
                stall_watchdog = threading.Thread(
                    target=self._stall_watchdog_loop,
                    args=(
                        stall_stop_event,
                        progress_state,
                        progress_lock,
                        input_path,
                        shard_started_monotonic,
                    ),
                    daemon=True,
                    name=f"gabriel-stall-watchdog-{hash(input_path)}",
                )
                stall_watchdog.start()

            file_failed = False
            file_error: str | None = None
            try:
                with input_path.open("r", encoding="utf-8") as handle:
                    for line_num, raw_line in enumerate(handle, start=1):
                        line = raw_line.strip()
                        if not line:
                            continue

                        file_stats["records_total"] += 1
                        self._update_progress_state(
                            progress_state=progress_state,
                            progress_lock=progress_lock,
                            file_stats=file_stats,
                        )
                        record = self._parse_line(line, line_num, input_path=input_path)
                        if record is None:
                            file_stats["parse_errors"] += 1
                            self._update_progress_state(
                                progress_state=progress_state,
                                progress_lock=progress_lock,
                                file_stats=file_stats,
                            )
                            continue

                        file_stats["records_parsed"] += 1
                        self._update_progress_state(
                            progress_state=progress_state,
                            progress_lock=progress_lock,
                            file_stats=file_stats,
                        )
                        stage_start = time.perf_counter()
                        variables = compute_gabriel_variables(
                            record,
                            required_provenance_fields=self.required_provenance_fields,
                        )
                        self._record_stage_timing(
                            stage="compute_variables",
                            duration_s=(time.perf_counter() - stage_start),
                            line_num=line_num,
                            input_path=input_path,
                            timing_totals=timing_totals,
                            timing_counts=timing_counts,
                        )
                        stage_start = time.perf_counter()
                        accepted, reasons = evaluate_high_precision_gate(
                            variables, self.gate_thresholds
                        )
                        reasons = self._apply_review_only_overrides(
                            record,
                            variables,
                            reasons,
                            quality_profile=self.quality_profile,
                        )
                        review_routing = self._determine_review_routing(
                            record,
                            reasons,
                            quality_profile=self.quality_profile,
                        )
                        accepted = len(reasons) == 0
                        self._record_stage_timing(
                            stage="evaluate_gate",
                            duration_s=(time.perf_counter() - stage_start),
                            line_num=line_num,
                            input_path=input_path,
                            timing_totals=timing_totals,
                            timing_counts=timing_counts,
                        )

                        if not accepted:
                            stage_start = time.perf_counter()
                            self._queue_for_review(
                                record,
                                variables,
                                reasons,
                                routing=review_routing,
                            )
                            self._record_stage_timing(
                                stage="queue_for_review",
                                duration_s=(time.perf_counter() - stage_start),
                                line_num=line_num,
                                input_path=input_path,
                                timing_totals=timing_totals,
                                timing_counts=timing_counts,
                            )
                            file_stats["records_rejected"] += 1
                            file_stats["review_queue_items"] += 1
                            self._update_progress_state(
                                progress_state=progress_state,
                                progress_lock=progress_lock,
                                file_stats=file_stats,
                            )
                            self._maybe_log_heartbeat(
                                file_stats=file_stats,
                                input_path=input_path,
                                shard_started_monotonic=shard_started_monotonic,
                                checkpoint_state=checkpoint_state,
                                started_at=started_at,
                                timing_totals=timing_totals,
                                timing_counts=timing_counts,
                            )
                            continue

                        stage_start = time.perf_counter()
                        created_nodes, created_rels = self._ingest_record(
                            record, variables
                        )
                        self._record_stage_timing(
                            stage="ingest_record",
                            duration_s=(time.perf_counter() - stage_start),
                            line_num=line_num,
                            input_path=input_path,
                            timing_totals=timing_totals,
                            timing_counts=timing_counts,
                        )
                        file_stats["records_accepted"] += 1
                        file_stats["nodes_created"] += created_nodes
                        file_stats["relationships_created"] += created_rels
                        self._update_progress_state(
                            progress_state=progress_state,
                            progress_lock=progress_lock,
                            file_stats=file_stats,
                        )
                        self._maybe_log_heartbeat(
                            file_stats=file_stats,
                            input_path=input_path,
                            shard_started_monotonic=shard_started_monotonic,
                            checkpoint_state=checkpoint_state,
                            started_at=started_at,
                            timing_totals=timing_totals,
                            timing_counts=timing_counts,
                        )
            except OSError as exc:
                file_failed = True
                file_error = str(exc)
                logger.warning("Failed to ingest GABRIEL shard %s: %s", input_path, exc)
            finally:
                stall_stop_event.set()
                if stall_watchdog is not None:
                    stall_watchdog.join(timeout=1.0)

            self._merge_file_stats(stats, file_stats)
            if file_failed:
                stats["files_failed"] += 1
            else:
                stats["files_processed"] += 1

            self._update_checkpoint_state(
                checkpoint_state,
                input_path=input_path,
                status="failed" if file_failed else "completed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc).isoformat(),
                file_stats=file_stats,
                error=file_error,
            )
            elapsed_s = max(0.0, time.monotonic() - shard_started_monotonic)
            self._progress_log(
                "event=ingest_shard_completed shard=%s status=%s elapsed_s=%.2f "
                "records_total=%d records_parsed=%d records_accepted=%d "
                "records_rejected=%d review_queue_items=%d nodes_created=%d "
                "relationships_created=%d parse_errors=%d",
                input_path,
                "failed" if file_failed else "completed",
                elapsed_s,
                file_stats["records_total"],
                file_stats["records_parsed"],
                file_stats["records_accepted"],
                file_stats["records_rejected"],
                file_stats["review_queue_items"],
                file_stats["nodes_created"],
                file_stats["relationships_created"],
                file_stats["parse_errors"],
            )

        elapsed_s = max(0.0, time.monotonic() - run_started_monotonic)
        throughput_rps = (
            float(stats["records_parsed"]) / elapsed_s
            if elapsed_s > 0 and stats["records_parsed"] > 0
            else 0.0
        )
        logger.info(
            "event=ingest_completed elapsed_s=%.2f files_processed=%d files_failed=%d "
            "records_total=%d records_parsed=%d records_accepted=%d "
            "records_rejected=%d review_queue_items=%d nodes_created=%d "
            "relationships_created=%d parse_errors=%d throughput_rps=%.2f",
            elapsed_s,
            stats["files_processed"],
            stats["files_failed"],
            stats["records_total"],
            stats["records_parsed"],
            stats["records_accepted"],
            stats["records_rejected"],
            stats["review_queue_items"],
            stats["nodes_created"],
            stats["relationships_created"],
            stats["parse_errors"],
            throughput_rps,
        )
        return stats

    def load_candidate_only_queue(
        self,
        *,
        mode: str = "spine",
        queue_paths: Sequence[str | Path] | None = None,
        source_quality_profile: str = "candidate_only",
    ) -> dict[str, Any]:
        """Materialize candidate-only review queue rows into the live graph."""

        del mode  # Candidate replay currently reuses spine materialization only.
        resolved_paths = self._resolve_candidate_only_queue_paths(queue_paths)
        if not resolved_paths:
            logger.warning(
                "No candidate-only queue files found (configured_path=%s)",
                self.candidate_only_review_queue_path,
            )
            return {
                "skipped": True,
                "reason": "missing-candidate-only-queue",
                "queue_paths": [],
                "source_quality_profile": source_quality_profile,
            }

        stats = {
            "files_processed": 0,
            "files_failed": 0,
            "queue_rows_total": 0,
            "queue_rows_loaded": 0,
            "queue_rows_skipped": 0,
            "overlay_conflicts": 0,
            "nodes_created": 0,
            "relationships_created": 0,
            "parse_errors": 0,
            "source_quality_profile": source_quality_profile,
            "per_file": {},
            "queue_paths": [str(path) for path in resolved_paths],
        }

        for queue_path in resolved_paths:
            file_stats = dict.fromkeys(self.CANDIDATE_QUEUE_STAT_KEYS, 0)
            try:
                with queue_path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if not line.strip():
                            continue
                        file_stats["queue_rows_total"] += 1
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            file_stats["parse_errors"] += 1
                            logger.warning(
                                "Skipping malformed candidate-only queue row: %s:%d",
                                queue_path,
                                line_number,
                            )
                            continue

                        parsed = self._parse_candidate_only_queue_payload(
                            payload,
                            queue_path=queue_path,
                            source_quality_profile=source_quality_profile,
                        )
                        if parsed is None:
                            file_stats["queue_rows_skipped"] += 1
                            continue

                        record, variables, ingest_annotations = parsed
                        conflicts = self._candidate_lane_overlay_conflicts(
                            record,
                            ingest_annotations=ingest_annotations,
                        )
                        if conflicts:
                            file_stats["queue_rows_skipped"] += 1
                            file_stats["overlay_conflicts"] += 1
                            logger.warning(
                                "Skipping candidate-only queue row that would mutate benchmark graph state (%s:%d): %s",
                                queue_path,
                                line_number,
                                "; ".join(conflicts),
                            )
                            continue
                        created_nodes, created_rels = self._ingest_record(
                            record,
                            variables,
                            ingest_annotations=ingest_annotations,
                        )
                        file_stats["queue_rows_loaded"] += 1
                        file_stats["nodes_created"] += created_nodes
                        file_stats["relationships_created"] += created_rels
            except Exception as exc:  # pragma: no cover - defensive fallback
                stats["files_failed"] += 1
                logger.exception(
                    "Candidate-only queue ingest failed for %s: %s", queue_path, exc
                )
                stats["per_file"][str(queue_path)] = {
                    **file_stats,
                    "status": "failed",
                    "error": str(exc),
                }
                continue

            stats["files_processed"] += 1
            stats["per_file"][str(queue_path)] = {
                **file_stats,
                "status": "completed",
            }
            for key in self.CANDIDATE_QUEUE_STAT_KEYS:
                stats[key] += int(file_stats.get(key, 0) or 0)

        return stats

    def _new_stat_block(self) -> dict[str, int]:
        return dict.fromkeys(self.FILE_STAT_KEYS, 0)

    def _resolve_candidate_only_queue_paths(
        self,
        queue_paths: Sequence[str | Path] | None = None,
    ) -> list[Path]:
        if queue_paths:
            resolved = [
                Path(path).expanduser().resolve()
                for path in queue_paths
                if str(path).strip()
            ]
            return [path for path in resolved if path.exists() and path.is_file()]

        default_path = self.candidate_only_review_queue_path.expanduser().resolve()
        return [default_path] if default_path.exists() and default_path.is_file() else []

    def _parse_candidate_only_queue_payload(
        self,
        payload: Mapping[str, Any],
        *,
        queue_path: Path,
        source_quality_profile: str,
    ) -> tuple[dict[str, Any], GabrielVariables, dict[str, Any]] | None:
        record = dict(payload.get("record") or {})
        if not record:
            return None

        reasons = [
            str(reason).strip()
            for reason in (payload.get("reasons") or [])
            if str(reason).strip()
        ]
        raw_routing = payload.get("routing") or {}
        routing = dict(raw_routing) if isinstance(raw_routing, Mapping) else {}
        lane = str(routing.get("lane") or "").strip().lower()
        if lane != "candidate_only":
            return None

        raw_variables = payload.get("variables")
        if isinstance(raw_variables, Mapping):
            try:
                variables = GabrielVariables(
                    mention_strength=float(raw_variables.get("mention_strength", 0.0)),
                    mapping_confidence=float(
                        raw_variables.get("mapping_confidence", 0.0)
                    ),
                    claim_polarity=str(
                        raw_variables.get("claim_polarity") or "uncertain"
                    ),
                    claim_strength=float(raw_variables.get("claim_strength", 0.0)),
                    evidence_quality=str(
                        raw_variables.get("evidence_quality") or "unknown"
                    ),
                    evidence_quality_score=float(
                        raw_variables.get("evidence_quality_score", 0.0)
                    ),
                    method_rigor=float(raw_variables.get("method_rigor", 0.0)),
                    provenance_completeness=float(
                        raw_variables.get("provenance_completeness", 0.0)
                    ),
                )
            except (TypeError, ValueError):
                variables = compute_gabriel_variables(
                    record,
                    self.required_provenance_fields,
                )
        else:
            variables = compute_gabriel_variables(
                record,
                self.required_provenance_fields,
            )

        return (
            record,
            variables,
            self._build_candidate_ingest_annotations(
                record=record,
                reasons=reasons,
                routing=routing,
                queue_path=queue_path,
                source_quality_profile=source_quality_profile,
            ),
        )

    def _build_candidate_ingest_annotations(
        self,
        *,
        record: Mapping[str, Any],
        reasons: Sequence[str],
        routing: Mapping[str, Any],
        queue_path: Path,
        source_quality_profile: str,
    ) -> dict[str, Any]:
        target = dict(record.get("target") or {})
        return self._clean_none(
            {
                "candidate_lane_present": True,
                "candidate_lane_promoted_at": datetime.now(timezone.utc).isoformat(),
                "candidate_lane_source_quality_profile": str(
                    source_quality_profile or "candidate_only"
                ),
                "candidate_lane_bucket": str(routing.get("bucket") or "").strip(),
                "candidate_lane_policy": str(routing.get("policy") or "").strip(),
                "candidate_lane_trigger_reason": str(
                    routing.get("trigger_reason") or ""
                ).strip(),
                "candidate_lane_review_reasons": [
                    reason for reason in reasons if reason
                ],
                "candidate_lane_queue_path": str(queue_path),
                "candidate_lane_target_id": str(target.get("id") or "").strip(),
                "candidate_lane_target_label": str(target.get("label") or "").strip(),
                "candidate_lane_source_review_bucket": str(
                    record.get("source_review_bucket") or ""
                ).strip(),
                "candidate_lane_source_bucket_reason": str(
                    record.get("source_bucket_reason") or ""
                ).strip(),
            }
        )

    def _candidate_lane_overlay_conflicts(
        self,
        record: Mapping[str, Any],
        *,
        ingest_annotations: Mapping[str, Any] | None = None,
    ) -> list[str]:
        if not ingest_annotations or not _candidate_lane_flag(ingest_annotations):
            return []

        conflicts: list[str] = []
        paper = self._extract_paper(record)
        if not paper["paper_id"]:
            return ["missing publication identifier"]
        paper_node_id = self._resolve_publication_node_id(paper) or paper["paper_id"]

        target = self._extract_target(record)
        claim = self._extract_claim(record, paper_node_id, target.get("target_id"))
        evidence = self._extract_evidence(record, paper_node_id, claim["claim_id"])

        existing_claim = self.db.get_node(claim["claim_id"])
        if existing_claim and not _candidate_lane_flag(existing_claim):
            conflicts.append(f"claim:{claim['claim_id']}")

        existing_evidence = self.db.get_node(evidence["span_id"])
        if existing_evidence and not _candidate_lane_flag(existing_evidence):
            conflicts.append(f"evidence:{evidence['span_id']}")

        target_id = str(target.get("target_id") or "").strip()
        if target_id:
            mention_type = (
                "MENTIONS_REGION"
                if str(target.get("target_type") or "").strip() == "Region"
                else "MENTIONS"
            )
            for _, _, rel_props in self.db.find_relationships(
                start_node=paper_node_id,
                end_node=target_id,
                rel_type=mention_type,
            ):
                if not _candidate_lane_flag(rel_props):
                    conflicts.append(f"{mention_type}:{paper_node_id}->{target_id}")
                    break

        return conflicts

    @staticmethod
    def _apply_review_only_overrides(
        record: Mapping[str, Any],
        variables: GabrielVariables,
        reasons: list[str],
        *,
        quality_profile: str = "high_precision",
    ) -> list[str]:
        evidence = dict(record.get("evidence") or {})
        signals = dict(record.get("signals") or {})
        normalized_reasons = list(reasons)

        title_only_evidence = bool(signals.get("title_only_evidence")) or (
            str(evidence.get("section") or "").strip().lower() == "title"
        )
        if (
            title_only_evidence
            and quality_profile
            in GabrielMeasurementLoader.BENCHMARK_TITLE_ONLY_SUPPRESSION_PROFILES
        ):
            normalized_reasons.append("benchmark_title_only_suppressed")
        if GabrielMeasurementLoader._is_generic_title_only_concept(record):
            normalized_reasons.append("candidate_only_title_generic_reroute")
        if title_only_evidence and variables.method_rigor <= 0.0:
            normalized_reasons.append("title_only_low_rigor_evidence")
        if bool(signals.get("unverifiable_snippet")):
            normalized_reasons.append("unverifiable_snippet")

        return list(dict.fromkeys(normalized_reasons))

    @staticmethod
    def _is_generic_title_only_concept(record: Mapping[str, Any]) -> bool:
        evidence = dict(record.get("evidence") or {})
        signals = dict(record.get("signals") or {})
        target = dict(record.get("target") or {})
        title_only_evidence = bool(signals.get("title_only_evidence")) or (
            str(evidence.get("section") or "").strip().lower() == "title"
        )
        if not title_only_evidence:
            return False
        if str(target.get("type") or "").strip().lower() != "concept":
            return False

        target_id = str(target.get("id") or "").strip().lower()
        target_label = str(target.get("label") or "").strip().lower()
        if target_id in GabrielMeasurementLoader.TITLE_ONLY_GENERIC_CONCEPT_IDS:
            return True

        normalized_label = re.sub(r"[^a-z0-9]+", " ", target_label).strip()
        if normalized_label in {"fmri", "eeg", "meg", "fmri study", "eeg study", "meg study"}:
            return True
        if "multi voxel pattern analysis" in normalized_label or "mvpa" in normalized_label:
            return True
        if "simultaneous eeg fmri" in normalized_label:
            return True
        return False

    @staticmethod
    def _determine_review_routing(
        record: Mapping[str, Any],
        reasons: Sequence[str],
        *,
        quality_profile: str,
    ) -> dict[str, Any] | None:
        if (
            quality_profile in GabrielMeasurementLoader.BENCHMARK_TITLE_ONLY_SUPPRESSION_PROFILES
            and "candidate_only_title_generic_reroute" in reasons
        ):
            target = dict(record.get("target") or {})
            return {
                "lane": "candidate_only",
                "bucket": "title_only_generic_concept",
                "policy": "do_not_promote_to_benchmark",
                "trigger_reason": "candidate_only_title_generic_reroute",
                "target_id": str(target.get("id") or "").strip(),
                "target_label": str(target.get("label") or "").strip(),
            }
        return None

    @staticmethod
    def _coerce_int_config(value: Any, *, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, parsed)

    def _progress_log(self, message: str, *args: Any) -> None:
        logger.log(self.progress_log_level, message, *args)

    def _update_progress_state(
        self,
        *,
        progress_state: dict[str, Any],
        progress_lock: threading.Lock,
        file_stats: Mapping[str, int],
    ) -> None:
        with progress_lock:
            progress_state["last_activity_monotonic"] = time.monotonic()
            progress_state["records_total"] = int(file_stats.get("records_total", 0))
            progress_state["records_parsed"] = int(file_stats.get("records_parsed", 0))
            progress_state["records_accepted"] = int(
                file_stats.get("records_accepted", 0)
            )
            progress_state["records_rejected"] = int(
                file_stats.get("records_rejected", 0)
            )
            progress_state["review_queue_items"] = int(
                file_stats.get("review_queue_items", 0)
            )
            progress_state["nodes_created"] = int(file_stats.get("nodes_created", 0))
            progress_state["relationships_created"] = int(
                file_stats.get("relationships_created", 0)
            )

    def _stall_watchdog_loop(
        self,
        stop_event: threading.Event,
        progress_state: dict[str, Any],
        progress_lock: threading.Lock,
        input_path: Path,
        shard_started_monotonic: float,
    ) -> None:
        if self.stall_warn_seconds <= 0:
            return

        check_interval_s = max(1.0, min(10.0, self.stall_warn_seconds / 3.0))
        last_warning_monotonic = 0.0

        while not stop_event.wait(timeout=check_interval_s):
            with progress_lock:
                last_activity_monotonic = float(
                    progress_state.get("last_activity_monotonic", 0.0)
                )
                snapshot = {
                    "records_total": int(progress_state.get("records_total", 0)),
                    "records_parsed": int(progress_state.get("records_parsed", 0)),
                    "records_accepted": int(progress_state.get("records_accepted", 0)),
                    "records_rejected": int(progress_state.get("records_rejected", 0)),
                    "review_queue_items": int(
                        progress_state.get("review_queue_items", 0)
                    ),
                    "nodes_created": int(progress_state.get("nodes_created", 0)),
                    "relationships_created": int(
                        progress_state.get("relationships_created", 0)
                    ),
                }

            now = time.monotonic()
            inactivity_s = max(0.0, now - last_activity_monotonic)
            if inactivity_s < float(self.stall_warn_seconds):
                continue
            if now - last_warning_monotonic < float(self.stall_warn_seconds):
                continue

            elapsed_s = max(0.0, now - shard_started_monotonic)
            logger.warning(
                "event=ingest_stall_warning shard=%s elapsed_s=%.2f inactivity_s=%.2f "
                "records_total=%d records_parsed=%d records_accepted=%d "
                "records_rejected=%d review_queue_items=%d nodes_created=%d "
                "relationships_created=%d hint=possible_db_wait_or_long_transaction",
                input_path,
                elapsed_s,
                inactivity_s,
                snapshot["records_total"],
                snapshot["records_parsed"],
                snapshot["records_accepted"],
                snapshot["records_rejected"],
                snapshot["review_queue_items"],
                snapshot["nodes_created"],
                snapshot["relationships_created"],
            )
            last_warning_monotonic = now

    def _record_stage_timing(
        self,
        *,
        stage: str,
        duration_s: float,
        line_num: int,
        input_path: Path,
        timing_totals: dict[str, float],
        timing_counts: dict[str, int],
    ) -> None:
        if self.log_timing_breakdown:
            timing_totals[stage] = float(timing_totals.get(stage, 0.0)) + duration_s
            timing_counts[stage] = int(timing_counts.get(stage, 0)) + 1

        if self.stall_warn_seconds > 0 and duration_s >= float(self.stall_warn_seconds):
            logger.warning(
                "event=ingest_slow_stage shard=%s line_num=%d stage=%s duration_s=%.2f",
                input_path,
                line_num,
                stage,
                duration_s,
            )

    def _format_timing_averages(
        self,
        *,
        timing_totals: Mapping[str, float],
        timing_counts: Mapping[str, int],
    ) -> str:
        parts: list[str] = []
        for stage in (
            "compute_variables",
            "evaluate_gate",
            "queue_for_review",
            "ingest_record",
        ):
            count = int(timing_counts.get(stage, 0) or 0)
            if count <= 0:
                continue
            avg_ms = (float(timing_totals.get(stage, 0.0)) / count) * 1000.0
            parts.append(f"{stage}:{avg_ms:.2f}ms")
        return ",".join(parts)

    def _maybe_log_heartbeat(
        self,
        *,
        file_stats: Mapping[str, int],
        input_path: Path,
        shard_started_monotonic: float,
        checkpoint_state: dict[str, Any] | None,
        started_at: str,
        timing_totals: Mapping[str, float],
        timing_counts: Mapping[str, int],
    ) -> None:
        if self.progress_log_every <= 0:
            return
        parsed = int(file_stats.get("records_parsed", 0))
        if parsed <= 0 or parsed % self.progress_log_every != 0:
            return

        elapsed_s = max(0.0, time.monotonic() - shard_started_monotonic)
        throughput_rps = (float(parsed) / elapsed_s) if elapsed_s > 0 else 0.0
        accepted = int(file_stats.get("records_accepted", 0))
        rejected = int(file_stats.get("records_rejected", 0))
        accept_rate = (float(accepted) / parsed) if parsed > 0 else 0.0
        timing_summary = ""
        if self.log_timing_breakdown:
            timing_summary = self._format_timing_averages(
                timing_totals=timing_totals,
                timing_counts=timing_counts,
            )

        message = (
            "event=ingest_heartbeat shard=%s elapsed_s=%.2f records_total=%d "
            "records_parsed=%d records_accepted=%d records_rejected=%d "
            "review_queue_items=%d nodes_created=%d relationships_created=%d "
            "throughput_rps=%.2f accept_rate=%.3f"
        )
        args: list[Any] = [
            input_path,
            elapsed_s,
            int(file_stats.get("records_total", 0)),
            parsed,
            accepted,
            rejected,
            int(file_stats.get("review_queue_items", 0)),
            int(file_stats.get("nodes_created", 0)),
            int(file_stats.get("relationships_created", 0)),
            throughput_rps,
            accept_rate,
        ]
        if timing_summary:
            message += " timings_avg=%s"
            args.append(timing_summary)
        self._progress_log(message, *args)

        self._update_checkpoint_state(
            checkpoint_state,
            input_path=input_path,
            status="in_progress",
            started_at=started_at,
            file_stats=file_stats,
        )

    def _merge_file_stats(
        self,
        overall_stats: dict[str, Any],
        file_stats: Mapping[str, int],
    ) -> None:
        for key in self.FILE_STAT_KEYS:
            overall_stats[key] += int(file_stats.get(key, 0))

    def _resolve_input_paths(self) -> list[Path]:
        candidates: list[Path] = []
        if not {"input_paths", "input_path_glob"} & set(self.config.keys()):
            candidates.append(self.input_path)
        elif "input_path" in self.config:
            candidates.append(self.input_path)

        candidates.extend(self.input_paths)
        if self.input_path_glob:
            candidates.extend(
                Path(match)
                for match in sorted(glob(self.input_path_glob, recursive=True))
            )

        resolved: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            expanded = candidate.expanduser()
            dedupe_key = str(expanded.resolve())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if not expanded.exists():
                logger.warning("GABRIEL input file not found: %s", expanded)
                continue
            if not expanded.is_file():
                logger.warning("GABRIEL input path is not a file: %s", expanded)
                continue

            resolved.append(expanded)
        return resolved

    def _load_checkpoint_state(self, mode: str) -> dict[str, Any] | None:
        if not self.ingest_checkpoint_path:
            return None

        state: dict[str, Any] = {
            "source": "gabriel",
            "loader_version": self.loader_version,
            "quality_profile": self.quality_profile,
            "mode": mode,
            "files": {},
        }
        if self.ingest_checkpoint_path.exists():
            try:
                with self.ingest_checkpoint_path.open("r", encoding="utf-8") as handle:
                    existing = json.load(handle)
                if isinstance(existing, dict):
                    state.update(existing)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Ignoring unreadable GABRIEL checkpoint file %s: %s",
                    self.ingest_checkpoint_path,
                    exc,
                )

        if not isinstance(state.get("files"), dict):
            state["files"] = {}

        state["source"] = "gabriel"
        state["loader_version"] = self.loader_version
        state["quality_profile"] = self.quality_profile
        state["mode"] = mode
        return state

    def _write_checkpoint_state(self, state: dict[str, Any] | None) -> None:
        if state is None or not self.ingest_checkpoint_path:
            return

        self.ingest_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp_suffix = f"{self.ingest_checkpoint_path.suffix}.tmp"
        tmp_path = self.ingest_checkpoint_path.with_suffix(tmp_suffix)
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.replace(self.ingest_checkpoint_path)

    def _update_checkpoint_state(
        self,
        state: dict[str, Any] | None,
        *,
        input_path: Path,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        file_stats: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if state is None:
            return

        files = state.setdefault("files", {})
        shard_id = str(input_path.resolve())
        entry = dict(files.get(shard_id) or {})
        entry["input_path"] = str(input_path)
        entry["status"] = status
        if started_at:
            entry["started_at"] = started_at
        if finished_at:
            entry["finished_at"] = finished_at
        if file_stats is not None:
            entry["stats"] = dict(file_stats)
        if error:
            entry["error"] = error
        else:
            entry.pop("error", None)
        files[shard_id] = entry
        self._write_checkpoint_state(state)

    def _parse_line(
        self, line: str, line_num: int, input_path: Path | None = None
    ) -> dict[str, Any] | None:
        path_suffix = f" in {input_path}" if input_path is not None else ""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Skipping malformed JSONL line %s%s: %s", line_num, path_suffix, exc
            )
            return None

        if not isinstance(payload, dict):
            logger.warning("Skipping non-object JSONL line %s%s", line_num, path_suffix)
            return None

        return payload

    def _ingest_record(
        self,
        record: Mapping[str, Any],
        variables: GabrielVariables,
        ingest_annotations: Mapping[str, Any] | None = None,
    ) -> tuple[int, int]:
        nodes_created = 0
        rels_created = 0

        paper = self._extract_paper(record)
        if not paper["paper_id"]:
            logger.warning("Skipping record without paper identifier")
            return nodes_created, rels_created
        paper_node_id = self._resolve_publication_node_id(paper) or paper["paper_id"]

        run = dict(record.get("run") or {})
        run_id = str(
            run.get("run_id") or record.get("run_id") or self._hash_record(record)
        )
        run_node_id = f"run:{run_id}"
        run_props = {
            "run_id": run_id,
            "tool": str(run.get("tool") or record.get("tool") or "extract"),
            "model": str(run.get("model") or record.get("model") or "unknown"),
            "prompt_hash": str(
                run.get("prompt_hash") or record.get("prompt_hash") or "unknown"
            ),
            "template_hash": str(
                run.get("template_hash") or record.get("template_hash") or "unknown"
            ),
            "raw_response_path": str(
                run.get("raw_response_path")
                or record.get("raw_response_path")
                or "unknown"
            ),
            "status": str(run.get("status") or "completed"),
            "source": "gabriel",
            "provenance_completeness": variables.provenance_completeness,
        }
        if ingest_annotations:
            run_props.update(dict(ingest_annotations))

        if run_node_id not in self._seen_run_nodes:
            self.db.create_node("MeasurementRun", run_props, node_id=run_node_id)
            self._seen_run_nodes.add(run_node_id)
            nodes_created += 1

        paper_props = {
            "title": paper["title"],
            "pmid": paper.get("pmid"),
            "doi": paper.get("doi"),
            "pmcid": paper.get("pmcid"),
            "year": paper.get("year"),
            "journal": paper.get("journal"),
            "source": paper.get("source") or "pubmed",
        }
        self.db.create_node(
            "Publication", self._clean_none(paper_props), node_id=paper_node_id
        )
        nodes_created += 1

        target = self._extract_target(record)
        target_type = target["target_type"]
        input_target_id = target["target_id"]
        resolved_target_id, created_target = self._upsert_target_node(target)
        if created_target:
            nodes_created += 1
        target_id = resolved_target_id or input_target_id

        claim = self._extract_claim(record, paper_node_id, target_id)
        self.db.create_node(
            "Claim",
            self._clean_none(
                {
                    "text": claim["text"],
                    "paper_id": paper_node_id,
                    "target_id": target_id,
                    "claim_kind": claim["claim_kind"],
                    "related_claim_id": claim.get("related_claim_id"),
                    "claim_polarity": variables.claim_polarity,
                    "claim_strength": variables.claim_strength,
                    "method_rigor": variables.method_rigor,
                    "main_assumption_text": claim.get("main_assumption_text"),
                    "main_assumption_id": claim.get("main_assumption_id"),
                    "assumption_type": claim.get("assumption_type"),
                    "assumption_scope": claim.get("assumption_scope"),
                    "defaultness_score": claim.get("defaultness_score"),
                    "challengeability_score": claim.get("challengeability_score"),
                    "assumption_confidence": claim.get("assumption_confidence"),
                    "assumption_status": claim.get("assumption_status"),
                    "provenance_completeness": variables.provenance_completeness,
                    "source": "gabriel",
                    **(dict(ingest_annotations) if ingest_annotations else {}),
                }
            ),
            node_id=claim["claim_id"],
        )
        nodes_created += 1

        assumption = self._extract_assumption(record, paper_node_id, claim)
        if assumption is not None:
            self.db.create_node(
                "Assumption",
                self._clean_none(
                    {
                        "text": assumption["text"],
                        "paper_id": paper_node_id,
                        "source_claim_id": claim["claim_id"],
                        "assumption_type": assumption.get("assumption_type"),
                        "domain_scope": assumption.get("domain_scope"),
                        "defaultness_score": assumption.get("defaultness_score"),
                        "challengeability_score": assumption.get(
                            "challengeability_score"
                        ),
                        "confidence": assumption.get("confidence"),
                        "status": assumption.get("status"),
                        "source": "gabriel",
                        **(dict(ingest_annotations) if ingest_annotations else {}),
                    }
                ),
                node_id=assumption["assumption_id"],
            )
            nodes_created += 1

        evidence = self._extract_evidence(record, paper_node_id, claim["claim_id"])
        self.db.create_node(
            "EvidenceSpan",
            {
                "paper_id": paper_node_id,
                "claim_id": claim["claim_id"],
                "quote": evidence["quote"],
                "section": evidence.get("section"),
                "page": evidence.get("page"),
                "char_start": evidence.get("char_start"),
                "char_end": evidence.get("char_end"),
                "mention_strength": variables.mention_strength,
                "evidence_quality": variables.evidence_quality,
                "evidence_quality_score": variables.evidence_quality_score,
                "method_rigor": variables.method_rigor,
                "provenance_completeness": variables.provenance_completeness,
                "source": "gabriel",
                **(dict(ingest_annotations) if ingest_annotations else {}),
            },
            node_id=evidence["span_id"],
        )
        nodes_created += 1

        base_rel_props = self._build_relationship_properties(
            record,
            run_id,
            variables,
            ingest_annotations=ingest_annotations,
        )

        if target_id:
            mention_type = "MENTIONS_REGION" if target_type == "Region" else "MENTIONS"
            if self.db.create_relationship(
                paper_node_id,
                target_id,
                mention_type,
                base_rel_props,
            ):
                rels_created += 1

        if self.db.create_relationship(
            paper_node_id,
            claim["claim_id"],
            "REPORTS_CLAIM",
            base_rel_props,
        ):
            rels_created += 1

        if self.db.create_relationship(
            evidence["span_id"],
            claim["claim_id"],
            "SUPPORTS",
            base_rel_props,
        ):
            rels_created += 1

        if self.db.create_relationship(
            run_node_id, evidence["span_id"], "GENERATED", base_rel_props
        ):
            rels_created += 1

        if self.db.create_relationship(
            run_node_id, claim["claim_id"], "GENERATED", base_rel_props
        ):
            rels_created += 1
        if assumption is not None:
            assumes_props = self._clean_none(
                {
                    **base_rel_props,
                    "assumption_confidence": assumption.get("confidence"),
                    "confidence": max(
                        float(base_rel_props.get("confidence") or 0.0),
                        float(assumption.get("confidence") or 0.0),
                    ),
                }
            )
            if self.db.create_relationship(
                claim["claim_id"],
                assumption["assumption_id"],
                "ASSUMES",
                assumes_props,
            ):
                rels_created += 1
            if self.db.create_relationship(
                run_node_id,
                assumption["assumption_id"],
                "GENERATED",
                base_rel_props,
            ):
                rels_created += 1

            if assumption.get("status") == "challenged":
                challenge_props = self._clean_none(
                    {
                        **base_rel_props,
                        "challenge_mode": self._claim_kind_to_challenge_mode(
                            claim["claim_kind"]
                        ),
                    }
                )
                if self.db.create_relationship(
                    paper_node_id,
                    assumption["assumption_id"],
                    "CHALLENGES_ASSUMPTION",
                    challenge_props,
                ):
                    rels_created += 1
                if self.db.create_relationship(
                    claim["claim_id"],
                    assumption["assumption_id"],
                    "CHALLENGES_ASSUMPTION",
                    challenge_props,
                ):
                    rels_created += 1

        relation_type = self._claim_kind_to_edge_type(claim["claim_kind"])
        related_claim_id = str(claim.get("related_claim_id") or "").strip()
        if relation_type and related_claim_id:
            relation_props = dict(base_rel_props)
            relation_mode = (
                str(claim.get("relation_mode") or "other").strip() or "other"
            )
            if relation_type in {"REPLICATES", "FAILED_REPLICATION_OF"}:
                relation_props["replication_type"] = relation_mode
            elif relation_type == "NULL_RESULT_FOR":
                relation_props["null_result_type"] = relation_mode
            elif relation_type == "CONTRADICTS":
                relation_props["contradiction_scope"] = relation_mode
            if self.db.create_relationship(
                claim["claim_id"],
                related_claim_id,
                relation_type,
                self._clean_none(relation_props),
            ):
                rels_created += 1

        canonical_id = (
            (record.get("mapping") or {}).get("canonical_id")
            if isinstance(record.get("mapping"), dict)
            else record.get("canonical_id")
        )
        if target_id and canonical_id and canonical_id != target_id:
            if self.db.create_relationship(
                target_id,
                str(canonical_id),
                "MAPS_TO",
                {
                    **base_rel_props,
                    "mapping_type": str(
                        (record.get("mapping") or {}).get("mapping_type", "related")
                    ),
                    "similarity_score": variables.mapping_confidence,
                },
            ):
                rels_created += 1

        return nodes_created, rels_created

    def _resolve_publication_node_id(self, paper: Mapping[str, Any]) -> str | None:
        pmid = str(paper.get("pmid") or "").strip()
        doi = str(paper.get("doi") or "").strip()
        pmcid = str(paper.get("pmcid") or "").strip()
        paper_id = str(paper.get("paper_id") or "").strip()
        cache_key = (
            pmid,
            doi.lower(),
            pmcid.lower(),
            paper_id,
        )
        if cache_key in self._publication_resolution_cache:
            return self._publication_resolution_cache[cache_key]

        existing_id: str | None = None

        if pmid:
            by_pmid = self.db.find_nodes("Publication", {"pmid": pmid})
            if by_pmid:
                existing_id = self._normalize_publication_match_id(
                    by_pmid[0],
                    pmid=pmid,
                    doi=doi,
                    pmcid=pmcid,
                    paper_id=paper_id,
                )
            elif hasattr(self.db, "execute_query"):
                try:
                    rows = self.db.execute_query(
                        """
                        MATCH (p:Publication)
                        WHERE toString(p.pmid) = toString($pmid)
                        RETURN p.id AS id, elementId(p) AS element_id
                        LIMIT 1
                        """,
                        {"pmid": pmid},
                    )
                    if rows:
                        found_id = rows[0].get("id")
                        if found_id:
                            existing_id = str(found_id)
                        else:
                            existing_id = self._ensure_publication_id_from_element(
                                element_id=str(rows[0].get("element_id") or ""),
                                pmid=pmid,
                                doi=doi,
                                pmcid=pmcid,
                                paper_id=paper_id,
                            )
                except Exception:  # pragma: no cover - defensive fallback
                    logger.debug(
                        "String-coerced Publication PMID lookup failed for '%s'", pmid
                    )

        if existing_id is None and doi:
            by_doi = self.db.find_nodes("Publication", {"doi": doi})
            if by_doi:
                existing_id = self._normalize_publication_match_id(
                    by_doi[0],
                    pmid=pmid,
                    doi=doi,
                    pmcid=pmcid,
                    paper_id=paper_id,
                )
            elif hasattr(self.db, "execute_query"):
                try:
                    rows = self.db.execute_query(
                        """
                        MATCH (p:Publication)
                        WHERE toLower(toString(p.doi)) = toLower($doi)
                        RETURN p.id AS id, elementId(p) AS element_id
                        LIMIT 1
                        """,
                        {"doi": doi},
                    )
                    if rows:
                        found_id = rows[0].get("id")
                        if found_id:
                            existing_id = str(found_id)
                        else:
                            existing_id = self._ensure_publication_id_from_element(
                                element_id=str(rows[0].get("element_id") or ""),
                                pmid=pmid,
                                doi=doi,
                                pmcid=pmcid,
                                paper_id=paper_id,
                            )
                except Exception:  # pragma: no cover - defensive fallback
                    logger.debug(
                        "Case-insensitive Publication DOI lookup failed for '%s'", doi
                    )

        if existing_id is None and pmcid:
            by_pmcid = self.db.find_nodes("Publication", {"pmcid": pmcid})
            if by_pmcid:
                existing_id = self._normalize_publication_match_id(
                    by_pmcid[0],
                    pmid=pmid,
                    doi=doi,
                    pmcid=pmcid,
                    paper_id=paper_id,
                )

        if existing_id is None and paper_id:
            by_id = self.db.find_nodes("Publication", {"id": paper_id})
            if by_id:
                existing_id = self._normalize_publication_match_id(
                    by_id[0],
                    pmid=pmid,
                    doi=doi,
                    pmcid=pmcid,
                    paper_id=paper_id,
                )

        if existing_id is None:
            existing_id = paper_id or None

        self._publication_resolution_cache[cache_key] = existing_id
        return existing_id

    def _normalize_publication_match_id(
        self,
        match: tuple[str, Mapping[str, Any]],
        *,
        pmid: str,
        doi: str,
        pmcid: str,
        paper_id: str,
    ) -> str | None:
        node_key, props = match
        node_props = dict(props or {})
        prop_id = str(node_props.get("id") or "").strip()
        if prop_id:
            return prop_id
        return self._ensure_publication_id_from_element(
            element_id=str(node_key),
            pmid=pmid,
            doi=doi,
            pmcid=pmcid,
            paper_id=paper_id,
        )

    @staticmethod
    def _canonical_publication_id(
        *,
        pmid: str,
        doi: str,
        pmcid: str,
        paper_id: str,
    ) -> str:
        if paper_id:
            return paper_id
        if pmid:
            return pmid if ":" in pmid else f"pmid:{pmid}"
        if doi:
            return doi if ":" in doi else f"doi:{doi}"
        if pmcid:
            return pmcid if ":" in pmcid else f"pmcid:{pmcid}"
        return ""

    def _ensure_publication_id_from_element(
        self,
        *,
        element_id: str,
        pmid: str,
        doi: str,
        pmcid: str,
        paper_id: str,
    ) -> str | None:
        canonical_id = self._canonical_publication_id(
            pmid=pmid,
            doi=doi,
            pmcid=pmcid,
            paper_id=paper_id,
        )
        if not element_id or not canonical_id or not hasattr(self.db, "execute_query"):
            return None
        try:
            rows = self.db.execute_query(
                """
                MATCH (p:Publication)
                WHERE elementId(p) = $element_id
                SET p.id = coalesce(p.id, $new_id)
                RETURN p.id AS id
                LIMIT 1
                """,
                {"element_id": element_id, "new_id": canonical_id},
            )
            if rows:
                found_id = rows[0].get("id")
                if found_id:
                    return str(found_id)
        except Exception:  # pragma: no cover - defensive fallback
            logger.debug(
                "Failed to materialize Publication.id for element %s", element_id
            )
        return None

    def _upsert_target_node(self, target: Mapping[str, Any]) -> tuple[str | None, bool]:
        target_type = str(target.get("target_type") or "Concept")
        target_id = str(target.get("target_id") or "")
        target_label = str(target.get("target_label") or "").strip()
        atlas = target.get("atlas")

        resolved = self._resolve_target_node_id(
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
        )
        props = self._target_node_props(
            target_type=target_type,
            target_label=target_label,
            atlas=atlas,
        )

        if resolved:
            # For Region, avoid rewriting `name` on existing nodes because the graph
            # enforces uniqueness on Region.name and legacy IDs may collide semantically.
            if target_type != "Region":
                self.db.create_node(target_type, props, node_id=resolved)
            return resolved, False

        if not self.create_missing_targets or not target_id:
            return None, False

        self.db.create_node(target_type, props, node_id=target_id)
        cache_key = self._target_resolution_cache_key(
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
        )
        self._target_resolution_cache[cache_key] = target_id
        return target_id, True

    def _resolve_target_node_id(
        self,
        *,
        target_type: str,
        target_id: str,
        target_label: str,
    ) -> str | None:
        cache_key = self._target_resolution_cache_key(
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
        )
        if cache_key in self._target_resolution_cache:
            return self._target_resolution_cache[cache_key]

        label = "Concept"
        if target_type == "Region":
            label = "Region"
        elif target_type == "Task":
            label = "Task"

        existing_id: str | None = None
        exact_task_namespace = label == "Task" and any(
            target_id.startswith(prefix) for prefix in self.TASK_EXACT_ID_PREFIXES
        )
        if label == "Region" and target_label:
            # Region has a uniqueness constraint on `name`; prefer this as canonical key.
            existing_id = self._find_region_by_name(target_label)

        if existing_id is None and target_id:
            by_id = self.db.find_nodes(label, {"id": target_id})
            if by_id:
                existing_id = str(by_id[0][0])

        if existing_id is None and target_label and not exact_task_namespace:
            if label == "Task":
                by_name = self.db.find_nodes("Task", {"name": target_label})
                if by_name:
                    existing_id = str(by_name[0][0])
            else:
                by_label = self.db.find_nodes("Concept", {"label": target_label})
                if by_label:
                    existing_id = str(by_label[0][0])
                else:
                    by_name = self.db.find_nodes("Concept", {"name": target_label})
                    if by_name:
                        existing_id = str(by_name[0][0])

        self._target_resolution_cache[cache_key] = existing_id
        return existing_id

    def _find_region_by_name(self, region_name: str) -> str | None:
        exact = self.db.find_nodes("Region", {"name": region_name})
        preferred_exact = self._select_preferred_node_id(exact)
        if preferred_exact:
            return preferred_exact

        # Case-insensitive fallback for legacy mixed-case region labels.
        if hasattr(self.db, "execute_query"):
            try:
                rows = self.db.execute_query(
                    """
                    MATCH (r:Region)
                    WHERE toLower(r.name) = toLower($name)
                    RETURN r.id AS id, coalesce(r.source, "") AS source
                    """,
                    {"name": region_name},
                )
                candidates: list[tuple[str, dict[str, Any]]] = []
                for row in rows:
                    found_id = row.get("id")
                    if not found_id:
                        continue
                    candidates.append(
                        (
                            str(found_id),
                            {
                                "source": str(row.get("source") or ""),
                            },
                        )
                    )
                preferred_ci = self._select_preferred_node_id(candidates)
                if preferred_ci:
                    return preferred_ci
            except Exception:  # pragma: no cover - defensive fallback
                logger.debug(
                    "Case-insensitive Region lookup failed for '%s'", region_name
                )
        return None

    @staticmethod
    def _select_preferred_node_id(
        candidates: list[tuple[str, Mapping[str, Any]]],
    ) -> str | None:
        if not candidates:
            return None

        def rank(item: tuple[str, Mapping[str, Any]]) -> tuple[int, int, int, str]:
            node_id, props = item
            source = str(props.get("source") or "").strip().lower()
            # Prefer curated/pre-existing nodes over generated gabriel placeholders.
            source_rank = 1 if source == "gabriel" else 0
            generated_rank = 1 if node_id.startswith("region:") else 0
            return (source_rank, generated_rank, len(node_id), node_id)

        ordered = sorted(
            ((str(node_id), props) for node_id, props in candidates),
            key=rank,
        )
        return ordered[0][0] if ordered else None

    @staticmethod
    def _target_resolution_cache_key(
        *,
        target_type: str,
        target_id: str,
        target_label: str,
    ) -> tuple[str, str, str]:
        return (
            target_type.strip(),
            target_id.strip(),
            target_label.strip().lower(),
        )

    def _target_node_props(
        self,
        *,
        target_type: str,
        target_label: str,
        atlas: Any,
    ) -> dict[str, Any]:
        if target_type == "Region":
            payload = {
                "name": target_label,
                "atlas": atlas or "unknown",
                "source": "gabriel",
            }
        elif target_type == "Task":
            payload = {
                "name": target_label,
                "source": "gabriel",
            }
        else:
            payload = {
                "label": target_label,
                "name": target_label,
                "source": "gabriel",
            }
        return self._clean_none(payload)

    def _build_relationship_properties(
        self,
        record: Mapping[str, Any],
        run_id: str,
        variables: GabrielVariables,
        ingest_annotations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = dict(record.get("run") or {})
        tool = str(run.get("tool") or record.get("tool") or "extract").lower()
        method = self.TOOL_TO_METHOD.get(tool, "llm_extract")
        now = datetime.now(timezone.utc).isoformat()
        claim = dict(record.get("claim") or {})
        assumption = dict(record.get("assumption") or {})
        claim_kind = self._normalize_claim_kind(
            claim.get("kind") or claim.get("claim_kind") or record.get("claim_kind")
        )

        payload = {
            "source": "gabriel",
            "method": method,
            "confidence": variables.mapping_confidence,
            "mention_strength": variables.mention_strength,
            "mapping_confidence": variables.mapping_confidence,
            "claim_kind": claim_kind,
            "related_claim_id": claim.get("related_claim_id")
            or (claim.get("relation") or {}).get("target_claim_id")
            or record.get("related_claim_id"),
            "claim_polarity": variables.claim_polarity,
            "claim_strength": variables.claim_strength,
            "evidence_quality": variables.evidence_quality,
            "evidence_quality_score": variables.evidence_quality_score,
            "method_rigor": variables.method_rigor,
            "provenance_completeness": variables.provenance_completeness,
            "main_assumption_text": claim.get("main_assumption_text")
            or assumption.get("text")
            or record.get("main_assumption_text"),
            "main_assumption_id": claim.get("main_assumption_id")
            or assumption.get("id")
            or record.get("main_assumption_id"),
            "assumption_type": claim.get("assumption_type")
            or assumption.get("type")
            or record.get("assumption_type"),
            "run_id": run_id,
            "prompt_hash": str(
                run.get("prompt_hash") or record.get("prompt_hash") or "unknown"
            ),
            "template_hash": str(
                run.get("template_hash") or record.get("template_hash") or "unknown"
            ),
            "raw_response_path": str(
                run.get("raw_response_path")
                or record.get("raw_response_path")
                or "unknown"
            ),
            "model": str(run.get("model") or record.get("model") or "unknown"),
            "loader_version": self.loader_version,
            "timestamp": str(record.get("timestamp") or now),
        }
        if ingest_annotations:
            payload.update(dict(ingest_annotations))
        return self._clean_none(payload)

    def _queue_for_review(
        self,
        record: Mapping[str, Any],
        variables: GabrielVariables,
        reasons: list[str],
        routing: Mapping[str, Any] | None = None,
    ) -> None:
        output_path = (
            self.candidate_only_review_queue_path
            if isinstance(routing, Mapping)
            and str(routing.get("lane") or "").strip().lower() == "candidate_only"
            else self.review_queue_path
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "reasons": reasons,
            "variables": asdict(variables),
            "record": dict(record),
        }
        if routing:
            payload["routing"] = dict(routing)
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _extract_paper(self, record: Mapping[str, Any]) -> dict[str, Any]:
        paper = dict(record.get("paper") or {})

        pmid = paper.get("pmid") or record.get("pmid")
        doi = paper.get("doi") or record.get("doi")
        pmcid = paper.get("pmcid") or record.get("pmcid")
        paper_id = paper.get("id") or record.get("paper_id")

        if not paper_id and pmid:
            paper_id = f"pmid:{pmid}"
        if not paper_id and doi:
            paper_id = f"doi:{doi}"
        if not paper_id and pmcid:
            paper_id = f"pmcid:{pmcid}"
        if paper_id and ":" not in str(paper_id):
            paper_id = f"paper:{paper_id}"

        title = (
            paper.get("title")
            or record.get("title")
            or record.get("paper_title")
            or str(paper_id or "Unknown paper")
        )

        return {
            "paper_id": str(paper_id or ""),
            "title": str(title),
            "pmid": str(pmid) if pmid is not None else None,
            "doi": str(doi) if doi is not None else None,
            "pmcid": str(pmcid) if pmcid is not None else None,
            "year": paper.get("year") or record.get("year"),
            "journal": paper.get("journal") or record.get("journal"),
            "source": paper.get("source") or record.get("source"),
        }

    def _extract_target(self, record: Mapping[str, Any]) -> dict[str, Any]:
        target = dict(record.get("target") or {})

        raw_type = str(target.get("type") or record.get("target_type") or "Concept")
        normalized_type = raw_type.strip().lower()
        if normalized_type in {"region", "brainregion"}:
            target_type = "Region"
            prefix = "region"
        elif normalized_type in {"task", "taskparadigm", "paradigm"}:
            target_type = "Task"
            prefix = "task"
        else:
            target_type = "Concept"
            prefix = "concept"

        target_id = target.get("id") or record.get("target_id")
        target_label = (
            target.get("label")
            or target.get("name")
            or record.get("target_label")
            or str(target_id or "unknown")
        )

        if not target_id:
            target_id = f"{prefix}:{self._slugify(str(target_label))}"
        elif ":" not in str(target_id):
            target_id = f"{prefix}:{self._slugify(str(target_id))}"

        return {
            "target_type": target_type,
            "target_id": str(target_id),
            "target_label": str(target_label),
            "atlas": target.get("atlas") or record.get("atlas"),
        }

    def _extract_claim(
        self,
        record: Mapping[str, Any],
        paper_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        claim = dict(record.get("claim") or {})
        claim_text = str(
            claim.get("text")
            or record.get("claim_text")
            or f"Claim extracted for {paper_id}::{target_id}"
        )
        claim_id = claim.get("id") or record.get("claim_id")
        if not claim_id:
            claim_id = f"claim:{self._short_hash(paper_id, target_id, claim_text)}"
        elif ":" not in str(claim_id):
            claim_id = f"claim:{claim_id}"
        relation = dict(claim.get("relation") or record.get("claim_relation") or {})
        claim_kind = self._normalize_claim_kind(
            claim.get("kind") or claim.get("claim_kind") or relation.get("type")
        )
        related_claim_id = (
            claim.get("related_claim_id")
            or relation.get("target_claim_id")
            or record.get("related_claim_id")
        )
        if related_claim_id and ":" not in str(related_claim_id):
            related_claim_id = f"claim:{related_claim_id}"
        assumption = dict(record.get("assumption") or {})
        main_assumption_text = str(
            claim.get("main_assumption_text")
            or assumption.get("text")
            or record.get("main_assumption_text")
            or ""
        ).strip()
        main_assumption_id = (
            claim.get("main_assumption_id")
            or assumption.get("id")
            or record.get("main_assumption_id")
        )
        if main_assumption_id and ":" not in str(main_assumption_id):
            main_assumption_id = f"assumption:{main_assumption_id}"
        assumption_status = str(
            claim.get("assumption_status")
            or assumption.get("status")
            or record.get("assumption_status")
            or ""
        ).strip()
        if not assumption_status and main_assumption_text:
            assumption_status = (
                "challenged"
                if claim_kind in {"contradiction", "null_result", "failed_replication"}
                else "default"
            )

        return self._clean_none(
            {
                "claim_id": str(claim_id),
                "text": claim_text,
                "claim_kind": claim_kind,
                "related_claim_id": (
                    str(related_claim_id) if related_claim_id is not None else None
                ),
                "relation_mode": str(
                    claim.get("relation_mode")
                    or relation.get("mode")
                    or record.get("relation_mode")
                    or "other"
                ).strip()
                or "other",
                "main_assumption_text": main_assumption_text or None,
                "main_assumption_id": (
                    str(main_assumption_id) if main_assumption_id is not None else None
                ),
                "assumption_type": claim.get("assumption_type")
                or assumption.get("type")
                or record.get("assumption_type"),
                "assumption_scope": claim.get("assumption_scope")
                or assumption.get("scope")
                or record.get("assumption_scope"),
                "defaultness_score": self._coerce_score(
                    claim.get("defaultness_score")
                    or assumption.get("defaultness_score")
                    or record.get("defaultness_score")
                ),
                "challengeability_score": self._coerce_score(
                    claim.get("challengeability_score")
                    or assumption.get("challengeability_score")
                    or record.get("challengeability_score")
                ),
                "assumption_confidence": self._coerce_score(
                    claim.get("assumption_confidence")
                    or assumption.get("confidence")
                    or record.get("assumption_confidence")
                ),
                "assumption_status": assumption_status or None,
            }
        )

    def _extract_assumption(
        self,
        record: Mapping[str, Any],
        paper_id: str,
        claim: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        text = str(claim.get("main_assumption_text") or "").strip()
        if not text:
            return None
        assumption_id = claim.get("main_assumption_id")
        if not assumption_id:
            assumption_id = (
                f"assumption:{self._short_hash(paper_id, claim.get('claim_id'), text)}"
            )
        elif ":" not in str(assumption_id):
            assumption_id = f"assumption:{assumption_id}"
        return self._clean_none(
            {
                "assumption_id": str(assumption_id),
                "text": text,
                "assumption_type": claim.get("assumption_type"),
                "domain_scope": claim.get("assumption_scope"),
                "defaultness_score": claim.get("defaultness_score"),
                "challengeability_score": claim.get("challengeability_score"),
                "confidence": claim.get("assumption_confidence"),
                "status": claim.get("assumption_status"),
            }
        )

    @staticmethod
    def _normalize_claim_kind(value: Any) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        if normalized in {
            "replication",
            "direct_replication",
            "conceptual_replication",
        }:
            return "replication"
        if normalized in {
            "failed_replication",
            "replication_failure",
            "failed_direct_replication",
        }:
            return "failed_replication"
        if normalized in {"null_result", "null", "negative_result"}:
            return "null_result"
        if normalized in {"contradiction", "contradicts", "conflict"}:
            return "contradiction"
        return "claim"

    @staticmethod
    def _claim_kind_to_edge_type(claim_kind: str) -> str | None:
        return {
            "replication": "REPLICATES",
            "failed_replication": "FAILED_REPLICATION_OF",
            "null_result": "NULL_RESULT_FOR",
            "contradiction": "CONTRADICTS",
        }.get(str(claim_kind or "").strip())

    @staticmethod
    def _claim_kind_to_challenge_mode(claim_kind: str) -> str:
        return {
            "failed_replication": "failed_replication",
            "null_result": "null_result",
            "contradiction": "contradiction",
        }.get(str(claim_kind or "").strip(), "other")

    @staticmethod
    def _coerce_score(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None

    def _extract_evidence(
        self,
        record: Mapping[str, Any],
        paper_id: str,
        claim_id: str,
    ) -> dict[str, Any]:
        evidence = dict(record.get("evidence") or {})
        quote = str(
            evidence.get("quote")
            or evidence.get("text")
            or record.get("evidence_quote")
            or "(no quote provided)"
        )
        span_id = evidence.get("span_id") or record.get("span_id")
        if not span_id:
            span_id = f"evidence:{self._short_hash(paper_id, claim_id, quote)}"
        elif ":" not in str(span_id):
            span_id = f"evidence:{span_id}"

        return {
            "span_id": str(span_id),
            "quote": quote,
            "section": evidence.get("section") or record.get("section"),
            "page": evidence.get("page") or record.get("page"),
            "char_start": evidence.get("char_start") or record.get("char_start"),
            "char_end": evidence.get("char_end") or record.get("char_end"),
        }

    @staticmethod
    def _short_hash(*parts: Any) -> str:
        joined = "||".join(str(part) for part in parts)
        return hashlib.md5(joined.encode("utf-8")).hexdigest()

    def _hash_record(self, record: Mapping[str, Any]) -> str:
        serialized = json.dumps(record, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _slugify(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9]+", "_", value)
        return value.strip("_") or "unknown"

    @staticmethod
    def _clean_none(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if value is not None and (not isinstance(value, str) or value != "")
        }
