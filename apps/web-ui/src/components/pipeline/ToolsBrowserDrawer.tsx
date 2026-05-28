"use client"

import { useEffect, useState } from 'react'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { KGPipeline, KGTool } from '@/types/kg-responses'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { PromotedBadge } from '@/components/ui/promoted-badge'
import { FamilyChip } from '@/components/ui/family-chip'
import { Loader2, AlertCircle, Clock, Database } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'

interface ToolsBrowserDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  pipeline: KGPipeline | null
  operation: string
}

export function ToolsBrowserDrawer({
  open,
  onOpenChange,
  pipeline,
  operation
}: ToolsBrowserDrawerProps) {
  const ANY_FILTER = '__any__'
  const [tools, setTools] = useState<KGTool[]>([])
  const [groupedTools, setGroupedTools] = useState<Record<string, KGTool[]>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [domainFilter, setDomainFilter] = useState<string>('')
  const [functionFilter, setFunctionFilter] = useState<string>('')
  const [riskFilter, setRiskFilter] = useState<string>('')

  const fetchTools = async () => {
    if (!operation) return

    setLoading(true)
    setError(null)
    try {
      const exposures = showAdvanced
        ? ['pipeline', 'cli', 'advanced', 'internal']
        : ['pipeline', 'cli']

      const response = await brainResearcherAPI.fetchKGTools(
        operation,
        pipeline?.id,
        5, // Limit to 5 tools per family
        {
          exposures,
          domain: domainFilter || undefined,
          func: functionFilter || undefined,
          risk: riskFilter || undefined,
        }
      )

      setTools(response.tools || [])

      // Group tools by family
      const grouped: Record<string, KGTool[]> = {}
      response.tools.forEach(tool => {
        if (!grouped[tool.family]) {
          grouped[tool.family] = []
        }
        grouped[tool.family].push(tool)
      })
      setGroupedTools(grouped)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tools')
      console.error('Error fetching tools:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && operation) {
      fetchTools()
    }
  }, [open, operation, pipeline?.id, showAdvanced, domainFilter, functionFilter, riskFilter])

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'Unknown'
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:w-[540px] sm:max-w-[540px]">
        <SheetHeader>
          <SheetTitle>Tools for {operation}</SheetTitle>
          <SheetDescription>
            {pipeline
              ? `Available tools from the ${pipeline.name} pipeline`
              : 'Available tools for this operation'}
          </SheetDescription>
        </SheetHeader>

        {/* Filters */}
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Switch
                id="advanced-toggle"
                checked={showAdvanced}
                onCheckedChange={setShowAdvanced}
              />
              <Label htmlFor="advanced-toggle" className="text-sm">Show advanced / backend tools</Label>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground">Domain</Label>
              <Select
                value={domainFilter || ANY_FILTER}
                onValueChange={(value) => setDomainFilter(value === ANY_FILTER ? '' : value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Any" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_FILTER}>Any</SelectItem>
                  <SelectItem value="fmri">fMRI</SelectItem>
                  <SelectItem value="dmri">dMRI</SelectItem>
                  <SelectItem value="surface">Surface/SMRI</SelectItem>
                  <SelectItem value="eeg">EEG</SelectItem>
                  <SelectItem value="ieeg">iEEG</SelectItem>
                  <SelectItem value="kg">KG</SelectItem>
                  <SelectItem value="datasets">Datasets</SelectItem>
                  <SelectItem value="jobs">Jobs</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Function</Label>
              <Select
                value={functionFilter || ANY_FILTER}
                onValueChange={(value) => setFunctionFilter(value === ANY_FILTER ? '' : value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Any" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_FILTER}>Any</SelectItem>
                  <SelectItem value="preproc">Preproc</SelectItem>
                  <SelectItem value="glm">GLM</SelectItem>
                  <SelectItem value="connectivity">Connectivity</SelectItem>
                  <SelectItem value="qc">QC</SelectItem>
                  <SelectItem value="analysis">Analysis</SelectItem>
                  <SelectItem value="decoding">Decoding</SelectItem>
                  <SelectItem value="visualization">Viz</SelectItem>
                  <SelectItem value="report">Report</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Risk</Label>
              <Select
                value={riskFilter || ANY_FILTER}
                onValueChange={(value) => setRiskFilter(value === ANY_FILTER ? '' : value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Any" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_FILTER}>Any</SelectItem>
                  <SelectItem value="safe">Safe</SelectItem>
                  <SelectItem value="dangerous">Dangerous</SelectItem>
                  <SelectItem value="high_cost">High cost</SelectItem>
                  <SelectItem value="external_net">External net</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <ScrollArea className="h-[calc(100vh-11rem)] mt-6 pr-4">
          {/* Loading state */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-blue-600 mb-4" />
              <p className="text-sm text-gray-600">Loading tools...</p>
            </div>
          )}

          {/* Error state */}
          {error && !loading && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="flex items-center justify-between">
                <span>{error}</span>
                <Button
                  onClick={fetchTools}
                  variant="outline"
                  size="sm"
                  className="ml-4"
                >
                  Retry
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {/* Empty state */}
          {!loading && !error && tools.length === 0 && (
            <Card className="p-8 text-center">
              <Database className="h-12 w-12 mx-auto text-gray-400 mb-4" />
              <h3 className="text-lg font-semibold mb-2">No Tools Found</h3>
              <p className="text-gray-600 text-sm">
                No tools are available for this operation.
              </p>
            </Card>
          )}

          {/* Tools grouped by family */}
          {!loading && !error && Object.keys(groupedTools).length > 0 && (
            <div className="space-y-6">
              {Object.entries(groupedTools).map(([family, familyTools]) => (
                <div key={family} className="space-y-3">
                  {/* Family header */}
                  <div className="flex items-center gap-2 border-b pb-2">
                    <FamilyChip
                      family={family}
                      count={familyTools.length}
                      isPreferred={pipeline?.preferred_families.includes(family)}
                    />
                    {familyTools[0].kg_tool_count !== undefined && (
                      <Badge variant="outline" className="text-xs">
                        {familyTools[0].kg_tool_count} in KG
                      </Badge>
                    )}
                  </div>

                  {/* Tools in this family */}
                  {familyTools.map(tool => (
                    <Card key={tool.id} className="hover:shadow-md transition-shadow">
                      <CardHeader className="pb-3">
                        <div className="flex items-start justify-between gap-2">
                          <CardTitle className="text-base flex items-center gap-2">
                            {tool.name}
                            {tool.is_promoted && <PromotedBadge showIcon={true} />}
                          </CardTitle>
                          {tool.version && (
                            <Badge variant="outline" className="shrink-0">
                              v{tool.version}
                            </Badge>
                          )}
                        </div>
                        {tool.description && (
                          <CardDescription className="text-sm line-clamp-2">
                            {tool.description}
                          </CardDescription>
                        )}
                      </CardHeader>
                      <CardContent className="space-y-2 pt-0">
                        {/* Runtime estimate */}
                        {tool.runtime_estimate_seconds !== undefined && (
                          <div className="flex items-center gap-2 text-sm text-gray-600">
                            <Clock className="h-4 w-4" />
                            <span>Est. runtime: {formatDuration(tool.runtime_estimate_seconds)}</span>
                          </div>
                        )}

                        {/* Tool metadata */}
                        {tool.metadata && Object.keys(tool.metadata).length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {Object.entries(tool.metadata).slice(0, 3).map(([key, value]) => (
                              <Badge key={key} variant="secondary" className="text-xs">
                                {key}: {String(value)}
                              </Badge>
                            ))}
                          </div>
                        )}

                        {/* Parameters preview */}
                        {tool.parameters && Object.keys(tool.parameters).length > 0 && (
                          <div className="text-xs text-gray-500 mt-2">
                            {Object.keys(tool.parameters).length} parameter
                            {Object.keys(tool.parameters).length !== 1 ? 's' : ''}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* Summary */}
          {!loading && !error && tools.length > 0 && (
            <div className="mt-6 p-4 bg-gray-50 rounded-lg">
              <h4 className="text-sm font-medium mb-2">Summary</h4>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-600">Total Tools:</span>
                  <span className="font-semibold ml-2">{tools.length}</span>
                </div>
                <div>
                  <span className="text-gray-600">Families:</span>
                  <span className="font-semibold ml-2">{Object.keys(groupedTools).length}</span>
                </div>
                <div>
                  <span className="text-gray-600">Promoted:</span>
                  <span className="font-semibold ml-2">
                    {tools.filter(t => t.is_promoted).length}
                  </span>
                </div>
                <div>
                  <span className="text-gray-600">Operation:</span>
                  <span className="font-semibold ml-2 truncate">{operation}</span>
                </div>
              </div>
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}
