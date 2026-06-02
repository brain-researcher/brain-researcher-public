#!/usr/bin/env bash
set -euo pipefail

CONF_PATH=${1:-/etc/neo4j/neo4j.conf}
HEAP_SIZE=${NEO4J_HEAP_SIZE:-8g}
PAGECACHE_SIZE=${NEO4J_PAGECACHE_SIZE:-6g}
TX_TIMEOUT=${NEO4J_TX_TIMEOUT:-0}

if [[ $EUID -ne 0 ]]; then
  echo "[tune_neo4j_memory] Please run as root (e.g. sudo $0)" >&2
  exit 1
fi

if [[ ! -f "$CONF_PATH" ]]; then
  echo "[tune_neo4j_memory] Config file not found: $CONF_PATH" >&2
  exit 1
fi

backup="${CONF_PATH}.bak.$(date +%Y%m%d%H%M%S)"
cp "$CONF_PATH" "$backup"
echo "[tune_neo4j_memory] Backup created at $backup"

declare -A settings=(
  [server.memory.heap.initial_size]="$HEAP_SIZE"
  [server.memory.heap.max_size]="$HEAP_SIZE"
  [server.memory.pagecache.size]="$PAGECACHE_SIZE"
  [dbms.transaction.timeout]="$TX_TIMEOUT"
)

for key in "${!settings[@]}"; do
  value="${settings[$key]}"
  if grep -Eq "^#?${key}=" "$CONF_PATH"; then
    sed -i "s|^#\?${key}=.*|${key}=${value}|" "$CONF_PATH"
  else
    printf n%s=%sn "$key" "$value" >> "$CONF_PATH"
  fi
done

echo "[tune_neo4j_memory] Updated $CONF_PATH"

echo "[tune_neo4j_memory] Restarting neo4j.service"
systemctl restart neo4j.service
systemctl --no-pager --full status neo4j.service
