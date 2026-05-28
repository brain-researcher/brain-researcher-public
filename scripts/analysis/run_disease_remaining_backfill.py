#!/usr/bin/env python3
"""Comprehensive backfill for remaining disease concepts after Top-N execution.

Workflow:
1) Load baseline from a disease linkage gap audit JSON.
2) Select remaining concepts (ranked_gaps minus top_ranked_gaps).
3) Propose conservative acronym expansions from label/aliases.
4) Apply non-conflicting acronyms into alias map.
5) Execute text backfill + dataset mediated backfill in batches.
6) Enforce strict gate per batch and stop on failure.
7) Write JSON/Markdown audit artifacts under docs/audits.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

BANNED_ACRONYM_TOKENS = {
    "ACID",
    "AURA",
    "BAD",
    "COMA",
    "DEAF",
    "DISEASE",
    "DISORDER",
    "DISORDERS",
    "DOWN",
    "FEAR",
    "GAME",
    "HEART",
    "HEP",
    "HIGH",
    "HUMAN",
    "INSULIN",
    "KIDNEY",
    "LIVER",
    "LOSS",
    "MEDICAL",
    "MELLITUS",
    "MOOD",
    "PAIN",
    "PORN",
    "POST",
    "REFLUX",
    "SEPSIS",
    "SEX",
    "SLEEP",
    "TYPE",
    "USE",
    "VIRUS",
    "WITH",
}


@dataclass(frozen=True)
class ConceptBaseline:
    concept_id: str
    label: str
    rank: int
    gap_score: int
    list_datasets: int
    list_connected_score: int
    summary_datasets: int
    summary_papers: int
    summary_tasks: int
    summary_statmaps: int


def _find_repo_root(start: Path | None = None) -> Path:
    start_path = (start or Path.cwd()).resolve()
    for parent in [start_path, *start_path.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return start_path


def _read_dotenv_value(repo_root: Path, key: str) -> str | None:
    for filename in (".env.local", ".env"):
        path = repo_root / filename
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            env_key, env_value = line.split("=", 1)
            if env_key.strip() != key:
                continue
            value = env_value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value or None
    return None


def _env(repo_root: Path, key: str, default: str | None = None) -> str | None:
    import os

    return os.getenv(key) or _read_dotenv_value(repo_root, key) or default


def _normalize_acronym(token: str) -> str:
    raw = (token or "").strip().upper()
    if not raw:
        return ""
    if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", raw):
        return raw
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    return compact


def _normalize_alias(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _extract_inline_acronyms(text: str) -> set[str]:
    out: set[str] = set()
    for token in re.findall(r"\b[A-Za-z0-9][A-Za-z0-9/-]{1,11}\b", text or ""):
        raw = token.strip()
        if not raw:
            continue
        # Keep explicit acronym-like tokens only:
        # - all-uppercase alpha tokens (e.g., PTSD, COPD)
        # - short lowercase alpha tokens (e.g., adhd, bpd)
        # - uppercase/number/hyphen compounds (e.g., BD-I)
        if raw.isalpha():
            if raw.isupper():
                if len(raw) < 3 or len(raw) > 8:
                    continue
            elif raw.islower():
                if len(raw) < 3 or len(raw) > 4:
                    continue
            else:
                continue
        else:
            if re.search(r"[a-z]", raw):
                continue
            compact = re.sub(r"[^A-Za-z0-9]", "", raw)
            if len(compact) < 3 or len(compact) > 8:
                continue
        normalized = _normalize_acronym(raw)
        compact_norm = normalized.replace("-", "")
        if len(compact_norm) < 3 or len(compact_norm) > 8:
            continue
        out.add(normalized)
    return out


def _generate_acronym_candidates(label: str, aliases: list[str]) -> set[str]:
    candidates: set[str] = set()

    for source in aliases:
        source_text = str(source or "").strip()
        if not source_text:
            continue
        candidates.update(_extract_inline_acronyms(source_text))

    # Remove pathological tokens.
    cleaned: set[str] = set()
    for token in candidates:
        normalized = _normalize_acronym(token)
        if not normalized:
            continue
        if normalized in BANNED_ACRONYM_TOKENS:
            continue
        stripped = normalized.replace("-", "")
        if len(stripped) < 3 or len(stripped) > 8:
            continue
        if stripped.isdigit():
            continue
        cleaned.add(normalized)
    return cleaned


def _fetch_json(url: str, timeout_s: float) -> Any:
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "brain-researcher-disease-remaining-backfill/1.0",
        },
    )
    attempts = 4
    retry_sleep_s = 2.0
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            # Transient upstream failures are common during service restarts.
            if exc.code in {429, 500, 502, 503, 504} and attempt < attempts:
                time.sleep(retry_sleep_s)
                continue
            raise
        except (URLError, TimeoutError):
            if attempt < attempts:
                time.sleep(retry_sleep_s)
                continue
            raise


def _chunks(values: list[str], size: int) -> list[list[str]]:
    chunk_size = max(1, int(size))
    return [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]


def _run_json_command(
    args: list[str],
    cwd: Path,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"command timeout after {timeout_s}s: {' '.join(args)}"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDERR:\n{proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"command output is not valid JSON: {' '.join(args)}\nSTDOUT:\n{proc.stdout}"
        ) from exc


def parse_args() -> argparse.Namespace:
    repo_root = _find_repo_root(Path(__file__).resolve().parent)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-json",
        default="docs/audits/disease_linkage_gap_audit_20260223_211347Z.json",
        help="Baseline disease linkage gap audit JSON.",
    )
    parser.add_argument(
        "--alias-map",
        default="configs/legacy/mappings/disease_alias_overrides.yaml",
        help="Disease alias/acronym mapping YAML.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/audits",
        help="Output directory for run artifacts.",
    )
    parser.add_argument(
        "--base-url",
        default=_env(repo_root, "NEUROKG_API_URL") or "https://brain-researcher.com/kg",
        help="BR-KG base URL for lens endpoints.",
    )
    parser.add_argument("--neo4j-uri", default=_env(repo_root, "NEO4J_URI"))
    parser.add_argument("--neo4j-user", default=_env(repo_root, "NEO4J_USER"))
    parser.add_argument("--neo4j-password", default=_env(repo_root, "NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env(repo_root, "NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--sample-seed", type=int, default=17)
    parser.add_argument(
        "--min-dataset-win-ratio",
        type=float,
        default=0.2,
        help="Required min ratio of concepts with datasets 0->>0 in a batch.",
    )
    parser.add_argument(
        "--min-sample-pass-rate",
        type=float,
        default=0.8,
        help="Required pass rate for sampled post-check concepts.",
    )
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        help="Stop immediately when a batch fails any gate.",
    )
    parser.add_argument(
        "--apply-acronyms",
        action="store_true",
        help="Write accepted acronym expansions back to alias map.",
    )
    parser.add_argument(
        "--run-backfill",
        action="store_true",
        help="Execute text/dataset backfill scripts (otherwise prepare artifacts only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass dry-run to ETL backfill scripts.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="HTTP timeout for API checks.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=300.0,
        help="Timeout (seconds) for each ETL subprocess call.",
    )
    return parser.parse_args()


def _load_baseline(audit_path: Path) -> tuple[list[ConceptBaseline], list[str]]:
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    ranked = payload.get("ranked_gaps") or []
    top = payload.get("top_ranked_gaps") or []
    top_ids = {str(row.get("concept_id")) for row in top if row.get("concept_id")}

    rows: list[ConceptBaseline] = []
    for row in ranked:
        concept_id = str(row.get("concept_id") or "").strip()
        if not concept_id:
            continue
        if concept_id in top_ids:
            continue
        rows.append(
            ConceptBaseline(
                concept_id=concept_id,
                label=str(row.get("label") or concept_id),
                rank=int(row.get("rank") or 0),
                gap_score=int(row.get("gap_score") or 0),
                list_datasets=int(row.get("list_datasets") or 0),
                list_connected_score=int(row.get("list_connected_score") or 0),
                summary_datasets=int(row.get("summary_datasets") or 0),
                summary_papers=int(row.get("summary_papers") or 0),
                summary_tasks=int(row.get("summary_tasks") or 0),
                summary_statmaps=int(row.get("summary_statmaps") or 0),
            )
        )
    rows.sort(key=lambda item: item.rank if item.rank > 0 else math.inf)
    return rows, sorted(top_ids)


def _load_alias_map(alias_path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {"concept_aliases": {}}
    concept_aliases = payload.get("concept_aliases")
    if not isinstance(concept_aliases, dict):
        payload["concept_aliases"] = {}
    return payload


def _build_existing_owners(concept_aliases: dict[str, Any]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for concept_id, node in concept_aliases.items():
        if not isinstance(node, dict):
            continue
        acronyms = node.get("acronyms")
        for raw in acronyms if isinstance(acronyms, list) else []:
            token = _normalize_acronym(str(raw))
            if not token:
                continue
            owners.setdefault(token, set()).add(str(concept_id))
    return owners


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _get_entities_counts(base_url: str, timeout_s: float, limit: int = 2000) -> dict[str, dict[str, int]]:
    url = f"{base_url.rstrip('/')}/api/kg/lens/disease/entities?limit={int(limit)}"
    payload = _fetch_json(url, timeout_s=timeout_s)
    if not isinstance(payload, list):
        return {}
    out: dict[str, dict[str, int]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        concept_id = str(item.get("id") or "").strip()
        if not concept_id:
            continue
        counts = item.get("counts") if isinstance(item.get("counts"), dict) else {}
        out[concept_id] = {
            "datasets": int(counts.get("datasets") or 0),
            "connected_score": int(item.get("connected_score") or 0),
        }
    return out


def _get_summary_features(base_url: str, concept_id: str, timeout_s: float) -> dict[str, int]:
    url = f"{base_url.rstrip('/')}/api/kg/lens/disease/entity/{concept_id}/summary"
    try:
        payload = _fetch_json(url, timeout_s=timeout_s)
    except HTTPError as exc:
        if exc.code == 404:
            return {"datasets": 0, "papers": 0, "tasks": 0, "statmaps": 0}
        raise
    features = payload.get("features") if isinstance(payload, dict) else {}
    if not isinstance(features, dict):
        return {"datasets": 0, "papers": 0, "tasks": 0, "statmaps": 0}
    return {
        "datasets": int(features.get("datasets") or 0),
        "papers": int(features.get("papers") or 0),
        "tasks": int(features.get("tasks") or 0),
        "statmaps": int(features.get("statmaps") or 0),
    }


def main() -> int:
    args = parse_args()
    repo_root = _find_repo_root(Path(__file__).resolve().parent)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")

    audit_path = repo_root / args.audit_json
    alias_path = repo_root / args.alias_map
    out_dir = repo_root / args.out_dir

    if not audit_path.exists():
        raise FileNotFoundError(f"audit json not found: {audit_path}")
    if not alias_path.exists():
        raise FileNotFoundError(f"alias map not found: {alias_path}")

    remaining_rows, top_ids = _load_baseline(audit_path)
    remaining_ids = [row.concept_id for row in remaining_rows]
    remaining_map = {row.concept_id: row for row in remaining_rows}

    alias_payload = _load_alias_map(alias_path)
    concept_aliases = alias_payload.get("concept_aliases") or {}
    if not isinstance(concept_aliases, dict):
        concept_aliases = {}
        alias_payload["concept_aliases"] = concept_aliases

    existing_owners = _build_existing_owners(concept_aliases)
    acronym_proposed: list[dict[str, Any]] = []
    acronym_applied: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for concept_id in remaining_ids:
        base = remaining_map[concept_id]
        node = concept_aliases.get(concept_id)
        if not isinstance(node, dict):
            node = {"aliases": [base.label], "acronyms": []}
            concept_aliases[concept_id] = node

        aliases_raw = node.get("aliases")
        aliases = [
            _normalize_alias(str(value))
            for value in aliases_raw
            if isinstance(aliases_raw, list) and value is not None
        ]
        aliases = [value for value in aliases if value]
        existing_acronyms = {
            _normalize_acronym(str(value))
            for value in (node.get("acronyms") or [])
            if value is not None
        }
        existing_acronyms = {value for value in existing_acronyms if value}

        candidates = _generate_acronym_candidates(base.label, aliases)
        candidates = {value for value in candidates if value not in existing_acronyms}
        accepted: list[str] = []
        blocked: list[dict[str, Any]] = []
        for token in sorted(candidates):
            owners = existing_owners.get(token, set())
            if owners and owners != {concept_id}:
                blocked.append(
                    {
                        "token": token,
                        "owners": sorted(owners),
                        "reason": "conflict_existing_owner",
                    }
                )
                continue
            accepted.append(token)
            existing_owners.setdefault(token, set()).add(concept_id)

        acronym_proposed.append(
            {
                "concept_id": concept_id,
                "label": base.label,
                "existing_acronyms": sorted(existing_acronyms),
                "accepted_new_acronyms": accepted,
                "blocked": blocked,
            }
        )
        for item in blocked:
            conflicts.append({"concept_id": concept_id, "label": base.label, **item})

        if args.apply_acronyms and accepted:
            merged = sorted(existing_acronyms.union(accepted))
            node["acronyms"] = merged
            acronym_applied.append(
                {
                    "concept_id": concept_id,
                    "label": base.label,
                    "new_acronyms": accepted,
                    "total_acronyms": merged,
                }
            )

    if args.apply_acronyms:
        alias_path.write_text(
            yaml.safe_dump(alias_payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )

    manifest_path = out_dir / f"disease_remaining_93_manifest_{stamp}.json"
    proposed_path = out_dir / f"disease_acronym_proposed_{stamp}.json"
    applied_path = out_dir / f"disease_acronym_applied_{stamp}.json"
    conflict_md_path = out_dir / f"disease_acronym_conflicts_{stamp}.md"
    run_report_path = out_dir / f"disease_remaining_backfill_run_{stamp}.json"
    run_md_path = out_dir / f"disease_remaining_backfill_run_{stamp}.md"

    _write_json(
        manifest_path,
        {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_audit": str(audit_path),
            "excluded_top_ids": top_ids,
            "remaining_count": len(remaining_rows),
            "remaining": [row.__dict__ for row in remaining_rows],
        },
    )
    _write_json(
        proposed_path,
        {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "remaining_count": len(remaining_rows),
            "rows": acronym_proposed,
            "counts": {
                "concepts_with_new_acronyms": sum(
                    1 for row in acronym_proposed if row["accepted_new_acronyms"]
                ),
                "new_acronyms_total": sum(
                    len(row["accepted_new_acronyms"]) for row in acronym_proposed
                ),
                "conflicts_total": len(conflicts),
            },
        },
    )
    _write_json(
        applied_path,
        {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "apply_acronyms": bool(args.apply_acronyms),
            "applied_rows": acronym_applied,
            "counts": {
                "concepts_updated": len(acronym_applied),
                "new_acronyms_applied": sum(len(row["new_acronyms"]) for row in acronym_applied),
            },
        },
    )

    conflict_lines = [
        "# Disease Acronym Conflict Report",
        "",
        f"- Generated (UTC): `{dt.datetime.now(dt.timezone.utc).isoformat()}`",
        f"- Conflict count: `{len(conflicts)}`",
        "",
        "| concept_id | label | token | owners | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    if conflicts:
        for row in conflicts:
            conflict_lines.append(
                f"| {row['concept_id']} | {row['label']} | {row['token']} | "
                f"{','.join(row['owners'])} | {row['reason']} |"
            )
    else:
        conflict_lines.append("| (none) |  |  |  |  |")
    _write_markdown(conflict_md_path, conflict_lines)

    run_report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_backfill": bool(args.run_backfill),
        "dry_run": bool(args.dry_run),
        "strict_gate": bool(args.strict_gate),
        "inputs": {
            "base_url": args.base_url.rstrip("/"),
            "batch_size": int(args.batch_size),
            "sample_size": int(args.sample_size),
            "min_dataset_win_ratio": float(args.min_dataset_win_ratio),
            "min_sample_pass_rate": float(args.min_sample_pass_rate),
        },
        "remaining_count": len(remaining_ids),
        "artifacts": {
            "manifest": str(manifest_path),
            "acronym_proposed": str(proposed_path),
            "acronym_applied": str(applied_path),
            "acronym_conflicts": str(conflict_md_path),
        },
        "batches": [],
        "stopped": False,
        "stop_reason": "",
    }

    if args.run_backfill:
        missing = [
            key
            for key, value in {
                "neo4j_uri": args.neo4j_uri,
                "neo4j_user": args.neo4j_user,
                "neo4j_password": args.neo4j_password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"missing required neo4j args: {', '.join(missing)}")

        rng = random.Random(args.sample_seed)

        for batch_index, concept_batch in enumerate(_chunks(remaining_ids, args.batch_size), start=1):
            text_results: list[dict[str, Any]] = []
            text_created_total = 0
            text_matched_total = 0

            for concept_id in concept_batch:
                node = concept_aliases.get(concept_id) if isinstance(concept_aliases, dict) else {}
                acronyms = node.get("acronyms") if isinstance(node, dict) else []
                use_high_conf = isinstance(acronyms, list) and len(acronyms) > 0
                confidence = "0.5" if use_high_conf else "0.35"
                cmd = [
                    sys.executable,
                    "scripts/tools/etl/backfill_onvoc_text_links.py",
                    "--neo4j-uri",
                    str(args.neo4j_uri),
                    "--neo4j-user",
                    str(args.neo4j_user),
                    "--neo4j-password",
                    str(args.neo4j_password),
                    "--neo4j-database",
                    str(args.neo4j_database),
                    "--concept-id",
                    concept_id,
                    "--alias-map",
                    str(alias_path),
                    "--confidence",
                    confidence,
                ]
                if args.dry_run:
                    cmd.append("--dry-run")
                result = _run_json_command(
                    cmd,
                    cwd=repo_root,
                    timeout_s=float(args.command_timeout),
                )
                total = result.get("totals") if isinstance(result, dict) else {}
                text_created_total += int((total or {}).get("created") or 0)
                text_matched_total += int((total or {}).get("matched") or 0)
                text_results.append(
                    {
                        "concept_id": concept_id,
                        "confidence": float(confidence),
                        "created": int((total or {}).get("created") or 0),
                        "matched": int((total or {}).get("matched") or 0),
                    }
                )

            dataset_totals = {"created": 0, "updated": 0, "matched": 0}
            dataset_errors: list[dict[str, Any]] = []
            for concept_id in concept_batch:
                dataset_cmd = [
                    sys.executable,
                    "scripts/tools/etl/backfill_disease_dataset_links.py",
                    "--neo4j-uri",
                    str(args.neo4j_uri),
                    "--neo4j-user",
                    str(args.neo4j_user),
                    "--neo4j-password",
                    str(args.neo4j_password),
                    "--neo4j-database",
                    str(args.neo4j_database),
                    "--concept-id",
                    concept_id,
                ]
                if args.dry_run:
                    dataset_cmd.append("--dry-run")
                try:
                    dataset_report = _run_json_command(
                        dataset_cmd,
                        cwd=repo_root,
                        timeout_s=float(args.command_timeout),
                    )
                    totals = (
                        dataset_report.get("totals")
                        if isinstance(dataset_report, dict)
                        else {}
                    )
                    dataset_totals["created"] += int((totals or {}).get("created") or 0)
                    dataset_totals["updated"] += int((totals or {}).get("updated") or 0)
                    dataset_totals["matched"] += int((totals or {}).get("matched") or 0)
                except Exception as exc:  # pragma: no cover - operational safeguard
                    dataset_errors.append(
                        {
                            "concept_id": concept_id,
                            "error": str(exc),
                        }
                    )

            before_features_map: dict[str, dict[str, int]] = {}
            for concept_id in concept_batch:
                before_features_map[concept_id] = _get_summary_features(
                    args.base_url,
                    concept_id,
                    timeout_s=args.timeout,
                )
            after_features_map: dict[str, dict[str, int]] = {}
            for concept_id in concept_batch:
                after_features_map[concept_id] = _get_summary_features(
                    args.base_url,
                    concept_id,
                    timeout_s=args.timeout,
                )

            # Batch-start delta: useful for this invocation's immediate effect.
            dataset_wins_batch_start = 0
            # Baseline delta: relative to the original audit snapshot.
            dataset_wins_baseline = 0
            for concept_id in concept_batch:
                before_ds = int(
                    (before_features_map.get(concept_id) or {}).get("datasets") or 0
                )
                after_ds = int(
                    (after_features_map.get(concept_id) or {}).get("datasets") or 0
                )
                base = remaining_map[concept_id]
                baseline_ds = max(int(base.list_datasets), int(base.summary_datasets))
                if before_ds == 0 and after_ds > 0:
                    dataset_wins_batch_start += 1
                if after_ds > baseline_ds:
                    dataset_wins_baseline += 1
            win_ratio_batch_start = dataset_wins_batch_start / max(1, len(concept_batch))
            win_ratio_baseline = dataset_wins_baseline / max(1, len(concept_batch))

            sample_candidates = sorted(
                text_results,
                key=lambda row: (-row["created"], -row["matched"], row["concept_id"]),
            )
            sample_ids = [row["concept_id"] for row in sample_candidates[: args.sample_size]]
            if len(sample_ids) < args.sample_size:
                remaining_pool = [cid for cid in concept_batch if cid not in sample_ids]
                rng.shuffle(remaining_pool)
                sample_ids.extend(remaining_pool[: args.sample_size - len(sample_ids)])

            sample_checks: list[dict[str, Any]] = []
            sample_pass = 0
            for concept_id in sample_ids:
                feat = after_features_map.get(concept_id) or _get_summary_features(
                    args.base_url,
                    concept_id,
                    timeout_s=args.timeout,
                )
                base = remaining_map[concept_id]
                passed = (
                    feat["datasets"] > base.summary_datasets
                    or feat["papers"] > 0
                    or feat["tasks"] > 0
                    or feat["statmaps"] > 0
                )
                if passed:
                    sample_pass += 1
                sample_checks.append(
                    {
                        "concept_id": concept_id,
                        "baseline_summary_datasets": base.summary_datasets,
                        "summary_datasets": feat["datasets"],
                        "summary_papers": feat["papers"],
                        "summary_tasks": feat["tasks"],
                        "summary_statmaps": feat["statmaps"],
                        "pass": bool(passed),
                    }
                )
            sample_rate = sample_pass / max(1, len(sample_checks))

            gate_failures: list[str] = []
            if win_ratio_baseline < float(args.min_dataset_win_ratio):
                gate_failures.append(
                    "dataset_win_ratio_baseline="
                    f"{win_ratio_baseline:.3f} < {float(args.min_dataset_win_ratio):.3f}"
                )
            if sample_rate < float(args.min_sample_pass_rate):
                gate_failures.append(
                    f"sample_pass_rate={sample_rate:.3f} < {float(args.min_sample_pass_rate):.3f}"
                )
            if dataset_errors:
                gate_failures.append(f"dataset_errors={len(dataset_errors)}")
            batch_report = {
                "batch_index": batch_index,
                "concept_ids": concept_batch,
                "text_totals": {
                    "created": text_created_total,
                    "matched": text_matched_total,
                },
                "dataset_totals": {
                    "created": int((dataset_totals or {}).get("created") or 0),
                    "updated": int((dataset_totals or {}).get("updated") or 0),
                    "matched": int((dataset_totals or {}).get("matched") or 0),
                },
                "dataset_win_count": dataset_wins_baseline,
                "dataset_win_ratio": win_ratio_baseline,
                "dataset_win_count_baseline": dataset_wins_baseline,
                "dataset_win_ratio_baseline": win_ratio_baseline,
                "dataset_win_count_batch_start": dataset_wins_batch_start,
                "dataset_win_ratio_batch_start": win_ratio_batch_start,
                "sample_checks": sample_checks,
                "sample_pass_rate": sample_rate,
                "dataset_errors": dataset_errors,
                "gate_failures": gate_failures,
                "gate_pass": len(gate_failures) == 0,
            }
            run_report["batches"].append(batch_report)

            if args.strict_gate and gate_failures:
                run_report["stopped"] = True
                run_report["stop_reason"] = (
                    f"batch {batch_index} gate failed: {'; '.join(gate_failures)}"
                )
                break

    _write_json(run_report_path, run_report)

    lines = [
        "# Disease Remaining Backfill Run",
        "",
        f"- Generated (UTC): `{run_report['generated_at']}`",
        f"- Remaining concepts: `{run_report['remaining_count']}`",
        f"- run_backfill: `{run_report['run_backfill']}`",
        f"- dry_run: `{run_report['dry_run']}`",
        f"- strict_gate: `{run_report['strict_gate']}`",
        f"- Stopped: `{run_report['stopped']}`",
        f"- Stop reason: `{run_report['stop_reason'] or '(none)'}`",
        "",
        "## Batch Summary",
        "",
        "| batch | concepts | text_created | dataset_created | dataset_updated | win_ratio_baseline | win_ratio_batch_start | sample_pass_rate | gate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for batch in run_report["batches"]:
        lines.append(
            f"| {batch['batch_index']} | {len(batch['concept_ids'])} | "
            f"{batch['text_totals']['created']} | {batch['dataset_totals']['created']} | "
            f"{batch['dataset_totals']['updated']} | {batch['dataset_win_ratio_baseline']:.3f} | "
            f"{batch['dataset_win_ratio_batch_start']:.3f} | "
            f"{batch['sample_pass_rate']:.3f} | "
            f"{'PASS' if batch['gate_pass'] else 'FAIL'} |"
        )
    _write_markdown(run_md_path, lines)

    print(
        json.dumps(
            {
                "status": "ok",
                "remaining_count": len(remaining_ids),
                "artifacts": {
                    "manifest": str(manifest_path),
                    "acronym_proposed": str(proposed_path),
                    "acronym_applied": str(applied_path),
                    "acronym_conflicts": str(conflict_md_path),
                    "run_report_json": str(run_report_path),
                    "run_report_md": str(run_md_path),
                },
                "run_backfill": bool(args.run_backfill),
                "stopped": bool(run_report.get("stopped")),
                "stop_reason": str(run_report.get("stop_reason") or ""),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
