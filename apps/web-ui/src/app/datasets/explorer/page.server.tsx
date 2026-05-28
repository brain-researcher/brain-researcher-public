import { headers } from 'next/headers'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { CatalogExplorerClient } from '@/components/datasets/catalog-explorer-client'
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

async function fetchInitialDatasets(baseUrl: string): Promise<DatasetSearchResponse> {
  const response = await fetch(`${baseUrl}${DATASET_API_PATH}/search?limit=60&offset=0`, {
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error('Failed to load dataset catalog')
  }
  return response.json()
}

export default async function DatasetsExplorerPage() {
  const initialResults = await fetchInitialDatasets(resolveBaseUrl())
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <CatalogExplorerClient initialResults={initialResults} apiBase={DATASET_API_PATH} />
        </div>
      </div>
    </NavigationWrapper>
  )
}
