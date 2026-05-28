'use client'

import { useEffect, useMemo, useRef, useState, FormEvent } from 'react'
import { Search, RefreshCw, Loader2, X, ChevronDown, Info } from 'lucide-react'
import { DatasetCardResponse, DatasetSearchResponse, FacetValueResponse } from '@/types/datasets-search'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { serviceEndpoints } from '@/lib/service-endpoints'
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

interface CatalogFinderProps {
  initialResults: DatasetSearchResponse
  apiBase: string
  basePath?: string
  initialQuery?: string
  initialFilters?: NumericFilters
  initialParseErrors?: string[]
  normalizeUrl?: boolean
}

interface FilterState {
  modalities: Set<string>
  access_type: Set<string>
  category: Set<string>
}

const MODALITY_FACET = 'modalities'
const ACCESS_FACET = 'access_type'
const CATEGORY_FACET = 'category'
const DEFAULT_FETCH_LIMIT = 60

export function CatalogFinder({
  initialResults,
  apiBase,
  basePath = '/finder/datasets',
  initialQuery = '',
  initialFilters,
  initialParseErrors,
  normalizeUrl = false,
}: CatalogFinderProps) {
  const router = useRouter()
  const [searchInput, setSearchInput] = useState(initialQuery)
  const [query, setQuery] = useState(initialQuery)
  const [searchNonce, setSearchNonce] = useState(0)
  const [results, setResults] = useState<DatasetSearchResponse>(initialResults)
  const [numericFilters, setNumericFilters] = useState<NumericFilters>(initialFilters ?? {})
  const [numericInputs, setNumericInputs] = useState<NumericInputState>(() => numericInputsFromFilters(initialFilters ?? {}))
  const [numericInputErrors, setNumericInputErrors] = useState<string[]>([])
  const [parseErrors, setParseErrors] = useState<string[]>(initialParseErrors ?? [])
  const [warnings, setWarnings] = useState<string[]>(initialResults.warnings ?? [])
  const [isSearching, setIsSearching] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [assistantLoading, setAssistantLoading] = useState(false)
  const normalizedRef = useRef(false)
  const sessionIdRef = useRef<string | null>(null)

  const summarize = (d: DatasetCardResponse) => {
    const desc = (d.description || '').replace(/\s+/g, ' ').slice(0, 140)
    const tasks = d.tasks?.length ? ` tasks: ${d.tasks.slice(0, 3).join(', ')}` : ''
    const mods = d.modalities?.length ? ` mods: ${d.modalities.join(', ')}` : ''
    const subs = d.subjects_count != null ? ` subjects: ${d.subjects_count}` : ''
    return `${d.name} (id: ${d.id}${mods}${subs}); ${desc}${tasks}`.trim()
  }

  const fetchTopSummaries = async (q: string) => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 1500)
    try {
      const params = new URLSearchParams({ limit: '5', offset: '0' })
      if (q) params.set('q', q)
      appendNumericFilters(params, numericFilters)
      const resp = await fetch(`${apiBase}/search?${params.toString()}`, { cache: 'no-store', signal: controller.signal })
      if (!resp.ok) return null
      const data: DatasetSearchResponse = await resp.json()
      return (data.datasets || []).slice(0, 5).map(summarize)
    } catch (e) {
      return null
    } finally {
      clearTimeout(timeout)
    }
  }
  const [filters, setFilters] = useState<FilterState>({
    modalities: new Set(),
    access_type: new Set(),
    category: new Set(),
  })

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

  const facetValues = useMemo(() => ({
    modalities: results.facets[MODALITY_FACET] ?? [],
    access_type: results.facets[ACCESS_FACET] ?? [],
    category: results.facets[CATEGORY_FACET] ?? [],
  }), [results])
  const filterChips = useMemo(() => buildFilterChips(numericFilters), [numericFilters])
  const trUnavailable = warnings.some((warning) => warning.toLowerCase().includes('tr filters'))
  const voxelUnavailable = warnings.some((warning) => warning.toLowerCase().includes('voxel size filters'))

  const buildTrackingQuery = (textQuery: string, filtersToRender: NumericFilters) => {
    const cleanedQuery = textQuery.trim()
    const chips = buildFilterChips(filtersToRender)
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
    const params = buildRouteParams({ query, filters, numericFilters: next })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const applyNumericFilters = () => {
    const { filters: parsedFilters, errors } = numericFiltersFromInputs(numericInputs)
    if (errors.length > 0) {
      setNumericInputErrors(errors)
      return
    }
    setNumericInputErrors([])
    setNumericFilters(parsedFilters)
    const params = buildRouteParams({
      query,
      filters,
      numericFilters: parsedFilters,
    })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
    void trackSearch(buildTrackingQuery(query, parsedFilters))
  }

  const clearNumericFilters = () => {
    const cleared: NumericFilters = {}
    setNumericInputs(numericInputsFromFilters(cleared))
    setNumericInputErrors([])
    setNumericFilters(cleared)
    const params = buildRouteParams({ query, filters, numericFilters: cleared })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  const updateNumericInput = (key: keyof NumericInputState) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setNumericInputs((prev) => ({ ...prev, [key]: event.target.value }))
  }

  const clearAllFilters = () => {
    setSearchInput('')
    setQuery('')
    setFilters({
      modalities: new Set(),
      access_type: new Set(),
      category: new Set(),
    })
    setNumericFilters({})
    setNumericInputs(numericInputsFromFilters({}))
    setParseErrors([])
    setNumericInputErrors([])
    setWarnings([])
    router.push(basePath)
  }

  useEffect(() => {
    setSearchInput(initialQuery)
    setQuery(initialQuery)
    setResults(initialResults)
    setNumericFilters(initialFilters ?? {})
    setNumericInputs(numericInputsFromFilters(initialFilters ?? {}))
    setNumericInputErrors([])
    setParseErrors(initialParseErrors ?? [])
    setWarnings(initialResults.warnings ?? [])
  }, [initialQuery, initialFilters, initialParseErrors, initialResults])

  useEffect(() => {
    setNumericInputs(numericInputsFromFilters(numericFilters))
  }, [numericFilters])

  useEffect(() => {
    if (!normalizeUrl || normalizedRef.current) return
    normalizedRef.current = true
    const params = buildRouteParams({
      query,
      filters,
      numericFilters,
    })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.replace(nextUrl)
  }, [basePath, normalizeUrl, numericFilters, query, filters, router])

  useEffect(() => {
    const controller = new AbortController()

    const runSearch = async () => {
      setIsSearching(true)
      try {
        const params = buildSearchParams({
          offset: 0,
          limit: DEFAULT_FETCH_LIMIT,
          query,
          filters,
          numericFilters,
        })
        const response = await fetch(`${apiBase}/search?${params.toString()}`, {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Failed to search datasets (${response.status})`)
        const data: DatasetSearchResponse = await response.json()
        setResults(data)
        setWarnings(data.warnings ?? [])
      } catch (error) {
        if ((error as Error).name !== 'AbortError') {
          console.error('Dataset search failed; falling back to previous results', error)
          // Keep prior results instead of blanking the UI
        }
      } finally {
        setIsSearching(false)
      }
    }

    runSearch()

    return () => controller.abort()
  }, [apiBase, filters, numericFilters, query, searchNonce])

  const handleLoadMore = async () => {
    if (!results.has_more || loadingMore) return
    setLoadingMore(true)
    try {
      const params = buildSearchParams({
        offset: results.datasets.length,
        limit: DEFAULT_FETCH_LIMIT,
        query,
        filters,
        numericFilters,
      })
      const response = await fetch(`${apiBase}/search?${params.toString()}`, { cache: 'no-store' })
      if (!response.ok) throw new Error('Failed to fetch additional datasets')
      const data: DatasetSearchResponse = await response.json()
      setWarnings(data.warnings ?? warnings)
      setResults((prev) => ({
        ...prev,
        datasets: mergeDatasets(prev.datasets, data.datasets),
        has_more: data.has_more,
        total: data.total,
        last_updated: data.last_updated,
        facets: data.facets,
        offset: prev.datasets.length + data.datasets.length,
        limit: data.limit,
      }))
    } catch (error) {
      console.error('Failed to load more datasets', error)
    } finally {
      setLoadingMore(false)
    }
  }

  const handleSearchSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const parsed = parseInlineFilters(searchInput)
    const mergedFilters = mergeNumericFilters(numericFilters, parsed.filters)
    setParseErrors(parsed.errors)
    setNumericFilters(mergedFilters)
    setSearchInput(parsed.query)
    const nextQuery = parsed.query.trim()
    if (nextQuery === query) {
      setSearchNonce((prev) => prev + 1)
    } else {
      setQuery(nextQuery)
    }
    const params = buildRouteParams({
      query: nextQuery,
      filters,
      numericFilters: mergedFilters,
    })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
    void trackSearch(buildTrackingQuery(nextQuery, mergedFilters))
  }

  const toggleFilter = (facet: keyof FilterState, value: string) => {
    const next = new Set(filters[facet])
    if (next.has(value)) {
      next.delete(value)
    } else {
      next.add(value)
    }
    const nextFilters = { ...filters, [facet]: next }
    setFilters(nextFilters)
    const params = buildRouteParams({ query, filters: nextFilters, numericFilters })
    const nextUrl = params.toString() ? `${basePath}?${params.toString()}` : basePath
    router.push(nextUrl)
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-4">
          <form className="flex flex-col gap-3 sm:flex-row sm:items-center" onSubmit={handleSearchSubmit}>
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search by task, modality, center, or condition"
                className="pl-10 pr-4 text-base"
              />
            </div>
            <Button type="submit" disabled={isSearching} className="sm:w-auto">
              Search
            </Button>
            <Button
              type="button"
              variant="outline"
              className="sm:w-auto"
              disabled={assistantLoading}
              onClick={async () => {
                const q = searchInput.trim()
                setAssistantLoading(true)
                try {
                  const lines = await fetchTopSummaries(q)
                  const prompt =
                    `Use ONLY the Brain Researcher dataset catalog results below (no external web) before answering. ` +
                    (q ? `User intent: ${q}. ` : '') +
                    (lines?.length ? `Top matches:\n${lines.join('\n')}` : 'No local matches; propose better filters to find relevant datasets.')
	                  const url = `/studio?prompt=${encodeURIComponent(prompt)}`
	                  router.push(url)
	                  setTimeout(() => {
	                    if (window.location.pathname !== '/studio') window.location.href = url
	                  }, 50)
                } catch (e) {
                  const fallback = q
                    ? `Dataset help: find datasets matching "${q}" using the internal catalog (no web).`
                    : 'Dataset help: suggest datasets using the internal catalog (no web).'
	                  const url = `/studio?prompt=${encodeURIComponent(fallback)}`
	                  router.push(url)
	                  setTimeout(() => {
	                    if (window.location.pathname !== '/studio') window.location.href = url
	                  }, 50)
                } finally {
                  setAssistantLoading(false)
                }
              }}
            >
              Ask assistant
            </Button>
          </form>
          <Collapsible defaultOpen={false} className="rounded-xl border bg-muted/20 p-3">
            <div className="flex items-center justify-between">
              <CollapsibleTrigger className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-muted-foreground">
                Numeric filters
                <span title="Add numeric constraints (subjects, age, TR, voxel size). Applied as URL parameters.">
                  <Info className="h-3 w-3" />
                </span>
                {filterChips.length > 0 && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-foreground">
                    {filterChips.length} active
                  </span>
                )}
                <ChevronDown className="h-3 w-3" />
              </CollapsibleTrigger>
              <Button type="button" variant="ghost" className="h-7 text-[11px]" onClick={clearAllFilters}>
                Clear all filters
              </Button>
            </div>
            <CollapsibleContent className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <Input
                  type="number"
                  inputMode="numeric"
                  placeholder="N min"
                  value={numericInputs.min_subjects}
                  onChange={updateNumericInput('min_subjects')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="numeric"
                  placeholder="N max"
                  value={numericInputs.max_subjects}
                  onChange={updateNumericInput('max_subjects')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  placeholder="Age min (y)"
                  value={numericInputs.age_min}
                  onChange={updateNumericInput('age_min')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  placeholder="Age max (y)"
                  value={numericInputs.age_max}
                  onChange={updateNumericInput('age_max')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  placeholder="TR min (s)"
                  value={numericInputs.tr_min}
                  onChange={updateNumericInput('tr_min')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  placeholder="TR max (s)"
                  value={numericInputs.tr_max}
                  onChange={updateNumericInput('tr_max')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  step="0.1"
                  placeholder="Voxel min (mm)"
                  value={numericInputs.voxel_min}
                  onChange={updateNumericInput('voxel_min')}
                  className="h-8"
                />
                <Input
                  type="number"
                  inputMode="decimal"
                  step="0.1"
                  placeholder="Voxel max (mm)"
                  value={numericInputs.voxel_max}
                  onChange={updateNumericInput('voxel_max')}
                  className="h-8"
                />
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant="secondary" className="h-8 text-xs" onClick={applyNumericFilters}>
                  Apply filters
                </Button>
                <Button type="button" variant="ghost" className="h-8 text-xs" onClick={clearNumericFilters}>
                  Clear numeric
                </Button>
              </div>
              {(trUnavailable || voxelUnavailable) && (
                <div className="text-[11px] text-amber-600">
                  {trUnavailable && <div>TR filters are not available in the current catalog.</div>}
                  {voxelUnavailable && <div>Voxel filters are not available in the current catalog.</div>}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
          {filterChips.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="text-[10px] uppercase tracking-widest">Parsed filters</span>
              {filterChips.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  onClick={() => clearFilter(chip.clearKeys)}
                  className="inline-flex items-center gap-1 rounded-full border border-muted px-2 py-1 text-xs text-foreground hover:bg-muted"
                >
                  {chip.label}
                  <X className="h-3 w-3" />
                </button>
              ))}
            </div>
          )}
          {parseErrors.length > 0 && (
            <div className="text-xs text-red-600">
              {parseErrors.map((err) => (
                <div key={err}>{err}</div>
              ))}
            </div>
          )}
          {numericInputErrors.length > 0 && (
            <div className="text-xs text-red-600">
              {numericInputErrors.map((err) => (
                <div key={err}>{err}</div>
              ))}
            </div>
          )}
          {warnings.length > 0 && (
            <div className="text-xs text-amber-600">
              {warnings.map((warning) => (
                <div key={warning}>{warning}</div>
              ))}
            </div>
          )}
          <FilterChips
            title="Modalities"
            facet={facetValues.modalities}
            active={filters.modalities}
            onToggle={(value) => toggleFilter('modalities', value)}
          />
          <FilterChips
            title="Categories"
            facet={facetValues.category}
            active={filters.category}
            onToggle={(value) => toggleFilter('category', value)}
          />
          <FilterChips
            title="Access"
            facet={facetValues.access_type}
            active={filters.access_type}
            onToggle={(value) => toggleFilter('access_type', value)}
          />
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Showing {results.datasets.length} of {results.total} datasets • refreshed {new Date(results.last_updated).toLocaleString()}
        </span>
        <Button variant="ghost" size="sm" disabled={isSearching} onClick={() => setSearchNonce((prev) => prev + 1)}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isSearching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {results.datasets.map((dataset) => (
          <DatasetSummaryCard key={dataset.id} dataset={dataset} />
        ))}
      </div>

      {results.has_more && (
        <div className="mt-6 flex justify-center">
          <Button variant="outline" onClick={handleLoadMore} disabled={loadingMore}>
            {loadingMore ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading more datasets…
              </>
            ) : (
              'Load more results'
            )}
          </Button>
        </div>
      )}
    </div>
  )
}

function buildSearchParams({
  offset,
  limit,
  query,
  filters,
  numericFilters,
}: {
  offset: number
  limit: number
  query: string
  filters: FilterState
  numericFilters: NumericFilters
}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (query) params.set('q', query)
  addFilterParams(params, 'modalities', filters.modalities)
  addFilterParams(params, 'access_type', filters.access_type)
  addFilterParams(params, 'category', filters.category)
  appendNumericFilters(params, numericFilters)
  return params
}

function buildRouteParams({ query, filters, numericFilters }: { query: string; filters: FilterState; numericFilters: NumericFilters }) {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  addFilterParams(params, 'modalities', filters.modalities)
  addFilterParams(params, 'access_type', filters.access_type)
  addFilterParams(params, 'category', filters.category)
  appendNumericFilters(params, numericFilters)
  return params
}

function addFilterParams(params: URLSearchParams, key: string, values: Set<string>) {
  if (values.size === 0) return
  values.forEach((value) => params.append(key, value))
}

function mergeDatasets(existing: DatasetCardResponse[], incoming: DatasetCardResponse[]) {
  const map = new Map(existing.map((dataset) => [dataset.id, dataset]))
  incoming.forEach((dataset) => map.set(dataset.id, dataset))
  return Array.from(map.values())
}

interface FilterChipsProps {
  title: string
  facet: FacetValueResponse[]
  active: Set<string>
  onToggle: (value: string) => void
}

function FilterChips({ title, facet, active, onToggle }: FilterChipsProps) {
  if (!facet.length) return null
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="flex flex-wrap gap-2">
        {facet.map((entry) => (
          <Badge
            key={entry.value}
            variant={active.has(entry.value) ? 'default' : 'outline'}
            className="cursor-pointer select-none"
            onClick={() => onToggle(entry.value)}
          >
            {entry.value}
            <span className="ml-1 text-[10px] opacity-70">{entry.count}</span>
          </Badge>
        ))}
      </div>
    </div>
  )
}

interface DatasetSummaryCardProps {
  dataset: DatasetCardResponse
}

function DatasetSummaryCard({ dataset }: DatasetSummaryCardProps) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm transition hover:shadow-md">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="font-semibold">{dataset.name}</div>
          <div className="flex items-center gap-2">
            {dataset.category && dataset.category.toLowerCase() !== dataset.source_repo.toLowerCase() && (
              <Badge variant="outline" className="text-xs">
                {dataset.category}
              </Badge>
            )}
            <Badge variant="secondary">{dataset.source_repo}</Badge>
          </div>
        </div>
        <p className="text-sm text-muted-foreground line-clamp-3">{dataset.description}</p>
        <div className="text-xs text-muted-foreground">
          {dataset.subjects_count ?? '—'} subjects • {dataset.modalities.join(', ')}
        </div>
        <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
          {dataset.tags.slice(0, 4).map((tag) => (
            <Badge key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
        </div>
        <div className="flex items-center justify-between pt-2 text-sm">
          <span className="text-muted-foreground capitalize">{dataset.access_type}</span>
          <Link href={`/finder/datasets/${dataset.id}`} className="text-primary hover:underline">
            View details
          </Link>
        </div>
      </div>
    </div>
  )
}
