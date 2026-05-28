import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { BrainResearcherAPI, getAccessTokenAnyContext } from '../brain-researcher-api'

// Mock next-auth client helpers
const getSessionMock = vi.fn()
vi.mock('next-auth/react', () => ({ getSession: getSessionMock }))

const mockFetch = vi.fn()
const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

beforeEach(() => {
  const sessionStore = new Map<string, string>()
  const localStore = new Map<string, string>()
  ;(globalThis as any).window = {
    sessionStorage: {
      getItem: (key: string) => sessionStore.get(key) ?? null,
      setItem: (key: string, value: string) => {
        sessionStore.set(key, value)
      },
      removeItem: (key: string) => {
        sessionStore.delete(key)
      },
    },
    localStorage: {
      getItem: (key: string) => localStore.get(key) ?? null,
      setItem: (key: string, value: string) => {
        localStore.set(key, value)
      },
      removeItem: (key: string) => {
        localStore.delete(key)
      },
    },
  }
  getSessionMock.mockReset()
  mockFetch.mockReset()
  consoleWarnSpy.mockClear()
  ;(globalThis as any).fetch = mockFetch
})

afterEach(() => {
  vi.clearAllMocks()
  delete (globalThis as any).window
})

describe('client-side auth headers', () => {
  it('getAccessTokenAnyContext returns client access token when present', async () => {
    getSessionMock.mockResolvedValue({ accessToken: 'client-token' })
    const token = await getAccessTokenAnyContext()
    expect(token).toBe('client-token')
  })

  it('authenticatedFetch attaches Authorization header on client', async () => {
    getSessionMock.mockResolvedValue({ accessToken: 'client-token' })
    mockFetch.mockResolvedValue(new Response('ok'))

    const api = new BrainResearcherAPI()
    await api['authenticatedFetch']('http://example.com/protected')

    expect(mockFetch).toHaveBeenCalledTimes(1)
    const [, options] = mockFetch.mock.calls[0]
    const headers = options?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer client-token')
  })

  it('marks notifications endpoint unsupported on 404 and hard-stops future calls', async () => {
    getSessionMock.mockResolvedValue({ accessToken: 'client-token' })
    mockFetch.mockResolvedValueOnce(new Response('not found', { status: 404 }))

    const api = new BrainResearcherAPI()
    const first = await api.getUserNotifications(9)
    expect(first.endpointStatus).toBe('unsupported')
    expect(first.endpointSupported).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(1)

    const second = await api.getUserNotifications(9)
    expect(second.endpointStatus).toBe('unsupported')
    expect(second.endpointSupported).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('skips markNotificationsRead when notifications endpoint is unsupported', async () => {
    getSessionMock.mockResolvedValue({ accessToken: 'client-token' })
    mockFetch.mockResolvedValueOnce(new Response('not found', { status: 404 }))

    const api = new BrainResearcherAPI()
    await api.getUserNotifications(9)
    await api.markNotificationsRead(['n-1'])

    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('treats 405 notifications endpoint responses as unsupported', async () => {
    getSessionMock.mockResolvedValue({ accessToken: 'client-token' })
    mockFetch.mockResolvedValueOnce(new Response('method not allowed', { status: 405 }))

    const api = new BrainResearcherAPI()
    const first = await api.getUserNotifications(9)
    expect(first.endpointStatus).toBe('unsupported')
    expect(first.endpointSupported).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })
})
