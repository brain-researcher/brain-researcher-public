"""Reconcile docs/mcp_tools.schema.json with the live @mcp.tool registry.

W1 of the OSS launch plan. Reads the existing aggregate tool-schema file as
baseline, cross-checks against the metadata declared in services/mcp/server.py
(_MCP_SURFACE_METADATA_BY_NAME), annotates each entry with a stability tier,
and emits one JSON per stable-tier tool under contracts/tools/<name>.json.

Stable tier is the 10 closed-loop tools listed in the OSS plan; everything
else is "experimental". Tools registered in server.py but missing from the
aggregate (added since 2026-03-17) are reported but not auto-added — they
need a human signature pass before entering the contract layer.

Usage:
    python scripts/oss/extract_tool_contracts.py            # write contracts/
    python scripts/oss/extract_tool_contracts.py --check    # verify only (CI)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE_PATH = REPO_ROOT / "docs" / "mcp_tools.schema.json"


def _locate_server_py() -> Path:
    """server.py lives at src/.../mcp/server.py in the source tree and at
    packages/brain-researcher/src/.../mcp/server.py post-carve. Try both."""
    candidates = (
        REPO_ROOT / "src" / "brain_researcher" / "services" / "mcp" / "server.py",
        REPO_ROOT / "packages" / "brain-researcher" / "src" / "brain_researcher" / "services" / "mcp" / "server.py",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "server.py not found at either src/ or packages/brain-researcher/src/ layout"
    )


SERVER_PY = _locate_server_py()
CONTRACTS_DIR = REPO_ROOT / "contracts"
CONTRACTS_TOOLS_DIR = CONTRACTS_DIR / "tools"
VERSION_FILE = CONTRACTS_DIR / "VERSION"

STABLE_TIER = (
    "server_info",
    "tool_search",
    "plan_preflight",
    "pipeline_plan_validate",
    "pipeline_plan_review",
    "get_execution_recipe",
    "grounding_gate_evidence_basis",
    "grounding_resolve",
    "scientific_report_generate",
    "run_scorecard",
)

# Tools we want to flag as deprecated aliases (kept for one release cycle).
DEPRECATED_ALIASES = {
    "sherlock_guide": "slurm_guide",
    "sherlock_slurm": "slurm_submit",
}


def load_aggregate() -> dict:
    with AGGREGATE_PATH.open() as fh:
        return json.load(fh)


def load_contract_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return "0.0.0-unset"


_MCP_TOOL_DECL_RE = re.compile(r"^@mcp\.tool\(\)\s*$\s*(?:async\s+)?def\s+(\w+)", re.MULTILINE)


def scan_server_tools() -> set[str]:
    """Return the names of every @mcp.tool() decorated function in server.py."""
    text = SERVER_PY.read_text()
    return set(_MCP_TOOL_DECL_RE.findall(text))


def stability_for(name: str) -> str:
    if name in STABLE_TIER:
        return "stable"
    if name in DEPRECATED_ALIASES:
        return "deprecated"
    return "experimental"


def annotate_tool(entry: dict, contract_version: str) -> dict:
    """Return a copy of `entry` with stability + contract_version added."""
    annotated = dict(entry)
    name = entry.get("name", "")
    annotated["stability"] = stability_for(name)
    annotated["contract_version"] = contract_version
    if name in DEPRECATED_ALIASES:
        annotated["deprecated_in_favor_of"] = DEPRECATED_ALIASES[name]
    return annotated


def schema_digest(entry: dict) -> str:
    """Stable sha256 digest over name + input/output schemas."""
    canonical = json.dumps(
        {
            "name": entry.get("name"),
            "input_schema": entry.get("input_schema"),
            "output_schema": entry.get("output_schema"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def toolset_hash(annotated_tools: list[dict]) -> str:
    """Stable sha256 over all stable-tier tools' (name, schema digest)."""
    stable_entries = sorted(
        (e for e in annotated_tools if e.get("stability") == "stable"),
        key=lambda e: e["name"],
    )
    h = hashlib.sha256()
    for entry in stable_entries:
        h.update(entry["name"].encode())
        h.update(b"\0")
        h.update(schema_digest(entry).encode())
        h.update(b"\0")
    return h.hexdigest()


def write_per_tool_json(entry: dict) -> Path:
    path = CONTRACTS_TOOLS_DIR / f"{entry['name']}.json"
    path.write_text(json.dumps(entry, indent=2, sort_keys=False) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify only: fail if contracts are stale or stable-tier tools missing.",
    )
    args = parser.parse_args()

    aggregate = load_aggregate()
    contract_version = load_contract_version()
    server_tools = scan_server_tools()

    aggregate_names = {entry["name"] for entry in aggregate["tools"]}
    missing_from_aggregate = sorted(server_tools - aggregate_names)
    missing_from_server = sorted(aggregate_names - server_tools)

    # Annotate every entry; we will emit per-tool JSONs only for stable-tier.
    annotated_tools = [annotate_tool(e, contract_version) for e in aggregate["tools"]]
    stable_entries = [e for e in annotated_tools if e["stability"] == "stable"]
    stable_names = {e["name"] for e in stable_entries}
    missing_stable = sorted(set(STABLE_TIER) - stable_names)

    th = toolset_hash(annotated_tools)

    # Report.
    print(f"contract_version: {contract_version}")
    print(f"aggregate tools : {len(aggregate['tools'])}")
    print(f"server @mcp.tool: {len(server_tools)}")
    print(f"stable tier     : {len(stable_entries)}/{len(STABLE_TIER)}")
    print(f"toolset_hash    : {th[:16]}…")
    if missing_from_aggregate:
        print(f"missing from aggregate (added since 2026-03-17, need review): {len(missing_from_aggregate)}")
        for n in missing_from_aggregate[:10]:
            print(f"  + {n}")
        if len(missing_from_aggregate) > 10:
            print(f"  ... +{len(missing_from_aggregate) - 10} more")
    if missing_from_server:
        print(f"in aggregate but not in server.py (likely removed): {len(missing_from_server)}")
        for n in missing_from_server:
            print(f"  - {n}")
    if missing_stable:
        print(f"ERROR: stable-tier tools missing from aggregate: {missing_stable}")
        return 2

    if args.check:
        # CI mode: verify per-tool JSONs match what we would emit.
        problems = []
        for entry in stable_entries:
            path = CONTRACTS_TOOLS_DIR / f"{entry['name']}.json"
            if not path.exists():
                problems.append(f"missing {path.relative_to(REPO_ROOT)}")
                continue
            existing = json.loads(path.read_text())
            expected = json.loads(json.dumps(entry, sort_keys=False))
            if existing != expected:
                problems.append(f"drift in {path.relative_to(REPO_ROOT)}")
        if problems:
            print("CHECK FAILED:")
            for p in problems:
                print(f"  {p}")
            return 1
        print("CHECK OK")
        return 0

    # Write mode.
    CONTRACTS_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for entry in stable_entries:
        path = write_per_tool_json(entry)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"\n{len(stable_entries)} stable-tier contracts written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
