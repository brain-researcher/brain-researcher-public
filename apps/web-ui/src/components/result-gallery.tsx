'use client'

import React, { useState, useCallback } from 'react'
import { 
  Grid, List, Download, Share2, Eye, Filter, SortAsc, 
  Calendar, Tag, User, FileText, Image as ImageIcon,
  ChevronLeft, ChevronRight, Maximize2, X
} from 'lucide-react'
import Image from 'next/image'

interface ResultItem {
  id: string
  title: string
  description?: string
  type: 'image' | 'plot' | 'table' | 'document' | 'model'
  thumbnail?: string
  fullSizeUrl?: string
  metadata: {
    created_at: Date
    created_by?: string
    tags?: string[]
    size?: number
    dimensions?: { width: number; height: number }
    format?: string
    pipeline?: string
    parameters?: Record<string, any>
  }
  downloadUrl?: string
  shareUrl?: string
}

interface ResultGalleryProps {
  items: ResultItem[]
  viewMode?: 'grid' | 'list'
  onItemClick?: (item: ResultItem) => void
  onDownload?: (item: ResultItem) => void
  onShare?: (item: ResultItem) => void
  enableFiltering?: boolean
  enableSorting?: boolean
  itemsPerPage?: number
}

const typeIcons = {
  image: ImageIcon,
  plot: ImageIcon,
  table: FileText,
  document: FileText,
  model: FileText
}

const typeColors = {
  image: 'bg-blue-100 text-blue-700',
  plot: 'bg-green-100 text-green-700',
  table: 'bg-purple-100 text-purple-700',
  document: 'bg-yellow-100 text-yellow-700',
  model: 'bg-red-100 text-red-700'
}

export function ResultGallery({
  items,
  viewMode: initialViewMode = 'grid',
  onItemClick,
  onDownload,
  onShare,
  enableFiltering = true,
  enableSorting = true,
  itemsPerPage = 12
}: ResultGalleryProps) {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(initialViewMode)
  const [selectedItem, setSelectedItem] = useState<ResultItem | null>(null)
  const [lightboxItem, setLightboxItem] = useState<ResultItem | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [sortBy, setSortBy] = useState<'date' | 'name' | 'type'>('date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [filterType, setFilterType] = useState<string>('all')
  const [filterTags, setFilterTags] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')

  // Filter and sort items
  const processedItems = React.useMemo(() => {
    let filtered = [...items]

    // Apply type filter
    if (filterType !== 'all') {
      filtered = filtered.filter(item => item.type === filterType)
    }

    // Apply tag filter
    if (filterTags.size > 0) {
      filtered = filtered.filter(item => 
        item.metadata.tags?.some(tag => filterTags.has(tag))
      )
    }

    // Apply search
    if (searchQuery) {
      filtered = filtered.filter(item =>
        item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.description?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    }

    // Sort
    filtered.sort((a, b) => {
      let comparison = 0
      
      switch (sortBy) {
        case 'date':
          comparison = new Date(a.metadata.created_at).getTime() - 
                      new Date(b.metadata.created_at).getTime()
          break
        case 'name':
          comparison = a.title.localeCompare(b.title)
          break
        case 'type':
          comparison = a.type.localeCompare(b.type)
          break
      }
      
      return sortOrder === 'asc' ? comparison : -comparison
    })

    return filtered
  }, [items, filterType, filterTags, searchQuery, sortBy, sortOrder])

  // Pagination
  const totalPages = Math.ceil(processedItems.length / itemsPerPage)
  const paginatedItems = processedItems.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  )

  // Get all unique tags
  const allTags = React.useMemo(() => {
    const tags = new Set<string>()
    items.forEach(item => {
      item.metadata.tags?.forEach(tag => tags.add(tag))
    })
    return Array.from(tags)
  }, [items])

  const handleItemClick = useCallback((item: ResultItem) => {
    setSelectedItem(item)
    onItemClick?.(item)
  }, [onItemClick])

  const handleLightbox = useCallback((item: ResultItem) => {
    if (item.type === 'image' || item.type === 'plot') {
      setLightboxItem(item)
    }
  }, [])

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return 'Unknown size'
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
  }

  const GridItem = ({ item }: { item: ResultItem }) => {
    const TypeIcon = typeIcons[item.type]
    
    return (
      <div
        className="bg-white rounded-lg shadow-md hover:shadow-lg transition-shadow cursor-pointer overflow-hidden"
        onClick={() => handleItemClick(item)}
      >
        {/* Thumbnail */}
        <div className="relative h-48 bg-gray-100">
          {item.thumbnail ? (
            <Image
              src={item.thumbnail}
              alt={item.title}
              fill
              className="object-cover"
            />
          ) : (
            <div className="flex items-center justify-center h-full">
              <TypeIcon className="h-12 w-12 text-gray-400" />
            </div>
          )}
          
          {/* Type badge */}
          <span className={`absolute top-2 right-2 px-2 py-1 rounded text-xs font-medium ${typeColors[item.type]}`}>
            {item.type}
          </span>
        </div>

        {/* Content */}
        <div className="p-4">
          <h3 className="font-semibold text-gray-900 truncate">{item.title}</h3>
          {item.description && (
            <p className="text-sm text-gray-600 mt-1 line-clamp-2">{item.description}</p>
          )}
          
          {/* Metadata */}
          <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
            <span>{new Date(item.metadata.created_at).toLocaleDateString()}</span>
            {item.metadata.size && <span>{formatFileSize(item.metadata.size)}</span>}
          </div>

          {/* Tags */}
          {item.metadata.tags && item.metadata.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {item.metadata.tags.slice(0, 3).map(tag => (
                <span key={tag} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                  {tag}
                </span>
              ))}
              {item.metadata.tags.length > 3 && (
                <span className="px-2 py-0.5 text-gray-500 text-xs">
                  +{item.metadata.tags.length - 3} more
                </span>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleLightbox(item)
              }}
              className="p-1.5 hover:bg-gray-100 rounded"
              title="View"
            >
              <Eye className="h-4 w-4" />
            </button>
            {onDownload && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDownload(item)
                }}
                className="p-1.5 hover:bg-gray-100 rounded"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
            {onShare && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onShare(item)
                }}
                className="p-1.5 hover:bg-gray-100 rounded"
                title="Share"
              >
                <Share2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  const ListItem = ({ item }: { item: ResultItem }) => {
    const TypeIcon = typeIcons[item.type]
    
    return (
      <div
        className="bg-white rounded-lg shadow-sm hover:shadow-md transition-shadow cursor-pointer p-4"
        onClick={() => handleItemClick(item)}
      >
        <div className="flex items-center gap-4">
          {/* Thumbnail */}
          <div className="relative w-20 h-20 bg-gray-100 rounded flex-shrink-0">
            {item.thumbnail ? (
              <Image
                src={item.thumbnail}
                alt={item.title}
                fill
                className="object-cover rounded"
              />
            ) : (
              <div className="flex items-center justify-center h-full">
                <TypeIcon className="h-8 w-8 text-gray-400" />
              </div>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-gray-900 truncate">{item.title}</h3>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${typeColors[item.type]}`}>
                {item.type}
              </span>
            </div>
            {item.description && (
              <p className="text-sm text-gray-600 mt-1">{item.description}</p>
            )}
            <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                {new Date(item.metadata.created_at).toLocaleDateString()}
              </span>
              {item.metadata.created_by && (
                <span className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  {item.metadata.created_by}
                </span>
              )}
              {item.metadata.size && (
                <span>{formatFileSize(item.metadata.size)}</span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleLightbox(item)
              }}
              className="p-2 hover:bg-gray-100 rounded"
              title="View"
            >
              <Eye className="h-4 w-4" />
            </button>
            {onDownload && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDownload(item)
                }}
                className="p-2 hover:bg-gray-100 rounded"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
            {onShare && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onShare(item)
                }}
                className="p-2 hover:bg-gray-100 rounded"
                title="Share"
              >
                <Share2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-50 rounded-lg">
      {/* Header */}
      <div className="p-4 bg-white border-b border-gray-200">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">Results Gallery</h2>
          
          <div className="flex items-center gap-4">
            {/* Search */}
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search results..."
              className="px-3 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />

            {/* View mode toggle */}
            <div className="flex items-center bg-gray-100 rounded-md">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-2 rounded-l-md ${viewMode === 'grid' ? 'bg-white shadow' : ''}`}
                title="Grid view"
              >
                <Grid className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-2 rounded-r-md ${viewMode === 'list' ? 'bg-white shadow' : ''}`}
                title="List view"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Filters and Sorting */}
        {(enableFiltering || enableSorting) && (
          <div className="mt-4 flex items-center justify-between">
            {/* Filters */}
            {enableFiltering && (
              <div className="flex items-center gap-4">
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="px-3 py-1.5 border border-gray-300 rounded-md"
                >
                  <option value="all">All Types</option>
                  <option value="image">Images</option>
                  <option value="plot">Plots</option>
                  <option value="table">Tables</option>
                  <option value="document">Documents</option>
                  <option value="model">Models</option>
                </select>

                {allTags.length > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-600">Tags:</span>
                    {allTags.slice(0, 5).map(tag => (
                      <label key={tag} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={filterTags.has(tag)}
                          onChange={(e) => {
                            const newTags = new Set(filterTags)
                            if (e.target.checked) {
                              newTags.add(tag)
                            } else {
                              newTags.delete(tag)
                            }
                            setFilterTags(newTags)
                          }}
                          className="rounded"
                        />
                        <span className="text-sm">{tag}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Sorting */}
            {enableSorting && (
              <div className="flex items-center gap-2">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                  className="px-3 py-1.5 border border-gray-300 rounded-md"
                >
                  <option value="date">Date</option>
                  <option value="name">Name</option>
                  <option value="type">Type</option>
                </select>
                <button
                  onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                  className="p-1.5 hover:bg-gray-100 rounded"
                  title="Toggle sort order"
                >
                  <SortAsc className={`h-4 w-4 ${sortOrder === 'desc' ? 'rotate-180' : ''}`} />
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Results Grid/List */}
      <div className="p-4">
        {viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {paginatedItems.map(item => (
              <GridItem key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {paginatedItems.map(item => (
              <ListItem key={item.id} item={item} />
            ))}
          </div>
        )}

        {processedItems.length === 0 && (
          <div className="text-center py-12">
            <p className="text-gray-500">No results found</p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="p-4 border-t border-gray-200 bg-white">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">
              Showing {(currentPage - 1) * itemsPerPage + 1} to{' '}
              {Math.min(currentPage * itemsPerPage, processedItems.length)} of{' '}
              {processedItems.length} results
            </span>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage === 1}
                className="p-1.5 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const page = i + 1
                return (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`px-3 py-1 rounded ${
                      currentPage === page
                        ? 'bg-blue-500 text-white'
                        : 'hover:bg-gray-100'
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
                className="p-1.5 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Lightbox */}
      {lightboxItem && (
        <div className="fixed inset-0 bg-black bg-opacity-75 z-50 flex items-center justify-center p-4">
          <div className="relative max-w-4xl max-h-[90vh] bg-white rounded-lg overflow-hidden">
            <button
              onClick={() => setLightboxItem(null)}
              className="absolute top-4 right-4 p-2 bg-white rounded-full shadow-lg z-10"
            >
              <X className="h-4 w-4" />
            </button>
            
            {lightboxItem.fullSizeUrl ? (
              <Image
                src={lightboxItem.fullSizeUrl}
                alt={lightboxItem.title}
                width={1200}
                height={800}
                className="object-contain"
              />
            ) : (
              <div className="p-8">
                <h3 className="text-xl font-semibold mb-2">{lightboxItem.title}</h3>
                <p className="text-gray-600">{lightboxItem.description}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}