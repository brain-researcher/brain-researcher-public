"""Side-effect-safe scoring helpers for bounded autoresearch."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


@dataclass(frozen=True)
class ScoreResult:
    scorer_name: str
    score: float
    payload: dict[str, Any]
    input_paths: tuple[str, ...]
    scored_at_utc: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer_name": self.scorer_name,
            "score": self.score,
            "payload": self.payload,
            "input_paths": list(self.input_paths),
            "scored_at_utc": self.scored_at_utc,
        }


class ScoreMutationError(RuntimeError):
    """Raised when a guarded scorer mutates tracked artifacts."""


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tracked_tree(
    roots: Iterable[Path],
    *,
    tracked_suffixes: Sequence[str] = (".json", ".jsonl", ".md", ".txt"),
) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for root in roots:
        resolved_root = root.expanduser().resolve()
        if not resolved_root.exists():
            continue
        for path in resolved_root.rglob("*"):
            if not path.is_file():
                continue
            if tracked_suffixes and path.suffix not in tracked_suffixes:
                continue
            snapshot[str(path)] = {
                "size": path.stat().st_size,
                "sha256": _hash_file(path),
            }
    return snapshot


def parse_json_stdout(stdout: str) -> dict[str, Any]:
    payload = json.loads((stdout or "").strip())
    if not isinstance(payload, dict):
        raise ValueError("scorer output must be a JSON object")
    return payload


def run_guarded_scorer_command(
    command: Sequence[str],
    *,
    cwd: Path | str | None = None,
    mutation_roots: Sequence[Path | str] = (),
    allowed_mutations: Sequence[Path | str] = (),
) -> dict[str, Any]:
    resolved_roots = [Path(root).expanduser().resolve() for root in mutation_roots]
    allowed = {str(Path(path).expanduser().resolve()) for path in allowed_mutations}
    before = snapshot_tracked_tree(resolved_roots)
    completed = subprocess.run(
        list(command),
        cwd=None if cwd is None else str(Path(cwd).expanduser().resolve()),
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"scorer exited with code {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    payload = parse_json_stdout(completed.stdout)
    after = snapshot_tracked_tree(resolved_roots)
    changed_paths = {
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    }
    disallowed = sorted(path for path in changed_paths if path not in allowed)
    if disallowed:
        raise ScoreMutationError(
            "scorer mutated tracked artifacts: " + ", ".join(disallowed)
        )
    return payload


def score_predictive_weak_targets(
    ledger_path: Path | str,
    *,
    weak_targets: Sequence[str] = ("PicSeq_Unadj", "ListSort_Unadj"),
    phase: str = "phase9_weak_target_term_discovery",
    baseline: float = -0.005,
    reference: float = 0.040,
    min_nulls: int = 4,
    min_replicates: int = 4,
) -> ScoreResult:
    rows = _read_jsonl(Path(ledger_path).expanduser().resolve())
    phase_rows = [row for row in rows if row.get("phase") == phase]

    best_r2: dict[str, float] = {}
    null_counts = dict.fromkeys(weak_targets, 0)
    replicate_counts = dict.fromkeys(weak_targets, 0)
    exploratory_terms: dict[str, set[int]] = {target: set() for target in weak_targets}

    for row in phase_rows:
        target = row.get("config", {}).get("target")
        if target not in weak_targets:
            continue
        score = row.get("scores", {}).get("gold_r2")
        if score is None:
            continue
        hyper = row.get("config", {}).get("hyperparameters", {})
        term_index = hyper.get("term_index")
        tags = set(row.get("tags") or [])
        is_null = "label-shuffle-control" in tags
        is_replicate = hyper.get("replicate_id") is not None
        if is_null:
            null_counts[target] += 1
        else:
            if is_replicate:
                replicate_counts[target] += 1
            if isinstance(term_index, int):
                exploratory_terms[target].add(term_index)
            if score > best_r2.get(target, float("-inf")):
                best_r2[target] = float(score)

    target_scores = {target: best_r2.get(target, baseline) for target in weak_targets}
    mean_r2 = (
        sum(target_scores.values()) / len(weak_targets) if weak_targets else baseline
    )
    score = max(0.0, min(1.0, (mean_r2 - baseline) / (reference - baseline)))
    contract_ok = all(
        null_counts.get(target, 0) >= min_nulls
        and replicate_counts.get(target, 0) >= min_replicates
        for target in weak_targets
    )

    payload = {
        "score": round(score, 4),
        "mean_r2_weak_targets": round(mean_r2, 6),
        "target_scores": {key: round(value, 6) for key, value in target_scores.items()},
        "contract_satisfied": contract_ok,
        "total_phase_rows": len(phase_rows),
        "null_counts": null_counts,
        "replicate_counts": replicate_counts,
        "exploratory_term_counts": {
            target: len(indices) for target, indices in exploratory_terms.items()
        },
        "phase": phase,
        "weak_targets": list(weak_targets),
    }
    return ScoreResult(
        scorer_name="predictive_weak_targets",
        score=float(payload["score"]),
        payload=payload,
        input_paths=(str(Path(ledger_path).expanduser().resolve()),),
    )


def score_discovery_closed_loop(
    checkpoint_path: Path | str,
    *,
    kg_log_path: Path | str,
    ledger_path: Path | str,
    expected_branches: Sequence[str] | None = None,
) -> ScoreResult:
    checkpoint_file = Path(checkpoint_path).expanduser().resolve()
    checkpoint = _read_json(checkpoint_file)
    rounds = checkpoint.get("rounds", [])
    branches: list[dict[str, Any]] = []
    n_rounds = len(rounds)
    if rounds:
        state_path = rounds[-1].get("state_path")
        if state_path:
            state = _read_json(Path(str(state_path)).expanduser().resolve())
            branches = list(state.get("branches", []))

    n_frozen = sum(1 for branch in branches if branch.get("status") == "frozen")
    scores = [
        float(branch.get("evidence", {}).get("best_score", 0.0) or 0.0)
        for branch in branches
    ]
    mean_best_score = sum(scores) / len(scores) if scores else 0.0
    score_a = (n_frozen / 5.0) * 0.7 + min(mean_best_score / 6.0, 1.0) * 0.3
    score_a = max(0.0, min(1.0, score_a))

    mandatory_injections = {1, 3, 4}
    kg_calls = _read_jsonl(Path(kg_log_path).expanduser().resolve())
    called_pairs = {
        (call.get("branch_id"), call.get("injection_point"))
        for call in kg_calls
        if call.get("branch_id")
        and call.get("injection_point") in mandatory_injections
        and not call.get("fallback")
    }
    branch_ids = [
        str(branch.get("branch_id")) for branch in branches if branch.get("branch_id")
    ]
    resolved_expected = list(
        expected_branches
        or branch_ids
        or [
            "tom",
            "language",
            "auditory",
            "math",
            "ibc_rsvp_language",
        ]
    )
    total_mandatory = len(resolved_expected) * len(mandatory_injections)
    n_called = sum(
        1
        for branch_id in resolved_expected
        for injection_point in mandatory_injections
        if (branch_id, injection_point) in called_pairs
    )
    score_b = n_called / total_mandatory if total_mandatory else 0.0

    hypotheses = _read_jsonl(Path(ledger_path).expanduser().resolve())
    n_novel = sum(
        1
        for hypothesis in hypotheses
        if hypothesis.get("kg_support_level") in {"unknown", "weak"}
        and len(hypothesis.get("kg_call_ids") or []) >= 2
    )
    score_c = min(n_novel / 3.0, 1.0)

    final_score = max(0.0, min(1.0, 0.6 * score_a + 0.2 * score_b + 0.2 * score_c))
    branch_summary = [
        {
            "branch_id": branch.get("branch_id"),
            "status": branch.get("status"),
            "decision": branch.get("decision"),
            "best_score": branch.get("evidence", {}).get("best_score"),
            "failure_modes": branch.get("failure_modes", []),
        }
        for branch in branches
    ]
    payload = {
        "score": round(final_score, 4),
        "score_A": round(score_a, 4),
        "score_B": round(score_b, 4),
        "score_C": round(score_c, 4),
        "n_frozen": n_frozen,
        "n_branches_seen": len(branches),
        "mean_best_score": round(mean_best_score, 4),
        "n_rounds": n_rounds,
        "n_kg_calls": len(kg_calls),
        "n_mandatory_called": n_called,
        "n_total_mandatory": total_mandatory,
        "n_novel_hypotheses": n_novel,
        "expected_branches": resolved_expected,
        "branches": branch_summary,
    }
    return ScoreResult(
        scorer_name="discovery_closed_loop",
        score=float(payload["score"]),
        payload=payload,
        input_paths=(
            str(checkpoint_file),
            str(Path(kg_log_path).expanduser().resolve()),
            str(Path(ledger_path).expanduser().resolve()),
        ),
    )


__all__ = [
    "ScoreMutationError",
    "ScoreResult",
    "parse_json_stdout",
    "run_guarded_scorer_command",
    "score_discovery_closed_loop",
    "score_predictive_weak_targets",
    "snapshot_tracked_tree",
]
