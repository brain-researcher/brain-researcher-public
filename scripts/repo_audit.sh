#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/audits"
OUT="$OUT_DIR/repo_audit_latest.md"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "$OUT_DIR"

# Header
echo "# Repo Audit Report" > "$OUT"
echo "" >> "$OUT"
echo "- Generated at (UTC): $TS" >> "$OUT"
echo "" >> "$OUT"

# Git info if available
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "## Git" >> "$OUT"
  echo "" >> "$OUT"
  echo "- Remote: \`$(git remote -v | head -n 1 | sed 's/`/\\`/g')\`" >> "$OUT" || true
  echo "- Branch: \`$(git rev-parse --abbrev-ref HEAD)\`" >> "$OUT"
  echo "- HEAD: \`$(git rev-parse --short HEAD)\`" >> "$OUT"
  echo "- Last commit: \`$(git log -1 --pretty=format:'%ad %an %s' --date=iso)\`" >> "$OUT"
  echo "" >> "$OUT"
  echo "### git status" >> "$OUT"
  echo '```' >> "$OUT"
  git status --porcelain=v1 >> "$OUT" || true
  echo '```' >> "$OUT"
  echo "" >> "$OUT"
fi

# Repo structure

echo "## Repository Structure" >> "$OUT"
echo "" >> "$OUT"
echo '```' >> "$OUT"
ls -la >> "$OUT"
echo '```' >> "$OUT"
echo "" >> "$OUT"

MODULES=("br-kg" "brain_researcher" "brain_reseacher" "mcp" "ui" "workflow" "frontend" "backend" "server" "apps" "packages")

echo "## Module Checks" >> "$OUT"
echo "" >> "$OUT"

for m in "${MODULES[@]}"; do
  if [ -d "$m" ]; then
    echo "### $m" >> "$OUT"
    echo "" >> "$OUT"

    # Key files
    for f in "README.md" "Dockerfile" "docker-compose.yml" "pyproject.toml" "requirements.txt" "package.json" "pnpm-lock.yaml" "package-lock.json" "yarn.lock" ".env.example" "openapi.yaml" "openapi.yml" ; do
      if [ -f "$m/$f" ]; then
        echo "- ✅ $f" >> "$OUT"
      fi
    done

    # Tests presence
    if [ -d "$m/tests" ] || [ -d "$m/test" ] || [ -d "$m/__tests__" ]; then
      echo "- ✅ tests directory present" >> "$OUT"
    else
      echo "- ⚠️ tests directory NOT found" >> "$OUT"
    fi

    # TODO/FIXME counts
    TODO_COUNT="$( (grep -RIn --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist --exclude-dir=build --exclude='*.lock' -E 'TODO|FIXME' "$m" 2>/dev/null || true) | wc -l | tr -d ' ')"
    echo "- TODO/FIXME hits: $TODO_COUNT" >> "$OUT"

    echo "" >> "$OUT"
  fi

done

echo "## CI / Workflows" >> "$OUT"
echo "" >> "$OUT"
if [ -d ".github/workflows" ]; then
  echo "- ✅ .github/workflows exists" >> "$OUT"
  echo "" >> "$OUT"
  echo '```' >> "$OUT"
  ls -la .github/workflows >> "$OUT"
  echo '```' >> "$OUT"
else
  echo "- ⚠️ .github/workflows NOT found" >> "$OUT"
fi
echo "" >> "$OUT"

echo "## Quick Risk Heuristics" >> "$OUT"
echo "" >> "$OUT"
echo "- If there is no Dockerfile for each runtime service: deployment risk ↑" >> "$OUT"
echo "- If no lockfiles: reproducibility risk ↑" >> "$OUT"
echo "- If no E2E tests: integration regression risk ↑" >> "$OUT"
echo "- If MCP tools are not allowlisted: security risk ↑" >> "$OUT"
echo "" >> "$OUT"

echo "Wrote $OUT"
