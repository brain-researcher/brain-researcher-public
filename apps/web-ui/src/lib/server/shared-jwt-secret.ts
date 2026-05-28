import fs from 'fs'
import path from 'path'

type DotenvLookup = {
  key: string
  value: string
}

const readDotenv = (filepath: string): DotenvLookup[] => {
  try {
    if (!fs.existsSync(filepath)) return []
    const content = fs.readFileSync(filepath, 'utf-8')
    return content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#'))
      .map((line) => {
        const eq = line.indexOf('=')
        if (eq <= 0) return null
        const key = line.slice(0, eq).trim()
        let value = line.slice(eq + 1).trim()
        if (
          (value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))
        ) {
          value = value.slice(1, -1)
        }
        return key ? { key, value } : null
      })
      .filter((entry): entry is DotenvLookup => Boolean(entry))
  } catch {
    return []
  }
}

const findRepoRoot = (startDir: string): string | null => {
  let current = startDir
  for (let i = 0; i < 10; i += 1) {
    const hasGit = fs.existsSync(path.join(current, '.git'))
    const hasPyproject = fs.existsSync(path.join(current, 'pyproject.toml'))
    if (hasGit || hasPyproject) return current
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  return null
}

const getRepoDotenvValue = (key: string): string | null => {
  const repoRoot = findRepoRoot(process.cwd())
  if (!repoRoot) return null

  for (const filename of ['.env.local', '.env']) {
    const filepath = path.join(repoRoot, filename)
    const entries = readDotenv(filepath)
    const hit = entries.find((entry) => entry.key === key)?.value
    if (hit) return hit
  }

  return null
}

export const resolveSharedJwtSecret = (): string | undefined => {
  const debug =
    process.env.BR_AUTH_DEBUG === '1' ||
    process.env.BR_AUTH_DEBUG === 'true' ||
    process.env.NEXTAUTH_DEBUG === '1' ||
    process.env.NEXTAUTH_DEBUG === 'true'
  const shouldWarnMismatch = process.env.NODE_ENV === 'production' || debug

  const explicitJwtSecret = process.env.JWT_SECRET_KEY
  if (debug) {
    // eslint-disable-next-line no-console
    console.log('[auth] JWT_SECRET_KEY from env:', explicitJwtSecret ? 'set' : 'not set')
  }

  const nextAuthSecret = process.env.NEXTAUTH_SECRET
  if (debug) {
    // eslint-disable-next-line no-console
    console.log('[auth] NEXTAUTH_SECRET from env:', nextAuthSecret ? 'set' : 'not set')
  }
  if (process.env.NODE_ENV === 'production') {
    return explicitJwtSecret || nextAuthSecret
  }

  const repoRoot = findRepoRoot(process.cwd())
  if (debug) {
    // eslint-disable-next-line no-console
    console.log('[auth] Repo root:', repoRoot, 'CWD:', process.cwd())
  }

  const repoSecret =
    getRepoDotenvValue('JWT_SECRET_KEY') ?? getRepoDotenvValue('NEXTAUTH_SECRET')
  if (debug) {
    // eslint-disable-next-line no-console
    console.log('[auth] Repo secret:', repoSecret ? 'found' : 'not found')
  }

  if (repoSecret && explicitJwtSecret && explicitJwtSecret !== repoSecret) {
    if (shouldWarnMismatch) {
      // eslint-disable-next-line no-console
      console.warn(
        '[auth] JWT_SECRET_KEY differs from repo-root JWT_SECRET_KEY; using repo-root secret for service compatibility.',
      )
    }
    return repoSecret
  }

  if (repoSecret && nextAuthSecret && nextAuthSecret !== repoSecret) {
    if (shouldWarnMismatch) {
      // eslint-disable-next-line no-console
      console.warn(
        '[auth] NEXTAUTH_SECRET differs from repo-root JWT_SECRET_KEY; using repo-root secret for service compatibility.',
      )
    }
    return repoSecret
  }

  if (explicitJwtSecret) return explicitJwtSecret
  if (repoSecret) return repoSecret
  if (nextAuthSecret) return nextAuthSecret

  // Dev convenience: allow local auth flows to run without env plumbing.
  // Do not rely on this in production.
  // eslint-disable-next-line no-console
  console.warn('[auth] JWT secret is not configured; using default dev secret.')
  return 'br-dev-secret'
}
