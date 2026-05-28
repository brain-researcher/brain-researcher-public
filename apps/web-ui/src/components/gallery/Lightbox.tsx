'use client'

import React, { useState, useEffect } from 'react'
import { 
  X, ChevronLeft, ChevronRight, Download, Share2, 
  Maximize2, ZoomIn, ZoomOut, RotateCw, Layers,
  Grid3x3, Info, Copy, Bookmark, Eye, EyeOff
} from 'lucide-react'
import { BrainMapViewer } from './viewers/BrainMapViewer'
import { TableViewer } from './viewers/TableViewer'
import { GraphViewer } from './viewers/GraphViewer'
import { ReportViewer } from './viewers/ReportViewer'

interface LightboxProps {
  items: GalleryItem[]
  currentIndex: number
  onClose: () => void
  onNavigate: (index: number) => void
  onDownload?: (item: GalleryItem) => void
  onShare?: (item: GalleryItem) => void
  enableComparison?: boolean
  comparisonItems?: GalleryItem[]
  showComparison?: boolean
  onToggleComparison?: () => void
}

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
  data?: any // For table/graph data
  downloadUrl?: string
  shareUrl?: string
}

export function Lightbox({
  items,
  currentIndex,
  onClose,
  onNavigate,
  onDownload,
  onShare,
  enableComparison = false,
  comparisonItems = [],
  showComparison = false,
  onToggleComparison
}: LightboxProps) {
  const [showInfo, setShowInfo] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [copiedText, setCopiedText] = useState<string | null>(null)

  const currentItem = items[currentIndex]

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape':
          onClose()
          break
        case 'ArrowLeft':
          if (currentIndex > 0) {
            onNavigate(currentIndex - 1)
          }
          break
        case 'ArrowRight':
          if (currentIndex < items.length - 1) {
            onNavigate(currentIndex + 1)
          }
          break
        case 'i':
          setShowInfo(!showInfo)
          break
        case 'f':
          setIsFullscreen(!isFullscreen)
          break
        case 'c':
          if (enableComparison && onToggleComparison) {
            onToggleComparison()
          }
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [currentIndex, items.length, onClose, onNavigate, showInfo, isFullscreen, enableComparison, onToggleComparison])

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
  }

  const handleCopyInfo = async () => {
    const info = {
      name: currentItem.name,
      type: currentItem.type,
      size: formatFileSize(currentItem.fileSize),
      created: new Date(currentItem.created).toLocaleString(),
      analysis: currentItem.analysis,
      tags: currentItem.tags,
      metadata: currentItem.metadata
    }
    
    try {
      await navigator.clipboard.writeText(JSON.stringify(info, null, 2))
      setCopiedText('info')
      setTimeout(() => setCopiedText(null), 2000)
    } catch (error) {
      console.error('Failed to copy info:', error)
    }
  }

  const renderViewer = (item: GalleryItem) => {
    const viewerProps = {
      item: item,
      onDownload: () => onDownload?.(item),
      className: showComparison ? 'border border-gray-300' : ''
    }

    switch (item.type) {
      case 'brain-map':
      case 'statistical-map':
        return <BrainMapViewer {...viewerProps} />
      case 'table':
        return <TableViewer {...viewerProps} item={item as any} />
      case 'graph':
        return <GraphViewer {...viewerProps} item={item as any} />
      case 'report':
        return <ReportViewer {...viewerProps} item={item as any} />
      default:
        return (
          <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-8 text-center">
            <h3 className="text-lg font-semibold mb-4">{item.name}</h3>
            <p className="text-gray-600 mb-4">{item.description}</p>
            <div className="text-sm text-gray-500">
              <p>Type: {item.type}</p>
              <p>Size: {formatFileSize(item.fileSize)}</p>
              <p>Format: {item.metadata.format}</p>
            </div>
          </div>
        )
    }
  }

  return (
    <div className={`fixed inset-0 bg-black bg-opacity-90 z-50 ${isFullscreen ? 'p-0' : 'p-4'}`}>
      <div className={`h-full flex flex-col ${isFullscreen ? '' : 'max-w-7xl mx-auto'}`}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 bg-black bg-opacity-50 text-white">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold">{currentItem.name}</h2>
            <span className="text-sm text-gray-300">
              {currentIndex + 1} of {items.length}
            </span>
            {showComparison && comparisonItems.length > 0 && (
              <span className="px-2 py-1 bg-green-600 text-white text-xs rounded">
                Comparing {comparisonItems.length} items
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Navigation */}
            <button
              onClick={() => currentIndex > 0 && onNavigate(currentIndex - 1)}
              disabled={currentIndex === 0}
              className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Previous"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button
              onClick={() => currentIndex < items.length - 1 && onNavigate(currentIndex + 1)}
              disabled={currentIndex === items.length - 1}
              className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Next"
            >
              <ChevronRight className="h-5 w-5" />
            </button>

            <div className="w-px h-6 bg-white bg-opacity-30 mx-2" />

            {/* Actions */}
            <button
              onClick={() => setShowInfo(!showInfo)}
              className={`p-2 rounded-full transition-colors ${
                showInfo ? 'bg-blue-600' : 'hover:bg-white hover:bg-opacity-20'
              }`}
              title="Toggle info (i)"
            >
              <Info className="h-5 w-5" />
            </button>

            {enableComparison && onToggleComparison && (
              <button
                onClick={onToggleComparison}
                className={`p-2 rounded-full transition-colors ${
                  showComparison ? 'bg-green-600' : 'hover:bg-white hover:bg-opacity-20'
                }`}
                title="Toggle comparison (c)"
              >
                <Layers className="h-5 w-5" />
              </button>
            )}

            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors"
              title="Toggle fullscreen (f)"
            >
              <Maximize2 className="h-5 w-5" />
            </button>

            {onDownload && (
              <button
                onClick={() => onDownload(currentItem)}
                className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors"
                title="Download"
              >
                <Download className="h-5 w-5" />
              </button>
            )}

            {onShare && (
              <button
                onClick={() => onShare(currentItem)}
                className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors"
                title="Share"
              >
                <Share2 className="h-5 w-5" />
              </button>
            )}

            <button
              onClick={onClose}
              className="p-2 hover:bg-white hover:bg-opacity-20 rounded-full transition-colors"
              title="Close (Esc)"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className="flex-1 flex min-h-0">
          {/* Viewer Area */}
          <div className={`flex-1 p-4 ${showInfo ? 'pr-0' : ''}`}>
            {showComparison && comparisonItems.length > 0 ? (
              /* Comparison View */
              <div className="h-full">
                <div className={`grid gap-4 h-full ${
                  comparisonItems.length === 2 ? 'grid-cols-2' : 
                  comparisonItems.length === 3 ? 'grid-cols-3' : 
                  'grid-cols-2 grid-rows-2'
                }`}>
                  {comparisonItems.map((item, index) => (
                    <div key={item.id} className="relative">
                      <div className="absolute top-2 left-2 z-10 px-2 py-1 bg-black bg-opacity-70 text-white text-xs rounded">
                        {item.name}
                      </div>
                      {renderViewer(item)}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              /* Single Item View */
              <div className="h-full">
                {renderViewer(currentItem)}
              </div>
            )}
          </div>

          {/* Info Panel */}
          {showInfo && (
            <div className="w-80 bg-white border-l border-gray-200 overflow-auto">
              <div className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-900">Item Details</h3>
                  <button
                    onClick={handleCopyInfo}
                    className="p-2 hover:bg-gray-100 rounded-lg transition-colors relative"
                    title="Copy info as JSON"
                  >
                    <Copy className="h-4 w-4" />
                    {copiedText === 'info' && (
                      <span className="absolute -top-8 left-1/2 transform -translate-x-1/2 px-2 py-1 bg-gray-900 text-white text-xs rounded whitespace-nowrap">
                        Copied!
                      </span>
                    )}
                  </button>
                </div>

                <div className="space-y-4">
                  {/* Basic Info */}
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">Basic Information</h4>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-500">Name:</span>
                        <span className="font-medium text-right">{currentItem.name}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Type:</span>
                        <span className="font-medium">{currentItem.type}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Size:</span>
                        <span className="font-medium">{formatFileSize(currentItem.fileSize)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Format:</span>
                        <span className="font-medium">{currentItem.mimeType}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Created:</span>
                        <span className="font-medium text-right">
                          {new Date(currentItem.created).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Analysis Info */}
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">Analysis Details</h4>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-500">Type:</span>
                        <span className="font-medium">{currentItem.analysis.type}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Pipeline:</span>
                        <span className="font-medium text-right">{currentItem.analysis.pipeline}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Duration:</span>
                        <span className="font-medium">{currentItem.analysis.duration}s</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Status:</span>
                        <span className={`font-medium capitalize px-2 py-0.5 rounded text-xs ${
                          currentItem.analysis.status === 'completed' ? 'bg-green-100 text-green-800' :
                          currentItem.analysis.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                          'bg-red-100 text-red-800'
                        }`}>
                          {currentItem.analysis.status}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Tags */}
                  {currentItem.tags && currentItem.tags.length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">Tags</h4>
                      <div className="flex flex-wrap gap-1">
                        {currentItem.tags.map(tag => (
                          <span key={tag} className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Description */}
                  {currentItem.description && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">Description</h4>
                      <p className="text-sm text-gray-600">{currentItem.description}</p>
                    </div>
                  )}

                  {/* Annotations */}
                  {currentItem.annotations && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">Annotations</h4>
                      <p className="text-sm text-gray-600">{currentItem.annotations}</p>
                    </div>
                  )}

                  {/* Metadata */}
                  {Object.keys(currentItem.metadata).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">Metadata</h4>
                      <div className="space-y-1 text-sm">
                        {Object.entries(currentItem.metadata).map(([key, value]) => (
                          <div key={key} className="flex justify-between">
                            <span className="text-gray-500 capitalize">{key.replace(/_/g, ' ')}:</span>
                            <span className="font-medium text-right max-w-[60%] truncate">
                              {Array.isArray(value) ? value.join(', ') : 
                               typeof value === 'object' ? JSON.stringify(value) : 
                               String(value)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Keyboard Shortcuts Help */}
        <div className="absolute bottom-4 right-4 bg-black bg-opacity-70 text-white text-xs p-3 rounded-lg">
          <div className="space-y-1">
            <div><kbd className="bg-gray-600 px-1 rounded">←→</kbd> Navigate</div>
            <div><kbd className="bg-gray-600 px-1 rounded">Esc</kbd> Close</div>
            <div><kbd className="bg-gray-600 px-1 rounded">I</kbd> Info</div>
            <div><kbd className="bg-gray-600 px-1 rounded">F</kbd> Fullscreen</div>
            {enableComparison && <div><kbd className="bg-gray-600 px-1 rounded">C</kbd> Compare</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
