'use client'

import React, { useState, useCallback, useMemo } from 'react'
import { 
  Grid, List, Download, Share2, Eye, Filter, SortAsc, 
  Calendar, Tag, User, FileText, Image as ImageIcon,
  ChevronLeft, ChevronRight, Maximize2, X, Check,
  Brain, BarChart3, TableIcon, Code2,
  Trash2, Archive, Copy, Layers, RefreshCw
} from 'lucide-react'
import Image from 'next/image'

// Enhanced interfaces for Brain Researcher specific needs
interface GalleryItem {
  id: string
  name: string
  description?: string
  type: 'brain-map' | 'table' | 'graph' | 'report' | 'metadata' | 'statistical-map'
  thumbnail: string
  fullUrl: string
  fileSize: number
  mimeType: string
  created: Date
  modified: Date
  analysis: {
    type: string
    pipeline: string
    duration: number
    status: 'completed' | 'processing' | 'failed'
  }
  metadata: {
    dimensions?: number[] | { width: number; height: number }
    voxelSize?: number[]
    rows?: number
    columns?: number
    format?: string
    [key: string]: any
  }
  tags: string[]
  annotations?: string
  downloadUrl?: string
  shareUrl?: string
}

interface GalleryView {
  layout: 'grid' | 'list' | 'masonry'
  itemsPerRow: number
  showMetadata: boolean
  sortBy: 'date' | 'name' | 'size' | 'type'
  sortOrder: 'asc' | 'desc'
  filters: {
    types: string[]
    dateRange?: [Date, Date]
    tags?: string[]
    search?: string
    analysisTypes?: string[]
  }
}

interface ResultGalleryProps {
  items: GalleryItem[]
  viewConfig?: Partial<GalleryView>
  onItemClick?: (item: GalleryItem) => void
  onDownload?: (item: GalleryItem) => void
  onShare?: (item: GalleryItem) => void
  onDelete?: (item: GalleryItem) => void
  enableBatchActions?: boolean
  enableComparison?: boolean
  enableFiltering?: boolean
  enableSorting?: boolean
  itemsPerPage?: number
  maxItems?: number
  className?: string
}

const typeIcons = {
  'brain-map': Brain,
  'statistical-map': Brain,
  table: TableIcon,
  graph: BarChart3,
  report: FileText,
  metadata: Code2
}

const typeColors = {
  'brain-map': 'bg-blue-100 text-blue-700 border-blue-200',
  'statistical-map': 'bg-indigo-100 text-indigo-700 border-indigo-200',
  table: 'bg-purple-100 text-purple-700 border-purple-200',
  graph: 'bg-green-100 text-green-700 border-green-200',
  report: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  metadata: 'bg-gray-100 text-gray-700 border-gray-200'
}

export function ResultGallery({
  items,
  viewConfig = {},
  onItemClick,
  onDownload,
  onShare,
  onDelete,
  enableBatchActions = true,
  enableComparison = true,
  enableFiltering = true,
  enableSorting = true,
  itemsPerPage = 12,
  maxItems,
  className = ''
}: ResultGalleryProps) {
  // View state
  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'masonry'>(viewConfig.layout || 'grid')
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())
  const [lightboxItem, setLightboxItem] = useState<GalleryItem | null>(null)
  const [comparisonItems, setComparisonItems] = useState<GalleryItem[]>([])
  const [showComparison, setShowComparison] = useState(false)
  
  // Pagination and filtering state
  const [currentPage, setCurrentPage] = useState(1)
  const [sortBy, setSortBy] = useState<'date' | 'name' | 'size' | 'type'>(viewConfig.sortBy || 'date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(viewConfig.sortOrder || 'asc')
  const [filterType, setFilterType] = useState<string>('all')
  const [filterTags, setFilterTags] = useState<Set<string>>(new Set())
  const [filterAnalysisType, setFilterAnalysisType] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Process and filter items
  const processedItems = useMemo(() => {
    let filtered = [...items]

    // Apply max items limit
    if (maxItems) {
      filtered = filtered.slice(0, maxItems)
    }

    // Apply type filter
    if (filterType !== 'all') {
      filtered = filtered.filter(item => item.type === filterType)
    }

    // Apply analysis type filter
    if (filterAnalysisType !== 'all') {
      filtered = filtered.filter(item => item.analysis.type === filterAnalysisType)
    }

    // Apply tag filter
    if (filterTags.size > 0) {
      filtered = filtered.filter(item => 
        item.tags?.some(tag => filterTags.has(tag))
      )
    }

    // Apply search
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(item =>
        item.name.toLowerCase().includes(query) ||
        item.description?.toLowerCase().includes(query) ||
        item.tags?.some(tag => tag.toLowerCase().includes(query))
      )
    }

    // Sort
    filtered.sort((a, b) => {
      let comparison = 0
      
      switch (sortBy) {
        case 'date':
          comparison = new Date(a.created).getTime() - new Date(b.created).getTime()
          break
        case 'name':
          comparison = a.name.localeCompare(b.name)
          break
        case 'size':
          comparison = (a.fileSize || 0) - (b.fileSize || 0)
          break
        case 'type':
          comparison = a.type.localeCompare(b.type)
          break
      }
      
      return sortOrder === 'asc' ? comparison : -comparison
    })

    return filtered
  }, [items, maxItems, filterType, filterAnalysisType, filterTags, searchQuery, sortBy, sortOrder])

  // Pagination
  const totalPages = Math.ceil(processedItems.length / itemsPerPage)
  const paginatedItems = processedItems.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  )

  // Get unique values for filters
  const allTags = useMemo(() => {
    const tags = new Set<string>()
    items.forEach(item => {
      item.tags?.forEach(tag => tags.add(tag))
    })
    return Array.from(tags).sort()
  }, [items])

  const allAnalysisTypes = useMemo(() => {
    const types = new Set<string>()
    items.forEach(item => types.add(item.analysis.type))
    return Array.from(types).sort()
  }, [items])

  // Batch selection handlers
  const handleSelectAll = () => {
    setSelectedItems((prev) => {
      if (prev.size === paginatedItems.length) {
        return new Set()
      }
      return new Set(paginatedItems.map(item => item.id))
    })
  }

  const handleItemSelect = (itemId: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) {
        next.delete(itemId)
      } else {
        next.add(itemId)
      }
      return next
    })
  }

  const handleBatchDownload = async () => {
    const selectedItemsArray = items.filter(item => selectedItems.has(item.id))
    // Implement batch download logic
    console.log('Downloading items:', selectedItemsArray)
  }

  const handleBatchDelete = async () => {
    const selectedItemsArray = items.filter(item => selectedItems.has(item.id))
    if (onDelete) {
      for (const item of selectedItemsArray) {
        await onDelete(item)
      }
    }
    setSelectedItems(new Set())
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
  }

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  }

  const addToComparison = (item: GalleryItem) => {
    setComparisonItems((prev) => {
      if (prev.length >= 4 || prev.find(i => i.id === item.id)) {
        return prev
      }
      return [...prev, item]
    })
  }

  const removeFromComparison = (itemId: string) => {
    setComparisonItems((prev) => prev.filter(item => item.id !== itemId))
  }

  const resetFilters = () => {
    setSearchQuery('')
    setFilterType('all')
    setFilterTags(new Set())
    setFilterAnalysisType('all')
    setCurrentPage(1)
  }

  const GalleryItemComponent = ({ item }: { item: GalleryItem }) => {
    const TypeIcon = typeIcons[item.type]
    const isSelected = selectedItems.has(item.id)
    const inComparison = comparisonItems.some(i => i.id === item.id)
    
    return (
      <div
        className={`bg-white rounded-lg shadow-md hover:shadow-lg transition-all cursor-pointer overflow-hidden border-2 ${
          isSelected ? 'border-blue-500 bg-blue-50' : 'border-transparent'
        } ${viewMode === 'list' ? 'flex items-center p-4' : ''}`}
        onClick={() => onItemClick?.(item)}
      >
        {/* Checkbox for selection */}
        {enableBatchActions && (
          <button
            type="button"
            className="absolute top-2 left-2 z-10"
            role="checkbox"
            aria-checked={isSelected}
            aria-label={`Select ${item.name}`}
            onClick={(e) => {
              e.stopPropagation()
              handleItemSelect(item.id)
            }}
            onKeyDown={(e) => {
              if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault()
                handleItemSelect(item.id)
              }
            }}
          >
            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center ${
              isSelected ? 'bg-blue-500 border-blue-500' : 'bg-white border-gray-300'
            }`}>
              {isSelected && <Check className="w-3 h-3 text-white" />}
            </div>
          </button>
        )}

        {viewMode === 'grid' ? (
          <div className="relative">
            {/* Thumbnail */}
            <div className="relative h-48 bg-gray-100">
              {item.thumbnail ? (
                <Image
                  src={item.thumbnail}
                  alt={item.name}
                  fill
                  className="object-cover"
                  sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
                />
              ) : (
                <div className="flex items-center justify-center h-full" role="img" aria-label={`${item.type} placeholder`}>
                  <TypeIcon className="h-12 w-12 text-gray-400" aria-hidden="true" />
                  <span className="sr-only">{item.type} placeholder</span>
                </div>
              )}
              
              {/* Status indicator */}
              <div className="absolute top-2 right-2 flex gap-1">
                <span className={`px-2 py-1 rounded text-xs font-medium border ${typeColors[item.type]}`}>
                  {item.type}
                </span>
                {item.analysis.status === 'processing' && (
                  <span className="px-2 py-1 bg-yellow-100 text-yellow-700 rounded text-xs animate-pulse">
                    Processing
                  </span>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="p-4">
              <h3 className="font-semibold text-gray-900 truncate mb-1">{item.name}</h3>
              {item.description && (
                <p className="text-sm text-gray-600 line-clamp-2 mb-2">{item.description}</p>
              )}
              
              {/* Metadata */}
              <div className="space-y-1 text-xs text-gray-500">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {new Date(item.created).toLocaleDateString()}
                  </span>
                  <span>{formatFileSize(item.fileSize)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>{item.analysis.type}</span>
                  <span>{formatDuration(item.analysis.duration)}</span>
                </div>
              </div>

              {/* Tags */}
              {item.tags && item.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {item.tags.slice(0, 3).map(tag => (
                    <span key={tag} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                      {tag}
                    </span>
                  ))}
                  {item.tags.length > 3 && (
                    <span className="px-2 py-0.5 text-gray-500 text-xs">
                      +{item.tags.length - 3}
                    </span>
                  )}
                </div>
              )}

              {/* Actions */}
              <div className="mt-3 flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setLightboxItem(item)
                    }}
                    className="p-1.5 hover:bg-gray-100 rounded transition-colors"
                    title="View"
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  {onDownload && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        Promise.resolve(onDownload(item)).catch((error) => {
                          console.error('Download failed', error)
                        })
                      }}
                      className="p-1.5 hover:bg-gray-100 rounded transition-colors"
                      title="Download"
                    >
                      <Download className="h-4 w-4" />
                    </button>
                  )}
                  {enableComparison && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (inComparison) {
                          removeFromComparison(item.id)
                        } else {
                          addToComparison(item)
                        }
                      }}
                      className={`p-1.5 rounded transition-colors ${
                        inComparison ? 'bg-green-100 text-green-600' : 'hover:bg-gray-100'
                      }`}
                      title={inComparison ? 'Remove from comparison' : 'Add to comparison'}
                    >
                      <Layers className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {onShare && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onShare(item)
                    }}
                    className="p-1.5 hover:bg-gray-100 rounded transition-colors"
                    title="Share"
                  >
                    <Share2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* List view layout */
          <div className="flex items-center gap-4 w-full">
            {/* Thumbnail */}
            <div className="relative w-20 h-20 bg-gray-100 rounded flex-shrink-0">
              {item.thumbnail ? (
                <Image
                  src={item.thumbnail}
                  alt={item.name}
                  fill
                  className="object-cover rounded"
                  sizes="80px"
                />
              ) : (
                <div className="flex items-center justify-center h-full" role="img" aria-label={`${item.type} placeholder`}>
                  <TypeIcon className="h-8 w-8 text-gray-400" aria-hidden="true" />
                  <span className="sr-only">{item.type} placeholder</span>
                </div>
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-gray-900 truncate">{item.name}</h3>
                <span className={`px-2 py-0.5 rounded text-xs font-medium border ${typeColors[item.type]}`}>
                  {item.type}
                </span>
              </div>
              {item.description && (
                <p className="text-sm text-gray-600 mb-2 line-clamp-2">{item.description}</p>
              )}
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span>{new Date(item.created).toLocaleDateString()}</span>
                <span>{formatFileSize(item.fileSize)}</span>
                <span>{item.analysis.type}</span>
                <span>{formatDuration(item.analysis.duration)}</span>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setLightboxItem(item)
                }}
                className="p-2 hover:bg-gray-100 rounded transition-colors"
                title="View"
              >
                <Eye className="h-4 w-4" />
              </button>
              {enableComparison && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (inComparison) {
                      removeFromComparison(item.id)
                    } else {
                      addToComparison(item)
                    }
                  }}
                  className={`p-2 rounded transition-colors ${
                    inComparison ? 'bg-green-100 text-green-600' : 'hover:bg-gray-100'
                  }`}
                  title={inComparison ? 'Remove from comparison' : 'Add to comparison'}
                >
                  <Layers className="h-4 w-4" />
                </button>
              )}
              {onDownload && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    Promise.resolve(onDownload(item)).catch((error) => {
                      console.error('Download failed', error)
                    })
                  }}
                  className="p-2 hover:bg-gray-100 rounded transition-colors"
                  title="Download"
                >
                  <Download className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`bg-gray-50 rounded-lg ${className}`}>
      {/* Header with controls */}
      <div className="p-4 bg-white border-b border-gray-200 rounded-t-lg">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Results Gallery</h2>
          
          <div className="flex items-center gap-4">
            {/* Search */}
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search results..."
              aria-label="Search results"
              className="px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />

            {/* View mode toggle */}
            <div className="flex items-center bg-gray-100 rounded-md">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-2 rounded-l-md transition-colors ${viewMode === 'grid' ? 'bg-white shadow text-blue-600' : 'text-gray-600 hover:text-gray-800'}`}
                title="Grid view"
              >
                <Grid className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-2 rounded-r-md transition-colors ${viewMode === 'list' ? 'bg-white shadow text-blue-600' : 'text-gray-600 hover:text-gray-800'}`}
                title="List view"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Batch Actions Bar */}
        {enableBatchActions && selectedItems.size > 0 && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-blue-900">
                {selectedItems.size} item{selectedItems.size > 1 ? 's' : ''} selected
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleBatchDownload}
                  className="px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors flex items-center gap-1"
                >
                  <Download className="h-4 w-4" />
                  Download
                </button>
                <button
                  onClick={() => setSelectedItems(new Set())}
                  className="px-3 py-1.5 bg-gray-600 text-white rounded-md hover:bg-gray-700 transition-colors"
                >
                  Clear
                </button>
                {onDelete && (
                  <button
                    onClick={handleBatchDelete}
                    className="px-3 py-1.5 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors flex items-center gap-1"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Comparison Bar */}
        {enableComparison && comparisonItems.length > 0 && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-green-900">
                  {comparisonItems.length} item{comparisonItems.length > 1 ? 's' : ''} ready for comparison
                </span>
                {comparisonItems.map(item => (
                  <span key={item.id} className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">
                    {item.name}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowComparison(true)}
                  className="px-3 py-1.5 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
                  disabled={comparisonItems.length < 2}
                >
                  Compare
                </button>
                <button
                  onClick={() => setComparisonItems([])}
                  className="px-3 py-1.5 bg-gray-600 text-white rounded-md hover:bg-gray-700 transition-colors"
                >
                  Clear
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Filters and Sorting */}
        {(enableFiltering || enableSorting) && (
          <div className="flex items-center justify-between flex-wrap gap-4">
            {/* Filters */}
            {enableFiltering && (
              <div className="flex items-center gap-4 flex-wrap">
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm"
                >
                  <option value="all">All Types</option>
                  <option value="brain-map">Brain Maps</option>
                  <option value="statistical-map">Statistical Maps</option>
                  <option value="table">Tables</option>
                  <option value="graph">Graphs</option>
                  <option value="report">Reports</option>
                  <option value="metadata">Metadata</option>
                </select>

                <select
                  value={filterAnalysisType}
                  onChange={(e) => setFilterAnalysisType(e.target.value)}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm"
                >
                  <option value="all">All Analysis Types</option>
                  {allAnalysisTypes.map(type => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>

                {/* Batch selection */}
                {enableBatchActions && (
                  <button
                    onClick={handleSelectAll}
                    className="px-3 py-1.5 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors text-sm"
                  >
                    {selectedItems.size === paginatedItems.length ? 'Deselect All' : 'Select All'}
                  </button>
                )}

                {(searchQuery || filterType !== 'all' || filterTags.size > 0 || filterAnalysisType !== 'all') && (
                  <button
                    onClick={resetFilters}
                    className="px-3 py-1.5 text-sm text-blue-600 border border-blue-200 rounded-md hover:bg-blue-50 transition-colors"
                  >
                    Clear filters
                  </button>
                )}
              </div>
            )}

            {/* Sorting */}
            {enableSorting && (
              <div className="flex items-center gap-2">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm"
                >
                  <option value="date">Date</option>
                  <option value="name">Name</option>
                  <option value="size">File Size</option>
                  <option value="type">Type</option>
                </select>
                <button
                  onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                  className="p-1.5 hover:bg-gray-100 rounded transition-colors"
                  title="Toggle sort order"
                >
                  <SortAsc className={`h-4 w-4 transition-transform ${sortOrder === 'desc' ? 'rotate-180' : ''}`} />
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Results Display */}
      <div className="p-4">
        {viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {paginatedItems.map(item => (
              <GalleryItemComponent key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {paginatedItems.map(item => (
              <GalleryItemComponent key={item.id} item={item} />
            ))}
          </div>
        )}

        {processedItems.length === 0 && (
          <div className="text-center py-12">
            <div className="text-gray-400 mb-2">
              <FileText className="h-12 w-12 mx-auto" />
            </div>
            <p className="text-gray-500">No results found</p>
            {(searchQuery || filterType !== 'all' || filterTags.size > 0) && (
              <button
                onClick={resetFilters}
                className="mt-2 text-blue-600 hover:text-blue-800 transition-colors"
              >
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Pagination */}
      {processedItems.length > 0 && (
        <div className="p-4 border-t border-gray-200 bg-white rounded-b-lg">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">
              Showing {Math.min((currentPage - 1) * itemsPerPage + 1, processedItems.length)} to{' '}
              {Math.min(currentPage * itemsPerPage, processedItems.length)} of{' '}
              {processedItems.length} results
            </span>
            
            {totalPages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="p-1.5 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const page = i + 1
                  const isCurrentPage = currentPage === page
                  return (
                    <button
                      key={page}
                      onClick={() => setCurrentPage(page)}
                      className={`px-3 py-1 rounded transition-colors ${
                        isCurrentPage
                          ? 'bg-blue-500 text-white'
                          : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      {page}
                    </button>
                  )
                })}
                
                {totalPages > 5 && <span className="text-gray-500">...</span>}
                
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="p-1.5 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Simple Lightbox */}
      {lightboxItem && (
        <div className="fixed inset-0 bg-black bg-opacity-75 z-50 flex items-center justify-center p-4">
          <div className="relative max-w-6xl max-h-[90vh] bg-white rounded-lg overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold">{lightboxItem.name}</h3>
              <button
                onClick={() => setLightboxItem(null)}
                className="p-2 hover:bg-gray-100 rounded transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            
            <div className="p-4 max-h-[80vh] overflow-auto">
              {lightboxItem.fullUrl ? (
                <Image
                  src={lightboxItem.fullUrl}
                  alt={lightboxItem.name}
                  width={1200}
                  height={800}
                  className="object-contain mx-auto"
                />
              ) : (
                <div className="text-center py-12">
                  <h4 className="text-xl font-semibold mb-2">{lightboxItem.name}</h4>
                  <p className="text-gray-600 mb-4">{lightboxItem.description}</p>
                  <div className="text-sm text-gray-500">
                    <p>Type: {lightboxItem.type}</p>
                    <p>Size: {formatFileSize(lightboxItem.fileSize)}</p>
                    <p>Created: {new Date(lightboxItem.created).toLocaleString()}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
