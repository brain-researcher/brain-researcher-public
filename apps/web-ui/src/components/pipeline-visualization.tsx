'use client'

import React, { useState, useEffect, useRef } from 'react'
import { Play, Pause, RotateCcw, CheckCircle, XCircle, Clock, AlertCircle, ChevronRight } from 'lucide-react'

interface PipelineStep {
  id: string
  name: string
  type: 'input' | 'process' | 'analysis' | 'output'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  progress?: number
  duration?: number
  inputs?: string[]
  outputs?: string[]
  parameters?: Record<string, any>
  error?: string
  startTime?: Date
  endTime?: Date
}

interface PipelineConnection {
  from: string
  to: string
  label?: string
  dataType?: string
}

interface PipelineData {
  id: string
  name: string
  description?: string
  steps: PipelineStep[]
  connections: PipelineConnection[]
  status: 'idle' | 'running' | 'completed' | 'failed'
  progress: number
  totalDuration?: number
}

interface PipelineVisualizationProps {
  pipeline: PipelineData
  onStepClick?: (step: PipelineStep) => void
  onRetry?: (stepId: string) => void
  onPause?: () => void
  onResume?: () => void
  onCancel?: () => void
  showMinimap?: boolean
  interactive?: boolean
}

const stepColors = {
  input: '#10B981',      // green
  process: '#3B82F6',    // blue
  analysis: '#8B5CF6',   // purple
  output: '#F59E0B'      // yellow
}

const statusIcons = {
  pending: Clock,
  running: Clock,
  completed: CheckCircle,
  failed: XCircle,
  skipped: AlertCircle
}

export function PipelineVisualization({
  pipeline,
  onStepClick,
  onRetry,
  onPause,
  onResume,
  onCancel,
  showMinimap = true,
  interactive = true
}: PipelineVisualizationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [selectedStep, setSelectedStep] = useState<PipelineStep | null>(null)
  const [hoveredStep, setHoveredStep] = useState<string | null>(null)
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, width: 1200, height: 600 })

  // Calculate step positions
  const calculateStepPositions = () => {
    const positions: Record<string, { x: number; y: number }> = {}
    const stepsByType: Record<string, PipelineStep[]> = {
      input: [],
      process: [],
      analysis: [],
      output: []
    }

    // Group steps by type
    pipeline.steps.forEach(step => {
      stepsByType[step.type].push(step)
    })

    // Position steps in columns
    const columnWidth = 250
    const columnOffsets = {
      input: 50,
      process: 350,
      analysis: 650,
      output: 950
    }

    Object.entries(stepsByType).forEach(([type, steps]) => {
      steps.forEach((step, index) => {
        const x = columnOffsets[type as keyof typeof columnOffsets]
        const y = 100 + index * 120
        positions[step.id] = { x, y }
      })
    })

    return positions
  }

  const positions = calculateStepPositions()

  // Draw connections between steps
  const drawConnections = () => {
    if (!canvasRef.current) return
    
    const ctx = canvasRef.current.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height)
    
    pipeline.connections.forEach(conn => {
      const from = positions[conn.from]
      const to = positions[conn.to]
      
      if (!from || !to) return

      // Draw curved path
      ctx.beginPath()
      ctx.moveTo(from.x + 100, from.y + 30)
      
      const controlX = (from.x + to.x) / 2
      ctx.bezierCurveTo(
        controlX, from.y + 30,
        controlX, to.y + 30,
        to.x, to.y + 30
      )
      
      ctx.strokeStyle = '#CBD5E1'
      ctx.lineWidth = 2
      ctx.stroke()

      // Draw arrow
      const angle = Math.atan2(to.y - from.y, to.x - from.x)
      ctx.beginPath()
      ctx.moveTo(to.x, to.y + 30)
      ctx.lineTo(
        to.x - 10 * Math.cos(angle - Math.PI / 6),
        to.y + 30 - 10 * Math.sin(angle - Math.PI / 6)
      )
      ctx.lineTo(
        to.x - 10 * Math.cos(angle + Math.PI / 6),
        to.y + 30 - 10 * Math.sin(angle + Math.PI / 6)
      )
      ctx.closePath()
      ctx.fillStyle = '#CBD5E1'
      ctx.fill()
    })
  }

  useEffect(() => {
    drawConnections()
  }, [pipeline])

  const formatDuration = (ms?: number) => {
    if (!ms) return '--'
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }

  const StepCard = ({ step }: { step: PipelineStep }) => {
    const pos = positions[step.id]
    const StatusIcon = statusIcons[step.status]
    
    return (
      <div
        className={`absolute bg-white rounded-lg shadow-lg border-2 transition-all cursor-pointer
          ${selectedStep?.id === step.id ? 'border-blue-500 ring-2 ring-blue-200' : 'border-gray-200'}
          ${hoveredStep === step.id ? 'transform scale-105 shadow-xl' : ''}
          ${step.status === 'failed' ? 'border-red-300' : ''}
        `}
        style={{
          left: pos.x,
          top: pos.y,
          width: 200,
          minHeight: 80
        }}
        onClick={() => {
          setSelectedStep(step)
          onStepClick?.(step)
        }}
        onMouseEnter={() => setHoveredStep(step.id)}
        onMouseLeave={() => setHoveredStep(null)}
      >
        {/* Header */}
        <div
          className="px-3 py-2 rounded-t-md text-white font-medium text-sm"
          style={{ backgroundColor: stepColors[step.type] }}
        >
          {step.name}
        </div>

        {/* Body */}
        <div className="p-3">
          {/* Status */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1">
              <StatusIcon className={`h-4 w-4 ${
                step.status === 'completed' ? 'text-green-500' :
                step.status === 'failed' ? 'text-red-500' :
                step.status === 'running' ? 'text-blue-500 animate-spin' :
                'text-gray-400'
              }`} />
              <span className="text-xs text-gray-600 capitalize">{step.status}</span>
            </div>
            <span className="text-xs text-gray-500">{formatDuration(step.duration)}</span>
          </div>

          {/* Progress bar */}
          {step.status === 'running' && step.progress !== undefined && (
            <div className="w-full bg-gray-200 rounded-full h-1.5 mb-2">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all"
                style={{ width: `${step.progress}%` }}
              />
            </div>
          )}

          {/* Error message */}
          {step.error && (
            <div className="text-xs text-red-600 mt-1">
              {step.error}
            </div>
          )}

          {/* Retry button */}
          {step.status === 'failed' && onRetry && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onRetry(step.id)
              }}
              className="mt-2 text-xs bg-red-100 text-red-700 px-2 py-1 rounded hover:bg-red-200"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-lg">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{pipeline.name}</h2>
            {pipeline.description && (
              <p className="text-sm text-gray-600 mt-1">{pipeline.description}</p>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2">
            {pipeline.status === 'running' && (
              <>
                {onPause && (
                  <button
                    onClick={onPause}
                    className="px-3 py-1.5 bg-yellow-100 text-yellow-700 rounded-md hover:bg-yellow-200 flex items-center gap-1"
                  >
                    <Pause className="h-4 w-4" />
                    Pause
                  </button>
                )}
                {onCancel && (
                  <button
                    onClick={onCancel}
                    className="px-3 py-1.5 bg-red-100 text-red-700 rounded-md hover:bg-red-200"
                  >
                    Cancel
                  </button>
                )}
              </>
            )}
            
            {pipeline.status === 'idle' && onResume && (
              <button
                onClick={onResume}
                className="px-3 py-1.5 bg-green-100 text-green-700 rounded-md hover:bg-green-200 flex items-center gap-1"
              >
                <Play className="h-4 w-4" />
                Start
              </button>
            )}

            {pipeline.status === 'failed' && onRetry && (
              <button
                onClick={() => onRetry('all')}
                className="px-3 py-1.5 bg-blue-100 text-blue-700 rounded-md hover:bg-blue-200 flex items-center gap-1"
              >
                <RotateCcw className="h-4 w-4" />
                Retry All
              </button>
            )}
          </div>
        </div>

        {/* Overall progress */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm text-gray-600">Overall Progress</span>
            <span className="text-sm font-medium">{pipeline.progress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${
                pipeline.status === 'failed' ? 'bg-red-500' :
                pipeline.status === 'completed' ? 'bg-green-500' :
                'bg-blue-500'
              }`}
              style={{ width: `${pipeline.progress}%` }}
            />
          </div>
        </div>
      </div>

      {/* Pipeline Canvas */}
      <div className="relative" style={{ height: viewBox.height }}>
        <canvas
          ref={canvasRef}
          width={viewBox.width}
          height={viewBox.height}
          className="absolute inset-0"
        />
        
        {/* Step Cards */}
        {pipeline.steps.map(step => (
          <StepCard key={step.id} step={step} />
        ))}
      </div>

      {/* Step Details Panel */}
      {selectedStep && (
        <div className="p-4 border-t border-gray-200 bg-gray-50">
          <h3 className="font-semibold mb-2">Step Details: {selectedStep.name}</h3>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Type:</span>
              <span className="ml-2 font-medium capitalize">{selectedStep.type}</span>
            </div>
            <div>
              <span className="text-gray-600">Status:</span>
              <span className="ml-2 font-medium capitalize">{selectedStep.status}</span>
            </div>
            {selectedStep.duration && (
              <div>
                <span className="text-gray-600">Duration:</span>
                <span className="ml-2 font-medium">{formatDuration(selectedStep.duration)}</span>
              </div>
            )}
            {selectedStep.progress !== undefined && (
              <div>
                <span className="text-gray-600">Progress:</span>
                <span className="ml-2 font-medium">{selectedStep.progress}%</span>
              </div>
            )}
          </div>
          
          {selectedStep.parameters && Object.keys(selectedStep.parameters).length > 0 && (
            <div className="mt-3">
              <h4 className="font-medium mb-1">Parameters:</h4>
              <div className="bg-white p-2 rounded border border-gray-200">
                <pre className="text-xs text-gray-700">
                  {JSON.stringify(selectedStep.parameters, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="p-4 border-t border-gray-200 bg-gray-50">
        <div className="flex items-center justify-around text-xs">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ backgroundColor: stepColors.input }} />
            <span>Input</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ backgroundColor: stepColors.process }} />
            <span>Process</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ backgroundColor: stepColors.analysis }} />
            <span>Analysis</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ backgroundColor: stepColors.output }} />
            <span>Output</span>
          </div>
        </div>
      </div>
    </div>
  )
}