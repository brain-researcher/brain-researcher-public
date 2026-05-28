import React from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  X,
  Download,
  Eye,
  Terminal,
  Clock,
} from 'lucide-react'

interface ExecutionResult {
  nodeId: string
  tool: string
  status: 'success' | 'error' | 'warning' | 'running'
  output?: string
  error?: string
  duration?: number
  timestamp?: string
  recovery?: {
    from_tool?: string
    to_tool?: string
    reason?: string
  }
  error_taxonomy?: {
    category?: string
    recovery_strategy?: string
    recovery_suggestions?: string[]
  }
}

interface ExecutionPanelProps {
  results: ExecutionResult[]
  isExecuting: boolean
  onClose: () => void
}

export default function ExecutionPanel({
  results,
  isExecuting,
  onClose,
}: ExecutionPanelProps) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'error':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'warning':
        return <AlertCircle className="h-4 w-4 text-yellow-500" />
      case 'running':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      default:
        return null
    }
  }

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      success: 'default',
      error: 'destructive',
      warning: 'secondary',
      running: 'outline',
    }
    return (
      <Badge variant={variants[status] || 'outline'} className="text-xs">
        {status}
      </Badge>
    )
  }

  const downloadLog = () => {
    const log = results.map(r => 
      `[${r.timestamp || new Date().toISOString()}] ${r.tool} (${r.nodeId}): ${r.status}\n${r.output || r.error || ''}\n`
    ).join('\n')
    
    const blob = new Blob([log], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `execution-log-${Date.now()}.txt`
    link.href = url
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="absolute bottom-0 left-0 right-0 z-50">
      <Card className="m-4 shadow-xl border-t-4 border-t-primary">
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-3">
            <Terminal className="h-5 w-5" />
            <h3 className="font-semibold">Execution Monitor</h3>
            {isExecuting && (
              <Badge variant="outline" className="animate-pulse">
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                Running
              </Badge>
            )}
            <Badge variant="secondary">
              {results.filter(r => r.status === 'success').length}/{results.length} completed
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={downloadLog}
              disabled={results.length === 0}
            >
              <Download className="h-4 w-4 mr-2" />
              Export Log
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <ScrollArea className="h-64">
          <div className="p-4 space-y-3">
            {results.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                No execution results yet. Click "Execute" to run the workflow.
              </div>
            ) : (
              results.map((result, index) => (
                <div key={`${result.nodeId}-${index}`}>
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                    <div className="mt-0.5">
                      {getStatusIcon(result.status)}
                    </div>
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{result.tool}</span>
                          <span className="text-xs text-muted-foreground font-mono">
                            {result.nodeId}
                          </span>
                          {getStatusBadge(result.status)}
                        </div>
                        {result.duration && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Clock className="h-3 w-3" />
                            {result.duration}ms
                          </div>
                        )}
                      </div>
                      
                      {result.output && (
                        <div className="text-sm text-muted-foreground">
                          {result.output}
                        </div>
                      )}
                      
                      {result.error && (
                        <div className="text-sm text-red-600 dark:text-red-400 font-mono text-xs bg-red-50 dark:bg-red-950/20 p-2 rounded">
                          {result.error}
                        </div>
                      )}

                      {result.recovery && (result.recovery.from_tool || result.recovery.to_tool) && (
                        <div className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-950/20 p-2 rounded">
                          Recovery: {result.recovery.from_tool} → {result.recovery.to_tool}
                          {result.recovery.reason ? ` • ${result.recovery.reason}` : ''}
                        </div>
                      )}

                      {result.error_taxonomy && (
                        <div className="text-xs text-gray-600 bg-muted/50 p-2 rounded">
                          <div>Category: {result.error_taxonomy.category || 'unknown'}</div>
                          {result.error_taxonomy.recovery_strategy && (
                            <div>Strategy: {result.error_taxonomy.recovery_strategy}</div>
                          )}
                          {Array.isArray(result.error_taxonomy.recovery_suggestions) &&
                            result.error_taxonomy.recovery_suggestions.length > 0 && (
                              <div>
                                Suggestions: {result.error_taxonomy.recovery_suggestions.slice(0, 2).join('; ')}
                              </div>
                            )}
                        </div>
                      )}

                      {result.status === 'success' && (
                        <div className="flex gap-2 mt-2">
                          <Button variant="ghost" size="sm" className="h-6 text-xs">
                            <Eye className="h-3 w-3 mr-1" />
                            View Output
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                  {index < results.length - 1 && <Separator className="my-2" />}
                </div>
              ))
            )}
          </div>
        </ScrollArea>

        {isExecuting && (
          <div className="p-2 border-t bg-muted/50">
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Processing workflow nodes...
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
