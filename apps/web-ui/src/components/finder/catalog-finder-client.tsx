'use client'

import { CatalogFinder } from '@/components/datasets/catalog-finder'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { DatasetSearchResponse } from '@/types/datasets-search'
import { NumericFilters } from '@/lib/dataset-query'

interface CatalogFinderClientProps {
  initialResults: DatasetSearchResponse
  apiBase: string
  initialQuery?: string
  initialFilters?: NumericFilters
  initialParseErrors?: string[]
  normalizeUrl?: boolean
}

export function CatalogFinderClient({
  initialResults,
  apiBase,
  initialQuery = '',
  initialFilters,
  initialParseErrors,
  normalizeUrl,
}: CatalogFinderClientProps) {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto w-full max-w-6xl px-4 py-8">
          <CatalogFinder
            initialResults={initialResults}
            apiBase={apiBase}
            initialQuery={initialQuery}
            initialFilters={initialFilters}
            initialParseErrors={initialParseErrors}
            normalizeUrl={normalizeUrl}
          />
        </div>
      </div>
    </NavigationWrapper>
  )
}
