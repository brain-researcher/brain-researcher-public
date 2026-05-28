'use client'

import { useState, useEffect } from 'react'
import { Search, X, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

interface Filter {
  facet: string
  value: any
  op: string
}

interface FinderSearchProps {
  onFiltersChange: (filters: Filter[]) => void
  className?: string
}

export function FinderSearch({ onFiltersChange, className = '' }: FinderSearchProps) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<Filter[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isFocused, setIsFocused] = useState(false)

  // Debounce query and parse filters
  useEffect(() => {
    if (!query.trim()) {
      setFilters([])
      onFiltersChange([])
      return
    }

    const timer = setTimeout(async () => {
      setIsLoading(true)
      try {
        const response = await fetch('/api/finder/suggestFilters', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: query })
        })
        
        if (response.ok) {
          const data = await response.json()
          setFilters(data.filters || [])
          onFiltersChange(data.filters || [])
        } else {
          setFilters([])
          onFiltersChange([])
        }
      } catch (error) {
        console.error('Failed to parse query:', error)
        setFilters([])
        onFiltersChange([])
      } finally {
        setIsLoading(false)
      }
    }, 500)

    return () => clearTimeout(timer)
  }, [query, onFiltersChange])

  const removeFilter = (index: number) => {
    const newFilters = filters.filter((_, i) => i !== index)
    setFilters(newFilters)
    onFiltersChange(newFilters)
  }

  const formatFilterValue = (filter: Filter) => {
    const op = filter.op === '=' ? '' : ` ${filter.op}`
    return `${filter.facet}${op} ${filter.value}`
  }

  const getFilterColor = (facet: string) => {
    const colors: Record<string, string> = {
      modality: 'bg-blue-500',
      task: 'bg-green-500',
      population: 'bg-purple-500',
      age: 'bg-orange-500',
      n: 'bg-red-500',
      year: 'bg-indigo-500',
      source: 'bg-pink-500',
      bids: 'bg-yellow-500',
      qc_ok: 'bg-teal-500',
      construct: 'bg-cyan-500'
    }
    return colors[facet] || 'bg-gray-500'
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {/* Search Input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-5 w-5" />
        <Input
          type="text"
          placeholder="Search datasets by task, modality, center, or condition"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          className="pl-10 pr-10 h-12 text-lg"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 transform -translate-y-1/2 h-5 w-5 animate-spin text-gray-400" />
        )}
        {query && !isLoading && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQuery('')
              setFilters([])
              onFiltersChange([])
            }}
            className="absolute right-2 top-1/2 transform -translate-y-1/2 h-8 w-8 p-0"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {isFocused && !query && (
        <div className="text-sm text-gray-500">
          Use filters below to narrow results by modality, population, and dataset size.
        </div>
      )}

      {/* Filter Chips */}
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {filters.map((filter, index) => (
            <Badge
              key={index}
              variant="secondary"
              className={`${getFilterColor(filter.facet)} text-white hover:opacity-80 cursor-pointer`}
              onClick={() => removeFilter(index)}
            >
              {formatFilterValue(filter)}
              <X className="ml-1 h-3 w-3" />
            </Badge>
          ))}
        </div>
      )}

      {/* Filter Summary */}
      {filters.length > 0 && (
        <div className="text-sm text-gray-600">
          Found {filters.length} filter{filters.length !== 1 ? 's' : ''} from your query
        </div>
      )}
    </div>
  )
}
