# Contributing to Brain Researcher

Thanks for your interest in contributing! Brain Researcher is an academic
research tool first and an open-source project second — we try to keep
the contribution process light while preserving scientific
reproducibility.

By participating in this project you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).

---

## Quick links

- 🐛 [File a bug](https://github.com/zjc062/brain_researcher/issues/new?template=bug.md)
- ✨ [Suggest a feature](https://github.com/zjc062/brain_researcher/issues/new?template=feature.md)
- 🔐 Report a vulnerability — see [`SECURITY.md`](SECURITY.md), **do not** open a public issue.
- 💬 Open-ended questions: [GitHub Discussions](https://github.com/zjc062/brain_researcher/discussions)

---

## Development setup

```bash
git clone https://github.com/zjc062/brain_researcher.git
cd brain_researcher
python -m venv .venv && source .venv/bin/activate
pip install -e .[all,dev]              # dev extras: pytest, ruff, mypy, etc.
cp .env.example .env                   # add an LLM API key
docker compose up -d neo4j postgres redis   # backing services
pytest tests/unit -x                   # quick smoke (~30s)
```

For the full local stack (agent + MCP + KG + web UI), follow the
`docker compose up -d` path in [README](README.md) or the
service-by-service walkthrough in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## PR workflow

### 1. Plan the change

Before writing code, especially for non-trivial work, open a Discussion
or draft issue describing:
- What you want to change and why
- Which datasets / tools / KG nodes are affected
- Whether a new dependency is needed

For substantial refactors, run the codegraph baseline first so you can
quantify the blast radius:

```bash
python scripts/analyze_code_import_graph.py \
  --src-root src/brain_researcher \
  --markdown-out /tmp/codegraph_local.md \
  --boundary core:services --boundary llmcore:services
```

Compare against the canonical baseline at
[`docs/architecture/codegraph_baseline.md`](docs/architecture/codegraph_baseline.md);
PRs must not introduce new cross-boundary violations.

For function-level impact (e.g., before renaming or moving a symbol),
the [code-review-graph](https://github.com/tirth8205/code-review-graph)
MCP tool surface is helpful:

```bash
pip install code-review-graph
code-review-graph build
code-review-graph serve     # then call `impact` / `affected` from your MCP client
```

### 2. Branch

```bash
git checkout -b <type>/<short-slug>
```

Type prefix one of: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`,
`perf`, `ci`.

### 3. Make the change

- **Style**: ruff + black + isort enforced via `.pre-commit-config.yaml`.
  Install hooks with `pre-commit install` (skip if you use git-annex —
  see [`docs/OPERATIONS.md`](docs/OPERATIONS.md)).
- **Types**: `mypy src/brain_researcher` should be clean for new code.
- **Tests**: add unit tests for new behavior; integration tests for new
  service surfaces. Mark slow / external-data tests with the appropriate
  `pytest.mark.*`.
- **Docs**: update `docs/` for user-facing changes; update
  `AGENTS.md` for new repository conventions.

### 4. Verify before pushing

```bash
ruff check src/ tests/
black --check src/ tests/
mypy src/brain_researcher --ignore-missing-imports
pytest tests/unit -x                  # required to pass
pytest tests/integration              # required for service changes
```

Pre-commit hooks (gitleaks, ruff, bandit, …) will run automatically.
Do not bypass them with `--no-verify` unless you're fixing a hook bug.

### 5. Open the PR

Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md) (if present) or
include:

- **What** changed and **why**
- Linked issue / discussion (if any)
- **Test plan** — what you ran, what passed
- **Impact** — for refactors, paste the codegraph diff or impact-report
  excerpt
- **Out-of-scope** — anything intentionally left for a follow-up

PRs go through CI (lint + tests + helm-render + secret scan). Reviewers
focus on correctness, test coverage, and scientific defensibility (for
analysis-touching changes).

---

## Repository conventions

### Hardcoded paths

**Never** commit absolute paths (`/home/<user>/...`) into source,
configs, or active docs. Use:
- env-var defaults: `os.environ.get("BR_DATA_ROOT", "/app/data")`
- repo-relative: `Path(__file__).resolve().parents[N] / "data"`
- helpers from `brain_researcher.config.paths`: `get_data_root()`,
  `get_config_root()`, etc.

The CI gitleaks step blocks new committed secrets; a manual grep
keeps personal paths out:

```bash
grep -rln "/home/$USER" src/ apps/ configs/ scripts/ tests/ docs/ \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.yaml" --include="*.yml" --include="*.json" \
  --exclude-dir=audits --exclude-dir=operations --exclude-dir=archive
# Should print nothing.
```

### Captured experiment archives

`benchmarks/reproducibility_audit_examples/`,
`benchmarks/UNIFIED_BENCHMARK_BUNDLE*/`, `docs/audits/`,
`docs/operations/*/data/`, `docs/archive/` are **frozen audit trails**.
Don't rewrite paths inside their JSON dumps — they're records, not
code. If you need to regenerate, do it via a new run, not by editing
the historical output.

### MCP tool naming

New MCP tools go under canonical SLURM/SLURM-style generic names
(`slurm_*` not `sherlock_*`). The existing `sherlock_*` tools are
kept as deprecated aliases for one release cycle and will be removed
post-v1.1.

---

## Adding a new analysis tool

To register a new analysis tool in the catalog so it's discoverable
from the agent / MCP loop:

1. Implement the tool under `src/brain_researcher/services/tools/`.
2. Add a contract entry in `configs/tools_catalog.json` (validated by
   `configs/schemas/tools_catalog.schema.json` in CI).
3. Add the tool name to `configs/catalog/exposed_tools.yaml`.
4. Add an example invocation in `configs/catalog/chat_tool_schemas.yaml`.
5. Add a unit test under `tests/unit/tools/`.
6. Document inputs/outputs in `docs/api/mcp-tools.md`.

---

## Adding a new SLURM cluster profile

See [`docs/hpc.md`](docs/hpc.md). One YAML in
`configs/slurm/profiles/<your_cluster>.yaml` is all it takes.

---

## Releasing

Releases are cut by the maintainers. The general flow:

1. Bump version in `pyproject.toml` and `CITATION.cff`.
2. Update `CHANGELOG.md` (Keep-a-Changelog format).
3. Tag the commit: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push --tags`.
4. CI builds Docker images, publishes to GHCR, and uploads PyPI.
5. Zenodo automatically mints a DOI for the tagged release.

---

## Contributor recognition

Significant contributions are acknowledged in the paper acknowledgments
section and in `CITATION.cff`'s `authors` block. Casual contributions
are recognized via GitHub's contributors graph. We do not require a CLA
— the MIT license covers both the project and contributions.
