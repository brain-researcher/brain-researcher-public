# Autoresearch scripts

This directory is a mixed research-support archive, not one end-to-end public
workflow. Most scripts were written for a specific analysis workspace and need
inputs that are not distributed in this repository.

| Surface | Status | Boundary |
|---|---|---|
| [`run_auditable_claim_demo.py`](run_auditable_claim_demo.py) | **active, input-required** | Current implementation helper for the auditable-claim example. It requires an installed Python 3.11 clone and a staged NiMARE/Neurosynth corpus. The reproducibility tutorial is the supported user entrypoint. |
| Narrow validators with required CLI paths | **experimental** | Reusable only when every required input, manifest, output path, and scientific assumption is supplied explicitly. There is no directory-wide runner or shared acceptance contract. |
| Figure builders, patch materializers, watchdogs, tmux launchers, and migration helpers | **historical** | Point-in-time research operations. Several retain machine-specific defaults or mutate an external workspace. Do not run them as public examples. |
| [`fc/`](fc/) and most of [`discovery/`](discovery/) | **private-input-required** | Depend on governed HCP inputs, private analysis workspaces, derived features, or site-specific runtime state that the public clone does not ship. |

## Working directory

Resolve all repository-relative paths from the repository root. Do not `cd` into
this directory and assume that a script's relative paths will still work.

```bash
cd "$(git rev-parse --show-toplevel)"
python scripts/autoresearch/run_auditable_claim_demo.py --help
```

`--help` confirms the current arguments; it does not stage data or execute an
analysis. For runnable public workflows, start with:

- [Auditable claim record](../../reproducibility/auditable_claim_record/README.md)
- [Bounded autoresearch A1](../../reproducibility/bounded_autoresearch_a1/README.md)

## Execution boundary

Before running any other file here, inspect its defaults and required arguments.
Replace machine-specific input and output roots with explicit paths, keep outputs
outside the checkout unless the workflow documents a tracked artifact, and do
not interpret script completion as scientific validation. The public repository
does not include the private workspaces or governed subject-level data used by
the historical FC and discovery campaigns.
