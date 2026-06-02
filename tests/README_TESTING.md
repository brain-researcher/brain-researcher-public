# Brain Researcher Test Suite

## Quick Start

```bash
# From project root or tests directory:
./tests/run_tests.sh help

# Run fast unit tests (recommended for development)
./tests/run_tests.sh unit

# Run both unit shards used by CI
./tests/run_tests.sh unit-all-shards

# Run architecture import-boundary ratchets
./tests/run_tests.sh architecture

# Collect both unit shards without executing tests
./tests/run_tests.sh collect-all-shards

# Run all fast tests (default behavior)
./tests/run_tests.sh fast

# Run tests with coverage report
./tests/run_tests.sh coverage
```

## Test Categories

### Unit Tests
The default unit shard is fast, isolated coverage that does not require external
services. BR-KG unit tests are intentionally kept as an explicit shard instead
of being hidden inside recursive `tests/unit` collection.
```bash
./tests/run_tests.sh unit
```

### BR-KG Unit Shard
Specific unit tests for the Knowledge Graph service:
```bash
./tests/run_tests.sh unit-br-kg
# or
./tests/run_tests.sh br-kg
```

### All Unit Shards
Run the default unit shard followed by the explicit BR-KG shard:
```bash
./tests/run_tests.sh unit-all-shards
```

### Architecture Tests
Static architecture ratchets protect import boundaries that are being cleaned up
incrementally. The current ratchet prevents new `core -> services` imports while
allowing existing baseline removals.
```bash
./tests/run_tests.sh architecture
```

### Collection Checks
Collect tests without executing them:
```bash
./tests/run_tests.sh collect-unit
./tests/run_tests.sh collect-br-kg
./tests/run_tests.sh collect-all-shards
./tests/run_tests.sh collect-architecture
```

### Integration Tests
Tests that may require running services (BR-KG, Redis, etc.):
```bash
./tests/run_tests.sh integration
```

### PR Integration Smoke
Fast integration contract shard used by CI for PR/push gating:
```bash
./tests/run_tests.sh integration-pr-smoke
```

### Fast Tests (Default)
Runs tests excluding markers: `slow`, `e2e`, `realdata`
```bash
./tests/run_tests.sh fast
```

### All Tests
Run the default pytest-discovered selection honored by `pytest.ini`:
```bash
./tests/run_tests.sh all
```

## Test Markers

Available markers (from `pytest.ini`):
- `unit` - Fast, isolated unit tests
- `integration` - Tests requiring external services
- `slow` - Tests taking > 10 seconds
- `e2e` - End-to-end browser or multi-service tests
- `realdata` - Tests requiring large/open datasets
- `network` - Tests hitting external services
- `performance` - Performance benchmarking tests
- `requires_api` - Requires external API access
- `requires_gpu` - Requires GPU for computation

Real API smoke tests (example: Deep Research Interactions in `tests/integration/mcp/test_google_deep_research_interactions.py`)
require `BR_REAL_DEEP_RESEARCH=1` and `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
Google File Search smoke test in `tests/integration/mcp/test_google_file_search_smoke.py`
requires `BR_REAL_FILE_SEARCH=1` and `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
Optional: `BR_GOOGLE_FILE_SEARCH_STORE` or `GOOGLE_FILE_SEARCH_STORE` to attach a file search store.
NiCLIP engine smoke test: set `BR_REAL_NICLIP=1` and `NICLIP_DATA_PATH` (or `NICLIP_EMBEDDINGS_PATH`).
NiCLIP CLI smoke test: same envs; requires `br` (or `brain-researcher`) on PATH.

### Data-dependent unit tests (opt-in)
Some unit tests require external datasets or local vocab files and are skipped by default:

- **Allen Brain API loader** (`tests/unit/ingestion/test_allen_loader.py`)
  - Enable with: `BR_RUN_ALLEN_API_TESTS=1`
  - Uses the live Allen Brain API and local cache under `/tmp/allen_cache`.
- **HCP loader** (`tests/unit/ingestion/test_hcp_loader.py`)
  - Enable with: `BR_RUN_HCP_TESTS=1`
  - Expects real HCP input files unless you explicitly pass `demo_mode=True`.
- **NiCLIP scorer vocabulary** (`tests/unit/knowledge/scoring/test_niclip_scorer.py`)
  - Enable by ensuring vocab files exist under `NICLIP_DATA_PATH` (or default `data/niclip`),
    or force-run with `BR_RUN_NICLIP_UNIT_TESTS=1`.
  - Tests that require vocab will skip if files are missing and the force flag is not set.

## Running Specific Tests

```bash
# Run a specific test file
./tests/run_tests.sh specific tests/unit/br-kg/test_node_matcher.py

# Run a specific test function
./tests/run_tests.sh specific tests/unit/br-kg/test_node_matcher.py::test_exact_match_task

# Run tests matching a pattern
python3 -m pytest -k "br-kg and match" -v
```

## Coverage Reports

Generate HTML coverage report:
```bash
./tests/run_tests.sh coverage
# Report saved to: htmlcov/index.html
```

## Direct pytest Usage

You can also use pytest directly:
```bash
# Run with specific markers
python3 -m pytest -m "unit and not slow" -v

# Run with coverage
python3 -m pytest --cov=brain_researcher --cov-report=term-missing

# Run specific test with detailed output
python3 -m pytest tests/unit/br-kg/test_node_matcher.py -vv --tb=long

# List all available tests
python3 -m pytest --collect-only

# Collect both active unit shards
./tests/run_tests.sh collect-all-shards
```

## Test Structure

```
tests/
├── run_tests.sh           # Main test runner script
├── architecture/          # Static import-boundary ratchets
├── unit/                  # Default unit shard (fast, isolated)
│   ├── br-kg/          # Explicit BR-KG unit shard
│   ├── agent/            # Agent service tests
│   └── ...
├── integration/          # Integration tests (requires services)
├── e2e/                  # End-to-end tests
├── fixtures/             # Test fixtures and data
├── conftest.py          # Pytest configuration
└── README_TESTING.md    # This file
```

## Current Status

- **Default unit shard**: `9384/9399` collected, `15` deselected, `4` skipped
- **BR-KG unit shard**: `1146/1148` collected, `2` deselected
- **Architecture shard**: `2` collected
- **Unit collection errors**: 0 in the two explicit unit shards
- **Test Framework**: pytest 8.4.1
- **Coverage Tool**: pytest-cov
- **Timeout**: 300s per test

## Continuous Integration

Tests are configured to run automatically via:
- Default markers exclude slow tests: `-m "not slow and not e2e and not realdata"`
- CI runs both unit shards: `tests/unit/` and `tests/unit/br-kg/`
- CI runs architecture boundary tests on Python 3.11
- Timeout set to 300s per test
- Verbose output with `--strict-markers`

## Troubleshooting

### Import Errors
If you see import errors, ensure you're in the project root:
```bash
cd /home/zijiaochen/projects/brain_researcher
python3 -m pytest
```

### Missing Dependencies
Install test dependencies:
```bash
pip install -e ".[test]"
# or
pip install pytest pytest-cov pytest-asyncio pytest-mock
```

### Service Dependencies
Some integration tests require services to be running:
```bash
# Start BR-KG service
br serve kg --port 5000

# Start Redis (if needed)
redis-server --daemonize yes
```

## Examples

```bash
# Daily development workflow
./tests/run_tests.sh unit              # Quick default unit sanity check
./tests/run_tests.sh collect-all-shards # Verify both unit shards collect
./tests/run_tests.sh architecture      # Check import-boundary ratchets

# Before committing
./tests/run_tests.sh unit-all-shards   # Run both active unit shards

# Before PR
./tests/run_tests.sh coverage    # Check coverage
./tests/run_tests.sh integration # Verify integrations

# Debugging a specific test
./tests/run_tests.sh specific tests/unit/br-kg/test_node_matcher.py::test_exact_match_task
```
