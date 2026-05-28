"use client"

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowRight, ExternalLink, LayoutGrid, Rows3, Loader2, X, ChevronDown, Info } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { serviceEndpoints } from '@/lib/service-endpoints'
import { DatasetCardResponse, DatasetSearchResponse, FacetValueResponse } from '@/types/datasets-search'
import {
  buildFilterChips,
  mergeNumericFilters,
  parseInlineFilters,
  appendNumericFilters,
  NumericFilters,
  NumericInputState,
  numericInputsFromFilters,
  numericFiltersFromInputs,
} from '@/lib/dataset-query'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

interface CatalogExplorerProps {
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

const CATEGORY_FACET = 'category'
const MODALITY_FACET = 'modalities'
const DEFAULT_FETCH_LIMIT = 60
const E2E_AUTH_COOKIE = 'br_e2e_auth=1'

type SortKey = 'featured' | 'subjects' | 'updated' | 'alpha'

export function CatalogExplorer({
  initialResults,
  apiBase,
  initialQuery = '',
  initialFilters,
  initialModalities,
  initialParseErrors,
  normalizeUrl = false,
  pickMode = false,
  returnTo,
}: CatalogExplorerProps) {
  const router = useRouter()
  const [searchValue, setSearchValue] = useState(initialQuery)
  const [numericFilters, setNumericFilters] = useState<NumericFilters>(initialFilters ?? {})
  const [selectedModalities, setSelectedModalities] = useState<string[]>(initialModalities ?? [])
  const [numericInputs, setNumericInputs] = useState<NumericInputState>(
    () => numericInputsFromFilters(initialFilters ?? {}),
  )
  const [numericInputErrors, setNumericInputErrors] = useState<string[]>([])
  const [parseErrors, setParseErrors] = useState<string[]>(initialParseErrors ?? [])
  const [warnings, setWarnings] = useState<string[]>(initialResults.warnings ?? [])
  const [initialLoadError, setInitialLoadError] = useState<string | null>(
    initialResults.errors?.[0] ?? null,
  )
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('featured')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [catalogDatasets, setCatalogDatasets] = useState<DatasetCardResponse[]>(initialResults.datasets)
  const [catalogOffset, setCatalogOffset] = useState(initialResults.datasets.length)
  const [hasMoreCatalog, setHasMoreCatalog] = useState(initialResults.has_more)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const datasetApiBase = apiBase ?? '/api/catalog/datasets'
  const normalizedRef = useRef(false)
  const sessionIdRef = useRef<string | null>(null)
  const basePath = '/datasets'

  const appendModalities = (params: URLSearchParams, modalities: string[]) => {
    for (const modality of modalities) {
      const trimmed = modality.trim()
      if (!trimmed) continue
      params.append('modalities', trimmed)
    }
  }

  const appendPickerParams = (params: URLSearchParams) => {
    if (!pickMode) return
    params.set('pick', '1')
    if (safeReturnTo) {
      params.set('returnTo', safeReturnTo)
    }
  }

  const safeReturnTo = useMemo(() => {
    if (!pickMode) return null
    if (typeof returnTo !== 'string' || !returnTo.trim()) return '/studio'
    const trimmed = returnTo.trim()
    if (!trimmed.startsWith('/studio')) return '/studio'
    return trimmed
  }, [pickMode, returnTo])

  const buildPickHref = (datasetId: string) => {
    const base = safeReturnTo || '/studio'
    const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin
    try {
      const url = new URL(base, origin)
      url.searchParams.set('datasetId', datasetId)
      url.searchParams.delete('dataset')
      url.searchParams.set('tab', 'plan')
      return `${url.pathname}?${url.searchParams.toString()}`
    } catch {
      const separator = base.includes('?') ? '&' : '?'
      return `${base}${separator}datasetId=${encodeURIComponent(datasetId)}&tab=plan`
    }
  }

  useEffect(() => {
    setSearchValue(initialQuery)
    setNumericFilters(initialFilters ?? {})
    setSelectedModalities(initialModalities ?? [])
    setNumericInputs(numericInputsFromFilters(initialFilters ?? {}))
    setNumericInputErrors([])
    setParseErrors(initialParseErrors ?? [])
    setWarnings(initialResults.warnings ?? [])
    setInitialLoadError(initialResults.errors?.[0] ?? null)
    setCatalogDatasets(initialResults.datasets)
    setCatalogOffset(initialResults.datasets.length)
    setHasMoreCatalog(initialResults.has_more)
    setSelectedCategory(null)
    setLoadingMore(false)
    setLoadMoreError(null)
  }, [initialQuery, initialFilters, initialParseErrors, initialResults])

  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (typeof document === 'undefined') return
    if (!document.cookie.includes(E2E_AUTH_COOKIE)) return

    const controller = new AbortController()
    let cancelled = false

    const fetchCatalog = async () => {
      setInitialLoadError(null)
      setLoadMoreError(null)
      try {
        const params = new URLSearchParams({
          limit: String(DEFAULT_FETCH_LIMIT),
          offset: '0',
        })
        if (searchValue.trim()) {
          params.set('q', searchValue.trim())
        }
        appendNumericFilters(params, numericFilters)
        appendModalities(params, selectedModalities)
        const response = await fetch(`${datasetApiBase}/search?${params.toString()}`, {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(`Failed to load datasets (${response.status})`)
        }
        const data: DatasetSearchResponse = await response.json()
        if (cancelled) return
        setWarnings(data.warnings ?? [])
        setCatalogDatasets(data.datasets)
        setCatalogOffset(data.datasets.length)
        setHasMoreCatalog(data.has_more)
        setInitialLoadError(data.errors?.[0] ?? null)
      } catch (error) {
        if (cancelled) return
        const message = error instanceof Error ? error.message : 'Failed to load datasets.'
        setInitialLoadError(message)
      }
    }

    void fetchCatalog()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [datasetApiBase, numericFilters, searchValue, selectedModalities])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const existing = localStorage.getItem('searchSessionId')
    if (existing) {
      sessionIdRef.current = existing
      return
    }
    const generated = `search_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
    localStorage.setItem('searchSessionId', generated)
    sessionIdRef.current = generated
  }, [])

  useEffect(() => {
    setNumericInputs(numericInputsFromFilters(numericFilters))
  }, [numericFilters])

  useEffect(() => {
    if (!normalizeUrl || normalizedRef.current) return
    normalizedRef.current = true
    const params = new URLSearchParams()
    if (searchValue.trim()) params.set('q', searchValue.trim())
    appendNumericFilters(params, numericFilters)
    appendModalities(params, selectedModalities)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.replace(nextUrl)
  }, [normalizeUrl, numericFilters, router, searchValue, basePath, selectedModalities])

  const datasets = catalogDatasets
  const filterChips = useMemo(() => buildFilterChips(numericFilters), [numericFilters])
  const modalityChips = useMemo(
    () =>
      selectedModalities
        .map((value) => value.trim())
        .filter(Boolean)
        .slice(0, 8),
    [selectedModalities],
  )
  const inlineWarnings = useMemo(
    () => warnings.filter((warning) => /tr filters|voxel size filters/i.test(warning)),
    [warnings],
  )
  const generalWarnings = useMemo(
    () => warnings.filter((warning) => !/tr filters|voxel size filters/i.test(warning)),
    [warnings],
  )

  const buildTrackingQuery = (query: string, filters: NumericFilters) => {
    const cleanedQuery = query.trim()
    const chips = buildFilterChips(filters)
    const suffix = chips.length ? ` ${chips.map((chip) => chip.label).join(' ')}` : ''
    if (cleanedQuery) return `${cleanedQuery}${suffix}`.trim()
    if (suffix.trim()) return `datasets${suffix}`.trim()
    return ''
  }

  const trackSearch = async (queryToTrack: string) => {
    const trimmed = queryToTrack.trim()
    if (!trimmed) return
    try {
      const params = new URLSearchParams({ query: trimmed })
      if (sessionIdRef.current) {
        params.set('session_id', sessionIdRef.current)
      }
      await fetch(serviceEndpoints.orchestrator(`/api/search/track?${params.toString()}`), {
        method: 'POST',
      })
    } catch (err) {
      console.warn('Failed to track search query:', err)
    }
  }

  const clearFilter = (keys: (keyof NumericFilters)[]) => {
    const next = { ...numericFilters }
    keys.forEach((key) => {
      delete next[key]
    })
    setNumericFilters(next)
    const params = new URLSearchParams()
    if (searchValue.trim()) params.set('q', searchValue.trim())
    appendNumericFilters(params, next)
    appendModalities(params, selectedModalities)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const clearModality = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed) return
    const next = selectedModalities.filter((entry) => entry !== trimmed)
    setSelectedModalities(next)
    const params = new URLSearchParams()
    if (searchValue.trim()) params.set('q', searchValue.trim())
    appendNumericFilters(params, numericFilters)
    appendModalities(params, next)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const applyNumericFilters = () => {
    const { filters, errors } = numericFiltersFromInputs(numericInputs)
    if (errors.length > 0) {
      setNumericInputErrors(errors)
      return
    }
    setNumericInputErrors([])
    setNumericFilters(filters)
    const params = new URLSearchParams()
    if (searchValue.trim()) params.set('q', searchValue.trim())
    appendNumericFilters(params, filters)
    appendModalities(params, selectedModalities)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
    void trackSearch(buildTrackingQuery(searchValue, filters))
  }

  const clearNumericFilters = () => {
    const cleared: NumericFilters = {}
    setNumericInputs(numericInputsFromFilters(cleared))
    setNumericInputErrors([])
    setNumericFilters(cleared)
    const params = new URLSearchParams()
    if (searchValue.trim()) params.set('q', searchValue.trim())
    appendModalities(params, selectedModalities)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const updateNumericInput = (key: keyof NumericInputState) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setNumericInputs((prev) => ({ ...prev, [key]: event.target.value }))
  }

  const clearAllFilters = () => {
    setSearchValue('')
    setSelectedCategory(null)
    setNumericFilters({})
    setNumericInputs(numericInputsFromFilters({}))
    setSelectedModalities([])
    setParseErrors([])
    setNumericInputErrors([])
    setWarnings([])
    const params = new URLSearchParams()
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const loadMoreCatalog = async () => {
    if (!hasMoreCatalog || loadingMore) return
    setLoadingMore(true)
    setLoadMoreError(null)
    try {
      const params = new URLSearchParams({
        limit: String(DEFAULT_FETCH_LIMIT),
        offset: String(catalogOffset),
      })
      if (searchValue.trim()) {
        params.set('q', searchValue.trim())
      }
      appendNumericFilters(params, numericFilters)
      appendModalities(params, selectedModalities)
      const response = await fetch(`${datasetApiBase}/search?${params.toString()}`, { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`Failed to load more datasets (${response.status})`)
      }
      const data: DatasetSearchResponse = await response.json()
      setWarnings(data.warnings ?? warnings)
      setCatalogDatasets((prev) => mergeDatasets(prev, data.datasets))
      setCatalogOffset((prev) => prev + data.datasets.length)
      setHasMoreCatalog(data.has_more)
    } catch (error) {
      console.error('Failed to load more datasets', error)
      const message = error instanceof Error ? error.message : 'Failed to load more datasets.'
      setLoadMoreError(message)
    } finally {
      setLoadingMore(false)
    }
  }

  const fallbackCategories = useMemo(() => summarizeFacetsFromDatasets(datasets), [datasets])
  const categoryFacets = initialResults.facets[CATEGORY_FACET]?.length
    ? initialResults.facets[CATEGORY_FACET]
    : fallbackCategories
  const modalityFacets = initialResults.facets[MODALITY_FACET] ?? []

  const filteredDatasets = useMemo(() => {
    if (!selectedCategory) return datasets
    return datasets.filter((dataset) =>
      (dataset.category ?? '').toLowerCase() === selectedCategory.toLowerCase(),
    )
  }, [datasets, selectedCategory])

  const sortedCatalog = useMemo(() => sortDatasets(filteredDatasets, sortKey), [filteredDatasets, sortKey])

  const topCategories = categoryFacets.slice(0, 10)
  const topModalities = modalityFacets.slice(0, 6)
  const hasActiveSearch = searchValue.trim().length > 0
  const hasActiveNumericFilters = Object.keys(numericFilters).length > 0
  const hasActiveModalityFilters = selectedModalities.length > 0
  const hasActiveCategoryFilter = selectedCategory !== null
  const hasActiveCriteria =
    hasActiveSearch ||
    hasActiveNumericFilters ||
    hasActiveModalityFilters ||
    hasActiveCategoryFilter
  const showDiscoverySections = !pickMode && !hasActiveCriteria

  const largeCohorts = useMemo(
    () =>
      filteredDatasets
        .filter((dataset) => (dataset.subjects_count ?? 0) >= 1000)
        .sort((a, b) => (b.subjects_count ?? 0) - (a.subjects_count ?? 0))
        .slice(0, 4),
    [filteredDatasets],
  )

  const clinicalDatasets = useMemo(
    () =>
      filteredDatasets.filter((dataset) => (dataset.category ?? '').toLowerCase().includes('clinical')).slice(0, 4),
    [filteredDatasets],
  )

  const restingDatasets = useMemo(
    () =>
      filteredDatasets
        .filter(
          (dataset) =>
            dataset.tags.some((tag) => /rest|naturalistic|movie|passive/i.test(tag)) ||
            dataset.name.toLowerCase().includes('rest') ||
            dataset.description?.toLowerCase().includes('rest'),
        )
        .slice(0, 4),
    [filteredDatasets],
  )

  const handleSearchSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const parsed = parseInlineFilters(searchValue)
    const mergedFilters = mergeNumericFilters(numericFilters, parsed.filters)
    setParseErrors(parsed.errors)
    setNumericFilters(mergedFilters)
    setSearchValue(parsed.query)
    const params = new URLSearchParams()
    if (parsed.query.trim()) params.set('q', parsed.query.trim())
    appendNumericFilters(params, mergedFilters)
    appendModalities(params, selectedModalities)
    appendPickerParams(params)
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
    void trackSearch(buildTrackingQuery(parsed.query, mergedFilters))
  }

  const handleCategorySelect = (value: string) => {
    setSelectedCategory((prev) => (prev === value ? null : value))
  }

  return (
    <div className="space-y-12">
      {pickMode && (
        <Alert className="border-primary/30 bg-primary/5">
          <AlertDescription>
            Select a dataset to continue in Studio. We’ll keep your workflow inputs pre-filled.
          </AlertDescription>
        </Alert>
      )}
      <section className="rounded-3xl border bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 px-6 py-10 text-white shadow-xl">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-widest text-slate-300">Dataset Explorer</p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight md:text-5xl">Discover neuroimaging datasets</h1>
            <p className="mt-4 max-w-2xl text-base text-slate-200">
              Browse curated datasets across OpenNeuro, HCP, ABCD, NDA, and more. Use search and filters to narrow down quickly.
            </p>
          </div>
          <div className="flex flex-col gap-3 md:w-80">
            <form onSubmit={handleSearchSubmit}>
              <Input
                placeholder="Search datasets..."
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                className="w-full border-slate-600 bg-slate-900/60 text-white placeholder:text-slate-400 focus-visible:ring-white"
              />
            </form>
            <Collapsible defaultOpen={false} className="rounded-2xl border border-white/10 bg-slate-900/50 p-3">
              <div className="flex items-center justify-between">
                <CollapsibleTrigger className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-300">
                  Numeric filters
                  <span title="Add numeric constraints (subjects, age, TR, voxel size). Applied as URL parameters.">
                    <Info className="h-3 w-3 text-slate-400" />
                  </span>
                  {filterChips.length > 0 && (
                    <span className="rounded-full bg-slate-700/80 px-2 py-0.5 text-[10px] font-semibold text-slate-100">
                      {filterChips.length} active
                    </span>
                  )}
                  <ChevronDown className="h-3 w-3 text-slate-400" />
                </CollapsibleTrigger>
                <Button
                  type="button"
                  variant="ghost"
                  className="h-7 text-[11px] text-slate-300 hover:text-white"
                  onClick={clearAllFilters}
                >
                  Clear all filters
                </Button>
              </div>
              {inlineWarnings.length > 0 && (
                <div className="mt-2 text-[11px] text-amber-200">
                  {inlineWarnings.map((warning) => (
                    <div key={warning}>{warning}</div>
                  ))}
                </div>
              )}
              <CollapsibleContent className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-200">
                  <Input
                    type="number"
                    inputMode="numeric"
                    placeholder="N min"
                    value={numericInputs.min_subjects}
                    onChange={updateNumericInput('min_subjects')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="numeric"
                    placeholder="N max"
                    value={numericInputs.max_subjects}
                    onChange={updateNumericInput('max_subjects')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    placeholder="Age min (y)"
                    value={numericInputs.age_min}
                    onChange={updateNumericInput('age_min')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    placeholder="Age max (y)"
                    value={numericInputs.age_max}
                    onChange={updateNumericInput('age_max')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    placeholder="TR min (s)"
                    value={numericInputs.tr_min}
                    onChange={updateNumericInput('tr_min')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    placeholder="TR max (s)"
                    value={numericInputs.tr_max}
                    onChange={updateNumericInput('tr_max')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    placeholder="Voxel min (mm)"
                    value={numericInputs.voxel_min}
                    onChange={updateNumericInput('voxel_min')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                  <Input
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    placeholder="Voxel max (mm)"
                    value={numericInputs.voxel_max}
                    onChange={updateNumericInput('voxel_max')}
                    className="h-8 border-slate-700 bg-slate-900/60 text-slate-100 placeholder:text-slate-500"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Button type="button" variant="secondary" className="h-8 text-xs" onClick={applyNumericFilters}>
                    Apply filters
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-8 text-xs text-slate-300 hover:text-white"
                    onClick={clearNumericFilters}
                  >
                    Clear numeric
                  </Button>
                </div>
              </CollapsibleContent>
            </Collapsible>
            {filterChips.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-200">
                <span className="text-[10px] uppercase tracking-widest text-slate-400">Parsed filters</span>
                {filterChips.map((chip) => (
                  <button
                    key={chip.id}
                    type="button"
                    onClick={() => clearFilter(chip.clearKeys)}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-800/70 px-2 py-1 text-xs text-slate-100 hover:bg-slate-700"
                  >
                    {chip.label}
                    <X className="h-3 w-3" />
                  </button>
                ))}
              </div>
            )}
            {modalityChips.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-200">
                <span className="text-[10px] uppercase tracking-widest text-slate-400">Modalities</span>
                {modalityChips.map((modality) => (
                  <button
                    key={`modality-${modality}`}
                    type="button"
                    onClick={() => clearModality(modality)}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-800/70 px-2 py-1 text-xs text-slate-100 hover:bg-slate-700"
                  >
                    {modality}
                    <X className="h-3 w-3" />
                  </button>
                ))}
              </div>
            )}
            {parseErrors.length > 0 && (
              <div className="text-xs text-rose-200">
                {parseErrors.map((err) => (
                  <div key={err}>{err}</div>
                ))}
              </div>
            )}
            {numericInputErrors.length > 0 && (
              <div className="text-xs text-rose-200">
                {numericInputErrors.map((err) => (
                  <div key={err}>{err}</div>
                ))}
              </div>
            )}
            {generalWarnings.length > 0 && (
              <div className="text-xs text-amber-200">
                {generalWarnings.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
              </div>
            )}
          </div>
        </div>

        {topCategories.length > 0 && (
          <div className="mt-8 flex flex-wrap gap-2">
            {topCategories.map((facet) => (
              <Badge
                key={facet.value}
                variant={selectedCategory === facet.value ? 'default' : 'secondary'}
                className={cn(
                  'cursor-pointer select-none text-sm capitalize',
                  selectedCategory === facet.value ? 'bg-white text-slate-900' : 'bg-slate-800 text-slate-100 hover:bg-slate-700',
                )}
                onClick={() => handleCategorySelect(facet.value)}
              >
                {facet.value}
                <span className="ml-1 text-xs text-slate-300">({facet.count})</span>
              </Badge>
            ))}
          </div>
        )}
      </section>

      {showDiscoverySections ? (
        <ExplorerSection
        title="Large cohorts (≥1000 subjects)"
        description="Multi-site datasets with extensive participant counts for population-level analyses."
      >
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {largeCohorts.length ? (
            largeCohorts.map((dataset) => <ExplorerDatasetCard key={`large-${dataset.id}`} dataset={dataset} variant="compact" />)
          ) : (
            <EmptySection message="No large cohorts surfaced yet in this slice of the catalog." />
          )}
        </div>
        </ExplorerSection>
      ) : null}

      {showDiscoverySections ? (
        <ExplorerSection
        title="Clinical & disease-specific studies"
        description="Handpicked datasets focused on psychiatric, neurological, and developmental conditions."
      >
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {clinicalDatasets.length ? (
            clinicalDatasets.map((dataset) => <ExplorerDatasetCard key={`clinical-${dataset.id}`} dataset={dataset} variant="compact" />)
          ) : (
            <EmptySection message="No clinical-focused datasets detected in this view. Try refining your query or filters." />
          )}
        </div>
        </ExplorerSection>
      ) : null}

      {showDiscoverySections ? (
        <ExplorerSection
        title="Resting-state & naturalistic"
        description="Datasets featuring resting-state paradigms, movies, or naturalistic stimuli."
      >
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {restingDatasets.length ? (
            restingDatasets.map((dataset) => <ExplorerDatasetCard key={`rest-${dataset.id}`} dataset={dataset} variant="compact" />)
          ) : (
            <EmptySection message="No resting-state sets in this slice; try searching for resting-state keywords." />
          )}
        </div>
        </ExplorerSection>
      ) : null}

      {showDiscoverySections && topModalities.length > 0 && (
        <ExplorerSection title="Explore by modality" description="Jump into datasets by acquisition modality or data type.">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {topModalities.map((facet) => (
              <ModalityCard
                key={facet.value}
                modality={facet.value}
                count={facet.count}
                onView={() => {
                  const next = selectedModalities.includes(facet.value)
                    ? selectedModalities.filter((entry) => entry !== facet.value)
                    : [...selectedModalities, facet.value]
                  setSelectedModalities(next)
                  const params = new URLSearchParams()
                  if (searchValue.trim()) params.set('q', searchValue.trim())
                  appendNumericFilters(params, numericFilters)
                  appendModalities(params, next)
                  appendPickerParams(params)
                  const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
                  router.push(nextUrl)
                }}
              />
            ))}
          </div>
        </ExplorerSection>
      )}

      <ExplorerSection title={pickMode ? 'Pick a dataset' : 'Browse the catalog'} description={pickMode ? 'Choose a dataset to continue in Studio.' : 'Toggle view and sort order for a broader slice of the dataset catalog.'}>
        <div className="flex flex-wrap items-center gap-4 rounded-xl border bg-card px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Sort by</span>
            <select
              value={sortKey}
              onChange={(event) => setSortKey(event.target.value as SortKey)}
              className="rounded-md border border-input bg-background px-2 py-1 text-sm"
            >
              <option value="featured">Featured</option>
              <option value="subjects">Subject count</option>
              <option value="updated">Recently updated</option>
              <option value="alpha">A–Z</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <Button variant={viewMode === 'grid' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('grid')}>
              <LayoutGrid className="mr-2 h-4 w-4" />
              Grid
            </Button>
            <Button variant={viewMode === 'list' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('list')}>
              <Rows3 className="mr-2 h-4 w-4" />
              List
            </Button>
          </div>
          <div className="ml-auto text-sm text-muted-foreground">{sortedCatalog.length} datasets in view</div>
        </div>

        {viewMode === 'grid' ? (
          <div className="mt-6 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            {sortedCatalog.map((dataset) => (
              <ExplorerDatasetCard
                key={`grid-${dataset.id}`}
                dataset={dataset}
                variant="standard"
                pickMode={pickMode}
                pickHref={pickMode ? buildPickHref(dataset.id) : undefined}
              />
            ))}
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            {sortedCatalog.map((dataset) => (
              <ExplorerDatasetCard
                key={`list-${dataset.id}`}
                dataset={dataset}
                variant="list"
                pickMode={pickMode}
                pickHref={pickMode ? buildPickHref(dataset.id) : undefined}
              />
            ))}
          </div>
        )}

        <div className="mt-6 flex flex-col items-center gap-3">
          {initialLoadError && (
            <Alert variant="destructive" className="w-full max-w-xl">
              <AlertDescription>{initialLoadError}</AlertDescription>
            </Alert>
          )}
          {loadMoreError && (
            <Alert variant="destructive" className="w-full max-w-xl">
              <AlertDescription>{loadMoreError}</AlertDescription>
            </Alert>
          )}
          {hasMoreCatalog ? (
            <Button variant="outline" onClick={loadMoreCatalog} disabled={loadingMore}>
              {loadingMore ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Loading datasets…
                </>
              ) : (
                'Load more datasets'
              )}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              Showing all {sortedCatalog.length.toLocaleString()} catalog datasets.
            </p>
          )}
        </div>
      </ExplorerSection>
    </div>
  )
}

function ExplorerSection({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{title}</h2>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  )
}

function ExplorerDatasetCard({
  dataset,
  variant,
  pickMode,
  pickHref,
}: {
  dataset: DatasetCardResponse
  variant: 'standard' | 'compact' | 'list'
  pickMode?: boolean
  pickHref?: string
}) {
  const tags = dataset.tags.slice(0, variant === 'standard' ? 4 : 2)
  const lastUpdated = dataset.updated_at ?? dataset.created_at
  const isList = variant === 'list'
  const previewHref =
    pickMode && pickHref
      ? `/datasets/${encodeURIComponent(dataset.id)}?pick=1&returnTo=${encodeURIComponent(pickHref)}`
      : `/datasets/${encodeURIComponent(dataset.id)}`
  return (
    <div
      className={cn(
        'group relative rounded-2xl border bg-card p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg',
        isList ? 'flex flex-col gap-3 md:flex-row md:items-center' : 'flex flex-col',
        variant === 'standard' ? 'min-h-[220px]' : 'min-h-[160px]',
      )}
    >
      <div className={cn('flex items-start justify-between gap-3 w-full')}>
        <div>
          <div className="text-sm font-medium text-muted-foreground">{dataset.source_repo}</div>
          <h3 className="text-lg font-semibold leading-tight">{dataset.name}</h3>
        </div>
        {dataset.category && dataset.category.toLowerCase() !== dataset.source_repo.toLowerCase() && (
          <Badge variant="outline" className="text-xs capitalize">
            {dataset.category}
          </Badge>
        )}
      </div>
      <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">{dataset.description || 'No description available.'}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{dataset.subjects_count ?? '—'} subjects</span>
        {dataset.modalities.length > 0 && <span>{dataset.modalities.join(', ')}</span>}
        {lastUpdated && <span>Updated {new Date(lastUpdated).toLocaleDateString()}</span>}
      </div>
      {tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {tags.map((tag) => (
            <Badge key={`${dataset.id}-${tag}`} variant="outline" className="text-xs">
              {tag}
            </Badge>
          ))}
        </div>
      )}
      <div className={cn('flex flex-wrap items-center gap-3', isList ? 'mt-2' : 'mt-4')}>
        <Link
          href={previewHref}
          className={cn('inline-flex items-center text-sm font-medium text-primary hover:underline')}
        >
          {pickMode ? 'Preview dataset' : 'View dataset'}
          <ExternalLink className="ml-1 h-3.5 w-3.5" />
        </Link>
        {pickMode && pickHref ? (
          <Button asChild size="sm" variant="secondary" className="ml-auto">
            <Link href={pickHref}>Add to Plan</Link>
          </Button>
        ) : !pickMode ? (
          <Button asChild size="sm" variant="secondary" className="ml-auto">
            <Link href={`/studio?tab=plan&datasetId=${encodeURIComponent(dataset.id)}`}>
              Add to Plan
            </Link>
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function ModalityCard({ modality, count, onView }: { modality: string; count: number; onView: () => void }) {
  return (
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">Modality</p>
      <h3 className="text-xl font-semibold capitalize">{modality}</h3>
      <p className="text-sm text-muted-foreground">{count} datasets</p>
      <Button variant="ghost" size="sm" className="mt-3 px-0 text-primary" onClick={onView}>
        Explore
        <ArrowRight className="ml-1 h-4 w-4" />
      </Button>
    </div>
  )
}

function mergeDatasets(existing: DatasetCardResponse[], incoming: DatasetCardResponse[]) {
  const map = new Map(existing.map((dataset) => [dataset.id, dataset]))
  incoming.forEach((dataset) => map.set(dataset.id, dataset))
  return Array.from(map.values())
}

function summarizeFacetsFromDatasets(datasets: DatasetCardResponse[]): FacetValueResponse[] {
  const counts = new Map<string, number>()
  datasets.forEach((dataset) => {
    const key = dataset.category || 'Uncategorized'
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return Array.from(counts.entries()).map(([value, count]) => ({ value, count }))
}

function sortDatasets(datasets: DatasetCardResponse[], key: SortKey): DatasetCardResponse[] {
  const sorted = [...datasets]
  switch (key) {
    case 'subjects':
      return sorted.sort((a, b) => (b.subjects_count ?? 0) - (a.subjects_count ?? 0))
    case 'updated':
      return sorted.sort(
        (a, b) => new Date(b.updated_at ?? b.created_at ?? 0).getTime() - new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
      )
    case 'alpha':
      return sorted.sort((a, b) => a.name.localeCompare(b.name))
    default:
      return sorted
  }
}

function EmptySection({ message }: { message: string }) {
  return <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-center text-sm text-muted-foreground">{message}</p>
}
