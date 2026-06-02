# Scripts

`scripts/` contains reusable operational, benchmark, data, and maintenance entrypoints. Prefer topical subdirectories over adding new files at the root.

Canonical benchmark runners live in:

- `scripts/eval/`: tool-routing and evaluation harnesses
- `scripts/neurometabench_v1/`: NeuroMetaBench runners, evaluators, and post-processors
- `scripts/reproducibility_audit/`: reproducibility-audit runners and batch launchers

Operational and development helpers should use existing subdirectories such as `scripts/dev/`, `scripts/deployment/`, `scripts/ci/`, `scripts/mcp/`, `scripts/br-kg/`, or `scripts/tools/`.

Topical operational entrypoints include:

- `scripts/build/`: build/materialization helpers that create durable artifacts
- `scripts/demos/`: demo and example commands
- `scripts/ingest/`: data ingestion jobs
- `scripts/linking/`: graph/data linking jobs
- `scripts/setup/`: local environment setup helpers
- `scripts/smoke/`: smoke-test shell entrypoints
- `scripts/validation/`: standalone repository and artifact validation helpers
- `scripts/workflows/`: workflow runner scripts used by the workflow catalog

Do not commit generated caches, raw benchmark episode outputs, or run-specific producer scripts. Put temporary one-off code beside the run artifact, under `/tmp`, or in a clearly named legacy/archive location if it must be preserved.

For cleanup decisions, use `docs/testing/script_surface_inventory.md` to
separate active CI/runtime scripts, tested utilities, documented one-offs, and
delete/archive candidates before removing files.
