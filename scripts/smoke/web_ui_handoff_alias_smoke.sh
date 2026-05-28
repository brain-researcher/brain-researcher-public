#!/usr/bin/env bash
set -euo pipefail

# Focused web-ui handoff smoke: alias canonicalization, plan-check handoff packs,
# and dataset detail modal behavior. This does not launch real workflows.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR/apps/web-ui"

npx vitest --run \
  tests/unit/lib/workflow-template-aliases.spec.ts \
  tests/unit/api/plan.checks.routes.spec.ts \
  src/components/datasets/__tests__/dataset-detail-view.test.tsx
