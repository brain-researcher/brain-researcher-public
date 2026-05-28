"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { ArrowUpDown, Grid, List, Search, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { DatasetCard } from './dataset-card'
import { DatasetFiltersComponent } from './dataset-filters'
import { DatasetDrawer } from './dataset-drawer'
import { Dataset, DatasetFilters } from '@/types/dataset'
import { getDatasets } from '@/lib/datasets'
import type { FacetValueResponse } from '@/types/datasets-search'
import { useRouter } from 'next/navigation'

const ITEMS_PER_PAGE = 12

export function DatasetExplorer() {
  const router = useRouter()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [searchQuery, setSearchQuery] = useState('')
  
  const [filters, setFilters] = useState<DatasetFilters>({})
  const [sortBy, setSortBy] = useState<'popularity' | 'nSubjects' | 'lastUpdated' | 'name'>('popularity')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  
  // Cache for dataset queries
  const cacheRef = useRef<Map<string, { data: { datasets: Dataset[]; total: number; facets?: Record<string, FacetValueResponse[]> }, timestamp: number }>>(new Map())
  const CACHE_DURATION = 5 * 60 * 1000 // 5 minutes
  
  // Debounced search
  const debounceTimerRef = useRef<NodeJS.Timeout>()
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  
  // Debounce search query
  useEffect(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }
    
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery)
    }, 300)
    
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }
    }
  }, [searchQuery])

  // Memoized cache key generation
  const getCacheKey = useCallback((searchQuery: string, filters: DatasetFilters, sortBy: string, sortDirection: string, currentPage: number) => {
    return JSON.stringify({ searchQuery, filters, sortBy, sortDirection, currentPage })
  }, [])

  // Optimized fetch function with caching
  const fetchDatasets = useCallback(async () => {
    const cacheKey = getCacheKey(debouncedSearchQuery, filters, sortBy, sortDirection, currentPage)
    const cachedResult = cacheRef.current.get(cacheKey)
    
    // Check cache first
    if (cachedResult && Date.now() - cachedResult.timestamp < CACHE_DURATION) {
      setDatasets(cachedResult.data.datasets)
      setTotal(cachedResult.data.total)
      setCategoryFacets(cachedResult.data.facets?.category ?? [])
      setLoading(false)
      return
    }
    
    setLoading(true)
    
    try {
      const result = await getDatasets({
        ...filters,
        search: debouncedSearchQuery || undefined,
        sortBy,
        sortDirection,
        limit: ITEMS_PER_PAGE,
        offset: (currentPage - 1) * ITEMS_PER_PAGE
      })
      
      // Cache the result
      cacheRef.current.set(cacheKey, {
        data: result,
        timestamp: Date.now()
      })
      
      // Clean up old cache entries
      if (cacheRef.current.size > 50) {
        const oldestKey = Array.from(cacheRef.current.keys())[0]
        cacheRef.current.delete(oldestKey)
      }
      
      setDatasets(result.datasets)
      setTotal(result.total)
      setCategoryFacets(result.facets?.category ?? [])
    } catch (error) {
      console.error('Failed to fetch datasets:', error)
      setDatasets([])
      setTotal(0)
      setCategoryFacets([])
    } finally {
      setLoading(false)
    }
  }, [debouncedSearchQuery, filters, sortBy, sortDirection, currentPage, getCacheKey])

  // Fetch datasets when dependencies change
  useEffect(() => {
    fetchDatasets()
  }, [fetchDatasets])

  // Reset to first page when search or filters change
  useEffect(() => {
    setCurrentPage(1)
  }, [debouncedSearchQuery, filters, sortBy, sortDirection])

  // Memoized handlers for better performance
  const handleFiltersChange = useCallback((newFilters: DatasetFilters) => {
    setFilters(newFilters)
  }, [])

  const handleClearFilters = useCallback(() => {
    setFilters({})
    setSearchQuery('')
  }, [])

  const handleSortChange = useCallback((field: typeof sortBy) => {
    if (field === sortBy) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(field)
      setSortDirection('desc')
    }
  }, [sortBy, sortDirection])

  const handleRunDemo = useCallback((dataset: Dataset) => {
    // Navigate to chat with dataset-specific prompt
    const prompt = `Run an analysis on the ${dataset.name} dataset`
    router.push(`/studio?prompt=${encodeURIComponent(prompt)}&datasetId=${dataset.id}`)
  }, [router])

  const handleViewDetails = useCallback((dataset: Dataset) => {
    setSelectedDataset(dataset)
    setDrawerOpen(true)
  }, [])

  const totalPages = Math.ceil(total / ITEMS_PER_PAGE)

  const fallbackCategorySummary = useMemo(() => {
    const counts = new Map<string, number>()
    datasets.forEach((dataset) => {
      const key = dataset.category || 'Uncategorized'
      counts.set(key, (counts.get(key) || 0) + 1)
    })
    return Array.from(counts.entries()).map(([value, count]) => ({ value, count }))
  }, [datasets])

  const categorySummary = categoryFacets.length ? categoryFacets : fallbackCategorySummary

  const sortOptions = [
    { value: 'popularity', label: 'Popularity' },
    { value: 'nSubjects', label: 'Subject Count' },
    { value: 'lastUpdated', label: 'Last Updated' },
    { value: 'name', label: 'Name' }
  ]

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Dataset Explorer</h1>
        <p className="text-muted-foreground mb-4">
          Discover and explore neuroimaging datasets from OpenNeuro, HCP, ABCD, and more
        </p>
        
        {/* Quick Search */}
        <div className="max-w-md">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search datasets..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
            {loading && debouncedSearchQuery && (
              <Loader2 className="absolute right-3 top-1/2 transform -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>
        </div>
      </div>

      {/* Filters */}
      <DatasetFiltersComponent
        filters={filters}
        onFiltersChange={handleFiltersChange}
        onClearFilters={handleClearFilters}
      />

      {categorySummary.length > 0 && (
        <div className="mb-6 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-muted-foreground">Category Breakdown</p>
              <p className="text-xs text-muted-foreground">Snapshot from catalog facets</p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {categorySummary.map(({ value, count }) => (
              <Badge key={`${value}`} variant="outline" className="text-xs">
                {value}
                <span className="ml-1 text-muted-foreground">({count})</span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="text-sm text-muted-foreground">
            {loading ? 'Loading...' : `${total.toLocaleString()} datasets found`}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Sort dropdown */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Sort by:</span>
            <div className="flex">
              {sortOptions.map((option) => (
                <Button
                  key={option.value}
                  variant={sortBy === option.value ? "default" : "ghost"}
                  size="sm"
                  onClick={() => handleSortChange(option.value as any)}
                  className="flex items-center gap-1"
                >
                  {option.label}
                  {sortBy === option.value && (
                    <ArrowUpDown className={`h-3 w-3 ${sortDirection === 'desc' ? 'rotate-180' : ''}`} />
                  )}
                </Button>
              ))}
            </div>
          </div>

          {/* View mode toggle */}
          <div className="flex border rounded-lg">
            <Button
              variant={viewMode === 'grid' ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode('grid')}
              className="rounded-r-none"
            >
              <Grid className="h-4 w-4" />
            </Button>
            <Button
              variant={viewMode === 'list' ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode('list')}
              className="rounded-l-none"
            >
              <List className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Dataset grid/list */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-80 bg-muted animate-pulse rounded-lg" />
          ))}
        </div>
      ) : datasets.length > 0 ? (
        <div className={
          viewMode === 'grid' 
            ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"
            : "space-y-4"
        }>
          {datasets.map((dataset) => (
            <DatasetCard
              key={dataset.id}
              dataset={dataset}
              onRunDemo={handleRunDemo}
              onViewDetails={handleViewDetails}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <div className="text-muted-foreground mb-4">No datasets found matching your criteria</div>
          <Button onClick={handleClearFilters} variant="outline">
            Clear filters
          </Button>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            Previous
          </Button>
          
          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const page = i + 1
              return (
                <Button
                  key={page}
                  variant={currentPage === page ? "default" : "outline"}
                  size="sm"
                  onClick={() => setCurrentPage(page)}
                >
                  {page}
                </Button>
              )
            })}
            
            {totalPages > 5 && (
              <>
                <span className="px-2">...</span>
                <Button
                  variant={currentPage === totalPages ? "default" : "outline"}
                  size="sm"
                  onClick={() => setCurrentPage(totalPages)}
                >
                  {totalPages}
                </Button>
              </>
            )}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            Next
          </Button>
        </div>
      )}

      {/* Dataset details drawer */}
      <DatasetDrawer
        dataset={selectedDataset}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onRunDemo={handleRunDemo}
      />
    </div>
  )
}
  const [categoryFacets, setCategoryFacets] = useState<FacetValueResponse[]>([])
