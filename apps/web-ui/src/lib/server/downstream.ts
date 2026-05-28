import { NextRequest } from 'next/server'

import {
  readBestBearerTokenFromCookies,
  readNextAuthSessionToken,
} from '@/lib/auth/cookie-tokens'

const stripTrailingSlash = (value: string) => value.replace(/\/$/, '')

export function resolveAgentBaseUrl(): string {
  // Agent owns direct execution/chat/file surfaces used behind public
  // Next.js routes such as `/api/chat`, `/api/files`, `/api/datasets`,
  // and `/api/threads`. The public `/api/runs` surface is compatibility-only
  // and still proxies to Agent for legacy callers.
  const explicitInternal = process.env.BR_AGENT_URL
  if (explicitInternal) {
    return stripTrailingSlash(explicitInternal)
  }

  const base =
    process.env.AGENT_BASE_URL ||
    process.env.AGENT_URL ||
    (process.env.AGENT_HOST
      ? `http://${process.env.AGENT_HOST}:${process.env.AGENT_PORT || '8000'}`
      : null)
  if (base) {
    return stripTrailingSlash(base)
  }

  return 'http://localhost:8000'
}

const normalizeMountPath = (value: string | undefined): string => {
  const trimmed = String(value || '').trim()
  if (!trimmed || trimmed === '/') return ''
  return trimmed.startsWith('/') ? trimmed.replace(/\/$/, '') : `/${trimmed.replace(/\/$/, '')}`
}

const applyMountPath = (base: string, mountPath: string): string => {
  if (!mountPath || base.endsWith(mountPath)) return stripTrailingSlash(base)
  return stripTrailingSlash(`${stripTrailingSlash(base)}${mountPath}`)
}

export function resolveOrchestratorBaseUrl(): string {
  // Orchestrator owns `/run` plus the canonical job/analysis resources behind
  // public routes such as `/api/jobs/*`, `/api/analyses/*`, `/api/share/*`,
  // `/api/credits/*`, and `/api/user/notifications/*`.
  const explicitOrchestrator =
    process.env.BR_ORCHESTRATOR_URL ||
    process.env.ORCHESTRATOR_BASE_URL ||
    process.env.ORCHESTRATOR_API ||
    process.env.ORCHESTRATOR_URL ||
    process.env.ORCHESTRATOR_API_URL
  const mountPath = normalizeMountPath(process.env.ORCHESTRATOR_MOUNT_PATH)

  // Do not infer Orchestrator from Agent or legacy compatibility flags.
  // Use an explicit Orchestrator URL when mounted under a non-root path.

  if (explicitOrchestrator) {
    let base = stripTrailingSlash(String(explicitOrchestrator))
    if (base.endsWith('/api')) base = base.slice(0, -4)
    return applyMountPath(base, mountPath)
  }

  const host = process.env.ORCHESTRATOR_HOST || 'localhost'
  const port = process.env.ORCHESTRATOR_PORT || '3001'
  return applyMountPath(`http://${host}:${port}`, mountPath)
}

export function forwardAuthHeaders(req: NextRequest): Headers {
  const headers = new Headers()

  const auth = req.headers.get('authorization')
  const cookie = req.headers.get('cookie')
  const workspaceId = req.headers.get('x-workspace-id')
  if (auth) headers.set('authorization', auth)
  if (cookie) headers.set('cookie', cookie)
  if (workspaceId) headers.set('x-workspace-id', workspaceId)

  // If the browser is authenticated via NextAuth cookies, upstream services still expect
  // a bearer token. Forward the session token as Authorization when available.
  if (!headers.get('authorization')) {
    // Prefer NextAuth session token for internal service calls; fall back to
    // legacy br_access_token for compatibility.
    const token =
      readNextAuthSessionToken(req.cookies) || readBestBearerTokenFromCookies(req.cookies)
    if (token) {
      headers.set('authorization', `Bearer ${token}`)
    }
  }

  return headers
}
