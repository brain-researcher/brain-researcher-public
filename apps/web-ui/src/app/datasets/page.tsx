import { cookies, headers } from 'next/headers'
import Link from 'next/link'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { CatalogExplorerClient } from '@/components/datasets/catalog-explorer-client'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { DatasetSearchResponse } from '@/types/datasets-search'
import {
  appendNumericFilters,
  hasAnyNumericFilters,
  mergeNumericFilters,
  numericFiltersFromSearchParams,
  parseInlineFilters,
} from '@/lib/dataset-query'

const DATASET_API_PATH = '/api/catalog/datasets'
const E2E_AUTH_COOKIE = 'br_e2e_auth'
const E2E_FIXTURE_HEADER = 'x-br-e2e'

function sanitizeStudioReturnTo(raw: string | undefined): string | null {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/studio')) return null
  try {
    const normalized = new URL(trimmed, 'http://localhost')
    if (!normalized.pathname.startsWith('/studio')) return null
    return `${normalized.pathname}${normalized.search}`
  } catch {
    return null
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

async function fetchInitialDatasets(
  baseUrl: string,
  query: string,
  filters: ReturnType<typeof numericFiltersFromSearchParams>,
  modalities: string[],
  useE2eFixtures: boolean,
): Promise<DatasetSearchResponse> {
  const params = new URLSearchParams({ limit: '60', offset: '0' })
  if (query) params.set('q', query)
  appendNumericFilters(params, filters)
  modalities.forEach((modality) => params.append('modalities', modality))

  try {
    const response = await fetch(
      `${baseUrl}${DATASET_API_PATH}/search?${params.toString()}`,
      {
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
          ...(useE2eFixtures ? { [E2E_FIXTURE_HEADER]: '1' } : {}),
        },
      },
    )

    if (!response.ok) {
      console.error(`Datasets API error: ${response.status} ${response.statusText}`)
      return {
        datasets: [],
        total: 0,
        limit: 60,
        offset: 0,
        has_more: false,
        search_time_ms: 0,
        facets: {},
        last_updated: new Date().toISOString(),
        errors: [`Failed to load datasets (${response.status})`],
      }
    }

    return response.json()
  } catch (error) {
    console.error('Failed to fetch datasets:', error)
    return {
      datasets: [],
      total: 0,
      limit: 60,
      offset: 0,
      has_more: false,
      search_time_ms: 0,
      facets: {},
      last_updated: new Date().toISOString(),
      errors: ['Failed to load datasets'],
    }
  }
}

export default async function DatasetsPage({
  searchParams,
}: {
  searchParams?: Record<string, string | string[] | undefined>
}) {
  const rawQuery =
    (Array.isArray(searchParams?.q) ? searchParams?.q[0] : searchParams?.q) ||
    (Array.isArray(searchParams?.query) ? searchParams?.query[0] : searchParams?.query) ||
    ''
  const inlineParse = parseInlineFilters(rawQuery)
  const structuredFilters = numericFiltersFromSearchParams(searchParams ?? {})
  const mergedFilters = mergeNumericFilters(structuredFilters, inlineParse.filters)
  const rawModalities = searchParams?.modalities
  const initialModalities = (Array.isArray(rawModalities) ? rawModalities : rawModalities ? [rawModalities] : [])
    .flatMap((value) => String(value).split(','))
    .map((value) => value.trim())
    .filter(Boolean)
  const pickValue = Array.isArray(searchParams?.pick) ? searchParams?.pick[0] : searchParams?.pick
  const returnTo = Array.isArray(searchParams?.returnTo) ? searchParams?.returnTo[0] : searchParams?.returnTo
  const pickMode = pickValue === '1' || pickValue === 'true'
  const sanitizedReturnTo = sanitizeStudioReturnTo(typeof returnTo === 'string' ? returnTo : undefined)
  const goToStudioHref =
    pickMode && sanitizedReturnTo
      ? sanitizedReturnTo
      : '/studio'
  const isE2eCookieAuth =
    process.env.NODE_ENV !== 'production' &&
    cookies().get(E2E_AUTH_COOKIE)?.value === '1'
  const initialResults = await fetchInitialDatasets(
    resolveBaseUrl(),
    inlineParse.query,
    mergedFilters,
    initialModalities,
    isE2eCookieAuth,
  )
  const shouldNormalizeUrl =
    inlineParse.hasInlineFilters && !hasAnyNumericFilters(structuredFilters) && !pickMode

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-4">
          <Alert>
            <AlertTitle>Datasets</AlertTitle>
            <AlertDescription>
              Browse datasets and add them to your plan in <code>Studio</code>. Legacy links under <code>/vault/datasets</code> redirect here.
              <span className="ml-2">
                <Link className="text-primary underline" href={goToStudioHref}>
                  Go to Studio
                </Link>
              </span>
            </AlertDescription>
          </Alert>

          <CatalogExplorerClient
            initialResults={initialResults}
            apiBase={DATASET_API_PATH}
            initialQuery={inlineParse.query}
            initialFilters={mergedFilters}
            initialModalities={initialModalities}
            initialParseErrors={inlineParse.errors}
            normalizeUrl={shouldNormalizeUrl}
            pickMode={pickMode}
            returnTo={typeof returnTo === 'string' ? returnTo : undefined}
          />
        </div>
      </div>
    </NavigationWrapper>
  )
}
