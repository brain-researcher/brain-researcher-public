'use client'

import React, { useState } from 'react'
import { 
  FileText, Download, Share2, Copy, CheckCircle,
  Eye, Maximize2, X, ChevronLeft, ChevronRight,
  BarChart3, Brain, Table, Code
} from 'lucide-react'
import Image from 'next/image'

interface ResultFile {
  id: string
  name: string
  type: 'image' | 'data' | 'report' | 'code'
  size: string
  url: string
  thumbnail?: string
}

interface ResultMetric {
  label: string
  value: string | number
  unit?: string
  description?: string
}

interface BasicResultDisplayProps {
  title: string
  description?: string
  files: ResultFile[]
  metrics?: ResultMetric[]
  metadata?: Record<string, any>
  onDownload?: (file: ResultFile) => void
  onShare?: () => void
}

export function BasicResultDisplay({
  title,
  description,
  files,
  metrics = [],
  metadata = {},
  onDownload,
  onShare
}: BasicResultDisplayProps) {
  const [selectedFile, setSelectedFile] = useState<ResultFile | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [showLightbox, setShowLightbox] = useState(false)
  const [currentImageIndex, setCurrentImageIndex] = useState(0)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const imageFiles = files.filter(f => f.type === 'image')
  const dataFiles = files.filter(f => f.type === 'data')
  const reportFiles = files.filter(f => f.type === 'report')
  const codeFiles = files.filter(f => f.type === 'code')

  const handleDownload = async (file: ResultFile) => {
    if (onDownload) {
      onDownload(file)
    } else {
      // Default download behavior
      try {
        const response = await fetch(file.url)
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = file.name
        a.click()
        URL.revokeObjectURL(url)
      } catch (err) {
        console.error('Download failed:', err)
      }
    }
  }

  const handleCopyLink = (file: ResultFile) => {
    navigator.clipboard.writeText(window.location.origin + file.url)
    setCopiedId(file.id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const openLightbox = (index: number) => {
    setCurrentImageIndex(index)
    setShowLightbox(true)
  }

  const getFileIcon = (type: string) => {
    switch (type) {
      case 'image':
        return Brain
      case 'data':
        return Table
      case 'report':
        return FileText
      case 'code':
        return Code
      default:
        return FileText
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg">
      {/* Header */}
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
              {title}
            </h2>
            {description && (
              <p className="mt-2 text-gray-600 dark:text-gray-400">
                {description}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onShare}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              title="Share results"
            >
              <Share2 className="h-5 w-5 text-gray-600 dark:text-gray-400" />
            </button>
          </div>
        </div>

        {/* View Mode Toggle */}
        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={() => setViewMode('grid')}
            className={`px-3 py-1.5 rounded-md text-sm font-medium ${
              viewMode === 'grid'
                ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
          >
            Grid View
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-3 py-1.5 rounded-md text-sm font-medium ${
              viewMode === 'list'
                ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
          >
            List View
          </button>
        </div>
      </div>

      {/* Metrics */}
      {metrics.length > 0 && (
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Key Metrics
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {metrics.map((metric, index) => (
              <div key={index} className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
                <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">
                  {metric.label}
                </div>
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {metric.value}
                  {metric.unit && (
                    <span className="text-lg font-normal text-gray-500 dark:text-gray-400 ml-1">
                      {metric.unit}
                    </span>
                  )}
                </div>
                {metric.description && (
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {metric.description}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Files */}
      <div className="p-6">
        {viewMode === 'grid' ? (
          <div className="space-y-6">
            {/* Images */}
            {imageFiles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Brain className="h-5 w-5" />
                  Visualizations
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {imageFiles.map((file, index) => (
                    <div
                      key={file.id}
                      className="relative group cursor-pointer"
                      onClick={() => openLightbox(index)}
                    >
                      <div className="aspect-square bg-gray-100 dark:bg-gray-700 rounded-lg overflow-hidden">
                        <img
                          src={file.thumbnail || file.url}
                          alt={file.name}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                        />
                      </div>
                      <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-50 transition-opacity rounded-lg flex items-center justify-center">
                        <Eye className="h-8 w-8 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                      <p className="mt-2 text-sm text-gray-700 dark:text-gray-300 truncate">
                        {file.name}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Data Files */}
            {dataFiles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Table className="h-5 w-5" />
                  Data Files
                </h3>
                <div className="grid md:grid-cols-2 gap-4">
                  {dataFiles.map((file) => (
                    <FileCard
                      key={file.id}
                      file={file}
                      onDownload={handleDownload}
                      onCopyLink={handleCopyLink}
                      copied={copiedId === file.id}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Reports */}
            {reportFiles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  Reports
                </h3>
                <div className="space-y-2">
                  {reportFiles.map((file) => (
                    <FileCard
                      key={file.id}
                      file={file}
                      onDownload={handleDownload}
                      onCopyLink={handleCopyLink}
                      copied={copiedId === file.id}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          // List View
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left py-3 px-4 text-sm font-medium text-gray-700 dark:text-gray-300">
                    Name
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-gray-700 dark:text-gray-300">
                    Type
                  </th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-gray-700 dark:text-gray-300">
                    Size
                  </th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-gray-700 dark:text-gray-300">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {files.map((file) => {
                  const Icon = getFileIcon(file.type)
                  return (
                    <tr key={file.id} className="border-b border-gray-100 dark:border-gray-700">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-3">
                          <Icon className="h-5 w-5 text-gray-400" />
                          <span className="text-sm text-gray-900 dark:text-white">
                            {file.name}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-sm text-gray-600 dark:text-gray-400 capitalize">
                          {file.type}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-sm text-gray-600 dark:text-gray-400">
                          {file.size}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center justify-end gap-2">
                          {file.type === 'image' && (
                            <button
                              onClick={() => {
                                const index = imageFiles.findIndex(f => f.id === file.id)
                                openLightbox(index)
                              }}
                              className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                              title="View"
                            >
                              <Eye className="h-4 w-4 text-gray-500" />
                            </button>
                          )}
                          <button
                            onClick={() => handleDownload(file)}
                            className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                            title="Download"
                          >
                            <Download className="h-4 w-4 text-gray-500" />
                          </button>
                          <button
                            onClick={() => handleCopyLink(file)}
                            className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                            title="Copy link"
                          >
                            {copiedId === file.id ? (
                              <CheckCircle className="h-4 w-4 text-green-500" />
                            ) : (
                              <Copy className="h-4 w-4 text-gray-500" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Metadata */}
      {Object.keys(metadata).length > 0 && (
        <div className="p-6 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Metadata
          </h3>
          <div className="grid md:grid-cols-2 gap-4">
            {Object.entries(metadata).map(([key, value]) => (
              <div key={key} className="flex justify-between">
                <span className="text-sm text-gray-500 dark:text-gray-400 capitalize">
                  {key.replace(/_/g, ' ')}:
                </span>
                <span className="text-sm text-gray-900 dark:text-white font-medium">
                  {typeof value === 'object' ? JSON.stringify(value) : value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lightbox */}
      {showLightbox && imageFiles.length > 0 && (
        <div className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center">
          <button
            onClick={() => setShowLightbox(false)}
            className="absolute top-4 right-4 p-2 text-white hover:bg-white/10 rounded-lg"
          >
            <X className="h-6 w-6" />
          </button>
          
          {currentImageIndex > 0 && (
            <button
              onClick={() => setCurrentImageIndex(currentImageIndex - 1)}
              className="absolute left-4 p-2 text-white hover:bg-white/10 rounded-lg"
            >
              <ChevronLeft className="h-8 w-8" />
            </button>
          )}
          
          {currentImageIndex < imageFiles.length - 1 && (
            <button
              onClick={() => setCurrentImageIndex(currentImageIndex + 1)}
              className="absolute right-4 p-2 text-white hover:bg-white/10 rounded-lg"
            >
              <ChevronRight className="h-8 w-8" />
            </button>
          )}
          
          <div className="max-w-6xl max-h-[90vh] p-4">
            <img
              src={imageFiles[currentImageIndex].url}
              alt={imageFiles[currentImageIndex].name}
              className="max-w-full max-h-full object-contain"
            />
            <p className="text-white text-center mt-4">
              {imageFiles[currentImageIndex].name}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// File Card Component
function FileCard({ 
  file, 
  onDownload, 
  onCopyLink, 
  copied 
}: { 
  file: ResultFile
  onDownload: (file: ResultFile) => void
  onCopyLink: (file: ResultFile) => void
  copied: boolean
}) {
  const Icon = file.type === 'data' ? Table : 
              file.type === 'report' ? FileText : 
              file.type === 'code' ? Code : FileText
  
  return (
    <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
      <div className="flex items-center gap-3">
        <Icon className="h-8 w-8 text-gray-400" />
        <div>
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            {file.name}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {file.size}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onDownload(file)}
          className="p-2 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Download"
        >
          <Download className="h-4 w-4 text-gray-500 dark:text-gray-400" />
        </button>
        <button
          onClick={() => onCopyLink(file)}
          className="p-2 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          title="Copy link"
        >
          {copied ? (
            <CheckCircle className="h-4 w-4 text-green-500" />
          ) : (
            <Copy className="h-4 w-4 text-gray-500 dark:text-gray-400" />
          )}
        </button>
      </div>
    </div>
  )
}