# Brain Researcher test suite

## Working directory and environment

Run the commands in this guide from the **repository root**, the directory that
contains `pyproject.toml` and `tests/`:

```bash
cd "$(git rev-parse --show-toplevel)"
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/locks/ci-py311.txt
python -m pip install --no-deps --no-build-isolation -e .
```

The `ci` lock supports the offline PR smoke, contract, reproducibility,
documentation, Web repository-contract, and deployment-contract checks. It
does not install the agent, BR-KG, browser, container, or large scientific
stacks. Use `requirements/locks/ci-services-py311.txt` by itself for the
`services` command; it inherits the CI tools without pulling the full agent ML
stack. Use the `dev`/`all` profile for the broad legacy unit shards.

The supported environment is Python 3.11. Once that environment is active,
set `PYTHON_BIN` only when you need to select its interpreter explicitly:

```bash
PYTHON_BIN=python3.11 ./tests/run_tests.sh help
```

If you are already inside `tests/`, invoke the same runner as
`./run_tests.sh <command>` instead of adding another `tests/` prefix.

## Quick start

```bash
# Show only the commands that exist in the current public tree.
./tests/run_tests.sh help

# Run the lightweight offline Python PR shards.
./tests/run_tests.sh unit-pr-smoke
./tests/run_tests.sh contracts
./tests/run_tests.sh reproducibility

# In a separate venv installed from ci-services-py311.txt:
./tests/run_tests.sh services

# Run Python Web contracts plus npm lint, unit tests, and production build.
# Run `npm ci` in apps/web-ui first.
./tests/run_tests.sh web

# Run configuration, Compose, Dockerfile, and Helm static checks.
./tests/run_tests.sh deployment-static

# The broad scientific/service shards remain explicit opt-ins.
./tests/run_tests.sh unit-all-shards
```

## Supported runner commands

| Command | What it does |
|---|---|
| `unit` | Runs `tests/unit/`, excluding `tests/unit/br_kg/` through `pytest.ini`. |
| `unit-br-kg` / `br-kg` | Runs `tests/unit/br_kg/`. |
| `unit-all-shards` | Runs the default unit shard, then the BR-KG shard. |
| `unit-pr-smoke` | Runs the small offline active-contract unit smoke selection. |
| `contracts` | Runs offline source-layout, package, docs-link, runtime, and configuration contracts. |
| `reproducibility` | Runs offline source-closure, manifest, verifier, archive, and scheduled-rerun report-builder checks. It validates report structure without importing the optional scientific stack or rerunning large analyses. |
| `services` | Runs downloader governance plus the five top-level service utility unit files; install `ci-services-py311.txt`. It excludes nested gateway/orchestrator/BR-KG suites, does not start live services, and does not call provider APIs. |
| `web` | Runs Python Web repository contracts, then `npm run lint:ci`, `npm test`, and `npm run build` in `apps/web-ui/`. Run `npm ci` there first. |
| `deployment-static` | Runs the tracked static deployment script plus Python deployment contracts. It validates configuration; it does not start or deploy services. |
| `architecture` | Runs `tests/architecture/test_import_boundaries.py`. |
| `fast` | Runs default discovery excluding `slow`, `e2e`, `realdata`, `network`, `requires_api`, and `requires_gpu`. |
| `coverage` | Runs the default selection and writes `htmlcov/index.html`. |
| `specific PATH` | Runs one pytest file or node id with the normal shared pytest fixtures. |
| `markers` | Prints marker declarations from `pytest.ini`. |
| `collect`, `collect-unit`, `collect-br-kg`, `collect-all-shards`, `collect-architecture` | Collects the corresponding selection without running it. |
| `all` | Runs the default pytest-discovered selection governed by `pytest.ini`. |

The public tree currently has no dedicated `tests/integration/` shard, so this
runner does not advertise an `integration` command. Add a real public shard and
its prerequisites before restoring that entry point.

The six PR-focused commands use explicit test-file inventories and do not load
the broad `tests/conftest.py`, whose shared fixtures require the full service
and scientific environment. This keeps a clean CI install honest: passing a
focused shard is not a claim that the full unit suite passed.

## Run a specific test

```bash
./tests/run_tests.sh specific tests/unit/br_kg/test_node_matcher.py
python -m pytest \
  tests/unit/br_kg/test_node_matcher.py::TestUnifiedNodeMatcher::test_exact_match_task \
  -v
python -m pytest -k "node_matcher and exact" -v
```

## Test markers

The full marker list lives in `pytest.ini` and is printed by
`./tests/run_tests.sh markers`. Common markers include:

- `unit`: fast, isolated unit coverage
- `integration`: tests that require multiple components or services
- `slow`: tests taking more than about 10 seconds
- `e2e`: browser or multi-service tests
- `realdata`: tests requiring large or external datasets
- `network`: tests that contact external services
- `performance`: performance and benchmark checks
- `requires_api`: tests requiring an external API
- `requires_gpu`: tests requiring a GPU

Markers describe individual tests; they do not imply that a same-named
top-level directory or runner command exists. The default selection in
`pytest.ini` excludes `slow`, `e2e`, `realdata`, `network`, `requires_api`, and
`requires_gpu`; opt in explicitly when the required data, credentials, network,
or hardware are available.

## Data-dependent unit tests

These files contain data-dependent cases that are skipped by default. Some have
a usable opt-in path; others still need public fixture wiring:

- `tests/unit/ingestion/test_allen_loader.py`
  - set `BR_RUN_ALLEN_API_TESTS=1`
  - contacts the live Allen Brain API and normally caches under
    `~/.cache/brain_researcher/`
- `tests/unit/ingestion/test_hcp_loader.py`
  - is skipped by default and is not currently a runnable public-data smoke:
    setting `BR_RUN_HCP_TESTS=1` does not provide its required HCP file paths
- `tests/unit/knowledge/scoring/test_niclip_scorer.py`
  - provide `NICLIP_DATA_PATH`, or unskip the opt-in cases with
    `BR_RUN_NICLIP_UNIT_TESTS=1`

Never place credentials in a command or tracked fixture. Load required values
from your local environment.

## Direct pytest usage

```bash
# Run the default marker selection from pytest.ini.
python -m pytest

# Collect without execution; use this instead of a hardcoded test count.
python -m pytest --collect-only

# Run one marker selection.
python -m pytest -m "unit and not slow" -v

# Generate terminal coverage output.
python -m pytest --cov=brain_researcher --cov-report=term-missing
```

Test counts change frequently. Treat the current collection output, not a number
copied into this README, as the authoritative inventory.

## Repository test layout

```text
tests/
├── architecture/        # Static import-boundary checks
├── unit/                # Default unit shard
│   └── br_kg/           # Explicit BR-KG unit shard
├── cli/                 # CLI-focused checks
├── eval/                # Evaluation harness checks
├── fixtures/            # Public test fixtures
├── performance/         # Performance checks
├── tools/               # Tool-level checks
├── run_tests.sh         # Supported shell runner
└── README_TESTING.md    # This guide
```

Browser tests for the Next.js application live under `apps/web-ui/tests/` and
use the scripts in `apps/web-ui/package.json`. The `web` PR shard runs lint,
Vitest, and a production build, but it does not run Playwright browser tests.

## Troubleshooting

### Import errors

Confirm the repository root and active interpreter before debugging the test:

```bash
cd "$(git rev-parse --show-toplevel)"
which python
python -c "import brain_researcher; print(brain_researcher.__file__)"
```

This repository has optional scientific and service dependencies. If a focused
test still fails during collection, report the exact missing module separately
from the behavior under test.

### Service-dependent tests

Start only the services named by the test. For example:

```bash
brain-researcher serve kg --port 5000
```

Do not infer that a service is required merely from a marker name; inspect the
test's skip condition and fixture first.
