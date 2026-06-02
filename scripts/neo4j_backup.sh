#!/usr/bin/env bash
set -euo pipefail

# Simple Neo4j backup helper for the docker-compose service.
# Creates an offline dump inside the container under /data/backups
# and copies it to ./backups/neo4j on the host.

CONTAINER_NAME="${1:-brain-researcher-neo4j}"
DATABASE_NAME="${2:-neo4j}"
HOST_BACKUP_DIR="${3:-./backups/neo4j}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
BACKUP_FILENAME="${DATABASE_NAME}-${TIMESTAMP}.dump"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; install Docker/Compose first." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Container ${CONTAINER_NAME} is not running. Start it with 'docker compose up -d neo4j'." >&2
  exit 1
fi

# Ensure paths exist
docker exec "${CONTAINER_NAME}" mkdir -p /data/backups
mkdir -p "${HOST_BACKUP_DIR}"

echo "Stopping database inside container..."
docker exec "${CONTAINER_NAME}" neo4j stop || true

echo "Creating Neo4j dump for database '${DATABASE_NAME}' from container '${CONTAINER_NAME}'..."
docker exec "${CONTAINER_NAME}" neo4j-admin database dump --overwrite-destination=true --to-path=/data/backups "${DATABASE_NAME}"

echo "Starting database inside container..."
docker exec "${CONTAINER_NAME}" neo4j start || true

echo "Copying dump to host..."
docker cp "${CONTAINER_NAME}:/data/backups/${DATABASE_NAME}.dump" "${HOST_BACKUP_DIR}/${BACKUP_FILENAME}"

echo "Backup complete: ${HOST_BACKUP_DIR}/${BACKUP_FILENAME}"
