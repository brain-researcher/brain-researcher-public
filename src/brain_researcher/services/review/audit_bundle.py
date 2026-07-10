"""Persist canonical audit bundles for review and Society runs."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import is_audit_persist_enabled

GENERATOR = "brain_researcher/audit_bundle v1"
AUDIT_DIR_NAME = "audit"
SOCIETY_DIR_NAME = "society"
_EVIDENCE_VERDICT_PATTERNS = (
    "evidence_verdicts.json",
    "claim_verdicts.json",
    "*claim*verdict*.json",
    "*evidence*verdict*.json",
    "**/evidence_verdicts.json",
    "**/claim_verdicts.json",
    "**/*claim*verdict*.json",
    "**/*evidence*verdict*.json",
)
RUN_BUNDLE_SOURCE_FILENAMES = (
    "trace.jsonl",
    "provenance.json",
    "trajectory.json",
    "observation.json",
    "analysis_bundle.json",
)


@dataclass(frozen=True)
class AuditSources:
    """Discovered audit-source files under a run directory."""

    run_dir: Path
    commitment: Path | None = None
    claim_card: Path | None = None
    refusal: Path | None = None
    evidence: tuple[Path, ...] = ()
    run_bundle: tuple[Path, ...] = ()

    def has_records(self) -> bool:
        return any(
            (
                self.commitment is not None,
                self.claim_card is not None,
                self.refusal is not None,
                bool(self.evidence),
                bool(self.run_bundle),
            )
        )

    def relative_source_paths(self) -> tuple[str, ...]:
        paths: list[str] = []
        for path in (self.commitment, self.claim_card, self.refusal):
            if path is not None:
                paths.append(_relative_to_run(self.run_dir, path))
        paths.extend(_relative_to_run(self.run_dir, path) for path in self.evidence)
        paths.extend(_relative_to_run(self.run_dir, path) for path in self.run_bundle)
        return tuple(paths)

    def source_paths_manifest(self) -> dict[str, Any]:
        source_paths: dict[str, Any] = {}
        if self.commitment is not None:
            source_paths["commitment"] = _relative_to_run(self.run_dir, self.commitment)
        if self.claim_card is not None:
            source_paths["claim_card"] = _relative_to_run(self.run_dir, self.claim_card)
        if self.refusal is not None:
            source_paths["refusal"] = _relative_to_run(self.run_dir, self.refusal)
        if self.evidence:
            source_paths["evidence"] = [
                _relative_to_run(self.run_dir, path) for path in self.evidence
            ]
        if self.run_bundle:
            source_paths["run_bundle"] = [
                _relative_to_run(self.run_dir, path) for path in self.run_bundle
            ]
        return source_paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _is_under_audit_dir(run_dir: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(run_dir)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] == AUDIT_DIR_NAME


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _append_unique(paths: list[Path], path: Path) -> None:
    try:
        key = str(path.resolve())
    except Exception:
        key = str(path)
    existing = set()
    for existing_path in paths:
        try:
            existing.add(str(existing_path.resolve()))
        except Exception:
            existing.add(str(existing_path))
    if key not in existing:
        paths.append(path)


def _discover_evidence_sources(run_dir: Path) -> tuple[Path, ...]:
    evidence: list[Path] = []
    evidence_gate = run_dir / "evidence_gate.json"
    if evidence_gate.is_file():
        evidence.append(evidence_gate)

    # Post-execution scientific-review verdict — an EXACT-name source (its name
    # carries no "verdict"/"evidence" token, so the globs below never match it).
    scientific_review = run_dir / "scientific_review.json"
    if scientific_review.is_file():
        _append_unique(evidence, scientific_review)

    for pattern in _EVIDENCE_VERDICT_PATTERNS:
        for path in sorted(run_dir.glob(pattern)):
            if not path.is_file() or _is_under_audit_dir(run_dir, path):
                continue
            _append_unique(evidence, path)
    return tuple(evidence)


def _discover_run_bundle_sources(run_dir: Path) -> tuple[Path, ...]:
    sources: list[Path] = []
    for filename in RUN_BUNDLE_SOURCE_FILENAMES:
        path = run_dir / filename
        if path.is_file():
            sources.append(path)
    return tuple(sources)


def collect_audit_sources(run_dir: Path) -> AuditSources:
    """Discover audit source files under ``run_dir`` without writing anything."""

    run_dir = Path(run_dir)
    society_dir = run_dir / SOCIETY_DIR_NAME
    return AuditSources(
        run_dir=run_dir,
        commitment=_first_existing(
            (
                society_dir / "commitment_card.json",
                run_dir / "commitment.json",
                # B2: LIGHT pre-execution plan commitment (unsealed, hash=null).
                # Lowest priority: a sealed society card or a richer
                # CommitmentRecordV1 supersedes it.
                run_dir / "plan_commitment.json",
            )
        ),
        claim_card=_first_existing(
            (
                society_dir / "claim_card.json",
                run_dir / "claim_report.json",
            )
        ),
        refusal=_first_existing((society_dir / "refusal.json",)),
        evidence=_discover_evidence_sources(run_dir),
        run_bundle=_discover_run_bundle_sources(run_dir),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(source: Path, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "path": target.name,
        "sha256": _sha256_file(target),
        "bytes": target.stat().st_size,
    }


def _copy_evidence_file(
    run_dir: Path,
    source: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    try:
        rel = source.relative_to(run_dir)
    except ValueError:
        rel = Path(source.name)
    if rel.parts and rel.parts[0] == AUDIT_DIR_NAME:
        rel = Path(source.name)
    target = evidence_dir / rel
    _copy_file(source, target)
    return _file_record(evidence_dir.parent, target)


def _file_record(audit_dir: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(audit_dir).as_posix(),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _commitment_hash_from_society_card(sources: AuditSources) -> str | None:
    source = sources.commitment
    if source is None:
        return None
    if _relative_to_run(sources.run_dir, source) != "society/commitment_card.json":
        return None
    payload = _read_json(source)
    value = payload.get("commitment_hash") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip():
        return value
    return None


def _commitment_card_ref_from_sources(sources: AuditSources) -> str | None:
    if sources.commitment is None:
        return None
    payload = _read_json(sources.commitment)
    if not isinstance(payload, dict):
        return None
    for key in ("commitment_card_ref", "commitment_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _status_and_notes(sources: AuditSources) -> tuple[str, str]:
    if not sources.has_records():
        return (
            "no_audit_records",
            "No commitment, claim, refusal, or evidence audit records were found.",
        )

    missing: list[str] = []
    if sources.commitment is None:
        missing.append("commitment")
    if sources.claim_card is None and sources.refusal is None:
        missing.append("claim_card_or_refusal")
    if missing:
        return "partial", "Missing audit source(s): " + ", ".join(missing) + "."
    return "complete", "All canonical audit records found."


def persist_audit_bundle(run_dir: Path, *, provenance: str = "live") -> Path | None:
    """Persist a canonical ``audit/`` bundle for ``run_dir``.

    Returns the audit directory path, or ``None`` when ``BR_AUDIT_PERSIST`` disables
    persistence. Missing source cards are represented in the manifest rather than
    filled with placeholders.
    """

    if not is_audit_persist_enabled():
        return None

    run_dir = Path(run_dir)
    audit_dir = run_dir / AUDIT_DIR_NAME
    sources = collect_audit_sources(run_dir)
    if audit_dir.exists():
        if audit_dir.is_dir():
            shutil.rmtree(audit_dir)
        else:
            audit_dir.unlink()
    audit_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = audit_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []
    if sources.commitment is not None:
        target = audit_dir / "commitment.json"
        _copy_file(sources.commitment, target)
        files.append(_file_record(audit_dir, target))
    if sources.claim_card is not None:
        target = audit_dir / "claim_card.json"
        _copy_file(sources.claim_card, target)
        files.append(_file_record(audit_dir, target))
    if sources.refusal is not None:
        target = audit_dir / "refusal.json"
        _copy_file(sources.refusal, target)
        files.append(_file_record(audit_dir, target))
    if sources.evidence:
        for source in sources.evidence:
            files.append(_copy_evidence_file(run_dir, source, evidence_dir))
    if sources.run_bundle:
        for source in sources.run_bundle:
            target = audit_dir / source.name
            _copy_file(source, target)
            files.append(_file_record(audit_dir, target))

    status, notes = _status_and_notes(sources)
    manifest = {
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "generator": GENERATOR,
        "provenance": provenance,
        "status": status,
        "source_paths": sources.source_paths_manifest(),
        "files": files,
        "commitment_hash": _commitment_hash_from_society_card(sources),
        "commitment_card_ref": _commitment_card_ref_from_sources(sources),
        "notes": notes,
    }
    _json_write(audit_dir / "manifest.json", manifest)
    return audit_dir


def _find_post_hoc_evidence(run_dir: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    patterns = (
        "REPORT*.md",
        "REPORT*.json",
        "report*.md",
        "report*.json",
        "h*_output*.json",
        "h*_output*.md",
        "H*_output*.json",
        "H*_output*.md",
        "analysis_bundle.json",
        "source_summary.json",
        "provenance.json",
        "trace.jsonl",
        "trajectory.json",
        "observation.json",
    )
    for pattern in patterns:
        for path in sorted(run_dir.glob(pattern)):
            if path.is_file() and not _is_under_audit_dir(run_dir, path):
                _append_unique(candidates, path)
    return tuple(candidates)


def rebuild_post_hoc(run_dir: Path) -> Path:
    """Rebuild an audit bundle from existing run evidence and label it post-hoc.

    This entrypoint never creates a sealed pre-analysis commitment record. If a
    real Society commitment card exists, ``persist_audit_bundle`` will copy it
    and pass through its hash; otherwise the post-hoc manifest keeps the
    commitment fields empty and records the limitation explicitly.
    """

    if not is_audit_persist_enabled():
        return None  # type: ignore[return-value]

    run_dir = Path(run_dir)
    audit_dir = persist_audit_bundle(run_dir, provenance="post_hoc")
    if audit_dir is None:
        return None  # type: ignore[return-value]

    manifest_path = audit_dir / "manifest.json"
    manifest = _read_json(manifest_path) or {}
    sources = collect_audit_sources(run_dir)
    copied_existing = {
        entry.get("path")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict)
    }

    evidence_dir = audit_dir / "evidence"
    files = [entry for entry in manifest.get("files", []) if isinstance(entry, dict)]
    run_bundle_sources = list(sources.run_bundle)
    evidence_sources = list(sources.evidence)
    for source in _find_post_hoc_evidence(run_dir):
        if source not in evidence_sources and source not in run_bundle_sources:
            evidence_sources.append(source)
    for source in evidence_sources:
        record = _copy_evidence_file(run_dir, source, evidence_dir)
        if record["path"] not in copied_existing:
            files.append(record)
            copied_existing.add(record["path"])

    generated_at = _utc_now()
    source_evidence_files = evidence_sources + run_bundle_sources
    source_evidence = [
        _relative_to_run(run_dir, path) for path in source_evidence_files
    ]
    evidence_verdicts_path = audit_dir / "evidence_verdicts.json"
    if not evidence_verdicts_path.exists():
        evidence_verdicts = {
            "schema_version": "evidence-verdicts-v1",
            "generated_at": generated_at,
            "generation_mode": "post_hoc_from_existing_artifacts",
            "claim_id": f"{run_dir.name}-posthoc",
            "overall_verdict": {
                "status": "post_hoc_reconstructed_with_limitations",
                "summary": (
                    "Post-hoc audit evidence reconstructed from existing run artifacts; "
                    "not a pre-run commitment record."
                ),
            },
            "evidence_items": [
                {
                    "evidence_id": f"source-{index + 1}",
                    "type": "run_artifact",
                    "path": relpath,
                    "sha256": _sha256_file(path),
                    "status": "available_for_post_hoc_review",
                }
                for index, (relpath, path) in enumerate(
                    zip(source_evidence, source_evidence_files, strict=False)
                )
            ],
            "audit_limitations": [
                "This packet was generated after the run from existing artifacts.",
                "No sealed pre-analysis commitment hash is created by this rebuild path.",
            ],
        }
        _json_write(evidence_verdicts_path, evidence_verdicts)
        files.append(_file_record(audit_dir, evidence_verdicts_path))

    if sources.claim_card is None and sources.refusal is None:
        commitment_hash = _commitment_hash_from_society_card(sources)
        commitment_ref = _commitment_card_ref_from_sources(sources)
        claim_card = {
            "schema_version": "claim-card-v1",
            "claim_id": f"{run_dir.name}-posthoc",
            "claim_text": (
                "Post-hoc audit record reconstructed from existing run artifacts; "
                "not a pre-registered or pre-run biomarker claim."
            ),
            "status": "post_hoc_reconstructed_with_limitations",
            "status_not_ground_truth": True,
            "provenance": "post_hoc",
            "commitment_card_ref": commitment_ref,
            "commitment_hash": commitment_hash,
            "commitment_status": {
                "pre_run_commitment_card_found": sources.commitment is not None,
                "pre_run_commitment_hash_found": commitment_hash is not None,
                "not_backfilled": True,
                "explanation": (
                    "This claim card was generated post-hoc from existing run artifacts. "
                    "Any commitment reference or hash is only copied from a real source "
                    "file already present in the run directory."
                ),
            },
            "evidence_bundle_refs": ["evidence_verdicts.json"],
            "generated_at": generated_at,
            "generation_mode": "post_hoc_from_existing_artifacts",
            "scope_boundary": {
                "artifact_scope": "Existing artifacts found under the run directory.",
            },
            "survived_checks": [],
            "failed_checks": (
                []
                if commitment_hash is not None
                else ["No sealed pre-run commitment hash was found."]
            ),
            "next_required_evidence": [
                "Recover the original run-store commitment card if it exists; do not synthesize one after the fact.",
            ],
            "pipeline_summary": {
                "source_evidence": source_evidence,
            },
            "not_backfilled": True,
            "extra": {
                "integrity_boundary": {
                    "may_say": [
                        "Post-hoc claim card generated from existing run artifacts.",
                    ],
                    "must_not_say": [
                        "A pre-analysis commitment card was generated by this rebuild.",
                        "A commitment hash was sealed before this run by this rebuild.",
                    ],
                }
            },
        }
        claim_path = audit_dir / "claim_card.json"
        _json_write(claim_path, claim_card)
        files = [entry for entry in files if entry.get("path") != "claim_card.json"]
        files.append(_file_record(audit_dir, claim_path))

    source_paths = sources.source_paths_manifest()
    if source_evidence_files:
        source_paths["post_hoc_evidence"] = [
            _relative_to_run(run_dir, path) for path in source_evidence_files
        ]

    manifest.update(
        {
            "provenance": "post_hoc",
            "status": "partial" if files else "no_audit_records",
            "source_paths": source_paths,
            "files": files,
            "commitment_hash": _commitment_hash_from_society_card(sources),
            "commitment_card_ref": _commitment_card_ref_from_sources(sources),
            "not_backfilled": True,
            "notes": (
                "Post-hoc audit bundle reconstructed from existing run evidence; "
                "not a sealed pre-analysis commitment card."
            ),
        }
    )
    if sources.commitment is None:
        manifest["commitment_hash"] = None
        manifest["commitment_card_ref"] = None
    _json_write(manifest_path, manifest)
    return audit_dir


def _copy_tree(source_dir: Path, dest_dir: Path) -> list[dict[str, Any]]:
    if dest_dir.exists():
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir)
        else:
            dest_dir.unlink()
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for source in sorted(source_dir.rglob("*")):
        if source.is_dir():
            continue
        rel = source.relative_to(source_dir)
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(_file_record(dest_dir, target))
    return copied


def _is_within(child: Path, root: Path) -> bool:
    """True iff resolved ``child`` is ``root`` itself or nested under it.

    Both arguments MUST already be ``resolve()``d by the caller: resolving
    normalises away ``..`` segments and dereferences symlinks, so a dest that
    tries to escape via traversal (``../../etc``) or a symlinked directory ends
    up compared as its real location and fails containment.
    """
    try:
        return child.is_relative_to(root)
    except AttributeError:  # pragma: no cover - Python < 3.9 fallback
        import os

        try:
            return os.path.commonpath([str(child), str(root)]) == str(root)
        except ValueError:  # different drives / anchors
            return False


def _render_export_readme(
    *,
    run_id: str,
    manifest: dict[str, Any],
    subdir: str,
) -> str:
    provenance = manifest.get("provenance")
    created = manifest.get("created_utc")
    status = manifest.get("status")
    return (
        f"# Audit bundle for `{run_id}`\n\n"
        f"- `run_id`: `{run_id}`\n"
        f"- `provenance`: `{provenance}`\n"
        f"- `status`: `{status}`\n"
        f"- `generated_utc`: `{created}`\n"
        f"- `repository_subdir`: `{subdir}`\n\n"
        "This directory is a copied Brain Researcher audit bundle. "
        "Use `manifest.json` for source paths and file checksums. "
        "To cross-check the original run through MCP, call "
        f'`run_bundle_get(run_id="{run_id}", verbose=true)` and compare the '
        "recorded source paths and sha256 values.\n"
    )


def export_audit_bundle(
    *,
    run_id: str,
    run_dir: Path,
    dest_repo_path: Path,
    subdir: str = "results/{run_id}/audit",
    allow_post_hoc: bool = False,
    allowed_root: Path | None = None,
) -> dict[str, Any]:
    """Copy ``run_dir/audit`` into a publishable repository subdirectory.

    ``allowed_root`` constrains the *final* destination directory to a vetted
    export root. When it is set, the resolved ``dest_repo_path/<subdir>`` must
    lie within the resolved ``allowed_root`` or the export is rejected — both the
    subdir template and ``dest_repo_path`` are caller-supplied, so the check is
    applied to their combined, ``resolve()``d target to defeat ``..`` traversal
    (in either) and symlink escapes. Untrusted callers (the MCP
    ``run_export_audit`` tool) pass a root; trusted local callers (the
    ``br runs export-audit`` CLI) pass ``None`` and stay unconstrained.
    """

    run_dir = Path(run_dir)

    # Enforce path containment first, before any filesystem side effects (the
    # source audit bundle may be persisted below). Fail closed on a dest that
    # resolves outside the vetted export root.
    rendered_subdir = subdir.format(run_id=run_id)
    dest_dir = Path(dest_repo_path).expanduser() / rendered_subdir
    if allowed_root is not None:
        try:
            resolved_root = Path(allowed_root).expanduser().resolve()
            resolved_dest = dest_dir.resolve()
        except (OSError, RuntimeError) as exc:
            return {
                "ok": False,
                "error": f"could not resolve export destination: {exc}",
                "run_id": run_id,
                "run_dir": str(run_dir),
            }
        if not _is_within(resolved_dest, resolved_root):
            return {
                "ok": False,
                "error": (
                    "dest_repo_path resolves outside the allowed export root: "
                    f"{resolved_dest} is not within {resolved_root}"
                ),
                "run_id": run_id,
                "run_dir": str(run_dir),
                "dest_dir": str(resolved_dest),
                "allowed_root": str(resolved_root),
            }
        # Write to the vetted, resolved location.
        dest_dir = resolved_dest

    audit_dir = run_dir / AUDIT_DIR_NAME
    if not audit_dir.exists():
        audit_dir = persist_audit_bundle(run_dir, provenance="live") or audit_dir
    manifest_path = audit_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return {
            "ok": False,
            "error": f"audit manifest not found or invalid: {manifest_path}",
        }
    provenance = manifest.get("provenance")
    if provenance == "post_hoc" and not allow_post_hoc:
        return {
            "ok": False,
            "error": (
                "audit bundle provenance is post_hoc; pass allow_post_hoc=True "
                "to export it explicitly"
            ),
            "run_id": run_id,
            "run_dir": str(run_dir),
            "audit_dir": str(audit_dir),
            "provenance": provenance,
        }

    files = _copy_tree(audit_dir, dest_dir)
    readme_path = dest_dir / "README.md"
    readme_path.write_text(
        _render_export_readme(run_id=run_id, manifest=manifest, subdir=rendered_subdir),
        encoding="utf-8",
    )
    files.append(_file_record(dest_dir, readme_path))

    return {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "audit_dir": str(audit_dir),
        "dest_dir": str(dest_dir),
        "subdir": rendered_subdir,
        "provenance": provenance,
        "files": files,
        "sha256": {entry["path"]: entry["sha256"] for entry in files},
    }


__all__ = [
    "AUDIT_DIR_NAME",
    "AuditSources",
    "GENERATOR",
    "collect_audit_sources",
    "export_audit_bundle",
    "persist_audit_bundle",
    "rebuild_post_hoc",
    "RUN_BUNDLE_SOURCE_FILENAMES",
]
