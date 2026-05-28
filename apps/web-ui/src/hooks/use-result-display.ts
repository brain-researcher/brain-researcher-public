'use client'

import { useState, useCallback, useMemo } from 'react'
import { ResultData, ResultMetadata } from '../components/results/ResultCard'

export interface UseResultDisplayOptions {
  initialExpanded?: Set<string>
  autoExpand?: boolean
  maxAutoExpand?: number
}

export interface ResultDisplayState {
  expandedResults: Set<string>
  selectedResults: Set<string>
  sortBy: 'name' | 'type' | 'created_at' | 'size'
  sortDirection: 'asc' | 'desc'
  filterBy: string
  groupBy: 'none' | 'type' | 'date' | 'author'
}

export interface ResultDisplayActions {
  toggleExpanded: (id: string) => void
  expandAll: () => void
  collapseAll: () => void
  toggleSelected: (id: string) => void
  selectAll: () => void
  clearSelection: () => void
  setSortBy: (field: string, direction?: 'asc' | 'desc') => void
  setFilter: (filter: string) => void
  setGroupBy: (groupBy: string) => void
  downloadSelected: () => Promise<void>
  shareSelected: () => Promise<void>
}

export interface ProcessedResult extends ResultData {
  searchScore?: number
  isVisible?: boolean
}

export function useResultDisplay(
  results: ResultData[],
  options: UseResultDisplayOptions = {}
) {
  const {
    initialExpanded = new Set(),
    autoExpand = false,
    maxAutoExpand = 3
  } = options

  const [state, setState] = useState<ResultDisplayState>({
    expandedResults: initialExpanded,
    selectedResults: new Set(),
    sortBy: 'created_at',
    sortDirection: 'desc',
    filterBy: '',
    groupBy: 'none'
  })

  // Auto-expand first few results if enabled
  useState(() => {
    if (autoExpand && results.length > 0 && state.expandedResults.size === 0) {
      const autoExpandIds = results
        .slice(0, Math.min(maxAutoExpand, results.length))
        .map(r => r.id)
      setState(prev => ({
        ...prev,
        expandedResults: new Set(autoExpandIds)
      }))
    }
  })

  // Filter and search results
  const filteredResults = useMemo<ProcessedResult[]>(() => {
    let filtered: ProcessedResult[] = [...results]

    // Apply text filter
    if (state.filterBy) {
      const searchTerm = state.filterBy.toLowerCase()
      filtered = filtered.map(result => {
        let searchScore = 0
        
        // Score based on matches
        if (result.name.toLowerCase().includes(searchTerm)) searchScore += 3
        if (result.metadata?.description?.toLowerCase().includes(searchTerm)) searchScore += 2
        if (result.metadata?.tags?.some(tag => tag.toLowerCase().includes(searchTerm))) searchScore += 1
        if (result.type.toLowerCase().includes(searchTerm)) searchScore += 1
        if (result.metadata?.author?.toLowerCase().includes(searchTerm)) searchScore += 1

        return {
          ...result,
          searchScore,
          isVisible: searchScore > 0
        }
      }).filter(result => result.isVisible)
    } else {
      filtered = filtered.map(result => ({ ...result, searchScore: 0, isVisible: true }))
    }

    return filtered
  }, [results, state.filterBy])

  // Sort results
  const sortedResults = useMemo(() => {
    const sorted = [...filteredResults]

    sorted.sort((a, b) => {
      let aVal: any
      let bVal: any

      switch (state.sortBy) {
        case 'name':
          aVal = a.name.toLowerCase()
          bVal = b.name.toLowerCase()
          break
        case 'type':
          aVal = a.type
          bVal = b.type
          break
        case 'created_at':
          aVal = new Date(a.metadata?.created_at || 0).getTime()
          bVal = new Date(b.metadata?.created_at || 0).getTime()
          break
        case 'size':
          aVal = a.metadata?.size || 0
          bVal = b.metadata?.size || 0
          break
        default:
          return 0
      }

      let comparison = 0
      if (aVal < bVal) comparison = -1
      else if (aVal > bVal) comparison = 1

      return state.sortDirection === 'asc' ? comparison : -comparison
    })

    // If filtering by search, sort by relevance first
    if (state.filterBy) {
      sorted.sort((a, b) => (b.searchScore || 0) - (a.searchScore || 0))
    }

    return sorted
  }, [filteredResults, state.sortBy, state.sortDirection, state.filterBy])

  // Group results
  const groupedResults = useMemo(() => {
    if (state.groupBy === 'none') {
      return [{ key: 'all', label: 'All Results', results: sortedResults }]
    }

    const groups = new Map<string, ProcessedResult[]>()

    sortedResults.forEach(result => {
      let groupKey: string
      let groupLabel: string

      switch (state.groupBy) {
        case 'type':
          groupKey = result.type
          groupLabel = result.type.charAt(0).toUpperCase() + result.type.slice(1)
          break
        case 'date':
          const date = result.metadata?.created_at
          if (date) {
            const dateObj = new Date(date)
            groupKey = dateObj.toDateString()
            groupLabel = dateObj.toLocaleDateString()
          } else {
            groupKey = 'unknown'
            groupLabel = 'Unknown Date'
          }
          break
        case 'author':
          groupKey = result.metadata?.author || 'unknown'
          groupLabel = result.metadata?.author || 'Unknown Author'
          break
        default:
          groupKey = 'all'
          groupLabel = 'All Results'
      }

      if (!groups.has(groupKey)) {
        groups.set(groupKey, [])
      }
      groups.get(groupKey)!.push(result)
    })

    return Array.from(groups.entries()).map(([key, results]) => ({
      key,
      label: key === 'unknown' ? 
        state.groupBy === 'date' ? 'Unknown Date' :
        state.groupBy === 'author' ? 'Unknown Author' :
        key :
        key.charAt(0).toUpperCase() + key.slice(1),
      results
    }))
  }, [sortedResults, state.groupBy])

  const actions: ResultDisplayActions = {
    toggleExpanded: useCallback((id: string) => {
      setState(prev => {
        const newExpanded = new Set(prev.expandedResults)
        if (newExpanded.has(id)) {
          newExpanded.delete(id)
        } else {
          newExpanded.add(id)
        }
        return { ...prev, expandedResults: newExpanded }
      })
    }, []),

    expandAll: useCallback(() => {
      setState(prev => ({
        ...prev,
        expandedResults: new Set(results.map(r => r.id))
      }))
    }, [results]),

    collapseAll: useCallback(() => {
      setState(prev => ({
        ...prev,
        expandedResults: new Set()
      }))
    }, []),

    toggleSelected: useCallback((id: string) => {
      setState(prev => {
        const newSelected = new Set(prev.selectedResults)
        if (newSelected.has(id)) {
          newSelected.delete(id)
        } else {
          newSelected.add(id)
        }
        return { ...prev, selectedResults: newSelected }
      })
    }, []),

    selectAll: useCallback(() => {
      setState(prev => ({
        ...prev,
        selectedResults: new Set(sortedResults.map(r => r.id))
      }))
    }, [sortedResults]),

    clearSelection: useCallback(() => {
      setState(prev => ({ ...prev, selectedResults: new Set() }))
    }, []),

    setSortBy: useCallback((field: string, direction?: 'asc' | 'desc') => {
      setState(prev => {
        const newDirection = direction || 
          (prev.sortBy === field && prev.sortDirection === 'asc' ? 'desc' : 'asc')
        return {
          ...prev,
          sortBy: field as any,
          sortDirection: newDirection
        }
      })
    }, []),

    setFilter: useCallback((filter: string) => {
      setState(prev => ({ ...prev, filterBy: filter }))
    }, []),

    setGroupBy: useCallback((groupBy: string) => {
      setState(prev => ({ ...prev, groupBy: groupBy as any }))
    }, []),

    downloadSelected: useCallback(async () => {
      const selectedResults = results.filter(r => state.selectedResults.has(r.id))
      
      if (selectedResults.length === 0) {
        throw new Error('No results selected')
      }

      if (selectedResults.length === 1) {
        // Single file download
        const result = selectedResults[0]
        const filename = result.name || `result-${result.id}`
        
        // This would typically call a download service
        // For now, we'll create a simple download
        let content: string
        let mimeType: string
        
        switch (result.type) {
          case 'json':
            content = JSON.stringify(result.content, null, 2)
            mimeType = 'application/json'
            break
          case 'table':
            // Convert to CSV
            const data = Array.isArray(result.content) ? result.content : []
            if (data.length > 0) {
              const headers = Object.keys(data[0]).join(',')
              const rows = data.map(row => Object.values(row).join(','))
              content = [headers, ...rows].join('\n')
              mimeType = 'text/csv'
            } else {
              throw new Error('No table data to download')
            }
            break
          default:
            content = typeof result.content === 'string' ? result.content : JSON.stringify(result.content)
            mimeType = 'text/plain'
        }
        
        const blob = new Blob([content], { type: mimeType })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      } else {
        // Multiple files - create zip
        // This would typically use a zip library like JSZip
        throw new Error('Multiple file download not implemented - would use JSZip')
      }
    }, [results, state.selectedResults]),

    shareSelected: useCallback(async () => {
      const selectedResults = results.filter(r => state.selectedResults.has(r.id))
      
      if (selectedResults.length === 0) {
        throw new Error('No results selected')
      }

      const shareData = {
        title: `${selectedResults.length} Research Results`,
        text: selectedResults.map(r => r.name).join(', '),
        url: window.location.href
      }

      if (navigator.share) {
        await navigator.share(shareData)
      } else {
        // Fallback to clipboard
        const text = `${shareData.title}\n${shareData.text}\n${shareData.url}`
        await navigator.clipboard.writeText(text)
      }
    }, [results, state.selectedResults])
  }

  return {
    state,
    results: sortedResults,
    groupedResults,
    actions,
    stats: {
      total: results.length,
      filtered: filteredResults.length,
      expanded: state.expandedResults.size,
      selected: state.selectedResults.size
    }
  }
}

// Utility hook for managing result metadata
export function useResultMetadata(result: ResultData) {
  const formatSize = useCallback((bytes?: number) => {
    if (!bytes) return 'Unknown size'
    
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    
    return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
  }, [])

  const formatDate = useCallback((dateString?: string) => {
    if (!dateString) return 'Unknown date'
    
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      })
    } catch {
      return dateString
    }
  }, [])

  const getTypeDescription = useCallback((type: ResultData['type']) => {
    switch (type) {
      case 'image':
        return 'Brain imaging visualization'
      case 'table':
        return 'Statistical data table'
      case 'json':
        return 'Structured data object'
      case 'report':
        return 'Analysis report'
      default:
        return 'Research file'
    }
  }, [])

  return {
    formatSize: () => formatSize(result.metadata?.size),
    formatDate: () => formatDate(result.metadata?.created_at),
    getTypeDescription: () => getTypeDescription(result.type),
    getTags: () => result.metadata?.tags || [],
    getAuthor: () => result.metadata?.author || 'Unknown',
    getDimensions: () => result.metadata?.dimensions || null
  }
}

// Hook for result performance monitoring
export function useResultPerformance() {
  const [metrics, setMetrics] = useState({
    renderTime: 0,
    loadTime: 0,
    memoryUsage: 0
  })

  const startTimer = useCallback((operation: string) => {
    const startTime = performance.now()
    
    return () => {
      const endTime = performance.now()
      const duration = endTime - startTime
      
      setMetrics(prev => ({
        ...prev,
        [operation]: duration
      }))
      
      return duration
    }
  }, [])

  const measureMemory = useCallback(() => {
    if ('memory' in performance) {
      const memory = (performance as any).memory
      setMetrics(prev => ({
        ...prev,
        memoryUsage: memory.usedJSHeapSize
      }))
    }
  }, [])

  return {
    metrics,
    startTimer,
    measureMemory
  }
}
