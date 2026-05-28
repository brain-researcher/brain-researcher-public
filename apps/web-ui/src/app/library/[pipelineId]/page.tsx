import Link from 'next/link'
import { notFound } from 'next/navigation'

import { STAGE_LABELS } from '@/lib/api/workflows'
import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LibraryWorkflowRunner } from '@/components/workflow/LibraryWorkflowRunner'
import { WorkflowDetailHandoffActions } from '@/components/workflow/WorkflowDetailHandoffActions'

type LibraryWorkflowDetailPageProps = {
  params: { pipelineId: string }
  searchParams?: Record<string, string | string[] | undefined>
}

function normalizeQuery(raw: string | string[] | undefined): string {
  if (Array.isArray(raw)) return raw[0]?.trim() ?? ''
  return typeof raw === 'string' ? raw.trim() : ''
}

function formatWorkflowTitle(id: string): string {
  return id
    .replace(/^workflow_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function LibraryWorkflowDetailPage({
  params,
  searchParams,
}: LibraryWorkflowDetailPageProps) {
  const pipelineId = typeof params.pipelineId === 'string' ? params.pipelineId.trim() : ''
  if (!pipelineId) notFound()

  const { workflow } = getWorkflowById(pipelineId)
  if (!workflow) {
    return (
      <NavigationWrapper>
        <div className="min-h-screen bg-gray-50">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
            <Alert>
              <AlertTitle>Workflow not found</AlertTitle>
              <AlertDescription>
                No workflow with id <span className="font-mono">{pipelineId}</span>.
              </AlertDescription>
            </Alert>
            <Button asChild variant="outline">
              <Link href="/library" prefetch={false}>
                Back to Workflows
              </Link>
            </Button>
          </div>
        </div>
      </NavigationWrapper>
    )
  }

  const title = formatWorkflowTitle(workflow.id)
  const primaryTool = workflow.runtime?.steps?.[0]?.tool ?? '—'
  const stageLabel = STAGE_LABELS[workflow.stage] || workflow.stage || 'Other'
  const workflowSteps = workflow.runtime?.steps ?? []
  const recipeAvailable =
    workflow.execution_recipe_available !== false && Boolean(workflow.supported_recipe_targets?.length)
  const requestedTab = normalizeQuery(searchParams?.tab).toLowerCase()
  const datasetId = normalizeQuery(searchParams?.datasetId || searchParams?.dataset_id)
  const datasetVersion = normalizeQuery(
    searchParams?.datasetVersion || searchParams?.dataset_version,
  )
  const initialTab = ['overview', 'pipeline', 'parameters', 'versions'].includes(requestedTab)
    ? requestedTab
    : 'overview'

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50" data-testid="library-workflow-detail">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">
                <Link href="/library" prefetch={false} className="hover:underline">
                  Workflows
                </Link>{' '}
                <span className="text-slate-300">/</span>{' '}
                <span className="font-mono text-muted-foreground">{workflow.id}</span>
              </div>
              <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
              <p className="text-sm text-muted-foreground">{workflow.description}</p>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <Badge variant="outline" className="text-xs">
                  {workflow.origin === 'official' ? 'Official ✓' : workflow.origin || 'catalog'}
                </Badge>
                <Badge variant="secondary" className="text-xs">
                  {stageLabel}
                </Badge>
                {workflow.est_runtime ? (
                  <Badge variant="secondary" className="text-xs">
                    {workflow.est_runtime}
                  </Badge>
                ) : null}
              </div>
            </div>

            <WorkflowDetailHandoffActions
              workflowId={workflow.id}
              workflowLabel={workflow.id}
              datasetId={datasetId}
              datasetVersion={datasetVersion}
              supportedTargets={workflow.supported_recipe_targets ?? null}
              recipeAvailable={recipeAvailable}
            />
          </div>

          <Tabs defaultValue={initialTab} className="w-full">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
              <TabsTrigger value="parameters">Parameters</TabsTrigger>
              <TabsTrigger value="versions">Versions</TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="text-sm font-medium">What it does</div>
                  <div className="text-sm text-muted-foreground">{workflow.description}</div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-sm">
                    <div className="rounded-md border bg-background p-3">
                      <div className="text-xs text-muted-foreground">Modalities</div>
                      <div className="mt-1">{workflow.modalities.join(', ') || '—'}</div>
                    </div>
                    <div className="rounded-md border bg-background p-3">
                      <div className="text-xs text-muted-foreground">Primary tool</div>
                      <div className="mt-1 font-mono text-xs">{primaryTool}</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="pipeline">
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="text-sm font-medium">Steps</div>
                  {workflowSteps.length > 0 ? (
                    <div className="space-y-2">
                      {workflowSteps.map((step, idx) => (
                        <div key={`${step.id}-${idx}`} className="rounded-md border bg-background p-3">
                          <div className="text-sm font-medium">Step {idx + 1}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Tool: <span className="font-mono">{step.tool}</span>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Step id: <span className="font-mono">{step.id}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-md border bg-background p-3 text-xs text-muted-foreground">
                      No runtime step metadata defined for this workflow.
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="parameters">
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="text-sm font-medium">Prepare for Studio</div>
                  <LibraryWorkflowRunner
                    workflow={workflow}
                    datasetId={datasetId}
                    datasetVersion={datasetVersion}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="versions">
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="text-sm font-medium">Versions</div>
                  <div className="text-sm text-muted-foreground">
                    Versioning metadata is not wired yet. v1.2 defaults to the built-in template version.
                  </div>
                  <div className="rounded-md border bg-background p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">Default</div>
                      <Badge variant="secondary">Current</Badge>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      Template id: <span className="font-mono">{workflow.id}</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </NavigationWrapper>
  )
}
