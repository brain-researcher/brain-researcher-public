'use client'

import React, { useState, useEffect } from 'react'
import { 
  FileText, Image as ImageIcon, Database, Code, 
  Download, Share2, Eye, Calendar, User,
  Clock, Tag, AlertCircle, CheckCircle
} from 'lucide-react'
import { ImageViewer } from './ImageViewer'
import { DataTable, TableColumn } from './DataTable'
import { JsonViewer } from './JsonViewer'

export interface ResultMetadata {
  created_at?: string
  author?: string
  version?: string
  tags?: string[]
  description?: string
  size?: number
  format?: string
  dimensions?: string
  [key: string]: any
}

export interface ResultData {
  id: string
  name: string
  type: 'image' | 'table' | 'json' | 'file' | 'report'
  content: any
  metadata?: ResultMetadata
  url?: string
  thumbnail?: string
}

interface ResultCardProps {
  result: ResultData
  expanded?: boolean
  onDownload?: (result: ResultData) => void
  onShare?: (result: ResultData) => void
  onToggleExpand?: (id: string) => void
  className?: string
}

// Type detection utilities
function detectResultType(data: any, filename?: string): ResultData['type'] {
  if (!data) return 'file'
  
  // Check filename extension
  if (filename) {
    const ext = filename.toLowerCase().split('.').pop()
    if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'nii', 'nii.gz'].includes(ext || '')) {
      return 'image'
    }
    if (['json', 'geojson'].includes(ext || '')) {
      return 'json'
    }
    if (['csv', 'tsv', 'xlsx'].includes(ext || '')) {
      return 'table'
    }
    if (['html', 'pdf', 'md', 'txt'].includes(ext || '')) {
      return 'report'
    }
  }
  
  // Check data structure
  if (typeof data === 'string' && data.startsWith('data:image/')) {
    return 'image'
  }
  
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
    return 'table'
  }
  
  if (typeof data === 'object' && data !== null) {
    return 'json'
  }
  
  return 'file'
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatDate(dateString: string): string {
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
}

function getTypeIcon(type: ResultData['type']) {
  switch (type) {
    case 'image':
      return ImageIcon
    case 'table':
      return Database
    case 'json':
      return Code
    case 'report':
      return FileText
    default:
      return FileText
  }
}

function getTypeColor(type: ResultData['type']): string {
  switch (type) {
    case 'image':
      return 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/20 dark:text-blue-400 dark:border-blue-800'
    case 'table':
      return 'bg-green-50 text-green-600 border-green-200 dark:bg-green-900/20 dark:text-green-400 dark:border-green-800'
    case 'json':
      return 'bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-900/20 dark:text-purple-400 dark:border-purple-800'
    case 'report':
      return 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/20 dark:text-orange-400 dark:border-orange-800'
    default:
      return 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-900/20 dark:text-gray-400 dark:border-gray-800'
  }
}

// Table columns generator for various data types
function generateTableColumns(data: any[]): TableColumn[] {
  if (!data || data.length === 0) return []
  
  const sampleRow = data[0]
  if (typeof sampleRow !== 'object') return []
  
  return Object.keys(sampleRow).map(key => ({
    key,
    header: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
    type: inferColumnType(data.map(row => row[key])),
    sortable: true,
    filterable: true
  }))
}

function inferColumnType(values: any[]): 'text' | 'number' | 'date' | 'boolean' {
  const nonNullValues = values.filter(v => v != null)
  if (nonNullValues.length === 0) return 'text'
  
  // Check if all values are boolean
  if (nonNullValues.every(v => typeof v === 'boolean')) {
    return 'boolean'
  }
  
  // Check if all values are numbers
  if (nonNullValues.every(v => typeof v === 'number' || (!isNaN(Number(v)) && v !== ''))) {
    return 'number'
  }
  
  // Check if all values look like dates
  if (nonNullValues.every(v => {
    const date = new Date(v)
    return !isNaN(date.getTime())
  })) {
    return 'date'
  }
  
  return 'text'
}

export function ResultCard({
  result,
  expanded = false,
  onDownload,
  onShare,
  onToggleExpand,
  className = ''
}: ResultCardProps) {
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actualType, setActualType] = useState<ResultData['type']>(result.type)
  
  useEffect(() => {
    // Auto-detect type if not specified or seems incorrect
    const detected = detectResultType(result.content, result.name)
    if (detected !== result.type) {
      setActualType(detected)
    }
  }, [result.content, result.name, result.type])
  
  const TypeIcon = getTypeIcon(actualType)
  const typeColor = getTypeColor(actualType)
  
  const handleDownload = async () => {
    if (onDownload) {
      setIsProcessing(true)
      try {
        await onDownload(result)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Download failed')
      } finally {
        setIsProcessing(false)
      }
    } else {
      // Default download behavior
      try {
        setIsProcessing(true)
        
        let blob: Blob
        let filename = result.name || `result-${result.id}`
        
        if (actualType === 'json') {
          blob = new Blob([JSON.stringify(result.content, null, 2)], { type: 'application/json' })
          if (!filename.endsWith('.json')) filename += '.json'
        } else if (actualType === 'table') {
          // Convert to CSV
          const data = Array.isArray(result.content) ? result.content : []
          if (data.length > 0) {
            const headers = Object.keys(data[0]).join(',')
            const rows = data.map(row => 
              Object.values(row).map(val => 
                typeof val === 'string' && val.includes(',') ? `"${val}"` : val
              ).join(',')
            )
            const csv = [headers, ...rows].join('\n')
            blob = new Blob([csv], { type: 'text/csv' })
            if (!filename.endsWith('.csv')) filename += '.csv'
          } else {
            throw new Error('No data to download')
          }
        } else if (result.url) {
          // Download from URL
          const response = await fetch(result.url)
          blob = await response.blob()
        } else {
          // Fallback to content as text
          blob = new Blob([String(result.content)], { type: 'text/plain' })
          if (!filename.includes('.')) filename += '.txt'
        }
        
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Download failed')
      } finally {
        setIsProcessing(false)
      }
    }
  }
  
  const handleShare = () => {
    if (onShare) {
      onShare(result)
    } else {
      // Default share behavior
      if (navigator.share) {
        navigator.share({
          title: result.name,
          text: result.metadata?.description,
          url: result.url || window.location.href
        })
      } else {
        // Fallback to clipboard
        navigator.clipboard.writeText(result.url || window.location.href)
      }
    }
  }
  
  const renderContent = () => {
    if (!expanded) return null
    
    try {
      switch (actualType) {
        case 'image':
          return (
            <ImageViewer
              src={result.url || result.content}
              alt={result.name}
              type={result.name?.toLowerCase().includes('nii') ? 'nifti' : 'standard'}
              onDownload={handleDownload}
              onShare={handleShare}
              className="h-96"
            />
          )
          
        case 'table':
          const columns = generateTableColumns(result.content)
          return (
            <DataTable
              data={Array.isArray(result.content) ? result.content : []}
              columns={columns}
              title={result.name}
              onDownload={handleDownload}
            />
          )
          
        case 'json':
          return (
            <JsonViewer
              data={result.content}
              title={result.name}
            />
          )
          
        default:
          return (
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
              <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words max-h-96 overflow-auto">
                {typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2)}
              </pre>
            </div>
          )
      }
    } catch (err) {
      return (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <AlertCircle className="h-5 w-5" />
            <span className="font-medium">Error displaying content</span>
          </div>
          <p className="mt-2 text-sm text-red-700 dark:text-red-300">
            {err instanceof Error ? err.message : 'Unknown error occurred'}
          </p>
        </div>
      )
    }
  }
  
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className={`p-2 rounded-lg border ${typeColor}`}>
              <TypeIcon className="h-5 w-5" />
            </div>
            
            <div className="flex-1 min-w-0">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate">
                {result.name || 'Untitled Result'}
              </h3>
              
              {result.metadata?.description && (
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
                  {result.metadata.description}
                </p>
              )}
              
              {/* Metadata Pills */}
              <div className="mt-2 flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                <span className={`px-2 py-1 rounded-full border ${typeColor} uppercase font-medium`}>
                  {actualType}
                </span>
                
                {result.metadata?.size && (
                  <span className="flex items-center gap-1">
                    <Database className="h-3 w-3" />
                    {formatFileSize(result.metadata.size)}
                  </span>
                )}
                
                {result.metadata?.created_at && (
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {formatDate(result.metadata.created_at)}
                  </span>
                )}
                
                {result.metadata?.author && (
                  <span className="flex items-center gap-1">
                    <User className="h-3 w-3" />
                    {result.metadata.author}
                  </span>
                )}
              </div>
              
              {/* Tags */}
              {result.metadata?.tags && result.metadata.tags.length > 0 && (
                <div className="mt-2 flex items-center gap-1 flex-wrap">
                  {result.metadata.tags.slice(0, 3).map((tag, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md text-xs"
                    >
                      <Tag className="h-2.5 w-2.5" />
                      {tag}
                    </span>
                  ))}
                  {result.metadata.tags.length > 3 && (
                    <span className="text-xs text-gray-400">+{result.metadata.tags.length - 3} more</span>
                  )}
                </div>
              )}
            </div>
          </div>
          
          {/* Action Buttons */}
          <div className="flex items-center gap-2 ml-4">
            {expanded && (
              <>
                <button
                  onClick={handleShare}
                  className="p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  title="Share result"
                >
                  <Share2 className="h-4 w-4" />
                </button>
                
                <button
                  onClick={handleDownload}
                  disabled={isProcessing}
                  className="p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
                  title="Download result"
                >
                  <Download className="h-4 w-4" />
                </button>
              </>
            )}
            
            <button
              onClick={() => onToggleExpand?.(result.id)}
              className="p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              title={expanded ? 'Collapse' : 'Expand'}
            >
              <Eye className={`h-4 w-4 ${expanded ? 'text-blue-500' : ''}`} />
            </button>
          </div>
        </div>
        
        {/* Error Display */}
        {error && (
          <div className="mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm font-medium">Error</span>
            </div>
            <p className="mt-1 text-sm text-red-700 dark:text-red-300">{error}</p>
            <button
              onClick={() => setError(null)}
              className="mt-2 text-sm text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 underline"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
      
      {/* Content */}
      {expanded && (
        <div className="p-4">
          {renderContent()}
        </div>
      )}
      
      {/* Processing Indicator */}
      {isProcessing && (
        <div className="absolute inset-0 bg-black bg-opacity-10 flex items-center justify-center">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-lg">
            <div className="flex items-center gap-3">
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-500 border-t-transparent" />
              <span className="text-sm font-medium">Processing...</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}