'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

type ReplayStep = {
  step_id: string
  stage: string
  title: string
  status: 'completed' | 'running' | 'failed' | 'pending'
  tool: string | null
  tool_calls: string[]
  prompt_text: string
  response_text: string
  artifact_refs: string[]
  started_at: number | null
  finished_at: number | null
  duration_ms: number | null
  narrative?: {
    title?: string | null
    order?: number | null
  } | null
  narrative_title?: string | null
  narrative_order?: number | null
  order?: number | null
}

type ReplayPayload = {
  demo: {
    slug: string
    title: string
    description?: string
    manuscript_figure?: string
    prompt_sources?: string[]
    is_template?: boolean
    template_reason?: string | null
    demo_type?: string
  }
  analysis: {
    analysis_id: string
    status: string
    title?: string
    created_at?: number | null
    started_at?: number | null
    finished_at?: number | null
    warnings?: string[]
  }
  prompt: {
    primary_prompt: string
    followup_prompts: string[]
    coding_agent_prompts: string[]
    mcp_prompts: string[]
    source_path: string | null
  }
  replay: {
    source: 'runcard' | 'bundle_steps' | 'synthetic'
    steps: ReplayStep[]
  }
  reference_output: {
    summary: string
    summary_kind?: 'answer' | 'query' | 'synthetic'
    highlights: string[]
    documents: Array<{
      id?: string
      path: string
      mime_type: string
      content: string
      truncated: boolean
    }>
    generated_at?: string | null
    dataset_version?: string | null
  }
  presentation?: {
    mode?: 'live' | 'curated'
    disclaimer?: string
    overview?: string
  }
  reproduce: {
    requirements: string[]
    commands: string[]
    snippets?: Array<{
      snippet_id: string
      title: string
      language: 'text' | 'bash'
      lines: string[]
    }>
    source_path: string | null
  }
  bundle: {
    available: boolean
    generated_at?: string | null
    artifact_count: number
    source_run_ids: string[]
    items: Array<{
      id?: string
      name: string
      path: string
      download_url: string
      mime_type?: string
      preview?: string
      stage?: string | null
      title?: string | null
      roles?: string[]
    }>
  }
  notes?: string[]
}

type Props = {
  demoId: string
}

type ReplayTab = 'prompt_response' | 'evidence' | 'artifacts'

type NarrativeStep = ReplayStep & {
  narrative_title_resolved: string
  narrative_order_resolved: number
  source_index: number
}

function formatStatus(status: string): string {
  const value = status.trim().toLowerCase()
  if (value === 'completed' || value === 'success' || value === 'succeeded') return 'completed'
  if (value === 'running') return 'running'
  if (value === 'failed' || value === 'error' || value === 'timeout') return 'failed'
  return value || 'pending'
}

function statusClass(status: string): string {
  const normalized = formatStatus(status)
  if (normalized === 'completed') return 'bg-green-100 text-green-800'
  if (normalized === 'running') return 'bg-blue-100 text-blue-800'
  if (normalized === 'failed') return 'bg-red-100 text-red-800'
  return 'bg-gray-100 text-gray-700'
}

function formatTimestamp(value: number | null | undefined): string {
  if (!value || !Number.isFinite(value)) return '—'
  return new Date(value * 1000).toLocaleString()
}

function formatDurationMs(value: number | null | undefined): string {
  if (!value || value <= 0) return '—'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(1)} s`
}

function formatIsoTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) return value
  return new Date(parsed).toLocaleString()
}

function formatModeLabel(mode: 'live' | 'curated' | undefined): string {
  if (mode === 'live') return 'Live evidence'
  if (mode === 'curated') return 'Curated replay'
  return 'Replay'
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"'
        i += 1
        continue
      }
      inQuotes = !inQuotes
      continue
    }
    if (ch === ',' && !inQuotes) {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += ch
  }
  cells.push(current.trim())
  return cells
}

function parseCsvPreview(
  content: string,
  maxRows = 12,
  maxCols = 8,
): { header: string[]; rows: string[][]; truncated: boolean } | null {
  const lines = content
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length === 0) return null

  const parsed = lines.slice(0, maxRows).map((line) => parseCsvLine(line).slice(0, maxCols))
  if (parsed.length === 0) return null

  return {
    header: parsed[0],
    rows: parsed.slice(1),
    truncated: lines.length > maxRows,
  }
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function resolveNarrativeOrder(step: ReplayStep, index: number): number {
  const explicitOrder = step.narrative?.order ?? step.narrative_order ?? step.order
  return typeof explicitOrder === 'number' && Number.isFinite(explicitOrder)
    ? explicitOrder
    : index + 1
}

function resolveNarrativeTitle(step: ReplayStep, fallbackOrder: number): string {
  const explicitTitle = step.narrative?.title || step.narrative_title || step.title
  const trimmedTitle = explicitTitle?.trim() || ''
  return trimmedTitle || `Step ${fallbackOrder}`
}

export function DemoReplayWorkbench({ demoId }: Props) {
  const [payload, setPayload] = useState<ReplayPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedStepId, setSelectedStepId] = useState<string>('')
  const [copyStatus, setCopyStatus] = useState<string>('')
  const [showAllArtifacts, setShowAllArtifacts] = useState(false)
  const [activeReplayTab, setActiveReplayTab] = useState<ReplayTab>('prompt_response')

  useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    const requestedView = params.get('view') || window.location.hash.replace(/^#/, '')
    if (
      requestedView === 'prompt_response' ||
      requestedView === 'evidence' ||
      requestedView === 'artifacts'
    ) {
      setActiveReplayTab(requestedView)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await fetch(`/api/demo/replay/${encodeURIComponent(demoId)}`, {
          method: 'GET',
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!res.ok) {
          const body = await res
            .clone()
            .json()
            .catch(() => ({}))
          throw new Error(body?.detail || `Failed to load replay (${res.status})`)
        }
        const data = (await res.json()) as ReplayPayload
        setPayload(data)
      } catch (err: any) {
        if (err.name === 'AbortError') return
        setError(err.message || 'Failed to load replay.')
      } finally {
        setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [demoId])

  const narrativeSteps = useMemo<NarrativeStep[]>(() => {
    if (!payload) return []
    return payload.replay.steps
      .map((step, index) => {
        const narrativeOrder = resolveNarrativeOrder(step, index)
        return {
          ...step,
          narrative_title_resolved: resolveNarrativeTitle(step, narrativeOrder),
          narrative_order_resolved: narrativeOrder,
          source_index: index,
        }
      })
      .sort(
        (a, b) =>
          a.narrative_order_resolved - b.narrative_order_resolved ||
          a.source_index - b.source_index,
      )
  }, [payload])

  useEffect(() => {
    if (narrativeSteps.length === 0) {
      if (selectedStepId) setSelectedStepId('')
      return
    }
    const hasSelection = narrativeSteps.some((step) => step.step_id === selectedStepId)
    if (!hasSelection) setSelectedStepId(narrativeSteps[0].step_id)
  }, [narrativeSteps, selectedStepId])

  const selectedStep = useMemo(() => {
    if (!narrativeSteps.length) return null
    return narrativeSteps.find((step) => step.step_id === selectedStepId) || narrativeSteps[0] || null
  }, [narrativeSteps, selectedStepId])

  const selectedStepArtifactIds = useMemo(() => {
    if (!selectedStep) return new Set<string>()
    return new Set(selectedStep.artifact_refs)
  }, [selectedStep])

  const displayedArtifacts = useMemo(() => {
    if (!payload) return []
    if (showAllArtifacts || selectedStepArtifactIds.size === 0) return payload.bundle.items
    const matched = payload.bundle.items.filter(
      (item) =>
        (item.id && selectedStepArtifactIds.has(item.id)) ||
        selectedStepArtifactIds.has(item.path) ||
        selectedStepArtifactIds.has(item.name),
    )
    return matched.length > 0 ? matched : payload.bundle.items
  }, [payload, selectedStepArtifactIds, showAllArtifacts])

  const claudePrompt = payload?.prompt.primary_prompt || ''
  const codexPrompt = payload?.prompt.coding_agent_prompts[0] || payload?.prompt.primary_prompt || ''
  const defaultMcpPrompt = [
    'Use BR-KG/MCP only. Build claims with explicit provenance and no memory-only assertions.',
    '',
    'Two-stage procedure:',
    '1) Seed extraction: DOI/PMID/short concept phrases from the query.',
    '2) Evidence expansion: kg_get_node -> kg_search_nodes -> kg_neighbors -> kg_multihop_qa.',
    '',
    'Required output:',
    '- narrative summary',
    '- condition x conclusion matrix',
    '- claims with evidence_for/evidence_against',
    '- insufficient evidence list',
    '',
    `Query: ${payload?.prompt.primary_prompt || ''}`,
  ].join('\n')
  const mcpPrompt = payload?.prompt.mcp_prompts[0] || defaultMcpPrompt

  const copyPrompt = async (label: string, text: string) => {
    const ok = text ? await copyText(text) : false
    setCopyStatus(ok ? `${label} copied.` : `${label} is unavailable.`)
    setTimeout(() => setCopyStatus(''), 1600)
  }

  if (loading) {
    return (
      <NavigationWrapper>
        <div className="flex min-h-screen items-center justify-center bg-gray-50">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </NavigationWrapper>
    )
  }

  if (error || !payload) {
    return (
      <NavigationWrapper>
        <div className="min-h-screen bg-gray-50">
          <div className="mx-auto max-w-5xl px-4 py-8">
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
              {error || 'Replay not found.'}
            </div>
          </div>
        </div>
      </NavigationWrapper>
    )
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
          <div className="space-y-2">
            <Link href="/demos" className="text-sm text-muted-foreground hover:text-primary">
              ← Back to Demos
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">
              {payload.analysis.title || payload.demo.title}
            </h1>
            {payload.demo.description ? (
              <p className="max-w-4xl text-sm text-muted-foreground">{payload.demo.description}</p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Badge className={statusClass(payload.analysis.status)}>
                {formatStatus(payload.analysis.status)}
              </Badge>
              <Badge variant="outline">
                {formatModeLabel(payload.presentation?.mode)}
              </Badge>
              {payload.demo.is_template ? <Badge variant="secondary">Template</Badge> : null}
              {payload.demo.manuscript_figure ? <span>Figure {payload.demo.manuscript_figure}</span> : null}
            </div>
            {payload.demo.is_template ? (
              <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                {payload.demo.template_reason ||
                  'This replay is template/exploration oriented; stage outputs may be partially synthetic.'}
              </div>
            ) : null}
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="text-sm font-medium">Overview</div>
            <div className="text-sm text-muted-foreground">
              {payload.presentation?.overview || payload.demo.description || payload.demo.title}
            </div>
            {payload.presentation?.disclaimer ? (
              <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                {payload.presentation.disclaimer}
              </div>
            ) : null}
            <div className="grid grid-cols-1 gap-2 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
              <div>Replay source: {payload.replay.source}</div>
              <div>Narrative steps: {narrativeSteps.length}</div>
              <div>Evidence files: {payload.bundle.artifact_count}</div>
              <div>Started: {formatTimestamp(payload.analysis.started_at)}</div>
            </div>
            {payload.analysis.warnings?.length ? (
              <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                {payload.analysis.warnings.slice(0, 3).join(' · ')}
              </div>
            ) : null}
          </div>

          {payload.reproduce.requirements.length > 0 ? (
            <div className="rounded-lg border bg-card p-4 space-y-3">
              <div className="text-sm font-medium">Prerequisites</div>
              <div className="space-y-1">
                {payload.reproduce.requirements.map((req, idx) => (
                  <div key={`${req}_${idx}`} className="rounded border p-2 text-xs">
                    {req}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium">The Prompt</div>
                <div className="text-xs text-muted-foreground">
                  Prompt-first replay. Output below is a reference run.
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    void copyPrompt('MCP replay prompt', mcpPrompt)
                  }}
                >
                  Hand off
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void copyPrompt('Claude prompt', claudePrompt)
                  }}
                >
                  Copy to Claude
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void copyPrompt('Codex prompt', codexPrompt)
                  }}
                >
                  Copy to Codex
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void copyPrompt('MCP prompt', mcpPrompt)
                  }}
                >
                  Copy MCP Prompt
                </Button>
              </div>
            </div>
            <pre className="max-h-56 overflow-auto rounded bg-muted/30 p-3 text-sm whitespace-pre-wrap">
              {payload.prompt.primary_prompt}
            </pre>
            {payload.prompt.followup_prompts.length > 0 ? (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">Follow-up prompts</div>
                {payload.prompt.followup_prompts.map((item, idx) => (
                  <div key={`${item}_${idx}`} className="rounded border p-2 text-xs">
                    {item}
                  </div>
                ))}
              </div>
            ) : null}
            {copyStatus ? <div className="text-xs text-muted-foreground">{copyStatus}</div> : null}
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-4">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium">What Happens</div>
                <div className="text-xs text-muted-foreground">
                  Narrative replay derived from payload step title/order.
                </div>
              </div>
              <div className="text-xs text-muted-foreground">{narrativeSteps.length} steps</div>
            </div>

            {narrativeSteps.length > 0 ? (
              <Accordion
                type="single"
                value={selectedStep?.step_id || ''}
                onValueChange={(value) => {
                  if (value) setSelectedStepId(value)
                }}
                className="rounded border"
              >
                {narrativeSteps.map((step) => (
                  <AccordionItem key={step.step_id} value={step.step_id}>
                    <AccordionTrigger className="px-3 text-left hover:no-underline">
                      <div className="min-w-0">
                        <div className="text-xs text-muted-foreground">
                          Step {step.narrative_order_resolved} · {step.stage}
                        </div>
                        <div className="truncate text-sm font-medium">
                          {step.narrative_title_resolved}
                        </div>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent className="px-3">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <Badge className={statusClass(step.status)}>{formatStatus(step.status)}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {step.tool ? `Tool: ${step.tool}` : 'Tool: —'}
                          {' · '}
                          Duration: {formatDurationMs(step.duration_ms)}
                        </span>
                      </div>
                      <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted/30 p-2 text-xs">
                        {step.response_text || 'No narrative response captured for this step.'}
                      </pre>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            ) : (
              <div className="text-sm text-muted-foreground">No replay steps available.</div>
            )}

            <Tabs
              value={activeReplayTab}
              onValueChange={(value) => setActiveReplayTab(value as ReplayTab)}
              className="space-y-3"
            >
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="prompt_response">Prompt + Response</TabsTrigger>
                <TabsTrigger value="evidence">Evidence</TabsTrigger>
                <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
              </TabsList>

              <TabsContent value="prompt_response" className="space-y-3">
                {selectedStep ? (
                  <>
                    <div className="rounded border p-3">
                      <div className="mb-2 text-xs font-medium text-muted-foreground">
                        Prompt
                      </div>
                      <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-sm">
                        {selectedStep.prompt_text || payload.prompt.primary_prompt}
                      </pre>
                    </div>
                    <div className="rounded border p-3">
                      <div className="mb-2 text-xs font-medium text-muted-foreground">
                        Response
                      </div>
                      <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-sm">
                        {selectedStep.response_text ||
                          'No step-level response text was captured for this step.'}
                      </pre>
                    </div>
                    <div className="grid grid-cols-1 gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                      <div>Started: {formatTimestamp(selectedStep.started_at)}</div>
                      <div>Finished: {formatTimestamp(selectedStep.finished_at)}</div>
                      <div>Duration: {formatDurationMs(selectedStep.duration_ms)}</div>
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-muted-foreground">No replay step selected.</div>
                )}
              </TabsContent>

              <TabsContent value="evidence" className="space-y-3">
                <div id="evidence" className="rounded border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">Source runs</div>
                  {payload.bundle.source_run_ids.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {payload.bundle.source_run_ids.map((runId) => (
                        <Badge key={runId} variant="outline">
                          {runId}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">No source runs declared.</div>
                  )}
                </div>
                <div className="rounded border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">
                    Selected step tool calls
                  </div>
                  {selectedStep?.tool_calls.length ? (
                    <div className="space-y-1">
                      {selectedStep.tool_calls.map((toolName) => (
                        <div key={toolName} className="truncate text-xs">
                          {toolName}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      No explicit tool calls were captured for this step.
                    </div>
                  )}
                </div>
                <div className="rounded border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">
                    Selected step artifact refs
                  </div>
                  {selectedStep?.artifact_refs.length ? (
                    <div className="space-y-1">
                      {selectedStep.artifact_refs.map((ref) => (
                        <div key={ref} className="truncate text-xs">
                          {ref}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      No explicit artifact refs for this step.
                    </div>
                  )}
                </div>
                <div className="rounded border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">
                    Provenance notes
                  </div>
                  {payload.notes?.length ? (
                    <div className="space-y-1">
                      {payload.notes.map((note, idx) => (
                        <div key={`${note}_${idx}`} className="text-xs">
                          {note}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">No provenance notes available.</div>
                  )}
                </div>
              </TabsContent>

              <TabsContent value="artifacts" className="space-y-2">
                <div className="flex items-center justify-between gap-2 rounded border p-2 text-xs text-muted-foreground">
                  <div>
                    Showing {displayedArtifacts.length} of {payload.bundle.items.length} artifacts
                    {selectedStep ? ` for ${selectedStep.stage}` : ''}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowAllArtifacts((prev) => !prev)}
                  >
                    {showAllArtifacts ? 'Show Step-linked' : 'Show All'}
                  </Button>
                </div>
                {displayedArtifacts.length > 0 ? (
                  displayedArtifacts.map((item) => (
                    <div key={item.path} className="rounded border p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{item.name}</div>
                          <div className="truncate text-xs text-muted-foreground">{item.path}</div>
                          <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                            {item.stage ? <Badge variant="outline">{item.stage}</Badge> : null}
                            {(item.roles || []).slice(0, 4).map((role) => (
                              <Badge key={`${item.path}_${role}`} variant="secondary">
                                {role}
                              </Badge>
                            ))}
                          </div>
                        </div>
                        <Button size="sm" variant="outline" asChild>
                          <a href={item.download_url} target="_blank" rel="noreferrer">
                            Open
                          </a>
                        </Button>
                      </div>
                      {item.preview ? (
                        <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                          {item.preview}
                        </pre>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No artifacts are linked to this step.
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="text-sm font-medium">Reference Output</div>
            <div className="text-sm">{payload.reference_output.summary}</div>
            <div className="grid grid-cols-1 gap-2 text-xs text-muted-foreground sm:grid-cols-2">
              <div>Run date: {formatIsoTimestamp(payload.reference_output.generated_at)}</div>
              <div>
                Dataset version: {payload.reference_output.dataset_version || 'not specified'}
              </div>
            </div>
            {payload.reference_output.highlights.length > 0 ? (
              <div className="space-y-1">
                {payload.reference_output.highlights.map((item, idx) => (
                  <div key={`${item}_${idx}`} className="rounded border p-2 text-xs">
                    {item}
                  </div>
                ))}
              </div>
            ) : null}
            {payload.reference_output.documents.length > 0 ? (
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">
                  Recorded Real Run Outputs
                </div>
                {payload.reference_output.documents.map((doc) => {
                  const fileName = doc.path.split('/').filter(Boolean).pop() || doc.path
                  const match = payload.bundle.items.find(
                    (item) =>
                      (doc.id && item.id === doc.id) ||
                      item.path === doc.path ||
                      item.path.endsWith(`/${fileName}`) ||
                      item.name === fileName,
                  )
                  return (
                    <div key={`${doc.path}_${doc.mime_type}`} className="rounded border p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-medium">{fileName}</div>
                          <div className="truncate text-[11px] text-muted-foreground">{doc.path}</div>
                        </div>
                        {match?.download_url ? (
                          <Button size="sm" variant="outline" asChild>
                            <a href={match.download_url} target="_blank" rel="noreferrer">
                              Open
                            </a>
                          </Button>
                        ) : null}
                      </div>
                      {doc.mime_type.startsWith('image/') && match?.download_url ? (
                        <img
                          src={match.download_url}
                          alt={fileName}
                          className="max-h-[420px] w-full rounded border bg-white object-contain"
                        />
                      ) : doc.mime_type.includes('csv') ? (
                        (() => {
                          const csv = parseCsvPreview(doc.content)
                          if (!csv) {
                            return (
                              <pre className="max-h-72 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                                {doc.content}
                              </pre>
                            )
                          }
                          return (
                            <div className="space-y-2">
                              <div className="overflow-auto rounded border">
                                <table className="min-w-full text-xs">
                                  <thead className="bg-muted/40">
                                    <tr>
                                      {csv.header.map((cell, idx) => (
                                        <th
                                          key={`head_${idx}`}
                                          className="border-b px-2 py-1 text-left font-medium"
                                        >
                                          {cell || `col_${idx + 1}`}
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {csv.rows.map((row, rowIdx) => (
                                      <tr key={`row_${rowIdx}`}>
                                        {csv.header.map((_, colIdx) => (
                                          <td
                                            key={`cell_${rowIdx}_${colIdx}`}
                                            className="border-b px-2 py-1 align-top"
                                          >
                                            {row[colIdx] || ''}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              {csv.truncated ? (
                                <div className="text-[11px] text-muted-foreground">
                                  Table preview truncated for readability.
                                </div>
                              ) : null}
                            </div>
                          )
                        })()
                      ) : (
                        <pre className="max-h-72 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                          {doc.content}
                        </pre>
                      )}
                      {doc.truncated ? (
                        <div className="mt-2 text-[11px] text-muted-foreground">
                          Preview truncated for readability.
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ) : null}
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="text-sm font-medium">Reproduce This</div>
            {payload.reproduce.snippets && payload.reproduce.snippets.length > 0 ? (
              <div className="space-y-1">
                {payload.reproduce.snippets.map((snippet) => (
                  <div key={snippet.snippet_id} className="space-y-1 rounded border p-2">
                    <div className="text-xs font-medium text-muted-foreground">{snippet.title}</div>
                    <pre className="overflow-auto rounded bg-muted/20 p-2 text-xs whitespace-pre-wrap">
                      {snippet.lines.join('\n')}
                    </pre>
                  </div>
                ))}
              </div>
            ) : payload.reproduce.commands.length > 0 ? (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">Commands / Inputs</div>
                {payload.reproduce.commands.map((cmd, idx) => (
                  <pre
                    key={`${cmd}_${idx}`}
                    className="overflow-auto rounded border bg-muted/20 p-2 text-xs whitespace-pre-wrap"
                  >
                    {cmd}
                  </pre>
                ))}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                No reproduction commands were provided.
              </div>
            )}
            <div className="text-xs text-muted-foreground">
              Prompt source: {payload.prompt.source_path || 'derived from replay metadata'}
            </div>
          </div>
        </div>
      </div>
    </NavigationWrapper>
  )
}
