'use client'

import React, { useState, useCallback, useMemo } from 'react'
import { 
  Filter, X, ChevronDown, ChevronUp, 
  Search, Calendar, Tag, Users, 
  Database, RefreshCw, Save, History
} from 'lucide-react'

interface FilterOption {
  value: string
  label: string
  count?: number
}

interface FilterGroup {
  id: string
  label: string
  icon: React.ElementType
  type: 'checkbox' | 'radio' | 'range' | 'date'
  options?: FilterOption[]
  min?: number
  max?: number
  value?: any
}

interface FilterSidebarProps {
  filters: FilterGroup[]
  appliedFilters: Record<string, any>
  onFilterChange: (filters: Record<string, any>) => void
  onReset?: () => void
  onSave?: (name: string) => void
  savedFilters?: Array<{ id: string; name: string; filters: Record<string, any> }>
  showSearch?: boolean
  className?: string
}

export function FilterSidebar({
  filters,
  appliedFilters,
  onFilterChange,
  onReset,
  onSave,
  savedFilters = [],
  showSearch = true,
  className = ''
}: FilterSidebarProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set(filters.map(f => f.id))
  )
  const [searchTerm, setSearchTerm] = useState('')
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [filterName, setFilterName] = useState('')
  const [showSavedFilters, setShowSavedFilters] = useState(false)
  const [tempFilters, setTempFilters] = useState<Record<string, any>>(appliedFilters)

  // Toggle group expansion
  const toggleGroup = useCallback((groupId: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(groupId)) {
        next.delete(groupId)
      } else {
        next.add(groupId)
      }
      return next
    })
  }, [])

  // Handle filter change
  const handleFilterChange = useCallback((groupId: string, value: any) => {
    const newFilters = { ...tempFilters, [groupId]: value }
    setTempFilters(newFilters)
  }, [tempFilters])

  // Apply filters
  const applyFilters = useCallback(() => {
    onFilterChange(tempFilters)
  }, [tempFilters, onFilterChange])

  // Reset filters
  const handleReset = useCallback(() => {
    setTempFilters({})
    onReset?.()
    onFilterChange({})
  }, [onReset, onFilterChange])

  // Save current filters
  const handleSaveFilters = useCallback(() => {
    if (filterName && onSave) {
      onSave(filterName)
      setShowSaveDialog(false)
      setFilterName('')
    }
  }, [filterName, onSave])

  // Load saved filter
  const loadSavedFilter = useCallback((savedFilter: typeof savedFilters[0]) => {
    setTempFilters(savedFilter.filters)
    onFilterChange(savedFilter.filters)
    setShowSavedFilters(false)
  }, [onFilterChange])

  // Count active filters
  const activeFilterCount = useMemo(() => {
    return Object.keys(tempFilters).filter(key => {
      const value = tempFilters[key]
      if (Array.isArray(value)) return value.length > 0
      if (typeof value === 'object') return Object.keys(value).length > 0
      return value !== null && value !== undefined && value !== ''
    }).length
  }, [tempFilters])

  // Filter options based on search
  const filteredGroups = useMemo(() => {
    if (!searchTerm) return filters
    
    return filters.map(group => ({
      ...group,
      options: group.options?.filter(opt =>
        opt.label.toLowerCase().includes(searchTerm.toLowerCase())
      )
    })).filter(group => 
      group.label.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (group.options && group.options.length > 0)
    )
  }, [filters, searchTerm])

  // Render filter control based on type
  const renderFilterControl = (group: FilterGroup) => {
    const currentValue = tempFilters[group.id]

    switch (group.type) {
      case 'checkbox':
        return (
          <div className="space-y-2">
            {group.options?.map(option => (
              <label
                key={option.value}
                className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded"
              >
                <input
                  type="checkbox"
                  checked={currentValue?.includes(option.value) || false}
                  onChange={(e) => {
                    const values = currentValue || []
                    const newValues = e.target.checked
                      ? [...values, option.value]
                      : values.filter((v: string) => v !== option.value)
                    handleFilterChange(group.id, newValues)
                  }}
                  className="rounded border-gray-300 dark:border-gray-600 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">
                  {option.label}
                </span>
                {option.count !== undefined && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    ({option.count})
                  </span>
                )}
              </label>
            ))}
          </div>
        )

      case 'radio':
        return (
          <div className="space-y-2">
            {group.options?.map(option => (
              <label
                key={option.value}
                className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded"
              >
                <input
                  type="radio"
                  name={group.id}
                  value={option.value}
                  checked={currentValue === option.value}
                  onChange={() => handleFilterChange(group.id, option.value)}
                  className="border-gray-300 dark:border-gray-600 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">
                  {option.label}
                </span>
              </label>
            ))}
          </div>
        )

      case 'range':
        const rangeValue = currentValue || [group.min || 0, group.max || 100]
        return (
          <div className="space-y-2 px-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600 dark:text-gray-400">{rangeValue[0]}</span>
              <span className="text-gray-600 dark:text-gray-400">{rangeValue[1]}</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={group.min || 0}
                max={group.max || 100}
                value={rangeValue[0]}
                onChange={(e) => handleFilterChange(group.id, [Number(e.target.value), rangeValue[1]])}
                className="flex-1"
              />
              <input
                type="range"
                min={group.min || 0}
                max={group.max || 100}
                value={rangeValue[1]}
                onChange={(e) => handleFilterChange(group.id, [rangeValue[0], Number(e.target.value)])}
                className="flex-1"
              />
            </div>
          </div>
        )

      case 'date':
        return (
          <div className="space-y-2 px-2">
            <input
              type="date"
              value={currentValue?.start || ''}
              onChange={(e) => handleFilterChange(group.id, { ...currentValue, start: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm"
              placeholder="Start date"
            />
            <input
              type="date"
              value={currentValue?.end || ''}
              onChange={(e) => handleFilterChange(group.id, { ...currentValue, end: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm"
              placeholder="End date"
            />
          </div>
        )

      default:
        return null
    }
  }

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-lg ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Filter className="h-5 w-5 text-gray-500" />
            <h3 className="font-semibold text-gray-900 dark:text-white">
              Filters
            </h3>
            {activeFilterCount > 0 && (
              <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-xs rounded-full">
                {activeFilterCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowSavedFilters(!showSavedFilters)}
              className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="Saved filters"
            >
              <History className="h-4 w-4" />
            </button>
            <button
              onClick={() => setShowSaveDialog(true)}
              className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="Save current filters"
            >
              <Save className="h-4 w-4" />
            </button>
            <button
              onClick={handleReset}
              className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="Reset filters"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Search */}
        {showSearch && (
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search filters..."
              className="w-full pl-9 pr-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm"
            />
          </div>
        )}
      </div>

      {/* Saved Filters */}
      {showSavedFilters && savedFilters.length > 0 && (
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Saved Filters
          </h4>
          <div className="space-y-1">
            {savedFilters.map(saved => (
              <button
                key={saved.id}
                onClick={() => loadSavedFilter(saved)}
                className="w-full text-left px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 rounded"
              >
                {saved.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Filter Groups */}
      <div className="max-h-[600px] overflow-y-auto">
        {filteredGroups.map(group => {
          const Icon = group.icon
          const isExpanded = expandedGroups.has(group.id)
          const hasActiveFilter = tempFilters[group.id] && (
            Array.isArray(tempFilters[group.id]) 
              ? tempFilters[group.id].length > 0
              : tempFilters[group.id] !== null && tempFilters[group.id] !== undefined
          )

          return (
            <div key={group.id} className="border-b border-gray-200 dark:border-gray-700 last:border-b-0">
              <button
                onClick={() => toggleGroup(group.id)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50"
              >
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-gray-500" />
                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                    {group.label}
                  </span>
                  {hasActiveFilter && (
                    <div className="w-2 h-2 bg-blue-500 rounded-full" />
                  )}
                </div>
                {isExpanded ? (
                  <ChevronUp className="h-4 w-4 text-gray-400" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-gray-400" />
                )}
              </button>
              
              {isExpanded && (
                <div className="px-4 pb-3">
                  {renderFilterControl(group)}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Apply Button */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <button
          onClick={applyFilters}
          className="w-full px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-md font-medium"
        >
          Apply Filters
        </button>
      </div>

      {/* Save Dialog */}
      {showSaveDialog && (
        <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold mb-4">Save Filters</h3>
            <input
              type="text"
              value={filterName}
              onChange={(e) => setFilterName(e.target.value)}
              placeholder="Enter filter name..."
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md mb-4"
              autoFocus
            />
            <div className="flex gap-2">
              <button
                onClick={handleSaveFilters}
                className="flex-1 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-md"
              >
                Save
              </button>
              <button
                onClick={() => setShowSaveDialog(false)}
                className="flex-1 px-4 py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 rounded-md"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}