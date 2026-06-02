"""Deterministic lessons and risk extraction for BR research sessions."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

OPEN_RISK_LABELS = (
    "uncommitted-local",
    "unrelated-dirty-worktree",
    "partial-validation",
    "prod-auth-data-runtime",
    "generated-artifact",
    "pre-existing-debt",
    "scientific-method-gap",
    "logging-metadata-gap",
)

SESSION_KG_NODE_LABELS = (
    "AgentSession",
    "TaskSurface",
    "ValidationEvidence",
    "OpenRisk",
    "Outcome",
    "Lesson",
    "NextAction",
)

SESSION_KG_RELATIONSHIP_TYPES = (
    "WORKED_ON_SURFACE",
    "VALIDATED_BY",
    "LEFT_OPEN_RISK",
    "PRODUCED_ARTIFACT",
    "EXPOSED_FAILURE_MODE",
    "HAS_REMEDIATION",
    "SHOULD_UPDATE_AGENT_POLICY",
)

SESSION_KG_QUERY_EXAMPLES = (
    {
        "name": "repeated_failure_modes_by_surface",
        "question": "show repeated failure modes by surface",
        "cypher": (
            "MATCH (s:TaskSurface)-[:EXPOSED_FAILURE_MODE]->(r:OpenRisk) "
            "RETURN s.name AS surface, r.label AS risk_label, count(*) AS count "
            "ORDER BY count DESC, surface"
        ),
    },
    {
        "name": "prod_rollout_without_browser_smoke",
        "question": "show sessions with prod rollout but no browser smoke",
        "cypher": (
            "MATCH (a:AgentSession)-[:WORKED_ON_SURFACE]->"
            "(:TaskSurface {name: 'prod-runtime'}) "
            "WHERE NOT EXISTS { MATCH (a)-[:VALIDATED_BY]->"
            "(:ValidationEvidence {evidence_type: 'health-smoke'}) } "
            "RETURN a.session_id AS session_id, a.status AS status, "
            "a.last_event_at AS last_event_at"
        ),
    },
    {
        "name": "scientific_runs_missing_null_result_diagnosis",
        "question": "show scientific runs with null-result diagnosis missing",
        "cypher": (
            "MATCH (a:AgentSession)-[:WORKED_ON_SURFACE]->"
            "(:TaskSurface {name: 'scientific-workflow'}) "
            "WHERE NOT EXISTS { MATCH (a)-[:LEFT_OPEN_RISK]->"
            "(:OpenRisk {label: 'scientific-method-gap'}) } "
            "RETURN a.session_id AS session_id, a.goal AS goal"
        ),
    },
    {
        "name": "succeeded_sessions_with_unresolved_blockers",
        "question": "show sessions succeeded but with unresolved blockers",
        "cypher": (
            "MATCH (a:AgentSession {status: 'succeeded'})"
            "-[:LEFT_OPEN_RISK]->(r:OpenRisk) "
            "RETURN a.session_id AS session_id, collect(r.label) AS risk_labels"
        ),
    },
)


_OPEN_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "uncommitted-local",
        r"\b(uncommitted|not committed|local only|ahead of origin|not pushed|"
        r"unstaged|staged)\b",
    ),
    (
        "unrelated-dirty-worktree",
        r"\b(unrelated|dirty worktree|dirty files|untracked .*remain|"
        r"left untouched|outside this|not touched)\b",
    ),
    (
        "partial-validation",
        r"\b(no tests|not run|not verified|unverified|manual verification|"
        r"partial validation|smoke .*not|full .*not run|coverage .*missing)\b",
    ),
    (
        "prod-auth-data-runtime",
        r"\b(prod|deploy|rollout|runtime|auth|credential|secret|token|health|"
        r"degraded|timeout|unavailable|service issue|bucket_state|migration)\b",
    ),
    (
        "generated-artifact",
        r"\b(generated|artifact|artifacts|pdf|report|run bundle|ignored output|"
        r"build output)\b",
    ),
    (
        "pre-existing-debt",
        r"\b(pre-existing|existing .*debt|lint debt|ruff .*fails|deprecation|"
        r"legacy|broad existing)\b",
    ),
    (
        "scientific-method-gap",
        r"\b(null|weak effect|non-significant|confound|label|granularity|"
        r"methodological|atlas|query-based seed|outer harness|raw data|ibma|"
        r"blocked asset|gate remains blocked)\b",
    ),
    (
        "logging-metadata-gap",
        r"\b(source_client|snapshot|running session|transcript|tool trace|"
        r"client_session_id|logging metadata)\b",
    ),
)

_TASK_SURFACE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "prod-runtime",
        r"\b(prod|rollout|deploy|k3s|gcp|helm|docker|image tag|pod|health|"
        r"smoke|runtime|orchestrator|secret|auth)\b",
    ),
    (
        "web-demo-ui",
        r"\b(web-ui|studio|demo|frontend|browser|playwright|screenshot|ui|"
        r"artifact viewer|case report|route|next api)\b",
    ),
    (
        "repo-cleanup-release",
        r"\b(open-source|release readiness|repo-cleanup|license|gitignore|"
        r"\.env|secret cleanup|generated artifact|vendored)\b",
    ),
    (
        "docs-manuscript",
        r"\b(overleaf|latex|manuscript|abstract|caption|figure|supplement|"
        r"discussion|bibliography|paper)\b",
    ),
    (
        "benchmark-eval-review",
        r"\b(benchmark|eval|review packet|score|scorer|metric|neurometabench|"
        r"layer b|harbor|rubric|audit)\b",
    ),
    (
        "scientific-workflow",
        r"\b(autoresearch|hypothesis|scientific workflow|scientific report|"
        r"neuroimaging|fmri|qsm|abide|hcp|connectome|multiverse|tribe|analysis)\b",
    ),
    (
        "kg-literature-data",
        r"\b(kg|br_kg|knowledge graph|literature|deepxiv|pubmed|openalex|"
        r"dataset|openneuro|cognitive atlas|neurosynth|nimare)\b",
    ),
    (
        "code-contract",
        r"\b(pytest|test|ci|ruff|typecheck|schema|contract|api|module-boundary|"
        r"core-services|implementation|bug|fix)\b",
    ),
    (
        "agent-policy-logging",
        r"\b(agents\.md|claude\.md|prompt|source_client|session logging|"
        r"research logging|mcp function|instruction|codex|claude code)\b",
    ),
)

_VALIDATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("pytest", r"\bpytest\b"),
    ("lint", r"\b(ruff|lint|black --check|eslint)\b"),
    ("typecheck", r"\b(typecheck|tsc|mypy)\b"),
    ("compile", r"\b(py_compile|compileall|latexmk|compiled|build passed)\b"),
    ("git-check", r"\b(git diff --check|git status|git ls-files|git check-ignore)\b"),
    (
        "health-smoke",
        r"\b(health endpoint|/api/health|smoke|curl|browser|playwright)\b",
    ),
    (
        "artifact-check",
        r"\b(pdfinfo|file check|artifact .*exists|verified .*artifact)\b",
    ),
    ("schema-contract", r"\b(schema|contract|json parse|validated .*shape)\b"),
    (
        "neurometabench-bundle",
        r"\b(BR plan_preflight|BR audit verified|Wrote RUN_SUMMARY|"
        r"coordinate count|space consistency|coordinate_table\.csv|"
        r"included_studies\.csv|Generated ALE maps|metrics\.json|"
        r"provenance_manifest\.json|spatial_report\.md)\b",
    ),
    (
        "test-prose",
        r"\b(validated \d+ .*tests? passing|validated .* tests? pass(?:ing|ed)?|"
        r"\d+ tests? pass(?:ing|ed)?)\b",
    ),
    (
        "report-render",
        r"\b(pdf rendered|rendered PDF|rerendered|LaTeX log|pdftotext|"
        r"pdfinfo|md5 parity|compiled PDF|rebuilt .*\.pdf|no LaTeX errors|"
        r"no fatal)\b",
    ),
    (
        "prod-operational",
        r"\b(tools/list|rollout status|deployment image|verified prod|"
        r"live MCP|MCP transport|kubectl)\b",
    ),
    (
        "kg-literature",
        r"\b(kg_search_nodes|deepxiv|DeepXiv|literature lookup|"
        r"publication evidence|KG search)\b",
    ),
)

_VALIDATION_FALSE_NEGATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "neurometabench-bundle-validation",
        r"\b(BR plan_preflight|BR audit verified|Wrote RUN_SUMMARY|"
        r"coordinate count|space consistency|coordinate_table\.csv|"
        r"included_studies\.csv|Generated ALE maps|metrics\.json|"
        r"provenance_manifest\.json|spatial_report\.md)\b",
    ),
    (
        "test-validation-prose",
        r"\b(validated \d+ .*tests? passing|validated .* tests? pass(?:ing|ed)?)\b",
    ),
    (
        "report-render-validation",
        r"\b(pdf rendered|rendered PDF|rerendered|LaTeX log|pdftotext|"
        r"pdfinfo|md5 parity|compiled PDF)\b",
    ),
    (
        "prod-operational-validation",
        r"\b(tools/list|rollout status|deployment image|verified prod|"
        r"live MCP|MCP transport|kubectl)\b",
    ),
    (
        "kg-literature-validation",
        r"\b(kg_search_nodes|deepxiv|DeepXiv|literature lookup|"
        r"publication evidence|KG search)\b",
    ),
)

_WEAK_CLEAN_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "handoff-only-or-outer-harness",
        r"\b(outer harness|evaluation harness|evaluator runs|bundle complete|"
        r"producer complete)\b",
    ),
    (
        "approximate-or-uncorrected-science",
        r"\b(approximate null|uncorrected|no FWE|FWE correction .*not|" r"FDR .*not)\b",
    ),
    (
        "vague-completion",
        r"\b(done|complete|completed|generated output|wrote artifacts)\b",
    ),
)

_BOUNDARY_PHRASE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("outer_harness", r"\b(outer harness|evaluation harness|evaluator runs)\b"),
    (
        "not_run_or_not_verified",
        r"\b(not run|not verified|not exercised|no external comparison|"
        r"no code tests|no live end-to-end)\b",
    ),
    (
        "missing_or_not_available",
        r"\b(missing|not available|not possible|could not confirm|"
        r"does not contain|no results)\b",
    ),
    (
        "approximate_or_uncorrected",
        r"\b(approximate null|uncorrected|no FWE|FWE correction .*not|" r"FDR .*not)\b",
    ),
    (
        "manual_or_not_measured",
        r"\b(manual adjudication|not measured|remain unavailable|"
        r"release blocker)\b",
    ),
    (
        "dirty_or_local_only",
        r"\b(dirty worktree|untracked|local only|not pushed|not committed)\b",
    ),
    (
        "documentation_only",
        r"\b(documentation only|doc-only|no file edits|does not refactor)\b",
    ),
)

_UNRESOLVED_NEXT_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "outer_harness_evaluation",
        r"\b(outer harness|evaluation harness|run_layer_b_comparison|"
        r"evaluator runs|benchmark evaluator)\b",
    ),
    (
        "study_id_reconciliation",
        r"\b(PMID|DOI|study[- ]ID|identifier reconciliation|BrainMap|"
        r"NiMADS .*PMID|crosswalk)\b",
    ),
    (
        "manual_silent_pass_adjudication",
        r"\b(silent-pass|silent pass|manual adjudication|collaborator/user)\b",
    ),
    (
        "prod_rollout_smoke",
        r"\b(prod|rollout|deploy|live .*smoke|browser smoke|API smoke|"
        r"health endpoint|taskbeacon)\b",
    ),
    (
        "docs_schema_or_release_drift",
        r"\b(schema drift|tool.*schema|hint drift|untracked|release blocker|"
        r"architecture debt|documentation only)\b",
    ),
    (
        "missing_scientific_assets",
        r"\b(Barch|HCP-MMP|asset|raw data|blocked asset|not available)\b",
    ),
)

_PROD_TASK_RE = re.compile(
    r"\b(prod|rollout|deploy|k3s|gcp|helm|docker|image|pod|health|smoke|runtime)\b",
    re.IGNORECASE,
)
_PROD_EVIDENCE_RE = re.compile(
    r"\b(rollout status|rolled out|deployed|image tag|docker\.io|kubectl|"
    r"deployment image|tools/list|live MCP|MCP transport|verified prod|"
    r"/api/health|health endpoint|browser smoke|api smoke|public health|200)\b",
    re.IGNORECASE,
)
_VAGUE_OPEN_VALUES = {
    "",
    "none",
    "n/a",
    "na",
    "no open issues",
    "no open issues.",
    "nothing",
}


def _items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text_parts(digest: dict[str, Any]) -> list[str]:
    snapshot = (
        digest.get("snapshot") if isinstance(digest.get("snapshot"), dict) else {}
    )
    return [
        str(digest.get("session_id") or ""),
        str(digest.get("run_id") or ""),
        str(snapshot.get("goal") or ""),
        str(snapshot.get("next_command") or ""),
        " ".join(_items(digest.get("event_tags"))),
        " ".join(_items(digest.get("done_items"))),
        " ".join(_items(digest.get("open_items"))),
    ]


def _digest_text(digest: dict[str, Any]) -> str:
    return " ".join(_text_parts(digest)).lower()


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def infer_task_surfaces(digest: dict[str, Any]) -> list[str]:
    """Infer coarse task surfaces from digest metadata."""
    text = _digest_text(digest)
    surfaces = [
        surface
        for surface, pattern in _TASK_SURFACE_PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    ]
    return surfaces or ["other"]


def extract_validation_evidence(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return concrete-looking validation evidence from session done/open text."""
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_field in ("done_items", "open_items"):
        for item in _items(digest.get(source_field)):
            for evidence_type, pattern in _VALIDATION_PATTERNS:
                if not re.search(pattern, item, re.IGNORECASE):
                    continue
                key = (evidence_type, item)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(
                    {
                        "id": _stable_id("validation_evidence", evidence_type, item),
                        "evidence_type": evidence_type,
                        "source_field": source_field,
                        "text": item,
                    }
                )
    return evidence


def _matched_named_patterns(
    text: str,
    patterns: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for name, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        matches.append(
            {
                "name": name,
                "matched_text": match.group(0),
            }
        )
    return matches


def _session_snapshot_text(digest: dict[str, Any]) -> str:
    snapshot = (
        digest.get("snapshot") if isinstance(digest.get("snapshot"), dict) else {}
    )
    parts = [
        str(snapshot.get("goal") or ""),
        str(snapshot.get("next_command") or ""),
        " ".join(_items(digest.get("done_items"))),
        " ".join(_items(digest.get("open_items"))),
    ]
    return " ".join(part for part in parts if part)


def extract_validation_parser_false_negative_candidate(
    digest: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a candidate when prose likely contains validation missed by parser."""
    if str(digest.get("status") or "").lower() != "succeeded":
        return None
    if not bool(digest.get("has_snapshot")):
        return None
    if extract_validation_evidence(digest):
        return None
    text = _session_snapshot_text(digest)
    matches = _matched_named_patterns(text, _VALIDATION_FALSE_NEGATIVE_PATTERNS)
    if not matches:
        return None
    return {
        "session_id": digest.get("session_id"),
        "run_id": digest.get("run_id"),
        "matched_categories": [match["name"] for match in matches],
        "matched_text": [match["matched_text"] for match in matches],
        "task_surfaces": infer_task_surfaces(digest),
        "example_done_items": _items(digest.get("done_items"))[:3],
    }


def extract_unresolved_next_action_themes(
    digest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify open/next-command text into loop-closure themes."""
    snapshot = (
        digest.get("snapshot") if isinstance(digest.get("snapshot"), dict) else {}
    )
    open_items = _items(digest.get("open_items"))
    next_command = str(snapshot.get("next_command") or "").strip()
    if not open_items and not next_command:
        return []
    text = " ".join([next_command, *open_items])
    matches = _matched_named_patterns(text, _UNRESOLVED_NEXT_ACTION_PATTERNS)
    return [
        {
            "session_id": digest.get("session_id"),
            "run_id": digest.get("run_id"),
            "theme": match["name"],
            "matched_text": match["matched_text"],
            "open_items": open_items[:3],
            "next_command": next_command,
            "task_surfaces": infer_task_surfaces(digest),
        }
        for match in matches
    ]


def extract_boundary_phrase_hits(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract self-admitted boundary phrases from snapshot text."""
    text = _session_snapshot_text(digest)
    matches = _matched_named_patterns(text, _BOUNDARY_PHRASE_PATTERNS)
    return [
        {
            "session_id": digest.get("session_id"),
            "run_id": digest.get("run_id"),
            "phrase": match["name"],
            "matched_text": match["matched_text"],
            "task_surfaces": infer_task_surfaces(digest),
        }
        for match in matches
    ]


def classify_weak_clean_snapshot(digest: dict[str, Any]) -> dict[str, Any] | None:
    """Identify succeeded open-empty snapshots that still need scrutiny."""
    if str(digest.get("status") or "").lower() != "succeeded":
        return None
    if not bool(digest.get("has_snapshot")):
        return None
    if _items(digest.get("open_items")):
        return None
    text = _session_snapshot_text(digest)
    reasons: list[str] = []
    if not extract_validation_evidence(digest):
        reasons.append("no_parser_validation_evidence")
    for match in _matched_named_patterns(text, _WEAK_CLEAN_PATTERNS):
        reason = str(match.get("name") or "")
        if reason and reason not in reasons:
            reasons.append(reason)
    if not reasons:
        return None
    return {
        "session_id": digest.get("session_id"),
        "run_id": digest.get("run_id"),
        "reasons": reasons,
        "task_surfaces": infer_task_surfaces(digest),
        "example_done_items": _items(digest.get("done_items"))[:3],
    }


def classify_open_risks(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Map open items to canonical risk labels."""
    risks: list[dict[str, Any]] = []
    session_key = digest.get("session_id") or digest.get("run_id")
    for item in _items(digest.get("open_items")):
        labels = [
            label
            for label, pattern in _OPEN_RISK_PATTERNS
            if re.search(pattern, item, re.IGNORECASE)
        ]
        matched = bool(labels)
        if not labels:
            labels = ["pre-existing-debt"]
        for label in labels:
            risks.append(
                {
                    "id": _stable_id("open_risk", session_key, label, item),
                    "label": label,
                    "text": item,
                    "matched_pattern": matched,
                }
            )
    return risks


def classify_session_hygiene(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify deterministic session logging and handoff hygiene issues."""
    issues: list[dict[str, Any]] = []
    session_id = str(digest.get("session_id") or "")
    if not str(digest.get("source_client") or "").strip():
        issues.append(
            {
                "code": "missing_source_client",
                "severity": "medium",
                "message": "Session does not record source_client.",
                "evidence": [session_id],
            }
        )
    if not bool(digest.get("has_snapshot")):
        issues.append(
            {
                "code": "missing_final_snapshot",
                "severity": "high",
                "message": "Session has no final write_session_snapshot closeout.",
                "evidence": [session_id],
            }
        )
    vague_open = [
        item
        for item in _items(digest.get("open_items"))
        if item.lower() in _VAGUE_OPEN_VALUES
    ]
    if vague_open:
        issues.append(
            {
                "code": "vague_open_none",
                "severity": "low",
                "message": "Open items contain vague none-style placeholders.",
                "evidence": vague_open,
            }
        )
    if (
        str(digest.get("status") or "").lower() == "succeeded"
        and bool(digest.get("has_snapshot"))
        and not extract_validation_evidence(digest)
    ):
        issues.append(
            {
                "code": "succeeded_without_validation_evidence",
                "severity": "medium",
                "message": (
                    "Session is closed as succeeded but no concrete validation "
                    "evidence was detected in done/open items."
                ),
                "evidence": _items(digest.get("done_items"))[:3],
            }
        )
    text = _digest_text(digest)
    evidence_text = " ".join(
        _items(digest.get("done_items")) + _items(digest.get("open_items"))
    )
    if _PROD_TASK_RE.search(text) and not _PROD_EVIDENCE_RE.search(evidence_text):
        issues.append(
            {
                "code": "prod_without_rollout_health_evidence",
                "severity": "high",
                "message": (
                    "Prod/runtime-like task lacks detected rollout or health "
                    "evidence."
                ),
                "evidence": _text_parts(digest)[:4],
            }
        )
    return issues


def classify_session(digest: dict[str, Any]) -> dict[str, Any]:
    """Return session surfaces, evidence, open risks, and hygiene issues."""
    return {
        "session_id": digest.get("session_id"),
        "run_id": digest.get("run_id"),
        "status": digest.get("status"),
        "source_client": digest.get("source_client"),
        "has_snapshot": bool(digest.get("has_snapshot")),
        "task_surfaces": infer_task_surfaces(digest),
        "validation_evidence": extract_validation_evidence(digest),
        "open_risks": classify_open_risks(digest),
        "hygiene_issues": classify_session_hygiene(digest),
    }


def extract_session_lessons(digest: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative, fact-first lesson extraction payload."""
    classification = classify_session(digest)
    lessons: list[dict[str, Any]] = []
    for issue in classification["hygiene_issues"]:
        code = str(issue.get("code") or "")
        if code == "missing_final_snapshot":
            lesson = "Close completed BR work with one final session snapshot."
        elif code == "missing_source_client":
            lesson = (
                "Pass source_client so client-specific agent behavior is auditable."
            )
        elif code == "succeeded_without_validation_evidence":
            lesson = "Pair succeeded closeout with concrete validation evidence."
        elif code == "prod_without_rollout_health_evidence":
            lesson = "Prod/runtime handoffs need rollout and health evidence."
        elif code == "vague_open_none":
            lesson = "Use explicit open-risk labels instead of vague none placeholders."
        else:
            continue
        lessons.append(
            {
                "id": _stable_id("lesson", digest.get("session_id"), code, lesson),
                "issue_code": code,
                "text": lesson,
                "status": "candidate",
            }
        )
    return {
        "session_id": digest.get("session_id"),
        "run_id": digest.get("run_id"),
        "classification": classification,
        "lessons": lessons,
    }


def build_session_policy_cards(
    lesson_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate lesson extractions into policy-card candidates."""
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for payload in lesson_payloads:
        session_id = str(payload.get("session_id") or "")
        for lesson in payload.get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            code = str(lesson.get("issue_code") or "")
            text = str(lesson.get("text") or "")
            if not code or not text:
                continue
            counts[code] += 1
            texts.setdefault(code, text)
            examples.setdefault(code, [])
            if session_id and session_id not in examples[code]:
                examples[code].append(session_id)
    cards: list[dict[str, Any]] = []
    for code, count in counts.most_common():
        cards.append(
            {
                "card_id": f"session_policy:{code}",
                "issue_code": code,
                "lesson": texts.get(code, ""),
                "support_count": count,
                "example_session_ids": examples.get(code, [])[:5],
                "status": "candidate",
            }
        )
    return cards


def _counter_rows(
    counter: Counter[str],
    *,
    key_name: str,
    top_k: int,
    min_support: int = 1,
    examples: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        if value < min_support:
            continue
        row = {key_name: key, "count": value}
        if examples is not None:
            row["example_session_ids"] = examples.get(key, [])
        rows.append(row)
        if len(rows) >= max(1, top_k):
            break
    return rows


def _append_example(
    examples: dict[str, list[str]],
    key: str,
    session_id: str,
    *,
    limit: int = 5,
) -> None:
    if not session_id:
        return
    rows = examples.setdefault(key, [])
    if session_id not in rows and len(rows) < limit:
        rows.append(session_id)


def build_session_learning_report(
    digests: list[dict[str, Any]],
    *,
    top_k: int = 10,
    min_support: int = 2,
) -> dict[str, Any]:
    """Aggregate session digests into a periodic agent-learning report."""
    top_k = max(1, min(int(top_k), 50))
    min_support = max(1, min(int(min_support), 100))
    surface_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    hygiene_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    success_pattern_counts: Counter[str] = Counter()
    source_client_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    blocker_examples: dict[str, list[str]] = {}
    surface_examples: dict[str, list[str]] = {}
    risk_examples: dict[str, list[str]] = {}
    risk_text_examples: dict[str, list[str]] = {}
    risk_surfaces: dict[str, set[str]] = {}
    hygiene_examples: dict[str, list[str]] = {}
    hygiene_severities: dict[str, str] = {}
    success_pattern_examples: dict[str, list[str]] = {}
    lesson_payloads: list[dict[str, Any]] = []
    kg_lessons: list[dict[str, Any]] = []
    stale_or_running: list[dict[str, Any]] = []
    validation_sessions = 0
    sessions_with_snapshot = 0
    source_client_missing = 0

    for digest in digests:
        if not isinstance(digest, dict):
            continue
        classification = classify_session(digest)
        lesson_payload = extract_session_lessons(digest)
        lesson_payloads.append(lesson_payload)

        session_id = str(
            classification.get("session_id")
            or digest.get("session_id")
            or digest.get("run_id")
            or ""
        )
        status = str(classification.get("status") or digest.get("status") or "unknown")
        status_counts[status] += 1

        source_client = str(classification.get("source_client") or "").strip()
        if source_client:
            source_client_counts[source_client] += 1
        else:
            source_client_missing += 1

        surfaces = [
            str(surface)
            for surface in classification.get("task_surfaces") or []
            if str(surface).strip()
        ]
        surface_counts.update(surfaces)
        for surface in surfaces:
            _append_example(surface_examples, surface, session_id)

        evidence_rows = [
            row
            for row in classification.get("validation_evidence") or []
            if isinstance(row, dict)
        ]
        if evidence_rows:
            validation_sessions += 1
        if bool(classification.get("has_snapshot")):
            sessions_with_snapshot += 1
        for evidence in evidence_rows:
            evidence_type = str(evidence.get("evidence_type") or "unknown")
            evidence_counts[evidence_type] += 1
            if status.lower() in {"succeeded", "completed"}:
                for surface in surfaces or ["other"]:
                    pattern = f"{surface}:{evidence_type}"
                    success_pattern_counts[pattern] += 1
                    _append_example(success_pattern_examples, pattern, session_id)

        for risk in classification.get("open_risks") or []:
            if not isinstance(risk, dict):
                continue
            label = str(risk.get("label") or "unknown")
            risk_counts[label] += 1
            _append_example(blocker_examples, f"open_risk:{label}", session_id)
            _append_example(risk_examples, label, session_id)
            risk_surfaces.setdefault(label, set()).update(surfaces)
            text = str(risk.get("text") or "").strip()
            if text:
                rows = risk_text_examples.setdefault(label, [])
                if text not in rows and len(rows) < 3:
                    rows.append(text)

        for issue in classification.get("hygiene_issues") or []:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "unknown")
            hygiene_counts[code] += 1
            _append_example(blocker_examples, f"hygiene:{code}", session_id)
            _append_example(hygiene_examples, code, session_id)
            hygiene_severities.setdefault(code, str(issue.get("severity") or "unknown"))

        for lesson in lesson_payload.get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            kg_lessons.append(
                {
                    "lesson_id": lesson.get("id"),
                    "session_id": session_id,
                    "issue_code": lesson.get("issue_code"),
                    "text": lesson.get("text"),
                    "status": lesson.get("status"),
                }
            )

        if status.lower() not in {"succeeded", "completed"} or not bool(
            classification.get("has_snapshot")
        ):
            stale_or_running.append(
                {
                    "session_id": session_id,
                    "run_id": digest.get("run_id"),
                    "status": status,
                    "has_snapshot": bool(classification.get("has_snapshot")),
                    "last_event_at": digest.get("last_event_at"),
                    "task_surfaces": surfaces,
                }
            )

    sessions_considered = len(
        [digest for digest in digests if isinstance(digest, dict)]
    )
    closure_rate = (
        round(sessions_with_snapshot / sessions_considered, 4)
        if sessions_considered
        else 0.0
    )
    validation_rate = (
        round(validation_sessions / sessions_considered, 4)
        if sessions_considered
        else 0.0
    )

    repeated_blockers: list[dict[str, Any]] = []
    for label, count in sorted(
        risk_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        if count < min_support:
            continue
        key = f"open_risk:{label}"
        repeated_blockers.append(
            {
                "kind": "open_risk",
                "code": label,
                "count": count,
                "example_session_ids": blocker_examples.get(key, []),
            }
        )
    for code, count in sorted(
        hygiene_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        if count < min_support:
            continue
        key = f"hygiene:{code}"
        repeated_blockers.append(
            {
                "kind": "hygiene_issue",
                "code": code,
                "count": count,
                "example_session_ids": blocker_examples.get(key, []),
            }
        )
    repeated_blockers.sort(key=lambda row: (-int(row["count"]), str(row["code"])))

    successful_patterns: list[dict[str, Any]] = []
    for pattern, count in sorted(
        success_pattern_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        if count < min_support:
            continue
        surface, evidence_type = pattern.split(":", 1)
        successful_patterns.append(
            {
                "surface": surface,
                "evidence_type": evidence_type,
                "pattern": pattern,
                "count": count,
                "example_session_ids": success_pattern_examples.get(pattern, []),
                "lesson": "Keep closing sessions with concrete validation evidence.",
            }
        )
        if len(successful_patterns) >= top_k:
            break
    if source_client_counts:
        successful_patterns.append(
            {
                "pattern": "source_client_present",
                "count": sum(source_client_counts.values()),
                "lesson": "Client attribution makes cross-agent behavior auditable.",
            }
        )

    recommended_next_actions: list[dict[str, Any]] = []
    if hygiene_counts.get("missing_final_snapshot"):
        recommended_next_actions.append(
            {
                "area": "agent-enforcement",
                "priority": "P0",
                "item": "Make final write_session_snapshot closeout non-optional for BR-enabled agents.",
                "evidence_count": hygiene_counts["missing_final_snapshot"],
            }
        )
    if hygiene_counts.get("succeeded_without_validation_evidence"):
        recommended_next_actions.append(
            {
                "area": "AGENTS.md",
                "priority": "P0",
                "item": "Keep validation evidence explicit in final handoffs, not just status prose.",
                "evidence_count": hygiene_counts[
                    "succeeded_without_validation_evidence"
                ],
            }
        )
    if hygiene_counts.get("prod_without_rollout_health_evidence"):
        recommended_next_actions.append(
            {
                "area": "MCP",
                "priority": "P0",
                "item": "Use directive warnings to require rollout or health evidence on prod/runtime sessions.",
                "evidence_count": hygiene_counts[
                    "prod_without_rollout_health_evidence"
                ],
            }
        )
    if source_client_missing:
        recommended_next_actions.append(
            {
                "area": "skills",
                "priority": "P1",
                "item": "Teach Codex/Claude handoff snippets to always pass source_client.",
                "evidence_count": source_client_missing,
            }
        )
    if sessions_considered:
        recommended_next_actions.extend(
            [
                {
                    "area": "KG",
                    "priority": "P1",
                    "item": "Backfill recent session snapshots into KG and query repeated failure modes by surface.",
                    "evidence_count": sessions_considered,
                },
                {
                    "area": "reporting",
                    "priority": "P2",
                    "item": "Review this agent-learning report periodically and promote stable lessons into AGENTS.md or skills.",
                    "evidence_count": sessions_considered,
                },
            ]
        )

    return {
        "sessions_considered": sessions_considered,
        "coverage": {
            "closure_rate": closure_rate,
            "validation_rate": validation_rate,
            "snapshot_count": sessions_with_snapshot,
            "source_client_missing": source_client_missing,
            "status_counts": _counter_rows(
                status_counts,
                key_name="status",
                top_k=top_k,
                min_support=1,
            ),
            "source_client_counts": _counter_rows(
                source_client_counts,
                key_name="source_client",
                top_k=top_k,
                min_support=1,
            ),
        },
        "top_task_surfaces": _counter_rows(
            surface_counts,
            key_name="surface",
            top_k=top_k,
            min_support=min_support,
            examples=surface_examples,
        ),
        "repeated_open_risks": [
            {
                "risk_label": row["risk_label"],
                "count": row["count"],
                "task_surfaces": sorted(
                    risk_surfaces.get(str(row["risk_label"]), set())
                ),
                "example_session_ids": row.get("example_session_ids", []),
                "example_texts": risk_text_examples.get(str(row["risk_label"]), []),
            }
            for row in _counter_rows(
                risk_counts,
                key_name="risk_label",
                top_k=top_k,
                min_support=min_support,
                examples=risk_examples,
            )
        ],
        "hygiene_issues": [
            {
                "risk_code": row["risk_code"],
                "severity": hygiene_severities.get(str(row["risk_code"]), "unknown"),
                "count": row["count"],
                "example_session_ids": row.get("example_session_ids", []),
            }
            for row in _counter_rows(
                hygiene_counts,
                key_name="risk_code",
                top_k=top_k,
                min_support=min_support,
                examples=hygiene_examples,
            )
        ],
        "validated_success_patterns": successful_patterns[:top_k],
        "repeated_blockers": repeated_blockers[:top_k],
        "policy_card_candidates": [
            card
            for card in build_session_policy_cards(lesson_payloads)
            if int(card.get("support_count") or 0) >= min_support
        ][:top_k],
        "kg_lesson_candidates": kg_lessons[: max(top_k, 10)],
        "stale_or_running_sessions": stale_or_running[:top_k],
        "recommended_next_actions": recommended_next_actions,
        "todo_items": recommended_next_actions,
        "rigor_guards": [
            "This report is derived from session digests and regex classifiers, not causal evidence.",
            "Use it to propose AGENTS.md, skill, MCP, or KG updates; verify before promoting a rule.",
            "Counts reflect logged sessions only and can undercount work that lacked BR snapshots.",
        ],
    }


def build_session_signal_report(
    digests: list[dict[str, Any]],
    *,
    post_snapshot_activity: list[dict[str, Any]] | None = None,
    top_k: int = 10,
    min_support: int = 2,
) -> dict[str, Any]:
    """Build a read-only signal report for silent-fail and loop-closure mining."""
    top_k = max(1, min(int(top_k), 50))
    min_support = max(1, min(int(min_support), 100))
    session_count = 0
    snapshot_count = 0
    clean_snapshot_count = 0
    open_snapshot_count = 0
    weak_clean: list[dict[str, Any]] = []
    false_negative_candidates: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    boundary_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    false_negative_counts: Counter[str] = Counter()
    boundary_examples: dict[str, list[str]] = {}
    unresolved_examples: dict[str, list[str]] = {}
    false_negative_examples: dict[str, list[str]] = {}

    for digest in digests:
        if not isinstance(digest, dict):
            continue
        session_count += 1
        session_id = str(digest.get("session_id") or digest.get("run_id") or "")
        if bool(digest.get("has_snapshot")):
            snapshot_count += 1
        if bool(digest.get("has_snapshot")) and not _items(digest.get("open_items")):
            clean_snapshot_count += 1
        elif bool(digest.get("has_snapshot")):
            open_snapshot_count += 1

        weak = classify_weak_clean_snapshot(digest)
        if weak is not None:
            weak_clean.append(weak)

        false_negative = extract_validation_parser_false_negative_candidate(digest)
        if false_negative is not None:
            false_negative_candidates.append(false_negative)
            for category in false_negative.get("matched_categories") or []:
                category_text = str(category)
                false_negative_counts[category_text] += 1
                _append_example(false_negative_examples, category_text, session_id)

        for row in extract_unresolved_next_action_themes(digest):
            unresolved_rows.append(row)
            theme = str(row.get("theme") or "unknown")
            unresolved_counts[theme] += 1
            _append_example(unresolved_examples, theme, session_id)

        for row in extract_boundary_phrase_hits(digest):
            boundary_rows.append(row)
            phrase = str(row.get("phrase") or "unknown")
            boundary_counts[phrase] += 1
            _append_example(boundary_examples, phrase, session_id)

    activity_rows = post_snapshot_activity or []
    clean_activity_rows = [
        row
        for row in activity_rows
        if bool(row.get("snapshot_open_empty")) and int(row.get("event_count") or 0) > 0
    ]
    review_activity_rows = [
        row for row in activity_rows if row.get("review_tool_names")
    ]
    artifact_activity_rows = [
        row for row in activity_rows if row.get("artifact_inspection_tool_names")
    ]
    invariant_activity_rows = [
        row for row in activity_rows if row.get("trace_only_invariant_terms")
    ]

    return {
        "sessions_considered": session_count,
        "snapshot_count": snapshot_count,
        "clean_snapshot_count": clean_snapshot_count,
        "open_snapshot_count": open_snapshot_count,
        "weak_clean_snapshot_count": len(weak_clean),
        "weak_clean_snapshots": weak_clean[:top_k],
        "boundary_phrase_counts": [
            {
                "phrase": row["phrase"],
                "count": row["count"],
                "example_session_ids": row.get("example_session_ids", []),
            }
            for row in _counter_rows(
                boundary_counts,
                key_name="phrase",
                top_k=top_k,
                min_support=min_support,
                examples=boundary_examples,
            )
        ],
        "validation_parser_false_negative_candidates": (
            false_negative_candidates[:top_k]
        ),
        "validation_parser_false_negative_summary": [
            {
                "category": row["category"],
                "count": row["count"],
                "example_session_ids": row.get("example_session_ids", []),
            }
            for row in _counter_rows(
                false_negative_counts,
                key_name="category",
                top_k=top_k,
                min_support=1,
                examples=false_negative_examples,
            )
        ],
        "unresolved_next_action_themes": [
            {
                "theme": row["theme"],
                "count": row["count"],
                "example_session_ids": row.get("example_session_ids", []),
            }
            for row in _counter_rows(
                unresolved_counts,
                key_name="theme",
                top_k=top_k,
                min_support=min_support,
                examples=unresolved_examples,
            )
        ],
        "unresolved_next_action_examples": unresolved_rows[:top_k],
        "post_snapshot_activity": {
            "session_count": len(activity_rows),
            "clean_snapshot_session_count": len(clean_activity_rows),
            "review_session_count": len(review_activity_rows),
            "artifact_inspection_session_count": len(artifact_activity_rows),
            "trace_only_invariant_session_count": len(invariant_activity_rows),
            "examples": activity_rows[:top_k],
        },
        "rigor_guards": [
            "Snapshot text mostly captures self-admitted boundaries, not silent failures.",
            "Post-snapshot activity is a candidate signal; it is not proof that the prior outcome was wrong.",
            "Validation false-negative candidates should update the parser or structured snapshot contract before they update policy.",
            "Loop closure is heuristic until NextAction/Outcome nodes link to later closing or contradicting sessions.",
        ],
    }


def build_session_kg_rows(digest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build dry-run KG rows for one session without writing to Neo4j."""
    session_id = str(digest.get("session_id") or digest.get("run_id") or "")
    snapshot = (
        digest.get("snapshot") if isinstance(digest.get("snapshot"), dict) else {}
    )
    surfaces = infer_task_surfaces(digest)
    risks = classify_open_risks(digest)
    evidence_rows = extract_validation_evidence(digest)
    lesson_rows = extract_session_lessons(digest)["lessons"]
    session_node_id = f"agent_session:{session_id}"
    nodes: list[dict[str, Any]] = [
        {
            "id": session_node_id,
            "labels": ["AgentSession"],
            "properties": {
                "session_id": session_id,
                "run_id": digest.get("run_id"),
                "source_client": digest.get("source_client"),
                "status": digest.get("status"),
                "has_snapshot": bool(digest.get("has_snapshot")),
                "last_event_at": digest.get("last_event_at"),
                "created_at": digest.get("created_at"),
                "finished_at": digest.get("finished_at"),
                "goal": snapshot.get("goal"),
                "task_surfaces": surfaces,
                "open_risk_labels": [risk["label"] for risk in risks],
                "validation_evidence_count": len(evidence_rows),
                "raw_session_json": digest,
            },
        }
    ]
    edges: list[dict[str, Any]] = []
    surface_ids: list[str] = []
    for surface in surfaces:
        surface_id = f"task_surface:{surface}"
        surface_ids.append(surface_id)
        nodes.append(
            {
                "id": surface_id,
                "labels": ["TaskSurface"],
                "properties": {"name": surface, "surface_id": surface},
            }
        )
        edges.append(
            {
                "source": session_node_id,
                "type": "WORKED_ON_SURFACE",
                "target": surface_id,
            }
        )
    for item in _items(digest.get("done_items")):
        outcome_id = _stable_id("outcome", session_id, item)
        nodes.append(
            {
                "id": outcome_id,
                "labels": ["Outcome"],
                "properties": {"text": item, "source_field": "done"},
            }
        )
        edges.append(
            {
                "source": session_node_id,
                "type": "PRODUCED_ARTIFACT",
                "target": outcome_id,
            }
        )
    next_command = str(snapshot.get("next_command") or "").strip()
    next_action_id = None
    if next_command:
        next_action_id = _stable_id("next_action", session_id, next_command)
        nodes.append(
            {
                "id": next_action_id,
                "labels": ["NextAction"],
                "properties": {"command": next_command},
            }
        )
    for risk in classify_open_risks(digest):
        nodes.append(
            {
                "id": risk["id"],
                "labels": ["OpenRisk"],
                "properties": {
                    "label": risk["label"],
                    "text": risk["text"],
                    "matched_pattern": bool(risk.get("matched_pattern")),
                },
            }
        )
        edges.append(
            {
                "source": session_node_id,
                "type": "LEFT_OPEN_RISK",
                "target": risk["id"],
            }
        )
        for surface_id in surface_ids:
            edges.append(
                {
                    "source": surface_id,
                    "type": "EXPOSED_FAILURE_MODE",
                    "target": risk["id"],
                    "properties": {"session_id": session_id},
                }
            )
        if next_action_id:
            edges.append(
                {
                    "source": risk["id"],
                    "type": "HAS_REMEDIATION",
                    "target": next_action_id,
                }
            )
    for evidence in evidence_rows:
        nodes.append(
            {
                "id": evidence["id"],
                "labels": ["ValidationEvidence"],
                "properties": {
                    "evidence_type": evidence["evidence_type"],
                    "text": evidence["text"],
                    "source_field": evidence["source_field"],
                },
            }
        )
        edges.append(
            {
                "source": session_node_id,
                "type": "VALIDATED_BY",
                "target": evidence["id"],
            }
        )
    if lesson_rows:
        policy_action_id = "next_action:agent_policy_session_handoff"
        nodes.append(
            {
                "id": policy_action_id,
                "labels": ["NextAction"],
                "properties": {
                    "command": "Review candidate lesson for AGENTS.md/session policy.",
                    "action_type": "agent_policy_update",
                },
            }
        )
    for lesson in lesson_rows:
        nodes.append(
            {
                "id": lesson["id"],
                "labels": ["Lesson"],
                "properties": {
                    "issue_code": lesson["issue_code"],
                    "text": lesson["text"],
                    "status": lesson["status"],
                },
            }
        )
        edges.append(
            {
                "source": lesson["id"],
                "type": "SHOULD_UPDATE_AGENT_POLICY",
                "target": "next_action:agent_policy_session_handoff",
                "properties": {"status": "pending_review"},
            }
        )
    return {"nodes": nodes, "edges": edges}
