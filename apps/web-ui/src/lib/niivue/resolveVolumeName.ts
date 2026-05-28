const FILENAME_PARAM = 'filename'

const FILENAME_REGEX = /filename\*=(?:UTF-8''|utf-8'')([^;]+)|filename="([^"]+)"|filename=([^;]+)/i

const EXTENSION_REGEX = /\.(nii(\.(gz|bz2|zst))?|mgz|mgh|hdr|img)$/i

const stripQuotes = (value: string) => value.replace(/^"|"$/g, '').trim()

const ensureExtension = (name: string, fallbackExt = '.nii.gz') => {
  const trimmed = stripQuotes(name)
  if (!trimmed) {
    return fallbackExt
  }
  return EXTENSION_REGEX.test(trimmed) ? trimmed : `${trimmed}${fallbackExt}`
}

export function resolveVolumeName(url: string, response?: Response, fallback = 'volume.nii.gz') {
  let pathSegment = ''

  try {
    const parsed = new URL(url ?? '', 'http://local.test')
    const queryValue = parsed.searchParams.get(FILENAME_PARAM)
    if (queryValue) {
      return ensureExtension(decodeURIComponent(queryValue))
    }
    pathSegment = parsed.pathname.split('/').pop() || ''
  } catch {
    // Ignore malformed URLs and try other strategies
  }

  const disposition = response?.headers?.get('content-disposition') ?? ''
  if (disposition) {
    const match = FILENAME_REGEX.exec(disposition)
    const candidate = decodeURIComponent(stripQuotes(match?.[1] || match?.[2] || match?.[3] || ''))
    if (candidate) {
      return ensureExtension(candidate)
    }
  }

  if (pathSegment) {
    return ensureExtension(decodeURIComponent(pathSegment))
  }

  return ensureExtension(fallback)
}
