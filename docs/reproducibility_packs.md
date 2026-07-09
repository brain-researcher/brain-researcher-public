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
| `bounded_autoresearch_a1` | Real recorded result | Checksum-verifiable artifacts for the HCP-YA bounded-autoresearch A1 result. Full rerun is data-gated because the HCP-YA behavior inputs are not redistributed. |
| `fitlins_multiverse_yeo17` | Synthetic schema exemplar | Shows the run-bundle and multiverse layout. It is a format template, not a real-data result; statmap entries are `schema_only`. |

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
