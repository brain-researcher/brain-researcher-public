# Local deployment guide

> **Support boundary: local development only.** The public repository supports
> the root Docker Compose stack as a local development and evaluation surface.
> It does not ship a supported production, cloud, cluster, image-publishing,
> rollout, backup, or rollback contract.

For the support level of every deployment-related asset, see the
[deployment status matrix](infrastructure/deployment/README.md).

## Prerequisites

- Docker Engine with Docker Compose v2 (`docker compose`)
- `curl` for the shipped HTTP health smoke
- enough local disk and memory to build and run the services
- one supported LLM provider key and its matching model name
- local secrets for Neo4j and Web authentication

Run every command below from the repository root:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## 1. Create the local environment file

The root [`.env.example`](.env.example) is the only general environment
template for this stack.

Run the copy command only in a fresh checkout. If `.env` already exists, keep
it and update the required values instead; `cp` would overwrite it.

```bash
cp .env.example .env
```

Edit `.env` and replace the required placeholders. At minimum, set
`NEO4J_PASSWORD`, `JWT_SECRET_KEY`, `NEXTAUTH_SECRET`, and one supported LLM
provider key. Also set `DEFAULT_LLM_MODEL` to a model served by that provider;
the [environment guide](docs/ENVIRONMENT_SETUP.md) gives matching examples.
Keep `.env` local and never commit credentials.

## 2. Validate the Compose model

```bash
PUBLIC_HOSTNAME=localhost docker compose --env-file .env config --quiet
```

This checks Compose interpolation and structure. It does not build images,
start containers, test credentials, or prove that the services will become
healthy.

## 3. Start the local stack

```bash
docker compose up -d --build --wait --wait-timeout 300
```

The default stack contains Neo4j, Redis, BR-KG, the agent, and the Web UI. It
does not start the optional orchestrator worker or the MCP server.

Inspect every container, including the one-shot directory initializer:

```bash
docker compose ps --all
```

The expected steady state is:

- `init-local-dirs` exited with status 0;
- `neo4j`, `redis`, `br-kg`, `agent`, and `web-ui` are healthy;
- the Web UI is available at <http://localhost:3000>.

If a service does not become healthy, inspect the resolved configuration and
logs before changing anything:

```bash
docker compose config
docker compose logs --tail=200
```

## 4. Run the shipped health smoke

```bash
bash scripts/smoke/health_smoke.sh
```

The smoke checks the local Agent, BR-KG, and Web UI endpoints and exits nonzero
if one cannot be reached. A passing smoke proves only that these local HTTP
surfaces responded at that moment. It is not a scientific workflow test or a
production-readiness check.

## 5. Stop the local stack

```bash
docker compose down
```

Docker volumes remain unless an operator explicitly removes them. Do not add
`--volumes` unless deleting local state is intentional.

## Optional orchestrator worker

The `worker` profile adds the orchestrator to the local stack:

```bash
docker compose --profile worker up -d --build --wait --wait-timeout 300
docker compose --profile worker ps --all
```

Stop it with the same profile selection:

```bash
docker compose --profile worker down
```

This remains a local development surface.

## What this repository does not promise

The public tree has no verified production target, published image set, fixed
release-image tag, cloud account setup, DNS/TLS workflow, persistent storage
policy, secret-manager integration, zero-downtime rollout, backup procedure, or
rollback procedure. Files such as `docker-compose.prod.yml`, the Kubernetes
manifests, and the Helm chart are inspection or operator-specific assets; do
not interpret their presence as an apply-ready production system.

The superseded production-oriented document is preserved only in Git history:
[view the exact pre-rewrite snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/DEPLOYMENT.md).
The [deployment archive index](docs/archive/deployment/README.md) records the
other removed or downgraded assets without republishing unsafe commands as
active instructions.
