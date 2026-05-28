const DEFAULT_KG_BASE = 'http://localhost:5000'

const SKIPPED_PREFIX_SEGMENTS = new Set(['api', 'kg', 'neurokg'])

export function resolveKgBaseUrl(): string {
  const configuredBase =
    process.env.BR_KG_URL ||
    process.env.BR_NEUROKG_URL ||
    process.env.KG_BASE_URL ||
    process.env.NEUROKG_BASE_URL ||
    process.env.KG_URL ||
    process.env.NEUROKG_URL ||
    process.env.KG_API ||
    process.env.NEUROKG_API ||
    (process.env.KG_HOST
      ? `http://${process.env.KG_HOST}:${process.env.KG_PORT || '5000'}`
      : null) ||
    (process.env.NEUROKG_HOST
      ? `http://${process.env.NEUROKG_HOST}:${process.env.NEUROKG_PORT || '5000'}`
      : null)
  if (configuredBase) {
    return configuredBase.replace(/\/$/, '')
  }

  return DEFAULT_KG_BASE
}

export function normalizeKgSubpath(path: string | string[] | undefined): string {
  if (!path) return ''

  const rawSegments = Array.isArray(path)
    ? path
    : path.split('/')

  const segments = rawSegments
    .flatMap((segment) => segment.split('/'))
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0)

  while (segments.length > 0 && SKIPPED_PREFIX_SEGMENTS.has(segments[0])) {
    segments.shift()
  }

  return segments.join('/')
}
