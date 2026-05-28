'use client'

import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  Clock,
  Activity,
  Cpu,
  HardDrive,
  Zap,
  PlayCircle,
  PauseCircle,
  RotateCcw,
  Eye,
  Terminal
} from 'lucide-react'

export interface PipelineNodeData {
  label: string
  type: 'input' | 'process' | 'analysis' | 'output'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'paused' | 'skipped'
  progress?: number
  startTime?: Date
  endTime?: Date
  duration?: number
  resources?: {
    cpu?: number
    memory?: number
    gpu?: number
  }
  logs?: string[]
  error?: string
  parameters?: Record<string, any>
  outputs?: any[]
  inputs?: any[]
  tool?: any
  category?: string
  metrics?: Record<string, any>
  metadata?: {
    tool?: string
    category?: string
    description?: string
  }
}

const nodeColors = {
  input: {
    bg: 'bg-blue-50 dark:bg-blue-950',
    border: 'border-blue-300 dark:border-blue-700',
    header: 'bg-blue-500',
    text: 'text-blue-900 dark:text-blue-100'
  },
  process: {
    bg: 'bg-purple-50 dark:bg-purple-950',
    border: 'border-purple-300 dark:border-purple-700', 
    header: 'bg-purple-500',
    text: 'text-purple-900 dark:text-purple-100'
  },
  analysis: {
    bg: 'bg-orange-50 dark:bg-orange-950',
    border: 'border-orange-300 dark:border-orange-700',
    header: 'bg-orange-500',
    text: 'text-orange-900 dark:text-orange-100'
  },
  output: {
    bg: 'bg-green-50 dark:bg-green-950',
    border: 'border-green-300 dark:border-green-700',
    header: 'bg-green-500',
    text: 'text-green-900 dark:text-green-100'
  }
}

const statusIcons = {
  pending: { icon: Clock, className: 'text-gray-400' },
  running: { icon: Loader2, className: 'text-blue-500 animate-spin' },
  completed: { icon: CheckCircle, className: 'text-green-500' },
  failed: { icon: XCircle, className: 'text-red-500' },
  paused: { icon: PauseCircle, className: 'text-yellow-500' }
}

export function PipelineNode({ data, selected }: NodeProps<PipelineNodeData>) {
  const colors = nodeColors[data.type]
  // Add defensive check for undefined status
  const statusConfig = statusIcons[data.status] || statusIcons.pending
  const StatusIcon = statusConfig.icon

  const formatDuration = (ms?: number) => {
    if (!ms) return '--'
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }

  const formatResourceUsage = (value?: number) => {
    if (value === undefined) return '--'
    return `${Math.round(value)}%`
  }

  return (
    <div 
      className={`
        ${colors.bg} ${colors.border} ${colors.text}
        rounded-lg border-2 shadow-lg transition-all duration-200 min-w-[280px]
        ${selected ? 'ring-2 ring-blue-400 ring-opacity-75' : ''}
        ${data.status === 'failed' ? 'ring-2 ring-red-400 ring-opacity-50' : ''}
        ${data.status === 'running' ? 'shadow-xl' : ''}
      `}
    >
      {/* Input Handle */}
      {data.type !== 'input' && (
        <Handle
          type="target"
          position={Position.Left}
          className="w-3 h-3 border-2 bg-white"
          style={{ left: -6 }}
        />
      )}

      {/* Header */}
      <div className={`${colors.header} px-4 py-2 rounded-t-lg text-white font-semibold flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <span className="text-sm">{data.label}</span>
          {data.metadata?.tool && (
            <Badge variant="secondary" className="text-xs bg-white/20">
              {data.metadata.tool}
            </Badge>
          )}
        </div>
        <StatusIcon className={`h-4 w-4 ${statusConfig.className}`} />
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {/* Status & Duration */}
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <span className="capitalize font-medium">{data.status}</span>
            {data.status === 'running' && data.progress !== undefined && (
              <span className="text-xs opacity-75">{data.progress}%</span>
            )}
          </div>
          <span className="text-xs opacity-75">{formatDuration(data.duration)}</span>
        </div>

        {/* Progress Bar */}
        {data.status === 'running' && data.progress !== undefined && (
          <Progress value={data.progress} className="h-1.5" />
        )}

        {/* Resource Usage */}
        {data.resources && (
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              <span>{formatResourceUsage(data.resources.cpu)}</span>
            </div>
            <div className="flex items-center gap-1">
              <HardDrive className="h-3 w-3" />
              <span>{formatResourceUsage(data.resources.memory)}</span>
            </div>
            <div className="flex items-center gap-1">
              <Zap className="h-3 w-3" />
              <span>{formatResourceUsage(data.resources.gpu)}</span>
            </div>
          </div>
        )}

        {/* Error Message */}
        {data.error && (
          <div className="p-2 bg-red-100 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-xs text-red-700 dark:text-red-300">
            <div className="flex items-center gap-1 mb-1">
              <AlertCircle className="h-3 w-3" />
              <span className="font-medium">Error</span>
            </div>
            <div className="font-mono text-xs opacity-90">{data.error}</div>
          </div>
        )}

        {/* Quick Actions */}
        <div className="flex items-center justify-between text-xs">
          <div className="flex gap-1">
            {data.status === 'failed' && (
              <button className="p-1 hover:bg-black/5 dark:hover:bg-white/5 rounded">
                <RotateCcw className="h-3 w-3" />
              </button>
            )}
            {data.status === 'running' && (
              <button className="p-1 hover:bg-black/5 dark:hover:bg-white/5 rounded">
                <PauseCircle className="h-3 w-3" />
              </button>
            )}
            {data.logs && data.logs.length > 0 && (
              <button className="p-1 hover:bg-black/5 dark:hover:bg-white/5 rounded">
                <Terminal className="h-3 w-3" />
              </button>
            )}
            {data.outputs && data.outputs.length > 0 && (
              <button className="p-1 hover:bg-black/5 dark:hover:bg-white/5 rounded">
                <Eye className="h-3 w-3" />
              </button>
            )}
          </div>
          {data.metadata?.category && (
            <Badge variant="outline" className="text-xs">
              {data.metadata.category}
            </Badge>
          )}
        </div>
      </div>

      {/* Output Handle */}
      {data.type !== 'output' && (
        <Handle
          type="source"
          position={Position.Right}
          className="w-3 h-3 border-2 bg-white"
          style={{ right: -6 }}
        />
      )}
    </div>
  )
}

export default memo(PipelineNode)