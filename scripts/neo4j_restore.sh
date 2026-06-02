#!/usr/bin/env bash
set -euo pipefail

# Restore a Neo4j database dump into the running docker-compose service.
# Usage: ./scripts/neo4j_restore.sh [container_name] [dump_path_on_host]
#
# - container_name: docker container name (default: brain-researcher-neo4j)
# - dump_path_on_host: path to .dump on the host (default: ./backups/neo4j/latest.dump if present)
#
# The database is stopped inside the container during restore to ensure consistency.

CONTAINER_NAME="${1:-brain-researcher-neo4j}"
DUMP_HOST_PATH="${2:-}"

if [[ -z "${DUMP_HOST_PATH}" ]]; then
  # pick the newest dump under backups
  DUMP_HOST_PATH="$(ls -1t ./backups/neo4j/*.dump 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${DUMP_HOST_PATH}" ]]; then
  echo "No dump file specified and none found in ./backups/neo4j" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; install Docker/Compose first." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Container ${CONTAINER_NAME} is not running. Start it with 'docker compose up -d neo4j'." >&2
  exit 1
fi

if [[ ! -f "${DUMP_HOST_PATH}" ]]; then
  echo "Dump file not found: ${DUMP_HOST_PATH}" >&2
  exit 1
fi

BASENAME="$(basename "${DUMP_HOST_PATH}")"

echo "Copying dump into container..."
docker cp "${DUMP_HOST_PATH}" "${CONTAINER_NAME}:/data/backups/${BASENAME}"

echo "Stopping Neo4j inside container..."
docker exec "${CONTAINER_NAME}" neo4j stop

echo "Restoring ${BASENAME} into database 'neo4j'..."
docker exec "${CONTAINER_NAME}" neo4j-admin database restore neo4j "/data/backups/${BASENAME}" --overwrite-destination=true

echo "Starting Neo4j inside container..."
docker exec "${CONTAINER_NAME}" neo4j start

echo "Restore complete."
