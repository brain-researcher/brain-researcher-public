"""Run-artifact distillation into reusable memory cards."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import iter_mcp_run_dir_candidates

from .canonical import build_canonical_claim_id, build_verification_claim_mapping
from .models import (
    ClaimEvidenceRefV1,
    ClaimMemoryV1,
    ClaimRelationLinkV1,
    EpisodicRunMemoryV1,
    normalize_space,
    normalize_token_text,
    unique_non_empty,
)
from .store import MemoryStore

logger = logging.getLogger(__name__)

_CLAIM_IDENTITY_KEYS = {
    "claim_id",
    "canonical_claim_id",
    "hypothesis_id",
    "target_id",
    "polarity",
    "claim_polarity",
    "expected_verdict",
    "source_records",
}


@dataclass
class DistilledRunMemory:
    episodic_card: EpisodicRunMemoryV1 | None
    claim_cards: list[ClaimMemoryV1]
    warnings: list[str]


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict | list) else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _find_run_dir(run_id: str, run_dir: Path | None = None) -> Path:
    if run_dir is not None:
        return Path(run_dir).expanduser().resolve()
    for candidate in iter_mcp_run_dir_candidates(run_id):
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"run not found: {run_id}")


def distill_run_records(
    run_id: str,
    *,
    run_dir: Path | None = None,
) -> DistilledRunMemory:
    resolved_run_dir = _find_run_dir(run_id, run_dir=run_dir)
    run_payload = _load_json(resolved_run_dir / "run.json")
    if not isinstance(run_payload, dict):
        raise FileNotFoundError(f"run.json missing for {run_id}")

    observation = _load_json(resolved_run_dir / "observation.json")
    analysis_bundle = _load_json(resolved_run_dir / "analysis_bundle.json")
    provenance = _load_json(resolved_run_dir / "provenance.json")
    trajectory = _load_json(resolved_run_dir / "trajectory.json")
    execution_manifest = _load_json(resolved_run_dir / "execution_manifest.json")
    session_snapshot = _load_json(resolved_run_dir / "session_snapshot.json")
    claim_updates = _load_json(resolved_run_dir / "claim_update.json")
    trace_rows = _load_jsonl(resolved_run_dir / "trace.jsonl")
    research_events = _load_jsonl(resolved_run_dir / "research_events.jsonl")

    episodic_card = _build_episodic_card(
        run_id=run_id,
        run_dir=resolved_run_dir,
        run_payload=run_payload,
        observation=observation if isinstance(observation, dict) else None,
        analysis_bundle=analysis_bundle if isinstance(analysis_bundle, dict) else None,
        provenance=provenance if isinstance(provenance, dict) else None,
        trajectory=trajectory if isinstance(trajectory, dict) else None,
        execution_manifest=execution_manifest if isinstance(execution_manifest, dict) else None,
        session_snapshot=session_snapshot if isinstance(session_snapshot, dict) else None,
        trace_rows=trace_rows,
        research_events=research_events,
    )
    claim_cards = _build_claim_cards(
        run_id=run_id,
        run_dir=resolved_run_dir,
        run_payload=run_payload,
        observation=observation,
        analysis_bundle=analysis_bundle,
        provenance=provenance,
        claim_updates=claim_updates,
    )
    return DistilledRunMemory(
        episodic_card=episodic_card,
        claim_cards=claim_cards,
        warnings=[],
    )


def distill_and_store_run(
    run_id: str,
    *,
    run_dir: Path | None = None,
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    resolved_store = store or MemoryStore()
    distilled = distill_run_records(run_id, run_dir=run_dir)

    writes: list[dict[str, Any]] = []
    if distilled.episodic_card is not None:
        writes.append(
            resolved_store.write(
                distilled.episodic_card.card_type,
                distilled.episodic_card.model_dump(exclude_none=True),
            )
        )
    for card in distilled.claim_cards:
        writes.append(
            resolved_store.write(
                card.card_type,
                card.model_dump(exclude_none=True),
            )
        )

    # Code review signal extraction (artifact-time, Phase 2)
    # Failure here never breaks the main distillation path.
    review_written = False
    review_warnings: list[str] = []
    try:
        from brain_researcher.services.memory.leaves_review_distiller import (
            distill_review_records,
        )
        from brain_researcher.services.memory.models import CodeReviewMemoryV1

        review_mem = distill_review_records(run_id, run_dir=run_dir)
        if (
            review_mem is not None
            and review_mem.verdict is not None
            and "cached" not in review_mem.warnings
        ):
            verdict = review_mem.verdict
            bundle = review_mem.bundle
            card = CodeReviewMemoryV1(
                source_run_id=run_id,
                workflow_id=bundle.workflow_id if bundle else None,
                review_mode="artifact",
                decision=verdict.decision,
                risk_level=verdict.risk_level,
                finding_count=len(verdict.findings),
                blocking_finding_count=sum(
                    1 for f in verdict.findings if getattr(f, "action", "warn") == "block"
                ),
                mean_fd=bundle.stats_metrics.get("mean_fd") if bundle else None,
                r_squared=bundle.stats_metrics.get("r_squared") if bundle else None,
                flag_rate=bundle.stats_metrics.get("flag_rate") if bundle else None,
                step_success_rate=(
                    bundle.scorecard_snapshot.get("step_success_rate") if bundle else None
                ),
                artifact_completeness_ratio=(
                    bundle.scorecard_snapshot.get("artifact_completeness_ratio") if bundle else None
                ),
            )
            writes.append(
                resolved_store.write(
                    card.card_type,
                    card.model_dump(exclude_none=True),
                )
            )
            review_written = True
        if review_mem is None:
            review_warnings = [
                "code_review distillation skipped: no review distiller registered"
            ]
        else:
            review_warnings = review_mem.warnings
    except Exception as exc:
        review_warnings = [f"code_review distillation skipped: {exc}"]
        logger.debug("code_review distillation failed for %s: %s", run_id, exc)

    return {
        "ok": True,
        "run_id": run_id,
        "memory_root": str(resolved_store.memory_root),
        "episodic_written": distilled.episodic_card is not None,
        "claim_count": len(distilled.claim_cards),
        "code_review_written": review_written,
        "writes": writes,
        "warnings": distilled.warnings + review_warnings,
    }


def _build_episodic_card(
    *,
    run_id: str,
    run_dir: Path,
    run_payload: dict[str, Any],
    observation: dict[str, Any] | None,
    analysis_bundle: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    trajectory: dict[str, Any] | None,
    execution_manifest: dict[str, Any] | None,
    session_snapshot: dict[str, Any] | None,
    trace_rows: list[dict[str, Any]],
    research_events: list[dict[str, Any]],
) -> EpisodicRunMemoryV1:
    status = _episodic_status(run_payload.get("status"))
    route = normalize_space((provenance or {}).get("route"))
    steps = run_payload.get("steps") if isinstance(run_payload.get("steps"), list) else []
    step_logs = _load_step_logs(run_dir=run_dir, steps=steps)
    tool_sequence = [
        normalize_space(step.get("tool_id"))
        for step in steps
        if isinstance(step, dict) and normalize_space(step.get("tool_id"))
    ]
    datasets = _extract_dataset_refs(observation, analysis_bundle, provenance)
    modalities = _extract_modalities(observation, analysis_bundle, provenance)
    execution_metadata = _extract_execution_metadata(observation, analysis_bundle)
    trajectory_metadata = _trajectory_metadata(trajectory)
    research_notes = _research_event_notes(research_events)
    research_tags = _research_event_tags(session_snapshot, research_events)
    manifest_stats = _manifest_stats(
        analysis_bundle=analysis_bundle,
        execution_manifest=execution_manifest,
    )
    task_description = _task_description(
        session_snapshot=session_snapshot,
        research_events=research_events,
        observation=observation,
        provenance=provenance,
        run_id=run_id,
        route=route,
        tool_sequence=tool_sequence,
    )
    task_type = route or (tool_sequence[0] if len(tool_sequence) == 1 else "mcp_run")
    key_parameters = _extract_key_parameters(steps)
    if execution_metadata:
        key_parameters["execution"] = execution_metadata
    if trajectory_metadata:
        key_parameters["trajectory"] = trajectory_metadata
    output_summary = _output_summary(
        status=status,
        run_dir=run_dir,
        steps=steps,
        session_snapshot=session_snapshot,
        observation=observation,
        step_logs=step_logs,
        research_notes=research_notes,
    )
    failure_mode = (
        normalize_space(run_payload.get("error"))
        or _failed_step_log_summary(step_logs)
        or _failed_step_summary(steps)
    )
    what_worked = unique_non_empty((session_snapshot or {}).get("done"))
    if not what_worked:
        what_worked.extend(_successful_step_log_summaries(step_logs))
        what_worked.extend(research_notes[:2])
        manifest_summary = _manifest_summary(manifest_stats)
        if manifest_summary:
            what_worked.append(manifest_summary)
        if tool_sequence:
            what_worked.append(f"Executed tool sequence: {', '.join(tool_sequence[:4])}.")
        if (run_dir / "analysis_bundle.json").exists():
            what_worked.append("Persisted canonical run bundle artifacts.")
    what_failed = unique_non_empty((session_snapshot or {}).get("open"))
    if not what_failed and failure_mode:
        what_failed.extend(_failed_step_log_summaries(step_logs) or [failure_mode])
    next_time_hints = unique_non_empty((session_snapshot or {}).get("open"))
    if (session_snapshot or {}).get("next_command"):
        next_time_hints.append(str(session_snapshot["next_command"]))
    quality_indicators = _quality_indicators(
        run_payload=run_payload,
        steps=steps,
        trace_rows=trace_rows,
        observation=observation,
        step_logs=step_logs,
        manifest_stats=manifest_stats,
        execution_metadata=execution_metadata,
        trajectory_metadata=trajectory_metadata,
        research_note_count=len(research_notes),
    )
    provenance_refs = [
        name
        for name in [
            "run.json",
            "observation.json",
            "analysis_bundle.json",
            "execution_manifest.json",
            "provenance.json",
            "trace.jsonl",
            "trajectory.json",
            "research_events.jsonl",
            "session_snapshot.json",
            *[entry["path"] for entry in step_logs[:3]],
        ]
        if (run_dir / name).exists()
    ]

    return EpisodicRunMemoryV1(
        source_run_id=run_id,
        source_session_id=normalize_space((session_snapshot or {}).get("session_id")) or None,
        task_description=task_description,
        task_type=task_type,
        dataset_refs=datasets,
        modality=modalities,
        tool_sequence=tool_sequence,
        key_parameters=key_parameters,
        workflow_pattern=route or None,
        status=status,
        output_summary=output_summary,
        failure_mode=failure_mode or None,
        quality_indicators=quality_indicators,
        what_worked=what_worked,
        what_failed=what_failed,
        next_time_hints=next_time_hints,
        resume_point=normalize_space((session_snapshot or {}).get("next_command")) or None,
        tags=_episodic_tags(
            status=status,
            route=route,
            task_type=task_type,
            tool_sequence=tool_sequence,
            dataset_refs=datasets,
            modalities=modalities,
            extra_tags=research_tags,
        ),
        provenance_refs=provenance_refs,
    )


def _build_claim_cards(
    *,
    run_id: str,
    run_dir: Path,
    run_payload: dict[str, Any],
    observation: dict[str, Any] | list[Any] | None,
    analysis_bundle: dict[str, Any] | list[Any] | None,
    provenance: dict[str, Any] | list[Any] | None,
    claim_updates: dict[str, Any] | list[Any] | None,
) -> list[ClaimMemoryV1]:
    candidate_sources: list[tuple[str, dict[str, Any] | list[Any] | None]] = [
        ("observation.json", observation),
        ("analysis_bundle.json", analysis_bundle),
        ("provenance.json", provenance),
    ]
    steps = run_payload.get("steps") if isinstance(run_payload.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        result_path = normalize_space(step.get("result_path"))
        if not result_path:
            continue
        payload = _load_json(run_dir / result_path)
        candidate_sources.append((result_path, payload))

    raw_claims: list[dict[str, Any]] = []
    for source_name, payload in candidate_sources:
        raw_claims.extend(_collect_claim_candidates(payload, source_name=source_name))

    by_key: dict[str, ClaimMemoryV1] = {}
    for raw in raw_claims:
        claim_card = _claim_card_from_candidate(run_id=run_id, raw=raw)
        if claim_card is None:
            continue
        if claim_card.stable_key in by_key:
            existing = by_key[claim_card.stable_key]
            merged_support = existing.supporting_evidence + claim_card.supporting_evidence
            merged_conflict = existing.conflicting_evidence + claim_card.conflicting_evidence
            by_key[claim_card.stable_key] = ClaimMemoryV1.model_validate(
                {
                    **existing.model_dump(exclude_none=True),
                    "source_run_ids": unique_non_empty(
                        existing.source_run_ids + claim_card.source_run_ids
                    ),
                    "target_ids": unique_non_empty(existing.target_ids + claim_card.target_ids),
                    "analytic_conditions": unique_non_empty(
                        existing.analytic_conditions + claim_card.analytic_conditions
                    ),
                    "supporting_evidence": [
                        item.model_dump(exclude_none=True) for item in merged_support
                    ],
                    "conflicting_evidence": [
                        item.model_dump(exclude_none=True) for item in merged_conflict
                    ],
                    "tags": unique_non_empty(existing.tags + claim_card.tags),
                }
            )
        else:
            by_key[claim_card.stable_key or claim_card.card_id or f"claim:{len(by_key)}"] = claim_card
    claim_cards = list(by_key.values())
    return _apply_claim_updates_to_cards(
        claim_cards,
        claim_updates=claim_updates,
        run_id=run_id,
    )


def _parse_claim_updates(
    payload: dict[str, Any] | list[Any] | None,
) -> list[dict[str, Any]]:
    from brain_researcher.core.contracts import ClaimUpdateV1

    if not isinstance(payload, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(
                ClaimUpdateV1.model_validate(item).model_dump(exclude_none=True)
            )
        except Exception:
            continue
    return parsed


def _claim_card_aliases(card: ClaimMemoryV1) -> set[str]:
    aliases: set[str] = set()
    if card.stable_key:
        aliases.add(card.stable_key)
        if card.stable_key.startswith("claim_memory:"):
            aliases.add(card.stable_key.removeprefix("claim_memory:"))
    if card.card_id:
        aliases.add(card.card_id)
    for evidence in [*card.supporting_evidence, *card.conflicting_evidence]:
        if evidence.claim_id:
            aliases.add(evidence.claim_id)
    for tag in card.tags:
        if ":" not in tag:
            continue
        prefix, value = tag.split(":", 1)
        if prefix in {"canonical_claim_id", "card_id"} and value.strip():
            aliases.add(value.strip())
    return {normalize_space(alias) for alias in aliases if normalize_space(alias)}


def _claim_update_target_ids(update: dict[str, Any]) -> list[str]:
    targets = [
        normalize_space(update.get("canonical_claim_id")),
        normalize_space(update.get("claim_id")),
    ]
    if normalize_space(update.get("canonical_claim_id")):
        targets.append(
            f"claim_memory:{normalize_space(update.get('canonical_claim_id'))}"
        )
    if normalize_space(update.get("claim_id")):
        targets.append(f"claim_memory:{normalize_space(update.get('claim_id'))}")
    return unique_non_empty(targets)


def _claim_card_match_indices(
    alias_index: dict[str, list[int]],
    *,
    claim_id: str | None = None,
    canonical_claim_id: str | None = None,
) -> list[int]:
    indices: list[int] = []
    for key in _claim_update_target_ids(
        {"claim_id": claim_id, "canonical_claim_id": canonical_claim_id}
    ):
        indices.extend(alias_index.get(key, []))
    return list(dict.fromkeys(indices))


def _claim_update_evidence_ref(
    *,
    run_id: str,
    update: dict[str, Any],
    source_ref: str,
) -> ClaimEvidenceRefV1:
    action = normalize_space(update.get("action")) or "support"
    return ClaimEvidenceRefV1(
        run_id=run_id,
        claim_id=normalize_space(update.get("canonical_claim_id"))
        or normalize_space(update.get("claim_id")),
        polarity=action,
        confidence="moderate",
        source_ref=source_ref,
        description=normalize_space(update.get("note"))
        or normalize_space(update.get("rationale"))
        or f"claim update action: {action}",
    )


def _merge_claim_relation_links(
    existing: list[ClaimRelationLinkV1],
    incoming: list[ClaimRelationLinkV1],
) -> list[ClaimRelationLinkV1]:
    merged: dict[tuple[str, str], ClaimRelationLinkV1] = {}
    for item in [*existing, *incoming]:
        key = (item.claim_id, item.relation)
        if key not in merged:
            merged[key] = item
    return list(merged.values())


def _claim_update_extra_entry(
    *,
    update: dict[str, Any],
    run_id: str,
    source_ref: str,
    applied_role: str,
) -> dict[str, Any]:
    normalized_update: dict[str, Any] = {}
    for key, value in update.items():
        if isinstance(value, str):
            text = normalize_space(value)
            if text:
                normalized_update[key] = text
        elif value is not None:
            normalized_update[key] = value
    return {
        "action": normalize_space(update.get("action")) or "support",
        "claim_id": normalize_space(update.get("claim_id")) or None,
        "canonical_claim_id": normalize_space(update.get("canonical_claim_id")) or None,
        "supersedes_claim_id": normalize_space(update.get("supersedes_claim_id")) or None,
        "updated_at": normalize_space(update.get("updated_at")) or None,
        "note": normalize_space(update.get("note")) or None,
        "run_id": run_id,
        "source_ref": source_ref,
        "applied_role": applied_role,
        "update": normalized_update,
    }


def _merge_claim_update_extra(
    extra: Mapping[str, Any] | None,
    *,
    entry: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(extra or {})
    claim_updates = merged.get("claim_updates")
    existing_entries = claim_updates if isinstance(claim_updates, list) else []
    serialized_seen = {
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in existing_entries
        if isinstance(item, dict)
    }
    serialized_entry = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    if serialized_entry not in serialized_seen:
        merged["claim_updates"] = [
            *[item for item in existing_entries if isinstance(item, dict)],
            entry,
        ]
    else:
        merged["claim_updates"] = [
            *[item for item in existing_entries if isinstance(item, dict)]
        ]
    return merged


def _with_claim_update_applied(
    card: ClaimMemoryV1,
    *,
    update: dict[str, Any],
    run_id: str,
    source_ref: str,
) -> ClaimMemoryV1:
    action = normalize_space(update.get("action")) or "support"
    payload = card.model_dump(exclude_none=True)
    payload["source_run_ids"] = unique_non_empty([*card.source_run_ids, run_id])
    payload["extra"] = _merge_claim_update_extra(
        card.extra,
        entry=_claim_update_extra_entry(
            update=update,
            run_id=run_id,
            source_ref=source_ref,
            applied_role="direct",
        ),
    )
    payload["analytic_conditions"] = unique_non_empty(
        [*card.analytic_conditions, f"claim_update:{action}"]
    )
    payload["last_tested_at"] = (
        normalize_space(update.get("updated_at")) or card.last_tested_at
    )
    payload["times_tested"] = max(int(card.times_tested or 0) + 1, 1)

    evidence_ref = _claim_update_evidence_ref(
        run_id=run_id,
        update=update,
        source_ref=source_ref,
    )
    if action == "support":
        payload["supporting_evidence"] = [
            *[item.model_dump(exclude_none=True) for item in card.supporting_evidence],
            evidence_ref.model_dump(exclude_none=True),
        ]
    elif action in {"weaken", "refute"}:
        payload["conflicting_evidence"] = [
            *[item.model_dump(exclude_none=True) for item in card.conflicting_evidence],
            evidence_ref.model_dump(exclude_none=True),
        ]
    elif action == "supersede" and normalize_space(update.get("supersedes_claim_id")):
        related = _merge_claim_relation_links(
            card.related_claims,
            [
                ClaimRelationLinkV1(
                    claim_id=normalize_space(update.get("supersedes_claim_id")) or "",
                    relation="supersedes",
                    note=normalize_space(update.get("note"))
                    or "Supersedes an earlier claim according to claim_update.json.",
                )
            ],
        )
        payload["related_claims"] = [
            item.model_dump(exclude_none=True) for item in related
        ]
        payload["supporting_evidence"] = [
            *[item.model_dump(exclude_none=True) for item in card.supporting_evidence],
            evidence_ref.model_dump(exclude_none=True),
        ]

    return ClaimMemoryV1.model_validate(payload)


def _mark_claim_superseded(
    card: ClaimMemoryV1,
    *,
    superseded_by: str,
    note: str | None = None,
    update: dict[str, Any] | None = None,
    run_id: str | None = None,
    source_ref: str | None = None,
) -> ClaimMemoryV1:
    payload = card.model_dump(exclude_none=True)
    payload["status"] = "superseded"
    payload["superseded_by"] = superseded_by
    if update is not None and run_id and source_ref:
        payload["extra"] = _merge_claim_update_extra(
            card.extra,
            entry=_claim_update_extra_entry(
                update=update,
                run_id=run_id,
                source_ref=source_ref,
                applied_role="superseded_target",
            ),
        )
    payload["analytic_conditions"] = unique_non_empty(
        [*card.analytic_conditions, "claim_update:superseded"]
    )
    if note:
        related = _merge_claim_relation_links(
            card.related_claims,
            [
                ClaimRelationLinkV1(
                    claim_id=superseded_by,
                    relation="refines",
                    note=note,
                )
            ],
        )
        payload["related_claims"] = [
            item.model_dump(exclude_none=True) for item in related
        ]
    return ClaimMemoryV1.model_validate(payload)


def _apply_claim_updates_to_cards(
    claim_cards: list[ClaimMemoryV1],
    *,
    claim_updates: dict[str, Any] | list[Any] | None,
    run_id: str,
) -> list[ClaimMemoryV1]:
    parsed_updates = _parse_claim_updates(claim_updates)
    if not parsed_updates or not claim_cards:
        return claim_cards

    updated_cards = list(claim_cards)
    alias_index: dict[str, list[int]] = {}
    for idx, card in enumerate(updated_cards):
        for alias in _claim_card_aliases(card):
            alias_index.setdefault(alias, []).append(idx)

    for idx, update in enumerate(parsed_updates):
        current_indices = _claim_card_match_indices(
            alias_index,
            claim_id=normalize_space(update.get("claim_id")) or None,
            canonical_claim_id=normalize_space(update.get("canonical_claim_id")) or None,
        )
        if not current_indices:
            continue
        source_ref = f"claim_update.json[{idx}]"
        for card_index in current_indices:
            updated_cards[card_index] = _with_claim_update_applied(
                updated_cards[card_index],
                update=update,
                run_id=run_id,
                source_ref=source_ref,
            )

        if normalize_space(update.get("action")) == "supersede":
            superseded_id = normalize_space(update.get("supersedes_claim_id"))
            replacement_id = normalize_space(update.get("canonical_claim_id")) or normalize_space(
                update.get("claim_id")
            )
            if superseded_id and replacement_id:
                superseded_indices = _claim_card_match_indices(
                    alias_index,
                    claim_id=superseded_id,
                    canonical_claim_id=None,
                )
                for card_index in superseded_indices:
                    if card_index in current_indices:
                        continue
                    updated_cards[card_index] = _mark_claim_superseded(
                        updated_cards[card_index],
                        superseded_by=replacement_id,
                        note=normalize_space(update.get("note")) or None,
                        update=update,
                        run_id=run_id,
                        source_ref=source_ref,
                    )

    return updated_cards


def _task_description(
    *,
    session_snapshot: dict[str, Any] | None,
    research_events: list[dict[str, Any]],
    observation: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    run_id: str,
    route: str,
    tool_sequence: list[str],
) -> str:
    goal = normalize_space((session_snapshot or {}).get("goal"))
    if goal:
        return goal
    for event in research_events:
        if normalize_token_text(event.get("kind")) == "start":
            content = normalize_space(event.get("content"))
            if content:
                return content
    run_card = (observation or {}).get("run_card") if isinstance(observation, dict) else {}
    if isinstance(run_card, dict):
        for key in ("description", "title"):
            value = normalize_space(run_card.get(key))
            if value:
                return value
    request = (provenance or {}).get("request") if isinstance(provenance, dict) else {}
    if isinstance(request, dict):
        for key in ("query", "question", "summary", "tool_id"):
            value = normalize_space(request.get(key))
            if value:
                return value
    if tool_sequence:
        return f"Run {run_id} executed {' -> '.join(tool_sequence[:3])} via {route or 'mcp'}."
    return f"Run {run_id} completed via {route or 'mcp'}."


def _output_summary(
    *,
    status: str,
    run_dir: Path,
    steps: list[dict[str, Any]],
    session_snapshot: dict[str, Any] | None,
    observation: dict[str, Any] | None,
    step_logs: list[dict[str, Any]],
    research_notes: list[str],
) -> str:
    done_items = unique_non_empty((session_snapshot or {}).get("done"))
    if done_items:
        return "; ".join(done_items[:3])
    success_summaries = _successful_step_log_summaries(step_logs)
    if success_summaries:
        return "; ".join(success_summaries[:2])
    if research_notes:
        return "; ".join(research_notes[:1])
    artifact_count = 0
    if isinstance(observation, dict) and isinstance(observation.get("artifacts"), list):
        artifact_count = len(observation["artifacts"])
    succeeded = sum(
        1
        for step in steps
        if isinstance(step, dict) and normalize_token_text(step.get("status")) == "succeeded"
    )
    bundle_bits = [
        name
        for name in ["observation.json", "analysis_bundle.json", "trajectory.json"]
        if (run_dir / name).exists()
    ]
    return (
        f"Status={status}; succeeded_steps={succeeded}/{len(steps)}; "
        f"artifacts={artifact_count}; bundle_files={', '.join(bundle_bits) or 'none'}."
    )


def _quality_indicators(
    *,
    run_payload: dict[str, Any],
    steps: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
    observation: dict[str, Any] | None,
    step_logs: list[dict[str, Any]],
    manifest_stats: dict[str, Any],
    execution_metadata: dict[str, Any],
    trajectory_metadata: dict[str, Any],
    research_note_count: int,
) -> dict[str, Any]:
    failed_steps = sum(
        1
        for step in steps
        if isinstance(step, dict) and normalize_token_text(step.get("status")) not in {"succeeded", ""}
    )
    artifacts = observation.get("artifacts") if isinstance(observation, dict) else []
    violations = observation.get("violations") if isinstance(observation, dict) else []
    log_statuses = [normalize_token_text(item.get("status")) for item in step_logs]
    return {
        "step_count": len(steps),
        "failed_step_count": failed_steps,
        "trace_event_count": len(trace_rows),
        "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "violation_count": len(violations) if isinstance(violations, list) else 0,
        "step_log_count": len(step_logs),
        "successful_log_count": sum(
            1 for item in log_statuses if item in {"success", "succeeded"}
        ),
        "failed_log_count": sum(1 for item in log_statuses if item in {"failed", "error"}),
        "file_manifest_count": manifest_stats.get("file_manifest_count", 0),
        "verified_checksum_count": manifest_stats.get("verified_checksum_count", 0),
        "execution_manifest_step_count": manifest_stats.get("execution_manifest_step_count", 0),
        "trajectory_step_count": trajectory_metadata.get("step_count", 0),
        "research_note_count": research_note_count,
        "selected_tool": normalize_space(execution_metadata.get("selected_tool")) or None,
        "execution_provider": normalize_space(execution_metadata.get("provider")) or None,
        "transport": normalize_space(execution_metadata.get("transport")) or None,
        "status": normalize_space(run_payload.get("status")) or "unknown",
    }


def _failed_step_summary(steps: list[dict[str, Any]]) -> str:
    failed = [
        f"{normalize_space(step.get('tool_id'))}: {normalize_space(step.get('error')) or normalize_space(step.get('status'))}"
        for step in steps
        if isinstance(step, dict) and normalize_token_text(step.get("status")) not in {"succeeded", ""}
    ]
    return "; ".join(item for item in failed if item)


def _load_step_logs(
    *,
    run_dir: Path,
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []

    step_tool_by_result_path = {
        normalize_space(step.get("result_path")): normalize_space(step.get("tool_id"))
        for step in steps
        if isinstance(step, dict) and normalize_space(step.get("result_path"))
    }
    loaded: list[dict[str, Any]] = []
    for path in sorted(logs_dir.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        source_name = str(path.relative_to(run_dir))
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        tool_id = normalize_space(
            metadata.get("tool_id")
            or metadata.get("tool")
            or metadata.get("tool_name")
            or step_tool_by_result_path.get(source_name)
        )
        loaded.append(
            {
                "path": source_name,
                "status": normalize_space(payload.get("status")) or None,
                "tool_id": tool_id or None,
                "error": normalize_space(payload.get("error")) or None,
                "metadata": metadata,
                "data": payload.get("data"),
            }
        )
    return loaded


def _successful_step_log_summaries(step_logs: list[dict[str, Any]]) -> list[str]:
    return unique_non_empty(
        [_step_log_success_summary(item) for item in step_logs if _is_successful_step_log(item)]
    )


def _failed_step_log_summaries(step_logs: list[dict[str, Any]]) -> list[str]:
    return unique_non_empty(
        [_step_log_failure_summary(item) for item in step_logs if _is_failed_step_log(item)]
    )


def _failed_step_log_summary(step_logs: list[dict[str, Any]]) -> str:
    return "; ".join(_failed_step_log_summaries(step_logs)[:3])


def _is_successful_step_log(item: dict[str, Any]) -> bool:
    return normalize_token_text(item.get("status")) in {"success", "succeeded"}


def _is_failed_step_log(item: dict[str, Any]) -> bool:
    return normalize_token_text(item.get("status")) in {"failed", "error"}


def _step_log_success_summary(item: dict[str, Any]) -> str:
    tool = normalize_space(item.get("tool_id")) or "step"
    detail = _compact_step_log_data(item.get("data"))
    return f"{tool} succeeded ({detail})." if detail else f"{tool} succeeded."


def _step_log_failure_summary(item: dict[str, Any]) -> str:
    tool = normalize_space(item.get("tool_id")) or "step"
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    error_type = normalize_space(metadata.get("error_type"))
    error_category = normalize_space(metadata.get("error_category"))
    error_bits = "/".join(bit for bit in [error_type, error_category] if bit)
    error_text = normalize_space(item.get("error"))
    if not error_text:
        error_text = _compact_step_log_data(item.get("data"))
    prefix = f"{tool} failed"
    if error_bits:
        prefix += f" [{error_bits}]"
    if error_text:
        prefix += f": {error_text}"
    return prefix


def _compact_step_log_data(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("would_execute") and len(value) <= 2:
            return "dry-run preview prepared"
        for key in ("summary", "answer"):
            text = normalize_space(value.get(key))
            if text:
                return text
        bits: list[str] = []
        for key in ("task_name", "matched_task", "query_concept"):
            text = normalize_space(value.get(key))
            if text:
                bits.append(f"{key}={text}")
        for key in ("n_concepts", "graph_depth", "confidence"):
            raw = value.get(key)
            if isinstance(raw, int | float | str) and normalize_space(raw):
                bits.append(f"{key}={raw}")
        for key in ("concepts", "related_concepts", "outputs", "paths", "warnings"):
            raw = value.get(key)
            if isinstance(raw, list):
                bits.append(f"{key}={len(raw)} items")
        if not bits and isinstance(value.get("policy_issues"), list):
            bits.append(f"policy_issues={len(value.get('policy_issues') or [])}")
        if bits:
            return "; ".join(bits[:3])
        return "keys=" + ",".join(sorted(str(key) for key in value.keys())[:4])
    text = normalize_space(value)
    return text or ""


def _extract_dataset_refs(
    observation: dict[str, Any] | None,
    analysis_bundle: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
) -> list[str]:
    out: list[str] = []
    for payload in [observation, analysis_bundle]:
        if not isinstance(payload, dict):
            continue
        run_card = payload.get("run_card")
        if isinstance(run_card, dict) and isinstance(run_card.get("datasets"), list):
            for dataset in run_card.get("datasets") or []:
                if not isinstance(dataset, dict):
                    continue
                out.extend(
                    unique_non_empty(
                        [
                            dataset.get("id"),
                            dataset.get("dataset_id"),
                            dataset.get("name"),
                        ]
                    )
                )
    request = (provenance or {}).get("request")
    if isinstance(request, dict):
        out.extend(
            unique_non_empty(
                [
                    request.get("dataset_ref"),
                    request.get("dataset_id"),
                    request.get("dataset"),
                ]
            )
        )
    return unique_non_empty(out)


def _extract_modalities(
    observation: dict[str, Any] | None,
    analysis_bundle: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
) -> list[str]:
    out: list[str] = []
    for payload in [observation, analysis_bundle]:
        if not isinstance(payload, dict):
            continue
        run_card = payload.get("run_card")
        if isinstance(run_card, dict):
            datasets = run_card.get("datasets")
            if isinstance(datasets, list):
                for dataset in datasets:
                    if isinstance(dataset, dict):
                        out.extend(unique_non_empty([dataset.get("modality"), dataset.get("type")]))
    request = (provenance or {}).get("request")
    if isinstance(request, dict):
        modalities = request.get("modality")
        if isinstance(modalities, list):
            out.extend(unique_non_empty(modalities))
        else:
            out.extend(unique_non_empty([modalities]))
    return unique_non_empty(out)


def _extract_key_parameters(steps: list[dict[str, Any]]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for step in steps[:3]:
        if not isinstance(step, dict):
            continue
        tool_id = normalize_space(step.get("tool_id")) or "tool"
        params = step.get("params")
        if not isinstance(params, dict):
            continue
        compact: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str | int | float | bool) and normalize_space(value):
                compact[str(key)] = value
            elif isinstance(value, list) and len(value) <= 4:
                compact[str(key)] = value
            if len(compact) >= 5:
                break
        if compact:
            selected[tool_id] = compact
    return selected


def _extract_execution_metadata(
    observation: dict[str, Any] | None,
    analysis_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    execution: dict[str, Any] = {}
    for payload in [observation, analysis_bundle]:
        if not isinstance(payload, dict):
            continue
        run_card = payload.get("run_card")
        if not isinstance(run_card, dict):
            continue
        raw_execution = run_card.get("execution")
        if not isinstance(raw_execution, dict):
            continue
        for key in ("provider", "model", "selected_tool", "tool_mode", "transport"):
            value = raw_execution.get(key)
            if normalize_space(value):
                execution[key] = value
        if "dry_run" in raw_execution:
            execution["dry_run"] = bool(raw_execution.get("dry_run"))
        usage = raw_execution.get("usage")
        if isinstance(usage, dict):
            usage_compact = {
                key: value
                for key, value in usage.items()
                if key in {"input_tokens", "output_tokens", "total_tokens", "cost_usd"}
                and isinstance(value, int | float)
            }
            if usage_compact:
                execution["usage"] = usage_compact
        if execution:
            break
    return execution


def _manifest_stats(
    *,
    analysis_bundle: dict[str, Any] | None,
    execution_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    file_manifest = (
        analysis_bundle.get("file_manifest")
        if isinstance(analysis_bundle, dict)
        and isinstance(analysis_bundle.get("file_manifest"), list)
        else []
    )
    execution_steps = (
        execution_manifest.get("steps")
        if isinstance(execution_manifest, dict)
        and isinstance(execution_manifest.get("steps"), list)
        else []
    )
    return {
        "file_manifest_count": len(file_manifest),
        "verified_checksum_count": sum(
            1
            for item in file_manifest
            if isinstance(item, dict)
            and normalize_token_text(item.get("checksum_status")) == "ok"
        ),
        "execution_manifest_step_count": len(execution_steps),
        "manifest_roles": unique_non_empty(
            [
                item.get("role")
                for item in file_manifest
                if isinstance(item, dict) and normalize_space(item.get("role"))
            ]
        ),
    }


def _manifest_summary(manifest_stats: dict[str, Any]) -> str:
    file_count = int(manifest_stats.get("file_manifest_count") or 0)
    if file_count <= 0:
        return ""
    checksum_count = int(manifest_stats.get("verified_checksum_count") or 0)
    roles = unique_non_empty(manifest_stats.get("manifest_roles"))
    role_text = f" roles={', '.join(roles[:3])}" if roles else ""
    return (
        f"Captured {file_count} manifest entries with {checksum_count} verified checksums."
        f"{role_text}"
    )


def _episodic_status(value: Any) -> str:
    normalized = normalize_token_text(value)
    if normalized in {"succeeded", "success"}:
        return "success"
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"running", "queued", "cancelled", "canceled"}:
        return "interrupted"
    return "partial"


def _episodic_tags(
    *,
    status: str,
    route: str,
    task_type: str,
    tool_sequence: list[str],
    dataset_refs: list[str],
    modalities: list[str],
    extra_tags: list[str] | None = None,
) -> list[str]:
    return unique_non_empty(
        [
            status,
            route,
            task_type,
            *tool_sequence[:4],
            *dataset_refs[:3],
            *modalities[:3],
            *(extra_tags or []),
        ]
    )


def _research_event_notes(research_events: list[dict[str, Any]]) -> list[str]:
    return unique_non_empty(
        [
            _truncate_summary_text(event.get("content"))
            for event in research_events
            if normalize_token_text(event.get("kind")) == "note"
        ]
    )


def _research_event_tags(
    session_snapshot: dict[str, Any] | None,
    research_events: list[dict[str, Any]],
) -> list[str]:
    tags: list[str] = []
    if isinstance(session_snapshot, dict):
        tags.extend(unique_non_empty(session_snapshot.get("tags")))
        source_client = normalize_space(session_snapshot.get("source_client"))
        if source_client:
            tags.append(f"source_client:{source_client}")
    for event in research_events:
        raw_tags = event.get("tags")
        if isinstance(raw_tags, list):
            tags.extend(unique_non_empty(raw_tags))
    return unique_non_empty(tags)


def _trajectory_metadata(trajectory: dict[str, Any] | None) -> dict[str, Any]:
    steps = (
        trajectory.get("steps")
        if isinstance(trajectory, dict) and isinstance(trajectory.get("steps"), list)
        else []
    )
    if not steps:
        return {}
    sources = unique_non_empty(
        [
            step.get("source")
            for step in steps
            if isinstance(step, dict) and normalize_space(step.get("source"))
        ]
    )
    return {
        "step_count": len(steps),
        "sources": sources,
    }


def _truncate_summary_text(value: Any, *, limit: int = 240) -> str:
    text = normalize_space(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _collect_claim_candidates(
    payload: dict[str, Any] | list[Any] | None,
    *,
    source_name: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            candidate = _claim_candidate_from_node(node)
            if candidate is not None:
                candidate["source_ref"] = f"{source_name}{path}"
                results.append(candidate)
            for key, value in node.items():
                _walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                _walk(value, f"{path}[{index}]")

    _walk(payload, "")
    deduped: dict[str, dict[str, Any]] = {}
    for item in results:
        identity = "||".join(
            [
                normalize_token_text(item.get("claim_id")),
                normalize_token_text(item.get("canonical_claim_id")),
                normalize_token_text(item.get("claim_text")),
                normalize_token_text(item.get("target_id")),
                normalize_token_text(item.get("polarity")),
            ]
        )
        deduped.setdefault(identity, item)
    return list(deduped.values())


def _claim_candidate_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    legacy_candidate = _legacy_claim_candidate_from_node(node)
    if legacy_candidate is not None:
        return legacy_candidate
    return _candidate_card_claim_candidate(node)


def _legacy_claim_candidate_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    claim_text = normalize_space(
        node.get("claim_text")
        or node.get("claim_statement")
        or node.get("text")
        or (node.get("claim") or {}).get("text")
    )
    if not claim_text:
        return None
    if not any(key in node for key in _CLAIM_IDENTITY_KEYS) and not (
        isinstance(node.get("claim"), dict) and any(key in node.get("claim", {}) for key in ("id", "polarity", "claim_strength"))
    ):
        return None

    claim_block = node.get("claim") if isinstance(node.get("claim"), dict) else {}
    target_block = node.get("target") if isinstance(node.get("target"), dict) else {}
    mapping_block = node.get("mapping") if isinstance(node.get("mapping"), dict) else {}
    variables_block = node.get("variables") if isinstance(node.get("variables"), dict) else {}
    run_block = node.get("run") if isinstance(node.get("run"), dict) else {}
    paper_block = node.get("paper") if isinstance(node.get("paper"), dict) else {}
    evidence_block = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}

    target_id = normalize_space(
        node.get("target_id")
        or target_block.get("id")
        or mapping_block.get("canonical_id")
    )
    claim_id = normalize_space(node.get("claim_id") or claim_block.get("id"))
    canonical_claim_id = normalize_space(node.get("canonical_claim_id"))
    polarity = normalize_space(
        node.get("polarity")
        or node.get("claim_polarity")
        or claim_block.get("polarity")
    )
    if not polarity:
        expected_verdict = normalize_token_text(node.get("expected_verdict"))
        if expected_verdict in {"supported", "support", "positive"}:
            polarity = "supports"
        elif expected_verdict in {"conflicting", "refuted", "refutes", "negative"}:
            polarity = "refutes"
    source_records = node.get("source_records") if isinstance(node.get("source_records"), list) else []
    if not target_id and source_records:
        first = next((item for item in source_records if isinstance(item, dict)), None)
        if isinstance(first, dict):
            target_id = normalize_space(first.get("target_id"))
            if not polarity:
                polarity = normalize_space(first.get("polarity"))

    evidence_quality_score = (
        node.get("evidence_quality_score")
        or variables_block.get("evidence_quality_score")
        or claim_block.get("evidence_quality_score")
    )
    claim_strength = (
        node.get("claim_strength")
        or variables_block.get("claim_strength")
        or claim_block.get("claim_strength")
    )
    paper_id = normalize_space(node.get("paper_id") or paper_block.get("id"))
    run_id = normalize_space(node.get("run_id") or run_block.get("run_id"))
    evidence_quote = normalize_space(
        evidence_block.get("quote")
        or node.get("evidence_quote")
        or node.get("quote_text")
    )
    if not claim_id and not canonical_claim_id and not target_id:
        return None
    return {
        "claim_text": claim_text,
        "claim_id": claim_id or None,
        "canonical_claim_id": canonical_claim_id or None,
        "target_id": target_id or None,
        "target_type": normalize_space(node.get("target_type") or target_block.get("type")) or None,
        "polarity": polarity or None,
        "claim_type": normalize_space(
            node.get("claim_kind")
            or node.get("claim_type")
            or claim_block.get("claim_kind")
            or claim_block.get("kind")
        )
        or None,
        "claim_strength": claim_strength,
        "evidence_quality_score": evidence_quality_score,
        "paper_id": paper_id or None,
        "run_id": run_id or None,
        "source_records": source_records,
        "evidence_quote": evidence_quote or None,
        "analytic_conditions": unique_non_empty(
            [
                node.get("relation_mode"),
                node.get("snapshot_role"),
                node.get("section"),
                evidence_block.get("section"),
            ]
        ),
        "related_claim_id": normalize_space(
            node.get("related_claim_id") or claim_block.get("related_claim_id")
        )
        or None,
    }


def _candidate_card_claim_candidate(node: dict[str, Any]) -> dict[str, Any] | None:
    if not _looks_like_candidate_card(node):
        return None
    claim_text = _candidate_card_claim_text(node)
    if not claim_text:
        return None

    mapping = _candidate_card_claim_mapping(node, claim_text=claim_text)
    if not mapping:
        return None

    provenance = node.get("provenance") if isinstance(node.get("provenance"), dict) else {}
    kg_verification = (
        node.get("kg_verification") if isinstance(node.get("kg_verification"), dict) else {}
    )
    extra_target_ids = unique_non_empty(mapping.get("target_ids") or [])
    target_id = normalize_space(mapping.get("canonical_target_id")) or (
        extra_target_ids[0] if extra_target_ids else ""
    )
    if not target_id:
        return None

    evidence_quote = normalize_space(
        node.get("evidence_summary")
        or node.get("minimal_discriminating_test")
        or node.get("falsifier_hint")
    )
    support_paper_ids = provenance.get("supporting_paper_ids")
    support_paper_id = (
        _candidate_card_scalar(_first_list_item(support_paper_ids))
        if isinstance(support_paper_ids, list)
        else _candidate_card_scalar(support_paper_ids)
    )
    paper_id = _candidate_card_scalar(provenance.get("paper_id")) or support_paper_id
    has_normalized_claim = isinstance(kg_verification.get("normalized_claim"), Mapping)

    return {
        "claim_text": claim_text,
        "claim_id": normalize_space(node.get("card_id")) or mapping.get("canonical_claim_id"),
        "canonical_claim_id": mapping.get("canonical_claim_id"),
        "canonical_target_id": mapping.get("canonical_target_id"),
        "target_id": target_id,
        "target_ids": extra_target_ids,
        "target_type": normalize_space(mapping.get("target_type")) or None,
        "polarity": normalize_space(mapping.get("claim_polarity")) or None,
        "claim_type": "verification" if has_normalized_claim else "candidate_hypothesis",
        "claim_strength": _first_numeric(
            provenance.get("avg_confidence"),
            node.get("principle_confidence"),
            node.get("query_relevance_score"),
            node.get("wow_score"),
        ),
        "evidence_quality_score": _first_numeric(
            provenance.get("avg_evidence_quality"),
            node.get("query_relevance_score"),
            node.get("testability"),
        ),
        "paper_id": paper_id or None,
        "run_id": None,
        "source_records": [],
        "evidence_quote": evidence_quote or None,
        "analytic_conditions": unique_non_empty(
            [
                "candidate_card",
                normalize_space(node.get("grounding_status")),
                normalize_space(node.get("quality_bucket")),
                normalize_space(node.get("rewrite_status")),
                normalize_space(provenance.get("relation_hint")),
                normalize_space(mapping.get("predicate")),
            ]
        ),
        "related_claim_id": None,
        "extra_tags": unique_non_empty(
            [
                *list(mapping.get("tags") or []),
                "candidate_card",
                normalize_space(node.get("card_id")) and f"card_id:{node.get('card_id')}",
                normalize_space(node.get("taste_axis"))
                and f"taste_axis:{node.get('taste_axis')}",
                normalize_space(node.get("grounding_status"))
                and f"grounding_status:{node.get('grounding_status')}",
            ]
        ),
    }


def _looks_like_candidate_card(node: dict[str, Any]) -> bool:
    return bool(
        normalize_space(node.get("card_id"))
        and (
            normalize_space(node.get("hypothesis"))
            or normalize_space(node.get("testable_hypothesis"))
            or normalize_space(node.get("raw_hypothesis"))
            or normalize_space(node.get("title"))
        )
    )


def _candidate_card_claim_text(node: dict[str, Any]) -> str:
    return normalize_space(
        node.get("testable_hypothesis")
        or node.get("hypothesis")
        or node.get("raw_hypothesis")
        or node.get("title")
        or node.get("idea")
    )


def _candidate_card_claim_mapping(
    node: dict[str, Any],
    *,
    claim_text: str,
) -> dict[str, Any] | None:
    kg_verification = (
        node.get("kg_verification") if isinstance(node.get("kg_verification"), dict) else {}
    )
    normalized_claim = (
        kg_verification.get("normalized_claim")
        if isinstance(kg_verification.get("normalized_claim"), Mapping)
        else None
    )
    verdict = normalize_space(kg_verification.get("verdict")) or None
    if normalized_claim:
        return build_verification_claim_mapping(
            hypothesis=claim_text,
            normalized_claim=normalized_claim,
            verdict=verdict,
        )

    provenance = node.get("provenance") if isinstance(node.get("provenance"), dict) else {}
    seed_kg_id = _candidate_card_scalar(provenance.get("seed_kg_id"))
    subject = (
        _candidate_card_entity(
            seed_kg_id,
            fallback_label=None,
            fallback_prefix="candidate_subject",
            treat_scalar_as_id=True,
        )
        if seed_kg_id
        else _candidate_card_entity(
            _first_list_item(provenance.get("top_subjects")),
            fallback_label=None,
            fallback_prefix="candidate_subject",
        )
    )
    candidate_kg_id = _candidate_card_scalar(provenance.get("candidate_kg_id"))
    object_entity = (
        _candidate_card_entity(
            candidate_kg_id,
            fallback_label=normalize_space(provenance.get("object_label")) or None,
            fallback_prefix="candidate_object",
            treat_scalar_as_id=True,
        )
        if candidate_kg_id
        else _candidate_card_entity(
            provenance.get("object_label") or node.get("title") or claim_text,
            fallback_label=normalize_space(provenance.get("object_label")) or None,
            fallback_prefix="candidate_object",
        )
    )
    predicate = (
        normalize_space(provenance.get("relation_hint"))
        or _candidate_card_scalar(_first_list_item(provenance.get("top_predicates")))
        or "related_to"
    )
    if not subject and not object_entity:
        return None
    normalized_fallback = {
        "subject": subject or {},
        "object": object_entity or {},
        "predicate": predicate,
        "raw": claim_text,
    }
    return build_verification_claim_mapping(
        hypothesis=claim_text,
        normalized_claim=normalized_fallback,
        verdict=verdict,
    )


def _candidate_card_entity(
    raw: Any,
    *,
    fallback_label: str | None,
    fallback_prefix: str,
    treat_scalar_as_id: bool = False,
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        kg_id = _candidate_card_scalar(
            raw.get("kg_id") or raw.get("id") or raw.get("element_id")
        )
        label = _candidate_card_scalar(raw.get("label")) or fallback_label or kg_id
        if not kg_id and label:
            kg_id = _candidate_card_fallback_id(fallback_prefix, label)
        node_type = _candidate_card_scalar(raw.get("node_type")) or "Entity"
        return (
            {"kg_id": kg_id, "label": label, "node_type": node_type}
            if kg_id or label
            else {}
        )

    text = _candidate_card_scalar(raw) or fallback_label
    if not text:
        return {}
    if treat_scalar_as_id:
        return {
            "kg_id": text,
            "label": fallback_label or text,
            "node_type": "Entity",
        }
    return {
        "kg_id": _candidate_card_fallback_id(fallback_prefix, text),
        "label": text,
        "node_type": "Entity",
    }


def _candidate_card_fallback_id(prefix: str, value: Any) -> str | None:
    text = normalize_token_text(value).replace(" ", "_")
    if not text:
        return None
    return f"{prefix}:{text[:120]}"


def _candidate_card_scalar(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("label", "kg_id", "id", "element_id", "name"):
            text = normalize_space(value.get(key))
            if text:
                return text
        return None
    text = normalize_space(value)
    return text or None


def _first_list_item(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else None


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, int | float):
            return float(value)
    return None


def _claim_card_from_candidate(
    *,
    run_id: str,
    raw: dict[str, Any],
) -> ClaimMemoryV1 | None:
    claim_text = normalize_space(raw.get("claim_text"))
    extra_target_ids = unique_non_empty(raw.get("target_ids") or [])
    target_id = normalize_space(raw.get("target_id")) or (
        extra_target_ids[0] if extra_target_ids else ""
    )
    if not claim_text or not target_id:
        return None

    target_type = normalize_space(raw.get("target_type")) or "unknown"
    polarity = normalize_space(raw.get("polarity")) or None
    canonical_claim_id = normalize_space(raw.get("canonical_claim_id")) or (
        build_canonical_claim_id(
            target_id=target_id,
            target_type=target_type,
            claim_text=claim_text,
            polarity=polarity,
        )
        if target_type
        else ""
    )
    evidence = ClaimEvidenceRefV1(
        run_id=normalize_space(raw.get("run_id")) or run_id,
        claim_id=normalize_space(raw.get("claim_id")) or canonical_claim_id,
        paper_id=normalize_space(raw.get("paper_id")) or None,
        target_id=target_id,
        polarity=polarity,
        metric="evidence_quality_score" if raw.get("evidence_quality_score") is not None else None,
        value=float(raw.get("evidence_quality_score"))
        if isinstance(raw.get("evidence_quality_score"), int | float)
        else None,
        confidence=_confidence_from_scores(
            raw.get("claim_strength"),
            raw.get("evidence_quality_score"),
        ),
        source_ref=normalize_space(raw.get("source_ref")) or None,
        description=normalize_space(raw.get("evidence_quote")) or claim_text,
    )

    supporting = [evidence] if _is_support_polarity(polarity) else []
    conflicting = [evidence] if _is_conflict_polarity(polarity) else []
    tags = unique_non_empty(
        [
            normalize_space(raw.get("claim_type")),
            normalize_space(raw.get("target_type")),
            target_id,
            polarity,
            *list(raw.get("extra_tags") or []),
        ]
    )

    return ClaimMemoryV1(
        source_run_ids=[normalize_space(raw.get("run_id")) or run_id],
        claim_text=claim_text,
        claim_type=normalize_space(raw.get("claim_type")) or "observation",
        claim_polarity=polarity,
        domain=normalize_space(raw.get("target_type")) or None,
        target_ids=unique_non_empty([target_id, *extra_target_ids]),
        specificity="unknown",
        analytic_conditions=unique_non_empty(raw.get("analytic_conditions")),
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        confidence=_confidence_from_scores(
            raw.get("claim_strength"),
            raw.get("evidence_quality_score"),
        ),
        tags=tags,
        stable_key=_claim_stable_key(
            {**raw, "canonical_claim_id": canonical_claim_id},
            claim_text=claim_text,
            target_id=target_id,
        ),
        related_claims=[
            {
                "claim_id": normalize_space(raw.get("related_claim_id")),
                "relation": "refines",
                "note": "Declared related claim from source artifact.",
            }
        ]
        if normalize_space(raw.get("related_claim_id"))
        else [],
    )


def _claim_stable_key(raw: dict[str, Any], *, claim_text: str, target_id: str) -> str:
    canonical = normalize_space(raw.get("canonical_claim_id"))
    if canonical:
        return f"claim_memory:{canonical}"
    claim_id = normalize_space(raw.get("claim_id"))
    if claim_id:
        return f"claim_memory:{claim_id}"
    return (
        "claim_memory:"
        + normalize_token_text(target_id)
        + ":"
        + normalize_token_text(claim_text)[:160]
    )


def _confidence_from_scores(claim_strength: Any, evidence_quality: Any) -> str:
    numeric = [
        float(value)
        for value in [claim_strength, evidence_quality]
        if isinstance(value, int | float)
    ]
    score = sum(numeric) / len(numeric) if numeric else 0.0
    if score >= 0.8:
        return "strong"
    if score >= 0.45:
        return "moderate"
    return "preliminary"


def _is_support_polarity(value: str | None) -> bool:
    normalized = normalize_token_text(value)
    return normalized in {"supports", "support", "positive", "aligned"}


def _is_conflict_polarity(value: str | None) -> bool:
    normalized = normalize_token_text(value)
    return normalized in {
        "refutes",
        "refute",
        "negative",
        "conflicts",
        "conflicting",
        "contradicts",
        "contradict",
        "opposes",
    }


__all__ = ["DistilledRunMemory", "distill_and_store_run", "distill_run_records"]
