#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ENV_FILE="${REPO_ROOT}/.env"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"

TOKEN="${BR_NEW_MCP_TOKEN:-}"
AUTH_MODE_OVERRIDE=""
PEPPER_OVERRIDE=""
PEPPER_VERSION_OVERRIDE=""
REDIS_PREFIX_OVERRIDE=""
REDIS_URL_OVERRIDE=""
USER_ID_OVERRIDE=""
NO_RESTART=0
NO_VERIFY=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Rotate local MCP PAT token and reseed local Redis in one command.

Usage:
  scripts/ops/rotate_local_mcp_token.sh --token <brk_token> [options]

Options:
  -t, --token <token>               New MCP PAT token (format: brk_<kid>.<secret>)
      --env-file <path>             Env file to update (default: ./.env)
      --compose-file <path>         Compose file for restart (default: ./docker-compose.prod.yml)
      --auth-mode <mode>            BR_MCP_AUTH_MODE (default: token_or_jwt)
      --pepper <hex64>              BR_MCP_TOKEN_PEPPER (default: current .env value)
      --pepper-version <version>    BR_MCP_TOKEN_PEPPER_VERSION (default: v1)
      --redis-prefix <prefix>       BR_MCP_TOKEN_REDIS_PREFIX (default: mcp_token)
      --redis-url <url>             REDIS_URL used by local docker services (default: redis://redis:6379/0)
      --user-id <user_id>           Force user_id for Redis seed (optional)
      --no-restart                  Do not restart redis/mcp/orchestrator
      --no-verify                   Skip HTTP verification checks
      --dry-run                     Print actions without writing/restarting
  -h, --help                        Show this help

Notes:
  - This updates keys in the target env file:
    BR_MCP_TOKEN, BR_MCP_AUTH_MODE, BR_MCP_TOKEN_PEPPER,
    BR_MCP_TOKEN_PEPPER_VERSION, BR_MCP_TOKEN_REDIS_PREFIX, REDIS_URL
  - Redis seed keys:
    <prefix>:kid:<kid>, <prefix>:user:<user_id>
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

info() {
  echo "[rotate-mcp-token] $*"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--token)
      [[ $# -ge 2 ]] || die "--token requires a value"
      TOKEN="$2"
      shift 2
      ;;
    --env-file)
      [[ $# -ge 2 ]] || die "--env-file requires a value"
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-file)
      [[ $# -ge 2 ]] || die "--compose-file requires a value"
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --auth-mode)
      [[ $# -ge 2 ]] || die "--auth-mode requires a value"
      AUTH_MODE_OVERRIDE="$2"
      shift 2
      ;;
    --pepper)
      [[ $# -ge 2 ]] || die "--pepper requires a value"
      PEPPER_OVERRIDE="$2"
      shift 2
      ;;
    --pepper-version)
      [[ $# -ge 2 ]] || die "--pepper-version requires a value"
      PEPPER_VERSION_OVERRIDE="$2"
      shift 2
      ;;
    --redis-prefix)
      [[ $# -ge 2 ]] || die "--redis-prefix requires a value"
      REDIS_PREFIX_OVERRIDE="$2"
      shift 2
      ;;
    --redis-url)
      [[ $# -ge 2 ]] || die "--redis-url requires a value"
      REDIS_URL_OVERRIDE="$2"
      shift 2
      ;;
    --user-id)
      [[ $# -ge 2 ]] || die "--user-id requires a value"
      USER_ID_OVERRIDE="$2"
      shift 2
      ;;
    --no-restart)
      NO_RESTART=1
      shift
      ;;
    --no-verify)
      NO_VERIFY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -f "$ENV_FILE" ]] || die "Env file not found: $ENV_FILE"
[[ -f "$COMPOSE_FILE" ]] || die "Compose file not found: $COMPOSE_FILE"

if [[ -z "$TOKEN" ]]; then
  read -r -p "New BR_MCP_TOKEN: " TOKEN
fi

[[ "$TOKEN" =~ ^brk_[A-Za-z0-9_-]+\.[A-Za-z0-9._~-]+$ ]] \
  || die "Invalid token format; expected brk_<kid>.<secret>"

env_get() {
  local file="$1"
  local key="$2"
  awk -F= -v k="$key" '$1==k {print substr($0, index($0, "=")+1)}' "$file" | tail -n 1
}

resolve_value() {
  local override="$1"
  local shell_val="$2"
  local file_val="$3"
  local default_val="$4"
  if [[ -n "$override" ]]; then
    echo "$override"
  elif [[ -n "$shell_val" ]]; then
    echo "$shell_val"
  elif [[ -n "$file_val" ]]; then
    echo "$file_val"
  else
    echo "$default_val"
  fi
}

upsert_env() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { replaced=0 }
    $0 ~ ("^" k "=") {
      if (!replaced) {
        print k "=" v
        replaced=1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print k "=" v
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

AUTH_MODE="$(resolve_value "$AUTH_MODE_OVERRIDE" "${BR_MCP_AUTH_MODE:-}" "$(env_get "$ENV_FILE" "BR_MCP_AUTH_MODE")" "token_or_jwt")"
PEPPER="$(resolve_value "$PEPPER_OVERRIDE" "${BR_MCP_TOKEN_PEPPER:-}" "$(env_get "$ENV_FILE" "BR_MCP_TOKEN_PEPPER")" "")"
PEPPER_VERSION="$(resolve_value "$PEPPER_VERSION_OVERRIDE" "${BR_MCP_TOKEN_PEPPER_VERSION:-}" "$(env_get "$ENV_FILE" "BR_MCP_TOKEN_PEPPER_VERSION")" "v1")"
REDIS_PREFIX="$(resolve_value "$REDIS_PREFIX_OVERRIDE" "${BR_MCP_TOKEN_REDIS_PREFIX:-}" "$(env_get "$ENV_FILE" "BR_MCP_TOKEN_REDIS_PREFIX")" "mcp_token")"
REDIS_URL="$(resolve_value "$REDIS_URL_OVERRIDE" "${REDIS_URL:-}" "$(env_get "$ENV_FILE" "REDIS_URL")" "redis://redis:6379/0")"

[[ "$AUTH_MODE" == "token" || "$AUTH_MODE" == "token_or_jwt" || "$AUTH_MODE" == "jwt" || "$AUTH_MODE" == "none" || "$AUTH_MODE" == "auto" ]] \
  || die "Invalid auth mode: $AUTH_MODE"

[[ -n "$PEPPER" ]] || die "BR_MCP_TOKEN_PEPPER is required (pass --pepper or set it in .env)"
[[ "$PEPPER" =~ ^[0-9a-fA-F]{64}$ ]] || die "BR_MCP_TOKEN_PEPPER must be 64 hex chars"

if [[ -f "${REPO_ROOT}/.env.local" ]]; then
  for key in BR_MCP_TOKEN BR_MCP_AUTH_MODE BR_MCP_TOKEN_PEPPER BR_MCP_TOKEN_PEPPER_VERSION BR_MCP_TOKEN_REDIS_PREFIX REDIS_URL; do
    if rg -q "^${key}=" "${REPO_ROOT}/.env.local"; then
      warn ".env.local contains ${key}; it may override ${ENV_FILE} in docker compose env_file order."
    fi
  done
fi

KID="${TOKEN#brk_}"
KID="${KID%%.*}"
SAFE_TOKEN_HEAD="${TOKEN%%.*}"

info "Target env file: ${ENV_FILE}"
info "Token kid: ${SAFE_TOKEN_HEAD}"
info "Resolved auth_mode=${AUTH_MODE} redis_prefix=${REDIS_PREFIX} redis_url=${REDIS_URL}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  info "DRY RUN: would update env keys and reseed Redis."
  exit 0
fi

upsert_env "$ENV_FILE" "BR_MCP_TOKEN" "$TOKEN"
upsert_env "$ENV_FILE" "BR_MCP_AUTH_MODE" "$AUTH_MODE"
upsert_env "$ENV_FILE" "BR_MCP_TOKEN_PEPPER" "$PEPPER"
upsert_env "$ENV_FILE" "BR_MCP_TOKEN_PEPPER_VERSION" "$PEPPER_VERSION"
upsert_env "$ENV_FILE" "BR_MCP_TOKEN_REDIS_PREFIX" "$REDIS_PREFIX"
upsert_env "$ENV_FILE" "REDIS_URL" "$REDIS_URL"

if [[ "$NO_RESTART" -eq 0 ]]; then
  info "Recreating local services: redis, mcp, orchestrator"
  docker compose -f "$COMPOSE_FILE" up -d --no-build --no-deps --force-recreate redis mcp orchestrator
else
  info "Skipping service restart (--no-restart)."
fi

info "Seeding local Redis token record via mcp container"
docker exec -i \
  -e NEW_BR_MCP_TOKEN="$TOKEN" \
  -e BR_MCP_TOKEN_PEPPER="$PEPPER" \
  -e BR_MCP_TOKEN_PEPPER_VERSION="$PEPPER_VERSION" \
  -e BR_MCP_TOKEN_REDIS_PREFIX="$REDIS_PREFIX" \
  -e REDIS_URL="$REDIS_URL" \
  ${USER_ID_OVERRIDE:+-e BR_MCP_FORCE_USER_ID="$USER_ID_OVERRIDE"} \
  brain-researcher-mcp python - <<'PY'
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

import redis

token = os.environ["NEW_BR_MCP_TOKEN"].strip()
if not token.startswith("brk_") or "." not in token:
    raise SystemExit("invalid token format")

kid, secret = token[4:].split(".", 1)
parts = kid.split("_")

forced_user_id = (os.getenv("BR_MCP_FORCE_USER_ID") or "").strip()
if forced_user_id:
    user_id = forced_user_id
elif len(parts) >= 4 and parts[-2].isdigit():
    user_id = "_".join(parts[:-2])
elif len(parts) >= 2:
    user_id = "_".join(parts[:2])
else:
    raise SystemExit("cannot derive user_id from kid; pass --user-id")

pepper = bytes.fromhex(os.environ["BR_MCP_TOKEN_PEPPER"].strip())
pepper_version = (os.getenv("BR_MCP_TOKEN_PEPPER_VERSION") or "v1").strip() or "v1"
prefix = (os.getenv("BR_MCP_TOKEN_REDIS_PREFIX") or "mcp_token").strip() or "mcp_token"
redis_url = os.environ["REDIS_URL"].strip()

r = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
digest = hmac.new(pepper, secret.encode("utf-8"), hashlib.sha256).hexdigest()
created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

kid_key = f"{prefix}:kid:{kid}"
user_key = f"{prefix}:user:{user_id}"
r.hset(
    kid_key,
    mapping={
        "kid": kid,
        "user_id": user_id,
        "digest": digest,
        "enabled": "1",
        "created_at": created_at,
        "expires_at": "",
        "pepper_version": pepper_version,
    },
)
r.hdel(kid_key, "revoked_at")
r.set(user_key, kid)

print(
    json.dumps(
        {
            "kid_key": kid_key,
            "user_key": user_key,
            "user_id": user_id,
            "enabled": "1",
            "pepper_version": pepper_version,
        },
        ensure_ascii=False,
    )
)
PY

if [[ "$NO_VERIFY" -eq 0 ]]; then
  info "Running local verification checks"
  NO_AUTH_CODE="$(curl -sS -o /tmp/mcp_no_auth.json -w '%{http_code}' http://localhost:7000/mcp/healthz || true)"
  AUTH_HEALTH_CODE="$(curl -sS -o /tmp/mcp_auth_health.json -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" http://localhost:7000/mcp/healthz || true)"
  AUTH_ROOT_CODE="$(curl -sS -o /tmp/mcp_auth_root.json -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" http://localhost:7000/mcp || true)"

  info "Verify /mcp/healthz no token -> ${NO_AUTH_CODE} (expect 401)"
  info "Verify /mcp/healthz with token -> ${AUTH_HEALTH_CODE} (expect non-401)"
  info "Verify /mcp with token -> ${AUTH_ROOT_CODE} (expect 406)"

  if [[ "$NO_AUTH_CODE" != "401" ]]; then
    die "Unexpected no-token response: ${NO_AUTH_CODE}"
  fi
  if [[ "$AUTH_HEALTH_CODE" == "401" ]]; then
    die "Token still rejected on /mcp/healthz"
  fi
  if [[ "$AUTH_ROOT_CODE" != "406" ]]; then
    warn "Unexpected /mcp auth response: ${AUTH_ROOT_CODE} (body: $(cat /tmp/mcp_auth_root.json))"
  fi
fi

info "Done. Token rotated and Redis reseeded for kid ${KID}."
