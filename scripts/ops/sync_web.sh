#!/usr/bin/env bash
set -euo pipefail

# Legacy static export sync helper for apps/web-ui.
# This does not affect the live Next.js service started by `br serve web`.
# Usage:
#   scripts/ops/sync_web.sh [out|dist|build]
#   scripts/ops/sync_web.sh --dest /tmp/web-ui-export [out|dist|build]
#   scripts/ops/sync_web.sh --legacy-br-kg-web-public [out|dist|build]

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_DIR="$ROOT_DIR/apps/web-ui"
DEST_DIR="${BR_SYNC_WEB_DEST:-$ROOT_DIR/artifacts/web-ui-static-export}"

FALLBACK_BUILD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      DEST_DIR="$2"
      shift 2
      ;;
    --legacy-br-kg-web-public)
      DEST_DIR="$ROOT_DIR/src/brain_researcher/services/br_kg/web_public"
      shift
      ;;
    *)
      FALLBACK_BUILD="$1"
      shift
      ;;
  esac
done

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Web UI directory not found: $SRC_DIR" >&2
  exit 1
fi

if [[ -d "$SRC_DIR/out" ]]; then
  BUILD_DIR="$SRC_DIR/out"
elif [[ -d "$SRC_DIR/dist" ]]; then
  BUILD_DIR="$SRC_DIR/dist"
elif [[ -d "$SRC_DIR/build" ]]; then
  BUILD_DIR="$SRC_DIR/build"
elif [[ -n "$FALLBACK_BUILD" && -d "$SRC_DIR/$FALLBACK_BUILD" ]]; then
  BUILD_DIR="$SRC_DIR/$FALLBACK_BUILD"
else
  echo "No build output found under $SRC_DIR (expected one of: out/, dist/, build/)." >&2
  exit 1
fi

echo "Legacy static export helper"
echo "Source:      $BUILD_DIR"
echo "Destination: $DEST_DIR"
echo "Syncing $BUILD_DIR -> $DEST_DIR"

rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"

cp -R "$BUILD_DIR"/* "$DEST_DIR"/

echo "Done."
