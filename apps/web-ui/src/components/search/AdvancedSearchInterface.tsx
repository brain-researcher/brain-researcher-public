'use client'

import React, { useState, useMemo, useRef } from 'react'
import { 
  Search, Filter, Plus, Minus, X, Save, History,
  Download, Share2, BarChart3, Calendar, Tag,
  FileText, Database, Brain, Users, Settings,
  ChevronDown, ChevronRight, Clock, Star,
  TrendingUp, AlertCircle, CheckCircle, Info,
  Zap, RefreshCw, Copy, ExternalLink, Sparkles
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { useDebounce } from '@/hooks/use-debounce'

interface SearchQuery {
  id: string
  text: string
  field?: string
  operator: 'AND' | 'OR' | 'NOT'
  group?: string
}

interface SearchFilter {
  field: string
  operator: 'equals' | 'contains' | 'startsWith' | 'endsWith' | 'gt' | 'lt' | 'between'
  value: any
  label?: string
}

interface SearchResult {
  id: string
  title: string
  type: 'dataset' | 'analysis' | 'publication' | 'concept' | 'task'
  description?: string
  relevance: number
  metadata?: Record<string, any>
  highlights?: string[]
  tags?: string[]
}

interface SavedSearch {
  id: string
  name: string
  query: SearchQuery[]
  filters: SearchFilter[]
  createdAt: Date
  lastUsed?: Date
  resultCount?: number
  shared?: boolean
}

interface SearchAnalytics {
  totalSearches: number
  avgResponseTime: number
  popularQueries: { query: string; count: number }[]
  searchTrends: { date: Date; count: number }[]
  conversionRate: number
}

const SEARCH_FIELDS = [
  { value: 'all', label: 'All Fields', icon: <Database className="w-4 h-4" /> },
  { value: 'title', label: 'Title', icon: <FileText className="w-4 h-4" /> },
  { value: 'description', label: 'Description', icon: <FileText className="w-4 h-4" /> },
  { value: 'author', label: 'Author', icon: <Users className="w-4 h-4" /> },
  { value: 'tags', label: 'Tags', icon: <Tag className="w-4 h-4" /> },
  { value: 'content', label: 'Content', icon: <FileText className="w-4 h-4" /> },
  { value: 'metadata', label: 'Metadata', icon: <Settings className="w-4 h-4" /> }
]

const OPERATORS = [
  { value: 'AND', label: 'AND', color: 'bg-blue-100 text-blue-700' },
  { value: 'OR', label: 'OR', color: 'bg-green-100 text-green-700' },
  { value: 'NOT', label: 'NOT', color: 'bg-red-100 text-red-700' }
]

export function AdvancedSearchInterface({
  onSearch,
  onResultClick,
  className
}: {
  onSearch?: (query: SearchQuery[], filters: SearchFilter[]) => void
  onResultClick?: (result: SearchResult) => void
  className?: string
}) {
  const { toast } = useToast()
  const [queries, setQueries] = useState<SearchQuery[]>([
    { id: '1', text: '', operator: 'AND' }
  ])
  const [filters, setFilters] = useState<SearchFilter[]>([])
  const [results, setResults] = useState<SearchResult[]>([])
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([])
  const [searchHistory, setSearchHistory] = useState<string[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [showSaved, setShowSaved] = useState(false)
  const [showAnalytics, setShowAnalytics] = useState(false)
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set())
  const [sortBy, setSortBy] = useState<'relevance' | 'date' | 'title'>('relevance')
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list')
  const [searchStats, setSearchStats] = useState({
    totalSearches: 0,
    successfulSearches: 0,
    avgResponseTime: 0
  })

  const analytics: SearchAnalytics = useMemo(() => {
    const counts = new Map<string, number>()
    searchHistory.forEach((entry) => {
      const query = entry.trim()
      if (!query) return
      counts.set(query, (counts.get(query) ?? 0) + 1)
    })

    const popularQueries = Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([query, count]) => ({ query, count }))

    return {
      totalSearches: searchStats.totalSearches,
      avgResponseTime: Math.round(searchStats.avgResponseTime),
      popularQueries,
      searchTrends: [],
      conversionRate: searchStats.totalSearches
        ? searchStats.successfulSearches / searchStats.totalSearches
        : 0
    }
  }, [searchHistory, searchStats])

  const searchInputRef = useRef<HTMLInputElement>(null)
  const debouncedSearch = useDebounce(performSearch, 300)

  // Add query row
  const addQuery = () => {
    const newQuery: SearchQuery = {
      id: Date.now().toString(),
      text: '',
      operator: 'AND'
    }
    setQueries([...queries, newQuery])
  }

  // Remove query row
  const removeQuery = (id: string) => {
    setQueries(queries.filter(q => q.id !== id))
  }

  // Update query
  const updateQuery = (id: string, updates: Partial<SearchQuery>) => {
    setQueries(queries.map(q => q.id === id ? { ...q, ...updates } : q))
  }

  // Add filter
  const addFilter = (filter: SearchFilter) => {
    setFilters([...filters, filter])
  }

  // Remove filter
  const removeFilter = (index: number) => {
    setFilters(filters.filter((_, i) => i !== index))
  }

  const parseNumber = (value: unknown) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : null
    }
    return null
  }

  const applyDatasetFilters = (params: URLSearchParams, activeFilters: SearchFilter[]) => {
    activeFilters.forEach((filter) => {
      const field = filter.field.toLowerCase()
      const op = filter.operator
      const value = filter.value

      if (['modality', 'modalities'].includes(field)) {
        const values = Array.isArray(value) ? value : [value]
        values.filter(Boolean).forEach((entry) => params.append('modalities', String(entry)))
        return
      }
      if (['category', 'access_type', 'access', 'source_repo', 'tags', 'center', 'consortium'].includes(field)) {
        const key =
          field === 'access' ? 'access_type' : field
        const values = Array.isArray(value) ? value : [value]
        values.filter(Boolean).forEach((entry) => params.append(key, String(entry)))
        return
      }

      const numeric = parseNumber(value)
      if (numeric == null && op !== 'between') return

      if (['n', 'subjects', 'n_subjects', 'subjects_count', 'min_subjects', 'max_subjects'].includes(field)) {
        if (op === 'lt') {
          params.set('max_subjects', String(numeric))
        } else if (op === 'gt') {
          params.set('min_subjects', String(numeric))
        } else if (op === 'between' && Array.isArray(value)) {
          const [minValue, maxValue] = value
          const minNum = parseNumber(minValue)
          const maxNum = parseNumber(maxValue)
          if (minNum != null) params.set('min_subjects', String(minNum))
          if (maxNum != null) params.set('max_subjects', String(maxNum))
        } else if (numeric != null) {
          params.set('min_subjects', String(numeric))
        }
        return
      }

      if (['age', 'age_min', 'age_max'].includes(field)) {
        if (op === 'lt') {
          params.set('age_max', String(numeric))
        } else if (op === 'gt') {
          params.set('age_min', String(numeric))
        } else if (op === 'between' && Array.isArray(value)) {
          const [minValue, maxValue] = value
          const minNum = parseNumber(minValue)
          const maxNum = parseNumber(maxValue)
          if (minNum != null) params.set('age_min', String(minNum))
          if (maxNum != null) params.set('age_max', String(maxNum))
        } else if (numeric != null) {
          params.set('age_min', String(numeric))
        }
        return
      }

      if (['tr', 'tr_min', 'tr_max'].includes(field)) {
        if (op === 'equals' && numeric != null) {
          params.set('tr', String(numeric))
        } else if (op === 'lt') {
          params.set('tr_max', String(numeric))
        } else if (op === 'gt') {
          params.set('tr_min', String(numeric))
        } else if (op === 'between' && Array.isArray(value)) {
          const [minValue, maxValue] = value
          const minNum = parseNumber(minValue)
          const maxNum = parseNumber(maxValue)
          if (minNum != null) params.set('tr_min', String(minNum))
          if (maxNum != null) params.set('tr_max', String(maxNum))
        }
        return
      }

      if (['voxel', 'voxel_mm', 'voxel_min', 'voxel_max'].includes(field)) {
        if (op === 'equals' && numeric != null) {
          params.set('voxel_mm', String(numeric))
        } else if (op === 'lt') {
          params.set('voxel_max', String(numeric))
        } else if (op === 'gt') {
          params.set('voxel_min', String(numeric))
        } else if (op === 'between' && Array.isArray(value)) {
          const [minValue, maxValue] = value
          const minNum = parseNumber(minValue)
          const maxNum = parseNumber(maxValue)
          if (minNum != null) params.set('voxel_min', String(minNum))
          if (maxNum != null) params.set('voxel_max', String(maxNum))
        }
      }
    })
  }

  // Perform search
  async function performSearch() {
    if (!queries.some(q => q.text.trim())) return

    setIsSearching(true)
    try {
      const queryText = queries.map(q => q.text).filter(Boolean).join(' ').trim()
      const startedAt = performance.now()

      const datasetParams = new URLSearchParams()
      datasetParams.set('q', queryText)
      datasetParams.set('limit', '20')
      datasetParams.set('offset', '0')
      applyDatasetFilters(datasetParams, filters)

      const datasetsPromise = fetch(`/api/catalog/datasets/search?${datasetParams.toString()}`, {
        cache: 'no-store'
      }).then(async (res) => (res.ok ? res.json() : null)).catch(() => null)

      const kgPromise = fetch(`/api/kg/search?q=${encodeURIComponent(queryText)}&limit=10`, {
        cache: 'no-store'
      }).then(async (res) => (res.ok ? res.json() : null)).catch(() => null)

      const toolsPromise = fetch(`/api/tools/search?q=${encodeURIComponent(queryText)}`, {
        cache: 'no-store'
      }).then(async (res) => (res.ok ? res.json() : null)).catch(() => null)

      const analysesPromise = fetch(`/api/analyses?limit=20`, {
        cache: 'no-store'
      }).then(async (res) => (res.ok ? res.json() : null)).catch(() => null)

      const [datasetsPayload, kgPayload, toolsPayload, analysesPayload] = await Promise.all([
        datasetsPromise,
        kgPromise,
        toolsPromise,
        analysesPromise
      ])

      const datasetResults: SearchResult[] = Array.isArray(datasetsPayload?.datasets)
        ? datasetsPayload.datasets.map((dataset: any) => ({
            id: dataset.id,
            title: dataset.name || dataset.id,
            type: 'dataset',
            description: dataset.description,
            relevance: typeof dataset.score === 'number' ? dataset.score : 0.6,
            metadata: {
              subjects: dataset.subjects_count,
              modalities: dataset.modalities,
              tasks: dataset.tasks,
              access: dataset.access_type,
              source: dataset.source_repo,
            },
            tags: (dataset.tags || []).slice(0, 5),
          }))
        : []

      const kgOperations = Array.isArray(kgPayload?.operations) ? kgPayload.operations : []
      const kgResults: SearchResult[] = kgOperations.map((op: any, index: number) => ({
        id: op.id || `kg-${index}`,
        title: op.name || op.id || 'Knowledge graph result',
        type: 'concept',
        description: op.description,
        relevance: 0.55,
        metadata: { source: 'kg' },
      }))

      const toolResults: SearchResult[] = Array.isArray(toolsPayload?.tools)
        ? toolsPayload.tools.map((tool: any, index: number) => ({
            id: tool.id || tool.name || `tool-${index}`,
            title: tool.display_name || tool.name || tool.id,
            type: 'task',
            description: tool.description,
            relevance: 0.5,
            metadata: {
              domain: tool.domain,
              runtime: tool.runtime,
              category: tool.category,
            },
            tags: tool.modalities || tool.tags || [],
          }))
        : []

      const analysesItems = Array.isArray(analysesPayload?.items) ? analysesPayload.items : []
      const terms = queryText.toLowerCase().split(/\s+/).filter(Boolean)
      const analysisResults: SearchResult[] = analysesItems
        .filter((analysis: any) => {
          if (!terms.length) return false
          const haystack = `${analysis.title || ''} ${analysis.template?.name || ''} ${analysis.dataset?.name || ''}`.toLowerCase()
          return terms.every(term => haystack.includes(term))
        })
        .map((analysis: any) => ({
          id: analysis.analysis_id || analysis.run_id,
          title: analysis.title || analysis.template?.name || analysis.analysis_id,
          type: 'analysis',
          description: analysis.template?.name || analysis.dataset?.name,
          relevance: 0.5,
          metadata: {
            status: analysis.status,
            dataset: analysis.dataset?.dataset_id,
            template: analysis.template?.template_id,
          }
        }))

      const combinedResults = [
        ...datasetResults,
        ...analysisResults,
        ...kgResults,
        ...toolResults
      ]

      setResults(combinedResults)

      // Add to history
      if (queryText && !searchHistory.includes(queryText)) {
        setSearchHistory([queryText, ...searchHistory.slice(0, 9)])
      }

      const elapsedMs = performance.now() - startedAt
      setSearchStats((prev) => {
        const nextTotal = prev.totalSearches + 1
        const nextSuccess = prev.successfulSearches + (combinedResults.length > 0 ? 1 : 0)
        const nextAvg = (prev.avgResponseTime * prev.totalSearches + elapsedMs) / nextTotal
        return {
          totalSearches: nextTotal,
          successfulSearches: nextSuccess,
          avgResponseTime: nextAvg,
        }
      })

      void fetch(`/api/search/track?query=${encodeURIComponent(queryText)}&results_count=${combinedResults.length}`, {
        method: 'POST',
      }).catch(() => undefined)

      if (onSearch) {
        onSearch(queries, filters)
      }
      
      toast({
        title: 'Search Complete',
        description: `Found ${combinedResults.length} results`
      })
    } catch (error) {
      toast({
        title: 'Search Failed',
        description: 'An error occurred during search',
        variant: 'destructive'
      })
    } finally {
      setIsSearching(false)
    }
  }

  // Save search
  const saveSearch = () => {
    const savedSearch: SavedSearch = {
      id: Date.now().toString(),
      name: `Search ${new Date().toLocaleDateString()}`,
      query: queries,
      filters: filters,
      createdAt: new Date(),
      resultCount: results.length
    }
    
    setSavedSearches([savedSearch, ...savedSearches])
    toast({
      title: 'Search Saved',
      description: 'Your search has been saved successfully'
    })
  }

  // Load saved search
  const loadSavedSearch = (search: SavedSearch) => {
    setQueries(search.query)
    setFilters(search.filters)
    performSearch()
  }

  // Query Builder Component
  const QueryBuilder = () => (
    <div className="space-y-3">
      {queries.map((query, index) => (
        <div key={query.id} className="flex items-center space-x-2">
          {index > 0 && (
            <select
              value={query.operator}
              onChange={(e) => updateQuery(query.id, { operator: e.target.value as any })}
              className="px-3 py-2 border rounded-lg text-sm font-medium"
            >
              {OPERATORS.map(op => (
                <option key={op.value} value={op.value}>{op.label}</option>
              ))}
            </select>
          )}
          
          <select
            value={query.field || 'all'}
            onChange={(e) => updateQuery(query.id, { field: e.target.value })}
            className="px-3 py-2 border rounded-lg"
          >
            {SEARCH_FIELDS.map(field => (
              <option key={field.value} value={field.value}>{field.label}</option>
            ))}
          </select>
          
          <input
            type="text"
            value={query.text}
            onChange={(e) => {
              updateQuery(query.id, { text: e.target.value })
              debouncedSearch()
            }}
            placeholder="Enter search terms..."
            className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          
          {queries.length > 1 && (
            <button
              onClick={() => removeQuery(query.id)}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      ))}
      
      <button
        onClick={addQuery}
        className="flex items-center space-x-2 text-blue-600 hover:text-blue-700"
      >
        <Plus className="w-4 h-4" />
        <span>Add condition</span>
      </button>
    </div>
  )

  // Filters Panel
  const FiltersPanel = () => (
    <div className="space-y-4">
      <h3 className="font-semibold">Filters</h3>
      
      {/* Date Range */}
      <div>
        <label className="text-sm font-medium">Date Range</label>
        <div className="flex space-x-2 mt-1">
          <input type="date" className="flex-1 px-3 py-2 border rounded-lg" />
          <span className="self-center">to</span>
          <input type="date" className="flex-1 px-3 py-2 border rounded-lg" />
        </div>
      </div>
      
      {/* Type Filter */}
      <div>
        <label className="text-sm font-medium">Type</label>
        <div className="space-y-2 mt-2">
          {['Dataset', 'Analysis', 'Publication', 'Concept', 'Task'].map(type => (
            <label key={type} className="flex items-center space-x-2">
              <input
                type="checkbox"
                onChange={(e) => {
                  if (e.target.checked) {
                    addFilter({
                      field: 'type',
                      operator: 'equals',
                      value: type.toLowerCase(),
                      label: type
                    })
                  }
                }}
                className="rounded"
              />
              <span className="text-sm">{type}</span>
            </label>
          ))}
        </div>
      </div>
      
      {/* Tags */}
      <div>
        <label className="text-sm font-medium">Tags</label>
        <div className="flex flex-wrap gap-2 mt-2">
          {['fMRI', 'GLM', 'motor', 'visual', 'resting-state', 'connectivity'].map(tag => (
            <button
              key={tag}
              onClick={() => addFilter({
                field: 'tags',
                operator: 'contains',
                value: tag,
                label: tag
              })}
              className="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-800 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              {tag}
            </button>
          ))}
        </div>
      </div>
      
      {/* Active Filters */}
      {filters.length > 0 && (
        <div>
          <label className="text-sm font-medium">Active Filters</label>
          <div className="space-y-2 mt-2">
            {filters.map((filter, index) => (
              <div key={index} className="flex items-center justify-between p-2 bg-blue-50 dark:bg-blue-900/20 rounded">
                <span className="text-sm">
                  {filter.field} {filter.operator} {filter.label || filter.value}
                </span>
                <button
                  onClick={() => removeFilter(index)}
                  className="text-red-500 hover:text-red-600"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )

  // Search Results Component
  const SearchResults = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <span className="text-sm text-gray-500">
            {results.length} results found
          </span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-3 py-1 border rounded text-sm"
          >
            <option value="relevance">Relevance</option>
            <option value="date">Date</option>
            <option value="title">Title</option>
          </select>
        </div>
        
        <div className="flex space-x-2">
          <button
            onClick={() => setViewMode('list')}
            className={`p-2 rounded ${viewMode === 'list' ? 'bg-gray-200 dark:bg-gray-700' : ''}`}
          >
            List
          </button>
          <button
            onClick={() => setViewMode('grid')}
            className={`p-2 rounded ${viewMode === 'grid' ? 'bg-gray-200 dark:bg-gray-700' : ''}`}
          >
            Grid
          </button>
        </div>
      </div>
      
      <div className={viewMode === 'grid' ? 'grid grid-cols-2 gap-4' : 'space-y-3'}>
        {results.map(result => (
          <div
            key={result.id}
            onClick={() => onResultClick?.(result)}
            className={`p-4 border rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer ${
              selectedResults.has(result.id) ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20' : ''
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center space-x-2">
                  <span className={`px-2 py-1 text-xs rounded ${
                    result.type === 'dataset' ? 'bg-blue-100 text-blue-700' :
                    result.type === 'analysis' ? 'bg-green-100 text-green-700' :
                    result.type === 'publication' ? 'bg-purple-100 text-purple-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {result.type}
                  </span>
                  <h4 className="font-medium">{result.title}</h4>
                </div>
                
                {result.description && (
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                    {result.description}
                  </p>
                )}
                
                {result.highlights && result.highlights.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {result.highlights.map((highlight, i) => (
                      <span key={i} className="text-xs bg-yellow-100 text-yellow-800 px-1 rounded">
                        {highlight}
                      </span>
                    ))}
                  </div>
                )}
                
                {result.tags && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {result.tags.map(tag => (
                      <span key={tag} className="text-xs bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
                        #{tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              
              <div className="flex flex-col items-end space-y-2 ml-4">
                <div className="text-sm font-medium text-green-600">
                  {Math.round(result.relevance * 100)}% match
                </div>
                <input
                  type="checkbox"
                  checked={selectedResults.has(result.id)}
                  onChange={(e) => {
                    const newSelected = new Set(selectedResults)
                    if (e.target.checked) {
                      newSelected.add(result.id)
                    } else {
                      newSelected.delete(result.id)
                    }
                    setSelectedResults(newSelected)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="rounded"
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  // Analytics Dashboard
  const AnalyticsDashboard = () => (
    <div className="space-y-4 p-4 bg-gray-50 dark:bg-gray-900 rounded-lg">
      <h3 className="font-semibold flex items-center space-x-2">
        <BarChart3 className="w-5 h-5" />
        <span>Search Analytics</span>
      </h3>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-gray-800 p-3 rounded-lg">
          <div className="text-2xl font-bold">{analytics.totalSearches}</div>
          <div className="text-sm text-gray-500">Total Searches</div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-3 rounded-lg">
          <div className="text-2xl font-bold">{analytics.avgResponseTime}ms</div>
          <div className="text-sm text-gray-500">Avg Response Time</div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-3 rounded-lg">
          <div className="text-2xl font-bold">{(analytics.conversionRate * 100).toFixed(0)}%</div>
          <div className="text-sm text-gray-500">Conversion Rate</div>
        </div>
        <div className="bg-white dark:bg-gray-800 p-3 rounded-lg">
          <div className="text-2xl font-bold">{results.length}</div>
          <div className="text-sm text-gray-500">Current Results</div>
        </div>
      </div>
      
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg">
        <h4 className="font-medium mb-3">Popular Queries</h4>
        <div className="space-y-2">
          {analytics.popularQueries.length > 0 ? (
            analytics.popularQueries.map((item, index) => (
              <div key={index} className="flex items-center justify-between">
                <span className="text-sm">{item.query}</span>
                <span className="text-sm text-gray-500">{item.count} searches</span>
              </div>
            ))
          ) : (
            <div className="text-sm text-gray-500">No searches yet.</div>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className={`max-w-7xl mx-auto p-6 ${className || ''}`}>
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center space-x-3">
          <Search className="w-7 h-7" />
          <span>Advanced Search</span>
          <Sparkles className="w-5 h-5 text-yellow-500" />
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mt-1">
          Build complex queries with filters and logical operators
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          {/* Saved Searches */}
          <div className="bg-white dark:bg-gray-900 rounded-lg p-4">
            <button
              onClick={() => setShowSaved(!showSaved)}
              className="w-full flex items-center justify-between font-medium"
            >
              <span className="flex items-center space-x-2">
                <Star className="w-4 h-4" />
                <span>Saved Searches</span>
              </span>
              <ChevronDown className={`w-4 h-4 transition-transform ${showSaved ? 'rotate-180' : ''}`} />
            </button>
            
            {showSaved && (
              <div className="mt-3 space-y-2">
                {savedSearches.map(search => (
                  <button
                    key={search.id}
                    onClick={() => loadSavedSearch(search)}
                    className="w-full text-left p-2 hover:bg-gray-50 dark:hover:bg-gray-800 rounded"
                  >
                    <div className="text-sm font-medium">{search.name}</div>
                    <div className="text-xs text-gray-500">
                      {search.resultCount} results • {new Date(search.createdAt).toLocaleDateString()}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
          
          {/* Search History */}
          <div className="bg-white dark:bg-gray-900 rounded-lg p-4">
            <h3 className="font-medium mb-3 flex items-center space-x-2">
              <History className="w-4 h-4" />
              <span>Recent Searches</span>
            </h3>
            <div className="space-y-2">
              {searchHistory.slice(0, 5).map((query, index) => (
                <button
                  key={index}
                  onClick={() => {
                    setQueries([{ id: '1', text: query, operator: 'AND' }])
                    performSearch()
                  }}
                  className="w-full text-left text-sm p-2 hover:bg-gray-50 dark:hover:bg-gray-800 rounded"
                >
                  {query}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="lg:col-span-3 space-y-6">
          {/* Query Builder */}
          <div className="bg-white dark:bg-gray-900 rounded-lg p-6">
            <QueryBuilder />
            
            <div className="flex items-center justify-between mt-4 pt-4 border-t">
              <div className="flex space-x-2">
                <button
                  onClick={() => setShowFilters(!showFilters)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center space-x-2"
                >
                  <Filter className="w-4 h-4" />
                  <span>Filters</span>
                  {filters.length > 0 && (
                    <span className="px-2 py-0.5 bg-blue-500 text-white text-xs rounded-full">
                      {filters.length}
                    </span>
                  )}
                </button>
                
                <button
                  onClick={() => setShowAnalytics(!showAnalytics)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center space-x-2"
                >
                  <BarChart3 className="w-4 h-4" />
                  <span>Analytics</span>
                </button>
              </div>
              
              <div className="flex space-x-2">
                <button
                  onClick={saveSearch}
                  disabled={queries.every(q => !q.text.trim())}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                </button>
                
                <button
                  onClick={performSearch}
                  disabled={isSearching || queries.every(q => !q.text.trim())}
                  className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center space-x-2"
                >
                  {isSearching ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Searching...</span>
                    </>
                  ) : (
                    <>
                      <Search className="w-4 h-4" />
                      <span>Search</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Filters Panel */}
          {showFilters && (
            <div className="bg-white dark:bg-gray-900 rounded-lg p-6">
              <FiltersPanel />
            </div>
          )}

          {/* Analytics Dashboard */}
          {showAnalytics && <AnalyticsDashboard />}

          {/* Search Results */}
          {results.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-lg p-6">
              <SearchResults />
              
              {/* Bulk Actions */}
              {selectedResults.size > 0 && (
                <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg flex items-center justify-between">
                  <span className="text-sm">
                    {selectedResults.size} items selected
                  </span>
                  <div className="flex space-x-2">
                    <button className="px-3 py-1 text-sm border rounded hover:bg-white dark:hover:bg-gray-800">
                      <Download className="w-3 h-3 inline mr-1" />
                      Export
                    </button>
                    <button className="px-3 py-1 text-sm border rounded hover:bg-white dark:hover:bg-gray-800">
                      <Share2 className="w-3 h-3 inline mr-1" />
                      Share
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default AdvancedSearchInterface
