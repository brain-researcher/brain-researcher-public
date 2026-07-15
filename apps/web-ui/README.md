# Brain Researcher Web UI

This directory contains the Next.js 14 browser application. The table below
separates current entrypoints from opt-in or historical material.

| Surface | Status | Boundary |
|---|---|---|
| `npm run dev`, `npm run build`, `npm run test`, `npm run lint:ci` | **active** | Local Web UI development and validation only. Starting the UI does not start Agent, Orchestrator, BR-KG, or MCP services. |
| Storybook and Cloudflare scripts | **experimental** | These scripts are available in `package.json`, but they are not the default local or release gate. |
| `IMPLEMENTATION_SUMMARY.md` and feature-specific implementation notes | **historical** | Point-in-time engineering notes, not current verification or production-readiness evidence. |
| `npm run e2e:real` | **private-input-required** | Requires running backend services, shared auth configuration, and real executor-visible neuroimaging inputs. It creates persistent run state. |

## Working directory

Run commands from the repository root, the directory containing `pyproject.toml`
and `apps/`:

```bash
cd "$(git rev-parse --show-toplevel)"
npm --prefix apps/web-ui ci
npm --prefix apps/web-ui run dev
```

The development server is then available on `http://localhost:3000`. This starts
only the Web UI. Use the [root quick start](../../README.md#quick-start-local-docker)
when you need the default Docker service stack.

## Narrow validation

From the repository root:

```bash
npm --prefix apps/web-ui run lint:ci
npm --prefix apps/web-ui test
npm --prefix apps/web-ui run build
```

These commands validate frontend code. They do not prove that external services,
credentials, datasets, or hosted execution are available.

## Configuration and end-to-end boundaries

- Use [CONFIG.md](CONFIG.md) for browser/server URL and proxy configuration.
- Use [README-real-pipeline.md](README-real-pipeline.md) only for the opt-in real
  pipeline test. Follow its repository-root commands and stage the required data
  before running it.
- Do not treat [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) as the
  current feature inventory. Inspect the current routes, components, and tests
  instead.
