"""Bounded deep-research -> Gabriel -> KGGEN -> idea-card pipeline."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.deep_research_idea_cards import (
    build_deep_research_idea_cards,
)
from brain_researcher.services.br_kg.etl.deep_research_bridge import (
    coerce_deep_research_result,
    write_gabriel_manifest_from_deep_research,
)

DEFAULT_MAX_SOURCES = 8
DEFAULT_MAX_SNIPPETS_PER_SOURCE = 4
DEFAULT_MAX_PAPERS = 4
DEFAULT_MAX_RELATIONS_PER_PAPER = 40
DEFAULT_TIMEOUT_SEC = 420.0
DEFAULT_RETRY_MAX_PAPERS = 2
DEFAULT_RETRY_MAX_RELATIONS_PER_PAPER = 20
DEFAULT_RETRY_TIMEOUT_SEC = 240.0
DEFAULT_KGGEN_MODEL = "gemini/gemini-2.5-flash"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _extract_interaction_id(result: dict[str, Any]) -> str | None:
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = str(metadata.get("interaction_id") or "").strip()
    return value or None


def _kggen_script_path() -> Path:
    return _repo_root() / "scripts" / "kggen_generate_from_manifest.py"


def _kggen_python_path() -> Path:
    return _repo_root() / "external" / "kg-gen" / ".venv" / "bin" / "python"


def _current_python_has_kggen() -> bool:
    return importlib.util.find_spec("kg_gen") is not None


def _resolve_kggen_python() -> Path:
    env_override = str(os.getenv("BR_DEEP_RESEARCH_IDEA_KGGEN_PYTHON") or "").strip()
    if env_override:
        candidate = Path(env_override).expanduser()
        if candidate.exists():
            return candidate.resolve()
        raise RuntimeError(
            "Configured KGGEN python was not found: "
            f"{candidate}. Check BR_DEEP_RESEARCH_IDEA_KGGEN_PYTHON."
        )

    repo_venv_python = _kggen_python_path()
    if repo_venv_python.exists():
        return repo_venv_python

    current_python = Path(sys.executable).resolve()
    if _current_python_has_kggen():
        return current_python

    raise RuntimeError(
        "KGGEN runtime not available. Checked repo venv at "
        f"{repo_venv_python} and current interpreter {current_python} "
        "without a loadable kg_gen package."
    )


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _count_nonempty_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except Exception:
        return 0
    return count


def _env_float(name: str) -> float | None:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _build_kggen_command(
    *,
    kggen_python: Path,
    script_path: Path,
    manifest_path: Path,
    kggen_output: Path,
    kggen_summary: Path,
    kggen_model: str,
    max_papers: int,
    max_relations_per_paper: int,
    query: str | None,
    no_dspy: bool = False,
) -> list[str]:
    cmd = [
        str(kggen_python),
        str(script_path),
        "--manifest",
        str(manifest_path),
        "--output",
        str(kggen_output),
        "--summary-output",
        str(kggen_summary),
        "--model",
        kggen_model,
        "--max-papers",
        str(max(1, int(max_papers))),
        "--max-relations-per-paper",
        str(max(1, int(max_relations_per_paper))),
        "--no-dedup",
        "--overwrite",
    ]
    if no_dspy:
        cmd.append("--no-dspy")
    if query:
        cmd.extend(
            ["--context", f"Deep-research grounded idea generation for: {query}"]
        )
    return cmd


def _write_timeout_summary(
    *,
    summary_path: Path,
    output_path: Path,
    timeout_sec: float,
    partial_rows: int,
    cmd: list[str],
) -> dict[str, Any]:
    summary = {
        "status": "partial_timeout",
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "timeout_seconds": round(float(timeout_sec), 3),
        "partial_rows": int(partial_rows),
        "command": cmd,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _run_kggen_with_recovery(
    *,
    cmd: list[str],
    repo_root: Path,
    kggen_output: Path,
    kggen_summary: Path,
    timeout_sec: float,
    retry_cmd: list[str] | None = None,
    retry_timeout_sec: float | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_sec)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        partial_rows = _count_nonempty_jsonl_rows(kggen_output)
        if partial_rows > 0:
            warnings.append("kggen_timeout_partial_output_used")
            summary = _load_json_if_exists(kggen_summary) or _write_timeout_summary(
                summary_path=kggen_summary,
                output_path=kggen_output,
                timeout_sec=timeout_sec,
                partial_rows=partial_rows,
                cmd=cmd,
            )
            return summary, warnings

        if retry_cmd is not None:
            warnings.append("kggen_timeout_retrying_reduced_config")
            retry_completed = subprocess.run(
                retry_cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=max(1.0, float(retry_timeout_sec or timeout_sec)),
                check=False,
            )
            if retry_completed.returncode != 0:
                stderr = (
                    retry_completed.stderr or retry_completed.stdout or ""
                ).strip()
                raise RuntimeError(
                    "KGGEN reduced-config retry failed with code "
                    f"{retry_completed.returncode}: {stderr[:1000]}"
                ) from None
            warnings.append("kggen_retry_succeeded")
            return _load_json_if_exists(kggen_summary), warnings

        raise RuntimeError(
            "KGGEN generation timed out after "
            f"{float(timeout_sec):.1f}s and produced no partial output"
        ) from None

    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"KGGEN generation failed with code {completed.returncode}: {stderr[:1000]}"
        )
    return _load_json_if_exists(kggen_summary), warnings


def generate_deep_research_idea_cards_from_result(
    *,
    deep_research_result: dict[str, Any],
    query: str | None = None,
    top_n: int = 5,
    min_supporting_papers: int = 2,
    output_dir: Path | None = None,
    max_sources: int = DEFAULT_MAX_SOURCES,
    max_snippets_per_source: int = DEFAULT_MAX_SNIPPETS_PER_SOURCE,
    max_papers: int = DEFAULT_MAX_PAPERS,
    max_relations_per_paper: int = DEFAULT_MAX_RELATIONS_PER_PAPER,
    kggen_model: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run a bounded idea-generation pipeline from deep-research results."""

    normalized = coerce_deep_research_result(dict(deep_research_result))
    if not isinstance(normalized.get("documents"), list) or not normalized.get(
        "documents"
    ):
        raise RuntimeError("deep research result contains no documents")

    repo_root = _repo_root()
    script_path = _kggen_script_path()
    kggen_python = _resolve_kggen_python()

    created_temp_dir = False
    if output_dir is None:
        output_dir = Path(
            tempfile.mkdtemp(prefix="deep_research_idea_cards_", dir=None)
        ).resolve()
        created_temp_dir = True
    else:
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    interaction_id = _extract_interaction_id(normalized)
    bridge_dir = output_dir / "bridge"
    bridge_summary = write_gabriel_manifest_from_deep_research(
        normalized,
        output_dir=bridge_dir,
        interaction_id=interaction_id,
        max_sources=max_sources,
        max_snippets_per_source=max_snippets_per_source,
        resolve_redirects=True,
        validate_identifiers=True,
    )

    manifest_path = bridge_dir / "manifest.json"
    kggen_output = output_dir / "kggen.idea_cards.jsonl"
    kggen_summary = output_dir / "kggen.idea_cards.summary.json"
    resolved_model = str(
        kggen_model
        or os.getenv("BR_DEEP_RESEARCH_IDEA_KGGEN_MODEL")
        or DEFAULT_KGGEN_MODEL
    )
    resolved_timeout_sec = _env_float("BR_DEEP_RESEARCH_IDEA_TIMEOUT_SEC") or float(
        timeout_sec
    )
    retry_timeout_sec = _env_float("BR_DEEP_RESEARCH_IDEA_RETRY_TIMEOUT_SEC") or min(
        resolved_timeout_sec,
        DEFAULT_RETRY_TIMEOUT_SEC,
    )
    cmd = _build_kggen_command(
        kggen_python=kggen_python,
        script_path=script_path,
        manifest_path=manifest_path,
        kggen_output=kggen_output,
        kggen_summary=kggen_summary,
        kggen_model=resolved_model,
        max_papers=max_papers,
        max_relations_per_paper=max_relations_per_paper,
        query=query,
    )
    retry_cmd = _build_kggen_command(
        kggen_python=kggen_python,
        script_path=script_path,
        manifest_path=manifest_path,
        kggen_output=kggen_output,
        kggen_summary=kggen_summary,
        kggen_model=resolved_model,
        max_papers=min(max(1, int(max_papers)), DEFAULT_RETRY_MAX_PAPERS),
        max_relations_per_paper=min(
            max(1, int(max_relations_per_paper)),
            DEFAULT_RETRY_MAX_RELATIONS_PER_PAPER,
        ),
        query=query,
        no_dspy=True,
    )
    should_retry = min(max(1, int(max_papers)), DEFAULT_RETRY_MAX_PAPERS) < int(
        max_papers
    ) or min(
        max(1, int(max_relations_per_paper)),
        DEFAULT_RETRY_MAX_RELATIONS_PER_PAPER,
    ) < int(
        max_relations_per_paper
    )
    kggen_summary_payload, kggen_warnings = _run_kggen_with_recovery(
        cmd=cmd,
        repo_root=repo_root,
        kggen_output=kggen_output,
        kggen_summary=kggen_summary,
        timeout_sec=resolved_timeout_sec,
        retry_cmd=retry_cmd if should_retry else None,
        retry_timeout_sec=retry_timeout_sec,
    )
    if _count_nonempty_jsonl_rows(kggen_output) <= 0:
        raise RuntimeError(
            "KGGEN finished without writing any rows to "
            f"{kggen_output}. Check bridge manifest content."
        )

    payload = build_deep_research_idea_cards(
        deep_research_result=normalized,
        kggen_input=kggen_output,
        query=query,
        top_n=top_n,
        min_supporting_papers=min_supporting_papers,
    )
    if output_dir is not None:
        idea_cards_path = output_dir / "idea_cards.json"
        idea_cards_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload["artifacts"] = {
            "bridge_dir": str(bridge_dir),
            "manifest_path": str(manifest_path),
            "kggen_output_path": str(kggen_output),
            "kggen_summary_path": str(kggen_summary),
            "idea_cards_path": str(idea_cards_path),
            "kggen_python_path": str(kggen_python),
        }
        payload["bridge_summary"] = bridge_summary
        payload["kggen_summary"] = kggen_summary_payload
    if kggen_warnings:
        payload.setdefault("warnings", []).extend(kggen_warnings)
    if created_temp_dir:
        payload.setdefault("warnings", []).append("ephemeral_output_dir")
    return payload


__all__ = ["generate_deep_research_idea_cards_from_result"]
