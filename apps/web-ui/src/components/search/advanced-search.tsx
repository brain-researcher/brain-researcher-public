'use client'

import React, { useState, useCallback, useMemo } from 'react'
import { 
  Search, Filter, X, Plus, Minus, Calendar,
  Hash, Type, ToggleLeft, ToggleRight, Clock,
  Database, FileText, User, Tag, Folder,
  ChevronDown, ChevronUp, Save, History
} from 'lucide-react'

interface SearchFilter {
  id: string
  field: string
  operator: string
  value: string | number | boolean | Date
  type: 'text' | 'number' | 'boolean' | 'date' | 'select'
}

interface SearchQuery {
  filters: SearchFilter[]
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

interface SavedSearch {
  id: string
  name: string
  query: SearchQuery
  createdAt: Date
  lastUsed?: Date
  count?: number
}

interface AdvancedSearchProps {
  onSearch: (query: SearchQuery) => void
  onReset?: () => void
  savedSearches?: SavedSearch[]
  onSaveSearch?: (name: string, query: SearchQuery) => void
  onLoadSearch?: (search: SavedSearch) => void
  searchableFields?: Array<{
    field: string
    label: string
    type: 'text' | 'number' | 'boolean' | 'date' | 'select'
    options?: Array<{ value: string; label: string }>
  }>
}

export function AdvancedSearch({
  onSearch,
  onReset,
  savedSearches = [],
  onSaveSearch,
  onLoadSearch,
  searchableFields = [
    { field: 'name', label: 'Name', type: 'text' },
    { field: 'description', label: 'Description', type: 'text' },
    { field: 'type', label: 'Type', type: 'select', options: [
      { value: 'dataset', label: 'Dataset' },
      { value: 'analysis', label: 'Analysis' },
      { value: 'paper', label: 'Paper' },
      { value: 'tool', label: 'Tool' }
    ]},
    { field: 'createdAt', label: 'Created Date', type: 'date' },
    { field: 'modifiedAt', label: 'Modified Date', type: 'date' },
    { field: 'author', label: 'Author', type: 'text' },
    { field: 'tags', label: 'Tags', type: 'text' },
    { field: 'subjects', label: 'Subjects', type: 'number' },
    { field: 'published', label: 'Published', type: 'boolean' }
  ]
}: AdvancedSearchProps) {
  const [filters, setFilters] = useState<SearchFilter[]>([
    { id: '1', field: 'name', operator: 'contains', value: '', type: 'text' }
  ])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [sortBy, setSortBy] = useState('relevance')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [limit, setLimit] = useState(20)
  const [showSaved, setShowSaved] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [searchName, setSearchName] = useState('')
  const [recentSearches, setRecentSearches] = useState<SearchQuery[]>([])

  const operators = {
    text: ['contains', 'equals', 'starts with', 'ends with', 'not contains'],
    number: ['equals', 'greater than', 'less than', 'between', 'not equals'],
    boolean: ['is true', 'is false'],
    date: ['equals', 'before', 'after', 'between', 'in last'],
    select: ['equals', 'not equals', 'in', 'not in']
  }

  const addFilter = useCallback(() => {
    const newFilter: SearchFilter = {
      id: Date.now().toString(),
      field: searchableFields[0].field,
      operator: 'contains',
      value: '',
      type: searchableFields[0].type
    }
    setFilters([...filters, newFilter])
  }, [filters, searchableFields])

  const removeFilter = useCallback((id: string) => {
    setFilters(filters.filter(f => f.id !== id))
  }, [filters])

  const updateFilter = useCallback((id: string, updates: Partial<SearchFilter>) => {
    setFilters(filters.map(f => {
      if (f.id === id) {
        const updated = { ...f, ...updates }
        // Update operator when field type changes
        if (updates.field) {
          const field = searchableFields.find(sf => sf.field === updates.field)
          if (field) {
            updated.type = field.type
            updated.operator = operators[field.type][0]
          }
        }
        return updated
      }
      return f
    }))
  }, [filters, searchableFields])

  const handleSearch = useCallback(() => {
    const query: SearchQuery = {
      filters: filters.filter(f => f.value !== ''),
      sortBy,
      sortOrder,
      limit
    }
    
    onSearch(query)
    
    // Add to recent searches
    setRecentSearches(prev => [query, ...prev.slice(0, 4)])
  }, [filters, sortBy, sortOrder, limit, onSearch])

  const handleReset = useCallback(() => {
    setFilters([{ id: '1', field: 'name', operator: 'contains', value: '', type: 'text' }])
    setSortBy('relevance')
    setSortOrder('desc')
    setLimit(20)
    onReset?.()
  }, [onReset])

  const handleSaveSearch = useCallback(() => {
    if (!searchName) return
    
    const query: SearchQuery = {
      filters: filters.filter(f => f.value !== ''),
      sortBy,
      sortOrder,
      limit
    }
    
    onSaveSearch?.(searchName, query)
    setSaveDialogOpen(false)
    setSearchName('')
  }, [searchName, filters, sortBy, sortOrder, limit, onSaveSearch])

  const handleLoadSearch = useCallback((search: SavedSearch) => {
    setFilters(search.query.filters.length > 0 ? search.query.filters : [
      { id: '1', field: 'name', operator: 'contains', value: '', type: 'text' }
    ])
    setSortBy(search.query.sortBy || 'relevance')
    setSortOrder(search.query.sortOrder || 'desc')
    setLimit(search.query.limit || 20)
    setShowSaved(false)
    onLoadSearch?.(search)
  }, [onLoadSearch])

  const buildQueryString = useMemo(() => {
    const parts = filters
      .filter(f => f.value !== '')
      .map(f => {
        const field = searchableFields.find(sf => sf.field === f.field)
        return `${field?.label || f.field} ${f.operator} "${f.value}"`
      })
    
    return parts.length > 0 ? parts.join(' AND ') : 'All items'
  }, [filters, searchableFields])

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg">
      {/* Basic Search Bar */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Quick search..."
              value={filters[0]?.value as string || ''}
              onChange={(e) => updateFilter(filters[0]?.id || '1', { value: e.target.value })}
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-2"
          >
            <Filter className="h-4 w-4" />
            Advanced
            {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          
          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600"
          >
            Search
          </button>
        </div>
        
        {/* Query Preview */}
        <div className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          {buildQueryString}
        </div>
      </div>

      {/* Advanced Options */}
      {showAdvanced && (
        <div className="p-4 space-y-4">
          {/* Filters */}
          <div className="space-y-2">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium">Filters</h3>
              <button
                onClick={addFilter}
                className="text-blue-500 hover:text-blue-600 text-sm flex items-center gap-1"
              >
                <Plus className="h-3 w-3" />
                Add Filter
              </button>
            </div>
            
            {filters.map((filter, index) => (
              <div key={filter.id} className="flex items-center gap-2">
                {index > 0 && (
                  <span className="text-xs text-gray-500 w-8">AND</span>
                )}
                {index === 0 && <div className="w-8" />}
                
                <select
                  value={filter.field}
                  onChange={(e) => updateFilter(filter.id, { field: e.target.value })}
                  className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                >
                  {searchableFields.map(field => (
                    <option key={field.field} value={field.field}>{field.label}</option>
                  ))}
                </select>
                
                <select
                  value={filter.operator}
                  onChange={(e) => updateFilter(filter.id, { operator: e.target.value })}
                  className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                >
                  {operators[filter.type].map(op => (
                    <option key={op} value={op}>{op}</option>
                  ))}
                </select>
                
                {filter.type === 'text' || filter.type === 'number' ? (
                  <input
                    type={filter.type === 'number' ? 'number' : 'text'}
                    value={filter.value as string}
                    onChange={(e) => updateFilter(filter.id, { value: e.target.value })}
                    className="flex-1 px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                    placeholder="Enter value..."
                  />
                ) : filter.type === 'boolean' ? (
                  <button
                    onClick={() => updateFilter(filter.id, { 
                      value: filter.operator === 'is true' 
                    })}
                    className="px-2 py-1"
                  >
                    {filter.operator === 'is true' ? (
                      <ToggleRight className="h-5 w-5 text-green-500" />
                    ) : (
                      <ToggleLeft className="h-5 w-5 text-gray-400" />
                    )}
                  </button>
                ) : filter.type === 'date' ? (
                  <input
                    type="date"
                    value={filter.value as string}
                    onChange={(e) => updateFilter(filter.id, { value: e.target.value })}
                    className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                  />
                ) : filter.type === 'select' ? (
                  <select
                    value={filter.value as string}
                    onChange={(e) => updateFilter(filter.id, { value: e.target.value })}
                    className="flex-1 px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                  >
                    <option value="">Select...</option>
                    {searchableFields
                      .find(f => f.field === filter.field)
                      ?.options?.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))
                    }
                  </select>
                ) : null}
                
                {filters.length > 1 && (
                  <button
                    onClick={() => removeFilter(filter.id)}
                    className="p-1 text-red-500 hover:text-red-600"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Sort Options */}
          <div className="flex items-center gap-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium">Sort by:</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
              >
                <option value="relevance">Relevance</option>
                <option value="name">Name</option>
                <option value="createdAt">Created Date</option>
                <option value="modifiedAt">Modified Date</option>
                <option value="size">Size</option>
              </select>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium">Order:</label>
              <select
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
                className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
              >
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </div>
            
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium">Show:</label>
              <input
                type="number"
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="w-16 px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-sm"
                min="1"
                max="100"
              />
              <span className="text-sm text-gray-500">results</span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-between pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSaveDialogOpen(true)}
                className="px-3 py-1.5 bg-green-500 text-white rounded text-sm hover:bg-green-600 flex items-center gap-1"
              >
                <Save className="h-3 w-3" />
                Save Search
              </button>
              
              <button
                onClick={() => setShowSaved(!showSaved)}
                className="px-3 py-1.5 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded text-sm hover:bg-gray-200 dark:hover:bg-gray-600 flex items-center gap-1"
              >
                <History className="h-3 w-3" />
                Saved ({savedSearches.length})
              </button>
            </div>
            
            <button
              onClick={handleReset}
              className="px-3 py-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 text-sm"
            >
              Reset All
            </button>
          </div>
        </div>
      )}

      {/* Saved Searches */}
      {showSaved && (
        <div className="p-4 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-medium mb-2">Saved Searches</h3>
          <div className="space-y-1">
            {savedSearches.map(search => (
              <button
                key={search.id}
                onClick={() => handleLoadSearch(search)}
                className="w-full text-left px-3 py-2 bg-gray-50 dark:bg-gray-700 rounded hover:bg-gray-100 dark:hover:bg-gray-600"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{search.name}</span>
                  <span className="text-xs text-gray-500">
                    {search.count} results
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  Created {new Date(search.createdAt).toLocaleDateString()}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Save Dialog */}
      {saveDialogOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Save Search</h2>
            <input
              type="text"
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              placeholder="Enter search name..."
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md mb-4"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setSaveDialogOpen(false)}
                className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveSearch}
                className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}