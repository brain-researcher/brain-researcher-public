# Reproducibility Packs

This repository includes public-safe reproducibility packs under
[`reproducibility/`](../reproducibility/). They are meant for reviewers and users
who want to inspect the audit record behind a Brain Researcher result without
access to private runtime logs or governed datasets.

## What A Pack Proves

Each pack has:

- `manifest.json` with sha256 checksums for shipped artifacts
- `provenance_card.md` describing the execution envelope
- `README.md` with the result boundary and rerun instructions
- optional `run/`, `source/`, `artifacts/`, and `reproduction/` files

Run:

```bash
python reproducibility/verify.py reproducibility/packs/<id>
```

Exit code `0` means the shipped bytes match the manifest. It does not by itself
prove that an LLM rerun will be byte-identical.

## Current Packs

| Pack | Status | Boundary |
|---|---|---|
| `bounded_autoresearch_a1` | Real recorded result | Checksum-verifiable artifacts for the HCP-YA bounded-autoresearch A1 result. Full rerun is data-gated because HCP-YA behavior rows are not redistributed; the public pack includes a redacted Liu/Tian source-provenance summary with OSF node `75je2`, key checksums, component-reconstruction caveats, and the `reconstructed_not_paper_exact` boundary. |
| `fitlins_multiverse_yeo17` | Synthetic schema exemplar | Shows the run-bundle and multiverse layout. It is a format template, not a real-data result; statmap entries are `schema_only`. |

## Reproduce From Language (Claude Code / Codex + MCP)

Beyond re-running the frozen scripts, each worked case can be reproduced the way
the platform actually produces it — a coding agent driving the loop from natural
language through the MCP. These guides map each step to the typed MCP tool that
makes it a verifiable action, and include a paste-ready starter prompt:

| Case | Shape | Agentic guide |
|---|---|---|
| Bounded autoresearch A1 | Multi-turn feature/pipeline **search** loop (edit `predict.py` → frozen evaluator → score/compare → cheap-check → freeze → confirmatory null) | [`reproducibility/packs/bounded_autoresearch_a1/AGENTIC_REPRODUCTION.md`](../reproducibility/packs/bounded_autoresearch_a1/AGENTIC_REPRODUCTION.md) |
| Auditable claim record | Single sealed **claim episode** (commit-before-observe → graded evidence → adjudicate → emit card) | [`examples/auditable_claim_record/AGENTIC_REPRODUCTION.md`](../examples/auditable_claim_record/AGENTIC_REPRODUCTION.md) |

Honest scope: an agent's *search path* is non-deterministic, so a rerun
reproduces the **discipline** (commit-before-observe, frozen evaluator,
cheap-check-before-expensive-compute, literature-vetoed hypotheses) and — once the
same predictor/claim is frozen — the **confirmatory numbers / verdict**, not the
exact trajectory. Connect the MCP per [`mcp.md`](mcp.md); start each loop by
calling `loop_profile_get`.

## Audit Protocol Boundary

Brain Researcher can emit richer audit bundles when work runs through the
governed engine path that creates commitment cards, claim cards, run bundles,
review verdicts, and manifests. A post-hoc or local laptop recipe can still be
auditable, but it should be described as a partial or post-hoc record unless the
commit-before-observe artifacts actually exist.

For LLM-mediated workflows, reproducibility should be judged by the recorded
tool contract, prompt/model provenance, artifact checksums, and scientific
equivalence tolerances. Do not promise byte-identical LLM traces.

## Privacy Boundary

Public packs should not contain user session logs, bearer tokens, private MCP
tool names, or machine-local absolute paths. Session access in a deployed MCP
service should remain scoped to the requesting user; public artifacts are
separate, redacted exports.

For governed datasets such as HCP-YA, a public pack should expose the source
route and checksums without shipping restricted rows. The A1 pack follows that
pattern: `artifacts/liu_source_provenance_summary.json` records the Liu FC-pyspi
OSF route, reconstruction provenance, and redaction rules while omitting raw HCP
rows, subject identifiers, raw FC files, credentials, and local absolute paths.
The shipped A1 residualised-target CSV is also row-indexed; the governed output
checksum is retained in provenance, but HCP `Subject` identifiers are not shipped.
