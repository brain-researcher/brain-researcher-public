type LooseRecord = Record<string, unknown>

const NIFTI_EXTENSION_PATTERN = /\.nii(\.gz)?$/i
const PRIORITY_NAME_PATTERNS = [
  /zstat/i,
  /tstat/i,
  /stat/i,
  /cope/i,
  /contrast/i,
  /map/i,
  /(^|[^a-z0-9])z([^a-z0-9]|$)/i,
  /(^|[^a-z0-9])t([^a-z0-9]|$)/i,
]

const asRecord = (value: unknown): LooseRecord | null =>
  value && typeof value === 'object' ? (value as LooseRecord) : null

const asTrimmedString = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

const stripQueryAndHash = (value: string): string =>
  value.split('#', 1)[0]?.split('?', 1)[0] ?? value

const matchesNiftiExtension = (value: string | null): boolean => {
  if (!value) {
    return false
  }

  return NIFTI_EXTENSION_PATTERN.test(stripQueryAndHash(value))
}

const normalizeFormat = (value: unknown): string | null => {
  const normalized = asTrimmedString(value)
  return normalized ? normalized.toLowerCase() : null
}

export const extractArtifactUrl = (artifact: unknown): string | null => {
  const record = asRecord(artifact)
  if (!record) {
    return null
  }

  return (
    asTrimmedString(record.download_url) ??
    asTrimmedString(record.url) ??
    asTrimmedString(record.path) ??
    asTrimmedString(record.href)
  )
}

export const extractArtifactName = (artifact: unknown): string | null => {
  const record = asRecord(artifact)
  if (!record) {
    return null
  }

  return (
    asTrimmedString(record.name) ??
    asTrimmedString(record.filename) ??
    asTrimmedString(record.label)
  )
}

const extractArtifactFormat = (artifact: unknown): string | null => {
  const record = asRecord(artifact)
  if (!record) {
    return null
  }

  const metadata = asRecord(record.metadata)
  const meta = asRecord(record.meta)

  return (
    normalizeFormat(record.format) ??
    normalizeFormat(metadata?.format) ??
    normalizeFormat(meta?.format)
  )
}

const scoreArtifactName = (artifact: unknown): number => {
  const name = extractArtifactName(artifact) ?? extractArtifactUrl(artifact) ?? ''
  const normalized = name.toLowerCase()

  return PRIORITY_NAME_PATTERNS.reduce((score, pattern) => {
    return score + (pattern.test(normalized) ? 1 : 0)
  }, 0)
}

export const isBrainMapArtifact = (artifact: unknown): boolean => {
  const url = extractArtifactUrl(artifact)
  if (!url) {
    return false
  }

  if (matchesNiftiExtension(url) || matchesNiftiExtension(extractArtifactName(artifact))) {
    return true
  }

  const format = extractArtifactFormat(artifact)
  return format === 'nifti'
}

export const pickPreferredBrainMapArtifact = <T>(artifacts: readonly T[] | null | undefined): T | null => {
  if (!artifacts || artifacts.length === 0) {
    return null
  }

  let bestArtifact: T | null = null
  let bestScore = -1

  for (const artifact of artifacts) {
    if (!isBrainMapArtifact(artifact)) {
      continue
    }

    const score = scoreArtifactName(artifact)
    if (score > bestScore) {
      bestArtifact = artifact
      bestScore = score
    }
  }

  return bestArtifact
}
