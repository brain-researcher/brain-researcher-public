type CookieEntry = {
  name: string
  value: string
}

type CookieReader = {
  get: (name: string) => { value: string } | undefined
  getAll: () => CookieEntry[]
}

const readCookie = (cookies: CookieReader, name: string): string | null => {
  const value = cookies.get(name)?.value?.trim()
  return value ? value : null
}

const readChunkedCookie = (cookies: CookieReader, name: string): string | null => {
  const direct = readCookie(cookies, name)
  if (direct) return direct

  const prefix = `${name}.`
  const chunked = cookies
    .getAll()
    .map((entry) => {
      if (!entry.name.startsWith(prefix)) return null
      const suffix = entry.name.slice(prefix.length)
      const index = Number.parseInt(suffix, 10)
      if (!Number.isFinite(index) || index < 0) return null
      return { index, value: entry.value }
    })
    .filter((entry): entry is { index: number; value: string } => Boolean(entry))
    .sort((left, right) => left.index - right.index)

  if (!chunked.length) return null
  return chunked.map((entry) => entry.value).join('')
}

export const readNextAuthSessionToken = (cookies: CookieReader): string | null => {
  return (
    readChunkedCookie(cookies, '__Secure-next-auth.session-token') ||
    readChunkedCookie(cookies, '__Host-next-auth.session-token') ||
    readChunkedCookie(cookies, 'next-auth.session-token')
  )
}

export const readBestBearerTokenFromCookies = (cookies: CookieReader): string | null => {
  return readCookie(cookies, 'br_access_token') || readNextAuthSessionToken(cookies)
}
