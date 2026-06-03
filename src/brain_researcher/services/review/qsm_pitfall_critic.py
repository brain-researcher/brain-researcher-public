"""QSM-specific anti-pitfall review helpers.

These checks are intentionally narrow and deterministic.  They do not try to
write a full QSM reconstruction recipe; they prevent known-bad advice from
passing review or retrieval as if it were scientifically safe.
"""

from __future__ import annotations

import json
import re
from typing import Any

from brain_researcher.core.contracts.code_review import (
    CodeReviewVerdict,
    ReviewFinding,
)

_TOKEN_RE = re.compile(r"[a-z0-9_+-]+")

_QSM_MARKERS = frozenset(
    {
        "qsm",
        "qsm_reconstruction",
        "quantitative susceptibility",
        "susceptibility mapping",
        "chi map",
        "chimap",
        "dipole inversion",
        "dipole_inversion",
        "local field",
        "local_field",
        "background field",
        "background_field",
        "v-sharp",
        "vsharp",
        "resharp",
        "multi-echo gre",
        "multi_echo_gre",
        "megre",
    }
)

_QSM_ALLOWED_MARKERS = frozenset(
    {
        "qsm",
        "quantitative susceptibility",
        "susceptibility",
        "dipole",
        "dipole_inversion",
        "local field",
        "local_field",
        "background field",
        "background_field",
        "v-sharp",
        "vsharp",
        "resharp",
        "sharp",
        "lbv",
        "tkd",
        "medi",
        "fansi",
        "phase unwrapping",
        "multi-echo gre",
        "multi_echo_gre",
        "megre",
        "chi map",
        "chimap",
    }
)

_QSM_BLOCKED_MARKERS = frozenset(
    {
        "fmriprep",
        "mriqc",
        "feat",
        "functional connectivity",
        "resting state",
        "resting-state",
        "tractography",
        "qsiprep",
        "vbm",
        "voxel based morphometry",
        "voxel-based morphometry",
        "fsl_prepare_fieldmap",
        "fieldmap distortion",
        "topup",
        "eddy",
    }
)

_BACKGROUND_MARKERS = frozenset(
    {
        "background removal",
        "background_removal",
        "background_or_local_field_removal",
        "background field removal",
        "background_field_removal",
        "local_field_removal",
        "local field",
        "local_field",
        "local-field",
        "v-sharp",
        "vsharp",
        "resharp",
        "sharp",
        "lbv",
        "pdf",
        "projection onto dipole fields",
    }
)

_INVERSION_MARKERS = frozenset(
    {
        "dipole inversion",
        "dipole_inversion",
        "invert",
        "inversion",
        "admm_tv",
        "admm",
        "tv",
        "total variation",
        "tkd",
        "tikhonov",
        "medi",
        "fansi",
    }
)

_DIRECT_TOTAL_FIELD_PATTERNS = (
    re.compile(
        r"(?:direct(?:ly)?\s+)?(?:run|apply|perform)?\s*"
        r"(?:admm|tv|total variation|tkd|tikhonov|dipole inversion|inversion)"
        r".{0,80}(?:total field|inter-echo field|raw field|delta[_ -]?ppm)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:total field|inter-echo field|raw field|delta[_ -]?ppm)"
        r".{0,80}(?:direct(?:ly)?\s+)?"
        r"(?:admm|tv|total variation|tkd|tikhonov|dipole inversion|inversion)",
        re.IGNORECASE | re.DOTALL,
    ),
)

_BAD_INVERSION_INPUT_NAMES = frozenset(
    {
        "totalfield",
        "total_field",
        "fieldppm",
        "field_ppm",
        "rawfield",
        "raw_field",
        "phasefield",
        "phase_field",
        "interecho",
        "inter_echo",
        "interechofield",
        "inter_echo_field",
        "deltappm",
        "delta_ppm",
    }
)

_OUTPUT_KEYS = frozenset(
    {
        "output",
        "outputs",
        "out",
        "artifact",
        "artifact_name",
        "result",
        "produces",
    }
)

_INPUT_KEYS = frozenset(
    {
        "input",
        "inputs",
        "in",
        "source",
        "source_field",
        "input_field",
        "field",
        "uses",
        "consumes",
    }
)

ANTI_PITFALL_CHECKLIST = [
    {
        "id": "total_field_direct_inversion_forbidden",
        "severity": "critical",
        "assertion": (
            "Dipole inversion must consume a local field produced by explicit "
            "background/local-field removal; direct inversion of total, raw, or "
            "inter-echo field is forbidden."
        ),
    },
    {
        "id": "phase_unit_te_conversion_check",
        "severity": "high",
        "assertion": (
            "Phase-to-field conversion must account for delta_TE and B0/gamma "
            "scaling or explicitly justify equivalent units."
        ),
    },
    {
        "id": "bare_tkd_contrast_loss",
        "severity": "medium",
        "assertion": (
            "TKD-only reconstructions require contrast-preservation mitigation "
            "or QC because raw NRMSE can improve while detrended tissue and DGM "
            "metrics fail."
        ),
    },
    {
        "id": "over_smoothing_hidden_metric_failure",
        "severity": "high",
        "assertion": (
            "Visual smoothness is insufficient; local contrast and detrended "
            "regional proxies must be checked."
        ),
    },
    {
        "id": "calcification_streak_tradeoff",
        "severity": "medium",
        "assertion": (
            "Calcification streak suppression must not erase deep-gray-matter or "
            "tissue susceptibility contrast."
        ),
    },
]

VERIFICATION_PROTOCOL = [
    {
        "id": "geometry_and_finite_check",
        "expected": "Output shape, affine, voxel size, and finite mask ratio match input.",
    },
    {
        "id": "chi_range_check",
        "expected": "Brain susceptibility values should stay in a plausible ppm range; extreme global range suggests unit/scaling failure.",
    },
    {
        "id": "local_field_dataflow_check",
        "expected": "Dipole inversion input is explicitly the output of background/local-field removal.",
    },
    {
        "id": "contrast_proxy_check",
        "expected": "DGM/tissue contrast proxies remain non-degenerate after detrending or high-pass comparison.",
    },
    {
        "id": "calcification_streak_proxy",
        "expected": "Calcification-adjacent residual variation is checked separately from global smoothness.",
    },
]

HARD_CONSTRAINTS = [
    "Dipole inversion must consume an explicitly named local_field.",
    "Direct inversion of total, raw, inter-echo, or phase-difference fields is forbidden.",
    "Background/local-field removal output must be the dipole-inversion input.",
    "Phase-to-field conversion must state delta_TE and B0/gamma scaling or an equivalent unit convention.",
]

NON_DISPLACEMENT_NOTICE = (
    "Use this QSM response as an audit-only constraint set. Do not replace the "
    "agent's reconstruction algorithm unless a hard constraint is violated."
)

FORBIDDEN_GUIDANCE = [
    "Do not suggest generic fMRI preprocessing, fMRIPrep, FEAT, or fieldmap-distortion workflows for QSM reconstruction.",
    "Do not prescribe full-resolution iterative TV/ADMM as mandatory.",
    "Do not recommend TKD-only without contrast-preservation QC.",
]

QC_PROTOCOL = [
    "Check output shape, affine, voxel size, and finite voxel ratio before finalizing.",
    "Check robust susceptibility quantiles, IQR, and standard deviation in the brain mask.",
    "Check a local high-pass or detrended contrast proxy to catch contrast collapse.",
    "Check calcification/streak behavior separately from global smoothness when calcification is present.",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            parts.append(str(key))
            parts.append(_text(item))
        return " ".join(parts)
    if isinstance(value, list | tuple | set):
        return " ".join(_text(item) for item in value)
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _normalized_text(*values: Any) -> str:
    return " ".join(_text(value) for value in values).lower()


def _contains_marker(text: str, marker: str) -> bool:
    marker = marker.strip().lower()
    if not marker:
        return False
    if re.fullmatch(r"[a-z0-9_+-]+", marker):
        return re.search(rf"(?<![a-z0-9_+-]){re.escape(marker)}(?![a-z0-9_+-])", text) is not None
    return marker in text


def normalize_modality_list(modality: Any) -> list[str]:
    if modality is None:
        return []
    if isinstance(modality, str):
        raw = modality.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return [raw]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [raw]
    if isinstance(modality, list | tuple | set):
        return [str(item).strip() for item in modality if str(item).strip()]
    return [str(modality).strip()] if str(modality).strip() else []


def is_qsm_task(*values: Any) -> bool:
    text = _normalized_text(*values)
    if any(_contains_marker(text, marker) for marker in _QSM_MARKERS):
        return True
    tokens = set(_TOKEN_RE.findall(text))
    return bool({"dipole", "inversion"} <= tokens and {"phase", "field"} & tokens)


def _candidate_text(card: dict[str, Any]) -> str:
    return _normalized_text(card)


def _candidate_is_qsm_specific(card: dict[str, Any]) -> bool:
    text = _candidate_text(card)
    return any(_contains_marker(text, marker) for marker in _QSM_ALLOWED_MARKERS)


def _candidate_is_blocked_for_qsm(card: dict[str, Any]) -> bool:
    text = _candidate_text(card)
    return any(_contains_marker(text, marker) for marker in _QSM_BLOCKED_MARKERS)


def qsm_retrieval_gate(
    *,
    query: str,
    domain: Any = None,
    modality: Any = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    modalities = normalize_modality_list(modality)
    if not is_qsm_task(query, domain, modalities):
        return None

    candidate_rows = [c for c in candidates or [] if isinstance(c, dict)]
    blocked = [
        str(card.get("name") or card.get("id") or "").strip()
        for card in candidate_rows
        if _candidate_is_blocked_for_qsm(card)
    ]
    qsm_specific = [card for card in candidate_rows if _candidate_is_qsm_specific(card)]
    usable = bool(qsm_specific)
    precision = (
        len(qsm_specific) / len(candidate_rows) if candidate_rows else 0.0
    )
    status = "ok" if usable and precision >= 0.5 else "low_confidence"
    return {
        "task_type": "qsm_reconstruction",
        "subdomain_confidence": 0.92,
        "retrieval_precision_estimate": round(float(precision), 3),
        "retrieval_status": status,
        "usable_guidance": bool(usable),
        "should_advise": bool(usable),
        "advice_mode": "audit_only" if usable else "abstain",
        "hard_constraints": HARD_CONSTRAINTS,
        "non_displacement_notice": NON_DISPLACEMENT_NOTICE,
        "qc_protocol": QC_PROTOCOL,
        "forbidden_guidance": FORBIDDEN_GUIDANCE,
        "blocked_candidate_names": [name for name in blocked if name],
        "reason": None
        if usable
        else (
            "No QSM-specific evidence/tool candidate was retrieved; generic "
            "fMRI, fieldmap-distortion, tractography, or VBM candidates are not "
            "appropriate for QSM reconstruction advice."
        ),
        "anti_pitfall_checklist": ANTI_PITFALL_CHECKLIST,
        "verification_protocol": VERIFICATION_PROTOCOL,
    }


def filter_qsm_tool_candidates(
    *,
    query: str,
    domain: Any = None,
    modality: Any = None,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    gate = qsm_retrieval_gate(
        query=query,
        domain=domain,
        modality=modality,
        candidates=candidates,
    )
    if gate is None:
        return candidates, None

    filtered = [
        card
        for card in candidates
        if isinstance(card, dict)
        and _candidate_is_qsm_specific(card)
        and not _candidate_is_blocked_for_qsm(card)
    ]
    if not filtered:
        gate = dict(gate)
        gate["retrieval_status"] = "low_confidence"
        gate["usable_guidance"] = False
        gate["should_advise"] = False
        gate["advice_mode"] = "abstain"
    return filtered, gate


def _plan_text(plan: Any, workflow_id: str | None = None) -> str:
    return _normalized_text(workflow_id, plan)


def _has_any(text: str, markers: frozenset[str]) -> bool:
    return any(_contains_marker(text, marker) for marker in markers)


def _mentions_direct_total_field_inversion(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DIRECT_TOTAL_FIELD_PATTERNS)


def _mentions_direct_total_field_inversion_in_plan(plan: Any) -> bool:
    for step in _iter_steps(plan):
        step_text = _normalized_text(step)
        if _mentions_direct_total_field_inversion(step_text):
            return True
        if _has_any(step_text, _INVERSION_MARKERS):
            for input_value in _collect_key_values(step, _INPUT_KEYS):
                if _looks_like_bad_inversion_input(input_value):
                    return True
    return False


def _field_name(value: Any) -> str:
    text = _normalized_text(value)
    return re.sub(r"[^a-z0-9_]+", "", text)


def _looks_like_local_field(value: Any) -> bool:
    name = _field_name(value)
    return name in {
        "localfield",
        "local_field",
        "resharplocalfield",
        "resharp_local_field",
        "vsharplocalfield",
        "vsharp_local_field",
        "backgroundremovedfield",
        "background_removed_field",
    } or ("local" in name and "field" in name)


def _looks_like_bad_inversion_input(value: Any) -> bool:
    name = _field_name(value)
    return name in _BAD_INVERSION_INPUT_NAMES or any(
        bad in name
        for bad in (
            "totalfield",
            "fieldppm",
            "rawfield",
            "phasefield",
            "interechofield",
            "deltappm",
        )
    )


def _iter_steps(plan: Any) -> list[Any]:
    if isinstance(plan, dict):
        steps = plan.get("steps") or plan.get("plan_steps") or plan.get("pipeline")
        if isinstance(steps, list):
            return list(steps)
        return [plan]
    if isinstance(plan, list | tuple):
        return list(plan)
    return [plan]


def _collect_key_values(value: Any, keys: frozenset[str]) -> list[Any]:
    out: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_norm = str(key).strip().lower()
            if key_norm in keys:
                out.append(item)
            out.extend(_collect_key_values(item, keys))
    elif isinstance(value, list | tuple | set):
        for item in value:
            out.extend(_collect_key_values(item, keys))
    return out


def _step_mentions_background_output_local(step_text: str) -> bool:
    if not _has_any(step_text, _BACKGROUND_MARKERS):
        return False
    if not any(marker in step_text for marker in ("local field", "local_field")):
        return False
    return any(
        marker in step_text
        for marker in (
            "output",
            "obtain",
            "produce",
            "estimate",
            "derive",
            "result",
            "to get",
        )
    )


def _step_mentions_inversion_input_local(step_text: str) -> bool:
    if not _has_any(step_text, _INVERSION_MARKERS):
        return False
    if not any(marker in step_text for marker in ("local field", "local_field")):
        return False
    return any(
        marker in step_text
        for marker in (
            "input",
            "using",
            "use",
            "consume",
            "feed",
            "from",
            "on the local",
        )
    )


def _has_explicit_local_field_dataflow(plan: Any) -> bool:
    bg_outputs: set[str] = set()
    inversion_inputs: set[str] = set()
    natural_bg_output = False
    natural_inv_input = False

    for step in _iter_steps(plan):
        step_text = _normalized_text(step)
        if _has_any(step_text, _BACKGROUND_MARKERS):
            for output in _collect_key_values(step, _OUTPUT_KEYS):
                if _looks_like_local_field(output):
                    bg_outputs.add(_field_name(output))
            natural_bg_output = natural_bg_output or _step_mentions_background_output_local(step_text)
        if _has_any(step_text, _INVERSION_MARKERS):
            for input_value in _collect_key_values(step, _INPUT_KEYS):
                if _looks_like_local_field(input_value):
                    inversion_inputs.add(_field_name(input_value))
            natural_inv_input = natural_inv_input or _step_mentions_inversion_input_local(step_text)

    if bg_outputs and inversion_inputs and bool(bg_outputs & inversion_inputs):
        return True
    return bool(natural_bg_output and natural_inv_input)


def _make_finding(
    rule_id: str,
    *,
    severity: str,
    action: str,
    message: str,
    suggested_fix: str,
) -> ReviewFinding:
    return ReviewFinding(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        message=message,
        suggested_fix=suggested_fix,
        reason_tags=["qsm_reconstruction", "domain_invariant", "anti_pitfall"],
    )


def _roll_up(findings: list[ReviewFinding]) -> tuple[str, str]:
    if any(f.action == "block" or f.severity == "critical" for f in findings):
        return "block", "critical"
    if any(f.severity == "error" for f in findings):
        return "revise", "high"
    if any(f.severity == "warn" for f in findings):
        return "approve_with_warnings", "medium"
    return "approve", "low"


def _rationale(findings: list[ReviewFinding], decision: str) -> str:
    if not findings:
        return f"QSM pitfall review passed all checks. Decision: {decision}."
    head = [f"QSM pitfall review - Decision: {decision}. {len(findings)} finding(s):"]
    for finding in findings:
        head.append(
            f"[{finding.severity.upper()}] {finding.rule_id}: {finding.message}"
        )
    return " | ".join(head)


def review_qsm_plan_payload(
    plan: dict[str, Any] | Any,
    *,
    workflow_id: str | None = None,
) -> CodeReviewVerdict | None:
    text = _plan_text(plan, workflow_id=workflow_id)
    if not is_qsm_task(text, workflow_id):
        return None

    findings: list[ReviewFinding] = []
    has_inversion = _has_any(text, _INVERSION_MARKERS)
    has_background = _has_any(text, _BACKGROUND_MARKERS)
    has_direct_total = _mentions_direct_total_field_inversion_in_plan(plan)
    has_explicit_dataflow = _has_explicit_local_field_dataflow(plan)

    if has_inversion and has_direct_total:
        findings.append(
            _make_finding(
                "QSM_TOTAL_FIELD_DIRECT_INVERSION_FORBIDDEN",
                severity="critical",
                action="block",
                message=(
                    "Dipole inversion appears to consume a total, raw, or "
                    "inter-echo field directly."
                ),
                suggested_fix=(
                    "Estimate the total field, run explicit background/local-field "
                    "removal such as RESHARP/V-SHARP/LBV, and feed the resulting "
                    "local field into dipole inversion."
                ),
            )
        )

    if has_inversion and not has_background:
        findings.append(
            _make_finding(
                "QSM_LOCAL_FIELD_REQUIRED_BEFORE_DIPOLE_INVERSION",
                severity="critical",
                action="block",
                message=(
                    "QSM plan includes dipole inversion but does not explicitly "
                    "estimate a local field via background field removal first."
                ),
                suggested_fix=(
                    "Add an explicit background/local-field removal step and state "
                    "that the inversion input is the local field, not the total or "
                    "raw inter-echo field."
                ),
            )
        )

    if (
        has_inversion
        and has_background
        and not has_direct_total
        and not has_explicit_dataflow
    ):
        findings.append(
            _make_finding(
                "QSM_AMBIGUOUS_LOCAL_FIELD_DATAFLOW",
                severity="critical",
                action="block",
                message=(
                    "QSM plan mentions background/local-field removal but does "
                    "not explicitly show that dipole inversion consumes the "
                    "local field produced by that step."
                ),
                suggested_fix=(
                    "Add explicit dataflow such as total_field -> "
                    "background_removal(output=local_field) -> "
                    "dipole_inversion(input=local_field)."
                ),
            )
        )

    if "tkd" in text and not any(
        marker in text
        for marker in (
            "tikhonov",
            "admm",
            "total variation",
            "tv regular",
            "medi",
            "fansi",
            "contrast-preserving",
            "contrast preserving",
        )
    ):
        findings.append(
            _make_finding(
                "QSM_BARE_TKD_CONTRAST_LOSS_RISK",
                severity="error",
                action="warn",
                message=(
                    "TKD-only QSM can improve raw visual or NRMSE-like metrics "
                    "while harming detrended tissue and deep-gray-matter contrast."
                ),
                suggested_fix=(
                    "Add contrast-preservation mitigation or run DGM/tissue "
                    "contrast proxies before accepting a TKD-only reconstruction."
                ),
            )
        )

    if "phase" in text and not any(
        marker in text for marker in ("delta_te", "delta te", "echo time", "te=", "tes=")
    ):
        findings.append(
            _make_finding(
                "QSM_PHASE_UNIT_TE_CONVERSION_CHECK_MISSING",
                severity="error",
                action="warn",
                message=(
                    "Plan mentions phase processing but does not explicitly check "
                    "delta_TE / echo-time scaling."
                ),
                suggested_fix=(
                    "State how phase differences are converted to field/ppm using "
                    "delta_TE and B0/gamma scaling or an equivalent convention."
                ),
            )
        )

    decision, risk_level = _roll_up(findings)
    checklist = [
        item["assertion"] for item in ANTI_PITFALL_CHECKLIST
    ] + [item["expected"] for item in VERIFICATION_PROTOCOL]
    return CodeReviewVerdict(
        decision=decision,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        findings=findings,
        checklist_generated=checklist,
        reviewer_rationale=_rationale(findings, decision),
    )


_INVERSION_CALL_RE = re.compile(
    r"(?P<callee>\b[a-zA-Z_][a-zA-Z0-9_]*"
    r"(?:admm|tv|tkd|dipole|invert|inversion|qsm)"
    r"[a-zA-Z0-9_]*\b)\s*\((?P<args>[^)]{0,300})\)",
    re.IGNORECASE | re.DOTALL,
)

_ASSIGN_LOCAL_FIELD_RE = re.compile(
    r"\b(?P<name>[a-zA-Z_][a-zA-Z0-9_]*local[a-zA-Z0-9_]*field[a-zA-Z0-9_]*)\s*=",
    re.IGNORECASE,
)


def _first_call_arg(args: str) -> str:
    first = args.split(",", 1)[0]
    return first.strip().strip("\"'")


def _has_background_removal_code(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "background_removal",
            "background removal",
            "resharp",
            "vsharp",
            "v-sharp",
            "sharp",
            "lbv",
            "local_field",
            "local field",
        )
    )


def review_qsm_implementation_payload(
    code: str,
    *,
    filename: str | None = None,
) -> CodeReviewVerdict:
    """Review generated QSM code for direct-inversion dataflow hazards."""

    text = _normalized_text(filename, code)
    findings: list[ReviewFinding] = []
    local_vars = {
        _field_name(match.group("name"))
        for match in _ASSIGN_LOCAL_FIELD_RE.finditer(code or "")
    }
    has_inversion_call = False
    has_bad_inversion_input = False
    has_ambiguous_inversion_input = False

    for match in _INVERSION_CALL_RE.finditer(code or ""):
        has_inversion_call = True
        arg = _first_call_arg(match.group("args"))
        arg_name = _field_name(arg)
        if _looks_like_bad_inversion_input(arg):
            has_bad_inversion_input = True
            continue
        if arg_name and arg_name not in local_vars and not _looks_like_local_field(arg):
            has_ambiguous_inversion_input = True

    if has_inversion_call and has_bad_inversion_input:
        findings.append(
            _make_finding(
                "QSM_IMPLEMENTATION_DIRECT_FIELD_INVERSION",
                severity="critical",
                action="block",
                message=(
                    "QSM implementation appears to pass a total/raw/inter-echo "
                    "or phase-derived field directly into a dipole inversion call."
                ),
                suggested_fix=(
                    "Route total_field through explicit background/local-field "
                    "removal and call inversion with the resulting local_field."
                ),
            )
        )

    if has_inversion_call and not _has_background_removal_code(text):
        findings.append(
            _make_finding(
                "QSM_IMPLEMENTATION_MISSING_BACKGROUND_REMOVAL",
                severity="critical",
                action="block",
                message=(
                    "QSM implementation contains an inversion call but no "
                    "detectable background/local-field removal stage."
                ),
                suggested_fix=(
                    "Create an explicit local_field via RESHARP/V-SHARP/LBV or "
                    "equivalent background removal before dipole inversion."
                ),
            )
        )

    if (
        has_inversion_call
        and _has_background_removal_code(text)
        and not has_bad_inversion_input
        and has_ambiguous_inversion_input
    ):
        findings.append(
            _make_finding(
                "QSM_IMPLEMENTATION_AMBIGUOUS_INVERSION_INPUT",
                severity="critical",
                action="block",
                message=(
                    "QSM implementation has background/local-field operations, "
                    "but at least one inversion call does not clearly consume a "
                    "local_field variable."
                ),
                suggested_fix=(
                    "Name the background-removal output local_field and pass that "
                    "variable directly into dipole inversion."
                ),
            )
        )

    if "tkd" in text and not any(
        marker in text
        for marker in (
            "tikhonov",
            "admm",
            "total variation",
            "tv regular",
            "medi",
            "fansi",
            "contrast",
            "highpass",
            "high-pass",
        )
    ):
        findings.append(
            _make_finding(
                "QSM_IMPLEMENTATION_TKD_WITHOUT_CONTRAST_QC",
                severity="error",
                action="warn",
                message=(
                    "QSM implementation appears to rely on TKD without a visible "
                    "contrast-preservation or high-pass QC check."
                ),
                suggested_fix=(
                    "Add contrast proxy/QC checks or use a contrast-preserving "
                    "regularized inversion."
                ),
            )
        )

    decision, risk_level = _roll_up(findings)
    checklist = [
        *HARD_CONSTRAINTS,
        *QC_PROTOCOL,
        "Implementation review is audit-only and must not prescribe a replacement pipeline.",
    ]
    return CodeReviewVerdict(
        decision=decision,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        findings=findings,
        checklist_generated=checklist,
        reviewer_rationale=_rationale(findings, decision),
    )


def merge_verdicts(
    primary: CodeReviewVerdict,
    domain: CodeReviewVerdict | None,
) -> CodeReviewVerdict:
    if domain is None:
        return primary
    findings = list(primary.findings) + list(domain.findings)
    decision, risk_level = _roll_up(findings)
    checklist = list(primary.checklist_generated)
    for item in domain.checklist_generated:
        if item not in checklist:
            checklist.append(item)
    kg_rules = list(primary.kg_rules_consulted)
    for item in domain.kg_rules_consulted:
        if item not in kg_rules:
            kg_rules.append(item)
    if domain.findings:
        rationale = f"{primary.reviewer_rationale} | {domain.reviewer_rationale}"
    else:
        rationale = primary.reviewer_rationale
    return CodeReviewVerdict(
        decision=decision,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        findings=findings,
        kg_rules_consulted=kg_rules,
        checklist_generated=checklist,
        reviewer_rationale=rationale,
    )


__all__ = [
    "ANTI_PITFALL_CHECKLIST",
    "VERIFICATION_PROTOCOL",
    "filter_qsm_tool_candidates",
    "is_qsm_task",
    "merge_verdicts",
    "normalize_modality_list",
    "qsm_retrieval_gate",
    "review_qsm_implementation_payload",
    "review_qsm_plan_payload",
]
