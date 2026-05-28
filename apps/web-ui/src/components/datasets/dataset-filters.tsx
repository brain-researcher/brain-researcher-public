'use client'

import { useState, useEffect } from 'react'
import { Search, Filter, X, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { DatasetFilters } from '@/types/dataset'
import { getFilterOptions } from '@/lib/datasets'

interface DatasetFiltersProps {
  filters: DatasetFilters
  onFiltersChange: (filters: DatasetFilters) => void
  onClearFilters: () => void
}

export function DatasetFiltersComponent({ filters, onFiltersChange, onClearFilters }: DatasetFiltersProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [filterOptions, setFilterOptions] = useState(getFilterOptions())

  useEffect(() => {
    setFilterOptions(getFilterOptions())
  }, [])

  const hasActiveFilters = Object.values(filters).some(value => 
    Array.isArray(value) ? value.length > 0 : value !== undefined && value !== ''
  )

  const updateFilters = (key: keyof DatasetFilters, value: any) => {
    onFiltersChange({ ...filters, [key]: value })
  }

  const toggleArrayFilter = (key: keyof DatasetFilters, value: string) => {
    const currentArray = (filters[key] as string[]) || []
    const newArray = currentArray.includes(value)
      ? currentArray.filter(item => item !== value)
      : [...currentArray, value]
    updateFilters(key, newArray.length > 0 ? newArray : undefined)
  }

  return (
    <Card className="mb-6">
      <CardContent className="p-4">
        {/* Search bar */}
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search datasets, tasks, or tags..."
            value={filters.search || ''}
            onChange={(e) => updateFilters('search', e.target.value || undefined)}
            className="pl-10 pr-10"
          />
          {filters.search && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateFilters('search', undefined)}
              className="absolute right-1 top-1/2 transform -translate-y-1/2 h-6 w-6 p-0"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>

        {/* Filter toggle */}
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-2"
          >
            <Filter className="h-4 w-4" />
            Filters
            {hasActiveFilters && (
              <span className="bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-xs">
                {Object.values(filters).filter(v => Array.isArray(v) ? v.length > 0 : v).length}
              </span>
            )}
            <ChevronDown className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
          </Button>

          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearFilters}
              className="text-muted-foreground hover:text-foreground"
            >
              Clear all
            </Button>
          )}
        </div>

        {/* Expanded filters */}
        {isExpanded && (
          <div className="mt-4 space-y-4 border-t pt-4">
            {/* Modality filter */}
            <div>
              <label className="text-sm font-medium mb-2 block">Modality</label>
              <div className="flex flex-wrap gap-2">
                {filterOptions.modalities.map((modality) => (
                  <Button
                    key={modality}
                    variant={filters.modality?.includes(modality) ? "default" : "outline"}
                    size="sm"
                    onClick={() => toggleArrayFilter('modality', modality)}
                  >
                    {modality}
                  </Button>
                ))}
              </div>
            </div>

            {filterOptions.categories?.length ? (
              <div>
                <label className="text-sm font-medium mb-2 block">Category</label>
                <div className="flex flex-wrap gap-2">
                  {filterOptions.categories.map((category) => (
                    <Button
                      key={category}
                      variant={filters.category?.includes(category) ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => toggleArrayFilter('category', category)}
                    >
                      {category}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Source filter */}
            <div>
              <label className="text-sm font-medium mb-2 block">Source</label>
              <div className="flex flex-wrap gap-2">
                {filterOptions.sources.map((source) => (
                  <Button
                    key={source}
                    variant={filters.source?.includes(source) ? "default" : "outline"}
                    size="sm"
                    onClick={() => toggleArrayFilter('source', source)}
                  >
                    {source}
                  </Button>
                ))}
              </div>
            </div>

            {/* Subject count range */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">Min Subjects</label>
                <Input
                  type="number"
                  placeholder="Minimum"
                  value={filters.nSubjectsMin || ''}
                  onChange={(e) => updateFilters('nSubjectsMin', e.target.value ? parseInt(e.target.value) : undefined)}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Max Subjects</label>
                <Input
                  type="number"
                  placeholder="Maximum"
                  value={filters.nSubjectsMax || ''}
                  onChange={(e) => updateFilters('nSubjectsMax', e.target.value ? parseInt(e.target.value) : undefined)}
                />
              </div>
            </div>

            {/* Tasks filter */}
            <div>
              <label className="text-sm font-medium mb-2 block">Tasks</label>
              <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                {filterOptions.tasks.map((task) => (
                  <Button
                    key={task}
                    variant={filters.tasks?.includes(task) ? "default" : "outline"}
                    size="sm"
                    onClick={() => toggleArrayFilter('tasks', task)}
                  >
                    {task}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
