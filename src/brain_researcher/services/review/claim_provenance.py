"""Report-code traceability: bind report claims to what actually ran.

The HCP netmats incident's root cause was a report describing the *intended*
analysis rather than the analysis that *actually executed*. This module makes
that failure detectable: every quantitative claim in a report must carry a
provenance pointer (artifact + hash, code ref, config), and the pointer is
validated against the run's real provenance (file manifest + plan steps). A
claim that cites an artifact the run never produced, or whose hash does not
match, fails validation — so a report cannot silently describe work that did
not happen.

Pure logic; no I/O. The validator consumes a ``RunProvenanceIndex`` built from a
``CodeReviewBundle`` (or raw manifests) and a list of ``ClaimProvenance``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimProvenance(BaseModel):
    """Provenance a single report claim must carry to be traceable."""

    claim_id: str
    statement: str = ""
    artifact_path: str | None = Field(
        default=None, description="Run-relative path of the artifact supporting the claim."
    )
    artifact_sha256: str | None = Field(
        default=None, description="Expected checksum, 'sha256:<hex>' or bare hex."
    )
    code_ref: str | None = Field(
        default=None, description="Producing code: tool id, or 'tool:step_id'."
    )
    config_digest: str | None = Field(
        default=None, description="Digest/summary of the config that produced the artifact."
    )


class ClaimProvenanceVerdict(BaseModel):
    """Per-claim traceability result."""

    claim_id: str
    ok: bool
    has_provenance: bool
    artifact_resolved: bool
    artifact_hash_matches: bool | None
    code_resolved: bool
    issues: list[str] = Field(default_factory=list)


def _normalize_sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    return text or None


class RunProvenanceIndex(BaseModel):
    """What actually ran: produced artifacts (path -> checksum) and code refs."""

    artifacts: dict[str, str | None] = Field(default_factory=dict)
    code_refs: set[str] = Field(default_factory=set)

    def resolves_artifact(self, path: str | None) -> bool:
        return bool(path) and path in self.artifacts

    def checksum_for(self, path: str | None) -> str | None:
        return self.artifacts.get(path) if path else None

    def resolves_code(self, code_ref: str | None) -> bool:
        if not code_ref:
            return False
        if code_ref in self.code_refs:
            return True
        # Allow a bare tool id to resolve when only "tool:step" refs are known.
        return any(ref.split(":", 1)[0] == code_ref for ref in self.code_refs)


def build_run_provenance_index(bundle: Any) -> RunProvenanceIndex:
    """Build the index from a CodeReviewBundle's manifests (best-effort)."""

    artifacts: dict[str, str | None] = {}
    code_refs: set[str] = set()

    observed = getattr(bundle, "observed_artifacts", None) or {}
    analysis_bundle = observed.get("analysis_bundle") if isinstance(observed, dict) else None

    # File manifest: produced artifacts + checksums.
    manifest = (
        analysis_bundle.get("file_manifest")
        if isinstance(analysis_bundle, dict)
        else None
    )
    for entry in manifest or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path:
            artifacts[path] = _normalize_sha(entry.get("checksum"))

    # Provenance outputs (ProvenanceV1-style) as a second artifact source.
    provenance = observed.get("provenance") if isinstance(observed, dict) else None
    for output in (provenance or {}).get("outputs", []) if isinstance(provenance, dict) else []:
        if isinstance(output, dict) and isinstance(output.get("uri"), str):
            artifacts.setdefault(output["uri"], _normalize_sha(output.get("sha256")))

    # Code refs: tool ids and tool:step_id from plan steps.
    for step in getattr(bundle, "plan_steps", None) or []:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        code_refs.add(tool)
        step_id = step.get("step_id")
        if step_id is not None and str(step_id):
            code_refs.add(f"{tool}:{step_id}")

    return RunProvenanceIndex(artifacts=artifacts, code_refs=code_refs)


def validate_claim_provenance(
    claims: list[ClaimProvenance],
    index: RunProvenanceIndex,
    *,
    require_full: bool = True,
) -> list[ClaimProvenanceVerdict]:
    """Validate each claim's provenance against what actually ran.

    ``require_full`` requires BOTH an artifact pointer and a code ref. Otherwise
    either alone satisfies ``has_provenance``. A claim is ``ok`` only when it has
    provenance, its artifact resolves in the run manifest, its checksum matches
    (when both expected and recorded), and its code ref resolves.
    """

    verdicts: list[ClaimProvenanceVerdict] = []
    for claim in claims:
        issues: list[str] = []
        has_artifact = bool(claim.artifact_path)
        has_code = bool(claim.code_ref)
        has_provenance = (
            (has_artifact and has_code) if require_full else (has_artifact or has_code)
        )
        if not has_provenance:
            missing = []
            if not has_artifact:
                missing.append("artifact_path")
            if require_full and not has_code:
                missing.append("code_ref")
            if not require_full and not has_artifact and not has_code:
                missing = ["artifact_path", "code_ref"]
            issues.append(f"missing provenance ({', '.join(missing)})")

        artifact_resolved = index.resolves_artifact(claim.artifact_path)
        if has_artifact and not artifact_resolved:
            issues.append(
                f"artifact '{claim.artifact_path}' not in run manifest "
                "(claim cites an artifact this run did not produce)"
            )

        artifact_hash_matches: bool | None = None
        if has_artifact and artifact_resolved:
            expected = _normalize_sha(claim.artifact_sha256)
            recorded = index.checksum_for(claim.artifact_path)
            if expected is not None and recorded is not None:
                artifact_hash_matches = expected == recorded
                if not artifact_hash_matches:
                    issues.append(
                        f"artifact checksum mismatch for '{claim.artifact_path}' "
                        f"(claimed {expected[:12]}…, ran {recorded[:12]}…)"
                    )

        code_resolved = index.resolves_code(claim.code_ref)
        if has_code and not code_resolved:
            issues.append(
                f"code_ref '{claim.code_ref}' not in run plan steps"
            )

        ok = (
            has_provenance
            and (not has_artifact or artifact_resolved)
            and (artifact_hash_matches is not False)
            and (not has_code or code_resolved)
            and not issues
        )
        verdicts.append(
            ClaimProvenanceVerdict(
                claim_id=claim.claim_id,
                ok=ok,
                has_provenance=has_provenance,
                artifact_resolved=artifact_resolved,
                artifact_hash_matches=artifact_hash_matches,
                code_resolved=code_resolved,
                issues=issues,
            )
        )
    return verdicts


def coerce_claims(raw: Any) -> list[ClaimProvenance]:
    """Best-effort coerce a list of dicts/objects into ClaimProvenance.

    Accepts dicts with the ClaimProvenance fields; assigns a positional
    ``claim_id`` when one is absent so violators can still be reported.
    """

    claims: list[ClaimProvenance] = []
    for i, item in enumerate(raw or []):
        if isinstance(item, ClaimProvenance):
            claims.append(item)
            continue
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data.setdefault("claim_id", str(data.get("id") or f"claim_{i}"))
        provenance = data.get("provenance")
        if isinstance(provenance, dict):
            for key in ("artifact_path", "artifact_sha256", "code_ref", "config_digest"):
                data.setdefault(key, provenance.get(key))
        allowed = {
            "claim_id",
            "statement",
            "artifact_path",
            "artifact_sha256",
            "code_ref",
            "config_digest",
        }
        claims.append(ClaimProvenance(**{k: v for k, v in data.items() if k in allowed}))
    return claims


_CLAIM_PROVENANCE_RULE_ID = "REVIEW_CLAIM_PROVENANCE_UNVERIFIED"


def build_claim_provenance_gate(
    claims: Any,
    index: RunProvenanceIndex,
    *,
    claim_mode: str = "confirmatory",
    require_claim_provenance: bool = False,
    require_full: bool = True,
) -> dict[str, Any] | None:
    """Report-time gate: validate claims and decide block vs. caveat (P2.2).

    Returns ``None`` when there are no claims. Otherwise a summary dict with
    ``checked``, ``unsupported_ids``, ``blocked``, ``claim_mode``, and — when
    there are unsupported claims — a ``section_text`` for the report, plus a
    synthetic blocking ``finding`` when ``blocked`` (so ``scientific_report_generate``
    can fold it into the existing review verdict and reuse the blocked-draft
    machinery). Unsupported claims block under ``require_claim_provenance`` or a
    ``confirmatory`` claim mode; exploratory runs only get the caveat section.
    """

    coerced = coerce_claims(claims)
    if not coerced:
        return None

    verdicts = validate_claim_provenance(coerced, index, require_full=require_full)
    unsupported = [v for v in verdicts if not v.ok]
    blocked = bool(unsupported) and (
        bool(require_claim_provenance) or str(claim_mode).lower() == "confirmatory"
    )

    summary: dict[str, Any] = {
        "checked": len(verdicts),
        "unsupported_ids": [v.claim_id for v in unsupported],
        "blocked": blocked,
        "claim_mode": claim_mode,
    }
    if not unsupported:
        return summary

    lines = [
        "The following report claims could not be traced to artifacts/code that "
        "actually ran in this analysis. Do not present them as results until each "
        "is bound to a produced artifact (path + sha256) and a code reference.",
        "",
    ]
    for verdict in unsupported[:20]:
        reasons = "; ".join(verdict.issues) or "no provenance attached"
        lines.append(f"- {verdict.claim_id}: {reasons}")
    if len(unsupported) > 20:
        lines.append(f"- Truncated: {len(unsupported) - 20} more unsupported claim(s).")
    summary["section_text"] = "\n".join(lines)

    if blocked:
        summary["finding"] = {
            "rule_id": _CLAIM_PROVENANCE_RULE_ID,
            "severity": "critical",
            "action": "block",
            "message": (
                f"{len(unsupported)} report claim(s) lack verifiable provenance: "
                "untraceable to artifacts/code that actually ran."
            ),
            "suggested_fix": (
                "Bind each claim to a produced artifact (artifact_path + "
                "artifact_sha256) and a code_ref present in this run, or remove "
                "the untraceable claim."
            ),
        }
    return summary


__all__ = [
    "ClaimProvenance",
    "ClaimProvenanceVerdict",
    "RunProvenanceIndex",
    "build_run_provenance_index",
    "validate_claim_provenance",
    "coerce_claims",
    "build_claim_provenance_gate",
]
