# Benchmark And Evaluation Scope

Brain Researcher v0.1.0 ships the self-hostable platform, MCP contracts,
deployment assets, documentation, and public KG snapshot workflow. It does not
ship the benchmark task corpus in the main source tree.

## What Changed

The `benchmark/` directory is intentionally absent from
`brain-researcher-public`. The platform repository should stay focused on
runnable product code, contracts, deployment, and docs. Benchmark task corpora
move faster, carry separate provenance and review requirements, and should not be
published as if they were part of the core install surface.

## What Remains Public

- Stable MCP tool contracts under `contracts/`.
- Local Docker and Kubernetes deployment paths.
- Demo replay and KG snapshot documentation.
- Agent-facing examples, rubrics, and workflow templates in
  [`brain-researcher-agent-kit`](https://github.com/zjc062/brain-researcher-agent-kit).

## What Is Not In This Repository

- The retired `benchmark/tasks/**` corpus.
- Harbor task bundles and generated scoring artifacts.
- Private or lab-internal evaluation traces.
- Any benchmark claim that should be interpreted as a v0.1.0 leaderboard.

## Current Evaluation Path

For v0.1.0, use the companion agent kit for lightweight behavior checks and
reproducible demo rubrics. Larger benchmark corpora should be distributed
separately, with their own versioning, provenance notes, and review gates.

If a future public benchmark release is needed, publish it in a dedicated
repository or GitHub Release artifact rather than under the platform source
tree.
