#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

REPO_ROOT="${BR_MCP_REPO_ROOT:-${DEFAULT_REPO_ROOT}}"
ENV_FILE="${BR_MCP_ENV_FILE:-${REPO_ROOT}/.env}"
BASHRC_FILE="${BR_MCP_BASHRC_FILE:-${HOME:-}/.bashrc}"

_trim_whitespace() {
  local value="${1}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

_strip_surrounding_quotes() {
  local value="${1}"
  if [[ ${#value} -ge 2 ]]; then
    local first_char="${value:0:1}"
    local last_char="${value: -1}"
    if [[ "${first_char}" == '"' && "${last_char}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${first_char}" == "'" && "${last_char}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s' "${value}"
}

_extract_token_from_file() {
  local source_file="${1}"
  [[ -f "${source_file}" ]] || return 1

  local line value
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?BR_MCP_TOKEN[[:space:]]*=' "${source_file}" | tail -n 1 || true)"
  [[ -n "${line}" ]] || return 1

  value="${line#*=}"
  value="${value%%#*}"
  value="$(_trim_whitespace "${value}")"
  value="$(_strip_surrounding_quotes "${value}")"
  [[ -n "${value}" ]] || return 1

  printf '%s\n' "${value}"
}

if [[ -n "${BR_MCP_TOKEN:-}" ]]; then
  printf '%s\n' "${BR_MCP_TOKEN}"
  exit 0
fi

if token="$(_extract_token_from_file "${ENV_FILE}")"; then
  printf '%s\n' "${token}"
  exit 0
fi

if [[ -n "${HOME:-}" ]] && token="$(_extract_token_from_file "${BASHRC_FILE}")"; then
  printf '%s\n' "${token}"
  exit 0
fi

{
  echo "Unable to resolve BR_MCP_TOKEN."
  echo "Checked sources in order:"
  echo "1) environment variable BR_MCP_TOKEN"
  echo "2) ${ENV_FILE}"
  if [[ -n "${HOME:-}" ]]; then
    echo "3) ${BASHRC_FILE}"
  else
    echo "3) HOME is not set, skipped ~/.bashrc"
  fi
  echo "Set BR_MCP_TOKEN in your shell or add BR_MCP_TOKEN=... to .env."
} >&2

exit 1
