'use client'

import type { ElementType } from 'react'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import {
  BarChart3,
  Brain,
  CheckCircle2,
  Clock,
  Code2,
  Loader2,
  Network,
  Sparkles,
  Workflow,
} from 'lucide-react'

import type { WorkflowSummary } from '@/lib/api/workflows'
import { STAGE_LABELS } from '@/lib/api/workflows'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const COST_TIER_COLORS: Record<string, string> = {
  cheap: 'bg-green-100 text-green-800',
  moderate: 'bg-yellow-100 text-yellow-800',
  expensive: 'bg-orange-100 text-orange-800',
  very_expensive: 'bg-red-100 text-red-800',
}

const STAGE_ICONS: Record<string, ElementType> = {
  preprocessing: Brain,
  connectivity: Network,
  glm: BarChart3,
  decoding: Sparkles,
  dmri: Workflow,
  dwi: Workflow,
  eeg: Sparkles,
  meg: Sparkles,
  ieeg: Sparkles,
  encoding: Sparkles,
  pet: Brain,
  dataset: CheckCircle2,
}

function getWorkflowIcon(workflow: WorkflowSummary): ElementType {
  return STAGE_ICONS[workflow.stage] ?? Sparkles
}

function workflowHasRecipe(workflow: WorkflowSummary): boolean {
  if (workflow.execution_recipe_available === false) return false
  return Boolean(workflow.supported_recipe_targets?.length)
}

export default function LibraryPage() {
  const searchParams = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''
  const initialStage = searchParams.get('stage') ?? ''

  const [query, setQuery] = useState(initialQuery)
  const [stage, setStage] = useState(initialStage)

  const [catalogWorkflows, setCatalogWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [handoffOpen, setHandoffOpen] = useState(false)
  const [handoffPayload, setHandoffPayload] = useState<HandoffTemplatePayload | null>(null)

  useEffect(() => {
    let cancelled = false

    brainResearcherAPI.fetchWorkflowCatalog()
      .then((data) => {
        if (cancelled) return
        setCatalogWorkflows(data.workflows)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('Failed to fetch workflow catalog:', err)
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })

    return () => { cancelled = true }
  }, [])

  const stages = useMemo(() => {
    const unique = new Set<string>()
    for (const w of catalogWorkflows) unique.add(w.stage)
    return Array.from(unique).sort()
  }, [catalogWorkflows])

  const workflows = useMemo(() => {
    let filtered = catalogWorkflows
    if (stage) {
      filtered = filtered.filter((w) => w.stage === stage)
    }
    if (query) {
      const lowerQuery = query.toLowerCase()
      filtered = filtered.filter((w) => {
        const haystack = `${w.id} ${w.description} ${w.stage}`.toLowerCase()
        return haystack.includes(lowerQuery)
      })
    }
    return filtered
  }, [catalogWorkflows, query, stage])

  const updateUrl = (newQuery: string, newStage: string) => {
    const params = new URLSearchParams()
    if (newQuery) params.set('q', newQuery)
    if (newStage) params.set('stage', newStage)
    const url = `/library${params.toString() ? `?${params.toString()}` : ''}`
    window.history.replaceState({}, '', url)
  }

  const handleQueryChange = (value: string) => {
    setQuery(value)
    updateUrl(value, stage)
  }

  const handleStageChange = (value: string) => {
    const newStage = value === 'all' ? '' : value
    setStage(newStage)
    updateUrl(query, newStage)
  }

  const handleClear = () => {
    setQuery('')
    setStage('')
    updateUrl('', '')
  }

  const openHandoff = (workflow: WorkflowSummary) => {
    setHandoffPayload({
      kind: 'template',
      workflowId: workflow.id,
      workflowLabel: workflow.id,
      supportedTargets: workflow.supported_recipe_targets ?? null,
      unresolvedInputs: ['dataset_id'],
    })
    setHandoffOpen(true)
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Workflows</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {loading ? 'Loading workflows...' : `Browse ${catalogWorkflows.length} official workflows. Hand off the recipe to your coding agent, or open it in Studio for plan validation.`}
            </p>

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                placeholder="Search workflows…"
                aria-label="Search workflows"
                className="sm:max-w-md"
              />
              <Select value={stage || 'all'} onValueChange={handleStageChange}>
                <SelectTrigger className="w-48">
                  <SelectValue placeholder="All stages" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All stages</SelectItem>
                  {stages.map((s) => (
                    <SelectItem key={s} value={s}>
                      {STAGE_LABELS[s] || s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {(query || stage) && (
                <Button variant="ghost" onClick={handleClear}>
                  Clear
                </Button>
              )}
            </div>

            {query || stage ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Showing {workflows.length} result{workflows.length === 1 ? '' : 's'}
                {query ? ` for "${query}"` : ''}
                {stage ? ` in ${STAGE_LABELS[stage] || stage}` : ''}.
              </p>
            ) : null}
          </div>

          {loading && (
            <div className="text-center py-12">
              <Loader2 className="h-8 w-8 mx-auto mb-4 animate-spin text-primary" />
              <p className="text-muted-foreground">Loading workflows...</p>
            </div>
          )}

          {error && !loading && (
            <div className="text-center py-12 text-red-500">
              <p className="text-lg font-medium">Failed to load workflows</p>
              <p className="mt-1 text-sm">{error}</p>
              <Button
                variant="outline"
                className="mt-4"
                onClick={() => window.location.reload()}
              >
                Retry
              </Button>
            </div>
          )}

          {!loading && !error && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {workflows.map((workflow) => {
                const Icon = getWorkflowIcon(workflow)
                const recipeAvailable = workflowHasRecipe(workflow)
                const title = workflow.id
                  .replace(/^workflow_/, '')
                  .replace(/_/g, ' ')
                  .replace(/\b\w/g, (c) => c.toUpperCase())

                return (
                  <Card
                    key={workflow.id}
                    className="hover:border-slate-300 transition-colors"
                    data-testid={`library-workflow-card-${workflow.id}`}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <Icon className="h-5 w-5 text-slate-600 shrink-0" />
                            <Link
                              href={`/library/${encodeURIComponent(workflow.id)}`}
                              prefetch={false}
                              className="font-medium truncate hover:underline"
                              title={workflow.id}
                            >
                              {title}
                            </Link>
                          </div>
                          <div className="mt-2 text-sm text-muted-foreground line-clamp-2">
                            {workflow.description}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="text-xs">
                              {workflow.origin === 'official' ? 'Official ✓' : workflow.origin}
                            </Badge>
                            <Badge variant="outline" className="text-xs">
                              {STAGE_LABELS[workflow.stage] || workflow.stage}
                            </Badge>
                            {workflow.cost_tier && (
                              <Badge
                                className={`text-xs ${COST_TIER_COLORS[workflow.cost_tier] || ''}`}
                              >
                                {workflow.cost_tier}
                              </Badge>
                            )}
                            {workflow.est_runtime ? (
                              <Badge variant="secondary" className="text-xs">
                                <Clock className="h-3 w-3 mr-1" />
                                {workflow.est_runtime}
                              </Badge>
                            ) : null}
                            {workflow.lifecycle === 'draft' ? (
                              <Badge variant="outline" className="text-xs">Preview only</Badge>
                            ) : null}
                            {recipeAvailable ? (
                              <Badge className="text-xs bg-green-100 text-green-800">
                                Recipe ready
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="text-xs text-muted-foreground">
                                Recipe pending
                              </Badge>
                            )}
                            {workflow.supported_recipe_targets?.length ? (
                              <Badge variant="secondary" className="text-xs">
                                Targets: {workflow.supported_recipe_targets.join(', ')}
                              </Badge>
                            ) : null}
                          </div>
                          {workflow.modalities && workflow.modalities.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {workflow.modalities.map((mod) => (
                                <span
                                  key={mod}
                                  className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded"
                                >
                                  {mod}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>

                      <div className="mt-4 grid gap-2 sm:grid-cols-2">
                        <Button
                          className="w-full"
                          onClick={() => openHandoff(workflow)}
                          disabled={!recipeAvailable}
                        >
                          <Code2 className="mr-2 h-4 w-4" />
                          Hand off
                        </Button>
                        <Button asChild variant="outline">
                          <Link
                            href={`/library/${encodeURIComponent(workflow.id)}`}
                            prefetch={false}
                          >
                            View workflow
                          </Link>
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}

          {!loading && !error && workflows.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <Sparkles className="h-12 w-12 mx-auto mb-4 text-slate-400" />
              <p className="text-lg font-medium">No workflows found</p>
              <p className="mt-1 text-sm">
                Try adjusting your search or filter criteria.
              </p>
            </div>
          )}
        </div>
      </div>
      {handoffPayload ? (
        <HandoffModal
          open={handoffOpen}
          onClose={() => setHandoffOpen(false)}
          mode="template"
          payload={handoffPayload}
        />
      ) : null}
    </NavigationWrapper>
  )
}
