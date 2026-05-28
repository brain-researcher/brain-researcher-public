'use client'

import { useEffect, useRef, useState } from 'react'

interface GraphNode {
  data: {
    id: string
    label: string
    type: string
    degree?: number
    size?: number
  }
}

interface GraphEdge {
  data: {
    id: string
    source: string
    target: string
    type: string
    weight?: number
  }
}

interface CytoscapeGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onNodeClick?: (node: any) => void
}

export function CytoscapeGraph({ nodes, edges, onNodeClick }: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [isInitialized, setIsInitialized] = useState(false)

  useEffect(() => {
    // Only initialize if we have nodes and edges
    if (!containerRef.current || (nodes.length === 0 && edges.length === 0)) {
      return
    }

    let mounted = true

    const initCytoscape = async () => {
      try {
        // Dynamically import cytoscape to avoid SSR issues
        const cytoscape = (await import('cytoscape')).default

        if (!mounted || !containerRef.current) return

        // Clean up existing instance
        if (cyRef.current) {
          cyRef.current.destroy()
          cyRef.current = null
        }

        const elements = [
          ...nodes.map(n => ({ data: n.data })),
          ...edges.map(e => ({
            data: {
              ...e.data,
              id: e.data.id ?? `${e.data.source}-${e.data.target}`
            }
          }))
        ]

        const cy = cytoscape({
          container: containerRef.current,
          elements,
          style: [
            {
              selector: 'node',
              style: {
                'background-color': '#3b82f6',
                'label': 'data(label)',
                'color': '#1f2937',
                'text-valign': 'center',
                'text-halign': 'center',
                'width': 'mapData(size, 1, 20, 28, 52)',
                'height': 'mapData(size, 1, 20, 28, 52)',
                'font-size': 'mapData(size, 1, 20, 9, 14)',
                'border-width': 'mapData(size, 1, 20, 1.5, 3)',
                'border-color': '#1f2937'
              }
            },
            {
              selector: 'node[type = "collection"]',
              style: {
                'background-color': '#eab308'
              }
            },
            {
              selector: 'node[type = "concept"]',
              style: {
                'background-color': '#a855f7'
              }
            },
            {
              selector: 'node[type = "coordinate"]',
              style: {
                'background-color': '#06b6d4'
              }
            },
            {
              selector: 'node[type = "publication"]',
              style: {
                'background-color': '#10b981'
              }
            },
            {
              selector: 'node[type = "task"]',
              style: {
                'background-color': '#f97316'
              }
            },
            {
              selector: 'node[type = "region"]',
              style: {
                'background-color': '#3b82f6'
              }
            },
            {
              selector: 'edge',
              style: {
                'width': 'mapData(weight, 1, 50, 1.5, 6)',
                'line-color': '#cbd5e1',
                'target-arrow-color': '#cbd5e1',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'opacity': 'mapData(weight, 1, 50, 0.45, 0.9)' as any
              }
            },
            {
              selector: 'node[overlay]',
              style: {
                'border-width': 3,
                'border-color': '#f59e0b',
              }
            },
            {
              selector: 'edge[overlay]',
              style: {
                'line-color': '#f59e0b',
                'target-arrow-color': '#f59e0b',
                'line-style': 'dashed'
              }
            },
            {
              selector: ':selected',
              style: {
                'border-width': 3,
                'border-color': '#000'
              }
            }
          ],
          layout: {
            name: 'cose',
            animate: true,
            animationDuration: 500,
            fit: true,
            padding: 50,
            nodeRepulsion: 8000,
            idealEdgeLength: 100,
            edgeElasticity: 100,
            nestingFactor: 5,
            gravity: 80,
            numIter: 1000,
            initialTemp: 200,
            coolingFactor: 0.95,
            minTemp: 1.0
          },
          minZoom: 0.2,
          maxZoom: 3,
          wheelSensitivity: 0.2
        })

        // Add click handler
        if (onNodeClick) {
          cy.on('tap', 'node', (evt: any) => {
            const node = evt.target
            onNodeClick(node.data())
          })
        }

        cyRef.current = cy
        setIsInitialized(true)
        setError(null)
      } catch (err) {
        console.error('Failed to initialize Cytoscape:', err)
        setError('Failed to render graph visualization')
      }
    }

    initCytoscape()

    return () => {
      mounted = false
      if (cyRef.current) {
        try {
          cyRef.current.destroy()
        } catch (e) {
          console.error('Error destroying cytoscape:', e)
        }
        cyRef.current = null
      }
    }
  }, [nodes, edges, onNodeClick])

  if (error) {
    return (
      <div className="h-[600px] bg-gradient-to-br from-red-50 to-red-100 rounded-lg flex items-center justify-center">
        <div className="text-center text-red-600">
          <p className="font-medium">{error}</p>
          <p className="text-sm mt-1">Please try refreshing the page</p>
        </div>
      </div>
    )
  }

  if (nodes.length === 0 && edges.length === 0) {
    return (
      <div className="h-[600px] bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg flex items-center justify-center">
        <div className="text-center text-gray-500">
          <p>No graph data available</p>
          <p className="text-sm mt-1">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="h-[600px] w-full bg-white rounded-lg"
      style={{ minHeight: '600px' }}
    />
  )
}
