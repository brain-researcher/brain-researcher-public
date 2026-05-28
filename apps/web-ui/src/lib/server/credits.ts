import { NextRequest } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { getRequestAuthToken } from '@/lib/server/request-auth'

export type CreditsIdentity = {
  workspaceId: string
  userId: string
}

export type CreditsBalancePayload = {
  workspace_id: string
  user_id: string
  balance: number
  balance_milli: number
  updated_at: string
}

export type CreditsReservationPayload = {
  reservation_id: string
  workspace_id: string
  user_id: string
  status: string
  amount: number
  amount_milli: number
  balance: number
  balance_milli: number
  created_at: string
  updated_at: string
  expires_at?: string | null
  idempotent?: boolean
}

function normalizeIdentityToken(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed || fallback
}

function firstIdentityClaim(payload: Record<string, unknown> | null, keys: string[]): string | null {
  for (const key of keys) {
    const value = payload?.[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

export async function resolveCreditsIdentity(
  req: NextRequest,
  input?: { workspaceId?: string | null; userId?: string | null },
): Promise<CreditsIdentity> {
  const authPayload = await getRequestAuthToken(req)
  const authenticatedWorkspaceId = firstIdentityClaim(authPayload, ['tenant_id', 'workspace_id'])
  const authenticatedUserId = firstIdentityClaim(authPayload, ['sub', 'user_id', 'email'])
  const workspaceId = normalizeIdentityToken(
    authenticatedWorkspaceId ??
      input?.workspaceId ??
      req.headers.get('x-workspace-id') ??
      req.headers.get('workspace-id'),
    'default',
  )
  const userId = normalizeIdentityToken(
    authenticatedUserId ??
      input?.userId ??
      req.headers.get('x-user-id') ??
      req.headers.get('user-id'),
    'default',
  )
  return { workspaceId, userId }
}

function buildCreditsUrl(path: string): string {
  const base = resolveOrchestratorBaseUrl()
  return `${base}${path}`
}

async function fetchCredits(
  req: NextRequest,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers)
  const auth = forwardAuthHeaders(req)
  auth.forEach((value, key) => headers.set(key, value))

  return fetch(buildCreditsUrl(path), {
    ...init,
    headers,
    cache: 'no-store',
  })
}

async function parseJson<T>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T
  } catch {
    return null
  }
}

export async function getCreditsBalance(
  req: NextRequest,
  identity: CreditsIdentity,
): Promise<CreditsBalancePayload | null> {
  const qs = new URLSearchParams({
    workspace_id: identity.workspaceId,
    user_id: identity.userId,
  })
  const response = await fetchCredits(req, `/api/credits/balance?${qs.toString()}`, {
    method: 'GET',
  })
  if (!response.ok) return null
  return parseJson<CreditsBalancePayload>(response)
}

export async function reserveCredits(
  req: NextRequest,
  identity: CreditsIdentity,
  amount: number,
  metadata?: Record<string, unknown>,
): Promise<{ ok: true; reservation: CreditsReservationPayload } | { ok: false; status: number; detail: string }> {
  const idempotencyKey = `reserve:${identity.workspaceId}:${identity.userId}:${Date.now()}:${Math.random()
    .toString(16)
    .slice(2)}`
  const response = await fetchCredits(req, '/api/credits/reservations', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      workspace_id: identity.workspaceId,
      user_id: identity.userId,
      amount,
      idempotency_key: idempotencyKey,
      metadata: metadata ?? {},
    }),
  })
  const payload = await parseJson<Record<string, unknown>>(response)
  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      detail:
        (typeof payload?.detail === 'string' && payload.detail) ||
        (typeof payload?.error === 'string' && payload.error) ||
        'Reservation failed',
    }
  }
  const reservationId =
    payload && typeof payload === 'object' && typeof payload.reservation_id === 'string'
      ? payload.reservation_id
      : null
  if (!reservationId) {
    return {
      ok: false,
      status: 502,
      detail: 'Invalid reservation response from credits service.',
    }
  }
  return { ok: true, reservation: payload as CreditsReservationPayload }
}

export async function commitCreditsReservation(
  req: NextRequest,
  reservationId: string,
  metadata?: Record<string, unknown>,
): Promise<boolean> {
  const response = await fetchCredits(req, `/api/credits/reservations/${encodeURIComponent(reservationId)}/commit`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ metadata: metadata ?? {} }),
  })
  return response.ok
}

export async function releaseCreditsReservation(
  req: NextRequest,
  reservationId: string,
  metadata?: Record<string, unknown>,
): Promise<boolean> {
  const response = await fetchCredits(req, `/api/credits/reservations/${encodeURIComponent(reservationId)}/release`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ metadata: metadata ?? {} }),
  })
  return response.ok
}

export function parseRuntimeToEstimatedMinutes(runtime: string | null | undefined): number | null {
  if (!runtime || typeof runtime !== 'string') return null
  const regex = /(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b/gi
  const minutes: number[] = []
  let match: RegExpExecArray | null = regex.exec(runtime)
  while (match) {
    const value = Number(match[1])
    const unit = (match[2] || '').toLowerCase()
    if (Number.isFinite(value) && value > 0) {
      if (unit.startsWith('h')) {
        minutes.push(value * 60)
      } else {
        minutes.push(value)
      }
    }
    match = regex.exec(runtime)
  }
  if (!minutes.length) return null
  return Math.max(...minutes)
}

export function estimateCreditsFromRuntime(
  runtime: string | null | undefined,
  options?: { variantsMultiplier?: number },
): number | null {
  const baseMinutes = parseRuntimeToEstimatedMinutes(runtime)
  if (baseMinutes == null) return null
  const multiplier =
    options?.variantsMultiplier && Number.isFinite(options.variantsMultiplier)
      ? Math.max(1, options.variantsMultiplier)
      : 1
  const adjustedMinutes = baseMinutes * multiplier
  return Math.max(1, Math.ceil(adjustedMinutes / 30))
}
