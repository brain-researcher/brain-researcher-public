# Brain Researcher Web UI

This directory contains the Next.js 14 browser application. The supported local
toolchain is Node.js 20 with npm 10; `package-lock.json` is the only dependency
lock used by the Web build.

| Surface | Status | Boundary |
|---|---|---|
| `npm run dev`, `npm test`, `npm run build`, `npm run lint:ci` | **active** | UI-only development and validation. These commands do not start Agent, Orchestrator, BR-KG, or MCP. |
| `npm run e2e:list`, `npm run e2e:smoke` | **active** | Playwright discovery and the narrow deterministic browser/API smoke. They are not a full backend or scientific rerun. |
| Storybook and Cloudflare scripts | **experimental** | Available in `package.json`, but not part of the default local or release gate. |
| `IMPLEMENTATION_SUMMARY.md` and feature-specific implementation notes | **historical** | Point-in-time engineering notes, not current verification or production-readiness evidence. |
| `npm run e2e:real` | **private-input-required** | Requires running backend services, shared auth configuration, and real executor-visible neuroimaging inputs. It creates persistent run state. |

## Working directory and commands

Run every command below from the repository root, the directory containing
`pyproject.toml` and `apps/`:

```bash
cd "$(git rev-parse --show-toplevel)"

# Deterministic install from apps/web-ui/package-lock.json
npm --prefix apps/web-ui ci

# Local development server at http://localhost:3000
npm --prefix apps/web-ui run dev

# Unit tests and production build
npm --prefix apps/web-ui test
npm --prefix apps/web-ui run build

# Playwright discovery, then the narrow smoke
npm --prefix apps/web-ui run e2e:list
npm --prefix apps/web-ui run e2e:install  # one-time Chromium setup
npm --prefix apps/web-ui run e2e:smoke
```

Run `npm --prefix apps/web-ui run lint:ci` for the focused frontend lint gate.
Starting the development server starts only the Web UI. Use the
[root quick start](../../README.md#quick-start-local-docker) when you need the
default Docker service stack.

## Environment files

- The repository-root [`.env.example`](../../.env.example) is the authoritative
  full-stack template. Copy it to the repository-root `.env` for Compose or
  shared service/auth configuration.
- [`.env.example`](.env.example) in this directory contains optional standalone
  Web routing overrides. UI-only install, dev, unit tests, and build need no env
  file. Copy it to `apps/web-ui/.env.local` only when changing those defaults.
- [`.env.test.template`](.env.test.template) is for the opt-in real-pipeline E2E.
  It does not replace the root service secrets and requires the private inputs
  documented in [README-real-pipeline.md](README-real-pipeline.md).

Protected/authenticated routes need `JWT_SECRET_KEY` or `NEXTAUTH_SECRET` shared
with the backing services. Upstream-backed routes also need Agent,
Orchestrator, and BR-KG running, either at their documented local defaults or at
the explicit internal URLs in [CONFIG.md](CONFIG.md).

These checks validate the frontend surface only. They do not prove that external
services, credentials, datasets, hosted execution, or a scientific rerun are
available. Do not treat [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) as
the current feature inventory; inspect current routes, components, and tests.
