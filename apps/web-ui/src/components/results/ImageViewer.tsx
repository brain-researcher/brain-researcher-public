'use client'

import React, { useState, useRef, useCallback, useEffect } from 'react'
import { 
  ZoomIn, ZoomOut, RotateCw, RotateCcw, Maximize2, 
  ChevronLeft, ChevronRight, Play, Pause,
  Download, Share2, Settings, Grid3x3
} from 'lucide-react'

interface ImageViewerProps {
  src: string
  alt: string
  type?: 'standard' | 'nifti' | 'dicom'
  slices?: string[] // For NIfTI/DICOM multi-slice images
  onDownload?: () => void
  onShare?: () => void
  className?: string
}

interface ViewState {
  zoom: number
  pan: { x: number; y: number }
  rotation: number
  currentSlice: number
  isPlaying: boolean
  playSpeed: number
}

export function ImageViewer({
  src,
  alt,
  type = 'standard',
  slices = [],
  onDownload,
  onShare,
  className = ''
}: ImageViewerProps) {
  const [viewState, setViewState] = useState<ViewState>({
    zoom: 1,
    pan: { x: 0, y: 0 },
    rotation: 0,
    currentSlice: 0,
    isPlaying: false,
    playSpeed: 500 // ms per frame
  })
  
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [showControls, setShowControls] = useState(true)
  const [showGrid, setShowGrid] = useState(false)
  
  const imageRef = useRef<HTMLImageElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null)
  
  const isMultiSlice = type === 'nifti' || type === 'dicom'
  const totalSlices = isMultiSlice ? slices.length : 1
  const currentSrc = isMultiSlice && slices.length > 0 
    ? slices[viewState.currentSlice] 
    : src

  // Auto-play functionality for multi-slice images
  useEffect(() => {
    if (viewState.isPlaying && isMultiSlice && totalSlices > 1) {
      playIntervalRef.current = setInterval(() => {
        setViewState(prev => ({
          ...prev,
          currentSlice: (prev.currentSlice + 1) % totalSlices
        }))
      }, viewState.playSpeed)
    } else {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current)
        playIntervalRef.current = null
      }
    }
    
    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current)
      }
    }
  }, [viewState.isPlaying, viewState.playSpeed, isMultiSlice, totalSlices])

  const handleZoom = useCallback((delta: number) => {
    setViewState(prev => ({
      ...prev,
      zoom: Math.max(0.1, Math.min(10, prev.zoom + delta))
    }))
  }, [])

  const handleRotate = useCallback((degrees: number) => {
    setViewState(prev => ({
      ...prev,
      rotation: (prev.rotation + degrees) % 360
    }))
  }, [])

  const handleSliceChange = useCallback((direction: number) => {
    if (!isMultiSlice) return
    setViewState(prev => ({
      ...prev,
      currentSlice: Math.max(0, Math.min(totalSlices - 1, prev.currentSlice + direction))
    }))
  }, [isMultiSlice, totalSlices])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0) { // Left click only
      setIsDragging(true)
      setDragStart({ x: e.clientX - viewState.pan.x, y: e.clientY - viewState.pan.y })
      e.preventDefault()
    }
  }, [viewState.pan])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isDragging) {
      setViewState(prev => ({
        ...prev,
        pan: {
          x: e.clientX - dragStart.x,
          y: e.clientY - dragStart.y
        }
      }))
    }
  }, [isDragging, dragStart])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    handleZoom(delta)
  }, [handleZoom])

  const resetView = useCallback(() => {
    setViewState(prev => ({
      ...prev,
      zoom: 1,
      pan: { x: 0, y: 0 },
      rotation: 0
    }))
  }, [])

  const togglePlay = useCallback(() => {
    if (isMultiSlice && totalSlices > 1) {
      setViewState(prev => ({ ...prev, isPlaying: !prev.isPlaying }))
    }
  }, [isMultiSlice, totalSlices])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!showControls) return
    
    switch (e.key) {
      case '+':
      case '=':
        handleZoom(0.1)
        break
      case '-':
        handleZoom(-0.1)
        break
      case 'r':
        handleRotate(90)
        break
      case 'R':
        handleRotate(-90)
        break
      case 'ArrowLeft':
        handleSliceChange(-1)
        break
      case 'ArrowRight':
        handleSliceChange(1)
        break
      case ' ':
        e.preventDefault()
        togglePlay()
        break
      case 'Escape':
        resetView()
        break
    }
  }, [handleZoom, handleRotate, handleSliceChange, togglePlay, resetView, showControls])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const imageStyle = {
    transform: `translate(${viewState.pan.x}px, ${viewState.pan.y}px) scale(${viewState.zoom}) rotate(${viewState.rotation}deg)`,
    cursor: isDragging ? 'grabbing' : 'grab',
    transition: isDragging ? 'none' : 'transform 0.1s ease-out'
  }

  return (
    <div 
      ref={containerRef}
      className={`relative bg-gray-900 rounded-lg overflow-hidden select-none ${className}`}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
    >
      {/* Image Container */}
      <div className="relative w-full h-full min-h-[400px] flex items-center justify-center">
        {showGrid && (
          <div className="absolute inset-0 opacity-30 pointer-events-none">
            <div className="w-full h-full" style={{
              backgroundImage: 'linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)',
              backgroundSize: '20px 20px'
            }} />
          </div>
        )}
        
        <img
          ref={imageRef}
          src={currentSrc}
          alt={alt}
          className="max-w-none"
          style={imageStyle}
          onMouseDown={handleMouseDown}
          onDragStart={(e) => e.preventDefault()}
          onError={(e) => {
            console.error('Image failed to load:', currentSrc)
          }}
        />
      </div>

      {/* Controls Overlay */}
      {showControls && (
        <div className="absolute inset-0 pointer-events-none">
          {/* Top Controls */}
          <div className="absolute top-4 left-4 right-4 flex justify-between pointer-events-auto">
            <div className="flex gap-2">
              <div className="bg-black/50 backdrop-blur-sm rounded-lg px-3 py-2 text-white text-sm">
                Zoom: {Math.round(viewState.zoom * 100)}%
              </div>
              {isMultiSlice && (
                <div className="bg-black/50 backdrop-blur-sm rounded-lg px-3 py-2 text-white text-sm">
                  Slice: {viewState.currentSlice + 1} / {totalSlices}
                </div>
              )}
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={() => setShowGrid(!showGrid)}
                className={`p-2 rounded-lg backdrop-blur-sm transition-colors ${
                  showGrid ? 'bg-blue-500/50 text-white' : 'bg-black/50 text-white hover:bg-black/70'
                }`}
                title="Toggle grid"
              >
                <Grid3x3 className="h-4 w-4" />
              </button>
              
              {onShare && (
                <button
                  onClick={onShare}
                  className="p-2 bg-black/50 hover:bg-black/70 backdrop-blur-sm rounded-lg text-white transition-colors"
                  title="Share image"
                >
                  <Share2 className="h-4 w-4" />
                </button>
              )}
              
              {onDownload && (
                <button
                  onClick={onDownload}
                  className="p-2 bg-black/50 hover:bg-black/70 backdrop-blur-sm rounded-lg text-white transition-colors"
                  title="Download image"
                >
                  <Download className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          {/* Multi-slice Navigation */}
          {isMultiSlice && totalSlices > 1 && (
            <div className="absolute bottom-20 left-4 right-4 pointer-events-auto">
              <div className="bg-black/50 backdrop-blur-sm rounded-lg p-4">
                <div className="flex items-center gap-4 mb-3">
                  <button
                    onClick={() => handleSliceChange(-1)}
                    disabled={viewState.currentSlice === 0}
                    className="p-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                  >
                    <ChevronLeft className="h-4 w-4 text-white" />
                  </button>
                  
                  <button
                    onClick={togglePlay}
                    className="p-2 bg-blue-500/50 hover:bg-blue-500/70 rounded transition-colors"
                  >
                    {viewState.isPlaying ? (
                      <Pause className="h-4 w-4 text-white" />
                    ) : (
                      <Play className="h-4 w-4 text-white" />
                    )}
                  </button>
                  
                  <button
                    onClick={() => handleSliceChange(1)}
                    disabled={viewState.currentSlice === totalSlices - 1}
                    className="p-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                  >
                    <ChevronRight className="h-4 w-4 text-white" />
                  </button>
                </div>
                
                {/* Slice Slider */}
                <input
                  type="range"
                  min={0}
                  max={totalSlices - 1}
                  value={viewState.currentSlice}
                  onChange={(e) => setViewState(prev => ({ ...prev, currentSlice: parseInt(e.target.value) }))}
                  className="w-full h-2 bg-white/20 rounded-lg appearance-none cursor-pointer"
                  style={{
                    background: `linear-gradient(to right, #3b82f6 0%, #3b82f6 ${(viewState.currentSlice / (totalSlices - 1)) * 100}%, rgba(255,255,255,0.2) ${(viewState.currentSlice / (totalSlices - 1)) * 100}%, rgba(255,255,255,0.2) 100%)`
                  }}
                />
              </div>
            </div>
          )}

          {/* Bottom Controls */}
          <div className="absolute bottom-4 left-4 right-4 flex justify-center pointer-events-auto">
            <div className="bg-black/50 backdrop-blur-sm rounded-lg p-2 flex gap-2">
              <button
                onClick={() => handleZoom(-0.2)}
                className="p-2 hover:bg-white/20 rounded transition-colors"
                title="Zoom out"
              >
                <ZoomOut className="h-4 w-4 text-white" />
              </button>
              
              <button
                onClick={() => handleZoom(0.2)}
                className="p-2 hover:bg-white/20 rounded transition-colors"
                title="Zoom in"
              >
                <ZoomIn className="h-4 w-4 text-white" />
              </button>
              
              <button
                onClick={() => handleRotate(-90)}
                className="p-2 hover:bg-white/20 rounded transition-colors"
                title="Rotate left"
              >
                <RotateCcw className="h-4 w-4 text-white" />
              </button>
              
              <button
                onClick={() => handleRotate(90)}
                className="p-2 hover:bg-white/20 rounded transition-colors"
                title="Rotate right"
              >
                <RotateCw className="h-4 w-4 text-white" />
              </button>
              
              <button
                onClick={resetView}
                className="p-2 hover:bg-white/20 rounded transition-colors"
                title="Reset view"
              >
                <Maximize2 className="h-4 w-4 text-white" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Controls Toggle */}
      <button
        onClick={() => setShowControls(!showControls)}
        className="absolute top-4 right-4 p-2 bg-black/30 hover:bg-black/50 backdrop-blur-sm rounded-lg text-white transition-colors z-10"
        title={showControls ? 'Hide controls' : 'Show controls'}
      >
        <Settings className="h-4 w-4" />
      </button>
      
      {/* Keyboard shortcuts help */}
      {showControls && (
        <div className="absolute bottom-4 left-4 text-xs text-white/70 bg-black/30 backdrop-blur-sm rounded px-2 py-1">
          +/- zoom • R rotate • ←/→ slice • Space play • Esc reset
        </div>
      )}
    </div>
  )
}