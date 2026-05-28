# Orchestrator Gateway Configuration

For the current Web UI topology, terminate browser traffic at the Next.js Web UI
and let its internal route handlers fan out to Agent, BR-KG, and Orchestrator.
Do not proxy every `/api/*` request directly to Orchestrator, because the Web UI
owns the public `/api/*` surface.

If you also want a direct operator/admin mount for Orchestrator, expose it under a
non-conflicting prefix such as `/orchestrator/`.

## Nginx (recommended)

```nginx
server {
    listen 80;
    server_name app.brainresearcher.local;

    location /orchestrator/ {
        proxy_pass http://orchestrator:3001/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
        add_header X-Accel-Buffering no;
    }

    location / {
        proxy_pass http://web-ui:3000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
```

## Traefik (docker labels)

```yaml
labels:
  - "traefik.http.routers.ui.rule=PathPrefix(`/`)"
  - "traefik.http.services.ui.loadbalancer.server.port=3000"
  - "traefik.http.routers.orchestrator.rule=PathPrefix(`/orchestrator`)"
  - "traefik.http.services.orchestrator.loadbalancer.server.port=3001"
  - "traefik.http.middlewares.orchestrator-sse.headers.customresponseheaders.X-Accel-Buffering=no"
  - "traefik.http.routers.orchestrator.middlewares=orchestrator-sse@docker"
```

Why it matters: SSE requires buffering to be disabled and generous timeouts;
the snippets above take care of both while preserving the Web UI's ownership of
public `/api/*` routes.
