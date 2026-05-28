"use client"

import { CatalogExplorer } from '@/components/datasets/catalog-explorer'
import { DatasetSearchResponse } from '@/types/datasets-search'
import { NumericFilters } from '@/lib/dataset-query'

interface CatalogExplorerClientProps {
  initialResults: DatasetSearchResponse
  apiBase?: string
  initialQuery?: string
  initialFilters?: NumericFilters
  initialModalities?: string[]
  initialParseErrors?: string[]
  normalizeUrl?: boolean
  pickMode?: boolean
  returnTo?: string
}

export function CatalogExplorerClient({
  initialResults,
  apiBase,
  initialQuery,
  initialFilters,
  initialModalities,
  initialParseErrors,
  normalizeUrl,
  pickMode,
  returnTo,
}: CatalogExplorerClientProps) {
  return (
    <CatalogExplorer
      initialResults={initialResults}
      apiBase={apiBase}
      initialQuery={initialQuery}
      initialFilters={initialFilters}
      initialModalities={initialModalities}
      initialParseErrors={initialParseErrors}
      normalizeUrl={normalizeUrl}
      pickMode={pickMode}
      returnTo={returnTo}
    />
  )
}
