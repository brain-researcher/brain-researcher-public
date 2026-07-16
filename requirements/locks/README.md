# Verified Python 3.11 environments

These seven files are generated from `pyproject.toml` and the canonical universal
`uv.lock` with `uv 0.9.21`. Every export also includes the `[build]` profile so
the checkout can be installed with `--no-build-isolation`. Do not edit them by
hand.

The verified contract is a fresh Python 3.11 venv plus an editable install of
the current checkout. Runtime configuration still comes from the clone's
repo-level `configs/` directory, and the smoke sets `BR_CONFIG_ROOT` explicitly.
These locks do not certify a standalone wheel or install-from-anywhere runtime;
that package-data boundary remains separate from this checkout install gate.

| File | Install target | Role |
| --- | --- | --- |
| `core-py311.txt` | `-e .` | Base package and lightweight CLI |
| `mcp-py311.txt` | `-e ".[mcp]"` | MCP server and its current agent runtime graph |
| `agent-py311.txt` | `-e ".[agent]"` | Agent services and neuroimaging tools |
| `br-kg-py311.txt` | `-e ".[br-kg]"` | BR-KG, database, and scientific stack |
| `ci-py311.txt` | `-e ".[ci]"` | Offline PR tests and the complete strict-MkDocs plugin stack |
| `ci-services-py311.txt` | `-e ".[ci-services]"` | Focused service/downloader tests without the full agent ML stack |
| `dev-py311.txt` | `-e ".[all]"` | Full contributor environment |

Install dependencies first, then install the checkout without resolving a
second time:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/locks/core-py311.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
```

For another profile, use its matching requirements file and install target.
The lightweight PR test environment is:

```bash
python -m pip install -r requirements/locks/ci-py311.txt
python -m pip install --no-deps --no-build-isolation -e .
./tests/run_tests.sh unit-pr-smoke
./tests/run_tests.sh contracts
./tests/run_tests.sh reproducibility
```

The `ci` profile intentionally excludes the agent, BR-KG, browser, container,
and large scientific stacks. Use `ci-services-py311.txt` by itself for the
focused `services` runner; it inherits `ci` and adds only its direct runtime
imports, without Torch or CUDA wheels. JavaScript tests use `npm ci` in
`apps/web-ui`; deployment commands also need their documented Docker/Helm
executables.

```bash
python -m pip install -r requirements/locks/ci-services-py311.txt
python -m pip install --no-deps --no-build-isolation -e ".[ci-services]"
./tests/run_tests.sh services
```

The clean-install smoke for the current checkout is:

```bash
scripts/setup/smoke_clean_install.sh core
```

`BR_CLEAN_INSTALL_PIP_CACHE_DIR` may point at a reusable pip cache (for example,
`$HOME/.cache/pip` in CI). It changes only downloaded-wheel caching; each smoke
still creates a fresh isolated venv under `BR_CLEAN_INSTALL_ROOT`.

Regenerate without changing selected versions, intentionally upgrade, or
verify lock freshness and byte-for-byte export freshness with:

```bash
scripts/setup/refresh_locks.sh
scripts/setup/refresh_locks.sh --upgrade
scripts/setup/refresh_locks.sh --check
```

The text exports intentionally omit hashes because pip hash mode cannot verify
VCS requirements. Every VCS dependency uses an immutable 40-character commit,
and `uv.lock` retains registry artifact hashes and the full resolution record.
