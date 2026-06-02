"""KG-backed scientific-review rule registry execution.

Only registry rules mapped to implemented ``configs/review_rules.yaml`` rules are
executable here. Candidate/spec-only registry entries remain KG metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.services.review.rule_engine import ReviewRuleEngine, get_engine

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_ID = "scientific_review_rule_registry_v1"


@dataclass(frozen=True)
class KGReviewRuleMapping:
    """Mapping from a KG registry rule to an implemented review-rule id."""

    kg_rule_id: str
    implementation_rule_id: str


_EXTERNAL_REVIEW_AXES = ("correctness", "completeness", "judgment")
_IMPLEMENTATION_CATALOG_ID = "review_rules_yaml"


def _record_get(record: Any, key: str) -> Any:
    try:
        return record[key]
    except Exception:
        if isinstance(record, dict):
            return record.get(key)
        getter = getattr(record, "get", None)
        if callable(getter):
            return getter(key)
    return None


def _mapping_from_record(record: Any) -> KGReviewRuleMapping | None:
    kg_rule_id = str(_record_get(record, "kg_rule_id") or "").strip()
    implementation_rule_id = str(
        _record_get(record, "implementation_rule_id") or ""
    ).strip()
    if not kg_rule_id or not implementation_rule_id:
        return None
    return KGReviewRuleMapping(
        kg_rule_id=kg_rule_id,
        implementation_rule_id=implementation_rule_id,
    )


def _as_clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        values = [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _slug(value: object) -> str:
    text = str(value).strip().lower()
    for old, new in (
        (" ", "_"),
        ("/", "_"),
        (":", "_"),
        ("-", "_"),
        (".", "_"),
        ("+", "_"),
    ):
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _review_rule_node_id(rule_id: str) -> str:
    return f"review_rule:{_slug(rule_id)}"


def _external_review_axes_for_rule(rule: dict[str, Any]) -> list[str]:
    """Map registry metadata to the existing external-review verdict axes."""

    tags = set(_as_clean_list(rule.get("reason_tags")))
    layers = set(_as_clean_list(rule.get("validity_layers")))
    group = str(rule.get("group") or "").strip()
    lifecycle_status = str(rule.get("lifecycle_status") or "").strip()
    fields = set(_as_clean_list(rule.get("metadata_fields")))

    axes: list[str] = []
    if tags & {"leakage", "circularity", "confound", "null_mismatch"} or layers & {
        "statistical_validity",
        "measurement_validity",
        "generalization_validity",
    }:
        axes.append("correctness")
    if (
        "low_reliability" in tags
        or group == "reporting_reproducibility"
        or lifecycle_status == "schema_dependent_candidate"
        or any(
            field.startswith(("qc.", "reproducibility.", "correction."))
            for field in fields
        )
    ):
        axes.append("completeness")
    if tags & {
        "claim_inflation",
        "prior_conflict",
        "controversial_choice",
    } or layers & {
        "claim_validity",
        "construct_validity",
    }:
        axes.append("judgment")
    if not axes:
        axes.append("correctness")
    return [axis for axis in _EXTERNAL_REVIEW_AXES if axis in axes]


def _external_agent_instruction(rule: dict[str, Any]) -> str:
    severity = str(rule.get("severity") or "").strip().upper()
    rule_id = str(rule.get("rule_id") or "").strip()
    action = "block" if severity == "BLOCK" else "warn"
    return (
        f"If the evidence matches this criterion, cite rule_id={rule_id} in "
        f"ScientificReviewVerdict.correctness.findings with action={action}; "
        "include the artifact/text evidence and any missing metadata fields."
    )


def _criterion_from_rule_record(record: Any) -> dict[str, Any] | None:
    rule_id = str(_record_get(record, "rule_id") or "").strip()
    if not rule_id:
        return None
    lifecycle_status = str(_record_get(record, "lifecycle_status") or "").strip()
    implementation_rule_ids = _as_clean_list(
        _record_get(record, "implementation_rule_ids")
    )
    criterion = {
        "rule_id": rule_id,
        "kg_node_id": _review_rule_node_id(rule_id),
        "severity": str(_record_get(record, "severity") or "").strip(),
        "lifecycle_status": lifecycle_status,
        "br_executable": bool(
            lifecycle_status == "implemented" and implementation_rule_ids
        ),
        "description": str(_record_get(record, "description") or "").strip(),
        "detection": str(_record_get(record, "detection") or "").strip(),
        "group": str(_record_get(record, "group") or "").strip(),
        "validity_layers": _as_clean_list(_record_get(record, "validity_layers")),
        "reason_tags": _as_clean_list(_record_get(record, "reason_tags")),
        "metadata_fields": _as_clean_list(_record_get(record, "metadata_fields")),
        "implementation_rule_ids": implementation_rule_ids,
        "sensitivity_templates": _as_clean_list(
            _record_get(record, "sensitivity_templates")
        ),
    }
    criterion["agent_instruction"] = _external_agent_instruction(criterion)
    return criterion


def _fetch_mappings_from_db(
    *,
    registry_id: str,
    db: Any,
) -> tuple[KGReviewRuleMapping, ...]:
    cypher = """
    MATCH (:ReviewRuleRegistry {registry_id: $registry_id})-[:CONTAINS_RULE]->(r:ReviewRule)
    WHERE r.lifecycle_status = 'implemented'
    MATCH (r)-[:MAPPED_TO_IMPLEMENTATION]->(impl:ReviewImplementationRule)
    RETURN DISTINCT r.rule_id AS kg_rule_id, impl.rule_id AS implementation_rule_id
    ORDER BY kg_rule_id, implementation_rule_id
    """
    records = db._run(cypher, {"registry_id": registry_id})
    mappings: list[KGReviewRuleMapping] = []
    for record in records:
        mapping = _mapping_from_record(record)
        if mapping is not None:
            mappings.append(mapping)
    return tuple(mappings)


def _fetch_external_review_rule_records_from_db(
    *,
    registry_id: str,
    db: Any,
) -> tuple[dict[str, Any], ...]:
    cypher = """
    MATCH (:ReviewRuleRegistry {registry_id: $registry_id})-[:CONTAINS_RULE]->(r:ReviewRule)
    WHERE coalesce(r.lifecycle_status, '') <> 'calibration_only'
    OPTIONAL MATCH (r)-[:HAS_VALIDITY_LAYER]->(layer:ReviewValidityLayer)
    OPTIONAL MATCH (r)-[:HAS_REASON_TAG]->(tag:ReviewReasonTag)
    OPTIONAL MATCH (r)-[:IN_RULE_GROUP]->(group:ReviewRuleGroup)
    OPTIONAL MATCH (r)-[:REQUIRES_FIELD]->(field:ReviewSchemaField)
    OPTIONAL MATCH (r)-[:MAPPED_TO_IMPLEMENTATION]->(impl:ReviewImplementationRule)
    OPTIONAL MATCH (r)-[:TRIGGERS_SENSITIVITY]->(template:ReviewSensitivityTemplate)
    RETURN DISTINCT
        r.rule_id AS rule_id,
        r.description AS description,
        r.detection AS detection,
        r.severity AS severity,
        r.lifecycle_status AS lifecycle_status,
        group.key AS group,
        collect(DISTINCT layer.key) AS validity_layers,
        collect(DISTINCT tag.key) AS reason_tags,
        collect(DISTINCT field.field_path) AS metadata_fields,
        collect(DISTINCT impl.rule_id) AS implementation_rule_ids,
        collect(DISTINCT template.key) AS sensitivity_templates
    ORDER BY r.severity, r.rule_id
    """
    records = db._run(cypher, {"registry_id": registry_id})
    criteria: list[dict[str, Any]] = []
    for record in records:
        criterion = _criterion_from_rule_record(record)
        if criterion is not None:
            criteria.append(criterion)
    return tuple(criteria)


def _fetch_implementation_rule_ids_from_db(
    *,
    catalog_id: str,
    db: Any,
) -> tuple[str, ...]:
    cypher = """
    MATCH (:ReviewImplementationRuleCatalog {catalog_id: $catalog_id})
          -[:CONTAINS_IMPLEMENTATION_RULE]->(impl:ReviewImplementationRule)
    RETURN DISTINCT impl.rule_id AS implementation_rule_id
    ORDER BY implementation_rule_id
    """
    records = db._run(cypher, {"catalog_id": catalog_id})
    rule_ids: list[str] = []
    seen: set[str] = set()
    for record in records:
        rule_id = str(_record_get(record, "implementation_rule_id") or "").strip()
        if not rule_id or rule_id in seen:
            continue
        seen.add(rule_id)
        rule_ids.append(rule_id)
    return tuple(rule_ids)


@lru_cache(maxsize=8)
def _fetch_mappings_from_default_db(
    registry_id: str,
) -> tuple[KGReviewRuleMapping, ...]:
    try:
        from brain_researcher.services.br_kg import query_service

        db = query_service.get_default_db()
        return _fetch_mappings_from_db(registry_id=registry_id, db=db)
    except Exception as exc:
        logger.info("KG review-rule registry unavailable: %s", exc)
        return ()


def get_implemented_kg_review_rule_mappings(
    *,
    registry_id: str = DEFAULT_REGISTRY_ID,
    db: Any | None = None,
) -> tuple[KGReviewRuleMapping, ...]:
    """Return executable KG registry mappings.

    Passing ``db`` is intended for tests or callers that already own a KG client.
    The default path uses the project BRKG client and fail-opens to no
    mappings if KG is unavailable.
    """

    if db is not None:
        try:
            return _fetch_mappings_from_db(registry_id=registry_id, db=db)
        except Exception as exc:
            logger.info("KG review-rule registry query failed: %s", exc)
            return ()
    return _fetch_mappings_from_default_db(registry_id)


@lru_cache(maxsize=8)
def _fetch_implementation_rule_ids_from_default_db(
    catalog_id: str,
) -> tuple[str, ...]:
    try:
        from brain_researcher.services.br_kg import query_service

        db = query_service.get_default_db()
        return _fetch_implementation_rule_ids_from_db(
            catalog_id=catalog_id,
            db=db,
        )
    except Exception as exc:
        logger.info("KG review implementation catalog unavailable: %s", exc)
        return ()


def get_kg_review_implementation_rule_ids(
    *,
    catalog_id: str = _IMPLEMENTATION_CATALOG_ID,
    db: Any | None = None,
) -> tuple[str, ...]:
    """Return review-gate implementation rule ids represented in BRKG."""

    if db is not None:
        try:
            return _fetch_implementation_rule_ids_from_db(
                catalog_id=catalog_id,
                db=db,
            )
        except Exception as exc:
            logger.info("KG review implementation catalog query failed: %s", exc)
            return ()
    return _fetch_implementation_rule_ids_from_default_db(catalog_id)


@lru_cache(maxsize=8)
def _fetch_external_review_rule_records_from_default_db(
    registry_id: str,
) -> tuple[dict[str, Any], ...]:
    try:
        from brain_researcher.services.br_kg import query_service

        db = query_service.get_default_db()
        return _fetch_external_review_rule_records_from_db(
            registry_id=registry_id,
            db=db,
        )
    except Exception as exc:
        logger.info("KG external review criteria unavailable: %s", exc)
        return ()


def build_external_review_kg_criteria(
    *,
    registry_id: str = DEFAULT_REGISTRY_ID,
    db: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return KG-derived criteria grouped under existing external-review axes.

    This is an instruction surface for external agents. It does not execute rules
    and it does not introduce a new verdict schema.
    """

    if db is not None:
        try:
            rules = _fetch_external_review_rule_records_from_db(
                registry_id=registry_id,
                db=db,
            )
        except Exception as exc:
            logger.info("KG external review criteria query failed: %s", exc)
            rules = ()
    else:
        rules = _fetch_external_review_rule_records_from_default_db(registry_id)

    criteria_by_axis: dict[str, list[dict[str, Any]]] = {
        axis: [] for axis in _EXTERNAL_REVIEW_AXES
    }
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        for axis in _external_review_axes_for_rule(rule):
            key = (axis, str(rule.get("rule_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            criteria_by_axis[axis].append(dict(rule))
    return {axis: criteria for axis, criteria in criteria_by_axis.items() if criteria}


def _extract_cited_rule_ids_from_verdict(verdict: dict[str, Any]) -> list[str]:
    correctness = verdict.get("correctness") if isinstance(verdict, dict) else {}
    findings = correctness.get("findings") if isinstance(correctness, dict) else []
    rule_ids: list[str] = []
    seen: set[str] = set()
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        rule_id = str(finding.get("rule_id") or "").strip()
        if not rule_id or rule_id in seen:
            continue
        seen.add(rule_id)
        rule_ids.append(rule_id)
    return rule_ids


def _resolve_cited_rules_from_db(
    *,
    cited_rule_ids: list[str],
    registry_id: str,
    db: Any,
) -> tuple[dict[str, Any], ...]:
    if not cited_rule_ids:
        return ()
    cypher = """
    MATCH (:ReviewRuleRegistry {registry_id: $registry_id})-[:CONTAINS_RULE]->(r:ReviewRule)
    OPTIONAL MATCH (r)-[:MAPPED_TO_IMPLEMENTATION]->(impl:ReviewImplementationRule)
    WITH r, collect(DISTINCT impl.rule_id) AS implementation_rule_ids
    WHERE r.rule_id IN $rule_ids
       OR any(rule_id IN implementation_rule_ids WHERE rule_id IN $rule_ids)
    RETURN DISTINCT
        r.rule_id AS kg_rule_id,
        r.severity AS severity,
        r.lifecycle_status AS lifecycle_status,
        implementation_rule_ids AS implementation_rule_ids
    ORDER BY r.rule_id
    """
    rows = db._run(cypher, {"registry_id": registry_id, "rule_ids": cited_rule_ids})
    hits: list[dict[str, Any]] = []
    for row in rows:
        kg_rule_id = str(_record_get(row, "kg_rule_id") or "").strip()
        if not kg_rule_id:
            continue
        implementation_rule_ids = _as_clean_list(
            _record_get(row, "implementation_rule_ids")
        )
        cited_matches = [
            rule_id
            for rule_id in cited_rule_ids
            if rule_id == kg_rule_id or rule_id in implementation_rule_ids
        ]
        hits.append(
            {
                "kg_rule_id": kg_rule_id,
                "kg_node_id": _review_rule_node_id(kg_rule_id),
                "cited_rule_ids": cited_matches,
                "severity": str(_record_get(row, "severity") or "").strip(),
                "lifecycle_status": str(
                    _record_get(row, "lifecycle_status") or ""
                ).strip(),
                "implementation_rule_ids": implementation_rule_ids,
            }
        )
    return tuple(hits)


def _resolve_cited_implementation_rules_from_db(
    *,
    cited_rule_ids: list[str],
    catalog_id: str,
    db: Any,
) -> tuple[dict[str, Any], ...]:
    if not cited_rule_ids:
        return ()
    cypher = """
    MATCH (:ReviewImplementationRuleCatalog {catalog_id: $catalog_id})
          -[:CONTAINS_IMPLEMENTATION_RULE]->(impl:ReviewImplementationRule)
    WHERE impl.rule_id IN $rule_ids
    RETURN DISTINCT
        impl.rule_id AS implementation_rule_id,
        impl.severity AS severity,
        impl.action AS action,
        impl.review_mode AS review_mode
    ORDER BY impl.rule_id
    """
    rows = db._run(cypher, {"catalog_id": catalog_id, "rule_ids": cited_rule_ids})
    hits: list[dict[str, Any]] = []
    for row in rows:
        implementation_rule_id = str(
            _record_get(row, "implementation_rule_id") or ""
        ).strip()
        if not implementation_rule_id:
            continue
        hits.append(
            {
                "implementation_rule_id": implementation_rule_id,
                "kg_node_id": f"implemented_review_rule:{_slug(implementation_rule_id)}",
                "cited_rule_ids": [
                    rule_id
                    for rule_id in cited_rule_ids
                    if rule_id == implementation_rule_id
                ],
                "severity": str(_record_get(row, "severity") or "").strip(),
                "action": str(_record_get(row, "action") or "").strip(),
                "review_mode": str(_record_get(row, "review_mode") or "").strip(),
            }
        )
    return tuple(hits)


def summarize_external_review_rule_feedback(
    verdict: dict[str, Any],
    *,
    registry_id: str = DEFAULT_REGISTRY_ID,
    db: Any | None = None,
) -> dict[str, Any]:
    """Summarize external verdict rule citations as KG feedback metadata."""

    cited_rule_ids = _extract_cited_rule_ids_from_verdict(verdict)
    if not cited_rule_ids:
        return {
            "registry_id": registry_id,
            "cited_rule_ids": [],
            "kg_rule_hits": [],
            "unknown_rule_ids": [],
            "status": "no_rule_citations",
        }

    try:
        if db is None:
            from brain_researcher.services.br_kg import query_service

            db = query_service.get_default_db()
        hits = list(
            _resolve_cited_rules_from_db(
                cited_rule_ids=cited_rule_ids,
                registry_id=registry_id,
                db=db,
            )
        )
        matched = {
            cited_rule_id
            for hit in hits
            for cited_rule_id in _as_clean_list(hit.get("cited_rule_ids"))
        }
        implementation_hits = list(
            _resolve_cited_implementation_rules_from_db(
                cited_rule_ids=[
                    rule_id for rule_id in cited_rule_ids if rule_id not in matched
                ],
                catalog_id=_IMPLEMENTATION_CATALOG_ID,
                db=db,
            )
        )
        matched_implementations = {
            cited_rule_id
            for hit in implementation_hits
            for cited_rule_id in _as_clean_list(hit.get("cited_rule_ids"))
        }
        unknown = [
            rule_id
            for rule_id in cited_rule_ids
            if rule_id not in matched and rule_id not in matched_implementations
        ]
        return {
            "registry_id": registry_id,
            "implementation_catalog_id": _IMPLEMENTATION_CATALOG_ID,
            "cited_rule_ids": cited_rule_ids,
            "kg_rule_hits": hits,
            "kg_implementation_hits": implementation_hits,
            "unknown_rule_ids": unknown,
            "status": "ok",
        }
    except Exception as exc:
        logger.info("KG external review feedback resolution failed: %s", exc)
        return {
            "registry_id": registry_id,
            "implementation_catalog_id": _IMPLEMENTATION_CATALOG_ID,
            "cited_rule_ids": cited_rule_ids,
            "kg_rule_hits": [],
            "kg_implementation_hits": [],
            "unknown_rule_ids": cited_rule_ids,
            "status": "kg_unavailable",
            "message": str(exc),
        }


def record_external_review_rule_feedback(
    *,
    feedback: dict[str, Any],
    directive_id: str,
    verdict_id: str,
    session_id: str,
    reviewer: str,
    overall_decision: str | None,
    db: Any | None = None,
) -> dict[str, Any]:
    """Persist external verdict rule hits as KG feedback nodes when KG is writable."""

    hits = feedback.get("kg_rule_hits") if isinstance(feedback, dict) else []
    implementation_hits = (
        feedback.get("kg_implementation_hits") if isinstance(feedback, dict) else []
    )
    if not hits and not implementation_hits:
        return {"ok": True, "status": "no_known_kg_rule_hits", "created": 0}

    rows: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        kg_rule_id = str(hit.get("kg_rule_id") or "").strip()
        if not kg_rule_id:
            continue
        rows.append(
            {
                "feedback_id": (
                    "external_review_feedback:"
                    f"{directive_id}:{verdict_id}:{_slug(kg_rule_id)}"
                ),
                "kg_rule_id": kg_rule_id,
                "kg_node_id": hit.get("kg_node_id") or _review_rule_node_id(kg_rule_id),
                "directive_id": directive_id,
                "verdict_id": verdict_id,
                "session_id": session_id,
                "reviewer": reviewer,
                "overall_decision": overall_decision,
                "cited_rule_ids": _as_clean_list(hit.get("cited_rule_ids")),
                "severity": hit.get("severity"),
                "lifecycle_status": hit.get("lifecycle_status"),
                "source": "external_scientific_review_verdict",
            }
        )
    implementation_rows: list[dict[str, Any]] = []
    for hit in implementation_hits or []:
        if not isinstance(hit, dict):
            continue
        implementation_rule_id = str(hit.get("implementation_rule_id") or "").strip()
        if not implementation_rule_id:
            continue
        implementation_rows.append(
            {
                "feedback_id": (
                    "external_review_feedback:"
                    f"{directive_id}:{verdict_id}:{_slug(implementation_rule_id)}"
                ),
                "implementation_rule_id": implementation_rule_id,
                "kg_node_id": hit.get("kg_node_id")
                or f"implemented_review_rule:{_slug(implementation_rule_id)}",
                "directive_id": directive_id,
                "verdict_id": verdict_id,
                "session_id": session_id,
                "reviewer": reviewer,
                "overall_decision": overall_decision,
                "cited_rule_ids": _as_clean_list(hit.get("cited_rule_ids")),
                "severity": hit.get("severity"),
                "action": hit.get("action"),
                "review_mode": hit.get("review_mode"),
                "source": "external_scientific_review_verdict",
            }
        )
    if not rows and not implementation_rows:
        return {"ok": True, "status": "no_known_kg_rule_hits", "created": 0}

    try:
        if db is None:
            from brain_researcher.services.br_kg import query_service

            db = query_service.get_default_db()
        created = 0
        if rows:
            cypher = """
            UNWIND $rows AS row
            MATCH (registry:ReviewRuleRegistry {registry_id: $registry_id})
                  -[:CONTAINS_RULE]->(rule:ReviewRule {rule_id: row.kg_rule_id})
            MERGE (feedback:ExternalReviewRuleFeedback {id: row.feedback_id})
            SET feedback += row
            MERGE (registry)-[:HAS_EXTERNAL_REVIEW_FEEDBACK]->(feedback)
            MERGE (feedback)-[:CITES_REVIEW_RULE]->(rule)
            RETURN count(feedback) AS created
            """
            result = db._run(
                cypher,
                {
                    "registry_id": feedback.get("registry_id") or DEFAULT_REGISTRY_ID,
                    "rows": rows,
                },
            )
            try:
                record = result.single()
                if record is not None:
                    created += int(_record_get(record, "created") or 0)
            except Exception:
                created += len(rows)
        if implementation_rows:
            cypher = """
            UNWIND $rows AS row
            MATCH (catalog:ReviewImplementationRuleCatalog {catalog_id: $catalog_id})
                  -[:CONTAINS_IMPLEMENTATION_RULE]->(
                      impl:ReviewImplementationRule {rule_id: row.implementation_rule_id}
                  )
            MERGE (feedback:ExternalReviewRuleFeedback {id: row.feedback_id})
            SET feedback += row
            MERGE (catalog)-[:HAS_EXTERNAL_REVIEW_FEEDBACK]->(feedback)
            MERGE (feedback)-[:CITES_IMPLEMENTATION_RULE]->(impl)
            RETURN count(feedback) AS created
            """
            result = db._run(
                cypher,
                {
                    "catalog_id": feedback.get("implementation_catalog_id")
                    or _IMPLEMENTATION_CATALOG_ID,
                    "rows": implementation_rows,
                },
            )
            try:
                record = result.single()
                if record is not None:
                    created += int(_record_get(record, "created") or 0)
            except Exception:
                created += len(implementation_rows)
        return {"ok": True, "status": "recorded", "created": created}
    except Exception as exc:
        logger.info("KG external review feedback write failed: %s", exc)
        return {
            "ok": False,
            "status": "kg_write_failed",
            "created": 0,
            "message": str(exc),
        }


def _merge_unique_strings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged


def _finding_key(finding: ReviewFinding) -> tuple[str, str | None, str | None, str]:
    return (
        finding.rule_id,
        finding.step_id,
        finding.artifact_name,
        finding.message,
    )


def merge_kg_registry_findings(
    existing_findings: list[ReviewFinding],
    kg_findings: list[ReviewFinding],
) -> list[ReviewFinding]:
    """Merge KG-triggered findings without duplicating existing deterministic hits."""

    merged = list(existing_findings)
    index = {_finding_key(finding): i for i, finding in enumerate(merged)}

    for kg_finding in kg_findings:
        key = _finding_key(kg_finding)
        existing_index = index.get(key)
        if existing_index is None:
            index[key] = len(merged)
            merged.append(kg_finding)
            continue

        existing = merged[existing_index]
        kg_evidence = _merge_unique_strings(
            existing.kg_evidence, kg_finding.kg_evidence
        )
        reason_tags = _merge_unique_strings(
            existing.reason_tags, kg_finding.reason_tags
        )
        merged[existing_index] = existing.model_copy(
            update={
                "kg_evidence": kg_evidence,
                "reason_tags": reason_tags,
                "novelty": existing.novelty or kg_finding.novelty,
            }
        )

    return merged


def evaluate_kg_review_registry(
    bundle: CodeReviewBundle,
    *,
    engine: ReviewRuleEngine | None = None,
    registry_id: str = DEFAULT_REGISTRY_ID,
    db: Any | None = None,
    catalog_rule_ids_filter: set[str] | None = None,
) -> tuple[list[ReviewFinding], list[str]]:
    """Evaluate implemented rules selected from the BRKG rule registry."""

    mappings = get_implemented_kg_review_rule_mappings(
        registry_id=registry_id,
        db=db,
    )
    implementation_rule_ids = get_kg_review_implementation_rule_ids(db=db)
    if not mappings and not implementation_rule_ids:
        return [], []

    mapping_by_impl: dict[str, list[str]] = {}
    for mapping in mappings:
        mapping_by_impl.setdefault(mapping.implementation_rule_id, []).append(
            mapping.kg_rule_id
        )

    engine = engine or get_engine()
    configured_rule_ids = {rule.rule_id for rule in engine.rules}
    catalog_rule_ids = set(implementation_rule_ids)
    if catalog_rule_ids_filter is not None:
        catalog_rule_ids &= set(catalog_rule_ids_filter)
    executable_rule_ids = (
        set(mapping_by_impl) | catalog_rule_ids
    ) & configured_rule_ids
    if not executable_rule_ids:
        return [], [
            f"{mapping.kg_rule_id}->{mapping.implementation_rule_id}"
            for mapping in mappings
        ] + [
            f"implementation_catalog->{implementation_rule_id}"
            for implementation_rule_id in sorted(catalog_rule_ids)
        ]

    findings = engine.evaluate_artifacts(bundle, rule_ids=executable_rule_ids)
    enriched: list[ReviewFinding] = []
    for finding in findings:
        kg_rule_ids = mapping_by_impl.get(finding.rule_id, [])
        if kg_rule_ids:
            evidence = [
                (
                    "BRKG scientific-review registry selected implemented rule "
                    f"{finding.rule_id} from KG rule(s): {', '.join(kg_rule_ids)}."
                )
            ]
        else:
            evidence = [
                (
                    "BRKG review implementation catalog selected configured rule "
                    f"{finding.rule_id}."
                )
            ]
        enriched.append(
            finding.model_copy(
                update={
                    "kg_evidence": _merge_unique_strings(
                        finding.kg_evidence,
                        evidence,
                    )
                }
            )
        )

    consulted = [
        f"{mapping.kg_rule_id}->{mapping.implementation_rule_id}"
        for mapping in mappings
        if mapping.implementation_rule_id in executable_rule_ids
    ] + [
        f"implementation_catalog->{implementation_rule_id}"
        for implementation_rule_id in sorted(catalog_rule_ids & executable_rule_ids)
        if implementation_rule_id not in mapping_by_impl
    ]
    return enriched, consulted


__all__ = [
    "DEFAULT_REGISTRY_ID",
    "KGReviewRuleMapping",
    "build_external_review_kg_criteria",
    "evaluate_kg_review_registry",
    "get_implemented_kg_review_rule_mappings",
    "get_kg_review_implementation_rule_ids",
    "merge_kg_registry_findings",
    "record_external_review_rule_feedback",
    "summarize_external_review_rule_feedback",
]
