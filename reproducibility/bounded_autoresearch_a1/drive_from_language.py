#!/usr/bin/env python3
"""Agentic path: the KG-as-prior step of the A1 loop, driven from language via MCP.

The deterministic sibling ``run_end_to_end.sh`` runs the frozen evaluator and
reproduces the headline number. The A1 loop's *language-driven* precondition is
the KG hypothesis step: from a natural-language query the deployed Brain
Researcher MCP surfaces falsifiable connectivity->behavior leads and vetoes /
downranks the ones the literature contradicts (``kg_hypothesis_workflow``). This
driver runs exactly that step and prints what survived and what was rejected.

The full loop (edit ``predict.py`` -> run the frozen evaluator -> score) is
agent-driven and its search path is non-deterministic by design; see
``AGENTIC_REPRODUCTION.md`` for the starter prompt a coding agent would follow.
This entry verifies the one typed step that is a single MCP call.

Needs a reachable MCP server (hosted ``BR_MCP_HTTP_URL`` + ``BR_MCP_TOKEN``, or a
local ``scripts/mcp/start_http_local.sh``):

    python drive_from_language.py
    python drive_from_language.py --from-file artifacts/agentic_kg_hypothesis_demo.json

KG sampling + OOD literature verification are non-deterministic and
budget-bounded: a re-run surfaces its own leads and may or may not spend budget
on a veto. What is invariant is the machinery — surfaced leads carry a falsifier,
duplicates collapse, same-family variants are downranked, and contradicted leads
are vetoed.
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

# pmid:27920976 is a real BR-KG Publication node: resting-state (dys)connectivity
# in generalized social anxiety disorder via the Weighted Phase Lag Index.
DEFAULT_SEED = "pmid:27920976"
DEFAULT_QUERY = (
    "A weighted phase-lag-index resting-state connectivity lead that could "
    "predict a behavioral trait (connectivity-statistic to behavior hypothesis)"
)


def call_mcp(
    tool: str,
    arguments: dict[str, Any],
    *,
    url: str | None,
    token: str | None,
    timeout_s: float,
) -> dict[str, Any]:
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
    return json.loads(proc.stdout)


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize {ok, result:{...}} envelopes and the shipped demo artifact."""
    if isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def _hypotheses(res: dict[str, Any]) -> list[dict[str, Any]]:
    # live payload -> "hypotheses"; the shipped curated demo -> "survived_hypothesis"
    if isinstance(res.get("hypotheses"), list):
        return res["hypotheses"]
    one = res.get("survived_hypothesis")
    return [one] if isinstance(one, dict) else []


def _vetoed(res: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(res.get("vetoed_candidates"), list):
        return res["vetoed_candidates"]
    one = res.get("vetoed_candidate")
    return [one] if isinstance(one, dict) else []


def summarize(payload: dict[str, Any], *, query: str) -> str:
    res = _result(payload)
    hyps = _hypotheses(res)
    vetoed = _vetoed(res)
    summary = res.get("summary") or {}

    lines = ["", "=== research query (natural language) ===", f"  {query}", ""]
    lines.append("=== surfaced, literature-survived leads ===")
    for h in hyps:
        if not h:
            continue
        lines.append(
            f"  - {h.get('anchor_label')} -> {h.get('candidate_label')} "
            f"[{h.get('verification_status')}]"
        )
        lines.append(f"      mechanism : {h.get('mechanism')}")
        lines.append(f"      falsifier : {h.get('falsifier')}")
        tri = h.get("semantic_triage_decision")
        if tri and tri != "pass":
            lines.append(f"      triage    : {tri} {h.get('semantic_triage_reasons')}")

    lines.append("")
    lines.append("=== rejected by the loop (not by the agent) ===")
    if vetoed:
        for v in vetoed:
            lines.append(
                f"  - VETOED {v.get('candidate_label')}: {v.get('verification_reason')}"
            )
    else:
        lines.append("  - (no hard veto this run — budget-bounded; see summary counts)")
    lines.append(
        f"  duplicates collapsed : {summary.get('n_collapsed_duplicate_candidates')}"
    )
    lines.append(f"  semantic downranked  : {summary.get('n_semantic_downranked')}")
    lines.append(f"  vetoed               : {summary.get('n_vetoed')}")
    lines.append(
        f"  verification counts  : {summary.get('verification_status_counts')}"
    )
    return "\n".join(lines)


def assert_structure(payload: dict[str, Any]) -> None:
    """Fail unless the surface->verify->veto machinery actually ran."""
    assert payload.get("ok") is not False, f"tool error: {payload.get('error')}"
    res = _result(payload)
    hyps = [h for h in _hypotheses(res) if h]
    assert hyps, "no hypotheses surfaced — KG-as-prior step did not run"
    for h in hyps:
        assert h.get("falsifier"), (
            f"surfaced lead has no falsifier: {h.get('candidate_label')}"
        )
        assert h.get("verification_status"), (
            "lead was not run through literature verification"
        )
    assert res.get("summary"), "no verification summary — veto machinery did not report"
    print(
        f"  OK: language query -> {len(hyps)} falsifiable, literature-checked lead(s)"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--query", default=DEFAULT_QUERY, help="Research query, natural language."
    )
    ap.add_argument(
        "--seed", default=DEFAULT_SEED, help="Seed BR-KG node id (e.g. a pmid)."
    )
    ap.add_argument("--n-samples", type=int, default=5)
    ap.add_argument("--url", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--timeout-s", type=float, default=120.0)
    ap.add_argument(
        "--from-file",
        default=None,
        help="Skip the MCP; summarize + assert a saved kg_hypothesis payload/artifact.",
    )
    args = ap.parse_args()

    if args.from_file:
        payload = json.loads(Path(args.from_file).read_text())
    else:
        info = call_mcp("server_info", {}, url=args.url, token=args.token, timeout_s=30)
        data = info.get("data") or info
        print(f"  MCP: {data.get('name')} contract {data.get('contract_version')}")
        payload = call_mcp(
            "kg_hypothesis_workflow",
            {
                "operation": "sample",
                "seed_kg_ids": [args.seed],
                "query": args.query,
                "n_samples": args.n_samples,
                "strategy": "evidence_first",
                "max_hops": 2,
            },
            url=args.url,
            token=args.token,
            timeout_s=args.timeout_s,
        )

    print(summarize(payload, query=args.query))
    print()
    assert_structure(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
