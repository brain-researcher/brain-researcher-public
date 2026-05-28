"use client"

import { useEffect, useState } from 'react'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { KGPipeline } from '@/types/kg-responses'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FamilyChip } from '@/components/ui/family-chip'
import { ToolsBrowserDrawer } from './ToolsBrowserDrawer'
import { AlertCircle, RefreshCw, Search, Database } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'

export function PipelineCatalogTab() {
  const [pipelines, setPipelines] = useState<KGPipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPipeline, setSelectedPipeline] = useState<KGPipeline | null>(null)
  const [selectedOperation, setSelectedOperation] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const fetchPipelines = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await brainResearcherAPI.fetchKGPipelines()
      setPipelines(response.pipelines || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch pipelines')
      console.error('Error fetching pipelines:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPipelines()
  }, [])

  const handleViewTools = (pipeline: KGPipeline, operation: string) => {
    setSelectedPipeline(pipeline)
    setSelectedOperation(operation)
    setDrawerOpen(true)
  }

  const filteredPipelines = pipelines.filter(pipeline =>
    pipeline.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    pipeline.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    pipeline.ops.some(op => op.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  // Loading state
  if (loading) {
    return (
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <Card key={i} className="animate-pulse">
            <CardHeader>
              <div className="h-6 bg-gray-200 rounded w-3/4 mb-2" />
              <div className="h-4 bg-gray-100 rounded w-full" />
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="h-4 bg-gray-100 rounded w-full" />
                <div className="h-4 bg-gray-100 rounded w-2/3" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button
            onClick={fetchPipelines}
            variant="outline"
            size="sm"
            className="ml-4"
          >
            <RefreshCw className="h-4 w-4 mr-1" />
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  // Empty state
  if (filteredPipelines.length === 0 && !searchQuery) {
    return (
      <Card className="p-12 text-center">
        <Database className="h-16 w-16 mx-auto text-gray-400 mb-4" />
        <h3 className="text-lg font-semibold mb-2">No Pipelines Found</h3>
        <p className="text-gray-600 mb-4">
          No pipeline templates are currently available in the knowledge graph.
        </p>
        <Button onClick={fetchPipelines} variant="outline">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Search bar */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            type="text"
            placeholder="Search pipelines, operations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button onClick={fetchPipelines} variant="outline" size="sm">
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {/* Pipeline count */}
      <div className="text-sm text-gray-600">
        Showing {filteredPipelines.length} pipeline{filteredPipelines.length !== 1 ? 's' : ''}
      </div>

      {/* Pipeline grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {filteredPipelines.map(pipeline => (
          <Card key={pipeline.id} className="hover:shadow-lg transition-shadow">
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="truncate">{pipeline.name}</span>
                <Badge variant="outline" className="ml-2 shrink-0">
                  {pipeline.ops.length} ops
                </Badge>
              </CardTitle>
              {pipeline.description && (
                <CardDescription className="line-clamp-2">
                  {pipeline.description}
                </CardDescription>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Operations */}
              {pipeline.ops.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">Operations</h4>
                  <div className="flex flex-wrap gap-2">
                    {pipeline.ops.slice(0, 3).map(op => (
                      <Badge key={op} variant="secondary" className="cursor-pointer hover:bg-secondary/80">
                        {op}
                      </Badge>
                    ))}
                    {pipeline.ops.length > 3 && (
                      <Badge variant="outline">
                        +{pipeline.ops.length - 3} more
                      </Badge>
                    )}
                  </div>
                </div>
              )}

              {/* Preferred Families */}
              {pipeline.preferred_families.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">Preferred Families</h4>
                  <div className="flex flex-wrap gap-2">
                    {pipeline.preferred_families.slice(0, 3).map(family => (
                      <FamilyChip
                        key={family}
                        family={family}
                        isPreferred={true}
                      />
                    ))}
                    {pipeline.preferred_families.length > 3 && (
                      <Badge variant="outline">
                        +{pipeline.preferred_families.length - 3} more
                      </Badge>
                    )}
                  </div>
                </div>
              )}

              {/* Datasets */}
              {pipeline.datasets.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">Recommended Datasets</h4>
                  <div className="flex flex-wrap gap-2">
                    {pipeline.datasets.slice(0, 2).map(dataset => (
                      <Badge key={dataset} variant="outline">
                        {dataset}
                      </Badge>
                    ))}
                    {pipeline.datasets.length > 2 && (
                      <Badge variant="outline">
                        +{pipeline.datasets.length - 2} more
                      </Badge>
                    )}
                  </div>
                </div>
              )}

              {/* Modalities */}
              {pipeline.modalities && pipeline.modalities.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium mb-2">Modalities</h4>
                  <div className="flex flex-wrap gap-2">
                    {pipeline.modalities.map(modality => (
                      <Badge key={modality} variant="secondary">
                        {modality}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* View Tools Button */}
              {pipeline.ops.length > 0 && (
                <Button
                  onClick={() => handleViewTools(pipeline, pipeline.ops[0])}
                  variant="outline"
                  size="sm"
                  className="w-full"
                >
                  View Tools
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* No search results */}
      {filteredPipelines.length === 0 && searchQuery && (
        <Card className="p-8 text-center">
          <Search className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-semibold mb-2">No Results Found</h3>
          <p className="text-gray-600">
            No pipelines match your search query "{searchQuery}".
          </p>
        </Card>
      )}

      {/* Tools Browser Drawer */}
      <ToolsBrowserDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        pipeline={selectedPipeline}
        operation={selectedOperation || ''}
      />
    </div>
  )
}
