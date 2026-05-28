#!/usr/bin/env bash
# Download + load the public KG dump from a GitHub Release.
#
# Usage:
#   scripts/oss/download_public_kg.sh [VERSION] [TARGET_DIR]
# Defaults:
#   VERSION    = v0.1.0
#   TARGET_DIR = ./data/neo4j-dumps
#
# After download, the script verifies sha256 and (if neo4j-admin is on
# PATH or docker is available) loads into the local Neo4j instance.

set -euo pipefail

VERSION="${1:-v0.1.0}"
TARGET_DIR="${2:-./data/neo4j-dumps}"
GH_REPO="${GH_REPO:-zjc062/brain-researcher-public}"
BASE_URL="https://github.com/${GH_REPO}/releases/download/${VERSION}"

mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

dump="kg-public-${VERSION}.dump"
manifest="kg-public-${VERSION}.manifest.json"
sha="kg-public-${VERSION}.dump.sha256"

echo "[1/4] downloading from ${BASE_URL}"
for f in "$dump" "$manifest" "$sha"; do
  if [[ -f "$f" ]]; then
    echo "  $f already present; skipping"
    continue
  fi
  curl -fL -o "$f" "${BASE_URL}/$f"
done

echo "[2/4] verifying sha256"
sha256sum -c "$sha"

echo "[3/4] inspecting manifest"
if command -v jq >/dev/null 2>&1; then
  jq '{extractor_version, pii_profile, cypher_sha256,
       node_count: (.counts.kept | to_entries | map(.value) | add),
       labels: (.counts.kept | keys)}' "$manifest"
else
  head -20 "$manifest"
fi

echo "[4/4] loading into Neo4j"
if command -v neo4j-admin >/dev/null 2>&1; then
  echo "  using local neo4j-admin"
  neo4j-admin database load --from-path="$PWD" --overwrite-destination=true neo4j
elif docker compose ps neo4j >/dev/null 2>&1; then
  echo "  using docker compose neo4j service"
  docker compose stop neo4j
  docker run --rm \
    -v "$(realpath ../neo4j):/data" \
    -v "$PWD:/dumps:ro" \
    neo4j:5.20 \
    neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j
  docker compose start neo4j
  echo "  Neo4j restarted. Wait ~15s, then query to verify."
else
  echo "  no neo4j-admin and no docker compose neo4j service found"
  echo "  manually run: neo4j-admin database load --from-path=$PWD neo4j"
  exit 0
fi
echo "Done."
