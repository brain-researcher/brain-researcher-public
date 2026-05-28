export const DEFAULT_CODING_STREAM_PLACEHOLDER = 'Running coding agent...'

function getPersistedContent(
  previousContent: string | null | undefined,
  placeholder: string,
): string | null {
  if (typeof previousContent !== 'string') return null
  if (!previousContent.trim()) return null
  if (previousContent === placeholder) return null
  return previousContent
}

export function extractCodingStreamText(data: unknown): string | null {
  if (typeof data === 'string') {
    return data.length > 0 ? data : null
  }
  if (!data || typeof data !== 'object') {
    return null
  }

  const record = data as Record<string, unknown>
  const candidates = [record.answer, record.content, record.text, record.message]
  for (const value of candidates) {
    if (typeof value === 'string' && value.length > 0) {
      return value
    }
  }

  return null
}

export function getNextCodingStreamContent(params: {
  event: string
  data: unknown
  previousContent?: string | null
  placeholder?: string
}): string | null {
  const {
    event,
    data,
    previousContent,
    placeholder = DEFAULT_CODING_STREAM_PLACEHOLDER,
  } = params
  const priorContent = getPersistedContent(previousContent, placeholder)
  const text = extractCodingStreamText(data)

  if (event === 'token') {
    if (!text) return priorContent
    return `${priorContent || ''}${text}`
  }

  if (event === 'result' || event === 'message') {
    return text || priorContent
  }

  if (event === 'done' || event === 'stream_end') {
    return text || priorContent
  }

  return priorContent
}
