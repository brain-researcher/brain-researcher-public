'use client'

import React, { useState, useRef } from 'react'
import { RotateCw, ZoomIn, ZoomOut, Download, Maximize2, Minimize2, Move3D } from 'lucide-react'

interface BrainMapViewerProps {
  item: {
    id: string
    name: string
    fullUrl: string
    metadata: {
      dimensions?: number[] | { width: number; height: number; depth?: number }
      voxelSize?: number[]
      format?: string
      [key: string]: any
    }
  }
  onDownload?: () => void
  className?: string
}

export function BrainMapViewer({ item, onDownload, className = '' }: BrainMapViewerProps) {
  const [zoomLevel, setZoomLevel] = useState(100)
  const [rotation, setRotation] = useState(0)
  const [currentSlice, setCurrentSlice] = useState(0)
  const [viewMode, setViewMode] = useState<'axial' | 'coronal' | 'sagittal'>('axial')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const dims = item.metadata.dimensions
  const maxSlices = Array.isArray(dims)
    ? dims[2] || dims[0] || 100
    : (typeof dims === 'object' && dims ? dims.depth || dims.height || 100 : 100)
  const dimsLabel = Array.isArray(dims)
    ? dims.join('×')
    : dims
      ? `${dims.width}×${dims.height}${dims.depth ? `×${dims.depth}` : ''}`
      : undefined

  const handleZoomIn = () => {
    setZoomLevel(Math.min(500, zoomLevel + 25))
  }

  const handleZoomOut = () => {
    setZoomLevel(Math.max(25, zoomLevel - 25))
  }

  const handleRotate = () => {
    setRotation((rotation + 90) % 360)
  }

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen)
  }

  return (
    <div 
      ref={containerRef}
      className={`bg-white rounded-lg shadow-lg border border-gray-200 ${
        isFullscreen ? 'fixed inset-0 z-50' : ''
      } ${className}`}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-gray-900">{item.name}</h3>
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                {item.metadata.format || 'NIfTI'}
              </span>
              {dimsLabel && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                  {dimsLabel}
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
            
            <button
              onClick={handleRotate}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title="Rotate"
            >
              <RotateCw className="h-4 w-4" />
            </button>
            
            <div className="w-px h-6 bg-gray-300 mx-1" />
            
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

      {/* View Mode Selector */}
      <div className="px-4 py-2 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">View:</span>
            <div className="flex items-center bg-white rounded-lg shadow-sm">
              {(['axial', 'coronal', 'sagittal'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
                    viewMode === mode
                      ? 'bg-blue-500 text-white'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Slice Navigator */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600">Slice:</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCurrentSlice(Math.max(0, currentSlice - 1))}
                disabled={currentSlice === 0}
                className="px-2 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                ←
              </button>
              <span className="min-w-[60px] text-center text-sm">
                {currentSlice + 1} / {maxSlices}
              </span>
              <button
                onClick={() => setCurrentSlice(Math.min(maxSlices - 1, currentSlice + 1))}
                disabled={currentSlice === maxSlices - 1}
                className="px-2 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                →
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Viewer */}
      <div className={`relative bg-black ${isFullscreen ? 'h-screen' : 'h-96'} flex items-center justify-center`}>
        {/* Placeholder for actual brain map rendering */}
        <div className="relative">
          <div
            className="bg-gray-800 rounded border-2 border-gray-600 flex items-center justify-center text-white transition-transform duration-300"
            style={{
              width: '400px',
              height: '400px',
              transform: `scale(${zoomLevel / 100}) rotate(${rotation}deg)`
            }}
          >
            <div className="text-center">
              <Move3D className="h-12 w-12 mx-auto mb-2 text-gray-400" />
              <p className="text-gray-400 text-sm">
                Brain Map Preview
              </p>
              <p className="text-gray-500 text-xs mt-1">
                {viewMode} view - Slice {currentSlice + 1}
              </p>
              <p className="text-gray-500 text-xs mt-1">
                NiiVue integration would render here
              </p>
            </div>
          </div>

          {/* Crosshair */}
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-green-500 opacity-50"></div>
            <div className="absolute top-1/2 left-0 right-0 h-px bg-green-500 opacity-50"></div>
          </div>
        </div>

        {/* Slice Slider */}
        <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2">
          <input
            type="range"
            min="0"
            max={maxSlices - 1}
            value={currentSlice}
            onChange={(e) => setCurrentSlice(parseInt(e.target.value))}
            className="w-64 h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer slider"
          />
        </div>
      </div>

      {/* Metadata Panel */}
      <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          {dimsLabel && (
            <div>
              <dt className="text-gray-500">Dimensions</dt>
              <dd className="font-medium">{dimsLabel}</dd>
            </div>
          )}
          {item.metadata.voxelSize && (
            <div>
              <dt className="text-gray-500">Voxel Size</dt>
              <dd className="font-medium">{item.metadata.voxelSize.join(' × ')} mm</dd>
            </div>
          )}
          <div>
            <dt className="text-gray-500">Format</dt>
            <dd className="font-medium">{item.metadata.format || 'NIfTI'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Current View</dt>
            <dd className="font-medium">{viewMode}</dd>
          </div>
        </div>
      </div>

      <style jsx>{`
        .slider::-webkit-slider-thumb {
          appearance: none;
          height: 16px;
          width: 16px;
          border-radius: 50%;
          background: #10b981;
          cursor: pointer;
          border: 2px solid #ffffff;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .slider::-moz-range-thumb {
          height: 16px;
          width: 16px;
          border-radius: 50%;
          background: #10b981;
          cursor: pointer;
          border: 2px solid #ffffff;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
      `}</style>
    </div>
  )
}
