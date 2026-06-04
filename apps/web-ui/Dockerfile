# Build stage
FROM node:18-alpine AS builder

WORKDIR /app
ENV NEXT_OUTPUT_TRACING_ROOT=/app

# Copy package files (build context is repo root)
COPY apps/web-ui/package*.json ./
# Copy build-time scripts needed by npm postinstall hooks
COPY apps/web-ui/scripts/ ./scripts/

# Install dependencies deterministically for the build without running
# app-level postinstall hooks before the full source tree is present.
RUN npm install --include=dev --ignore-scripts

# Copy application code (build context is repo root)
COPY apps/web-ui/ .

# Restore Monaco assets after the full app tree has been copied.
RUN npm run sync:monaco
# Copy configs for static catalog data (workflows, datasets, tools)
COPY configs/ ./configs/
# Copy prompt/result artifacts used by demo replay pages
COPY docs/use_cases/brain_researcher_hybrid/ ./docs/use_cases/brain_researcher_hybrid/

# Build-time env for Next.js public vars (required for client bundle)
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS
ARG NEXT_PUBLIC_AUTH_MODE
ARG NEXT_PUBLIC_AGENT_API
ARG NEXT_PUBLIC_ORCHESTRATOR_URL
ARG NEXT_PUBLIC_BR_KG_API
ARG NEXT_PUBLIC_NICLIP_API
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_USE_API_PROXY
ARG NEXT_PUBLIC_ENABLE_STUDIO_BRAIN_VIEWER_BETA
ARG ORCHESTRATOR_HOST
ARG ORCHESTRATOR_PORT
ARG AGENT_HOST
ARG AGENT_PORT
ARG BR_KG_HOST
ARG BR_KG_PORT

ENV NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL}
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY}
ENV NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS=${NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS}
ENV NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE}
ENV NEXT_PUBLIC_AGENT_API=${NEXT_PUBLIC_AGENT_API}
ENV NEXT_PUBLIC_ORCHESTRATOR_URL=${NEXT_PUBLIC_ORCHESTRATOR_URL}
ENV NEXT_PUBLIC_BR_KG_API=${NEXT_PUBLIC_BR_KG_API}
ENV NEXT_PUBLIC_NICLIP_API=${NEXT_PUBLIC_NICLIP_API}
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}
ENV NEXT_PUBLIC_USE_API_PROXY=${NEXT_PUBLIC_USE_API_PROXY}
ENV NEXT_PUBLIC_ENABLE_STUDIO_BRAIN_VIEWER_BETA=${NEXT_PUBLIC_ENABLE_STUDIO_BRAIN_VIEWER_BETA}
ENV ORCHESTRATOR_HOST=${ORCHESTRATOR_HOST}
ENV ORCHESTRATOR_PORT=${ORCHESTRATOR_PORT}
ENV AGENT_HOST=${AGENT_HOST}
ENV AGENT_PORT=${AGENT_PORT}
ENV BR_KG_HOST=${BR_KG_HOST}
ENV BR_KG_PORT=${BR_KG_PORT}

# Build the Next.js application
RUN npm run build

# Production stage
FROM node:18-alpine AS runner

WORKDIR /app

# Create a non-root user
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001

# Copy built application from builder stage (standalone layout already includes runtime dependencies)
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
COPY --from=builder /app/configs ./configs
COPY --from=builder /app/docs ./docs

# Ensure non-root runtime user can read all assets
RUN chown -R nextjs:nodejs /app && chmod -R a+rX /app/configs /app/docs /app/public

# Set user
USER nextjs

# Expose port
EXPOSE 3000

# Set environment to production
ENV NODE_ENV production
ENV PORT 3000
ENV HOSTNAME 0.0.0.0
ENV PROJECT_ROOT /app

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://web-ui:3000/health', (r) => {const ok = r.statusCode >= 200 && r.statusCode < 400; process.exit(ok ? 0 : 1);}).on('error', () => process.exit(1))" || exit 1

# Start the application
CMD ["node", "server.js"]
