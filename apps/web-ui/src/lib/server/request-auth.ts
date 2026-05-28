import type { NextRequest } from 'next/server'
import { createRemoteJWKSet, decodeProtectedHeader, jwtVerify } from 'jose'

import {
  readBestBearerTokenFromCookies,
  readNextAuthSessionToken,
} from '@/lib/auth/cookie-tokens'
import { resolveSharedJwtSecret } from '@/lib/server/shared-jwt-secret'

const resolveJwtSecret = () => resolveSharedJwtSecret() || ''

const resolveSupabaseUrl = () =>
  process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || ''

const resolveJwksUrl = () => {
  const explicit =
    process.env.SUPABASE_JWKS_URL || process.env.BR_JWKS_URL || process.env.BR_AUTH_JWKS_URL
  if (explicit) return explicit
  const supabaseUrl = resolveSupabaseUrl()
  return supabaseUrl ? `${supabaseUrl.replace(/\/$/, '')}/auth/v1/keys` : ''
}

const resolveIssuer = () => {
  const explicit =
    process.env.SUPABASE_JWT_ISSUER || process.env.BR_JWT_ISSUER || process.env.BR_AUTH_JWT_ISSUER
  if (explicit) return explicit
  const supabaseUrl = resolveSupabaseUrl()
  return supabaseUrl ? `${supabaseUrl.replace(/\/$/, '')}/auth/v1` : ''
}

const resolveAudiences = () => {
  const raw =
    process.env.SUPABASE_JWT_AUDIENCE ||
    process.env.BR_JWT_AUDIENCE ||
    process.env.BR_AUTH_JWT_AUDIENCE
  return raw ? raw.split(',').map((value) => value.trim()).filter(Boolean) : []
}

const jwksCache = new Map<string, ReturnType<typeof createRemoteJWKSet>>()
const getRemoteJwks = (jwksUrl: string) => {
  const existing = jwksCache.get(jwksUrl)
  if (existing) return existing
  const jwks = createRemoteJWKSet(new URL(jwksUrl))
  jwksCache.set(jwksUrl, jwks)
  return jwks
}

const extractBearer = (value: string | null) => {
  if (!value) return null
  const trimmed = value.trim()
  return trimmed.toLowerCase().startsWith('bearer ') ? trimmed.slice(7).trim() : null
}

const getCandidateTokens = (req: NextRequest): string[] => {
  const tokens: string[] = []
  const authHeader = req.headers.get('authorization') || req.headers.get('Authorization')
  const bearer = extractBearer(authHeader)
  if (bearer) tokens.push(bearer)

  const brAccess = readBestBearerTokenFromCookies(req.cookies)
  if (brAccess) tokens.push(brAccess)

  const nextAuth = readNextAuthSessionToken(req.cookies)
  if (nextAuth) tokens.push(nextAuth)

  const seen = new Set<string>()
  return tokens.filter((token) => {
    if (seen.has(token)) return false
    seen.add(token)
    return true
  })
}

async function verifyToken(token: string): Promise<Record<string, unknown> | null> {
  try {
    const header = decodeProtectedHeader(token)
    const alg = String(header.alg || '').toUpperCase()
    const audiences = resolveAudiences()
    const issuer = resolveIssuer()

    if (alg.startsWith('HS')) {
      const secret = resolveJwtSecret()
      if (!secret) return null
      const { payload } = await jwtVerify(token, new TextEncoder().encode(secret), {
        algorithms: [alg],
      })
      return payload as Record<string, unknown>
    }

    const jwksUrl = resolveJwksUrl()
    if (!jwksUrl) return null
    const jwks = getRemoteJwks(jwksUrl)
    const { payload } = await jwtVerify(token, jwks, {
      algorithms: [alg || 'RS256'],
      audience: audiences.length ? audiences : undefined,
      issuer: issuer || undefined,
    })
    return payload as Record<string, unknown>
  } catch {
    return null
  }
}

export async function getVerifiedBearerToken(req: NextRequest): Promise<string | null> {
  const tokens = getCandidateTokens(req)
  for (const token of tokens) {
    const payload = await verifyToken(token)
    if (payload) {
      const orchestratorAccessToken = payload.orchestrator_access_token
      if (
        typeof orchestratorAccessToken === 'string' &&
        orchestratorAccessToken.trim()
      ) {
        return orchestratorAccessToken.trim()
      }
      return token
    }
  }
  return null
}

export async function getRequestAuthToken(req: NextRequest): Promise<Record<string, unknown> | null> {
  const tokens = getCandidateTokens(req)
  for (const token of tokens) {
    const payload = await verifyToken(token)
    if (payload) return payload
  }
  return null
}

export async function isRequestAuthenticated(req: NextRequest): Promise<boolean> {
  const token = await getRequestAuthToken(req)
  if (token) return true

  const isDev = process.env.NODE_ENV !== 'production'
  if (!isDev) return false

  const e2eAuth = req.cookies.get('br_e2e_auth')?.value === '1'
  if (!e2eAuth) return false

  const cookieToken = req.cookies.get('br_access_token')?.value?.trim()
  const bearerHeader = extractBearer(
    req.headers.get('authorization') || req.headers.get('Authorization'),
  )
  return Boolean(cookieToken || bearerHeader)
}
