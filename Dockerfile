# ==========================================
# Stage 1: Build Web UI (Node.js)
# ==========================================
FROM node:20-alpine AS node-builder
WORKDIR /app
COPY apps/web-ui/package.json apps/web-ui/package-lock.json ./
RUN npm install
COPY apps/web-ui ./
# Build Next.js app (requires some fake env vars to pass validation during build)
ENV NEXT_PUBLIC_AGENT_URL=http://localhost:8000
ENV NEXT_PUBLIC_NEUROKG_URL=http://localhost:5000
RUN npm run build -- --no-lint

# ==========================================
# Stage 2: Python Base (Common)
# ==========================================
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install common system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    make \
    git \
    libsqlite3-dev \
    pkg-config \
    libcairo2-dev \
    libffi-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Set common environment variables
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

# Copy project files
COPY pyproject.toml README.md ./
COPY packages/brain-researcher/src ./src
COPY configs ./configs
COPY scripts ./scripts
COPY contracts ./contracts

# Install base dependencies including CLI
RUN pip install --no-cache-dir -e .

# Create necessary directories
RUN mkdir -p data/neurokg/db data/neurokg/logs

# Create non-root user
RUN addgroup --gid 1000 appgroup && \
    adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser && \
    chown -R appuser:appgroup /app

# ==========================================
# Stage 3: BR-KG Service
# ==========================================
FROM base AS neurokg

# Install BR-KG specific dependencies
RUN pip install --no-cache-dir -e ".[neurokg]"

# Bake the default English model into the image so Finder avoids runtime fallback.
RUN python -m spacy download en_core_web_sm

# BR-KG service imports GraphQL support via `strawberry`.
RUN pip install --no-cache-dir "strawberry-graphql>=0.219.0"

# BR-KG enhanced API uses Redis client.
RUN pip install --no-cache-dir "redis>=5.0.0"

# BR-KG falls back to fakeredis when Redis is unavailable.
RUN pip install --no-cache-dir "fakeredis>=2.23.0"

# Avoid importing optional heavy CLI command groups during service startup.
ENV BR_SKIP_HEAVY_COMMANDS=1

USER appuser
EXPOSE 5000

# Use CLI to launch (matches launch_services_clean.sh 'br serve kg')
CMD ["brain-researcher", "serve", "kg", "--port", "5000", "--host", "0.0.0.0"]

# ==========================================
# Stage 3.5: Apptainer Runtime Binary
# ==========================================
FROM ghcr.io/apptainer/apptainer:1.3.6 AS apptainer-runtime

# ==========================================
# Stage 3.6: Conda Runtime (FitLins / Brain Researcher env)
# ==========================================
FROM mambaorg/micromamba:1.5.10 AS conda-runtime

USER root
COPY infrastructure/deployment/conda/agent-env.yml /tmp/agent-env.yml
RUN micromamba create -y -n brain_researcher -f /tmp/agent-env.yml && \
    micromamba run -n brain_researcher pip install --no-deps "fitlins==0.11.0" && \
    micromamba clean -a -y

# ==========================================
# Stage 4: Agent (Unified Gateway)
# ==========================================
FROM base AS agent

# Install runtime deps for Apptainer execution.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    libseccomp2 \
    squashfuse \
    fuse2fs \
    libgtk-3-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    freeglut3-dev \
    libwebkit2gtk-4.1-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libsdl2-dev \
    libnotify-dev \
    libsm-dev \
    libgl1-mesa-dev \
    libglu1-mesa-dev \
    libusb-1.0-0-dev \
    portaudio19-dev \
    libasound2-dev \
    && npm install -g --omit=dev "bids-validator@1.14.7" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Copy the full Apptainer runtime tree so config/libexec paths remain valid.
COPY --from=apptainer-runtime /opt/apptainer /opt/apptainer
RUN ln -sf /opt/apptainer/bin/apptainer /usr/bin/apptainer && \
    ln -sf /opt/apptainer/bin/apptainer /usr/bin/singularity

# Copy conda environment (includes fitlins CLI + deps).
COPY --from=conda-runtime /opt/conda/envs/brain_researcher /opt/conda/envs/brain_researcher
RUN ln -sf /opt/conda/envs/brain_researcher/bin/fitlins /usr/local/bin/fitlins

# Install agent deps plus the psyflow-backed behavior-task extra because
# MCP tool_execute is delegated to the agent in production.
RUN pip install --no-cache-dir -e ".[agent,behavior-task]"
# Ensure sqlite-backed queue runtime dependency is always present.
# This prevents silent fallback to MemoryJobStore in production.
RUN pip install --no-cache-dir "aiosqlite>=0.20.0"

RUN pip install --no-cache-dir "passlib[bcrypt]>=1.7.4"

# Install uvicorn for ASGI serving
RUN pip install uvicorn

ENV APPTAINER_CACHEDIR=/tmp/apptainer-cache
ENV APPTAINER_TMPDIR=/tmp/apptainer-tmp
ENV SINGULARITY_CACHEDIR=/tmp/apptainer-cache
ENV APPTAINER_CONFDIR=/opt/apptainer/etc/apptainer

USER appuser
EXPOSE 8000

# Use the Agent ASGI app for the default runtime image.
CMD ["sh", "-c", "uvicorn brain_researcher.services.agent.asgi:app --host 0.0.0.0 --port ${PORT:-8000}"]
# ==========================================
# Stage 5: MCP Service
# ==========================================
FROM base AS mcp

# MCP shares the agent-facing orchestration/tool surface, but behavior-task
# execution is delegated to the agent runtime instead of running psyflow
# locally inside the MCP container.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    latexmk \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-pictures \
    texlive-science \
    && npm install -g --omit=dev "bids-validator@1.14.7" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -e ".[agent]"

ENV BR_MCP_TRANSPORT=streamable-http
ENV BR_MCP_HOST=0.0.0.0
ENV BR_MCP_PORT=7000
ENV BR_MCP_MOUNT_PATH=/mcp

USER appuser
EXPOSE 7000

CMD ["python", "-m", "brain_researcher.services.mcp.server"]

# ==========================================
# Stage 6: UI Dashboard (Node.js Runtime)
# ==========================================
FROM node:20-alpine AS ui

WORKDIR /app

# Install production dependencies only
COPY --chown=node:node apps/web-ui/package.json apps/web-ui/package-lock.json ./
RUN npm install --production

# Copy built artifacts from builder
COPY --from=node-builder --chown=node:node /app/.next ./.next
COPY --from=node-builder --chown=node:node /app/public ./public
COPY --from=node-builder --chown=node:node /app/next.config.js ./next.config.js
# Some next.js deployments need source files for image optimization etc, but .next is usually enough
# We also need the start script logic
COPY --chown=node:node apps/web-ui/scripts ./scripts
# Ship dataset catalog for server-side catalog search fallback.
COPY --chown=node:node configs/datasets /configs/datasets

# Setup user (Reuse existing node user from base image to avoid CID 1000 collision)
RUN chown node:node /app
USER node

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "start"]

# ==========================================
# Stage 7: CLI / Dev
# ==========================================
FROM base AS cli
RUN pip install --no-cache-dir -e ".[all]"
USER appuser
ENTRYPOINT ["brain-researcher"]
CMD ["--help"]
