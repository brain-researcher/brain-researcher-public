import { cookies, headers } from 'next/headers'
import Link from 'next/link'
import { notFound } from 'next/navigation'

import { DatasetDetailView } from '@/components/datasets/dataset-detail-view'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import type {
  DatasetDetailResponse,
  DatasetResourceAddresses,
} from '@/types/datasets-search'

const DATASET_API_PATH = '/api/catalog/datasets'
const DATASET_RESOURCES_API_PATH = '/api/catalog/datasets'
const E2E_AUTH_COOKIE = 'br_e2e_auth'
const E2E_FIXTURE_HEADER = 'x-br-e2e'

function sanitizeStudioReturnTo(raw: string | undefined): string | undefined {
  if (!raw) return undefined
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/studio')) return undefined
  try {
    const normalized = new URL(trimmed, 'http://localhost')
    if (!normalized.pathname.startsWith('/studio')) return undefined
    return `${normalized.pathname}${normalized.search}`
  } catch {
    return undefined
  }
}

function resolveBaseUrl(): string {
  const headerList = headers()
  const protoHeader = headerList.get('x-forwarded-proto')
  const proto =
    (protoHeader ? protoHeader.split(',')[0] : null) ??
    (process.env.NODE_ENV === 'production' ? 'https' : 'http')
  const hostHeader = headerList.get('x-forwarded-host') ?? headerList.get('host')
  const host = (hostHeader ? hostHeader.split(',')[0] : null) ?? '127.0.0.1:3000'
  const explicit = process.env.NEXT_PUBLIC_SITE_URL
  if (explicit) return explicit.replace(/\/$/, '')
  return `${proto}://${host}`
}

function normalizeDatasetId(datasetId: string): string {
  let normalized = datasetId.trim()
  for (let i = 0; i < 2; i += 1) {
    try {
      const next = decodeURIComponent(normalized).trim()
      if (!next || next === normalized) break
      normalized = next
    } catch {
      break
    }
  }
  return normalized
}

function buildDatasetApiHeaders(useE2eFixtures: boolean): HeadersInit | undefined {
  const requestHeaders = headers()
  const nextHeaders: Record<string, string> = {}
  const cookieHeader = requestHeaders.get('cookie')
  if (cookieHeader) nextHeaders.cookie = cookieHeader
  if (useE2eFixtures) nextHeaders[E2E_FIXTURE_HEADER] = '1'
  return Object.keys(nextHeaders).length ? nextHeaders : undefined
}

async function fetchDataset(
  datasetId: string,
  baseUrl: string,
  requestHeaders: HeadersInit | undefined,
): Promise<DatasetDetailResponse> {
  const normalizedDatasetId = normalizeDatasetId(datasetId)
  const response = await fetch(
    `${baseUrl}${DATASET_API_PATH}/${encodeURIComponent(normalizedDatasetId)}`,
    {
      cache: 'no-store',
      headers: requestHeaders,
    },
  )
  if (response.status === 404) {
    notFound()
  }
  if (!response.ok) {
    throw new Error('Failed to load dataset details')
  }
  return response.json()
}

async function fetchDatasetResources(
  datasetId: string,
  baseUrl: string,
  requestHeaders: HeadersInit | undefined,
): Promise<DatasetResourceAddresses | undefined> {
  const normalizedDatasetId = normalizeDatasetId(datasetId)
  try {
    const response = await fetch(
      `${baseUrl}${DATASET_RESOURCES_API_PATH}/${encodeURIComponent(normalizedDatasetId)}/resources`,
      {
        cache: 'no-store',
        headers: requestHeaders,
      },
    )
    if (!response.ok) return undefined
    const payload = (await response.json()) as DatasetResourceAddresses
    if (!payload || typeof payload !== 'object' || !('dataset_ref' in payload)) {
      return undefined
    }
    return payload
  } catch {
    return undefined
  }
}

export default async function DatasetDetailPage({
  params,
  searchParams,
}: {
  params: { datasetId: string }
  searchParams?: Record<string, string | string[] | undefined>
}) {
  const useE2eFixtures =
    process.env.NODE_ENV !== 'production' && cookies().get(E2E_AUTH_COOKIE)?.value === '1'
  const pickValue = Array.isArray(searchParams?.pick) ? searchParams?.pick[0] : searchParams?.pick
  const returnTo = Array.isArray(searchParams?.returnTo)
    ? searchParams?.returnTo[0]
    : searchParams?.returnTo
  const pickMode = pickValue === '1' || pickValue === 'true'
  const safeReturnTo = sanitizeStudioReturnTo(
    typeof returnTo === 'string' ? returnTo : undefined,
  )
  const backHref =
    pickMode && safeReturnTo
      ? `/datasets?pick=1&returnTo=${encodeURIComponent(safeReturnTo)}`
      : '/datasets'
  const baseUrl = resolveBaseUrl()
  const requestHeaders = buildDatasetApiHeaders(useE2eFixtures)
  const [dataset, resourceAddresses] = await Promise.all([
    fetchDataset(params.datasetId, baseUrl, requestHeaders),
    fetchDatasetResources(params.datasetId, baseUrl, requestHeaders),
  ])
  const datasetWithResources: DatasetDetailResponse = {
    ...dataset,
    resource_addresses: resourceAddresses,
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
          <div>
            <Link href={backHref} className="text-sm text-primary hover:underline">
              ← Back to Datasets
            </Link>
          </div>
          <DatasetDetailView dataset={datasetWithResources} />
        </div>
      </div>
    </NavigationWrapper>
  )
}
