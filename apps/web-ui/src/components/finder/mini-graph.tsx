'use client'

import { useEffect, useRef } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface GraphNode {
  id: string
  type: string
  label: string
}

interface GraphEdge {
  src: string
  dst: string
  rel: string
  weight: number
}

interface Position {
  id: string
  x: number
  y: number
}

interface MiniGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  positions?: Position[]
  width?: number
  height?: number
}

export function MiniGraph({ 
  nodes, 
  edges, 
  positions,
  width = 500,
  height = 300 
}: MiniGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Set canvas size
    canvas.width = width
    canvas.height = height

    // Calculate positions if not provided
    const nodePositions = new Map<string, { x: number, y: number }>()
    
    if (positions) {
      // Use provided positions, scale to canvas
      const minX = Math.min(...positions.map(p => p.x))
      const maxX = Math.max(...positions.map(p => p.x))
      const minY = Math.min(...positions.map(p => p.y))
      const maxY = Math.max(...positions.map(p => p.y))
      
      const scaleX = (width - 100) / (maxX - minX || 1)
      const scaleY = (height - 100) / (maxY - minY || 1)
      
      positions.forEach(pos => {
        nodePositions.set(pos.id, {
          x: 50 + (pos.x - minX) * scaleX,
          y: 50 + (pos.y - minY) * scaleY
        })
      })
    } else {
      // Simple circular layout
      nodes.forEach((node, i) => {
        const angle = (2 * Math.PI * i) / nodes.length
        const radius = Math.min(width, height) * 0.3
        nodePositions.set(node.id, {
          x: width / 2 + radius * Math.cos(angle),
          y: height / 2 + radius * Math.sin(angle)
        })
      })
    }

    // Animation variables
    let frame = 0
    const maxFrames = 60

    const draw = () => {
      // Clear canvas
      ctx.clearRect(0, 0, width, height)
      
      // Set styles
      ctx.strokeStyle = '#e5e7eb'
      ctx.fillStyle = '#f9fafb'
      
      // Draw background grid
      ctx.lineWidth = 0.5
      for (let x = 0; x < width; x += 50) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, height)
        ctx.stroke()
      }
      for (let y = 0; y < height; y += 50) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(width, y)
        ctx.stroke()
      }

      // Animation progress
      const progress = Math.min(frame / maxFrames, 1)
      const easeProgress = 1 - Math.pow(1 - progress, 3) // Ease out cubic

      // Draw edges
      edges.forEach(edge => {
        const from = nodePositions.get(edge.src)
        const to = nodePositions.get(edge.dst)
        
        if (from && to) {
          ctx.beginPath()
          ctx.strokeStyle = `rgba(59, 130, 246, ${0.2 + edge.weight * 0.3})`
          ctx.lineWidth = 1 + edge.weight * 2
          
          // Animate edge drawing
          const currentX = from.x + (to.x - from.x) * easeProgress
          const currentY = from.y + (to.y - from.y) * easeProgress
          
          ctx.moveTo(from.x, from.y)
          ctx.lineTo(currentX, currentY)
          ctx.stroke()
          
          // Draw edge label at midpoint (after animation)
          if (progress >= 1) {
            const midX = (from.x + to.x) / 2
            const midY = (from.y + to.y) / 2
            ctx.font = '10px sans-serif'
            ctx.fillStyle = '#6b7280'
            ctx.fillText(edge.rel, midX - 20, midY - 5)
          }
        }
      })

      // Draw nodes
      nodes.forEach(node => {
        const pos = nodePositions.get(node.id)
        if (!pos) return

        // Node style based on type
        const colors: Record<string, { fill: string, stroke: string }> = {
          Dataset: { fill: '#3b82f6', stroke: '#2563eb' },
          Task: { fill: '#10b981', stroke: '#059669' },
          Construct: { fill: '#8b5cf6', stroke: '#7c3aed' },
          Region: { fill: '#f59e0b', stroke: '#d97706' },
          Publication: { fill: '#ef4444', stroke: '#dc2626' }
        }
        
        const nodeColor = colors[node.type] || { fill: '#6b7280', stroke: '#4b5563' }
        const nodeRadius = 8 + (node.type === 'Dataset' ? 4 : 0)
        
        // Animate node appearance
        const currentRadius = nodeRadius * easeProgress
        
        // Draw node circle
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, currentRadius, 0, 2 * Math.PI)
        ctx.fillStyle = nodeColor.fill
        ctx.fill()
        ctx.strokeStyle = nodeColor.stroke
        ctx.lineWidth = 2
        ctx.stroke()
        
        // Draw node label (after animation)
        if (progress >= 1) {
          ctx.font = '12px sans-serif'
          ctx.fillStyle = '#1f2937'
          const textWidth = ctx.measureText(node.label).width
          ctx.fillText(node.label, pos.x - textWidth / 2, pos.y + nodeRadius + 15)
        }
      })

      // Continue animation
      if (frame < maxFrames) {
        frame++
        animationRef.current = requestAnimationFrame(draw)
      }
    }

    // Start animation
    draw()

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [nodes, edges, positions, width, height])

  const downloadGraph = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    
    const link = document.createElement('a')
    link.download = 'knowledge-graph.png'
    link.href = canvas.toDataURL()
    link.click()
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <h4 className="font-medium">Knowledge Graph</h4>
        <Button
          variant="outline"
          size="sm"
          onClick={downloadGraph}
        >
          <Download className="h-4 w-4 mr-1" />
          Export
        </Button>
      </div>
      
      <div className="border rounded-lg bg-white p-2">
        <canvas
          ref={canvasRef}
          className="w-full"
          style={{ maxWidth: `${width}px`, height: `${height}px` }}
        />
      </div>
      
      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-blue-500" />
          <span>Dataset</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-green-500" />
          <span>Task</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-purple-500" />
          <span>Construct</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-orange-500" />
          <span>Region</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <span>Publication</span>
        </div>
      </div>
    </div>
  )
}