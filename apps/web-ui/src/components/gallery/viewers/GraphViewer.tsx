'use client'

import React, { useState } from 'react'
import { Download, Maximize2, Minimize2, BarChart3, LineChart, PieChart, Zap } from 'lucide-react'
import Image from 'next/image'

interface GraphViewerProps {
  item: {
    id: string
    name: string
    fullUrl: string
    data?: any
    metadata: {
      graphType?: 'bar' | 'line' | 'scatter' | 'heatmap' | 'violin' | 'box'
      dimensions?: { width: number; height: number }
      format?: string
      interactive?: boolean
      [key: string]: any
    }
  }
  onDownload?: () => void
  className?: string
}

export function GraphViewer({ item, onDownload, className = '' }: GraphViewerProps) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showRawData, setShowRawData] = useState(false)

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen)
  }

  const getGraphIcon = () => {
    switch (item.metadata.graphType) {
      case 'bar': return BarChart3
      case 'line': return LineChart
      case 'scatter': return Zap
      default: return BarChart3
    }
  }

  const GraphIcon = getGraphIcon()

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
            <GraphIcon className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">{item.name}</h3>
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full">
                {item.metadata.graphType || 'Graph'}
              </span>
              {item.metadata.interactive && (
                <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                  Interactive
                </span>
              )}
              {item.metadata.dimensions && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                  {item.metadata.dimensions.width}×{item.metadata.dimensions.height}
                </span>
              )}
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            {item.data && (
              <button
                onClick={() => setShowRawData(!showRawData)}
                className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                title={showRawData ? "Show Graph" : "Show Raw Data"}
              >
                {showRawData ? <BarChart3 className="h-4 w-4" /> : <PieChart className="h-4 w-4" />}
              </button>
            )}
            
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

      {/* Main Content */}
      <div className={`${isFullscreen ? 'h-screen' : 'h-96'} flex items-center justify-center bg-gray-50`}>
        {!showRawData ? (
          /* Graph Display */
          <div className="relative w-full h-full p-4">
            {item.fullUrl ? (
              <div className="w-full h-full flex items-center justify-center">
                <Image
                  src={item.fullUrl}
                  alt={item.name}
                  fill
                  className="object-contain"
                  sizes={isFullscreen ? "100vw" : "(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"}
                />
              </div>
            ) : (
              /* Placeholder for interactive graph */
              <div className="w-full h-full flex items-center justify-center border-2 border-dashed border-gray-300 rounded-lg">
                <div className="text-center">
                  <GraphIcon className="h-16 w-16 mx-auto mb-4 text-gray-400" />
                  <h4 className="text-lg font-medium text-gray-700 mb-2">
                    Interactive {item.metadata.graphType || 'Graph'}
                  </h4>
                  <p className="text-sm text-gray-500 mb-4">
                    Interactive graph component would render here
                  </p>
                  <div className="space-y-2 text-xs text-gray-400">
                    <p>Plotly.js or D3.js integration</p>
                    <p>Zoom, pan, and hover interactions</p>
                    <p>Data export and customization</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Raw Data Display */
          <div className="w-full h-full p-4 overflow-auto">
            <div className="bg-gray-900 text-gray-100 rounded-lg p-4 h-full overflow-auto">
              <div className="mb-4 flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300">Raw Data</h4>
                <button
                  onClick={() => {
                    if (item.data) {
                      navigator.clipboard.writeText(JSON.stringify(item.data, null, 2))
                    }
                  }}
                  className="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs hover:bg-gray-600 transition-colors"
                >
                  Copy JSON
                </button>
              </div>
              <pre className="text-sm font-mono whitespace-pre-wrap">
                <code>
                  {item.data ? JSON.stringify(item.data, null, 2) : 'No raw data available'}
                </code>
              </pre>
            </div>
          </div>
        )}
      </div>

      {/* Graph Controls (if interactive) */}
      {item.metadata.interactive && !showRawData && (
        <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-600">Controls:</span>
              <div className="flex items-center gap-2">
                <button className="px-3 py-1.5 bg-blue-100 text-blue-800 rounded text-sm hover:bg-blue-200 transition-colors">
                  Reset Zoom
                </button>
                <button className="px-3 py-1.5 bg-green-100 text-green-800 rounded text-sm hover:bg-green-200 transition-colors">
                  Auto Scale
                </button>
                <button className="px-3 py-1.5 bg-purple-100 text-purple-800 rounded text-sm hover:bg-purple-200 transition-colors">
                  Toggle Grid
                </button>
              </div>
            </div>
            <div className="text-sm text-gray-500">
              Mouse: Pan • Scroll: Zoom • Double-click: Reset
            </div>
          </div>
        </div>
      )}

      {/* Metadata Panel */}
      <div className="px-4 py-3 border-t border-gray-200 bg-white">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Type</dt>
            <dd className="font-medium">{item.metadata.graphType || 'Unknown'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Format</dt>
            <dd className="font-medium">{item.metadata.format || 'PNG'}</dd>
          </div>
          {item.metadata.dimensions && (
            <div>
              <dt className="text-gray-500">Dimensions</dt>
              <dd className="font-medium">
                {item.metadata.dimensions.width} × {item.metadata.dimensions.height}px
              </dd>
            </div>
          )}
          <div>
            <dt className="text-gray-500">Interactive</dt>
            <dd className="font-medium">{item.metadata.interactive ? 'Yes' : 'No'}</dd>
          </div>
        </div>

        {/* Additional metadata */}
        {Object.entries(item.metadata)
          .filter(([key]) => !['graphType', 'format', 'dimensions', 'interactive'].includes(key))
          .length > 0 && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <h5 className="text-sm font-medium text-gray-700 mb-2">Additional Properties</h5>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(item.metadata)
                .filter(([key]) => !['graphType', 'format', 'dimensions', 'interactive'].includes(key))
                .map(([key, value]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-gray-500">{key}:</span>
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