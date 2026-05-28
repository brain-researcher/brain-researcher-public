# Web UI Configuration Guide

This document explains how the Brain Researcher Web UI resolves downstream
services in development and production.

> Important: the browser should normally talk to the Web UI only. The Next.js
> app owns the public same-origin surface and proxies to the downstream
> services:
>
> - Agent on `8000`
> - Orchestrator on `3001`
> - BR-KG on `5000`

## Quick Start

1. Copy the example configuration:
   ```bash
   cp .env.example .env.local
   ```
2. Edit `.env.local` only if you need non-default ports, hosts, or external
   services.
3. Restart the development server:
   ```bash
   npm run dev
   ```

## Default Model

By default, browser traffic stays same-origin.

- HTTP traffic goes through the Web UI under routes such as `/api/*` and
  `/internal/agent`
- WebSocket traffic defaults to `/ws`
- The Web UI then forwards to Agent, Orchestrator, or BR-KG as needed

This is controlled by:

```bash
NEXT_PUBLIC_USE_API_PROXY=true
```

That value is the default. You usually do not need to set it explicitly.

## Recommended Configurations

### Option 1: Same-Origin Proxy Mode (Recommended)

Use the proxy model for local development and most deployments.

```bash
NEXT_PUBLIC_USE_API_PROXY=true
AGENT_PORT=8000
ORCHESTRATOR_PORT=3001
KG_PORT=5000
AGENT_HOST=localhost
ORCHESTRATOR_HOST=localhost
KG_HOST=localhost
```

**When to use:** almost always. This is the default browser-safe setup.

### Option 2: Direct Public URLs (Advanced / Opt-Out)

Only use direct browser URLs if you intentionally want to bypass the Web UI
proxy.

```bash
NEXT_PUBLIC_USE_API_PROXY=false
NEXT_PUBLIC_AGENT_API=http://localhost:8000
NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:3001
NEXT_PUBLIC_BR_KG_API=http://localhost:5000
NEXT_PUBLIC_WS_URL=ws://localhost:3001/ws
```

**When to use:** custom deployments, debugging, or environments where the Web UI
should not proxy browser traffic.

## Service Ports Reference

| Service      | Default Port | Environment Variable | Description |
|--------------|--------------|----------------------|-------------|
| Agent        | 8000         | `AGENT_PORT`         | Chat, files, datasets, threads, legacy runs |
| Orchestrator | 3001         | `ORCHESTRATOR_PORT`  | `/run`, jobs, analyses, credits, notifications |
| BR-KG       | 5000         | `KG_PORT`            | Knowledge graph API |
| NICLIP       | 8001         | `NICLIP_PORT`        | Image embedding service |
| Web UI       | 3000         | `WEB_UI_PORT`        | Frontend dev server |

## Configuration Priority

For server-side downstream service resolution, the system prefers:

1. Explicit internal service URLs such as `BR_AGENT_URL`,
   `BR_ORCHESTRATOR_URL`, `BR_KG_URL`
2. Service-specific base URL / host / port settings
3. Local defaults (`localhost` with standard ports)

Browser-facing `NEXT_PUBLIC_*` overrides do not participate in server-side
resolver selection. They only affect direct browser mode when
`NEXT_PUBLIC_USE_API_PROXY=false`.

For browser traffic, `NEXT_PUBLIC_USE_API_PROXY=true` keeps requests same-origin
unless you explicitly opt out.

## Common Scenarios

### Scenario 1: Default Local Development

No configuration is required beyond running the services:

```bash
npm run dev
```

The browser uses same-origin routes. The Web UI forwards to local Agent,
Orchestrator, and BR-KG services on their default ports.

### Scenario 2: Custom Local Ports

If one of the default service ports is already in use:

```bash
# .env.local
AGENT_PORT=8004
ORCHESTRATOR_PORT=3004
KG_PORT=5004
```

You usually do not need to set matching `NEXT_PUBLIC_*` variables if proxy mode
stays enabled.

### Scenario 3: Docker Compose / Internal Hostnames

```bash
# .env.local
AGENT_HOST=agent
ORCHESTRATOR_HOST=orchestrator
KG_HOST=kg
AGENT_PORT=8000
ORCHESTRATOR_PORT=3001
KG_PORT=5000
```

The browser still talks to the Web UI. The Web UI talks to the service
hostnames above.

### Scenario 4: Production with HTTPS

Keep proxy mode enabled unless you have a specific reason to expose direct
service URLs:

```bash
HTTP_PROTOCOL=https
WS_PROTOCOL=wss
NEXT_PUBLIC_USE_API_PROXY=true
```

If you intentionally disable proxy mode, also provide explicit public service
URLs:

```bash
NEXT_PUBLIC_USE_API_PROXY=false
NEXT_PUBLIC_AGENT_API=https://agent.example.com
NEXT_PUBLIC_ORCHESTRATOR_URL=https://orchestrator.example.com
NEXT_PUBLIC_BR_KG_API=https://kg.example.com
NEXT_PUBLIC_WS_URL=wss://orchestrator.example.com/ws
```

## WebSocket Endpoints

WebSocket connections default to same-origin `/ws` when proxy mode is enabled.
Only set `NEXT_PUBLIC_WS_URL` if you need to override that behavior.

## Browser Endpoint Helpers

For browser code, prefer the centralized helpers over hardcoded URLs:

```typescript
import { serviceEndpoints } from '@/lib/service-endpoints'

await fetch(serviceEndpoints.orchestrator('/api/jobs'))
await fetch(serviceEndpoints.agent('/api/chat'))
```

For server-side code that needs explicit downstream ownership, use the resolver
helpers under `src/lib/server/*`.

## Environment Variables Reference

### Public Browser Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_USE_API_PROXY` | `true` | Keep browser traffic same-origin |
| `NEXT_PUBLIC_AGENT_API` | derived | Direct Agent base URL when proxy mode is disabled |
| `NEXT_PUBLIC_ORCHESTRATOR_URL` | derived | Direct Orchestrator base URL when proxy mode is disabled |
| `NEXT_PUBLIC_BR_KG_API` | derived | Direct BR-KG base URL when proxy mode is disabled |
| `NEXT_PUBLIC_WS_URL` | `/ws` in proxy mode | Optional WebSocket override |

### Internal / Server-Side Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BR_AGENT_URL` | none | Explicit internal Agent base URL |
| `BR_ORCHESTRATOR_URL` | none | Explicit internal Orchestrator base URL |
| `BR_KG_URL` | none | Explicit internal BR-KG base URL |
| `AGENT_HOST` / `AGENT_PORT` | `localhost` / `8000` | Agent service location |
| `ORCHESTRATOR_HOST` / `ORCHESTRATOR_PORT` | `localhost` / `3001` | Orchestrator service location |
| `KG_HOST` / `KG_PORT` | `localhost` / `5000` | BR-KG service location |

### Compatibility Variables

These still work, but they are legacy compatibility inputs rather than the
preferred configuration surface:

- `ORCHESTRATOR_URL`
- `ORCHESTRATOR_API_URL`
- `BR_NEUROKG_URL`
- `NEXT_PUBLIC_NEUROKG_API`
- `NEUROKG_HOST`
- `NEUROKG_PORT`

`NEXT_PUBLIC_AGENT_URL` is no longer part of the supported browser/runtime
contract. Use `NEXT_PUBLIC_AGENT_API` instead when you intentionally disable
proxy mode.

## Troubleshooting

### WebSocket Connection Failures

**Symptom:** WebSocket connection fails

**Check:**

1. If proxy mode is enabled, the browser should use `/ws`, not
   `ws://localhost:3001/ws`
2. Only set `NEXT_PUBLIC_WS_URL` when overriding the default routing
3. Ensure the upstream Orchestrator WebSocket server is reachable by the Web UI

### Wrong Downstream Target

**Symptom:** the Web UI proxies to the wrong service or wrong port

**Check:**

1. Prefer explicit internal variables such as `BR_ORCHESTRATOR_URL`
2. Otherwise verify `*_HOST` and `*_PORT`
3. Avoid relying on `NEXT_PUBLIC_*` as the primary server-side configuration

### Port Already in Use

**Symptom:** `EADDRINUSE`

**Solution:**

```bash
WEB_UI_PORT=3002
npm run dev -- -p 3002
```

## Validation

To verify your configuration:

1. Check the config endpoint:
   ```bash
   curl http://localhost:3000/api/config
   ```
2. Inspect browser DevTools:
   - with proxy mode enabled, browser requests should stay same-origin
   - downstream `localhost:8000/3001/5000` requests should come from the server,
     not the browser
3. Check `/api/health`, `/api/kg/health`, and related same-origin routes

## See Also

- [Next.js Environment Variables](https://nextjs.org/docs/app/building-your-application/configuring/environment-variables)
- [Brain Researcher Architecture](../../docs/architecture.md)
