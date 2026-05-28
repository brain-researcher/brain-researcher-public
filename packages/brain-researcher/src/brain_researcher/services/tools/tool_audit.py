"""Generate repeatable audit reports for the tool catalog and NeoKG.

This module treats TSVs like `tool_universe.tsv` and `tool_family_suggestions.tsv`
as *generated artifacts* (not sources of truth), and helps produce stable
"gap lists" to drive controlled quality improvements.

Outputs (TSV):
- missing_in_neo4j.tsv: tool_universe - (:Tool)
- missing_in_universe.tsv: (:Tool) - tool_universe
- family_suggestions_filtered.tsv: tool_family_suggestions filtered to tools that exist in Neo4j
"""

from __future__ import annotations

import csv
import logging
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolUniverseRow:
    tool_id: str
    sources: str
    runtime_kind: str
    module: str


@dataclass(frozen=True)
class ToolFamilySuggestionRow:
    tool_id: str
    suggested_family: str
    reason: str


@dataclass(frozen=True)
class NeoToolRow:
    tool_id: str
    software: str | None
    runtime_kind: str | None
    source: str | None
    op_key: str | None
    is_default: bool | None
    exposed: bool | None
    primary_intent: str | None


@dataclass(frozen=True)
class ToolAuditOutputs:
    missing_in_neo4j: list[ToolUniverseRow]
    missing_in_universe: list[NeoToolRow]
    family_suggestions_filtered: list[ToolFamilySuggestionRow]
    stats: dict[str, Any]


def _find_repo_root(start: Path | None = None) -> Path:
    start_path = start or Path.cwd()
    for parent in [start_path, *start_path.resolve().parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return start_path.resolve()


def _read_repo_dotenv_value(repo_root: Path, key: str) -> str | None:
    for filename in (".env.local", ".env"):
        env_path = repo_root / filename
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() != key:
                continue
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            return val or None
    return None


def _get_env(repo_root: Path, key: str, default: str | None = None) -> str | None:
    return os.getenv(key) or _read_repo_dotenv_value(repo_root, key) or default


def _run_script(repo_root: Path, argv: list[str]) -> str:
    """Run a repo-local script and return stdout as text."""
    proc = subprocess.run(
        argv,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _ensure_tool_universe(repo_root: Path, tool_universe_path: Path) -> None:
    if tool_universe_path.exists():
        return
    logger.info("Generating %s via scripts/tools/dump_tools.py", tool_universe_path)
    stdout = _run_script(repo_root, ["python", "scripts/tools/dump_tools.py"])
    tool_universe_path.write_text(stdout, encoding="utf-8")


def _ensure_family_suggestions(repo_root: Path, suggestions_path: Path) -> None:
    if suggestions_path.exists():
        return
    logger.info("Generating %s via scripts/tools/suggest_tool_families.py", suggestions_path)
    stdout = _run_script(repo_root, ["python", "scripts/tools/suggest_tool_families.py"])
    suggestions_path.write_text(stdout, encoding="utf-8")


def load_tool_universe(path: Path) -> list[ToolUniverseRow]:
    rows: list[ToolUniverseRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tool_id = (row.get("id") or "").strip()
            if not tool_id:
                continue
            rows.append(
                ToolUniverseRow(
                    tool_id=tool_id,
                    sources=(row.get("sources") or "").strip(),
                    runtime_kind=(row.get("runtime_kind") or "").strip(),
                    module=(row.get("module") or "").strip(),
                )
            )
    return rows


def load_family_suggestions(path: Path) -> list[ToolFamilySuggestionRow]:
    rows: list[ToolFamilySuggestionRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tool_id = (row.get("tool_id") or "").strip()
            if not tool_id or tool_id.startswith("#"):
                continue
            rows.append(
                ToolFamilySuggestionRow(
                    tool_id=tool_id,
                    suggested_family=(row.get("suggested_family") or "").strip(),
                    reason=(row.get("reason") or "").strip(),
                )
            )
    return rows


def fetch_neo4j_tools(
    *,
    repo_root: Path,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> list[NeoToolRow]:
    uri = uri or _get_env(repo_root, "NEO4J_URI")
    username = username or _get_env(repo_root, "NEO4J_USER")
    password = password or _get_env(repo_root, "NEO4J_PASSWORD")
    database = database or _get_env(repo_root, "NEO4J_DATABASE")

    if not uri or not username or password is None or not database:
        raise RuntimeError(
            "Missing Neo4j configuration. Set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD/NEO4J_DATABASE."
        )

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        query = """
        MATCH (t:Tool)
        RETURN
          t.tool_id AS tool_id,
          t.software AS software,
          t.runtime_kind AS runtime_kind,
          t.source AS source,
          t.op_key AS op_key,
          t.is_default AS is_default,
          t.exposed AS exposed,
          t.primary_intent AS primary_intent
        """
        with driver.session(database=database) as session:
            result = session.run(query)
            rows: list[NeoToolRow] = []
            for rec in result:
                tool_id = rec.get("tool_id")
                if not tool_id:
                    continue
                rows.append(
                    NeoToolRow(
                        tool_id=str(tool_id),
                        software=rec.get("software"),
                        runtime_kind=rec.get("runtime_kind"),
                        source=rec.get("source"),
                        op_key=rec.get("op_key"),
                        is_default=rec.get("is_default"),
                        exposed=rec.get("exposed"),
                        primary_intent=rec.get("primary_intent"),
                    )
                )
        return rows
    finally:
        driver.close()


def _software_hint(tool_id: str) -> str:
    # Heuristic: first token before '.' is a good bucket across ids.
    # (e.g., afni.24.2.06..., fsl.6.0.4..., python.xxx, datasets.client)
    if "." in tool_id:
        return tool_id.split(".", 1)[0]
    if "_" in tool_id:
        return tool_id.split("_", 1)[0]
    return "unknown"


def build_audit_outputs(
    *,
    tool_universe: list[ToolUniverseRow],
    neo_tools: list[NeoToolRow],
    family_suggestions: list[ToolFamilySuggestionRow],
) -> ToolAuditOutputs:
    universe_ids = {row.tool_id for row in tool_universe}
    neo_ids = {row.tool_id for row in neo_tools}

    missing_in_neo4j = sorted(
        (row for row in tool_universe if row.tool_id not in neo_ids),
        key=lambda r: r.tool_id,
    )
    missing_in_universe = sorted(
        (row for row in neo_tools if row.tool_id not in universe_ids),
        key=lambda r: r.tool_id,
    )
    family_suggestions_filtered = sorted(
        (row for row in family_suggestions if row.tool_id in neo_ids),
        key=lambda r: (r.suggested_family, r.tool_id),
    )

    missing_sources = Counter()
    missing_runtime = Counter()
    missing_software = Counter()
    for row in missing_in_neo4j:
        missing_runtime[row.runtime_kind or "unknown"] += 1
        missing_software[_software_hint(row.tool_id)] += 1
        for src in (row.sources or "").split(","):
            src = src.strip()
            if src:
                missing_sources[src] += 1

    extra_runtime = Counter()
    extra_software = Counter()
    for row in missing_in_universe:
        extra_runtime[(row.runtime_kind or "unknown")] += 1
        extra_software[(row.software or "unknown")] += 1

    stats = {
        "tool_universe_count": len(universe_ids),
        "neo4j_tool_count": len(neo_ids),
        "missing_in_neo4j_count": len(missing_in_neo4j),
        "missing_in_universe_count": len(missing_in_universe),
        "missing_in_neo4j_by_source": missing_sources.most_common(15),
        "missing_in_neo4j_by_runtime_kind": missing_runtime.most_common(15),
        "missing_in_neo4j_by_software_hint": missing_software.most_common(15),
        "missing_in_universe_by_runtime_kind": extra_runtime.most_common(15),
        "missing_in_universe_by_software": extra_software.most_common(15),
        "family_suggestions_total": len(family_suggestions),
        "family_suggestions_filtered_count": len(family_suggestions_filtered),
    }

    return ToolAuditOutputs(
        missing_in_neo4j=missing_in_neo4j,
        missing_in_universe=missing_in_universe,
        family_suggestions_filtered=family_suggestions_filtered,
        stats=stats,
    )


def _write_tsv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_audit_reports(output_dir: Path, outputs: ToolAuditOutputs) -> dict[str, Path]:
    out_missing_in_neo4j = output_dir / "missing_in_neo4j.tsv"
    out_missing_in_universe = output_dir / "missing_in_universe.tsv"
    out_family_suggestions = output_dir / "family_suggestions_filtered.tsv"

    _write_tsv(
        out_missing_in_neo4j,
        ["id", "sources", "runtime_kind", "module"],
        [
            {
                "id": r.tool_id,
                "sources": r.sources,
                "runtime_kind": r.runtime_kind,
                "module": r.module,
            }
            for r in outputs.missing_in_neo4j
        ],
    )

    _write_tsv(
        out_missing_in_universe,
        [
            "tool_id",
            "software",
            "runtime_kind",
            "source",
            "op_key",
            "is_default",
            "exposed",
            "primary_intent",
        ],
        [
            {
                "tool_id": r.tool_id,
                "software": r.software or "",
                "runtime_kind": r.runtime_kind or "",
                "source": r.source or "",
                "op_key": r.op_key or "",
                "is_default": "" if r.is_default is None else str(bool(r.is_default)).lower(),
                "exposed": "" if r.exposed is None else str(bool(r.exposed)).lower(),
                "primary_intent": r.primary_intent or "",
            }
            for r in outputs.missing_in_universe
        ],
    )

    _write_tsv(
        out_family_suggestions,
        ["tool_id", "suggested_family", "reason"],
        [
            {
                "tool_id": r.tool_id,
                "suggested_family": r.suggested_family,
                "reason": r.reason,
            }
            for r in outputs.family_suggestions_filtered
        ],
    )

    return {
        "missing_in_neo4j": out_missing_in_neo4j,
        "missing_in_universe": out_missing_in_universe,
        "family_suggestions_filtered": out_family_suggestions,
    }


def generate_tool_audit_reports(
    *,
    output_dir: Path | None = None,
    tool_universe_path: Path | None = None,
    family_suggestions_path: Path | None = None,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> tuple[ToolAuditOutputs, dict[str, Path]]:
    repo_root = _find_repo_root()
    output_dir = output_dir or (repo_root / "artifacts" / "tool_audit")
    tool_universe_path = tool_universe_path or (repo_root / "tool_universe.tsv")
    family_suggestions_path = family_suggestions_path or (repo_root / "tool_family_suggestions.tsv")

    _ensure_tool_universe(repo_root, tool_universe_path)
    _ensure_family_suggestions(repo_root, family_suggestions_path)

    tool_universe = load_tool_universe(tool_universe_path)
    family_suggestions = load_family_suggestions(family_suggestions_path)
    neo_tools = fetch_neo4j_tools(
        repo_root=repo_root,
        uri=uri,
        username=username,
        password=password,
        database=database,
    )

    outputs = build_audit_outputs(
        tool_universe=tool_universe,
        neo_tools=neo_tools,
        family_suggestions=family_suggestions,
    )
    paths = write_audit_reports(output_dir, outputs)
    return outputs, paths
