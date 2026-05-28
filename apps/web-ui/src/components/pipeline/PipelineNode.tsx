'use client'

import React, { memo, useMemo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
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
  Terminal,
  Settings,
  Database,
  Code,
  Brain,
  FileOutput,
  Workflow
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
    networkIO?: number
  }
  logs?: string[]
  error?: string
  parameters?: Record<string, any>
  outputs?: any[]
  metadata?: {
    tool?: string
    category?: string
    description?: string
    version?: string
    estimatedDuration?: number
  }
  dependencies?: string[]
  retryCount?: number
  maxRetries?: number
  priority?: 'low' | 'normal' | 'high' | 'critical'
}

const nodeThemes = {
  input: {
    bg: 'bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-950 dark:to-blue-900',
    border: 'border-blue-300 dark:border-blue-700',
    header: 'bg-gradient-to-r from-blue-500 to-blue-600',
    text: 'text-blue-900 dark:text-blue-100',
    icon: Database,
    shadow: 'shadow-blue-200 dark:shadow-blue-900'
  },
  process: {
    bg: 'bg-gradient-to-br from-purple-50 to-purple-100 dark:from-purple-950 dark:to-purple-900',
    border: 'border-purple-300 dark:border-purple-700',
    header: 'bg-gradient-to-r from-purple-500 to-purple-600',
    text: 'text-purple-900 dark:text-purple-100',
    icon: Code,
    shadow: 'shadow-purple-200 dark:shadow-purple-900'
  },
  analysis: {
    bg: 'bg-gradient-to-br from-orange-50 to-orange-100 dark:from-orange-950 dark:to-orange-900',
    border: 'border-orange-300 dark:border-orange-700',
    header: 'bg-gradient-to-r from-orange-500 to-orange-600',
    text: 'text-orange-900 dark:text-orange-100',
    icon: Brain,
    shadow: 'shadow-orange-200 dark:shadow-orange-900'
  },
  output: {
    bg: 'bg-gradient-to-br from-green-50 to-green-100 dark:from-green-950 dark:to-green-900',
    border: 'border-green-300 dark:border-green-700',
    header: 'bg-gradient-to-r from-green-500 to-green-600',
    text: 'text-green-900 dark:text-green-100',
    icon: FileOutput,
    shadow: 'shadow-green-200 dark:shadow-green-900'
  }
}

const statusConfigs = {
  pending: {
    icon: Clock,
    className: 'text-gray-400',
    bgColor: 'bg-gray-100 dark:bg-gray-800',
    textColor: 'text-gray-600 dark:text-gray-400',
    pulseColor: ''
  },
  running: {
    icon: Loader2,
    className: 'text-blue-500 animate-spin',
    bgColor: 'bg-blue-100 dark:bg-blue-900',
    textColor: 'text-blue-700 dark:text-blue-300',
    pulseColor: 'animate-pulse'
  },
  completed: {
    icon: CheckCircle,
    className: 'text-green-500',
    bgColor: 'bg-green-100 dark:bg-green-900',
    textColor: 'text-green-700 dark:text-green-300',
    pulseColor: ''
  },
  failed: {
    icon: XCircle,
    className: 'text-red-500',
    bgColor: 'bg-red-100 dark:bg-red-900',
    textColor: 'text-red-700 dark:text-red-300',
    pulseColor: 'animate-bounce'
  },
  paused: {
    icon: PauseCircle,
    className: 'text-yellow-500',
    bgColor: 'bg-yellow-100 dark:bg-yellow-900',
    textColor: 'text-yellow-700 dark:text-yellow-300',
    pulseColor: ''
  },
  skipped: {
    icon: AlertCircle,
    className: 'text-gray-400',
    bgColor: 'bg-gray-100 dark:bg-gray-800',
    textColor: 'text-gray-500 dark:text-gray-400',
    pulseColor: ''
  }
}

const priorityColors = {
  low: 'border-l-gray-400',
  normal: 'border-l-blue-400',
  high: 'border-l-orange-400',
  critical: 'border-l-red-500 animate-pulse'
}

export function PipelineNode({ data, selected }: NodeProps<PipelineNodeData>) {
  // Defensive defaults to avoid runtime errors when data is incomplete
  const safeType = (data?.type && (nodeThemes as any)[data.type]) ? data.type : 'process'
  const safeStatus = (data?.status && (statusConfigs as any)[data.status]) ? data.status : 'pending'

  const theme = nodeThemes[safeType as keyof typeof nodeThemes]
  const statusConfig = statusConfigs[safeStatus as keyof typeof statusConfigs]
  const StatusIcon = statusConfig?.icon || Clock
  const TypeIcon = theme?.icon || Code
  const priorityClass = priorityColors[data?.priority || 'normal']

  const formatDuration = (ms?: number) => {
    if (!ms) return '--'
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }

  const formatResourceUsage = (value?: number) => {
    if (value === undefined) return null
    return `${Math.round(value)}%`
  }

  const getEstimatedTimeRemaining = () => {
    if (safeStatus !== 'running' || !data?.progress || !data?.startTime) return null
    
    const elapsed = Date.now() - data.startTime.getTime()
    const estimatedTotal = (elapsed / data.progress) * 100
    const remaining = estimatedTotal - elapsed
    
    return remaining > 0 ? formatDuration(remaining) : null
  }

  const progressValue = data?.progress !== undefined ? Math.max(0, Math.min(100, data.progress)) : 0

  const hasResources = !!(data?.resources && Object.values(data.resources).some(val => val !== undefined))
  const hasActions = safeStatus === 'failed' || (!!data?.logs && data.logs.length > 0) || (!!data?.outputs && data.outputs.length > 0)

  return (
    <div
      className={`
        ${theme?.bg || ''} ${theme?.border || ''} ${theme?.text || ''} ${priorityClass}
        rounded-xl border-2 border-l-4 shadow-lg ${theme.shadow} 
        transition-all duration-300 ease-in-out min-w-[300px] max-w-[400px]
        ${selected ? 'ring-2 ring-blue-400 ring-opacity-75 scale-105' : ''}
        ${data.status === 'failed' ? 'ring-2 ring-red-400 ring-opacity-50' : ''}
        ${data.status === 'running' ? 'shadow-xl transform scale-102' : ''}
        ${statusConfig.pulseColor}
        hover:shadow-xl hover:scale-102 cursor-pointer
      `}
    >
      {/* Input Handle */}
      {data.type !== 'input' && (
        <Handle
          type="target"
          position={Position.Left}
          className="w-3 h-3 border-2 bg-white shadow-md transition-transform hover:scale-125"
          style={{ left: -6 }}
        />
      )}

      {/* Header */}
      <div className={`${theme?.header || ''} px-4 py-3 rounded-t-xl text-white font-semibold flex items-center justify-between shadow-sm`}>
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <TypeIcon className="h-4 w-4 flex-shrink-0" />
          <span className="text-sm truncate" title={data?.label}>{data?.label || 'Step'}</span>
          {data?.metadata?.tool && (
            <Badge variant="secondary" className="text-xs bg-white/20 text-white border-white/30">
              {data.metadata.tool}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {data?.priority === 'critical' && <span className="w-2 h-2 bg-red-400 rounded-full animate-pulse" />}
          <StatusIcon className={`h-4 w-4 ${statusConfig.className}`} />
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {/* Status & Duration Row */}
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <Badge
              variant="secondary"
              className={`capitalize text-xs ${statusConfig.bgColor} ${statusConfig.textColor} border-0`}
            >
              {safeStatus}
            </Badge>
            {safeStatus === 'running' && data?.progress !== undefined && (
              <span className="text-xs text-muted-foreground">{data.progress}%</span>
            )}
            {data?.retryCount && data.retryCount > 0 && (
              <Badge variant="outline" className="text-xs">
                Retry {data.retryCount}/{data.maxRetries || 3}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground text-right">
            <div>{formatDuration(data?.duration)}</div>
            {safeStatus === 'running' && getEstimatedTimeRemaining() && (
              <div className="text-xs opacity-75">{getEstimatedTimeRemaining()} left</div>
            )}
          </div>
        </div>

        {/* Progress Bar */}
        {safeStatus === 'running' && data?.progress !== undefined && (
          <div className="space-y-1">
            <Progress 
              value={progressValue} 
              className="h-2 transition-all duration-300" 
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{progressValue}%</span>
              {data?.metadata?.estimatedDuration && (
                <span>~{formatDuration(data.metadata.estimatedDuration)}</span>
              )}
            </div>
          </div>
        )}

        {/* Resource Usage */}
        {hasResources && (
          <div className="grid grid-cols-2 gap-2 text-xs">
            {data?.resources?.cpu !== undefined && (
              <div className="flex items-center gap-1 p-2 rounded bg-muted/50">
                <Cpu className="h-3 w-3 text-blue-500" />
                <span className="font-medium">CPU</span>
                <span className="ml-auto">{formatResourceUsage(data?.resources?.cpu)}</span>
              </div>
            )}
            {data?.resources?.memory !== undefined && (
              <div className="flex items-center gap-1 p-2 rounded bg-muted/50">
                <HardDrive className="h-3 w-3 text-green-500" />
                <span className="font-medium">RAM</span>
                <span className="ml-auto">{formatResourceUsage(data?.resources?.memory)}</span>
              </div>
            )}
            {data?.resources?.gpu !== undefined && (
              <div className="flex items-center gap-1 p-2 rounded bg-muted/50">
                <Zap className="h-3 w-3 text-yellow-500" />
                <span className="font-medium">GPU</span>
                <span className="ml-auto">{formatResourceUsage(data?.resources?.gpu)}</span>
              </div>
            )}
            {data?.resources?.networkIO !== undefined && (
              <div className="flex items-center gap-1 p-2 rounded bg-muted/50">
                <Activity className="h-3 w-3 text-purple-500" />
                <span className="font-medium">I/O</span>
                <span className="ml-auto">{formatResourceUsage(data?.resources?.networkIO)}</span>
              </div>
            )}
          </div>
        )}

        {/* Error Message */}
        {data?.error && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <span className="font-medium text-red-700 dark:text-red-300">Error</span>
            </div>
            <div className="font-mono text-xs text-red-600 dark:text-red-400 break-words">
              {data?.error}
            </div>
          </div>
        )}

        {/* Metadata */}
        {data?.metadata?.description && !data?.error && (
          <div className="text-xs text-muted-foreground p-2 bg-muted/30 rounded">
            {data?.metadata?.description}
          </div>
        )}

        {/* Quick Actions */}
        {hasActions && (
          <div className="flex items-center justify-between pt-2 border-t border-muted/50">
            <div className="flex gap-1">
              {safeStatus === 'failed' && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0 hover:bg-red-100 dark:hover:bg-red-900/20"
                  title="Retry node"
                >
                  <RotateCcw className="h-3 w-3 text-red-500" />
                </Button>
              )}
              {data?.logs && data.logs.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  title="View logs"
                >
                  <Terminal className="h-3 w-3" />
                </Button>
              )}
              {data?.outputs && data.outputs.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  title="View outputs"
                >
                  <Eye className="h-3 w-3" />
                </Button>
              )}
              {data?.parameters && Object.keys(data.parameters).length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  title="View parameters"
                >
                  <Settings className="h-3 w-3" />
                </Button>
              )}
            </div>
            
            <div className="flex items-center gap-2 text-xs">
              {data?.metadata?.category && (
                <Badge variant="outline" className="text-xs">
                  {data?.metadata?.category}
                </Badge>
              )}
              {data?.metadata?.version && (
                <Badge variant="outline" className="text-xs">
                  v{data?.metadata?.version}
                </Badge>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Output Handle */}
      {safeType !== 'output' && (
        <Handle
          type="source"
          position={Position.Right}
          className="w-3 h-3 border-2 bg-white shadow-md transition-transform hover:scale-125"
          style={{ right: -6 }}
        />
      )}

      {/* Execution Indicator */}
      {safeStatus === 'running' && (
        <div className="absolute -top-1 -right-1 w-4 h-4 bg-blue-500 rounded-full animate-pulse shadow-lg">
          <div className="absolute inset-0 bg-blue-400 rounded-full animate-ping opacity-75" />
        </div>
      )}

      {/* Priority Indicator */}
      {data?.priority === 'critical' && (
        <div className="absolute -top-1 -left-1 w-3 h-3 bg-red-500 rounded-full animate-pulse shadow-lg" />
      )}
    </div>
  )
}

export default memo(PipelineNode)
