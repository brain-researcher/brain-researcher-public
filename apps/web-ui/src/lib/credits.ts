export const CREDITS_BALANCE_STORAGE_KEY = 'br:credits:balance'
export const CREDITS_UPDATED_AT_STORAGE_KEY = 'br:credits:updated_at'
export const API_USD_CREDITS_BALANCE_STORAGE_KEY = 'br:credits:api_usd:balance'
export const API_USD_CREDITS_UPDATED_AT_STORAGE_KEY = 'br:credits:api_usd:updated_at'
export const CREDITS_UPDATED_EVENT = 'br:credits:updated'

export type CreditsBalance = number | null
export type ApiUsdCreditsBalance = number | null
export type CreditsLedgerEntry = {
  entry_id: string
  event_type: string
  amount: number
  amount_milli: number
  balance_after: number
  balance_after_milli: number
  created_at: string
  reservation_id?: string | null
  idempotency_key?: string | null
  metadata?: Record<string, unknown>
}

type CreditsBalanceResponse = {
  workspace_id: string
  user_id: string
  balance: number
  balance_milli: number
  updated_at: string
}

type ApiUsdCreditsBalanceResponse = CreditsBalanceResponse & {
  bucket: string
  currency: string
}

type CreditsLedgerResponse = {
  items: CreditsLedgerEntry[]
  next_cursor?: string | null
}

export function readCreditsBalance(): CreditsBalance {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(CREDITS_BALANCE_STORAGE_KEY)
    if (!raw) return null
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || parsed < 0) return null
    return Math.floor(parsed)
  } catch {
    return null
  }
}

export function readCreditsUpdatedAt(): number | null {
  return readTimestamp(CREDITS_UPDATED_AT_STORAGE_KEY)
}

function readTimestamp(storageKey: string): number | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return null
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || parsed <= 0) return null
    return parsed
  } catch {
    return null
  }
}

export function readApiUsdCreditsBalance(): ApiUsdCreditsBalance {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(API_USD_CREDITS_BALANCE_STORAGE_KEY)
    if (!raw) return null
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || parsed < 0) return null
    return Math.round(parsed * 1000) / 1000
  } catch {
    return null
  }
}

export function readApiUsdCreditsUpdatedAt(): number | null {
  return readTimestamp(API_USD_CREDITS_UPDATED_AT_STORAGE_KEY)
}

export function touchCreditsUpdatedAt(storageKey: string = CREDITS_UPDATED_AT_STORAGE_KEY): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey, String(Date.now()))
    window.dispatchEvent(new Event(CREDITS_UPDATED_EVENT))
  } catch {
    // ignore
  }
}

export function writeCreditsBalance(balance: CreditsBalance): void {
  if (typeof window === 'undefined') return
  try {
    if (balance == null) {
      window.localStorage.removeItem(CREDITS_BALANCE_STORAGE_KEY)
    } else {
      const safe = Math.max(0, Math.floor(balance))
      window.localStorage.setItem(CREDITS_BALANCE_STORAGE_KEY, String(safe))
    }
    touchCreditsUpdatedAt(CREDITS_UPDATED_AT_STORAGE_KEY)
  } catch {
    // ignore
  }
}

export function writeApiUsdCreditsBalance(balance: ApiUsdCreditsBalance): void {
  if (typeof window === 'undefined') return
  try {
    if (balance == null) {
      window.localStorage.removeItem(API_USD_CREDITS_BALANCE_STORAGE_KEY)
    } else {
      const safe = Math.max(0, Math.round(balance * 1000) / 1000)
      window.localStorage.setItem(API_USD_CREDITS_BALANCE_STORAGE_KEY, String(safe))
    }
    touchCreditsUpdatedAt(API_USD_CREDITS_UPDATED_AT_STORAGE_KEY)
  } catch {
    // ignore
  }
}

export function subscribeCreditsUpdates(onUpdate: () => void): () => void {
  if (typeof window === 'undefined') return () => {}

  const handleCustom = () => onUpdate()
  const handleStorage = (event: StorageEvent) => {
    if (
      event.key !== CREDITS_BALANCE_STORAGE_KEY &&
      event.key !== CREDITS_UPDATED_AT_STORAGE_KEY &&
      event.key !== API_USD_CREDITS_BALANCE_STORAGE_KEY &&
      event.key !== API_USD_CREDITS_UPDATED_AT_STORAGE_KEY
    ) {
      return
    }
    onUpdate()
  }

  window.addEventListener(CREDITS_UPDATED_EVENT, handleCustom)
  window.addEventListener('storage', handleStorage)

  return () => {
    window.removeEventListener(CREDITS_UPDATED_EVENT, handleCustom)
    window.removeEventListener('storage', handleStorage)
  }
}

function normalizeBalance(value: unknown): number | null {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) return null
  return Math.max(0, Math.floor(parsed))
}

function normalizeUsdBalance(value: unknown): number | null {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) return null
  return Math.max(0, Math.round(parsed * 1000) / 1000)
}

export async function syncCreditsBalanceFromServer(): Promise<CreditsBalance> {
  if (typeof window === 'undefined') return null
  try {
    const response = await fetch('/api/credits/balance', {
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
    })
    if (!response.ok) {
      if (response.status === 401) {
        writeCreditsBalance(null)
      }
      return readCreditsBalance()
    }
    const payload = (await response.json()) as CreditsBalanceResponse
    const nextBalance = normalizeBalance(payload.balance)
    writeCreditsBalance(nextBalance)
    return nextBalance
  } catch {
    return readCreditsBalance()
  }
}

export async function syncApiUsdCreditsBalanceFromServer(): Promise<ApiUsdCreditsBalance> {
  if (typeof window === 'undefined') return null
  try {
    const response = await fetch('/api/credits/api-usd/balance', {
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
    })
    if (!response.ok) {
      if (response.status === 401) {
        writeApiUsdCreditsBalance(null)
      }
      return readApiUsdCreditsBalance()
    }
    const payload = (await response.json()) as ApiUsdCreditsBalanceResponse
    const nextBalance = normalizeUsdBalance(payload.balance)
    writeApiUsdCreditsBalance(nextBalance)
    return nextBalance
  } catch {
    return readApiUsdCreditsBalance()
  }
}

export async function fetchCreditsLedger(limit: number = 20, cursor?: string | null): Promise<CreditsLedgerResponse> {
  const params = new URLSearchParams()
  params.set('limit', String(Math.max(1, Math.min(200, Math.floor(limit || 20)))))
  if (cursor) params.set('cursor', cursor)
  const response = await fetch(`/api/credits/ledger?${params.toString()}`, {
    method: 'GET',
    credentials: 'include',
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Failed to load credits ledger (${response.status})`)
  }
  return (await response.json()) as CreditsLedgerResponse
}

export async function grantCredits(
  amount: number,
  options?: { reason?: string; metadata?: Record<string, unknown> },
): Promise<CreditsBalance> {
  const parsedAmount = Number(amount)
  if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
    throw new Error('Amount must be a positive number.')
  }

  const idempotencyKey = `ui-grant:${Date.now()}:${Math.random().toString(16).slice(2)}`
  const response = await fetch('/api/credits/grants', {
    method: 'POST',
    credentials: 'include',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      amount: parsedAmount,
      reason: options?.reason ?? 'internal_grant',
      idempotency_key: idempotencyKey,
      metadata: options?.metadata ?? {},
    }),
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(text || `Failed to grant credits (${response.status})`)
  }
  return syncCreditsBalanceFromServer()
}
