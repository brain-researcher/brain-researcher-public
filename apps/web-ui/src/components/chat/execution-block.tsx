'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight, Clock, CheckCircle, XCircle, Loader2, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { ExecutionBlock as ExecutionBlockType, ExecutionStep } from '@/types/chat'
import { formatDuration } from '@/lib/utils'

interface ExecutionBlockProps {
  executionBlock: ExecutionBlockType
  onCancel?: (jobId: string) => void
}

function ExecutionStepItem({ step }: { step: ExecutionStep }) {
  const [isExpanded, setIsExpanded] = useState(false)
  const toolQuery = step.tool ? encodeURIComponent(step.tool) : null

  const normalizedStatus = (() => {
    const status = (step.status ?? 'pending').toString().toLowerCase()
    if (status === 'success' || status === 'succeeded') return 'completed'
    if (status === 'error') return 'failed'
    if (status === 'skipped') return 'completed'
    return status
  })()

  const getStatusIcon = () => {
    switch (normalizedStatus) {
      case 'pending':
        return <Clock className="h-4 w-4 text-muted-foreground" />
      case 'running':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getDuration = () => {
    if (!step.timing?.startTime) return null
    if (step.timing.endTime) {
      return formatDuration((step.timing.endTime.getTime() - step.timing.startTime.getTime()) / 1000)
    }
    if (normalizedStatus === 'running') {
      return formatDuration((Date.now() - step.timing.startTime.getTime()) / 1000)
    }
    return null
  }

  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getStatusIcon()}
          <div>
            <div className="font-medium text-sm">{step.name}</div>
            <div className="text-xs text-muted-foreground">
              {step.tool} • {getDuration() && `${getDuration()} • `}
              {step.preview}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {toolQuery ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              asChild
            >
              <a href={`/library/tools?q=${toolQuery}&tool=${toolQuery}`}>View tool</a>
            </Button>
          ) : null}

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="h-6 w-6 p-0"
            aria-label={isExpanded ? 'Collapse step' : 'Expand step'}
          >
            {isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </Button>
        </div>
      </div>

      {isExpanded && (
        <div className="pl-7 space-y-2 text-xs">
          <div>
            <div className="font-medium mb-1">Arguments:</div>
            <pre className="bg-muted p-2 rounded text-xs overflow-x-auto">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
          
          {step.logs && step.logs.length > 0 && (
            <div>
              <div className="font-medium mb-1">Logs:</div>
              <div className="bg-muted p-2 rounded max-h-32 overflow-y-auto space-y-1">
                {step.logs.map((log, index) => (
                  <div key={index} className="flex gap-2">
                    <span className="text-muted-foreground">
                      {log.timestamp.toLocaleTimeString()}
                    </span>
                    <span className={
                      log.level === 'ERROR' ? 'text-red-500' :
                      log.level === 'WARN' ? 'text-yellow-500' :
                      'text-foreground'
                    }>
                      [{log.level}]
                    </span>
                    <span>{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ExecutionBlock({ executionBlock, onCancel }: ExecutionBlockProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  const getStatusColor = () => {
    switch (executionBlock.status) {
      case 'running':
        return 'border-blue-500 bg-blue-50 dark:bg-blue-950'
      case 'completed':
        return 'border-green-500 bg-green-50 dark:bg-green-950'
      case 'failed':
        return 'border-red-500 bg-red-50 dark:bg-red-950'
      case 'cancelled':
        return 'border-yellow-500 bg-yellow-50 dark:bg-yellow-950'
      default:
        return 'border-muted'
    }
  }

  const getStatusIcon = () => {
    switch (executionBlock.status) {
      case 'queued':
        return <Clock className="h-4 w-4 text-muted-foreground" />
      case 'running':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'cancelled':
        return <Square className="h-4 w-4 text-yellow-500" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  const getTotalDuration = () => {
    if (!executionBlock.startTime) return null
    if (executionBlock.endTime) {
      return formatDuration((executionBlock.endTime.getTime() - executionBlock.startTime.getTime()) / 1000)
    }
    if (executionBlock.status === 'running') {
      return formatDuration((Date.now() - executionBlock.startTime.getTime()) / 1000)
    }
    return null
  }

  return (
    <Card className={`${getStatusColor()} transition-colors`}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {getStatusIcon()}
            <div>
              <div className="font-medium text-sm capitalize">
                {executionBlock.status} • {executionBlock.steps.length} steps
              </div>
              <div className="text-xs text-muted-foreground">
                {getTotalDuration() && `${getTotalDuration()} • `}
                {executionBlock.artifacts.length} artifacts generated
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {executionBlock.status === 'running' && onCancel && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onCancel(executionBlock.id)}
                className="h-7"
              >
                Cancel
              </Button>
            )}
            
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="h-7 w-7 p-0"
            >
              {isCollapsed ? (
                <ChevronRight className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {executionBlock.error && (
          <div className="mt-2 p-2 bg-red-100 dark:bg-red-900 rounded text-sm text-red-700 dark:text-red-300">
            <strong>Error:</strong> {executionBlock.error}
          </div>
        )}
      </CardHeader>

      {!isCollapsed && (
        <CardContent className="pt-0 space-y-3">
          {executionBlock.steps.map((step) => (
            <ExecutionStepItem key={step.id} step={step} />
          ))}

          {executionBlock.artifacts.length > 0 && (
            <div>
              <div className="font-medium text-sm mb-2">Generated Artifacts:</div>
              <div className="grid gap-2">
                {executionBlock.artifacts.map((artifact) => (
                  <div key={artifact.id} className="flex items-center justify-between p-2 bg-muted rounded">
                    <div>
                      <div className="font-medium text-sm">{artifact.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {artifact.type} • {artifact.size && formatBytes(artifact.size)}
                      </div>
                    </div>
                    <Button variant="outline" size="sm" asChild>
                      <a href={artifact.url} target="_blank" rel="noopener noreferrer">
                        View
                      </a>
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}
