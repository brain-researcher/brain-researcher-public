"""Multiverse-survival -> claim-ceiling keystone (V-HRL section 4).

Couples a real GLM multiverse run's survival profile to a claim-strength ceiling,
so a claim's status is bounded by how its effect actually survives across pipeline
variants — the empirical heart of neuroimaging robustness. This is the REAL
evidence base for the section-13 experiment:

* it IS arm (b) "no society" for empirical claims (BR's existing-style anti-
  overclaim calibration, no falsifiers, no commitment), and
* it is the BASE status that arm (c)'s falsifiers can only lower further.

Reads the exact fields produced by
``core/analysis/multiverse_robustness_report.py`` (stability.sign_consistency,
stability.active_frac, stability.effect_size_stability,
effect_distribution.n_pipelines).

Thresholds (0.8 / 0.9 / 0.5 / 0.7, the n_valid floor, the BWAS r ceiling) are
CONVENTIONS that must be calibrated against NARPS/HCP-style ground truth
(V-HRL section 8.1) before they are load-bearing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from .cards import ClaimStatusV1

# Calibration conventions — NOT settled (V-HRL section 8.1).
ROBUST_A = 0.8
ROBUST_S = 0.9
EFFECT_SIZE_STABILITY_TAU = 0.7
SENSITIVE_A = 0.5
DIRECTION_S = 0.7
N_VALID_FLOOR = 5
BWAS_R_CEILING = 0.4  # Marek 2022

# Ascending strength; the ceiling never emits `rejected` (rejection requires a
# positive refutation — a falsifier or a trap — not merely low survival).
_LADDER = (
    ClaimStatusV1.rejected,
    ClaimStatusV1.weakened,
    ClaimStatusV1.qualified,
    ClaimStatusV1.supported_within_scope,
)


class MultiverseProfile(BaseModel):
    active_frac: float  # a: fraction of pipeline variants with a supra-threshold effect
    sign_consistency: float  # s: max(frac>0, frac<0)
    n_valid: int  # number of valid pipeline variants
    effect_size_stability: float | None = None  # magnitude concordance across variants
    effect_size: float | None = (
        None  # optional |Pearson r| for the BWAS underpowered check
    )
    run_id: str | None = None
    source: str | None = None

    @classmethod
    def from_robustness_report(
        cls, report: dict[str, Any], **overrides: Any
    ) -> MultiverseProfile:
        """Build from the dict returned by multiverse_robustness_report."""
        stability = report.get("stability", {}) or {}
        effect_dist = report.get("effect_distribution", {}) or {}
        analysis_space = report.get("analysis_space", {}) or {}
        n_valid = effect_dist.get("n_pipelines")
        if n_valid is None:
            n_valid = analysis_space.get("n_pipelines", 0)
        data = {
            "active_frac": float(stability.get("active_frac", 0.0)),
            "sign_consistency": float(stability.get("sign_consistency", 0.0)),
            "n_valid": int(n_valid or 0),
            "effect_size_stability": _optional_float(
                stability.get("effect_size_stability")
            ),
            "source": (report.get("input", {}) or {}).get("contrast"),
        }
        data.update(overrides)
        return cls(**data)


class CeilingResult(BaseModel):
    status: ClaimStatusV1
    display: str
    underpowered: bool = False
    rationale: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


class ClaimRobustnessBindingResult(BaseModel):
    """Fail-closed claim -> robustness-check binding result.

    This is the P0.3 report-flow analogue of ``resolve_multiverse_ceiling``. It
    uses the content-derived ``contrast_id`` stamped onto claim provenance, not a
    filename label, and only applies a multiverse ceiling when a claim's
    ``(contrast_id, multiverse_run_id)`` resolves to exactly one robustness check.
    """

    claim_id: str
    binding_status: Literal["verified", "no_multiverse", "unbound"]
    bound_to: dict[str, str | None] | None = None
    max_claim_strength: (
        Literal[
            "contract_satisfied",
            "internally_supported",
            "scientifically_convincing",
        ]
        | None
    ) = None
    max_claim_strength_rank: int = 0
    max_verdict: ClaimStatusV1 | None = None
    display_qualifiers: list[str] = Field(default_factory=list)
    required_caveats: list[str] = Field(default_factory=list)
    reason: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


def _drop_one_floor_weakened(status: ClaimStatusV1) -> ClaimStatusV1:
    """Drop one strength tier, but never below `weakened` (underpowered != refuted)."""
    floor = _LADDER.index(ClaimStatusV1.weakened)
    return _LADDER[max(floor, _LADDER.index(status) - 1)]


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def multiverse_ceiling(profile: MultiverseProfile) -> CeilingResult:
    """Map a multiverse survival profile to a claim-strength ceiling (V-HRL section 4)."""
    a, s, n = profile.active_frac, profile.sign_consistency, profile.n_valid
    esz = profile.effect_size_stability

    if s < DIRECTION_S:
        status, display = ClaimStatusV1.weakened, "direction-unstable"
        rationale = f"sign_consistency {s:.2f} < {DIRECTION_S}: effect direction flips across pipelines."
    elif (
        a >= ROBUST_A
        and s >= ROBUST_S
        and esz is not None
        and esz >= EFFECT_SIZE_STABILITY_TAU
    ):
        status, display = ClaimStatusV1.supported_within_scope, "robust"
        rationale = (
            f"active_frac {a:.2f} >= {ROBUST_A}, sign_consistency {s:.2f} >= "
            f"{ROBUST_S}, and effect_size_stability {esz:.2f} >= "
            f"{EFFECT_SIZE_STABILITY_TAU}."
        )
    elif a >= ROBUST_A and s >= ROBUST_S:
        status, display = ClaimStatusV1.qualified, "effect-size-unstable"
        if esz is None:
            rationale = (
                f"active_frac {a:.2f} >= {ROBUST_A} and sign_consistency {s:.2f} "
                f">= {ROBUST_S}, but effect_size_stability is undefined because "
                "the median absolute effect is near zero."
            )
        else:
            rationale = (
                f"active_frac {a:.2f} >= {ROBUST_A} and sign_consistency {s:.2f} "
                f">= {ROBUST_S}, but effect_size_stability {esz:.2f} < "
                f"{EFFECT_SIZE_STABILITY_TAU}."
            )
    elif a < SENSITIVE_A:
        status, display = ClaimStatusV1.weakened, "pipeline-dependent, not robust"
        rationale = f"active_frac {a:.2f} < {SENSITIVE_A}: effect survives a minority of pipelines."
    else:
        status, display = ClaimStatusV1.qualified, "pipeline-sensitive"
        rationale = f"{SENSITIVE_A} <= active_frac {a:.2f} < {ROBUST_A}: effect is pipeline-sensitive."

    underpowered = False
    power_reasons: list[str] = []
    if n < N_VALID_FLOOR:
        underpowered = True
        power_reasons.append(f"n_valid {n} < {N_VALID_FLOOR}")
    if profile.effect_size is not None and profile.effect_size > BWAS_R_CEILING:
        underpowered = True
        power_reasons.append(
            f"effect_size {profile.effect_size:.2f} > BWAS ceiling {BWAS_R_CEILING} (Marek 2022)"
        )
    if underpowered:
        status = _drop_one_floor_weakened(status)
        display = f"{display}; underpowered"
        rationale = f"{rationale} Underpowered: {'; '.join(power_reasons)}."

    return CeilingResult(
        status=status,
        display=display,
        underpowered=underpowered,
        rationale=rationale,
        inputs={
            "active_frac": a,
            "sign_consistency": s,
            "n_valid": n,
            "effect_size_stability": esz,
            "effect_size": profile.effect_size,
        },
    )


def _claim_strength_cap_for_status(
    status: ClaimStatusV1,
) -> tuple[str | None, int]:
    if status is ClaimStatusV1.supported_within_scope:
        return "scientifically_convincing", 3
    if status is ClaimStatusV1.qualified:
        return "internally_supported", 2
    if status is ClaimStatusV1.weakened:
        return "contract_satisfied", 1
    return None, 0


def _field(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _claim_extra(claim: Any) -> dict[str, Any]:
    extra = _field(claim, "extra")
    return extra if isinstance(extra, dict) else {}


def _claim_id(claim: Any, index: int) -> str:
    value = _field(claim, "claim_id") or _field(claim, "id")
    text = str(value or "").strip()
    return text or f"claim_{index}"


def _record_dict(record: Any) -> dict[str, Any] | None:
    if isinstance(record, dict):
        return record
    model_dump = getattr(record, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            return None
        return dumped if isinstance(dumped, dict) else None
    return None


def _artifact_provenance_records(claim: Any) -> list[dict[str, Any]]:
    raw = _field(claim, "artifact_provenance")
    if raw is None:
        raw = _claim_extra(claim).get("artifact_provenance")
    if not isinstance(raw, list):
        return []
    return [
        item for item in (_record_dict(record) for record in raw) if item is not None
    ]


def _robustness_check_key(check: dict[str, Any]) -> tuple[str, str] | None:
    contrast_id = check.get("contrast_id")
    multiverse_run_id = check.get("multiverse_run_id")
    if not isinstance(contrast_id, str) or not contrast_id.strip():
        return None
    if not isinstance(multiverse_run_id, str) or not multiverse_run_id.strip():
        return None
    return contrast_id.strip(), multiverse_run_id.strip()


def _robustness_profile_from_check(check: dict[str, Any]) -> MultiverseProfile:
    return MultiverseProfile(
        active_frac=float(check.get("active_frac") or 0.0),
        sign_consistency=float(check.get("sign_consistency") or 0.0),
        n_valid=int(check.get("n_valid") or 0),
        effect_size_stability=_optional_float(check.get("effect_size_stability")),
        run_id=(
            str(check.get("multiverse_run_id"))
            if check.get("multiverse_run_id") is not None
            else None
        ),
        source=str(check.get("contrast_id") or check.get("contrast") or ""),
    )


def resolve_claim_robustness_bindings(
    claims: Sequence[Any],
    robustness_checks: Sequence[dict[str, Any]],
) -> list[ClaimRobustnessBindingResult]:
    """Resolve claim-side provenance bindings against robustness checks.

    Fail-closed states:
    - no multiverse-backed evidence -> ``no_multiverse`` and cap at
      ``internally_supported``.
    - any multiverse-backed claim without exactly one resolved
      ``(contrast_id, multiverse_run_id)`` match -> ``unbound`` and cap at
      ``internally_supported``.
    - exactly one match -> ``verified`` and apply the check's multiverse ceiling.
    """

    check_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for check in robustness_checks or []:
        if not isinstance(check, dict):
            continue
        key = _robustness_check_key(check)
        if key is None:
            continue
        check_index.setdefault(key, []).append(check)

    results: list[ClaimRobustnessBindingResult] = []
    for index, claim in enumerate(claims or []):
        claim_id = _claim_id(claim, index)
        records = _artifact_provenance_records(claim)
        multiverse_records = [
            record
            for record in records
            if isinstance(record.get("multiverse_run_id"), str)
            and record.get("multiverse_run_id", "").strip()
        ]
        if not multiverse_records:
            results.append(
                ClaimRobustnessBindingResult(
                    claim_id=claim_id,
                    binding_status="no_multiverse",
                    max_claim_strength="internally_supported",
                    max_claim_strength_rank=2,
                    display_qualifiers=["no-multiverse-robustness"],
                    required_caveats=[
                        "No multiverse robustness evidence is bound to this claim."
                    ],
                    reason=(
                        "Claim has no evidence provenance carrying a multiverse_run_id; "
                        "do not describe it as robust across analytic choices."
                    ),
                    inputs={"artifact_provenance_records": len(records)},
                )
            )
            continue

        candidate_keys: list[tuple[str, str]] = []
        unresolved_records = 0
        for record in multiverse_records:
            contrast_id = record.get("contrast_id")
            multiverse_run_id = record.get("multiverse_run_id")
            if (
                isinstance(contrast_id, str)
                and contrast_id.strip()
                and isinstance(multiverse_run_id, str)
                and multiverse_run_id.strip()
            ):
                candidate_keys.append((contrast_id.strip(), multiverse_run_id.strip()))
            else:
                unresolved_records += 1

        unique_keys = sorted(set(candidate_keys))
        if unresolved_records or len(unique_keys) != 1:
            results.append(
                ClaimRobustnessBindingResult(
                    claim_id=claim_id,
                    binding_status="unbound",
                    max_claim_strength="internally_supported",
                    max_claim_strength_rank=2,
                    display_qualifiers=["unverifiable-robustness-binding"],
                    required_caveats=[
                        "Unverifiable robustness binding: this claim's contrast could not be matched uniquely to a multiverse robustness check."
                    ],
                    reason=(
                        "Claim has multiverse-backed evidence, but the stamped "
                        "contrast binding is missing or ambiguous."
                    ),
                    inputs={
                        "multiverse_records": len(multiverse_records),
                        "unresolved_records": unresolved_records,
                        "candidate_bindings": [
                            {"contrast_id": contrast_id, "multiverse_run_id": run_id}
                            for contrast_id, run_id in unique_keys
                        ],
                    },
                )
            )
            continue

        key = unique_keys[0]
        matches = check_index.get(key, [])
        if len(matches) != 1:
            results.append(
                ClaimRobustnessBindingResult(
                    claim_id=claim_id,
                    binding_status="unbound",
                    bound_to={"contrast_id": key[0], "multiverse_run_id": key[1]},
                    max_claim_strength="internally_supported",
                    max_claim_strength_rank=2,
                    display_qualifiers=["unverifiable-robustness-binding"],
                    required_caveats=[
                        "Unverifiable robustness binding: the claimed contrast did not resolve to exactly one robustness check."
                    ],
                    reason=(
                        f"Expected exactly one robustness check for the claim binding; "
                        f"found {len(matches)}."
                    ),
                    inputs={
                        "contrast_id": key[0],
                        "multiverse_run_id": key[1],
                        "n_matches": len(matches),
                    },
                )
            )
            continue

        check = matches[0]
        ceiling = multiverse_ceiling(_robustness_profile_from_check(check))
        cap, rank = _claim_strength_cap_for_status(ceiling.status)
        caveats: list[str] = []
        if ceiling.status is not ClaimStatusV1.supported_within_scope:
            caveats.append(
                f"Multiverse robustness ceiling is {ceiling.status.value}: {ceiling.rationale}"
            )
        results.append(
            ClaimRobustnessBindingResult(
                claim_id=claim_id,
                binding_status="verified",
                bound_to={"contrast_id": key[0], "multiverse_run_id": key[1]},
                max_claim_strength=cap,  # type: ignore[arg-type]
                max_claim_strength_rank=rank,
                max_verdict=ceiling.status,
                display_qualifiers=[ceiling.display],
                required_caveats=caveats,
                reason=ceiling.rationale,
                inputs={
                    "contrast_id": key[0],
                    "multiverse_run_id": key[1],
                    "ceiling_inputs": ceiling.inputs,
                },
            )
        )

    return results


def resolve_multiverse_ceiling(
    *,
    claim_contrast: str | None,
    multiverse_run_id: str | None,
    profiles: Sequence[MultiverseProfile],
) -> tuple[CeilingResult, str]:
    """Bind a claim to ITS contrast's multiverse profile among many — FAIL-CLOSED.

    ``multiverse_ceiling`` trusts that the profile it is handed is the right one. When a real
    run carries many contrasts, that trust is the mis-bind hazard: clamping a claim with the
    *wrong* contrast's robustness. This resolver matches on (contrast label, run_id); if the
    binding is not *uniquely verified* it does NOT apply the ceiling — the claim is capped at
    ``qualified`` (you cannot reach ``supported_within_scope`` on robustness you cannot verify
    is about this claim) and the reason is recorded. A mis-bound clamp is worse than no clamp.

    Returns ``(CeilingResult, binding_status)`` with binding_status in
    ``{"verified", "no_multiverse", "unbound"}``. The match key is the contrast LABEL
    (``MultiverseProfile.source``): FitLins contrast names are already distinct strings, and
    society claims carry no GLM contrast definition, so a content-hashed contrast id is not
    used here.
    """
    if not profiles:
        return (
            CeilingResult(
                status=ClaimStatusV1.qualified,
                display="no-multiverse-evidence",
                rationale=(
                    "No multiverse robustness profile for this claim; cannot reach "
                    "supported_within_scope without it."
                ),
                inputs={
                    "claim_contrast": claim_contrast,
                    "multiverse_run_id": multiverse_run_id,
                },
            ),
            "no_multiverse",
        )

    matches = [
        profile
        for profile in profiles
        if claim_contrast
        and profile.source == claim_contrast
        and (
            multiverse_run_id is None
            or profile.run_id is None
            or profile.run_id == multiverse_run_id
        )
    ]
    if len(matches) == 1:
        return multiverse_ceiling(matches[0]), "verified"

    return (
        CeilingResult(
            status=ClaimStatusV1.qualified,
            display="unverifiable-robustness-binding",
            rationale=(
                f"robustness binding unresolved (matches={len(matches)}, "
                f"claim_contrast={claim_contrast!r}); fail-closed, ceiling not applied."
            ),
            inputs={
                "claim_contrast": claim_contrast,
                "multiverse_run_id": multiverse_run_id,
                "n_profiles": len(profiles),
                "n_matches": len(matches),
            },
        ),
        "unbound",
    )
