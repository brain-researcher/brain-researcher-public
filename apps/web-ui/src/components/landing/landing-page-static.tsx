'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { ArrowRight, Brain, Code2, Copy } from 'lucide-react'

import { ANALYSIS_TYPES } from '@/config/analysis-presets'
import type { WorkflowSummary } from '@/lib/api/workflows'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { useAuth } from '@/hooks/use-auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'
import {
  buildHostedMcpSnippet,
  DEFAULT_MCP_CLOUD_URL,
  type HostedMcpClient,
} from '@/lib/mcp-config-snippets'

type TemplateChip = {
  id: string
  label: string
  dataset?: string
  est: string
  description?: string
}

type DemoIndexEntry = {
  slug: string
  title: string
  description?: string
  is_template?: boolean
  evidence_mode?: 'real' | 'hybrid' | 'template'
  bundle_available?: boolean
  bundle_artifact_count?: number
}

function workflowIdToLabel(id: string): string {
  return id
    .replace(/^workflow_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function sanitizeCallbackUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed.startsWith('/')) return '/studio'
  if (trimmed.startsWith('/auth')) return '/studio'
  return trimmed
}

function buildSignupHref(callbackUrl: string): string {
  const safe = sanitizeCallbackUrl(callbackUrl)
  return `/auth/signup?callbackUrl=${encodeURIComponent(safe)}`
}

const HERO_SAMPLE_WORKFLOW: HandoffTemplatePayload = {
  kind: 'template',
  workflowId: 'nilearn_connectivity',
  workflowLabel: 'Nilearn Connectivity',
  unresolvedInputs: ['dataset_id'],
  title: 'Hand off — Nilearn Connectivity',
}

export default function LandingPageStatic() {
  const router = useRouter()
  const { toast } = useToast()
  const { isAuthenticated, isLoading } = useAuth()
  const { data: session, status } = useSession()
  const [ideConfigTab, setIdeConfigTab] = useState<HostedMcpClient>('cursor')
  const [hydrated, setHydrated] = useState(false)
  const [libraryWorkflows, setLibraryWorkflows] = useState<WorkflowSummary[]>([])
  const [workflowsLoading, setWorkflowsLoading] = useState(true)
  const [demos, setDemos] = useState<DemoIndexEntry[]>([])
  const [demosLoading, setDemosLoading] = useState(true)
  const [heroHandoffOpen, setHeroHandoffOpen] = useState(false)
  const showLandingDemoVideo =
    (process.env.NEXT_PUBLIC_ENABLE_LANDING_DEMO_VIDEO || '').trim().toLowerCase() === 'true'
  const showAuthenticatedActions =
    !isLoading && (isAuthenticated || status === 'authenticated' || Boolean(session))

  const buildEntryHref = (callbackUrl: string) => {
    const safe = sanitizeCallbackUrl(callbackUrl)
    return showAuthenticatedActions ? safe : buildSignupHref(safe)
  }

  useEffect(() => setHydrated(true), [])

  useEffect(() => {
    let cancelled = false
    brainResearcherAPI
      .fetchWorkflowCatalog({ limit: 6 })
      .then((data) => {
        if (cancelled) return
        setLibraryWorkflows(data.workflows?.slice(0, 6) ?? [])
      })
      .catch(() => {
        if (cancelled) return
        setLibraryWorkflows([])
      })
      .finally(() => {
        if (!cancelled) setWorkflowsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/demo/index', { cache: 'no-store', signal: controller.signal })
      .then((res) => (res.ok ? res.json() : { demos: [] }))
      .then((data) => {
        setDemos((data.demos || []).slice(0, 6))
      })
      .catch(() => {
        setDemos([])
      })
      .finally(() => setDemosLoading(false))
    return () => controller.abort()
  }, [])

  const pipelineById = useMemo(() => {
    type PipelineInfo = {
      id: string
      label: string
      description: string
      estRuntime?: string
    }

    const entries = ANALYSIS_TYPES.flatMap<[string, PipelineInfo]>((analysis) =>
      analysis.pipelines.map((pipeline): [string, PipelineInfo] => [
        pipeline.id,
        {
          id: pipeline.id,
          label: pipeline.label,
          description: pipeline.description,
          estRuntime: pipeline.estRuntime,
        },
      ]),
    )
    return new Map<string, PipelineInfo>(entries)
  }, [])

  const templateChips = useMemo<TemplateChip[]>(() => {
    const defaults: Array<{ id: string; dataset?: string; fallbackEst: string }> = [
      { id: 'nilearn_connectivity', dataset: 'HCP', fallbackEst: '~3 min' },
      { id: 'nilearn_glm', dataset: 'HCP', fallbackEst: '~5 min' },
      { id: 'qsiprep', dataset: 'HCP', fallbackEst: '~6 min' },
      { id: 'fmriprep', dataset: 'HCP', fallbackEst: '~12 min' },
      { id: 'mriqc', dataset: 'OpenNeuro', fallbackEst: '~6 min' },
      { id: 'fmri_glm_multiverse_openneuro', dataset: 'OpenNeuro', fallbackEst: '~8 min' },
    ]

    return defaults
      .map(({ id, dataset, fallbackEst }) => {
        const pipeline = pipelineById.get(id)
        if (!pipeline) return null
        return {
          id,
          label: pipeline.label,
          dataset,
          est: pipeline.estRuntime || fallbackEst,
          description: pipeline.description,
        }
      })
      .filter(Boolean) as TemplateChip[]
  }, [pipelineById])

  const startWithTemplate = (templateId: string) => {
    const callbackUrl = `/studio?template=${encodeURIComponent(templateId)}`
    router.push(buildEntryHref(callbackUrl))
  }

  const copyText = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast({ title: `${label} copied` })
    } catch {
      toast({ title: `Failed to copy ${label}`, variant: 'destructive' })
    }
  }

  const ideSnippet = buildHostedMcpSnippet(ideConfigTab, { url: DEFAULT_MCP_CLOUD_URL })

  return (
    <div
      className="min-h-screen bg-white"
      data-testid="landing-page"
      data-hydrated={hydrated ? '1' : '0'}
    >
      <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <Brain className="h-7 w-7 text-blue-500" />
            <span className="text-lg font-semibold tracking-tight text-foreground">Brain Researcher</span>
            <Badge variant="secondary" className="text-[10px] font-medium">
              Beta
            </Badge>
          </Link>

          <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
            <a
              href="#workflows"
              className="underline-offset-4 hover:text-foreground hover:underline transition-colors"
            >
              Workflows
            </a>
            <Link
              href="/demos"
              className="underline-offset-4 hover:text-foreground hover:underline transition-colors"
            >
              Demos
            </Link>
            <Link
              href="/mcp/setup"
              className="underline-offset-4 hover:text-foreground hover:underline transition-colors"
            >
              MCP
            </Link>
            <Link
              href="/docs"
              className="underline-offset-4 hover:text-foreground hover:underline transition-colors"
            >
              Docs
            </Link>
          </nav>

          <div className="flex items-center gap-2">
            {isLoading ? null : showAuthenticatedActions ? (
              <>
                <Button variant="ghost" asChild>
                  <Link href="/settings">Settings</Link>
                </Button>
                <Button variant="outline" onClick={() => setHeroHandoffOpen(true)}>
                  <Code2 className="mr-2 h-4 w-4" />
                  Hand off
                </Button>
                <Button asChild>
                  <Link href="/studio">Open Studio</Link>
                </Button>
              </>
            ) : (
              <>
                <Button variant="ghost" asChild>
                  <Link href={`/auth/login?callbackUrl=${encodeURIComponent('/studio')}`}>
                    Log in
                  </Link>
                </Button>
                <Button asChild>
                  <Link href={buildSignupHref('/studio')}>Sign up</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-12">
        <section className="mx-auto max-w-3xl space-y-8 text-center">
          <div className="space-y-3">
            <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">
              Take any neuroimaging workflow
              <br />
              <span className="text-muted-foreground">with you.</span>
            </h1>
            <p className="text-muted-foreground text-base sm:text-lg">
              Plan once; run anywhere — Studio, Cursor, Codex, or Claude Code.
            </p>
          </div>

          <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button size="lg" onClick={() => setHeroHandoffOpen(true)}>
              <Code2 className="mr-2 h-4 w-4" />
              Hand off to your agent
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href={buildEntryHref('/studio')}>
                Open in Studio
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>

          <div className="text-xs text-muted-foreground">
            <Link href={buildEntryHref('/studio/plan-preview')} className="underline underline-offset-4 hover:text-foreground">
              Try with your own question
            </Link>
          </div>
        </section>

        <section id="demos" className="mt-14 space-y-6">
          <div className="text-center space-y-2">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Demos and use cases
            </div>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Inspect public use-case reports
            </h2>
            <p className="text-sm text-muted-foreground max-w-xl mx-auto">
              Read curated report replays, evidence bundles, and MCP handoff context before running
              your own workflow.
            </p>
            <div className="pt-2">
              <Button asChild size="sm" variant="outline">
                <Link href="/demos">Open all use cases</Link>
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {demosLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <Card key={i} className="animate-pulse">
                  <CardContent className="p-5 space-y-3">
                    <div className="h-5 bg-muted rounded w-3/4" />
                    <div className="h-4 bg-muted rounded w-full" />
                    <div className="h-9 bg-muted rounded w-full" />
                  </CardContent>
                </Card>
              ))
            ) : demos.length === 0 ? (
              <div className="col-span-full text-center text-sm text-muted-foreground py-6">
                No demos available yet.
              </div>
            ) : (
              demos.map((demo) => (
                <Card key={demo.slug} className="hover:border-slate-300 transition-colors">
                  <CardContent className="p-5 space-y-3">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold">{demo.title}</div>
                      {demo.evidence_mode ? (
                        <span className="rounded border px-2 py-0.5 text-[10px] text-muted-foreground">
                          {demo.evidence_mode === 'real'
                            ? 'Real evidence'
                            : demo.evidence_mode === 'hybrid'
                              ? 'Hybrid evidence'
                              : 'Template'}
                        </span>
                      ) : null}
                      {demo.is_template ? (
                        <span className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] text-amber-800">
                          Template
                        </span>
                      ) : null}
                    </div>
                    {demo.description ? (
                      <div className="text-sm text-muted-foreground line-clamp-3">
                        {demo.description}
                      </div>
                    ) : null}
                    <Button asChild size="sm" variant="secondary" className="w-full">
                      <Link href={`/demos/${demo.slug}`}>Open use case</Link>
                    </Button>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </section>

        <section id="workflows" className="mt-14 space-y-6">
          <div className="text-center space-y-2">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Official workflows
            </div>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Start with a workflow you can validate
            </h2>
            <p className="text-sm text-muted-foreground max-w-xl mx-auto">
              Choose from curated pipelines for preprocessing, GLM, connectivity, and more, then hand off or review them in Studio.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {workflowsLoading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="animate-pulse">
                  <CardContent className="p-5 space-y-4">
                    <div className="h-5 bg-muted rounded w-3/4" />
                    <div className="h-4 bg-muted rounded w-full" />
                    <div className="h-4 bg-muted rounded w-5/6" />
                    <div className="flex gap-2">
                      <div className="h-5 bg-muted rounded w-16" />
                      <div className="h-5 bg-muted rounded w-12" />
                    </div>
                    <div className="h-9 bg-muted rounded w-full" />
                  </CardContent>
                </Card>
              ))
            ) : libraryWorkflows.length > 0 ? (
              libraryWorkflows.map((workflow) => {
                const callbackUrl = `/studio?template=${encodeURIComponent(workflow.id)}`
                const actionHref = buildEntryHref(callbackUrl)
                const label = workflowIdToLabel(workflow.id)
                return (
                  <Card
                    key={workflow.id}
                    className="cursor-pointer hover:border-slate-300 transition-colors"
                    onClick={() => startWithTemplate(workflow.id)}
                  >
                    <CardContent className="p-5 space-y-4">
                      <div className="space-y-2">
                        <div className="font-semibold">{label}</div>
                        {workflow.description ? (
                          <div className="text-sm text-muted-foreground line-clamp-2">
                            {workflow.description}
                          </div>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        {workflow.origin === 'official' ? (
                          <Badge variant="outline">Official ✓</Badge>
                        ) : null}
                        <Badge variant="secondary">
                          {workflow.est_runtime ?? '—'}
                        </Badge>
                      </div>

                      <Button type="button" variant="secondary" className="w-full" asChild>
                        <Link href={actionHref}>Choose template</Link>
                      </Button>
                    </CardContent>
                  </Card>
                )
              })
            ) : (
              templateChips.slice(0, 6).map((template) => {
                const callbackUrl = `/studio?template=${encodeURIComponent(template.id)}`
                const actionHref = buildEntryHref(callbackUrl)
                return (
                  <Card
                    key={template.id}
                    className="cursor-pointer hover:border-slate-300 transition-colors"
                    onClick={() => startWithTemplate(template.id)}
                  >
                    <CardContent className="p-5 space-y-4">
                      <div className="space-y-2">
                        <div className="font-semibold">{template.label}</div>
                        {template.description ? (
                          <div className="text-sm text-muted-foreground line-clamp-2">
                            {template.description}
                          </div>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant="outline">Official ✓</Badge>
                        <Badge variant="secondary">{template.est}</Badge>
                      </div>

                      <Button type="button" variant="secondary" className="w-full" asChild>
                        <Link href={actionHref}>Choose template</Link>
                      </Button>
                    </CardContent>
                  </Card>
                )
              })
            )}
          </div>
        </section>

        {showLandingDemoVideo ? (
          <section className="mt-14">
            <Card>
              <CardContent className="p-8">
                <div className="text-center space-y-2">
                  <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Product demo
                  </div>
                  <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                    Question → Plan → Validate → Full Run
                  </h2>
                </div>

                <div className="mt-6 aspect-video rounded-xl border bg-muted/10 flex items-center justify-center text-muted-foreground">
                  Studio walkthrough demo for validation-first workflow review will appear here.
                </div>
              </CardContent>
            </Card>
          </section>
        ) : null}

        <section id="ide" className="mt-14">
          <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
            <div className="space-y-4">
              <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                🔌 IDE integration
              </div>
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Use in your IDE
              </h2>
              <p className="text-muted-foreground">
                Run Brain Researcher directly in Cursor, Codex, or Claude Code. Full setup lives at{' '}
                <Link href="/mcp/setup" className="underline underline-offset-4 hover:text-foreground">
                  /mcp/setup
                </Link>
                .
              </p>
              <div className="text-sm text-muted-foreground">
                Cursor uses a direct bearer token in JSON, Codex uses{' '}
                <code className="font-mono">~/.codex/config.toml</code> plus{' '}
                <code className="font-mono">BR_MCP_TOKEN</code>, and Claude Code keeps{' '}
                <code className="font-mono">Authorization: Bearer ${'{'}BR_MCP_TOKEN{'}'}</code>{' '}
                in the hosted HTTP JSON config.
              </div>
            </div>

            <div className="rounded-xl border bg-slate-950 text-slate-50 p-5">
              <div className="mb-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={ideConfigTab === 'cursor' ? 'default' : 'secondary'}
                  onClick={() => setIdeConfigTab('cursor')}
                >
                  Cursor
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={ideConfigTab === 'codex' ? 'default' : 'secondary'}
                  onClick={() => setIdeConfigTab('codex')}
                >
                  Codex
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={ideConfigTab === 'claude' ? 'default' : 'secondary'}
                  onClick={() => setIdeConfigTab('claude')}
                >
                  Claude Code
                </Button>
              </div>
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-slate-400">{ideSnippet.fileName}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void copyText(ideSnippet.copyLabel, ideSnippet.snippet)}
                >
                  <Copy className="mr-2 h-3 w-3" />
                  {ideSnippet.copyButtonLabel}
                </Button>
              </div>
              <pre className="mt-4 text-xs leading-relaxed overflow-x-auto whitespace-pre-wrap text-slate-100">
                {ideSnippet.snippet}
              </pre>
            </div>
          </div>
        </section>

        <section className="mt-14">
          <Card>
            <CardContent className="p-8 text-center space-y-3">
              <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Trusted datasets built in
              </div>
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Explore datasets in the catalog
              </h2>
              <p className="text-muted-foreground max-w-2xl mx-auto">
                Browse curated neuroimaging datasets indexed by Brain Researcher and add them to your plan when you’re
                ready to run.
              </p>
              <div className="flex flex-col items-center justify-center gap-3 pt-2 sm:flex-row">
                <Button asChild variant="secondary">
                  <Link href="/datasets">Browse datasets</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="mt-14">
          <Card>
            <CardContent className="p-8 text-center space-y-3">
              <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Graph-backed evidence
              </div>
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Check the knowledge graph before you commit to a run
              </h2>
              <p className="text-muted-foreground max-w-2xl mx-auto">
                Use graph-backed concepts, datasets, and evidence trails to pressure-test your plan before you hand off a full execution.
              </p>
              <div className="flex flex-col items-center justify-center gap-3 pt-2 sm:flex-row">
                <Button asChild variant="secondary">
                  <Link href="/kg">Explore knowledge graph</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="mt-14 text-center space-y-4">
          <h2 className="text-3xl font-semibold tracking-tight">Take it with you</h2>
          <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button size="lg" onClick={() => setHeroHandoffOpen(true)}>
              <Code2 className="mr-2 h-4 w-4" />
              Hand off
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href={buildEntryHref('/studio')}>
                Open in Studio
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
          <div className="text-xs text-muted-foreground">
            Validate in Studio · Run full analyses in IDE or cluster
          </div>
        </section>
      </main>

      <HandoffModal
        open={heroHandoffOpen}
        onClose={() => setHeroHandoffOpen(false)}
        mode="template"
        payload={HERO_SAMPLE_WORKFLOW}
      />
    </div>
  )
}
