'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { 
  Search, X, Clock, TrendingUp, FileText, 
  Database, Brain, ChevronRight, Loader2
} from 'lucide-react'
import { useRouter } from 'next/navigation'

import { serviceEndpoints } from '@/lib/service-endpoints'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'

interface SearchSuggestion {
  id: string
  type: 'dataset' | 'analysis' | 'paper' | 'tool' | 'history'
  title: string
  description?: string
  icon: React.ElementType
  url: string
  metadata?: {
    date?: string
    author?: string
    count?: number
  }
}

type ApiSuggestion = {
  text?: string
  category?: string
  type?: string
  confidence?: number
  metadata?: Record<string, any>
  source?: string
}

type TrendingItem = {
  query: string
  count?: number
  growth_rate?: number
  category?: string
  last_searched?: string
}

type TrendingResponse = {
  trending?: TrendingItem[]
  timeframe?: string
  updated_at?: string
}

interface SearchAutocompleteProps {
  placeholder?: string
  onSearch?: (query: string) => void
  onSelect?: (suggestion: SearchSuggestion) => void
  showHistory?: boolean
  maxSuggestions?: number
  debounceMs?: number
  className?: string
}

export function SearchAutocomplete({
  placeholder = 'Search datasets, analyses, papers...',
  onSearch,
  onSelect,
  showHistory = true,
  maxSuggestions = 8,
  debounceMs = 300,
  className = ''
}: SearchAutocompleteProps) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
  const [history, setHistory] = useState<SearchSuggestion[]>([])
  const [trending, setTrending] = useState<TrendingItem[]>([])
  const [trendingLoading, setTrendingLoading] = useState(false)
  const [trendingError, setTrendingError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  
  const router = useRouter()
  const { enabled: advancedMode } = useAdvancedMode()
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const lastTrendingFetchRef = useRef<number>(0)

  const resolveSuggestionType = (category?: string): SearchSuggestion['type'] => {
    switch ((category || '').toLowerCase()) {
      case 'dataset':
        return 'dataset'
      case 'analysis':
        return 'analysis'
      case 'paper':
        return 'paper'
      case 'tool':
        return 'tool'
      default:
        return 'dataset'
    }
  }

  const resolveSuggestionIcon = (type: SearchSuggestion['type']) => {
    switch (type) {
      case 'dataset':
        return Database
      case 'analysis':
        return Brain
      case 'paper':
        return FileText
      case 'tool':
        return TrendingUp
      case 'history':
        return Clock
      default:
        return Search
    }
  }

  const resolveSuggestionUrl = (type: SearchSuggestion['type'], title: string) => {
    const encoded = encodeURIComponent(title)
    if (type === 'dataset') return `/datasets?q=${encoded}`
    if (type === 'analysis') return `/analyses?q=${encoded}`
    if (type === 'tool') return advancedMode ? `/library/tools?q=${encoded}` : `/studio?prompt=${encoded}`
    if (type === 'paper') return `/studio?prompt=${encoded}`
    return `/datasets?q=${encoded}`
  }

  // Load search history from localStorage
  useEffect(() => {
    if (showHistory && typeof window !== 'undefined') {
      const saved = localStorage.getItem('searchHistory')
      if (saved) {
        try {
          const parsed = JSON.parse(saved)
          setHistory(parsed.slice(0, 5))
        } catch (err) {
          console.error('Failed to parse search history:', err)
        }
      }
    }
  }, [showHistory])

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

  const trackSearch = useCallback(async (searchQuery: string) => {
    try {
      const params = new URLSearchParams({ query: searchQuery })
      if (sessionIdRef.current) {
        params.set('session_id', sessionIdRef.current)
      }
      await fetch(serviceEndpoints.orchestrator(`/api/search/track?${params.toString()}`), {
        method: 'POST'
      })
    } catch (err) {
      console.warn('Failed to track search query:', err)
    }
  }, [])

  const fetchTrending = useCallback(async () => {
    const now = Date.now()
    if (now - lastTrendingFetchRef.current < 30_000) {
      return
    }

    setTrendingLoading(true)
    setTrendingError(null)
    lastTrendingFetchRef.current = now

    try {
      const path = `/api/search/trending?timeframe=24h&limit=3`
      const url = serviceEndpoints.orchestrator(path)

      let response: Response
      try {
        response = await fetch(url)
      } catch {
        response = await fetch(path)
      }

      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as TrendingResponse
      const items = Array.isArray(data.trending) ? data.trending : []
      setTrending(items.filter((item) => item?.query).slice(0, 3))
    } catch (err) {
      setTrending([])
      setTrendingError(err instanceof Error ? err.message : 'Failed to load trending searches')
    } finally {
      setTrendingLoading(false)
    }
  }, [])

  useEffect(() => {
    const shouldShowTrending = showDropdown && !query.trim() && history.length === 0
    if (!shouldShowTrending) return
    void fetchTrending()
  }, [showDropdown, query, history.length, fetchTrending])

  // Fetch suggestions
  const fetchSuggestions = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setSuggestions([])
      return
    }

    setIsLoading(true)
    
    try {
      const response = await fetch(
        serviceEndpoints.orchestrator(`/api/search/autocomplete?q=${encodeURIComponent(searchQuery)}`)
      )
      if (response.ok) {
        const data = await response.json()
        const normalized = (data.suggestions || []).map((item: ApiSuggestion, index: number) => {
          const title = item.text || searchQuery
          const type = resolveSuggestionType(item.category || item.type)
          if (type === 'tool' && !advancedMode) {
            return null
          }
          return {
            id: String(item.metadata?.id || `${type}-${index}`),
            type,
            title,
            description: item.metadata?.description || item.metadata?.summary || item.source || undefined,
            icon: resolveSuggestionIcon(type),
            url: resolveSuggestionUrl(type, title),
            metadata: item.metadata,
          }
        })
        setSuggestions(normalized.filter(Boolean).slice(0, maxSuggestions) as SearchSuggestion[])
      } else {
        setSuggestions([])
      }
    } catch (err) {
      console.error('Failed to fetch suggestions:', err)
      setSuggestions([])
    } finally {
      setIsLoading(false)
    }
  }, [maxSuggestions, advancedMode])

  // Handle input change with debounce
  const handleInputChange = useCallback((value: string) => {
    setQuery(value)
    setSelectedIndex(-1)
    
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }
    
    if (value.trim()) {
      setShowDropdown(true)
      debounceTimerRef.current = setTimeout(() => {
        fetchSuggestions(value)
      }, debounceMs)
    } else {
      setSuggestions([])
      setShowDropdown(showHistory && history.length > 0)
    }
  }, [fetchSuggestions, debounceMs, showHistory, history])

  // Handle search submission
  const handleSearch = useCallback((searchQuery?: string) => {
    const finalQuery = searchQuery || query
    
    if (!finalQuery.trim()) return
    
    // Add to history
    if (showHistory) {
      const newHistoryItem: SearchSuggestion = {
        id: `history_${Date.now()}`,
        type: 'history',
        title: finalQuery,
        icon: Clock,
        url: `/datasets?q=${encodeURIComponent(finalQuery)}`,
        metadata: { date: new Date().toISOString() }
      }
      
      const updatedHistory = [newHistoryItem, ...history.filter(h => h.title !== finalQuery)].slice(0, 10)
      setHistory(updatedHistory)
      localStorage.setItem('searchHistory', JSON.stringify(updatedHistory))
    }
    
    // Execute search
    if (onSearch) {
      onSearch(finalQuery)
    } else {
      router.push(`/datasets?q=${encodeURIComponent(finalQuery)}`)
    }

    void trackSearch(finalQuery)
    
    setShowDropdown(false)
    setQuery('')
    setSuggestions([])
  }, [query, history, showHistory, onSearch, router, trackSearch])

  // Handle suggestion selection
  const handleSelectSuggestion = useCallback((suggestion: SearchSuggestion) => {
    if (onSelect) {
      onSelect(suggestion)
    } else if (suggestion.type === 'history') {
      handleSearch(suggestion.title)
    } else {
      void trackSearch(suggestion.title)
      router.push(suggestion.url)
    }
    
    setShowDropdown(false)
    setQuery('')
    setSuggestions([])
  }, [onSelect, handleSearch, router, trackSearch])

  // Keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const items = query.trim() ? suggestions : history
    
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(prev => 
          prev < items.length - 1 ? prev + 1 : prev
        )
        break
        
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(prev => prev > -1 ? prev - 1 : -1)
        break
        
      case 'Enter':
        e.preventDefault()
        if (selectedIndex >= 0 && selectedIndex < items.length) {
          handleSelectSuggestion(items[selectedIndex])
        } else {
          handleSearch()
        }
        break
        
      case 'Escape':
        setShowDropdown(false)
        setSelectedIndex(-1)
        break
    }
  }, [query, suggestions, history, selectedIndex, handleSelectSuggestion, handleSearch])

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setShowDropdown(false)
      }
    }
    
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Clear search history
  const clearHistory = useCallback(() => {
    setHistory([])
    localStorage.removeItem('searchHistory')
  }, [])

  const getIcon = (type: string) => {
    switch (type) {
      case 'dataset':
        return Database
      case 'analysis':
        return Brain
      case 'paper':
        return FileText
      case 'history':
        return Clock
      default:
        return ChevronRight
    }
  }

  return (
    <div className={`relative ${className}`}>
      {/* Search Input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowDropdown(true)}
          placeholder={placeholder}
          className="w-full pl-10 pr-10 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-900 dark:text-white"
        />
        {query && (
          <button
            onClick={() => {
              setQuery('')
              setSuggestions([])
              inputRef.current?.focus()
            }}
            className="absolute right-3 top-1/2 transform -translate-y-1/2 p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
          >
            <X className="h-4 w-4 text-gray-400" />
          </button>
        )}
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 animate-spin" />
        )}
      </div>

      {/* Dropdown */}
      {showDropdown && (suggestions.length > 0 || (!query && history.length > 0) || (!query && history.length === 0)) && (
        <div
          ref={dropdownRef}
          className="absolute top-full mt-2 w-full bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 max-h-96 overflow-y-auto z-50"
        >
          {/* Search History */}
          {!query && history.length > 0 && (
            <>
              <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Recent Searches
                </span>
                <button
                  onClick={clearHistory}
                  className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  Clear
                </button>
              </div>
              {history.map((item, index) => {
                const Icon = getIcon(item.type)
                return (
                  <button
                    key={item.id}
                    onClick={() => handleSelectSuggestion(item)}
                    className={`w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 dark:hover:bg-gray-700 ${
                      selectedIndex === index ? 'bg-gray-50 dark:bg-gray-700' : ''
                    }`}
                  >
                    <Icon className="h-4 w-4 text-gray-400" />
                    <span className="flex-1 text-left text-sm text-gray-700 dark:text-gray-300">
                      {item.title}
                    </span>
                  </button>
                )
              })}
            </>
          )}

          {/* Suggestions */}
          {query && suggestions.length > 0 && (
            <>
              <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Suggestions
                </span>
              </div>
              {suggestions.map((suggestion, index) => {
                const Icon = getIcon(suggestion.type)
                const isSelected = selectedIndex === index
                
                return (
                  <button
                    key={suggestion.id}
                    onClick={() => handleSelectSuggestion(suggestion)}
                    className={`w-full px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-gray-700 ${
                      isSelected ? 'bg-gray-50 dark:bg-gray-700' : ''
                    }`}
                  >
                    <Icon className="h-5 w-5 text-gray-400 mt-0.5" />
                    <div className="flex-1 text-left">
                      <div className="text-sm font-medium text-gray-900 dark:text-white">
                        {suggestion.title}
                      </div>
                      {suggestion.description && (
                        <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          {suggestion.description}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 capitalize">
                      {suggestion.type}
                    </span>
                  </button>
                )
              })}
            </>
          )}

          {/* Trending Searches */}
          {!query && history.length === 0 && (
            <>
              <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  Trending
                </span>
              </div>
              {trendingLoading ? (
                <div className="px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading trending…
                </div>
              ) : trendingError ? (
                <div className="px-4 py-3 text-sm text-muted-foreground">No data yet.</div>
              ) : trending.length === 0 ? (
                <div className="px-4 py-3 text-sm text-muted-foreground">No data yet.</div>
              ) : (
                trending.map((item) => (
                  <button
                    key={item.query}
                    onClick={() => handleSearch(item.query)}
                    className="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
                  >
                    <TrendingUp className="h-4 w-4 text-gray-400" />
                    <div className="flex-1">
                      <div className="text-sm text-gray-700 dark:text-gray-300">{item.query}</div>
                      {typeof item.count === 'number' && (
                        <div className="text-xs text-gray-400">{item.count.toLocaleString()} searches</div>
                      )}
                    </div>
                  </button>
                ))
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
