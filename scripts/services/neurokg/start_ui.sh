#!/usr/bin/env bash
set -euo pipefail

echo "Dash UI has been retired. Starting the canonical Next.js Web UI instead."
echo "BR-KG Explorer is served from http://localhost:3000/en/kg/explore"
exec br serve web --host 0.0.0.0 --port "${PORT:-3000}"
