'use client'

import React, { useState, useCallback, useMemo, useRef } from 'react'
import ReactFlow, {
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  Panel,
  Node,
  Edge,
  MarkerType,
  useReactFlow,
  FitViewOptions
} from 'reactflow'
import 'reactflow/dist/style.css'

import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Download,
  Settings,
  Maximize2,
  Minimize2,
  ZoomIn,
  ZoomOut,
  Activity,
  Clock,
  AlertTriangle,
  CheckCircle,
  Loader2,
  Eye,
  EyeOff,
  Search,
  Filter
} from 'lucide-react'

import { PipelineNode, PipelineNodeData } from './PipelineNode'
import { PipelineTimeline, TimelineEvent } from './PipelineTimeline'
import { ResourceMonitor } from './ResourceMonitor'
import { NodeDetailsPanel } from './NodeDetailsPanel'
import { usePipelineMonitoring } from '../../hooks/use-pipeline-monitoring'

const nodeTypes = {
  pipeline: PipelineNode
}

const defaultEdgeOptions = {
  type: 'smoothstep',
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20
  },
  style: {
    strokeWidth: 2,
    stroke: '#64748b'
  }
}

export interface PipelineVisualizationProps {
  pipelineId: string
  initialNodes?: Node<PipelineNodeData>[]
  initialEdges?: Edge[]
  onNodeSelect?: (node: Node<PipelineNodeData> | null) => void
  onExport?: (format: 'png' | 'json' | 'svg' | 'logs') => void
  showTimeline?: boolean
  showMinimap?: boolean
  showResourceMonitor?: boolean
  autoLayout?: boolean
  height?: string
  className?: string
}

interface PipelineStats {
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  paused: number
}

const fitViewOptions: FitViewOptions = {
  padding: 0.2,
  includeHiddenNodes: false,
  minZoom: 0.1,
  maxZoom: 1.5
}

function PipelineVisualizationInner({
  pipelineId,
  initialNodes = [],
  initialEdges = [],
  onNodeSelect,
  onExport,
  showTimeline = true,
  showMinimap = true,
  showResourceMonitor = false,
  autoLayout = false,
  height = '600px',
  className = ''
}: PipelineVisualizationProps) {
  const reactFlowInstance = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [selectedNode, setSelectedNode] = useState<Node<PipelineNodeData> | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showTimelinePanel, setShowTimelinePanel] = useState(showTimeline)
  const [showResourcePanel, setShowResourcePanel] = useState(showResourceMonitor)
  const containerRef = useRef<HTMLDivElement>(null)

  // Pipeline monitoring hook
  const {
    pipeline,
    execution,
    monitoringEnabled,
    wsTargetReady,
    transportMode,
    isConnected,
    connectionState,
    reconnect,
    startPipeline,
    pausePipeline,
    resumePipeline,
    cancelPipeline,
    retryNode,
    exportLogs,
    exportPipelineImage,
    error: monitoringError,
    loading
  } = usePipelineMonitoring({
    pipelineId,
    autoConnect: true,
    enableResourceMonitoring: true
  })

  // Update nodes from pipeline status, creating them from snapshots when needed.
  React.useEffect(() => {
    const pipelineNodes = pipeline?.nodes
    if (!pipelineNodes) return
    const entries = Object.entries(pipelineNodes)
    if (entries.length === 0) return

    setNodes((prevNodes) => {
      const prevById = new Map(prevNodes.map((node) => [node.id, node]))

      const nextNodes = entries.map(([id, data], index) => {
        const prev = prevById.get(id)
        const position = prev?.position ?? {
          x: (index % 3) * 300,
          y: Math.floor(index / 3) * 150,
        }

        const mergedData: PipelineNodeData = {
          ...(prev?.data ?? {}),
          ...data,
        }

        return {
          id,
          type: 'pipeline',
          position,
          data: mergedData,
          selected: prev?.selected ?? false,
        }
      })

      return nextNodes
    })
  }, [pipeline?.nodes, setNodes])

  // Keep edges in sync with pipeline snapshots.
  React.useEffect(() => {
    if (!pipeline?.edges) return

    setEdges((prevEdges) => {
      const nextEdges = pipeline.edges.map((edge) => ({
        ...edge,
        type: edge.type ?? 'smoothstep',
      }))

      if (
        prevEdges.length === nextEdges.length &&
        prevEdges.every((edge, index) => edge.id === nextEdges[index].id)
      ) {
        return prevEdges
      }

      return nextEdges
    })
  }, [pipeline?.edges, setEdges])

  // Update edges animation based on execution status
  React.useEffect(() => {
    if (!pipeline?.status) return

    setEdges((prevEdges) => {
      let changed = false
      const nextEdges = prevEdges.map((edge) => {
        const isRunning = pipeline.status === 'running'
        const sourceNode = pipeline.nodes?.[edge.source]
        const targetNode = pipeline.nodes?.[edge.target]
        const isActiveFlow =
          isRunning &&
          (sourceNode?.status === 'running' || targetNode?.status === 'running')

        const nextAnimated = Boolean(isActiveFlow)
        const nextStyle = {
          ...edge.style,
          stroke: isActiveFlow ? '#3b82f6' : '#64748b',
          strokeWidth: isActiveFlow ? 3 : 2,
          opacity: isActiveFlow ? 1 : isRunning ? 0.6 : 1,
        }

        // Avoid triggering ReactFlow store updates when nothing materially changed.
        const currentStroke = (edge.style as any)?.stroke
        const currentStrokeWidth = (edge.style as any)?.strokeWidth
        const currentOpacity = (edge.style as any)?.opacity
        const styleUnchanged =
          currentStroke === nextStyle.stroke &&
          currentStrokeWidth === nextStyle.strokeWidth &&
          currentOpacity === nextStyle.opacity

        if (edge.animated === nextAnimated && styleUnchanged) return edge

        changed = true

        return {
          ...edge,
          animated: nextAnimated,
          style: nextStyle,
        }
      })

      return changed ? nextEdges : prevEdges
    })
  }, [pipeline?.status, pipeline?.nodes, setEdges])

  // Auto layout when requested
  React.useEffect(() => {
    if (autoLayout && reactFlowInstance && nodes.length > 0) {
      const layoutedElements = applyDagreLayout(nodes, edges)
      setNodes(layoutedElements.nodes)
      setEdges(layoutedElements.edges)
    }
  }, [autoLayout, reactFlowInstance, nodes.length])

  const onNodeClick = useCallback((event: React.MouseEvent, node: Node<PipelineNodeData>) => {
    event.stopPropagation()
    setSelectedNode(node)
    setShowDetails(true)
    onNodeSelect?.(node)
  }, [onNodeSelect])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
    setShowDetails(false)
    onNodeSelect?.(null)
  }, [onNodeSelect])

  const handleStartPipeline = useCallback(async () => {
    try {
      await startPipeline(pipelineId)
    } catch (err) {
      console.error('Failed to start pipeline:', err)
    }
  }, [startPipeline, pipelineId])

  const handlePausePipeline = useCallback(async () => {
    if (execution?.id) {
      try {
        await pausePipeline(execution.id)
      } catch (err) {
        console.error('Failed to pause pipeline:', err)
      }
    }
  }, [pausePipeline, execution?.id])

  const handleResumePipeline = useCallback(async () => {
    if (execution?.id) {
      try {
        await resumePipeline(execution.id)
      } catch (err) {
        console.error('Failed to resume pipeline:', err)
      }
    }
  }, [resumePipeline, execution?.id])

  const handleCancelPipeline = useCallback(async () => {
    if (execution?.id) {
      try {
        await cancelPipeline(execution.id)
      } catch (err) {
        console.error('Failed to cancel pipeline:', err)
      }
    }
  }, [cancelPipeline, execution?.id])

  const handleRetryNode = useCallback(async (nodeId: string) => {
    if (execution?.id) {
      try {
        await retryNode(execution.id, nodeId)
      } catch (err) {
        console.error('Failed to retry node:', err)
      }
    }
  }, [retryNode, execution?.id])

  const handleExport = useCallback(async (format: 'png' | 'json' | 'svg' | 'logs') => {
    try {
      switch (format) {
        case 'png':
        case 'svg':
          const imageBlob = await exportPipelineImage(format)
          if (imageBlob) {
            const url = URL.createObjectURL(imageBlob)
            const link = document.createElement('a')
            link.download = `pipeline-${pipelineId}.${format}`
            link.href = url
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
            URL.revokeObjectURL(url)
          }
          break
        case 'json':
          const pipelineData = {
            pipeline,
            execution,
            nodes: nodes.map(n => ({ ...n, selected: false })),
            edges: edges.map(e => ({ ...e, selected: false })),
            exportedAt: new Date().toISOString()
          }
          const jsonBlob = new Blob([JSON.stringify(pipelineData, null, 2)], {
            type: 'application/json'
          })
          const jsonUrl = URL.createObjectURL(jsonBlob)
          const jsonLink = document.createElement('a')
          jsonLink.download = `pipeline-${pipelineId}.json`
          jsonLink.href = jsonUrl
          document.body.appendChild(jsonLink)
          jsonLink.click()
          document.body.removeChild(jsonLink)
          URL.revokeObjectURL(jsonUrl)
          break
        case 'logs':
          if (execution?.id) {
            exportLogs(execution.id)
          }
          break
      }
      onExport?.(format)
    } catch (err) {
      console.error(`Failed to export ${format}:`, err)
    }
  }, [exportPipelineImage, exportLogs, pipeline, execution, nodes, edges, pipelineId, onExport])

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement && containerRef.current) {
      containerRef.current.requestFullscreen?.()
      setIsFullscreen(true)
    } else if (document.exitFullscreen) {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }, [])

  const handleFitView = useCallback(() => {
    reactFlowInstance?.fitView(fitViewOptions)
  }, [reactFlowInstance])

  const handleZoomIn = useCallback(() => {
    reactFlowInstance?.zoomIn({ duration: 300 })
  }, [reactFlowInstance])

  const handleZoomOut = useCallback(() => {
    reactFlowInstance?.zoomOut({ duration: 300 })
  }, [reactFlowInstance])

  const pipelineStats: PipelineStats = useMemo(() => {
    if (!pipeline) {
      return { total: 0, pending: 0, running: 0, completed: 0, failed: 0, paused: 0 }
    }

    const nodeStates = Object.values(pipeline.nodes)
    return {
      total: nodeStates.length,
      pending: nodeStates.filter(n => n.status === 'pending').length,
      running: nodeStates.filter(n => n.status === 'running').length,
      completed: nodeStates.filter(n => n.status === 'completed').length,
      failed: nodeStates.filter(n => n.status === 'failed').length,
      paused: nodeStates.filter(n => n.status === 'paused').length
    }
  }, [pipeline])

  const getStatusIcon = () => {
    switch (pipeline?.status) {
      case 'running':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <AlertTriangle className="h-4 w-4 text-red-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  const getConnectionStatus = () => {
    if (!monitoringEnabled) {
      return (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">Monitoring disabled</Badge>
          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="outline">
                <Settings className="h-4 w-4 mr-2" />
                Configure WS URL
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 text-xs" align="end">
              <div className="space-y-2">
                <div className="font-medium">Enable pipeline monitoring</div>
                <p className="text-muted-foreground">
                  The Web UI uses same-origin <code className="font-mono">/ws</code> by default.
                  Set <code className="font-mono">NEXT_PUBLIC_WS_URL</code> only if you need a custom
                  monitoring WebSocket endpoint, then restart the Web UI.
                </p>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      )
    }

    if (transportMode === 'waiting') {
      return <Badge variant="secondary" className="text-xs">Waiting for run</Badge>
    }
    if (transportMode === 'polling') {
      return <Badge variant="outline" className="text-xs">Polling (degraded)</Badge>
    }
    switch (connectionState) {
      case 'open':
        return <Badge variant="default" className="text-xs">Connected</Badge>
      case 'connecting':
        return <Badge variant="secondary" className="text-xs">Connecting...</Badge>
      case 'closed':
        return (
          <div className="flex items-center gap-2">
            <Badge variant="destructive" className="text-xs">Disconnected</Badge>
            {wsTargetReady && (
              <Button size="sm" variant="outline" onClick={() => reconnect()}>
                Retry
              </Button>
            )}
          </div>
        )
      default:
        return <Badge variant="outline" className="text-xs">{connectionState}</Badge>
    }
  }

  return (
    <div 
      ref={containerRef}
      className={`h-full flex flex-col ${className} ${isFullscreen ? 'fixed inset-0 z-50 bg-background' : ''}`}
      style={{ height: isFullscreen ? '100vh' : height }}
    >
      {/* Header */}
      <Card className="rounded-b-none border-b-0">
        <div className="p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                {getStatusIcon()}
                <h2 className="text-lg font-semibold">
                  {pipeline?.name || `Pipeline ${pipelineId}`}
                </h2>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline">{pipelineStats.total} nodes</Badge>
                {pipelineStats.completed > 0 && (
                  <Badge variant="default">{pipelineStats.completed} completed</Badge>
                )}
                {pipelineStats.running > 0 && (
                  <Badge variant="secondary" className="animate-pulse">{pipelineStats.running} running</Badge>
                )}
                {pipelineStats.failed > 0 && (
                  <Badge variant="destructive">{pipelineStats.failed} failed</Badge>
                )}
                {pipelineStats.paused > 0 && (
                  <Badge variant="secondary">{pipelineStats.paused} paused</Badge>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              {getConnectionStatus()}
              <Separator orientation="vertical" className="h-6" />

              {/* View Controls */}
              <Button onClick={handleZoomIn} variant="outline" size="sm">
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button onClick={handleZoomOut} variant="outline" size="sm">
                <ZoomOut className="h-4 w-4" />
              </Button>
              <Button onClick={handleFitView} variant="outline" size="sm">
                <Maximize2 className="h-4 w-4" />
              </Button>
              
              <Separator orientation="vertical" className="h-6" />

              {/* Panel Controls */}
              <Button
                onClick={() => setShowTimelinePanel(!showTimelinePanel)}
                variant={showTimelinePanel ? "default" : "outline"}
                size="sm"
              >
                <Clock className="h-4 w-4 mr-2" />
                Timeline
              </Button>
              <Button
                onClick={() => setShowResourcePanel(!showResourcePanel)}
                variant={showResourcePanel ? "default" : "outline"}
                size="sm"
              >
                <Activity className="h-4 w-4 mr-2" />
                Resources
              </Button>

              <Separator orientation="vertical" className="h-6" />

              {/* Pipeline Controls */}
              {pipeline?.status === 'idle' && (
                <Button onClick={handleStartPipeline} disabled={loading} size="sm">
                  <Play className="h-4 w-4 mr-2" />
                  Start
                </Button>
              )}
              
              {pipeline?.status === 'running' && (
                <>
                  <Button onClick={handlePausePipeline} variant="outline" size="sm">
                    <Pause className="h-4 w-4 mr-2" />
                    Pause
                  </Button>
                  <Button onClick={handleCancelPipeline} variant="destructive" size="sm">
                    <Square className="h-4 w-4 mr-2" />
                    Cancel
                  </Button>
                </>
              )}
              
              {pipeline?.status === 'paused' && (
                <Button onClick={handleResumePipeline} size="sm">
                  <Play className="h-4 w-4 mr-2" />
                  Resume
                </Button>
              )}
              
              {(pipeline?.status === 'failed' || pipeline?.status === 'completed') && (
                <Button onClick={() => handleStartPipeline()} variant="outline" size="sm">
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Retry
                </Button>
              )}

              <Separator orientation="vertical" className="h-6" />

              {/* Export Controls */}
              <Button onClick={() => handleExport('png')} variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                PNG
              </Button>
              <Button onClick={() => handleExport('svg')} variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                SVG
              </Button>
              <Button onClick={() => handleExport('json')} variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                JSON
              </Button>

              <Separator orientation="vertical" className="h-6" />

              <Button onClick={toggleFullscreen} variant="outline" size="sm">
                {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          {/* Progress Bar */}
          {pipeline?.progress !== undefined && (
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-500 ${
                  pipeline.status === 'failed' ? 'bg-red-500' :
                  pipeline.status === 'completed' ? 'bg-green-500' :
                  'bg-blue-500'
                }`}
                style={{ width: `${pipeline.progress}%` }}
              />
            </div>
          )}
        </div>
      </Card>

      {/* Main Visualization Area */}
      <div className="flex-1 flex">
        {/* ReactFlow Canvas */}
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes}
            defaultEdgeOptions={defaultEdgeOptions}
            fitView
            fitViewOptions={fitViewOptions}
            className="bg-slate-50 dark:bg-slate-900"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              className="opacity-30"
            />
            <Controls showFitView={false} showZoom={false} />
            {showMinimap && (
              <MiniMap
                nodeStrokeColor={(n) => {
                  switch (n.data?.status) {
                    case 'running': return '#3b82f6'
                    case 'completed': return '#10b981'
                    case 'failed': return '#ef4444'
                    case 'paused': return '#f59e0b'
                    default: return '#94a3b8'
                  }
                }}
                nodeColor={(n) => {
                  switch (n.data?.type) {
                    case 'input': return '#3b82f6'
                    case 'process': return '#8b5cf6'
                    case 'analysis': return '#f97316'
                    case 'output': return '#10b981'
                    default: return '#64748b'
                  }
                }}
                nodeBorderRadius={8}
                className="border-2"
              />
            )}
          </ReactFlow>

          {/* Empty/Disconnected State Overlay */}
          {(!nodes?.length || nodes.length === 0) && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/60 dark:bg-black/40">
              <div className="text-center p-6 rounded-lg border bg-white dark:bg-gray-900">
                <h3 className="text-lg font-semibold mb-1">No nodes to display</h3>
                <p className="text-sm text-muted-foreground mb-3">
                  {connectionState === 'open'
                    ? 'Pipeline is idle or has no steps yet.'
                    : monitoringEnabled
                      ? 'Real-time connection is not available.'
                      : 'Monitoring is disabled. Configure WS URL to enable real-time updates.'}
                </p>
                {connectionState !== 'open' && monitoringEnabled && (
                  <Button onClick={() => reconnect()} size="sm">Reconnect</Button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Side Panels */}
        {(showTimelinePanel || showResourcePanel) && (
          <div className="flex flex-col border-l bg-background" style={{ width: '360px' }}>
            <Tabs defaultValue={showTimelinePanel ? "timeline" : "resources"} className="h-full flex flex-col">
              <TabsList className="mx-4 mt-4 grid w-auto grid-cols-2">
                <TabsTrigger value="timeline" disabled={!showTimelinePanel}>
                  <Clock className="h-4 w-4 mr-2" />
                  Timeline
                </TabsTrigger>
                <TabsTrigger value="resources" disabled={!showResourcePanel}>
                  <Activity className="h-4 w-4 mr-2" />
                  Resources
                </TabsTrigger>
              </TabsList>

              {showTimelinePanel && (
                <TabsContent value="timeline" className="flex-1 overflow-hidden">
                  <PipelineTimeline
                    events={pipeline?.timeline || []}
                    className="h-full rounded-none border-0"
                    searchable={true}
                    filterable={true}
                  />
                </TabsContent>
              )}

              {showResourcePanel && (
                <TabsContent value="resources" className="flex-1 overflow-hidden">
                  <ResourceMonitor
                    pipelineId={pipelineId}
                    nodes={pipeline?.nodes || {}}
                    className="h-full rounded-none border-0"
                  />
                </TabsContent>
              )}
            </Tabs>
          </div>
        )}
      </div>

      {/* Node Details Panel */}
      {selectedNode && (
        <NodeDetailsPanel
          node={selectedNode}
          execution={execution}
          onRetryNode={handleRetryNode}
          onClose={() => {
            setSelectedNode(null)
            setShowDetails(false)
          }}
          open={showDetails}
        />
      )}

      {/* Error Display */}
      {monitoringEnabled && monitoringError && (
        <div className="absolute bottom-4 right-4 p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300 text-sm max-w-md shadow-lg">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            <span className="font-medium">Pipeline Error</span>
          </div>
          <p className="mt-1">{monitoringError}</p>
        </div>
      )}
    </div>
  )
}

// Dagre layout function placeholder
function applyDagreLayout(nodes: Node[], edges: Edge[]) {
  // Simple horizontal layout for now
  const layoutedNodes = nodes.map((node, index) => ({
    ...node,
    position: {
      x: (index % 3) * 300,
      y: Math.floor(index / 3) * 150
    }
  }))
  
  return { nodes: layoutedNodes, edges }
}

export function PipelineVisualization(props: PipelineVisualizationProps) {
  return (
    <ReactFlowProvider>
      <PipelineVisualizationInner {...props} />
    </ReactFlowProvider>
  )
}

export default PipelineVisualization
