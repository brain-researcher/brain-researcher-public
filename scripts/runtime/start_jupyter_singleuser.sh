#!/usr/bin/env bash
set -euo pipefail

python -m brain_researcher.integrations.notebook_intelligence.bootstrap \
  --write-extension-metadata \
  --write-user-config \
  --user-home "${HOME}"

exec "$@"
