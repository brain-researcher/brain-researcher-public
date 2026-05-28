import type { Mock } from 'vitest'

type MockFetchInput = Parameters<Mock<[RequestInfo | URL, RequestInit?], Promise<Response>>>

export const makeJsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

export const jsonResponse = makeJsonResponse

export const makeToolSuccessResponse = (data: unknown, status = 200): Response =>
  makeJsonResponse(
    {
      result: {
        status: 'success',
        data,
      },
    },
    status,
  )

export type FetchResponseQueue = Response[]

interface QueueFetchMockOptions {
  authSessionPath?: string
  authSessionResponse?: unknown
}

export const queueFetchMock = (
  mockFetch: Mock<MockFetchInput, Promise<Response>>,
  responses: FetchResponseQueue,
  options: QueueFetchMockOptions = {},
): void => {
  const queue = [...responses]
  const authSessionPath = options.authSessionPath ?? '/api/auth/session'
  const authSessionResponse = options.authSessionResponse ?? { data: null }

  mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith(authSessionPath)) {
      return makeJsonResponse(authSessionResponse)
    }

    const next = queue.shift()
    if (next) {
      return next
    }

    throw new Error(`Unexpected fetch call for ${url}`)
  })
}
