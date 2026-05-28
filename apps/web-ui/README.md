# Brain Researcher Web UI

A modern Next.js-based web interface for the Brain Researcher neuroimaging analysis platform.

## Quick Start

### Using Brain Researcher CLI
```bash
# Start the web UI
br serve web

# Or with custom port
br serve web --port 3002
```

### Manual Setup
```bash
cd apps/web-ui
# The repo ships a .npmrc that pins legacy peer resolution to satisfy
# @cloudflare/next-on-pages peer requirements.
npm install
npm run dev
```

Access at http://localhost:3000 (Next.js dev server; public `/api/*` routes proxy
to Agent, Orchestrator, and BR-KG)

For helper scripts and Playwright-style local checks, you can also run
`npm run dev:3002` or override the target with `BR_WEB_URL`.

## Features

- 🧠 AI-powered neuroimaging workflows
- 📊 Dataset exploration (OpenNeuro, NeuroVault)
- 🤖 Copilot assistance for analysis
- 🔍 Knowledge graph integration
- ⚡ Real-time analysis streaming

## Configuration

Copy `.env.example` to `.env.local`:

```env
# Browser traffic stays same-origin by default
NEXT_PUBLIC_USE_API_PROXY=true

# Local downstream services
AGENT_PORT=8000
ORCHESTRATOR_PORT=3001
NEUROKG_PORT=5000

# Optional server-to-server overrides for Next.js route handlers
# BR_AGENT_URL=http://localhost:8000
# BR_ORCHESTRATOR_URL=http://localhost:3001
# BR_NEUROKG_URL=http://localhost:5000
```

## Docker

```bash
# Build and run
docker-compose up web-ui
```

## API Integration

- **BR-KG**: Knowledge graph and datasets
- **Agent**: chat/files/datasets/threads/runs
- **Orchestrator**: `/run`, `/api/jobs/*`, `/api/analyses/*`, share, dashboard, credits
- **NICLIP**: Text-to-brain mapping

## Documentation

- [Main Documentation](../../README.md)
- [CLI Documentation](../../docs/user-guide/cli.md)
- [Agent Service README](../../src/brain_researcher/services/agent/README.md)
- [BR-KG Service README](../../src/brain_researcher/services/kg/README.md)
