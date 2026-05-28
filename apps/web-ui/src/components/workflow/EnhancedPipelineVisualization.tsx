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
  MarkerType
} from 'reactflow'
import 'reactflow/dist/style.css'

import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Separator } from '@/components/ui/separator'
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Download,
  Maximize,
  Activity,
  Clock,
  Terminal,
  Eye,
  Settings,
  AlertTriangle,
  CheckCircle,
  Loader2,
  ZoomIn,
  ZoomOut
} from 'lucide-react'

import PipelineNode, { PipelineNodeData } from './PipelineNode'
import PipelineTimeline, { TimelineEvent } from './PipelineTimeline'
import { usePipelineMonitoring } from '@/hooks/use-pipeline-monitoring'

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

interface EnhancedPipelineVisualizationProps {
  pipelineId: string
  initialNodes?: Node<PipelineNodeData>[]
  initialEdges?: Edge[]
  onNodeSelect?: (node: Node<PipelineNodeData> | null) => void
  onExport?: (format: 'png' | 'json' | 'logs') => void
  onSnapshotChange?: (snapshot: { nodes: Node<PipelineNodeData>[]; edges: Edge[] }) => void
  showTimeline?: boolean
  showMinimap?: boolean
  autoLayout?: boolean
  className?: string
}

export function EnhancedPipelineVisualization({
  pipelineId,
  initialNodes = [],
  initialEdges = [],
  onNodeSelect,
  onExport,
  onSnapshotChange,
  showTimeline = true,
  showMinimap = true,
  autoLayout = false,
  className = ''
}: EnhancedPipelineVisualizationProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [selectedNode, setSelectedNode] = useState<Node<PipelineNodeData> | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null)
  const reactFlowWrapperRef = useRef<HTMLDivElement | null>(null)

  // Rehydrate canvas when new initial data is provided
  React.useEffect(() => {
    setNodes(initialNodes)
  }, [initialNodes, setNodes])

  React.useEffect(() => {
    setEdges(initialEdges)
  }, [initialEdges, setEdges])

  // Emit snapshot updates whenever the graph mutates so parents can persist state
  React.useEffect(() => {
    if (!onSnapshotChange) return
    onSnapshotChange({ nodes, edges })
  }, [nodes, edges, onSnapshotChange])

  // Allow external consumers (e.g., properties panel) to patch node data
  React.useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ nodeId?: string; data?: Partial<PipelineNodeData> }>).detail
      if (!detail?.nodeId || !detail.data) return

      let updatedNode: Node<PipelineNodeData> | null = null
      setNodes((prevNodes) =>
        prevNodes.map((node) => {
          if (node.id !== detail.nodeId) return node

          const nextData = {
            ...node.data,
            ...detail.data,
            resources: detail.data.resources
              ? { ...node.data?.resources, ...detail.data.resources }
              : node.data?.resources,
            parameters: detail.data.parameters
              ? { ...node.data?.parameters, ...detail.data.parameters }
              : node.data?.parameters,
          }

          const nextNode = {
            ...node,
            data: nextData,
          }
          updatedNode = nextNode
          return nextNode
        })
      )

      if (updatedNode) {
        setSelectedNode((prev) => (prev?.id === updatedNode?.id ? updatedNode : prev))
      }
    }

    window.addEventListener('pipeline:update-node', handler as EventListener)
    return () => window.removeEventListener('pipeline:update-node', handler as EventListener)
  }, [setNodes])

  // Drag and drop handlers
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      
      const type = event.dataTransfer.getData('application/reactflow')
      if (type !== 'tool') return
      
      const toolData = JSON.parse(event.dataTransfer.getData('tool'))
      const category = event.dataTransfer.getData('category') || toolData?.category || ''
      
      if (!reactFlowInstance) return
      // Use the ReactFlow wrapper bounds to compute proper coordinates
      const wrapperEl = reactFlowWrapperRef.current || (event.currentTarget as HTMLElement)
      const reactFlowBounds = wrapperEl.getBoundingClientRect()
      const position = reactFlowInstance.project({
        x: event.clientX - reactFlowBounds.left,
        y: event.clientY - reactFlowBounds.top,
      })
      
      const newNode: Node<PipelineNodeData> = {
        id: `node-${Date.now()}`,
        type: 'pipeline',
        position,
        data: {
          label: toolData.name,
          type: 'process' as const,
          tool: toolData,
          category,
          status: 'pending',
          progress: 0,
          metrics: {},
          inputs: toolData.inputs || [],
          outputs: toolData.outputs || []
        },
      }
      
      setNodes((nds) => nds.concat(newNode))
    },
    [reactFlowInstance, setNodes]
  )

  // Click-to-add fallback: listens for a custom event dispatched by ToolPalette
  React.useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool?: any }
      if (!detail?.tool || !reactFlowInstance) return

      const wrapperEl = reactFlowWrapperRef.current
      if (!wrapperEl) return

      const bounds = wrapperEl.getBoundingClientRect()
      const center = reactFlowInstance.project({
        x: (bounds.left + bounds.right) / 2 - bounds.left,
        y: (bounds.top + bounds.bottom) / 2 - bounds.top,
      })

      const newNode: Node<PipelineNodeData> = {
        id: `node-${Date.now()}`,
        type: 'pipeline',
        position: center,
        data: {
          label: detail.tool.name,
          type: 'process' as const,
          tool: detail.tool,
          category: detail.tool.category || '',
          status: 'pending',
          progress: 0,
          metrics: {},
          inputs: detail.tool.inputs || [],
          outputs: detail.tool.outputs || []
        },
      }
      setNodes((nds) => nds.concat(newNode))
    }

    window.addEventListener('pipeline:add-tool', handler as EventListener)
    return () => window.removeEventListener('pipeline:add-tool', handler as EventListener)
  }, [reactFlowInstance, setNodes])

  // Pipeline monitoring hook
  const {
    pipeline,
    execution,
    monitoringEnabled,
    transportMode,
    isConnected,
    connectionState,
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
    autoConnect: true 
  })

  // Update nodes from pipeline status
  React.useEffect(() => {
    if (pipeline?.nodes) {
      const updatedNodes = nodes.map(node => {
        const pipelineNode = pipeline.nodes[node.id]
        if (pipelineNode) {
          return {
            ...node,
            data: {
              ...node.data,
              ...pipelineNode
            }
          }
        }
        return node
      })
      setNodes(updatedNodes)
    }
  }, [pipeline?.nodes, setNodes])

  // Update edges animation based on execution status
  React.useEffect(() => {
    if (pipeline?.status === 'running') {
      const animatedEdges = edges.map(edge => ({
        ...edge,
        animated: true,
        style: {
          ...edge.style,
          stroke: '#3b82f6'
        }
      }))
      setEdges(animatedEdges)
    } else {
      const staticEdges = edges.map(edge => ({
        ...edge,
        animated: false,
        style: {
          ...edge.style,
          stroke: '#64748b'
        }
      }))
      setEdges(staticEdges)
    }
  }, [pipeline?.status])

  const onNodeClick = useCallback((event: React.MouseEvent, node: Node<PipelineNodeData>) => {
    setSelectedNode(node)
    setShowDetails(true)
    onNodeSelect?.(node)
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

  const handleExport = useCallback(async (format: 'png' | 'json' | 'logs') => {
    try {
      switch (format) {
        case 'png':
          const imageBlob = await exportPipelineImage()
          if (imageBlob) {
            const url = URL.createObjectURL(imageBlob)
            const link = document.createElement('a')
            link.download = `pipeline-${pipelineId}.png`
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
            edges: edges.map(e => ({ ...e, selected: false }))
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

  const pipelineStats = useMemo(() => {
    if (!pipeline) return null

    const nodeStates = Object.values(pipeline.nodes)
    return {
      total: nodeStates.length,
      pending: nodeStates.filter(n => n.status === 'pending').length,
      running: nodeStates.filter(n => n.status === 'running').length,
      completed: nodeStates.filter(n => n.status === 'completed').length,
      failed: nodeStates.filter(n => n.status === 'failed').length
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

    switch (transportMode) {
      case 'ws':
        return <Badge variant="default" className="text-xs">Connected</Badge>
      case 'polling':
        return <Badge variant="secondary" className="text-xs">Polling</Badge>
      case 'waiting':
        return <Badge variant="outline" className="text-xs">Waiting</Badge>
      case 'disconnected':
        return <Badge variant="destructive" className="text-xs">Disconnected</Badge>
      default:
        return <Badge variant="outline" className="text-xs">{connectionState}</Badge>
    }
  }

  return (
    <div className={`h-full flex flex-col ${className}`}>
      <ReactFlowProvider>
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
                {pipelineStats && (
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{pipelineStats.total} nodes</Badge>
                    {pipelineStats.completed > 0 && (
                      <Badge variant="default">{pipelineStats.completed} completed</Badge>
                    )}
                    {pipelineStats.running > 0 && (
                      <Badge variant="secondary">{pipelineStats.running} running</Badge>
                    )}
                    {pipelineStats.failed > 0 && (
                      <Badge variant="destructive">{pipelineStats.failed} failed</Badge>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                {getConnectionStatus()}
                <Separator orientation="vertical" className="h-6" />
                
                {/* Control buttons */}
                {pipeline?.status === 'idle' && (
                  <Button
                    onClick={handleStartPipeline}
                    disabled={loading}
                    size="sm"
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Start
                  </Button>
                )}
                
                {pipeline?.status === 'running' && (
                  <>
                    <Button
                      onClick={handlePausePipeline}
                      variant="outline"
                      size="sm"
                    >
                      <Pause className="h-4 w-4 mr-2" />
                      Pause
                    </Button>
                    <Button
                      onClick={handleCancelPipeline}
                      variant="destructive"
                      size="sm"
                    >
                      <Square className="h-4 w-4 mr-2" />
                      Cancel
                    </Button>
                  </>
                )}
                
                {pipeline?.status === 'paused' && (
                  <Button
                    onClick={handleResumePipeline}
                    size="sm"
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Resume
                  </Button>
                )}
                
                {(pipeline?.status === 'failed' || pipeline?.status === 'completed') && (
                  <Button
                    onClick={() => handleStartPipeline()}
                    variant="outline"
                    size="sm"
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Retry
                  </Button>
                )}

                <Separator orientation="vertical" className="h-6" />
                
                {/* Export buttons */}
                <Button
                  onClick={() => handleExport('png')}
                  variant="outline"
                  size="sm"
                >
                  <Download className="h-4 w-4 mr-2" />
                  Image
                </Button>
                <Button
                  onClick={() => handleExport('logs')}
                  variant="outline"
                  size="sm"
                  disabled={!execution?.logs?.length}
                >
                  <Terminal className="h-4 w-4 mr-2" />
                  Logs
                </Button>
              </div>
            </div>

            {/* Progress bar */}
            {pipeline?.progress !== undefined && (
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all duration-300 ${
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

        {/* Main visualization area */}
        <div className="flex-1 flex">
          {/* ReactFlow Canvas */}
          <div
            className="flex-1 relative"
            ref={reactFlowWrapperRef}
            data-testid="rf__wrapper"
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={onNodeClick}
              onInit={setReactFlowInstance}
              onDrop={onDrop}
              onDragOver={onDragOver}
              nodeTypes={nodeTypes}
              defaultEdgeOptions={defaultEdgeOptions}
              fitView
              className="bg-slate-50 dark:bg-slate-900"
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
              />
              <Controls />
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
                />
              )}
            </ReactFlow>
          </div>

          {/* Timeline Panel */}
          {showTimeline && pipeline?.timeline && (
            <div className="w-80 border-l bg-background">
              <PipelineTimeline 
                events={pipeline.timeline}
                className="h-full rounded-none border-0"
              />
            </div>
          )}
        </div>

        {/* Node Details Sheet */}
        <Sheet open={showDetails} onOpenChange={setShowDetails}>
          <SheetContent className="w-[500px] sm:w-[600px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>
                {selectedNode?.data.label || 'Node Details'}
              </SheetTitle>
            </SheetHeader>

            {selectedNode && (
              <Tabs value={activeTab} onValueChange={setActiveTab} className="mt-6">
                <TabsList className="grid w-full grid-cols-3">
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="logs">Logs</TabsTrigger>
                  <TabsTrigger value="outputs">Outputs</TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="space-y-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium">Type:</span>
                      <p className="capitalize">{selectedNode.data.type}</p>
                    </div>
                    <div>
                      <span className="font-medium">Status:</span>
                      <p className="capitalize">{selectedNode.data.status}</p>
                    </div>
                    {selectedNode.data.progress !== undefined && (
                      <div>
                        <span className="font-medium">Progress:</span>
                        <p>{selectedNode.data.progress}%</p>
                      </div>
                    )}
                    {selectedNode.data.duration && (
                      <div>
                        <span className="font-medium">Duration:</span>
                        <p>{Math.round(selectedNode.data.duration / 1000)}s</p>
                      </div>
                    )}
                  </div>

                  {selectedNode.data.resources && (
                    <div>
                      <span className="font-medium">Resource Usage:</span>
                      <div className="mt-2 space-y-2">
                        {selectedNode.data.resources.cpu !== undefined && (
                          <div className="flex justify-between">
                            <span>CPU:</span>
                            <span>{Math.round(selectedNode.data.resources.cpu)}%</span>
                          </div>
                        )}
                        {selectedNode.data.resources.memory !== undefined && (
                          <div className="flex justify-between">
                            <span>Memory:</span>
                            <span>{Math.round(selectedNode.data.resources.memory)}%</span>
                          </div>
                        )}
                        {selectedNode.data.resources.gpu !== undefined && (
                          <div className="flex justify-between">
                            <span>GPU:</span>
                            <span>{Math.round(selectedNode.data.resources.gpu)}%</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {selectedNode.data.parameters && (
                    <div>
                      <span className="font-medium">Parameters:</span>
                      <pre className="mt-2 text-xs bg-muted p-3 rounded overflow-x-auto">
                        {JSON.stringify(selectedNode.data.parameters, null, 2)}
                      </pre>
                    </div>
                  )}

                  {selectedNode.data.error && (
                    <div className="p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded">
                      <span className="font-medium text-red-700 dark:text-red-300">Error:</span>
                      <p className="mt-1 text-sm text-red-600 dark:text-red-400">
                        {selectedNode.data.error}
                      </p>
                      {selectedNode.data.status === 'failed' && (
                        <Button
                          onClick={() => handleRetryNode(selectedNode.id)}
                          variant="outline"
                          size="sm"
                          className="mt-2"
                        >
                          <RotateCcw className="h-4 w-4 mr-2" />
                          Retry Node
                        </Button>
                      )}
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="logs" className="space-y-2">
                  {selectedNode.data.logs ? (
                    selectedNode.data.logs.map((log, index) => (
                      <div
                        key={index}
                        className="p-2 bg-muted rounded text-xs font-mono"
                      >
                        {log}
                      </div>
                    ))
                  ) : (
                    <p className="text-muted-foreground text-sm">No logs available</p>
                  )}
                </TabsContent>

                <TabsContent value="outputs">
                  {selectedNode.data.outputs ? (
                    <pre className="text-xs bg-muted p-3 rounded overflow-x-auto">
                      {JSON.stringify(selectedNode.data.outputs, null, 2)}
                    </pre>
                  ) : (
                    <p className="text-muted-foreground text-sm">No outputs available</p>
                  )}
                </TabsContent>
              </Tabs>
            )}
          </SheetContent>
        </Sheet>
      </ReactFlowProvider>

      {monitoringEnabled && monitoringError && (
        <div className="p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm">
          Pipeline monitoring error: {monitoringError}
        </div>
      )}
    </div>
  )
}

export default EnhancedPipelineVisualization
