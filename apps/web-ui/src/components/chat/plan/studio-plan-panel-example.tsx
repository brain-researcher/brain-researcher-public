'use client'

import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  FileBarChart2,
  FileText,
  Play,
  Sparkles,
  Table2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import {
  DEFAULT_STUDIO_PLAN_EXAMPLE,
  type StudioNotebookArtifact,
  type StudioNotebookExampleData,
  type StudioNotebookStep,
} from './studio-plan-example-data'

type StudioPlanPanelExampleProps = {
  example?: StudioNotebookExampleData
}

const STATUS_BADGE: Record<StudioNotebookExampleData['checkpoint']['status'], { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive' }> = {
  ready: { label: 'Ready', variant: 'default' },
  warning: { label: 'Warnings', variant: 'outline' },
  blocked: { label: 'Blocked', variant: 'destructive' },
  running: { label: 'Running', variant: 'secondary' },
}

function NotebookCell({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string
  title: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {eyebrow}
        </div>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">{children}</CardContent>
    </Card>
  )
}

function StepStatusBadge({ status }: { status: StudioNotebookStep['status'] }) {
  if (status === 'done') {
    return (
      <Badge variant="default" className="gap-1">
        <CheckCircle2 className="h-3 w-3" />
        Complete
      </Badge>
    )
  }
  if (status === 'running') {
    return (
      <Badge variant="secondary" className="gap-1">
        <Play className="h-3 w-3" />
        Running
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1">
      <AlertCircle className="h-3 w-3" />
      Waiting
    </Badge>
  )
}

function ArtifactKindIcon({ kind }: { kind: StudioNotebookArtifact['kind'] }) {
  if (kind === 'chart') return <FileBarChart2 className="h-4 w-4" />
  if (kind === 'table') return <Table2 className="h-4 w-4" />
  return <FileText className="h-4 w-4" />
}

function InspectorPreview({ artifact }: { artifact: StudioNotebookArtifact }) {
  if (artifact.kind === 'chart') {
    return (
      <div className="space-y-3 rounded-lg border bg-slate-950 p-4 text-slate-100">
        <div className="text-xs uppercase tracking-wide text-slate-400">Chart preview</div>
        <div className="flex h-40 items-end gap-3">
          {artifact.previewBars?.map((bar) => (
            <div key={bar.label} className="flex flex-1 flex-col items-center gap-2">
              <div
                className="w-full rounded-t-md bg-cyan-400/80"
                style={{ height: `${Math.max(16, Math.round(bar.value * 100))}%` }}
              />
              <div className="text-[11px] text-slate-300">{bar.label}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (artifact.kind === 'table') {
    return (
      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[1.2fr,0.8fr,0.8fr] border-b bg-muted/40 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <div>Region</div>
          <div>Effect</div>
          <div>q-value</div>
        </div>
        <div className="divide-y">
          {artifact.previewRows?.map((row) => (
            <div key={row.label} className="grid grid-cols-[1.2fr,0.8fr,0.8fr] px-3 py-2 text-sm">
              <div>{row.label}</div>
              <div>{row.value}</div>
              <div>{row.meta}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-muted/30 p-4 font-mono text-xs leading-6 text-foreground">
      {artifact.previewLines?.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  )
}

function ArtifactInspector({
  artifact,
  artifacts,
  activeArtifactId,
  onSelect,
}: {
  artifact: StudioNotebookArtifact
  artifacts: StudioNotebookArtifact[]
  activeArtifactId: string
  onSelect: (artifactId: string) => void
}) {
  return (
    <div className="space-y-4 lg:sticky lg:top-6">
      <Card className="border-dashed border-sky-300 bg-sky-50/70">
        <CardContent className="p-4">
          <div className="text-sm font-medium text-sky-950">Focused inspector</div>
          <div className="mt-1 text-sm text-sky-800">
            The right rail stays dedicated to the currently selected artifact or visualization.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Inspector
              </div>
              <CardTitle className="mt-1 text-base">{artifact.title}</CardTitle>
            </div>
            <Badge variant="outline" className="gap-1 capitalize">
              <ArtifactKindIcon kind={artifact.kind} />
              {artifact.kind}
            </Badge>
          </div>
          <div className="text-sm text-muted-foreground">{artifact.summary}</div>
        </CardHeader>
        <CardContent className="space-y-4 pt-0">
          <InspectorPreview artifact={artifact} />

          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              What the agent surfaced
            </div>
            <ul className="space-y-2 text-sm text-muted-foreground">
              {artifact.insights.map((insight) => (
                <li key={insight} className="flex items-start gap-2">
                  <span className="mt-1 h-1.5 w-1.5 rounded-full bg-sky-500" />
                  <span>{insight}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Other open artifacts
            </div>
            <div className="flex flex-wrap gap-2">
              {artifacts.map((item) => (
                <Button
                  key={item.id}
                  type="button"
                  variant={item.id === activeArtifactId ? 'default' : 'outline'}
                  size="sm"
                  className="gap-2"
                  onClick={() => onSelect(item.id)}
                >
                  <ArtifactKindIcon kind={item.kind} />
                  {item.shortLabel}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export function StudioPlanPanelExample({
  example = DEFAULT_STUDIO_PLAN_EXAMPLE,
}: StudioPlanPanelExampleProps) {
  const [activeArtifactId, setActiveArtifactId] = useState(example.defaultArtifactId)

  const activeArtifact = useMemo(
    () => example.artifacts.find((artifact) => artifact.id === activeArtifactId) ?? example.artifacts[0],
    [activeArtifactId, example.artifacts],
  )

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.95fr)]">
      <div className="space-y-4">
        <Card className="border-dashed border-sky-300 bg-sky-50/70">
          <CardContent className="p-4">
            <div className="text-sm font-medium text-sky-950">Notebook-style Studio preview</div>
            <div className="mt-1 text-sm text-sky-800">
              Main execution stays in the notebook stream. The right rail is only for focused viewing.
            </div>
          </CardContent>
        </Card>

        <ScrollArea className="h-[min(72vh,960px)] rounded-xl border bg-muted/10">
          <div className="space-y-4 p-4">
            <NotebookCell eyebrow="User request" title="Natural-language intent drives the run">
              <div className="rounded-lg border bg-background p-4 text-sm leading-7 text-foreground">
                {example.userPrompt}
              </div>
            </NotebookCell>

            <NotebookCell eyebrow="Agent plan" title="The agent translates chat into an executable workflow">
              <div className="space-y-3 text-sm text-muted-foreground">
                <div className="flex items-start gap-3 rounded-lg border bg-background p-4 text-foreground">
                  <Bot className="mt-0.5 h-4 w-4 text-sky-600" />
                  <div>
                    <div>{example.agentPlan.summary}</div>
                    <ul className="mt-3 space-y-2">
                      {example.agentPlan.bullets.map((bullet) => (
                        <li key={bullet} className="flex items-start gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-sky-500" />
                          <span>{bullet}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </NotebookCell>

            <NotebookCell eyebrow="Plan checkpoint" title="Plan stays a compact approval cell">
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">{example.checkpoint.intentTitle}</div>
                    <div className="mt-1 text-sm text-muted-foreground">{example.checkpoint.intentSummary}</div>
                  </div>
                  <Badge variant={STATUS_BADGE[example.checkpoint.status].variant}>
                    {STATUS_BADGE[example.checkpoint.status].label}
                  </Badge>
                </div>

                <div className="space-y-3 rounded-lg border bg-background p-4">
                  {example.checkpoint.summaryRows.map((row) => (
                    <div key={row.id} className="flex items-start justify-between gap-3 border-b pb-3 last:border-b-0 last:pb-0">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {row.label}
                        </div>
                        <div className="mt-1 text-sm font-medium text-foreground">{row.value}</div>
                        {row.detail ? <div className="mt-1 text-sm text-muted-foreground">{row.detail}</div> : null}
                      </div>
                      {row.status ? (
                        <Badge
                          variant={
                            row.status === 'passed'
                              ? 'default'
                              : row.status === 'blocked'
                                ? 'destructive'
                                : row.status === 'warning'
                                  ? 'outline'
                                  : 'secondary'
                          }
                        >
                          {row.status === 'passed'
                            ? 'Ready'
                            : row.status === 'blocked'
                              ? 'Blocked'
                              : row.status === 'warning'
                                ? 'Warning'
                                : 'Info'}
                        </Badge>
                      ) : null}
                    </div>
                  ))}
                </div>

                <div className="space-y-3 rounded-lg border bg-amber-50 p-4">
                  <div className="text-sm font-medium text-foreground">Needs attention</div>
                  {example.checkpoint.alerts.map((alert) => (
                    <div key={alert.id} className="flex items-start gap-3 text-sm">
                      <AlertCircle className={cn('mt-0.5 h-4 w-4', alert.severity === 'blocked' ? 'text-destructive' : 'text-amber-700')} />
                      <div>
                        <div className="font-medium text-foreground">{alert.label}</div>
                        <div className="mt-1 text-muted-foreground">{alert.message}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock3 className="h-4 w-4" />
                    Estimated runtime: {example.checkpoint.runtime}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="button" disabled={!example.checkpoint.canRun}>
                      {example.checkpoint.primaryLabel}
                    </Button>
                    <Button type="button" variant="outline">
                      {example.checkpoint.secondaryLabel}
                    </Button>
                  </div>
                </div>
              </div>
            </NotebookCell>

            <NotebookCell eyebrow="Execution trace" title="Step progress belongs in the notebook stream">
              <div className="space-y-3">
                {example.steps.map((step) => (
                  <div key={step.id} className="flex items-start justify-between gap-3 rounded-lg border bg-background p-4">
                    <div>
                      <div className="text-sm font-medium text-foreground">{step.title}</div>
                      <div className="mt-1 text-sm text-muted-foreground">{step.detail}</div>
                    </div>
                    <StepStatusBadge status={step.status} />
                  </div>
                ))}
              </div>
            </NotebookCell>

            <NotebookCell eyebrow="Results" title="Artifacts appear inline and open in the inspector">
              <div className="space-y-3">
                <div className="text-sm text-muted-foreground">{example.resultsSummary}</div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {example.artifacts.map((artifact) => (
                    <button
                      key={artifact.id}
                      type="button"
                      className={cn(
                        'rounded-xl border bg-background p-4 text-left transition-colors hover:border-sky-400 hover:bg-sky-50/40',
                        artifact.id === activeArtifactId && 'border-sky-500 bg-sky-50/60',
                      )}
                      onClick={() => setActiveArtifactId(artifact.id)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                            <ArtifactKindIcon kind={artifact.kind} />
                            {artifact.title}
                          </div>
                          <div className="mt-1 text-sm text-muted-foreground">{artifact.summary}</div>
                        </div>
                        {artifact.id === activeArtifactId ? <Badge variant="default">Open</Badge> : null}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </NotebookCell>

            <NotebookCell eyebrow="Follow-up" title="Edits return to chat, not to a side form">
              <div className="space-y-3 rounded-lg border bg-background p-4">
                <div className="text-sm text-muted-foreground">{example.followupHint}</div>
                <div className="rounded-lg border bg-muted/30 p-3 text-sm text-foreground">
                  Increase the font size on the QC plot, switch to Schaefer-200, and rerun with global signal regression.
                </div>
                <div className="flex items-center gap-2 text-sm text-sky-700">
                  <Sparkles className="h-4 w-4" />
                  The agent would treat this as the next notebook turn and update the checkpoint cell.
                </div>
              </div>
            </NotebookCell>
          </div>
        </ScrollArea>
      </div>

      <ArtifactInspector
        artifact={activeArtifact}
        artifacts={example.artifacts}
        activeArtifactId={activeArtifactId}
        onSelect={setActiveArtifactId}
      />
    </div>
  )
}
