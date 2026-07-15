# Verified Python 3.11 environments

These files are generated from `pyproject.toml` and the canonical universal
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
The clean-install smoke for the current checkout is:

```bash
scripts/setup/smoke_clean_install.sh core
```

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
