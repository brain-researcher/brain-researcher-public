#!/usr/bin/env python3
"""Agentic path: drive the auditable claim record from language through the MCP.

The deterministic sibling ``run_end_to_end.sh`` runs one fixed script. This driver
takes the claim as *natural language* and gates it through the deployed Brain
Researcher MCP (``neuroclaim_compile``): the claim is grounded, the two big
mapping uncertainties (coordinate->region, task->ontology) surface as explicit
"sorries", and a graded evidence verdict comes back with those uncertainties kept
as a NAMED VECTOR rather than folded into the association strength.

This is the ``compile`` step of the episode documented in
``AGENTIC_REPRODUCTION.md``; a coding agent (Claude Code / Codex) would drive the
same tool from the starter prompt there. It needs a reachable MCP server:

    # against a hosted server
    BR_MCP_HTTP_URL=https://<host>/mcp BR_MCP_TOKEN=... \
        python drive_from_language.py

    # or a local one: scripts/mcp/start_http_local.sh first, then
    python drive_from_language.py

The full lenient-vs-conservative sensitivity sweep (which is what flags the claim
threshold-fragile / ``weakened``) is a long call and can exceed an interactive
MCP timeout; it is OFF here by default (the verdict ships with a loud
"robustness unknown" caveat). Pass ``--full`` for it, or use the generator script
for the fully sealed record.

    python drive_from_language.py --from-file verdict.json   # offline: summarize a saved payload
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CALL_TOOL = REPO_ROOT / "scripts" / "mcp" / "call_http_tool.py"

DEFAULT_CLAIM = (
    "Working-memory-labeled Neurosynth studies show dlPFC activation and "
    "dlPFC-IPS coactivation within coordinate evidence."
)


def call_mcp(
    tool: str,
    arguments: dict[str, Any],
    *,
    url: str | None,
    token: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    """Call one MCP tool via the repo's HTTP JSON-RPC client, return its payload."""
    cmd = [
        sys.executable,
        str(CALL_TOOL),
        "call",
        tool,
        "--args",
        json.dumps(arguments),
        "--result-only",
    ]
    if url:
        cmd += ["--url", url]
    if token:
        cmd += ["--token", token]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{tool} call failed (exit {proc.returncode}):\n{proc.stderr.strip()}\n"
            f"{proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"{tool} returned non-JSON:\n{proc.stdout[:800]}") from exc


def summarize(report: dict[str, Any], *, claim: str) -> str:
    """Render the gated verdict the way a reader should read it. Pure function."""
    lines = ["", "=== claim (natural language) ===", f"  {claim}", ""]
    lines.append("=== gated verdict ===")
    lines.append(f"  status         : {report.get('status')}")
    lines.append(f"  verdict_basis  : {report.get('verdict_basis')}")
    ev = report.get("evidence_verdict") or {}
    raw = ev.get("raw") or {}
    lines.append(f"  backend        : {ev.get('backend')} ({ev.get('inference')})")
    if raw:
        lines.append(
            f"  evidence       : z={raw.get('z_association')} "
            f"p={raw.get('p_association')} n_studies={raw.get('n_studies')}"
        )

    lines.append("")
    lines.append("=== named uncertainty (kept as its own vector, NOT folded in) ===")
    for name, u in (report.get("uncertainty") or {}).items():
        sorry = " [SORRY]" if u.get("is_sorry") else ""
        lines.append(f"  {name:22s}: {u.get('value')}  ({u.get('source')}){sorry}")

    missing = report.get("missing_premises") or []
    if missing:
        lines.append("")
        lines.append("=== missing premises / open sorries ===")
        for m in missing:
            lines.append(f"  - {m}")

    rq = report.get("reproducible_query")
    if rq:
        lines.append("")
        lines.append("=== reproducible query (re-runnable) ===")
        lines.append(f"  {json.dumps(rq)}")
    return "\n".join(lines)


def assert_gated(report: dict[str, Any]) -> None:
    """Fail loudly unless the compile actually produced a gated verdict."""
    assert report.get("ok") is not False, f"compile error: {report.get('error')}"
    status = report.get("status")
    assert status, "no status in the report — compile did not run"
    ev = report.get("evidence_verdict") or {}
    n = (ev.get("raw") or {}).get("n_studies")
    assert n and n > 0, "evidence layer did not run (no corpus studies scored)"
    unc = report.get("uncertainty") or {}
    assert unc, "no named-uncertainty vector — the honesty layer did not fire"
    print(f"  OK: language -> gated verdict '{status}' with named uncertainty")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--claim", default=DEFAULT_CLAIM, help="Claim, in natural language."
    )
    ap.add_argument("--modality", default="fMRI")
    ap.add_argument("--workflow-family", default="neurolang_probabilistic_datalog")
    ap.add_argument(
        "--backend", default="nimare", choices=["nimare", "neurolang", "kg_verify"]
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="Run the full lenient-vs-conservative sensitivity sweep (slow).",
    )
    ap.add_argument(
        "--url", default=None, help="MCP URL (default BR_MCP_HTTP_URL / local)."
    )
    ap.add_argument(
        "--token", default=None, help="Bearer token (default BR_MCP_TOKEN / resolver)."
    )
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument(
        "--from-file",
        default=None,
        help="Skip the MCP; summarize + assert a saved neuroclaim report JSON.",
    )
    args = ap.parse_args()

    if args.from_file:
        report = json.loads(Path(args.from_file).read_text())
    else:
        # Sanity-check the server first (the episode's server_info step).
        info = call_mcp("server_info", {}, url=args.url, token=args.token, timeout_s=30)
        data = info.get("data") or info
        print(f"  MCP: {data.get('name')} contract {data.get('contract_version')}")
        report = call_mcp(
            "neuroclaim_compile",
            {
                "claim_text": args.claim,
                "modality": args.modality,
                "workflow_family": args.workflow_family,
                "backend": args.backend,
                "run_sensitivity": bool(args.full),
            },
            url=args.url,
            token=args.token,
            timeout_s=args.timeout_s,
        )

    print(summarize(report, claim=args.claim))
    print()
    assert_gated(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
