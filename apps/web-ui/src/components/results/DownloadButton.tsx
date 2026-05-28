'use client'

import React, { useState } from 'react'
import { Download, FileText, Image, Database, Code, CheckCircle } from 'lucide-react'

export interface DownloadOptions {
  format: string
  label: string
  mimeType: string
  icon?: React.ComponentType<{ className?: string }>
}

interface DownloadButtonProps {
  data: any
  filename: string
  type?: 'image' | 'table' | 'json' | 'text' | 'auto'
  options?: DownloadOptions[]
  onDownload?: (data: any, format: string) => Promise<void> | void
  className?: string
  variant?: 'button' | 'icon' | 'menu'
}

const DEFAULT_OPTIONS: Record<string, DownloadOptions[]> = {
  image: [
    { format: 'png', label: 'PNG Image', mimeType: 'image/png', icon: Image },
    { format: 'jpg', label: 'JPEG Image', mimeType: 'image/jpeg', icon: Image },
    { format: 'svg', label: 'SVG Vector', mimeType: 'image/svg+xml', icon: Image }
  ],
  table: [
    { format: 'csv', label: 'CSV File', mimeType: 'text/csv', icon: Database },
    { format: 'json', label: 'JSON File', mimeType: 'application/json', icon: Code },
    { format: 'xlsx', label: 'Excel File', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', icon: Database },
    { format: 'tsv', label: 'TSV File', mimeType: 'text/tab-separated-values', icon: Database }
  ],
  json: [
    { format: 'json', label: 'JSON File', mimeType: 'application/json', icon: Code },
    { format: 'csv', label: 'CSV File', mimeType: 'text/csv', icon: Database },
    { format: 'txt', label: 'Text File', mimeType: 'text/plain', icon: FileText }
  ],
  text: [
    { format: 'txt', label: 'Text File', mimeType: 'text/plain', icon: FileText },
    { format: 'md', label: 'Markdown', mimeType: 'text/markdown', icon: FileText },
    { format: 'html', label: 'HTML File', mimeType: 'text/html', icon: FileText }
  ]
}

function detectDataType(data: any): 'image' | 'table' | 'json' | 'text' {
  if (typeof data === 'string') {
    if (data.startsWith('data:image/') || data.match(/\.(jpg|jpeg|png|gif|svg)$/i)) {
      return 'image'
    }
    return 'text'
  }
  
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
    return 'table'
  }
  
  if (typeof data === 'object' && data !== null) {
    return 'json'
  }
  
  return 'text'
}

function convertData(data: any, format: string, filename: string): { blob: Blob; filename: string } {
  let content: string
  let mimeType: string
  let extension: string
  
  switch (format) {
    case 'csv':
      if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
        // Convert array of objects to CSV
        const headers = Object.keys(data[0])
        const csvHeaders = headers.join(',')
        const csvRows = data.map(row => 
          headers.map(header => {
            const value = row[header]
            // Escape commas and quotes
            if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
              return `"${value.replace(/"/g, '""')}"`
            }
            return value == null ? '' : String(value)
          }).join(',')
        )
        content = [csvHeaders, ...csvRows].join('\n')
      } else if (typeof data === 'object' && data !== null) {
        // Convert object to CSV
        const entries = Object.entries(data)
        content = 'Key,Value\n' + entries.map(([key, value]) => 
          `"${key}","${String(value).replace(/"/g, '""')}"`
        ).join('\n')
      } else {
        throw new Error('Data cannot be converted to CSV format')
      }
      mimeType = 'text/csv'
      extension = 'csv'
      break
      
    case 'json':
      content = JSON.stringify(data, null, 2)
      mimeType = 'application/json'
      extension = 'json'
      break
      
    case 'tsv':
      if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
        const headers = Object.keys(data[0])
        const tsvHeaders = headers.join('\t')
        const tsvRows = data.map(row => 
          headers.map(header => String(row[header] || '')).join('\t')
        )
        content = [tsvHeaders, ...tsvRows].join('\n')
      } else {
        throw new Error('Data cannot be converted to TSV format')
      }
      mimeType = 'text/tab-separated-values'
      extension = 'tsv'
      break
      
    case 'txt':
      content = typeof data === 'string' ? data : 
               typeof data === 'object' ? JSON.stringify(data, null, 2) : 
               String(data)
      mimeType = 'text/plain'
      extension = 'txt'
      break
      
    case 'md':
      if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
        // Convert table to markdown
        const headers = Object.keys(data[0])
        const headerRow = '| ' + headers.join(' | ') + ' |'
        const separatorRow = '| ' + headers.map(() => '---').join(' | ') + ' |'
        const dataRows = data.map(row => 
          '| ' + headers.map(header => String(row[header] || '')).join(' | ') + ' |'
        )
        content = [headerRow, separatorRow, ...dataRows].join('\n')
      } else {
        content = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
      }
      mimeType = 'text/markdown'
      extension = 'md'
      break
      
    case 'html':
      if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
        const headers = Object.keys(data[0])
        const headerCells = headers.map(h => `<th>${h}</th>`).join('')
        const rows = data.map(row => 
          '<tr>' + headers.map(header => `<td>${String(row[header] || '')}</td>`).join('') + '</tr>'
        )
        content = `<!DOCTYPE html>
<html>
<head><title>Data Export</title></head>
<body>
<table border="1">
<thead><tr>${headerCells}</tr></thead>
<tbody>
${rows.join('\n')}
</tbody>
</table>
</body>
</html>`
      } else {
        content = `<!DOCTYPE html>
<html>
<head><title>Data Export</title></head>
<body>
<pre>${typeof data === 'string' ? data : JSON.stringify(data, null, 2)}</pre>
</body>
</html>`
      }
      mimeType = 'text/html'
      extension = 'html'
      break
      
    default:
      throw new Error(`Unsupported format: ${format}`)
  }
  
  const blob = new Blob([content], { type: mimeType })
  const baseFilename = filename.replace(/\.[^/.]+$/, '') // Remove existing extension
  const newFilename = `${baseFilename}.${extension}`
  
  return { blob, filename: newFilename }
}

export function DownloadButton({
  data,
  filename,
  type = 'auto',
  options,
  onDownload,
  className = '',
  variant = 'button'
}: DownloadButtonProps) {
  const [isDownloading, setIsDownloading] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [downloadComplete, setDownloadComplete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const detectedType = type === 'auto' ? detectDataType(data) : type
  const availableOptions = options || DEFAULT_OPTIONS[detectedType] || DEFAULT_OPTIONS.text
  
  const handleDownload = async (format: string) => {
    setIsDownloading(true)
    setError(null)
    
    try {
      if (onDownload) {
        await onDownload(data, format)
      } else {
        // Default download behavior
        const { blob, filename: finalFilename } = convertData(data, format, filename)
        
        // Create download link
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = finalFilename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      }
      
      setDownloadComplete(true)
      setTimeout(() => setDownloadComplete(false), 2000)
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setIsDownloading(false)
      setShowMenu(false)
    }
  }
  
  const handleSingleDownload = () => {
    if (availableOptions.length === 1) {
      handleDownload(availableOptions[0].format)
    } else {
      // Default to first option
      handleDownload(availableOptions[0].format)
    }
  }
  
  if (variant === 'icon') {
    return (
      <div className="relative">
        <button
          onClick={availableOptions.length > 1 ? () => setShowMenu(!showMenu) : handleSingleDownload}
          disabled={isDownloading}
          className={`p-2 rounded-lg transition-colors disabled:opacity-50 hover:bg-gray-100 dark:hover:bg-gray-700 ${className}`}
          title="Download"
        >
          {downloadComplete ? (
            <CheckCircle className="h-4 w-4 text-green-500" />
          ) : (
            <Download className={`h-4 w-4 ${isDownloading ? 'animate-pulse' : ''}`} />
          )}
        </button>
        
        {/* Dropdown Menu */}
        {showMenu && availableOptions.length > 1 && (
          <div className="absolute top-full right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 min-w-48">
            {availableOptions.map((option) => {
              const IconComponent = option.icon || Download
              return (
                <button
                  key={option.format}
                  onClick={() => handleDownload(option.format)}
                  className="w-full px-4 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-3 first:rounded-t-lg last:rounded-b-lg"
                >
                  <IconComponent className="h-4 w-4 text-gray-500 dark:text-gray-400" />
                  <div>
                    <div className="text-sm font-medium text-gray-900 dark:text-white">
                      {option.label}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {option.format.toUpperCase()}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    )
  }
  
  if (variant === 'menu') {
    return (
      <div className="space-y-1">
        {availableOptions.map((option) => {
          const IconComponent = option.icon || Download
          return (
            <button
              key={option.format}
              onClick={() => handleDownload(option.format)}
              disabled={isDownloading}
              className={`w-full px-4 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg flex items-center gap-3 transition-colors disabled:opacity-50 ${className}`}
            >
              <IconComponent className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              <div className="flex-1">
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  {option.label}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  Download as {option.format.toUpperCase()}
                </div>
              </div>
              {isDownloading && (
                <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-500 border-t-transparent" />
              )}
            </button>
          )
        })}
        
        {error && (
          <div className="px-4 py-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            {error}
          </div>
        )}
      </div>
    )
  }
  
  // Default button variant
  return (
    <div className="relative">
      <button
        onClick={availableOptions.length > 1 ? () => setShowMenu(!showMenu) : handleSingleDownload}
        disabled={isDownloading}
        className={`inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg transition-colors font-medium ${className}`}
      >
        {downloadComplete ? (
          <>
            <CheckCircle className="h-4 w-4" />
            Downloaded
          </>
        ) : isDownloading ? (
          <>
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
            Downloading...
          </>
        ) : (
          <>
            <Download className="h-4 w-4" />
            Download
            {availableOptions.length > 1 && (
              <span className="ml-1 text-xs opacity-75">
                ▼
              </span>
            )}
          </>
        )}
      </button>
      
      {/* Dropdown Menu */}
      {showMenu && availableOptions.length > 1 && (
        <div className="absolute top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 min-w-full">
          {availableOptions.map((option) => {
            const IconComponent = option.icon || Download
            return (
              <button
                key={option.format}
                onClick={() => handleDownload(option.format)}
                className="w-full px-4 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-3 first:rounded-t-lg last:rounded-b-lg"
              >
                <IconComponent className="h-4 w-4 text-gray-500 dark:text-gray-400" />
                <div>
                  <div className="text-sm font-medium text-gray-900 dark:text-white">
                    {option.label}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {option.format.toUpperCase()}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}
      
      {error && (
        <div className="absolute top-full left-0 mt-1 px-3 py-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg shadow-lg z-50">
          {error}
        </div>
      )}
    </div>
  )
}