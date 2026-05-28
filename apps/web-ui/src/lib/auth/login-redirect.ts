export function sanitizeAuthCallbackUrl(value?: string | null): string {
  const candidate = typeof value === 'string' ? value.trim() : ''
  if (!candidate) return '/'
  if (!candidate.startsWith('/')) return '/'
  if (candidate.startsWith('/auth')) return '/'
  return candidate
}

export function buildAuthLoginHref(callbackUrl?: string | null): string {
  const safe = sanitizeAuthCallbackUrl(callbackUrl)
  return `/auth/login?callbackUrl=${encodeURIComponent(safe)}`
}
