import crypto from 'crypto'

const base64UrlEncode = (value: Buffer | string) => {
  const buf = Buffer.isBuffer(value) ? value : Buffer.from(value, 'utf-8')
  return buf
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
}

const resolveJwtSecret = () => process.env.JWT_SECRET_KEY || process.env.NEXTAUTH_SECRET || ''

const resolveJwtIssuer = () => {
  const explicit =
    process.env.BR_AGENT_JWT_ISSUER ||
    process.env.BR_AUTH_JWT_ISSUER ||
    process.env.SUPABASE_JWT_ISSUER ||
    process.env.BR_JWT_ISSUER ||
    ''
  if (explicit) return explicit
  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || ''
  return supabaseUrl ? `${supabaseUrl.replace(/\/$/, '')}/auth/v1` : ''
}

const resolveJwtAudience = () => {
  const raw =
    process.env.BR_AGENT_JWT_AUDIENCE ||
    process.env.BR_AUTH_JWT_AUDIENCE ||
    process.env.SUPABASE_JWT_AUDIENCE ||
    process.env.BR_JWT_AUDIENCE ||
    ''
  return raw
    ? raw
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
    : []
}

export function issueInternalJwt(args: {
  subject: string
  ttlSeconds?: number
  role?: string
  provider?: string
  email?: string
  name?: string
}): string | null {
  const secret = resolveJwtSecret()
  if (!secret) return null

  const subject = args.subject.trim()
  if (!subject) return null

  const now = Math.floor(Date.now() / 1000)
  const ttlSeconds = Math.max(60, Math.min(args.ttlSeconds ?? 15 * 60, 24 * 60 * 60))

  const headerB64 = base64UrlEncode(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload: Record<string, unknown> = {
    sub: subject,
    iat: now,
    exp: now + ttlSeconds,
    role: args.role ?? 'service',
    provider: args.provider ?? 'internal',
  }

  if (args.email) payload.email = args.email
  if (args.name) payload.name = args.name

  const issuer = resolveJwtIssuer()
  if (issuer) payload.iss = issuer

  const audiences = resolveJwtAudience()
  if (audiences.length === 1) payload.aud = audiences[0]
  if (audiences.length > 1) payload.aud = audiences

  const payloadB64 = base64UrlEncode(JSON.stringify(payload))
  const signingInput = `${headerB64}.${payloadB64}`
  const sigB64 = base64UrlEncode(crypto.createHmac('sha256', secret).update(signingInput).digest())
  return `${signingInput}.${sigB64}`
}

