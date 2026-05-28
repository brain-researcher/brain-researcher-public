'use client'

import JSZip from 'jszip'
import { saveAs } from 'file-saver'

export interface GalleryItem {
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
  data?: any
  downloadUrl?: string
  shareUrl?: string
}

export interface FilterState {
  types: string[]
  dateRange?: [Date, Date]
  tags?: string[]
  search?: string
  analysisTypes?: string[]
  status?: string[]
}

/**
 * Format file size in human readable format
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  if (i === 0) return `${bytes} ${sizes[i]}`
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

/**
 * Format duration in human readable format
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${minutes}m`
}

/**
 * Filter items based on filter state
 */
export function filterItems(items: GalleryItem[], filters: FilterState): GalleryItem[] {
  return items.filter(item => {
    // Type filter
    if (filters.types.length > 0 && !filters.types.includes(item.type)) {
      return false
    }

    // Date range filter
    if (filters.dateRange) {
      const [startDate, endDate] = filters.dateRange
      const itemDate = new Date(item.created)
      if (itemDate < startDate || itemDate > endDate) {
        return false
      }
    }

    // Tags filter
    if (filters.tags && filters.tags.length > 0) {
      if (!item.tags.some(tag => filters.tags!.includes(tag))) {
        return false
      }
    }

    // Analysis type filter
    if (filters.analysisTypes && filters.analysisTypes.length > 0) {
      if (!filters.analysisTypes.includes(item.analysis.type)) {
        return false
      }
    }

    // Status filter
    if (filters.status && filters.status.length > 0) {
      if (!filters.status.includes(item.analysis.status)) {
        return false
      }
    }

    // Search filter
    if (filters.search) {
      const searchTerm = filters.search.toLowerCase()
      const searchFields = [
        item.name,
        item.description || '',
        item.analysis.type,
        item.analysis.pipeline,
        ...item.tags
      ].join(' ').toLowerCase()
      
      if (!searchFields.includes(searchTerm)) {
        return false
      }
    }

    return true
  })
}

/**
 * Sort items by specified criteria
 */
export function sortItems(
  items: GalleryItem[], 
  sortBy: 'date' | 'name' | 'size' | 'type',
  sortOrder: 'asc' | 'desc'
): GalleryItem[] {
  return [...items].sort((a, b) => {
    let comparison = 0

    switch (sortBy) {
      case 'date':
        comparison = new Date(a.created).getTime() - new Date(b.created).getTime()
        break
      case 'name':
        comparison = a.name.localeCompare(b.name)
        break
      case 'size':
        comparison = a.fileSize - b.fileSize
        break
      case 'type':
        comparison = a.type.localeCompare(b.type)
        break
    }

    return sortOrder === 'asc' ? comparison : -comparison
  })
}

/**
 * Paginate items
 */
export function paginateItems(
  items: GalleryItem[], 
  page: number, 
  itemsPerPage: number
): { items: GalleryItem[], totalPages: number, hasNext: boolean, hasPrev: boolean } {
  const totalPages = Math.ceil(items.length / itemsPerPage)
  const startIndex = (page - 1) * itemsPerPage
  const endIndex = startIndex + itemsPerPage
  const paginatedItems = items.slice(startIndex, endIndex)

  return {
    items: paginatedItems,
    totalPages,
    hasNext: page < totalPages,
    hasPrev: page > 1
  }
}

/**
 * Download multiple items as a ZIP file
 */
export async function downloadItemsAsZip(
  items: GalleryItem[], 
  zipName: string = 'results.zip'
): Promise<void> {
  const zip = new JSZip()
  
  try {
    // Add each item to the zip
    for (const item of items) {
      if (item.downloadUrl || item.fullUrl) {
        try {
          const response = await fetch(item.downloadUrl || item.fullUrl)
          const blob = await response.blob()
          
          // Determine file extension from mime type or filename
          let extension = getExtensionFromMimeType(item.mimeType) || 
                          getExtensionFromFilename(item.name) || 
                          'dat'
          
          const filename = `${sanitizeFilename(item.name)}.${extension}`
          zip.file(filename, blob)
          
          // Add metadata file for each item
          const metadata = {
            name: item.name,
            description: item.description,
            type: item.type,
            fileSize: item.fileSize,
            mimeType: item.mimeType,
            created: item.created,
            modified: item.modified,
            analysis: item.analysis,
            metadata: item.metadata,
            tags: item.tags,
            annotations: item.annotations
          }
          
          zip.file(`${sanitizeFilename(item.name)}_metadata.json`, JSON.stringify(metadata, null, 2))
        } catch (error) {
          console.error(`Failed to download ${item.name}:`, error)
          // Add error note to zip
          zip.file(`${sanitizeFilename(item.name)}_ERROR.txt`, 
                  `Failed to download ${item.name}: ${error}`)
        }
      }
    }

    // Add a manifest file
    const manifest = {
      created: new Date().toISOString(),
      itemCount: items.length,
      items: items.map(item => ({
        id: item.id,
        name: item.name,
        type: item.type,
        size: item.fileSize,
        analysis: item.analysis.type
      }))
    }
    
    zip.file('manifest.json', JSON.stringify(manifest, null, 2))

    // Generate and download the zip file
    const content = await zip.generateAsync({ type: 'blob' })
    saveAs(content, zipName)
    
  } catch (error) {
    console.error('Error creating ZIP file:', error)
    throw new Error('Failed to create download archive')
  }
}

/**
 * Export items metadata as CSV
 */
export function exportItemsAsCSV(items: GalleryItem[], filename: string = 'results.csv'): void {
  const headers = [
    'Name', 'Type', 'Size', 'Created', 'Modified', 'Analysis Type', 
    'Pipeline', 'Duration', 'Status', 'Tags', 'Description'
  ]
  
  const rows = items.map(item => [
    item.name,
    item.type,
    formatFileSize(item.fileSize),
    new Date(item.created).toISOString(),
    new Date(item.modified).toISOString(),
    item.analysis.type,
    item.analysis.pipeline,
    formatDuration(item.analysis.duration),
    item.analysis.status,
    item.tags.join('; '),
    item.description || ''
  ])
  
  const csvContent = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
  ].join('\n')
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  saveAs(blob, filename)
}

/**
 * Generate shareable link for items
 */
export function generateShareLink(items: GalleryItem[]): string {
  const itemIds = items.map(item => item.id)
  const params = new URLSearchParams({
    items: itemIds.join(','),
    view: 'gallery'
  })
  
  return `${window.location.origin}${window.location.pathname}?${params.toString()}`
}

/**
 * Copy items information to clipboard
 */
export async function copyItemsToClipboard(items: GalleryItem[]): Promise<void> {
  const text = items.map(item => {
    const info = [
      `Name: ${item.name}`,
      `Type: ${item.type}`,
      `Size: ${formatFileSize(item.fileSize)}`,
      `Created: ${new Date(item.created).toLocaleString()}`,
      `Analysis: ${item.analysis.type} (${item.analysis.pipeline})`,
      `Tags: ${item.tags.join(', ')}`
    ]
    
    if (item.description) {
      info.push(`Description: ${item.description}`)
    }
    
    return info.join('\n')
  }).join('\n\n---\n\n')
  
  try {
    await navigator.clipboard.writeText(text)
  } catch (error) {
    throw new Error('Failed to copy to clipboard')
  }
}

/**
 * Get all unique values for a field across items
 */
export function getUniqueValues(items: GalleryItem[], field: keyof GalleryItem): string[] {
  const values = new Set<string>()
  
  items.forEach(item => {
    const value = item[field]
    if (Array.isArray(value)) {
      value.forEach(v => values.add(String(v)))
    } else if (value) {
      values.add(String(value))
    }
  })
  
  return Array.from(values).sort()
}

/**
 * Get analysis statistics for items
 */
export function getAnalysisStats(items: GalleryItem[]) {
  const stats = {
    totalItems: items.length,
    totalSize: items.reduce((sum, item) => sum + item.fileSize, 0),
    typeBreakdown: {} as Record<string, number>,
    statusBreakdown: {} as Record<string, number>,
    analysisTypeBreakdown: {} as Record<string, number>,
    avgDuration: 0,
    totalDuration: 0
  }
  
  items.forEach(item => {
    // Type breakdown
    stats.typeBreakdown[item.type] = (stats.typeBreakdown[item.type] || 0) + 1
    
    // Status breakdown
    stats.statusBreakdown[item.analysis.status] = (stats.statusBreakdown[item.analysis.status] || 0) + 1
    
    // Analysis type breakdown
    stats.analysisTypeBreakdown[item.analysis.type] = (stats.analysisTypeBreakdown[item.analysis.type] || 0) + 1
    
    // Duration
    stats.totalDuration += item.analysis.duration
  })
  
  stats.avgDuration = items.length > 0 ? stats.totalDuration / items.length : 0
  
  return stats
}

// Helper functions
function getExtensionFromMimeType(mimeType: string): string | null {
  const mimeToExt: Record<string, string> = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'text/csv': 'csv',
    'text/plain': 'txt',
    'application/json': 'json',
    'application/pdf': 'pdf',
    'text/html': 'html',
    'application/zip': 'zip',
    'application/x-gzip': 'gz'
  }
  
  return mimeToExt[mimeType] || null
}

function getExtensionFromFilename(filename: string): string | null {
  const lastDot = filename.lastIndexOf('.')
  return lastDot >= 0 ? filename.substring(lastDot + 1) : null
}

function sanitizeFilename(filename: string): string {
  return filename.replace(/[^a-zA-Z0-9._-]/g, '_')
}
