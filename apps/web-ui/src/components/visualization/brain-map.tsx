'use client'

import { useState, useRef } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { BrainMapData } from '@/types/visualization'
import { 
  Brain, 
  Maximize2, 
  Download, 
  RotateCcw, 
  ZoomIn, 
  ZoomOut,
  Layers,
  Settings,
  Play,
  Pause
} from 'lucide-react'

interface BrainMapProps {
  brainMap: BrainMapData
  className?: string
  onPeakClick?: (peak: { x: number; y: number; z: number; value: number; region?: string }) => void
}

export function BrainMapVisualization({ brainMap, className, onPeakClick }: BrainMapProps) {
  const [viewMode, setViewMode] = useState<'3d' | 'slices' | 'glass'>('3d')
  const [currentSlice, setCurrentSlice] = useState(0)
  const [threshold, setThreshold] = useState(brainMap.threshold || 0.001)
  const [isRotating, setIsRotating] = useState(false)
  const [zoom, setZoom] = useState(1)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = brainMap.imageUrl
    link.download = `${brainMap.name.replace(/\s+/g, '_')}.png`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleNiftiDownload = () => {
    if (!brainMap.niftiUrl) return
    
    const link = document.createElement('a')
    link.href = brainMap.niftiUrl
    link.download = `${brainMap.name.replace(/\s+/g, '_')}.nii.gz`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const renderSliceView = () => {
    if (!brainMap.slices) return null

    const sliceTypes = ['axial', 'sagittal', 'coronal'] as const
    
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {sliceTypes.map((type) => (
              <Button
                key={type}
                variant="outline"
                size="sm"
                className="capitalize"
              >
                {type}
              </Button>
            ))}
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Slice:</span>
            <input
              type="range"
              min="0"
              max="29"
              value={currentSlice}
              onChange={(e) => setCurrentSlice(parseInt(e.target.value))}
              className="w-24"
            />
            <span className="text-sm font-mono">{currentSlice + 1}/30</span>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          {sliceTypes.map((type) => (
            <div key={type} className="space-y-2">
              <div className="text-sm font-medium capitalize text-center">{type}</div>
              <div className="aspect-square bg-muted rounded-lg flex items-center justify-center">
                <img
                  src={brainMap.imageUrl}
                  alt={`${type} slice`}
                  className="max-w-full max-h-full object-contain"
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const render3DView = () => {
    return (
      <div className="relative">
        <div 
          className="aspect-square bg-gradient-to-br from-gray-900 to-gray-700 rounded-lg flex items-center justify-center overflow-hidden"
          style={{ transform: `scale(${zoom})` }}
        >
          <img
            src={brainMap.imageUrl}
            alt={brainMap.name}
            className={`max-w-full max-h-full object-contain transition-transform duration-300 ${
              isRotating ? 'animate-spin' : ''
            }`}
          />
        </div>

        {/* 3D Controls */}
        <div className="absolute top-4 right-4 flex flex-col gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={() => setIsRotating(!isRotating)}
            className="bg-background/80 backdrop-blur-sm"
          >
            {isRotating ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          
          <Button
            variant="outline"
            size="icon"
            onClick={() => setZoom(Math.min(2, zoom + 0.2))}
            className="bg-background/80 backdrop-blur-sm"
          >
            <ZoomIn className="h-4 w-4" />
          </Button>
          
          <Button
            variant="outline"
            size="icon"
            onClick={() => setZoom(Math.max(0.5, zoom - 0.2))}
            className="bg-background/80 backdrop-blur-sm"
          >
            <ZoomOut className="h-4 w-4" />
          </Button>
        </div>

        {/* Coordinates display */}
        {brainMap.coordinates && (
          <div className="absolute bottom-4 left-4 bg-background/80 backdrop-blur-sm rounded-lg p-2 text-sm font-mono">
            <div>X: {brainMap.coordinates.x}</div>
            <div>Y: {brainMap.coordinates.y}</div>
            <div>Z: {brainMap.coordinates.z}</div>
          </div>
        )}
      </div>
    )
  }

  const renderGlassView = () => {
    return (
      <div className="space-y-4">
        <div className="text-center text-sm text-muted-foreground mb-4">
          Glass brain projection showing all significant activations
        </div>
        
        <div className="aspect-[4/3] bg-black rounded-lg flex items-center justify-center">
          <img
            src={brainMap.imageUrl}
            alt="Glass brain"
            className="max-w-full max-h-full object-contain opacity-90"
            style={{ filter: 'invert(1) hue-rotate(180deg)' }}
          />
        </div>
      </div>
    )
  }

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5" />
              {brainMap.name}
            </CardTitle>
            <CardDescription className="capitalize">
              {brainMap.type} map • Threshold: {threshold}
            </CardDescription>
          </div>
          
          <div className="flex items-center gap-2">
            <Button
              variant={viewMode === '3d' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setViewMode('3d')}
            >
              3D
            </Button>
            <Button
              variant={viewMode === 'slices' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setViewMode('slices')}
            >
              <Layers className="h-4 w-4" />
            </Button>
            <Button
              variant={viewMode === 'glass' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setViewMode('glass')}
            >
              Glass
            </Button>
            
            <Button variant="outline" size="sm">
              <Settings className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-6">
          {/* Threshold control */}
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium">Threshold:</span>
            <input
              type="range"
              min="0.001"
              max="0.05"
              step="0.001"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="flex-1"
            />
            <span className="text-sm font-mono w-16">{threshold.toFixed(3)}</span>
          </div>

          {/* Main visualization */}
          <div className="min-h-[400px]">
            {viewMode === '3d' && render3DView()}
            {viewMode === 'slices' && renderSliceView()}
            {viewMode === 'glass' && renderGlassView()}
          </div>

          {/* Peak activations table */}
          {brainMap.peaks && brainMap.peaks.length > 0 && (
            <div className="space-y-2">
              <h4 className="font-medium">Peak Activations</h4>
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="text-left p-2">Region</th>
                      <th className="text-left p-2">Coordinates</th>
                      <th className="text-left p-2">Z-score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {brainMap.peaks.slice(0, 5).map((peak, index) => (
                      <tr 
                        key={index}
                        className="border-t hover:bg-muted/50 cursor-pointer"
                        onClick={() => onPeakClick?.(peak)}
                      >
                        <td className="p-2">{peak.region || 'Unknown'}</td>
                        <td className="p-2 font-mono">
                          {peak.x}, {peak.y}, {peak.z}
                        </td>
                        <td className="p-2 font-mono">{peak.value.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Download options */}
          <div className="flex items-center gap-2 pt-4 border-t">
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="h-4 w-4 mr-2" />
              PNG Image
            </Button>
            {brainMap.niftiUrl && (
              <Button variant="outline" size="sm" onClick={handleNiftiDownload}>
                <Download className="h-4 w-4 mr-2" />
                NIfTI File
              </Button>
            )}
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4 mr-2" />
              SVG Vector
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}