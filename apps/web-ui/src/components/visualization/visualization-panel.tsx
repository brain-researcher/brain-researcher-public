'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { KnowledgeGraphVisualization } from './knowledge-graph'
import { BrainMapVisualization } from './brain-map'
import { KnowledgeGraph, BrainMapData, VisualizationConfig } from '@/types/visualization'
import { Network, Brain, Settings, Maximize2 } from 'lucide-react'

interface VisualizationPanelProps {
  knowledgeGraph?: KnowledgeGraph
  brainMaps?: BrainMapData[]
  config?: VisualizationConfig
  className?: string
}

export function VisualizationPanel({ 
  knowledgeGraph, 
  brainMaps = [], 
  config,
  className 
}: VisualizationPanelProps) {
  const [activeTab, setActiveTab] = useState<'knowledge-graph' | 'brain-maps'>('brain-maps')
  const [selectedBrainMap, setSelectedBrainMap] = useState(0)

  const hasKnowledgeGraph = knowledgeGraph && knowledgeGraph.nodes.length > 0
  const hasBrainMaps = brainMaps.length > 0
  const topTabColumnsClass =
    hasBrainMaps && hasKnowledgeGraph ? 'grid-cols-2' : 'grid-cols-1'

  if (!hasKnowledgeGraph && !hasBrainMaps) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center h-64 text-muted-foreground">
          <div className="text-center space-y-2">
            <Brain className="h-12 w-12 mx-auto opacity-50" />
            <p>No visualizations available</p>
            <p className="text-sm">Run an analysis to see results</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className={className}>
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as any)}>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <TabsList
            className={`grid h-auto w-full ${topTabColumnsClass} sm:inline-flex sm:h-9 sm:w-auto`}
          >
            {hasBrainMaps && (
              <TabsTrigger
                value="brain-maps"
                className="min-w-0 gap-2 px-2 sm:px-3"
              >
                <Brain className="h-4 w-4" />
                Brain Maps ({brainMaps.length})
              </TabsTrigger>
            )}
            {hasKnowledgeGraph && (
              <TabsTrigger
                value="knowledge-graph"
                className="min-w-0 gap-2 px-2 sm:px-3"
              >
                <Network className="h-4 w-4" />
                Knowledge Graph
              </TabsTrigger>
            )}
          </TabsList>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm">
              <Settings className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm">
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {hasBrainMaps && (
          <TabsContent value="brain-maps" className="space-y-4">
            {brainMaps.length > 1 && (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <span className="text-sm font-medium">Brain Map:</span>
                <div className="flex flex-wrap gap-1">
                  {brainMaps.map((map, index) => (
                    <Button
                      key={index}
                      variant={selectedBrainMap === index ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setSelectedBrainMap(index)}
                    >
                      {map.name}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            
            <BrainMapVisualization 
              brainMap={brainMaps[selectedBrainMap]}
              onPeakClick={(peak) => {
                console.log('Peak clicked:', peak)
                // Could trigger navigation to coordinates or show details
              }}
            />
          </TabsContent>
        )}

        {hasKnowledgeGraph && (
          <TabsContent value="knowledge-graph">
            <KnowledgeGraphVisualization 
              graph={knowledgeGraph}
              onNodeClick={(node) => {
                console.log('Node clicked:', node)
                // Could trigger navigation or show details
              }}
              onEdgeClick={(edge) => {
                console.log('Edge clicked:', edge)
                // Could show relationship details
              }}
            />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
