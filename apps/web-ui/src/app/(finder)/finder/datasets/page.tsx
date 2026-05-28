import { headers } from 'next/headers'

import { CatalogFinder } from '@/components/datasets/catalog-finder'
import { DatasetSearchResponse } from '@/types/datasets-search'

const DATASET_API_PATH = '/api/catalog/datasets'

function resolveBaseUrl(): string {
  const headerList = headers()
  const protoHeader = headerList.get('x-forwarded-proto')
  const proto = (protoHeader ? protoHeader.split(',')[0] : null) ?? (process.env.NODE_ENV === 'production' ? 'https' : 'http')
  const hostHeader = headerList.get('x-forwarded-host') ?? headerList.get('host')
  const host = (hostHeader ? hostHeader.split(',')[0] : null) ?? '127.0.0.1:3000'
  const explicit = process.env.NEXT_PUBLIC_SITE_URL
  if (explicit) return explicit.replace(/\/$/, '')
  return `${proto}://${host}`
}

async function fetchInitialDatasets(baseUrl: string, query: string): Promise<DatasetSearchResponse> {
  const params = new URLSearchParams({ limit: '24', offset: '0' })
  if (query) params.set('q', query)
  const url = `${baseUrl}${DATASET_API_PATH}/search?${params.toString()}`
  const response = await fetch(url, { cache: 'no-store' })
  if (!response.ok) {
    throw new Error('Failed to load dataset catalog')
  }
  return response.json()
}

export default async function FinderDatasetsPage({ searchParams }: { searchParams: Record<string, string | string[] | undefined> }) {
  const queryParam = (Array.isArray(searchParams?.q) ? searchParams.q[0] : searchParams?.q) ||
    (Array.isArray(searchParams?.query) ? searchParams.query[0] : searchParams?.query) ||
    ''
  const baseUrl = resolveBaseUrl()
  const initialResults = await fetchInitialDatasets(baseUrl, queryParam)
  return (
    <div className="mx-auto max-w-6xl space-y-6 py-6">
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Dataset Finder</h1>
        <p className="text-muted-foreground">Search curated datasets across OpenNeuro, HCP, ADNI, DANDI, and custom sources.</p>
      </div>
      <CatalogFinder initialResults={initialResults} apiBase={DATASET_API_PATH} initialQuery={queryParam} />
    </div>
  )
}
