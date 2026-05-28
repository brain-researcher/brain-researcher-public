/**
 * Utility to build cURL commands for debugging API requests
 */

export interface CurlCommandOptions {
  url: string
  method?: string
  body?: any
  headers?: Record<string, string>
  baseUrl?: string
}

/**
 * Builds a cURL command string from request parameters
 * Useful for debugging and sharing API requests
 */
export function buildCurlCommand({
  url,
  method = 'GET',
  body,
  headers,
  baseUrl
}: CurlCommandOptions): string {
  const fullUrl = baseUrl ? `${baseUrl}${url}` : url
  const parts: string[] = [`curl -X ${method.toUpperCase()}`]

  // Add headers
  const defaultHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers
  }

  Object.entries(defaultHeaders).forEach(([key, value]) => {
    parts.push(`-H "${key}: ${value}"`)
  })

  // Add body for POST/PUT/PATCH
  if (body && ['POST', 'PUT', 'PATCH'].includes(method.toUpperCase())) {
    const bodyStr = typeof body === 'string' ? body : JSON.stringify(body, null, 2)
    // Escape single quotes in JSON and wrap in single quotes
    const escapedBody = bodyStr.replace(/'/g, "'\\''")
    parts.push(`-d '${escapedBody}'`)
  }

  // Add URL (quoted to handle special characters)
  parts.push(`"${fullUrl}"`)

  return parts.join(' \\\n  ')
}

/**
 * Builds a cURL command for a plan request
 */
export function buildPlanCurl(
  payload: any,
  debug_selection: boolean = false
): string {
  const url = debug_selection ? '/api/plan?debug_selection=true' : '/api/plan'
  return buildCurlCommand({
    url,
    method: 'POST',
    body: payload,
    baseUrl: typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'
  })
}

/**
 * Builds a cURL command for fetching KG tools
 */
export function buildKGToolsCurl(
  intent: string,
  pipeline?: string,
  perFamily?: number
): string {
  const params = new URLSearchParams({ intent })
  if (pipeline) params.append('pipeline', pipeline)
  if (perFamily) params.append('per_family', String(perFamily))

  const url = `/api/kg/tools?${params.toString()}`
  return buildCurlCommand({
    url,
    method: 'GET',
    baseUrl: typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'
  })
}

/**
 * Builds a cURL command for fetching KG pipelines
 */
export function buildKGPipelinesCurl(): string {
  return buildCurlCommand({
    url: '/api/kg/pipelines',
    method: 'GET',
    baseUrl: typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'
  })
}
