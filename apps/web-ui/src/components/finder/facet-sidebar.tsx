'use client'

import { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

interface Filter {
  facet: string
  value: any
  op: string
}

interface FacetValue {
  value: string | number | boolean
  count: number
}

interface FacetSidebarProps {
  filters: Filter[]
  onFiltersChange: (filters: Filter[]) => void
  className?: string
}

export function FacetSidebar({ filters, onFiltersChange, className = '' }: FacetSidebarProps) {
  const [facets, setFacets] = useState<Record<string, FacetValue[]>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openFacets, setOpenFacets] = useState<Set<string>>(new Set(['modality', 'task', 'source']))

  // Fetch facet counts when filters change
  useEffect(() => {
    const fetchFacets = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const response = await fetch('/api/finder/facets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filters }),
          cache: 'no-store',
        })
        
        if (response.ok) {
          const data = await response.json()
          const payload = data?.facets && typeof data.facets === 'object' ? data.facets : data
          setFacets(payload ?? {})
        } else {
          const detail = await response.text().catch(() => '')
          setFacets({})
          setError(detail || `HTTP ${response.status}`)
        }
      } catch (error) {
        console.error('Failed to fetch facets:', error)
        setFacets({})
        setError(error instanceof Error ? error.message : 'Failed to fetch facets')
      } finally {
        setIsLoading(false)
      }
    }

    fetchFacets()
  }, [filters])

  const toggleFacet = (facetName: string) => {
    const newOpenFacets = new Set(openFacets)
    if (newOpenFacets.has(facetName)) {
      newOpenFacets.delete(facetName)
    } else {
      newOpenFacets.add(facetName)
    }
    setOpenFacets(newOpenFacets)
  }

  const toggleFilter = (facet: string, value: any) => {
    const existingIndex = filters.findIndex(
      f => f.facet === facet && f.value === value
    )
    
    let newFilters: Filter[]
    if (existingIndex >= 0) {
      // Remove filter
      newFilters = filters.filter((_, i) => i !== existingIndex)
    } else {
      // Add filter
      newFilters = [...filters, { facet, value, op: '=' }]
    }
    
    onFiltersChange(newFilters)
  }

  const isFilterActive = (facet: string, value: any) => {
    return filters.some(f => f.facet === facet && f.value === value)
  }

  const formatFacetName = (name: string) => {
    const formatted: Record<string, string> = {
      modality: 'Modality',
      task: 'Task',
      population: 'Population',
      n_range: 'Sample Size',
      year: 'Year',
      source: 'Data Source',
      quality: 'Quality Flags'
    }
    return formatted[name] || name
  }

  const formatValue = (value: any) => {
    if (typeof value === 'boolean') {
      return value ? 'Yes' : 'No'
    }
    if (typeof value === 'string') {
      return value.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
    }
    return String(value)
  }

  return (
    <div className={`w-64 border-r bg-gray-50 ${className}`}>
      <div className="p-4 border-b">
        <h3 className="font-semibold text-lg">Filters</h3>
        {isLoading && (
          <div className="flex items-center gap-2 mt-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Updating...
          </div>
        )}
        {error && (
          <div className="mt-2 text-xs text-red-600">
            Facets unavailable: {error}
          </div>
        )}
      </div>

      <ScrollArea className="h-[calc(100vh-200px)]">
        <div className="p-4 space-y-4">
          {Object.entries(facets).map(([facetName, values]) => (
            <Collapsible
              key={facetName}
              open={openFacets.has(facetName)}
              onOpenChange={() => toggleFacet(facetName)}
            >
              <CollapsibleTrigger className="flex items-center justify-between w-full hover:bg-gray-100 p-2 rounded">
                <span className="font-medium">{formatFacetName(facetName)}</span>
                {openFacets.has(facetName) ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </CollapsibleTrigger>
              
              <CollapsibleContent className="space-y-2 mt-2">
                {values.slice(0, 10).map((item) => (
                  <div
                    key={`${facetName}-${item.value}`}
                    className="flex items-center space-x-2 pl-2"
                  >
                    <Checkbox
                      id={`${facetName}-${item.value}`}
                      checked={isFilterActive(facetName, item.value)}
                      onCheckedChange={() => toggleFilter(facetName, item.value)}
                      disabled={item.count === 0}
                    />
                    <Label
                      htmlFor={`${facetName}-${item.value}`}
                      className="flex-1 cursor-pointer text-sm flex justify-between items-center"
                    >
                      <span className={item.count === 0 ? 'text-gray-400' : ''}>
                        {formatValue(item.value)}
                      </span>
                      <span className="text-gray-500 text-xs">
                        ({item.count})
                      </span>
                    </Label>
                  </div>
                ))}
                
                {values.length > 10 && (
                  <button className="text-sm text-blue-600 hover:underline pl-2">
                    Show {values.length - 10} more...
                  </button>
                )}
              </CollapsibleContent>
            </Collapsible>
          ))}
        </div>
      </ScrollArea>

      {/* Active Filters Summary */}
      {filters.length > 0 && (
        <div className="p-4 border-t bg-white">
          <div className="text-sm text-gray-600">
            {filters.length} active filter{filters.length !== 1 ? 's' : ''}
          </div>
          <button
            onClick={() => onFiltersChange([])}
            className="text-sm text-blue-600 hover:underline mt-1"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  )
}
