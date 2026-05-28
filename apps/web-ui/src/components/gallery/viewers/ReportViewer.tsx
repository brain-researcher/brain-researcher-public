'use client'

import React, { useState } from 'react'
import { 
  Download, Maximize2, Minimize2, FileText, 
  ChevronLeft, ChevronRight, Search, ZoomIn, ZoomOut,
  Copy, Printer, Share2, Bookmark
} from 'lucide-react'

interface ReportViewerProps {
  item: {
    id: string
    name: string
    fullUrl: string
    data?: string // HTML content for reports
    metadata: {
      format?: 'pdf' | 'html' | 'md' | 'docx'
      pages?: number
      fileSize?: number
      [key: string]: any
    }
  }
  onDownload?: () => void
  className?: string
}

export function ReportViewer({ item, onDownload, className = '' }: ReportViewerProps) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [zoomLevel, setZoomLevel] = useState(100)
  const [searchTerm, setSearchTerm] = useState('')
  const [viewMode, setViewMode] = useState<'rendered' | 'source'>('rendered')

  const totalPages = item.metadata.pages || 1

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen)
  }

  const handleZoomIn = () => {
    setZoomLevel(Math.min(200, zoomLevel + 25))
  }

  const handleZoomOut = () => {
    setZoomLevel(Math.max(50, zoomLevel - 25))
  }

  const handlePrint = () => {
    window.print()
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return 'Unknown size'
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
  }

  const renderContent = () => {
    if (item.metadata.format === 'html' && item.data) {
      return (
        <div 
          className="prose max-w-none p-6"
          style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top left' }}
          dangerouslySetInnerHTML={{ __html: item.data }}
        />
      )
    }

    if (item.metadata.format === 'pdf') {
      return (
        <div className="flex items-center justify-center h-full bg-gray-100">
          <div 
            className="bg-white shadow-lg border border-gray-300 rounded p-8 max-w-4xl"
            style={{ transform: `scale(${zoomLevel / 100})` }}
          >
            <div className="text-center">
              <FileText className="h-16 w-16 mx-auto mb-4 text-gray-400" />
              <h4 className="text-lg font-medium text-gray-700 mb-2">PDF Report</h4>
              <p className="text-sm text-gray-500 mb-4">{item.name}</p>
              <p className="text-xs text-gray-400">
                PDF viewer integration would render here
              </p>
              {item.metadata.pages && (
                <p className="text-xs text-gray-400 mt-2">
                  Page {currentPage} of {item.metadata.pages}
                </p>
              )}
            </div>
          </div>
        </div>
      )
    }

    // Fallback for other formats
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <FileText className="h-16 w-16 mx-auto mb-4 text-gray-400" />
          <h4 className="text-lg font-medium text-gray-700 mb-2">
            {item.metadata.format?.toUpperCase() || 'Document'} Report
          </h4>
          <p className="text-sm text-gray-500 mb-4">{item.name}</p>
          <p className="text-xs text-gray-400">
            Specialized viewer for {item.metadata.format} would render here
          </p>
        </div>
      </div>
    )
  }

  return (
    <div 
      className={`bg-white rounded-lg shadow-lg border border-gray-200 ${
        isFullscreen ? 'fixed inset-0 z-50' : ''
      } ${className}`}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">{item.name}</h3>
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 bg-yellow-100 text-yellow-800 text-xs rounded-full">
                {item.metadata.format?.toUpperCase() || 'Report'}
              </span>
              {item.metadata.pages && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                  {item.metadata.pages} pages
                </span>
              )}
              {item.metadata.fileSize && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                  {formatFileSize(item.metadata.fileSize)}
                </span>
              )}
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={handleZoomOut}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title="Zoom Out"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            
            <span className="text-sm text-gray-600 min-w-[50px] text-center">
              {zoomLevel}%
            </span>
            
            <button
              onClick={handleZoomIn}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title="Zoom In"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            
            <div className="w-px h-6 bg-gray-300 mx-1" />
            
            <button
              onClick={handlePrint}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title="Print"
            >
              <Printer className="h-4 w-4" />
            </button>
            
            {onDownload && (
              <button
                onClick={onDownload}
                className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
            
            <button
              onClick={toggleFullscreen}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            >
              {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="px-4 py-2 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between">
          {/* Search and View Mode */}
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search in document..."
                className="pl-10 pr-4 py-1.5 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            
            {item.data && (
              <div className="flex items-center bg-white rounded-lg shadow-sm">
                <button
                  onClick={() => setViewMode('rendered')}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors rounded-l-lg ${
                    viewMode === 'rendered'
                      ? 'bg-blue-500 text-white'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  Rendered
                </button>
                <button
                  onClick={() => setViewMode('source')}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors rounded-r-lg ${
                    viewMode === 'source'
                      ? 'bg-blue-500 text-white'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  Source
                </button>
              </div>
            )}
          </div>

          {/* Page Navigation */}
          {item.metadata.pages && item.metadata.pages > 1 && (
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-600">Page:</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="p-1.5 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[60px] text-center text-sm">
                  {currentPage} / {totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="p-1.5 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className={`overflow-auto ${isFullscreen ? 'h-screen' : 'h-96'} bg-gray-50`}>
        {viewMode === 'rendered' ? (
          renderContent()
        ) : (
          /* Source View */
          <div className="p-4">
            <div className="bg-gray-900 text-gray-100 rounded-lg p-4 h-full overflow-auto">
              <div className="mb-4 flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300">Source Code</h4>
                <button
                  onClick={() => {
                    if (item.data) {
                      navigator.clipboard.writeText(item.data)
                    }
                  }}
                  className="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs hover:bg-gray-600 transition-colors flex items-center gap-1"
                >
                  <Copy className="h-3 w-3" />
                  Copy
                </button>
              </div>
              <pre className="text-sm font-mono whitespace-pre-wrap">
                <code>{item.data || 'No source data available'}</code>
              </pre>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-200 bg-white">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Format</dt>
            <dd className="font-medium">{item.metadata.format?.toUpperCase() || 'Unknown'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Size</dt>
            <dd className="font-medium">{formatFileSize(item.metadata.fileSize)}</dd>
          </div>
          {item.metadata.pages && (
            <div>
              <dt className="text-gray-500">Pages</dt>
              <dd className="font-medium">{item.metadata.pages}</dd>
            </div>
          )}
          <div>
            <dt className="text-gray-500">Zoom</dt>
            <dd className="font-medium">{zoomLevel}%</dd>
          </div>
        </div>

        {/* Additional metadata */}
        {Object.entries(item.metadata)
          .filter(([key]) => !['format', 'fileSize', 'pages'].includes(key))
          .length > 0 && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <h5 className="text-sm font-medium text-gray-700 mb-2">Additional Properties</h5>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(item.metadata)
                .filter(([key]) => !['format', 'fileSize', 'pages'].includes(key))
                .map(([key, value]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-gray-500 capitalize">{key.replace(/_/g, ' ')}:</span>
                    <span className="font-medium text-gray-700 truncate ml-2">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}