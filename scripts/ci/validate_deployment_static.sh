#!/usr/bin/env bash
set -euo pipefail

# Validate inspectable deployment configuration without starting services.
#
# Supported local deployment remains the root docker-compose.yml workflow.
# The CC overlay, standalone Compose files, and Helm chart are experimental
# static inputs. Passing this gate proves only that those inputs can be parsed
# (and, for Helm, rendered); it does not make them runnable deployment targets.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PLACEHOLDER_ROOT="$(
  mktemp -d "${TMPDIR:-/tmp}/brain-researcher-deployment-static.XXXXXX"
)"
PLACEHOLDER_ENV="${PLACEHOLDER_ROOT}/.env"

cleanup() {
  if [[ -d "${PLACEHOLDER_ROOT}" ]]; then
    find "${PLACEHOLDER_ROOT}" -type f -delete
    rmdir "${PLACEHOLDER_ROOT}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for executable in docker helm; do
  if ! command -v "${executable}" >/dev/null 2>&1; then
    echo "error: ${executable} is required for deployment-static validation" >&2
    exit 1
  fi
done
docker compose version >/dev/null
docker buildx version >/dev/null

# Compose interpolation is intentionally evaluated with short-lived, inert
# placeholders. The file is never printed and is removed by the EXIT trap.
# Using a temporary project directory also satisfies compose-level env_file
# references without reading a developer's repo-local .env.
umask 077
PLACEHOLDERS=(
  "ANTHROPIC_API_KEY=placeholder"
  "BR_MCP_AUTH_TOKEN=placeholder"
  "BR_MCP_TOKEN_PEPPER=placeholder"
  "BR_MODEL_API_KEY=placeholder"
  "DATABASE_URL=postgresql://postgres@postgres:5432/brain_researcher"
  "DEEPSEEK_API_KEY=placeholder"
  "GEMINI_API_KEY=placeholder"
  "GITHUB_REPOSITORY=example/brain-researcher"
  "GITHUB_SHA=0000000000000000000000000000000000000000"
  "GRAFANA_ADMIN_PASSWORD=placeholder"
  "GRAFANA_ADMIN_USER=placeholder"
  "GRAFANA_PASSWORD=placeholder"
  "JWT_SECRET_KEY=placeholder"
  "LITELLM_MASTER_KEY=placeholder"
  "NEO4J_PASSWORD=placeholder"
  "NEXTAUTH_SECRET=placeholder"
  "NEXT_PUBLIC_AUTH_MODE=placeholder"
  "NEXT_PUBLIC_NICLIP_API=https://example.invalid"
  "NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder"
  "NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS=placeholder"
  "NEXT_PUBLIC_SUPABASE_URL=https://example.invalid"
  "OPENAI_API_KEY=placeholder"
  "PAGERDUTY_SERVICE_KEY=placeholder"
  "PGBOUNCER_AUTH_FILE=/dev/null"
  "POSTGRES_PASSWORD=placeholder"
  "REDIS_PASSWORD=placeholder"
  "REGISTRY=ghcr.io"
  "SLACK_API_URL=https://example.invalid"
  "SMTP_PASSWORD=placeholder"
  "SUPABASE_ANON_KEY=placeholder"
  "SUPABASE_OAUTH_PROVIDERS=placeholder"
  "SUPABASE_SERVICE_ROLE_KEY=placeholder"
  "SUPABASE_URL=https://example.invalid"
  "TEST_NEO4J_PASSWORD=placeholder"
  "TEST_OPENAI_API_KEY=placeholder"
)
printf '%s\n' "${PLACEHOLDERS[@]}" >"${PLACEHOLDER_ENV}"
set -a
# shellcheck disable=SC1090 -- generated above and removed by cleanup.
source "${PLACEHOLDER_ENV}"
set +a
export COMPOSE_PROJECT_NAME="brain-researcher-static-check"

compose_config() {
  local label="$1"
  shift
  echo "compose config: ${label}"
  docker compose \
    --project-directory "${PLACEHOLDER_ROOT}" \
    --env-file "${PLACEHOLDER_ENV}" \
    "$@" \
    config --quiet
}

compose_config \
  "supported local base file (parse only)" \
  -f "${REPO_ROOT}/docker-compose.yml"
compose_config \
  "base plus experimental CC overlay (parse only)" \
  -f "${REPO_ROOT}/docker-compose.yml" \
  -f "${REPO_ROOT}/docker-compose.cc-stack.yml"
compose_config \
  "standalone production file (experimental parse only)" \
  -f "${REPO_ROOT}/docker-compose.prod.yml"
compose_config \
  "standalone test file (experimental parse only)" \
  -f "${REPO_ROOT}/infrastructure/docker/compose/docker-compose.override.test.yml"
compose_config \
  "standalone production override (experimental parse only)" \
  -f "${REPO_ROOT}/infrastructure/docker/compose/docker-compose.override.prod.yml"
compose_config \
  "standalone swarm file (experimental parse only)" \
  -f "${REPO_ROOT}/infrastructure/docker/compose/docker-compose.override.swarm.yml"
compose_config \
  "standalone CI file (experimental parse only)" \
  -f "${REPO_ROOT}/infrastructure/docker/compose/docker-compose.ci.yml"
compose_config \
  "standalone monitoring file (experimental parse only)" \
  -f "${REPO_ROOT}/infrastructure/monitoring/service_stack/docker-compose.monitoring.yml"

echo "Dockerfile check: root multi-stage image contract"
docker buildx build --check --file "${REPO_ROOT}/Dockerfile" "${REPO_ROOT}"

CHART="${REPO_ROOT}/infrastructure/k8s/helm/brain-researcher"
echo "Helm lint/template: experimental render-only chart"
helm lint --strict "${CHART}"
helm template brain-researcher-static "${CHART}" \
  --set mcp.enabled=true >/dev/null

echo "deployment-static validation: PASS"
