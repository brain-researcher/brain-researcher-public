'use client'

import { useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge } from '@/types/visualization'
import { Network, Maximize2, Download, RotateCcw } from 'lucide-react'

interface KnowledgeGraphProps {
  graph: KnowledgeGraph
  className?: string
  onNodeClick?: (node: KnowledgeGraphNode) => void
  onEdgeClick?: (edge: KnowledgeGraphEdge) => void
}

export function KnowledgeGraphVisualization({ 
  graph, 
  className, 
  onNodeClick, 
  onEdgeClick 
}: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedNode, setSelectedNode] = useState<KnowledgeGraphNode | null>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })

  // Simple force-directed layout simulation
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})

  useEffect(() => {
    if (!graph.nodes.length) return

    // Initialize positions if not set
    const newPositions: Record<string, { x: number; y: number }> = {}
    
    graph.nodes.forEach((node, index) => {
      if (node.position) {
        newPositions[node.id] = node.position
      } else {
        // Arrange in a circle initially
        const angle = (index / graph.nodes.length) * 2 * Math.PI
        const radius = Math.min(dimensions.width, dimensions.height) * 0.3
        newPositions[node.id] = {
          x: dimensions.width / 2 + radius * Math.cos(angle),
          y: dimensions.height / 2 + radius * Math.sin(angle)
        }
      }
    })

    setPositions(newPositions)
  }, [graph.nodes, dimensions])

  const getNodeColor = (type: string) => {
    switch (type) {
      case 'dataset': return '#3b82f6'
      case 'analysis': return '#10b981'
      case 'result': return '#f59e0b'
      case 'tool': return '#8b5cf6'
      case 'parameter': return '#ef4444'
      case 'citation': return '#6b7280'
      default: return '#6b7280'
    }
  }

  const getNodeSize = (node: KnowledgeGraphNode) => {
    return node.size || 20
  }

  const handleNodeClick = (node: KnowledgeGraphNode) => {
    setSelectedNode(node)
    onNodeClick?.(node)
  }

  const resetLayout = () => {
    const newPositions: Record<string, { x: number; y: number }> = {}
    
    graph.nodes.forEach((node, index) => {
      const angle = (index / graph.nodes.length) * 2 * Math.PI
      const radius = Math.min(dimensions.width, dimensions.height) * 0.3
      newPositions[node.id] = {
        x: dimensions.width / 2 + radius * Math.cos(angle),
        y: dimensions.height / 2 + radius * Math.sin(angle)
      }
    })

    setPositions(newPositions)
  }

  const exportGraph = () => {
    if (!svgRef.current) return
    
    const svgData = new XMLSerializer().serializeToString(svgRef.current)
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
    const svgUrl = URL.createObjectURL(svgBlob)
    
    const downloadLink = document.createElement('a')
    downloadLink.href = svgUrl
    downloadLink.download = `knowledge-graph-${Date.now()}.svg`
    document.body.appendChild(downloadLink)
    downloadLink.click()
    document.body.removeChild(downloadLink)
    URL.revokeObjectURL(svgUrl)
  }

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Network className="h-5 w-5" />
              {graph.metadata?.title || 'Knowledge Graph'}
            </CardTitle>
            <CardDescription>
              {graph.metadata?.description || 'Analysis workflow and dependencies'}
            </CardDescription>
          </div>
          
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={resetLayout}>
              <RotateCcw className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={exportGraph}>
              <Download className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="relative">
          <svg
            ref={svgRef}
            width={dimensions.width}
            height={dimensions.height}
            className="border rounded-lg bg-muted/20"
            viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
          >
            {/* Edges */}
            <g className="edges">
              {graph.edges.map((edge) => {
                const sourcePos = positions[edge.source]
                const targetPos = positions[edge.target]
                
                if (!sourcePos || !targetPos) return null
                
                return (
                  <g key={edge.id}>
                    <line
                      x1={sourcePos.x}
                      y1={sourcePos.y}
                      x2={targetPos.x}
                      y2={targetPos.y}
                      stroke="#6b7280"
                      strokeWidth={edge.weight || 1}
                      strokeDasharray={edge.type === 'cites' ? '5,5' : undefined}
                      className="cursor-pointer hover:stroke-primary transition-colors"
                      onClick={() => onEdgeClick?.(edge)}
                    />
                    
                    {/* Edge label */}
                    {edge.label && (
                      <text
                        x={(sourcePos.x + targetPos.x) / 2}
                        y={(sourcePos.y + targetPos.y) / 2}
                        textAnchor="middle"
                        className="text-xs fill-muted-foreground pointer-events-none"
                        dy="-5"
                      >
                        {edge.label}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>

            {/* Nodes */}
            <g className="nodes">
              {graph.nodes.map((node) => {
                const pos = positions[node.id]
                if (!pos) return null
                
                const size = getNodeSize(node)
                const color = getNodeColor(node.type)
                const isSelected = selectedNode?.id === node.id
                
                return (
                  <g key={node.id}>
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r={size}
                      fill={color}
                      stroke={isSelected ? '#000' : '#fff'}
                      strokeWidth={isSelected ? 3 : 2}
                      className="cursor-pointer hover:opacity-80 transition-opacity"
                      onClick={() => handleNodeClick(node)}
                    />
                    
                    <text
                      x={pos.x}
                      y={pos.y + size + 15}
                      textAnchor="middle"
                      className="text-xs fill-foreground pointer-events-none font-medium"
                    >
                      {node.label}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>

          {/* Node details panel */}
          {selectedNode && (
            <div className="absolute top-4 right-4 w-64 bg-background border rounded-lg p-4 shadow-lg">
              <div className="space-y-2">
                <div className="font-semibold">{selectedNode.label}</div>
                <div className="text-sm text-muted-foreground capitalize">
                  {selectedNode.type}
                </div>
                {selectedNode.description && (
                  <div className="text-sm">{selectedNode.description}</div>
                )}
                {selectedNode.metadata && (
                  <div className="text-xs space-y-1">
                    {Object.entries(selectedNode.metadata).map(([key, value]) => (
                      <div key={key} className="flex justify-between">
                        <span className="text-muted-foreground">{key}:</span>
                        <span>{String(value)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          {['dataset', 'analysis', 'result', 'tool', 'parameter', 'citation'].map((type) => (
            <div key={type} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: getNodeColor(type) }}
              />
              <span className="capitalize">{type}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}