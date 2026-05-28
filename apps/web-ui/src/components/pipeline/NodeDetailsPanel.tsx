'use client'

import React, { useState, useMemo } from 'react'
import { Node } from 'reactflow'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
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
  Network,
  PlayCircle,
  PauseCircle,
  RotateCcw,
  Eye,
  Terminal,
  Settings,
  Download,
  BarChart3,
  Copy,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Database,
  Code,
  Brain,
  FileOutput,
  TrendingUp,
  TrendingDown,
  Minus,
  Calendar,
  User,
  Tag
} from 'lucide-react'

import { PipelineNodeData } from './PipelineNode'

interface PipelineExecution {
  id: string
  pipelineId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
  startTime: Date
  endTime?: Date
  nodes: Record<string, PipelineNodeData>
  logs: Array<{
    id: string
    timestamp: Date
    nodeId: string
    level: 'info' | 'warning' | 'error' | 'debug'
    message: string
    metadata?: Record<string, any>
  }>
  results?: Record<string, any>
}

interface NodeDetailsPanelProps {
  node: Node<PipelineNodeData>
  execution?: PipelineExecution | null
  onRetryNode?: (nodeId: string) => Promise<void>
  onClose: () => void
  open: boolean
}

const typeIcons = {
  input: Database,
  process: Code,
  analysis: Brain,
  output: FileOutput
}

const statusColors = {
  pending: 'text-gray-500',
  running: 'text-blue-500',
  completed: 'text-green-500',
  failed: 'text-red-500',
  paused: 'text-yellow-500',
  skipped: 'text-gray-400'
}

export function NodeDetailsPanel({
  node,
  execution,
  onRetryNode,
  onClose,
  open
}: NodeDetailsPanelProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'logs' | 'outputs' | 'config' | 'performance'>('overview')
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['basic', 'resources']))

  const nodeData = node.data
  const TypeIcon = typeIcons[nodeData.type]

  const nodeLogs = useMemo(() => {
    if (!execution?.logs) return []
    return execution.logs
      .filter(log => log.nodeId === node.id)
      .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
  }, [execution?.logs, node.id])

  const nodeOutputs = useMemo(() => {
    if (!nodeData.outputs) return []
    return nodeData.outputs
  }, [nodeData.outputs])

  const performanceMetrics = useMemo(() => {
    if (!nodeData.resources || !nodeData.duration) return null

    const efficiency = nodeData.duration > 0 ? 
      (100 - Math.max(nodeData.resources.cpu || 0, nodeData.resources.memory || 0)) / 100 : 0

    return {
      efficiency: efficiency * 100,
      resourceBalance: nodeData.resources.cpu && nodeData.resources.memory ? 
        Math.abs((nodeData.resources.cpu - nodeData.resources.memory) / Math.max(nodeData.resources.cpu, nodeData.resources.memory)) : 0,
      avgResourceUsage: Object.values(nodeData.resources).filter(v => v !== undefined).reduce((sum, v) => sum + v!, 0) / 
        Object.values(nodeData.resources).filter(v => v !== undefined).length
    }
  }, [nodeData.resources, nodeData.duration])

  const formatTime = (date?: Date) => {
    if (!date) return '--'
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  }

  const formatDuration = (ms?: number) => {
    if (!ms) return '--'
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m ${seconds % 60}s`
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }

  const formatResourceUsage = (value?: number) => {
    if (value === undefined) return '--'
    return `${Math.round(value)}%`
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }

  const downloadLogs = () => {
    if (nodeLogs.length === 0) return
    
    const logText = nodeLogs
      .map(log => `[${log.timestamp.toISOString()}] ${log.level.toUpperCase()}: ${log.message}`)
      .join('\n')

    const blob = new Blob([logText], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${nodeData.label}-logs.txt`
    link.href = url
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const downloadOutputs = () => {
    if (nodeOutputs.length === 0) return
    
    const blob = new Blob([JSON.stringify(nodeOutputs, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${nodeData.label}-outputs.json`
    link.href = url
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const newSet = new Set(prev)
      if (newSet.has(sectionId)) {
        newSet.delete(sectionId)
      } else {
        newSet.add(sectionId)
      }
      return newSet
    })
  }

  return (
    <Sheet open={open} onOpenChange={onClose}>
      <SheetContent className="w-[600px] sm:w-[700px] overflow-hidden flex flex-col">
        <SheetHeader>
          <div className="flex items-center gap-3">
            <TypeIcon className="h-5 w-5" />
            <div>
              <SheetTitle className="text-left">{nodeData.label}</SheetTitle>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="outline" className="text-xs capitalize">
                  {nodeData.type}
                </Badge>
                <Badge variant={nodeData.status === 'completed' ? 'default' : 
                              nodeData.status === 'failed' ? 'destructive' : 
                              nodeData.status === 'running' ? 'secondary' : 'outline'} 
                       className="text-xs capitalize">
                  {nodeData.status}
                </Badge>
                {nodeData.metadata?.tool && (
                  <Badge variant="outline" className="text-xs">
                    {nodeData.metadata.tool}
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </SheetHeader>

        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)} className="flex-1 flex flex-col overflow-hidden">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="logs">
              Logs {nodeLogs.length > 0 && <span className="ml-1 text-xs">({nodeLogs.length})</span>}
            </TabsTrigger>
            <TabsTrigger value="outputs">
              Outputs {nodeOutputs.length > 0 && <span className="ml-1 text-xs">({nodeOutputs.length})</span>}
            </TabsTrigger>
            <TabsTrigger value="config">Config</TabsTrigger>
            <TabsTrigger value="performance">Performance</TabsTrigger>
          </TabsList>

          <div className="flex-1 overflow-hidden mt-4">
            <TabsContent value="overview" className="h-full">
              <ScrollArea className="h-full pr-4">
                <div className="space-y-6">
                  {/* Basic Information */}
                  <Collapsible open={expandedSections.has('basic')}>
                    <CollapsibleTrigger 
                      onClick={() => toggleSection('basic')}
                      className="flex items-center gap-2 w-full hover:bg-muted/50 p-2 rounded"
                    >
                      {expandedSections.has('basic') ? 
                        <ChevronDown className="h-4 w-4" /> : 
                        <ChevronRight className="h-4 w-4" />
                      }
                      <span className="font-medium">Basic Information</span>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-2">
                      <Card className="p-4">
                        <div className="grid grid-cols-2 gap-4 text-sm">
                          <div>
                            <span className="font-medium text-muted-foreground">Node ID:</span>
                            <div className="flex items-center gap-2">
                              <p className="font-mono text-xs">{node.id}</p>
                              <Button 
                                onClick={() => copyToClipboard(node.id)} 
                                variant="ghost" 
                                size="sm"
                                className="h-6 w-6 p-0"
                              >
                                <Copy className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                          <div>
                            <span className="font-medium text-muted-foreground">Type:</span>
                            <p className="capitalize">{nodeData.type}</p>
                          </div>
                          <div>
                            <span className="font-medium text-muted-foreground">Status:</span>
                            <p className="capitalize">{nodeData.status}</p>
                          </div>
                          <div>
                            <span className="font-medium text-muted-foreground">Priority:</span>
                            <p className="capitalize">{nodeData.priority || 'normal'}</p>
                          </div>
                          {nodeData.startTime && (
                            <div>
                              <span className="font-medium text-muted-foreground">Started:</span>
                              <p>{formatTime(nodeData.startTime)}</p>
                            </div>
                          )}
                          {nodeData.endTime && (
                            <div>
                              <span className="font-medium text-muted-foreground">Completed:</span>
                              <p>{formatTime(nodeData.endTime)}</p>
                            </div>
                          )}
                          {nodeData.duration && (
                            <div>
                              <span className="font-medium text-muted-foreground">Duration:</span>
                              <p>{formatDuration(nodeData.duration)}</p>
                            </div>
                          )}
                          {nodeData.retryCount && nodeData.retryCount > 0 && (
                            <div>
                              <span className="font-medium text-muted-foreground">Retries:</span>
                              <p>{nodeData.retryCount} / {nodeData.maxRetries || 3}</p>
                            </div>
                          )}
                        </div>

                        {nodeData.metadata?.description && (
                          <div className="mt-4">
                            <span className="font-medium text-muted-foreground">Description:</span>
                            <p className="mt-1 text-sm">{nodeData.metadata.description}</p>
                          </div>
                        )}
                      </Card>
                    </CollapsibleContent>
                  </Collapsible>

                  {/* Progress */}
                  {nodeData.progress !== undefined && (
                    <Collapsible defaultOpen>
                      <CollapsibleTrigger className="flex items-center gap-2 w-full hover:bg-muted/50 p-2 rounded">
                        <ChevronDown className="h-4 w-4" />
                        <span className="font-medium">Progress</span>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-2">
                        <Card className="p-4">
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Completion</span>
                              <span className="text-sm font-mono">{nodeData.progress}%</span>
                            </div>
                            <Progress value={nodeData.progress} className="h-3" />
                            {nodeData.metadata?.estimatedDuration && nodeData.startTime && (
                              <div className="text-xs text-muted-foreground">
                                Estimated completion: {new Date(
                                  nodeData.startTime.getTime() + nodeData.metadata.estimatedDuration
                                ).toLocaleTimeString()}
                              </div>
                            )}
                          </div>
                        </Card>
                      </CollapsibleContent>
                    </Collapsible>
                  )}

                  {/* Resource Usage */}
                  {nodeData.resources && (
                    <Collapsible open={expandedSections.has('resources')}>
                      <CollapsibleTrigger 
                        onClick={() => toggleSection('resources')}
                        className="flex items-center gap-2 w-full hover:bg-muted/50 p-2 rounded"
                      >
                        {expandedSections.has('resources') ? 
                          <ChevronDown className="h-4 w-4" /> : 
                          <ChevronRight className="h-4 w-4" />
                        }
                        <span className="font-medium">Resource Usage</span>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-2">
                        <Card className="p-4">
                          <div className="grid grid-cols-1 gap-4">
                            {nodeData.resources.cpu !== undefined && (
                              <div>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <Cpu className="h-4 w-4 text-blue-500" />
                                    <span className="text-sm font-medium">CPU</span>
                                  </div>
                                  <span className="text-sm font-mono">
                                    {formatResourceUsage(nodeData.resources.cpu)}
                                  </span>
                                </div>
                                <Progress value={nodeData.resources.cpu} className="h-2" />
                              </div>
                            )}

                            {nodeData.resources.memory !== undefined && (
                              <div>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <HardDrive className="h-4 w-4 text-green-500" />
                                    <span className="text-sm font-medium">Memory</span>
                                  </div>
                                  <span className="text-sm font-mono">
                                    {formatResourceUsage(nodeData.resources.memory)}
                                  </span>
                                </div>
                                <Progress value={nodeData.resources.memory} className="h-2" />
                              </div>
                            )}

                            {nodeData.resources.gpu !== undefined && (
                              <div>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <Zap className="h-4 w-4 text-yellow-500" />
                                    <span className="text-sm font-medium">GPU</span>
                                  </div>
                                  <span className="text-sm font-mono">
                                    {formatResourceUsage(nodeData.resources.gpu)}
                                  </span>
                                </div>
                                <Progress value={nodeData.resources.gpu} className="h-2" />
                              </div>
                            )}

                            {nodeData.resources.networkIO !== undefined && (
                              <div>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <Network className="h-4 w-4 text-purple-500" />
                                    <span className="text-sm font-medium">Network I/O</span>
                                  </div>
                                  <span className="text-sm font-mono">
                                    {formatResourceUsage(nodeData.resources.networkIO)}
                                  </span>
                                </div>
                                <Progress value={nodeData.resources.networkIO} className="h-2" />
                              </div>
                            )}
                          </div>
                        </Card>
                      </CollapsibleContent>
                    </Collapsible>
                  )}

                  {/* Error Information */}
                  {nodeData.error && (
                    <Collapsible defaultOpen>
                      <CollapsibleTrigger className="flex items-center gap-2 w-full hover:bg-muted/50 p-2 rounded">
                        <ChevronDown className="h-4 w-4" />
                        <span className="font-medium text-red-600">Error Details</span>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-2">
                        <Card className="p-4 border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/20">
                          <div className="flex items-start gap-3">
                            <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                            <div className="flex-1">
                              <div className="font-medium text-red-700 dark:text-red-300 mb-2">
                                Execution Failed
                              </div>
                              <div className="font-mono text-sm text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 p-3 rounded">
                                {nodeData.error}
                              </div>
                              {nodeData.status === 'failed' && onRetryNode && (
                                <Button
                                  onClick={() => onRetryNode(node.id)}
                                  variant="outline"
                                  size="sm"
                                  className="mt-3"
                                >
                                  <RotateCcw className="h-4 w-4 mr-2" />
                                  Retry Node
                                </Button>
                              )}
                            </div>
                          </div>
                        </Card>
                      </CollapsibleContent>
                    </Collapsible>
                  )}

                  {/* Dependencies */}
                  {nodeData.dependencies && nodeData.dependencies.length > 0 && (
                    <Collapsible>
                      <CollapsibleTrigger 
                        onClick={() => toggleSection('dependencies')}
                        className="flex items-center gap-2 w-full hover:bg-muted/50 p-2 rounded"
                      >
                        {expandedSections.has('dependencies') ? 
                          <ChevronDown className="h-4 w-4" /> : 
                          <ChevronRight className="h-4 w-4" />
                        }
                        <span className="font-medium">Dependencies</span>
                        <Badge variant="outline" className="text-xs">
                          {nodeData.dependencies.length}
                        </Badge>
                      </CollapsibleTrigger>
                      <CollapsibleContent className="mt-2">
                        <Card className="p-4">
                          <div className="space-y-2">
                            {nodeData.dependencies.map((dep, index) => (
                              <div key={index} className="flex items-center gap-2 p-2 bg-muted/50 rounded">
                                <ExternalLink className="h-3 w-3 text-muted-foreground" />
                                <span className="text-sm">{dep}</span>
                              </div>
                            ))}
                          </div>
                        </Card>
                      </CollapsibleContent>
                    </Collapsible>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="logs" className="h-full">
              <div className="h-full flex flex-col">
                <div className="flex items-center justify-between mb-4">
                  <span className="text-sm font-medium">
                    {nodeLogs.length} log entries
                  </span>
                  {nodeLogs.length > 0 && (
                    <Button onClick={downloadLogs} variant="outline" size="sm">
                      <Download className="h-4 w-4 mr-2" />
                      Download
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1">
                  {nodeLogs.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      <Terminal className="h-8 w-8 mx-auto mb-2 opacity-50" />
                      <p>No logs available</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {nodeLogs.map((log, index) => (
                        <Card key={index} className={`p-3 ${
                          log.level === 'error' ? 'border-red-200 dark:border-red-800' :
                          log.level === 'warning' ? 'border-yellow-200 dark:border-yellow-800' :
                          ''
                        }`}>
                          <div className="flex items-start justify-between mb-2">
                            <Badge variant={
                              log.level === 'error' ? 'destructive' :
                              log.level === 'warning' ? 'secondary' :
                              'outline'
                            } className="text-xs">
                              {log.level.toUpperCase()}
                            </Badge>
                            <span className="text-xs font-mono text-muted-foreground">
                              {log.timestamp.toLocaleTimeString()}
                            </span>
                          </div>
                          <div className="font-mono text-sm bg-muted/50 p-2 rounded">
                            {log.message}
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </TabsContent>

            <TabsContent value="outputs" className="h-full">
              <div className="h-full flex flex-col">
                <div className="flex items-center justify-between mb-4">
                  <span className="text-sm font-medium">
                    {nodeOutputs.length} output artifacts
                  </span>
                  {nodeOutputs.length > 0 && (
                    <Button onClick={downloadOutputs} variant="outline" size="sm">
                      <Download className="h-4 w-4 mr-2" />
                      Download
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1">
                  {nodeOutputs.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      <Eye className="h-8 w-8 mx-auto mb-2 opacity-50" />
                      <p>No outputs available</p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {nodeOutputs.map((output, index) => (
                        <Card key={index} className="p-4">
                          <div className="space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Output {index + 1}</span>
                              <Button 
                                onClick={() => copyToClipboard(JSON.stringify(output, null, 2))} 
                                variant="ghost" 
                                size="sm"
                              >
                                <Copy className="h-4 w-4" />
                              </Button>
                            </div>
                            <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-40">
                              {JSON.stringify(output, null, 2)}
                            </pre>
                          </div>
                        </Card>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </TabsContent>

            <TabsContent value="config" className="h-full">
              <ScrollArea className="h-full">
                {nodeData.parameters ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">Configuration Parameters</span>
                      <Button 
                        onClick={() => copyToClipboard(JSON.stringify(nodeData.parameters, null, 2))} 
                        variant="ghost" 
                        size="sm"
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                    <Card className="p-4">
                      <pre className="text-xs bg-muted p-3 rounded overflow-x-auto">
                        {JSON.stringify(nodeData.parameters, null, 2)}
                      </pre>
                    </Card>
                  </div>
                ) : (
                  <div className="text-center text-muted-foreground py-8">
                    <Settings className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No configuration parameters</p>
                  </div>
                )}
              </ScrollArea>
            </TabsContent>

            <TabsContent value="performance" className="h-full">
              <ScrollArea className="h-full">
                <div className="space-y-4">
                  {performanceMetrics && (
                    <Card className="p-4">
                      <h4 className="font-medium mb-3">Performance Metrics</h4>
                      <div className="grid grid-cols-1 gap-4">
                        <div className="flex items-center justify-between">
                          <span className="text-sm">Efficiency Score</span>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm">
                              {Math.round(performanceMetrics.efficiency)}%
                            </span>
                            {performanceMetrics.efficiency > 80 ? (
                              <TrendingUp className="h-4 w-4 text-green-500" />
                            ) : performanceMetrics.efficiency < 50 ? (
                              <TrendingDown className="h-4 w-4 text-red-500" />
                            ) : (
                              <Minus className="h-4 w-4 text-gray-400" />
                            )}
                          </div>
                        </div>
                        <Progress value={performanceMetrics.efficiency} className="h-2" />

                        <div className="flex items-center justify-between">
                          <span className="text-sm">Resource Balance</span>
                          <span className="font-mono text-sm">
                            {Math.round(performanceMetrics.resourceBalance * 100)}%
                          </span>
                        </div>
                        <Progress value={performanceMetrics.resourceBalance * 100} className="h-2" />

                        <div className="flex items-center justify-between">
                          <span className="text-sm">Average Resource Usage</span>
                          <span className="font-mono text-sm">
                            {Math.round(performanceMetrics.avgResourceUsage)}%
                          </span>
                        </div>
                        <Progress value={performanceMetrics.avgResourceUsage} className="h-2" />
                      </div>
                    </Card>
                  )}

                  {/* Historical Performance */}
                  <Card className="p-4">
                    <h4 className="font-medium mb-3">Historical Performance</h4>
                    <div className="text-center text-muted-foreground py-8">
                      <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-50" />
                      <p>Historical charts would be rendered here</p>
                      <p className="text-xs">Integration with charting library needed</p>
                    </div>
                  </Card>

                  {/* Recommendations */}
                  {performanceMetrics && performanceMetrics.efficiency < 70 && (
                    <Card className="p-4 border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/20">
                      <h4 className="font-medium mb-2 text-yellow-800 dark:text-yellow-200">
                        Performance Recommendations
                      </h4>
                      <div className="space-y-2 text-sm text-yellow-700 dark:text-yellow-300">
                        {performanceMetrics.avgResourceUsage > 90 && (
                          <p>• Consider increasing resource allocation for this node</p>
                        )}
                        {performanceMetrics.resourceBalance > 0.5 && (
                          <p>• Resource usage is unbalanced - check CPU vs Memory allocation</p>
                        )}
                        {nodeData.duration && nodeData.metadata?.estimatedDuration && 
                         nodeData.duration > nodeData.metadata.estimatedDuration * 1.5 && (
                          <p>• Execution time exceeded estimates - review node configuration</p>
                        )}
                      </div>
                    </Card>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>
          </div>
        </Tabs>
      </SheetContent>
    </Sheet>
  )
}

export default NodeDetailsPanel
