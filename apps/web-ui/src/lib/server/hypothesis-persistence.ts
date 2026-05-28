export type HypothesisStoreBackend = 'memory' | 'redis' | 'postgres' | 'dual'

export type HypothesisPersistenceArea =
  | 'local_session'
  | 'local_run'
  | 'run_store_run'
  | 'run_store_session_runs'
  | 'run_store_intent'

type PersistenceSelection = {
  requested: HypothesisStoreBackend
  useRedis: boolean
  usePostgres: boolean
  autoSelected: boolean
}

type PersistenceState = {
  fingerprint: string
  requested: HypothesisStoreBackend
  autoSelected: boolean
  useRedis: boolean
  usePostgres: boolean
  redisUrl: string | null
  postgresUrl: string | null
  cache: Map<string, string>
  redisClient: any | null
  pgPool: any | null
  initPromise: Promise<void> | null
  warned: Set<string>
  ttlSeconds: number
}

declare global {
  // eslint-disable-next-line no-var
  var __brHypothesisPersistenceState: PersistenceState | undefined
}

const POSTGRES_TABLE = 'br_hypothesis_store_kv'

function trimNullable(value: string | undefined | null): string | null {
  const normalized = typeof value === 'string' ? value.trim() : ''
  return normalized || null
}

function parseRequestedBackend(value: string | undefined): HypothesisStoreBackend | null {
  const normalized = trimNullable(value)?.toLowerCase()
  if (!normalized) return null
  if (normalized === 'memory') return 'memory'
  if (normalized === 'redis') return 'redis'
  if (normalized === 'postgres') return 'postgres'
  if (normalized === 'dual') return 'dual'
  return null
}

function resolveRedisUrl(): string | null {
  return (
    trimNullable(process.env.HYPOTHESIS_STORE_REDIS_URL) ||
    trimNullable(process.env.HYPOTHESIS_REDIS_URL) ||
    trimNullable(process.env.REDIS_URL)
  )
}

function resolvePostgresUrl(): string | null {
  return (
    trimNullable(process.env.HYPOTHESIS_STORE_POSTGRES_URL) ||
    trimNullable(process.env.HYPOTHESIS_POSTGRES_URL) ||
    trimNullable(process.env.POSTGRES_URL) ||
    trimNullable(process.env.DATABASE_URL)
  )
}

function resolveTtlSeconds(): number {
  const raw = trimNullable(process.env.HYPOTHESIS_SESSION_TTL_SEC)
  const parsed = raw ? Number(raw) : NaN
  if (Number.isFinite(parsed) && parsed > 0) {
    return Math.trunc(parsed)
  }
  return 60 * 60 * 24 * 30
}

function resolveSelection(args: {
  requestedRaw: string | undefined
  redisUrl: string | null
  postgresUrl: string | null
}): PersistenceSelection {
  const requested = parseRequestedBackend(args.requestedRaw)

  if (!requested) {
    const canDual = Boolean(args.redisUrl && args.postgresUrl)
    return {
      requested: canDual ? 'dual' : 'memory',
      useRedis: canDual,
      usePostgres: canDual,
      autoSelected: true,
    }
  }

  if (requested === 'memory') {
    return {
      requested,
      useRedis: false,
      usePostgres: false,
      autoSelected: false,
    }
  }

  if (requested === 'redis') {
    return {
      requested,
      useRedis: Boolean(args.redisUrl),
      usePostgres: false,
      autoSelected: false,
    }
  }

  if (requested === 'postgres') {
    return {
      requested,
      useRedis: false,
      usePostgres: Boolean(args.postgresUrl),
      autoSelected: false,
    }
  }

  return {
    requested,
    useRedis: Boolean(args.redisUrl),
    usePostgres: Boolean(args.postgresUrl),
    autoSelected: false,
  }
}

function describeResolvedBackend(state: PersistenceState): HypothesisStoreBackend {
  if (state.useRedis && state.usePostgres) return 'dual'
  if (state.useRedis) return 'redis'
  if (state.usePostgres) return 'postgres'
  return 'memory'
}

function buildFingerprint(args: {
  requestedRaw: string | undefined
  redisUrl: string | null
  postgresUrl: string | null
  ttlSeconds: number
}): string {
  return [
    args.requestedRaw || '',
    args.redisUrl || '',
    args.postgresUrl || '',
    String(args.ttlSeconds),
  ].join('::')
}

function warnOnce(state: PersistenceState, key: string, message: string): void {
  if (state.warned.has(key)) return
  state.warned.add(key)
  // eslint-disable-next-line no-console
  console.warn(`[hypothesis-persistence] ${message}`)
}

async function dynamicImportModule(moduleName: string): Promise<any | null> {
  try {
    if (moduleName === 'redis') {
      return await import('redis')
    }
    if (moduleName === 'pg') {
      return await import('pg')
    }
    return null
  } catch {
    return null
  }
}

async function closeState(state: PersistenceState): Promise<void> {
  await Promise.all([
    (async () => {
      if (!state.redisClient) return
      try {
        if (typeof state.redisClient.quit === 'function') {
          await state.redisClient.quit()
        } else if (typeof state.redisClient.disconnect === 'function') {
          state.redisClient.disconnect()
        }
      } catch {
        // Best-effort cleanup.
      }
    })(),
    (async () => {
      if (!state.pgPool) return
      try {
        if (typeof state.pgPool.end === 'function') {
          await state.pgPool.end()
        }
      } catch {
        // Best-effort cleanup.
      }
    })(),
  ])
}

function createState(args: {
  fingerprint: string
  selection: PersistenceSelection
  redisUrl: string | null
  postgresUrl: string | null
  ttlSeconds: number
}): PersistenceState {
  return {
    fingerprint: args.fingerprint,
    requested: args.selection.requested,
    autoSelected: args.selection.autoSelected,
    useRedis: args.selection.useRedis,
    usePostgres: args.selection.usePostgres,
    redisUrl: args.redisUrl,
    postgresUrl: args.postgresUrl,
    cache: new Map<string, string>(),
    redisClient: null,
    pgPool: null,
    initPromise: null,
    warned: new Set<string>(),
    ttlSeconds: args.ttlSeconds,
  }
}

function getState(): PersistenceState {
  const requestedRaw = process.env.HYPOTHESIS_STORE_BACKEND
  const redisUrl = resolveRedisUrl()
  const postgresUrl = resolvePostgresUrl()
  const ttlSeconds = resolveTtlSeconds()
  const selection = resolveSelection({ requestedRaw, redisUrl, postgresUrl })
  const fingerprint = buildFingerprint({ requestedRaw, redisUrl, postgresUrl, ttlSeconds })

  const existing = globalThis.__brHypothesisPersistenceState
  if (existing && existing.fingerprint === fingerprint) {
    return existing
  }

  if (existing) {
    void closeState(existing)
  }

  const next = createState({
    fingerprint,
    selection,
    redisUrl,
    postgresUrl,
    ttlSeconds,
  })

  if (selection.requested === 'redis' && !selection.useRedis) {
    warnOnce(next, 'redis-url-missing', 'Requested redis backend but no redis URL found. Falling back to memory cache.')
  }
  if (selection.requested === 'postgres' && !selection.usePostgres) {
    warnOnce(next, 'postgres-url-missing', 'Requested postgres backend but no postgres URL found. Falling back to memory cache.')
  }
  if (
    selection.requested === 'dual' &&
    !selection.useRedis &&
    !selection.usePostgres
  ) {
    warnOnce(next, 'dual-url-missing', 'Requested dual backend but neither redis nor postgres URL was found. Falling back to memory cache.')
  }

  globalThis.__brHypothesisPersistenceState = next
  return next
}

async function ensureRedisClient(state: PersistenceState): Promise<void> {
  if (!state.useRedis || state.redisClient) return
  if (!state.redisUrl) {
    state.useRedis = false
    return
  }

  const redisModule = await dynamicImportModule('redis')
  const createClient = redisModule?.createClient
  if (typeof createClient !== 'function') {
    state.useRedis = false
    warnOnce(
      state,
      'redis-module-missing',
      'Redis backend selected but package "redis" is not installed. Redis persistence disabled.',
    )
    return
  }

  try {
    const client = createClient({ url: state.redisUrl })
    if (typeof client.on === 'function') {
      client.on('error', (error: unknown) => {
        const message = error instanceof Error ? error.message : String(error)
        warnOnce(state, `redis-runtime-${message}`, `Redis error: ${message}`)
      })
    }
    if (!client.isOpen && typeof client.connect === 'function') {
      await client.connect()
    }
    state.redisClient = client
  } catch (error) {
    state.useRedis = false
    const message = error instanceof Error ? error.message : 'unknown redis init error'
    warnOnce(state, 'redis-connect-failed', `Failed to initialize Redis client: ${message}`)
  }
}

async function ensurePostgresPool(state: PersistenceState): Promise<void> {
  if (!state.usePostgres || state.pgPool) return
  if (!state.postgresUrl) {
    state.usePostgres = false
    return
  }

  const pgModule = await dynamicImportModule('pg')
  const Pool = pgModule?.Pool || pgModule?.default?.Pool
  if (typeof Pool !== 'function') {
    state.usePostgres = false
    warnOnce(
      state,
      'pg-module-missing',
      'Postgres backend selected but package "pg" is not installed. Postgres persistence disabled.',
    )
    return
  }

  try {
    const pool = new Pool({ connectionString: state.postgresUrl })
    await pool.query(`
      CREATE TABLE IF NOT EXISTS ${POSTGRES_TABLE} (
        store_key TEXT PRIMARY KEY,
        value_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `)
    state.pgPool = pool
  } catch (error) {
    state.usePostgres = false
    const message = error instanceof Error ? error.message : 'unknown postgres init error'
    warnOnce(state, 'pg-init-failed', `Failed to initialize Postgres pool: ${message}`)
  }
}

async function ensureRemoteClients(state: PersistenceState): Promise<void> {
  if (!state.useRedis && !state.usePostgres) return
  if (state.initPromise) {
    await state.initPromise
    return
  }

  state.initPromise = (async () => {
    await Promise.all([ensureRedisClient(state), ensurePostgresPool(state)])
  })().finally(() => {
    state.initPromise = null
  })

  await state.initPromise
}

function buildStoreKey(area: HypothesisPersistenceArea, id: string): string {
  return `hypothesis:${area}:${id}`
}

function safeStringify(value: unknown): string | null {
  try {
    return JSON.stringify(value)
  } catch {
    return null
  }
}

function safeParseJson<T>(value: string | null): T | null {
  if (!value) return null
  try {
    return JSON.parse(value) as T
  } catch {
    return null
  }
}

async function writeRedis(state: PersistenceState, key: string, serialized: string): Promise<void> {
  if (!state.useRedis || !state.redisClient) return
  try {
    if (state.ttlSeconds > 0) {
      await state.redisClient.set(key, serialized, { EX: state.ttlSeconds })
    } else {
      await state.redisClient.set(key, serialized)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown redis write error'
    warnOnce(state, `redis-write-${message}`, `Redis write failed: ${message}`)
  }
}

async function writePostgres(
  state: PersistenceState,
  key: string,
  serialized: string,
): Promise<void> {
  if (!state.usePostgres || !state.pgPool) return
  try {
    await state.pgPool.query(
      `
        INSERT INTO ${POSTGRES_TABLE} (store_key, value_json, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (store_key)
        DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
      `,
      [key, serialized],
    )
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown postgres write error'
    warnOnce(state, `pg-write-${message}`, `Postgres write failed: ${message}`)
  }
}

async function readRedis(state: PersistenceState, key: string): Promise<string | null> {
  if (!state.useRedis || !state.redisClient) return null
  try {
    const value = await state.redisClient.get(key)
    return typeof value === 'string' ? value : null
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown redis read error'
    warnOnce(state, `redis-read-${message}`, `Redis read failed: ${message}`)
    return null
  }
}

async function readPostgres(state: PersistenceState, key: string): Promise<string | null> {
  if (!state.usePostgres || !state.pgPool) return null
  try {
    const result = await state.pgPool.query(
      `SELECT value_json FROM ${POSTGRES_TABLE} WHERE store_key = $1 LIMIT 1`,
      [key],
    )
    const row = result?.rows?.[0]
    if (!row) return null
    const raw = row.value_json
    if (typeof raw === 'string') return raw
    return safeStringify(raw)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown postgres read error'
    warnOnce(state, `pg-read-${message}`, `Postgres read failed: ${message}`)
    return null
  }
}

export function persistHypothesisStoreRecord(
  area: HypothesisPersistenceArea,
  id: string,
  value: unknown,
): void {
  const normalizedId = (id || '').trim()
  if (!normalizedId) return

  const state = getState()
  const key = buildStoreKey(area, normalizedId)
  const serialized = safeStringify(value)
  if (!serialized) {
    warnOnce(state, `serialize-failed-${key}`, `Failed to serialize ${key} for persistence.`)
    return
  }

  state.cache.set(key, serialized)

  void (async () => {
    await ensureRemoteClients(state)
    await Promise.all([
      writeRedis(state, key, serialized),
      writePostgres(state, key, serialized),
    ])
  })()
}

export async function loadHypothesisStoreRecord<T>(
  area: HypothesisPersistenceArea,
  id: string,
): Promise<T | null> {
  const normalizedId = (id || '').trim()
  if (!normalizedId) return null

  const state = getState()
  const key = buildStoreKey(area, normalizedId)

  const cached = state.cache.get(key)
  if (typeof cached === 'string') {
    return safeParseJson<T>(cached)
  }

  await ensureRemoteClients(state)

  let source: 'redis' | 'postgres' | null = null
  let serialized = await readRedis(state, key)
  if (serialized) {
    source = 'redis'
  }

  if (!serialized) {
    serialized = await readPostgres(state, key)
    if (serialized) {
      source = 'postgres'
    }
  }

  if (!serialized) return null

  state.cache.set(key, serialized)

  if (source === 'postgres' && state.useRedis && state.redisClient) {
    void writeRedis(state, key, serialized)
  }

  return safeParseJson<T>(serialized)
}

export async function __resetHypothesisPersistenceForTests(): Promise<void> {
  const state = globalThis.__brHypothesisPersistenceState
  if (!state) return
  await closeState(state)
  delete globalThis.__brHypothesisPersistenceState
}

export function getHypothesisPersistenceInfo(): {
  requested: HypothesisStoreBackend
  resolved: HypothesisStoreBackend
  auto_selected: boolean
  redis_configured: boolean
  postgres_configured: boolean
} {
  const state = getState()
  return {
    requested: state.requested,
    resolved: describeResolvedBackend(state),
    auto_selected: state.autoSelected,
    redis_configured: Boolean(state.redisUrl),
    postgres_configured: Boolean(state.postgresUrl),
  }
}
