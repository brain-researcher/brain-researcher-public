'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Activity, AlertCircle, BarChart3, CheckCircle, Clock, Menu, Plus, RefreshCw } from 'lucide-react'
import { ChatWorkspace } from './chat-workspace'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import type { WorkflowSummary } from '@/lib/api/workflows'
import { STAGE_LABELS } from '@/lib/api/workflows'
import { KgSheet } from '@/components/studio/KgSheet'
import { buildStudioDatasetsPickerHref, isTruthyQueryValue } from '@/lib/studio-navigation'

type AnalysisItem = {
  analysis_id: string
  status: string
  created_at: number | null
  thread_id?: string | null
  title?: string
  dataset?: {
    dataset_id?: string
    name?: string
  }
  template?: {
    template_id?: string
    name?: string
  }
}

type AnalysesListResponse = {
  items: AnalysisItem[]
  count: number
}

type ThreadItem = {
  id: string
  title?: string | null
  created_at?: string | number | null
  updated_at?: string | number | null
  message_count?: number
}

type ThreadsListResponse = {
  threads: ThreadItem[]
  count: number
  user_id?: string
}

interface LinearChatProps {
  initialPrompt?: string
  systemPrompt?: string
  pipeline?: string
  datasetId?: string
  datasetVersion?: string
  conceptId?: string
  analysisId?: string
  threadId?: string
  scenarioId?: string
  draftPrompt?: string
  prefillParameters?: Record<string, unknown>
  initialCanvasTab?: 'plan' | 'results' | 'charts' | 'steps'
  projectId?: string
  openMcpOnMount?: boolean
}

const statusTone = (status: string) => {
  switch (status) {
    case 'running':
      return 'bg-blue-100 text-blue-700 border-blue-200'
    case 'completed':
      return 'bg-green-100 text-green-700 border-green-200'
    case 'failed':
      return 'bg-red-100 text-red-700 border-red-200'
    case 'queued':
      return 'bg-gray-100 text-gray-700 border-gray-200'
    default:
      return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

const statusIcon = (status: string) => {
  switch (status) {
    case 'running':
      return <RefreshCw className="h-3 w-3 animate-spin" />
    case 'completed':
      return <CheckCircle className="h-3 w-3" />
    case 'failed':
      return <AlertCircle className="h-3 w-3" />
    default:
      return <Clock className="h-3 w-3" />
  }
}

const formatCreatedAt = (createdAtSec?: number) => {
  if (!createdAtSec) return '–'
  return new Date(createdAtSec * 1000).toLocaleString()
}

const toSortableTimestamp = (value: unknown): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e11 ? value : value * 1000
  }
  if (typeof value !== 'string' || !value.trim()) return 0
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? ms : 0
}

export function LinearChat({
  initialPrompt,
  systemPrompt,
  pipeline,
  datasetId,
  datasetVersion,
  conceptId,
  analysisId,
  threadId,
  scenarioId,
  draftPrompt,
  prefillParameters,
  initialCanvasTab,
  projectId,
  openMcpOnMount,
}: LinearChatProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [chatKey, setChatKey] = useState(0)

  const [threads, setThreads] = useState<ThreadItem[]>([])
  const [threadsLoading, setThreadsLoading] = useState(true)
  const [threadsError, setThreadsError] = useState<string | null>(null)
  const [threadsAuthRequired, setThreadsAuthRequired] = useState(false)

  const [analyses, setAnalyses] = useState<AnalysisItem[]>([])
  const [analysesLoading, setAnalysesLoading] = useState(true)
  const [analysesError, setAnalysesError] = useState<string | null>(null)
  const [analysesAuthRequired, setAnalysesAuthRequired] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [kgOpen, setKgOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    const raw = searchParams.get('pickDataset') || searchParams.get('pick_dataset')
    if (!isTruthyQueryValue(raw)) return

    const target = buildStudioDatasetsPickerHref(new URLSearchParams(searchParams.toString()))
    if (typeof window !== 'undefined') {
      window.location.replace(target)
      return
    }
    router.replace(target)
  }, [router, searchParams])

  useEffect(() => {
    const raw =
      searchParams.get('openLibrary') || searchParams.get('open_library') || searchParams.get('library')
    if (!raw) return
    const normalized = raw.trim().toLowerCase()
    const shouldOpen = normalized === '1' || normalized === 'true' || normalized === 'yes'
    if (!shouldOpen) return

    setLibraryOpen(true)

    const params = new URLSearchParams(searchParams.toString())
    params.delete('openLibrary')
    params.delete('open_library')
    params.delete('library')
    const suffix = params.toString()
    router.replace(suffix ? `/studio?${suffix}` : '/studio')
  }, [router, searchParams])

  useEffect(() => {
    const raw =
      searchParams.get('openKg') ||
      searchParams.get('open_kg') ||
      searchParams.get('kg')
    if (!raw) return
    const normalized = raw.trim().toLowerCase()
    const shouldOpen = normalized === '1' || normalized === 'true' || normalized === 'yes'
    if (!shouldOpen) return

    setKgOpen(true)

    const params = new URLSearchParams(searchParams.toString())
    params.delete('openKg')
    params.delete('open_kg')
    params.delete('kg')
    const suffix = params.toString()
    router.replace(suffix ? `/studio?${suffix}` : '/studio')
  }, [router, searchParams])

  useEffect(() => {
    let cancelled = false
    const loadThreads = async () => {
      setThreadsLoading(true)
      setThreadsError(null)
      setThreadsAuthRequired(false)
      try {
        const res = await fetch('/api/threads?limit=50', { cache: 'no-store' })
        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            if (!cancelled) {
              setThreads([])
              setThreadsAuthRequired(true)
            }
            return
          }
          const detail = await res.text().catch(() => '')
          throw new Error(detail || `HTTP ${res.status}`)
        }
        const data = (await res.json()) as ThreadsListResponse
        if (!cancelled) {
          setThreads(Array.isArray(data.threads) ? data.threads : [])
        }
      } catch (err) {
        if (cancelled) return
        setThreads([])
        setThreadsError(err instanceof Error ? err.message : 'Failed to load threads')
      } finally {
        if (!cancelled) setThreadsLoading(false)
      }
    }

    void loadThreads()
    const timer = setInterval(loadThreads, 15_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const loadAnalyses = async () => {
      setAnalysesLoading(true)
      setAnalysesError(null)
      setAnalysesAuthRequired(false)
      try {
        const res = await fetch('/api/analyses?limit=50', { cache: 'no-store' })
        if (!res.ok) {
          if (res.status === 401) {
            if (!cancelled) {
              setAnalyses([])
              setAnalysesAuthRequired(true)
            }
            return
          }
          const detail = await res.text().catch(() => '')
          throw new Error(detail || `HTTP ${res.status}`)
        }
        const data = (await res.json()) as AnalysesListResponse
        if (!cancelled) {
          setAnalyses(Array.isArray(data.items) ? data.items : [])
        }
      } catch (err) {
        if (cancelled) return
        setAnalyses([])
        setAnalysesError(err instanceof Error ? err.message : 'Failed to load runs')
      } finally {
        if (!cancelled) setAnalysesLoading(false)
      }
    }

    void loadAnalyses()
    const timer = setInterval(loadAnalyses, 15_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const stats = useMemo(() => {
    const total = analyses.length
    const completed = analyses.filter((analysis) => analysis.status === 'completed').length
    const running = analyses.filter((analysis) => analysis.status === 'running').length
    const failed = analyses.filter((analysis) => analysis.status === 'failed').length
    return { total, completed, running, failed }
  }, [analyses])

  const recentAnalyses = useMemo(() => {
    return [...analyses]
      .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
      .slice(0, 5)
  }, [analyses])

  const threadTitleByAnalysis = useMemo(() => {
    const mapping = new Map<string, string>()
    const ordered = [...analyses].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
    for (const analysis of ordered) {
      const threadId = typeof analysis.thread_id === 'string' ? analysis.thread_id.trim() : ''
      const title = typeof analysis.title === 'string' ? analysis.title.trim() : ''
      if (!threadId || !title || mapping.has(threadId)) continue
      mapping.set(threadId, title)
    }
    return mapping
  }, [analyses])

  const recentThreads = useMemo(() => {
    const items: Array<{ threadId: string; label: string }> = []
    const sorted = [...threads].sort((a, b) => {
      const aTs = Math.max(toSortableTimestamp(a.updated_at), toSortableTimestamp(a.created_at))
      const bTs = Math.max(toSortableTimestamp(b.updated_at), toSortableTimestamp(b.created_at))
      return bTs - aTs
    })

    for (const thread of sorted) {
      const threadId = typeof thread.id === 'string' ? thread.id.trim() : ''
      if (!threadId) continue
      const title = typeof thread.title === 'string' ? thread.title.trim() : ''
      const inferredTitle = threadTitleByAnalysis.get(threadId) || ''
      items.push({
        threadId,
        label: title || inferredTitle || `Thread ${threadId.slice(0, 8)}`,
      })
      if (items.length >= 5) break
    }

    return items
  }, [threadTitleByAnalysis, threads])

  const applyPipelineToPlan = (pipelineId: string) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('tab', 'plan')
    params.set('pipeline', pipelineId)
    params.delete('template')
    router.push(`/studio?${params.toString()}`)
  }

  const openDatasetPicker = () => {
    const target = buildStudioDatasetsPickerHref(new URLSearchParams(searchParams.toString()))
    router.push(target)
  }

  const openSignIn = () => {
    router.push(`/auth/login?callbackUrl=${encodeURIComponent('/studio')}`)
  }

  const renderSidebar = (closeSidebar?: () => void) => {
    const close = () => closeSidebar?.()

    return (
      <div className="p-4">
        <div className="space-y-6">
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                History
              </h2>
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600"
                onClick={() => {
                  close()
                  router.push('/analyses')
                }}
                aria-label="Browse runs"
              >
                <Activity className="h-4 w-4" />
              </button>
            </div>

            <div className="mb-4 space-y-2">
              <div className="text-xs font-medium text-gray-900">Recent threads</div>
              {threadsAuthRequired ? (
                <div className="space-y-2 text-sm text-gray-500">
                  <div>Sign in to view your history.</div>
                  <button
                    type="button"
                    onClick={() => {
                      close()
                      openSignIn()
                    }}
                    className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 transition-colors hover:bg-gray-50"
                  >
                    Sign in
                  </button>
                </div>
              ) : threadsLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading threads…
                </div>
              ) : threadsError ? (
                <div className="text-sm text-red-600">Failed to load threads: {threadsError}</div>
              ) : recentThreads.length === 0 ? (
                <div className="text-sm text-gray-500">No threads yet.</div>
              ) : (
                <div className="space-y-1">
                  {recentThreads.map((item) => (
                    <button
                      key={item.threadId}
                      type="button"
                      onClick={() => {
                        close()
                        const params = new URLSearchParams()
                        params.set('thread', item.threadId)
                        router.push(`/studio?${params.toString()}`)
                      }}
                      className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 transition-colors hover:bg-gray-50"
                      title={item.threadId}
                    >
                      <div className="truncate font-medium">{item.label}</div>
                      <div className="truncate text-xs text-gray-500">{item.threadId.slice(0, 12)}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="text-xs font-medium text-gray-900">Recent runs</div>

            {analysesAuthRequired ? (
              <div className="space-y-2 text-sm text-gray-500">
                <div>Sign in to view your runs.</div>
                <button
                  type="button"
                  onClick={() => {
                    close()
                    openSignIn()
                  }}
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 transition-colors hover:bg-gray-50"
                >
                  Sign in
                </button>
              </div>
            ) : analysesLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <RefreshCw className="h-4 w-4 animate-spin" />
                Loading runs…
              </div>
            ) : analysesError ? (
              <div className="text-sm text-red-600">Failed to load runs: {analysesError}</div>
            ) : recentAnalyses.length === 0 ? (
              <div className="space-y-2 text-sm text-gray-500">
                <div>No runs yet.</div>
                <button
                  type="button"
                  onClick={() => {
                    close()
                    openDatasetPicker()
                  }}
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 transition-colors hover:bg-gray-50"
                >
                  Browse datasets
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {recentAnalyses.map((analysis) => {
                  const title = analysis.title || `Run ${analysis.analysis_id.slice(0, 8)}`
                  const datasetLabel = analysis.dataset?.name || analysis.dataset?.dataset_id
                  const templateLabel = analysis.template?.name || analysis.template?.template_id
                  return (
                    <div
                      key={analysis.analysis_id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        close()
                        const params = new URLSearchParams()
                        params.set('analysisId', analysis.analysis_id)
                        params.set('tab', 'results')
                        if (analysis.thread_id) {
                          params.set('thread', analysis.thread_id)
                        }
                        router.push(`/studio?${params.toString()}`)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          close()
                          const params = new URLSearchParams()
                          params.set('analysisId', analysis.analysis_id)
                          params.set('tab', 'results')
                          if (analysis.thread_id) {
                            params.set('thread', analysis.thread_id)
                          }
                          router.push(`/studio?${params.toString()}`)
                        }
                      }}
                      className="cursor-pointer rounded-lg border border-transparent p-3 transition-all hover:border-gray-200 hover:bg-gray-50"
                    >
                      <div className="mb-1 flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{title}</div>
                          {datasetLabel && <div className="truncate text-xs text-gray-500">Dataset: {datasetLabel}</div>}
                          {templateLabel ? (
                            <div className="truncate text-xs text-gray-500">Workflow: {templateLabel}</div>
                          ) : null}
                        </div>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium ${statusTone(analysis.status)}`}
                        >
                          {statusIcon(analysis.status)}
                          {analysis.status}
                        </span>
                      </div>
                      <div className="text-xs text-gray-500">
                        {formatCreatedAt(typeof analysis.created_at === 'number' ? analysis.created_at : undefined)}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div>
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Workflows
            </div>
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => {
                  close()
                  setLibraryOpen(true)
                }}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 transition-colors hover:bg-gray-50"
              >
                Official workflows ({workflowCount ?? (officialPipelines.length || '...')})
              </button>
              <button
                type="button"
                onClick={() => {
                  close()
                  router.push('/library/tools')
                }}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 transition-colors hover:bg-gray-50"
              >
                Tool Catalog
              </button>
            </div>
          </div>

          <div>
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Resources
            </div>
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => {
                  close()
                  router.push('/datasets')
                }}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 transition-colors hover:bg-gray-50"
              >
                Datasets
              </button>
              <button
                type="button"
                onClick={() => {
                  close()
                  setKgOpen(true)
                }}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-900 transition-colors hover:bg-gray-50"
              >
                Knowledge Graph
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
            <h3 className="mb-1 font-medium text-blue-900">Tip</h3>
            <p className="text-xs text-blue-700">
              Click a run to review it in Studio. You can share or export from the Results tab.
            </p>
          </div>
        </div>
      </div>
    )
  }

  // Fetch workflows from backend API
  const [officialPipelines, setOfficialPipelines] = useState<Array<{
    id: string
    title: string
    description: string
    estRuntime?: string
    stage: string
  }>>([])
  const [workflowsLoading, setWorkflowsLoading] = useState(true)
  const [workflowCount, setWorkflowCount] = useState<number | null>(null)

  // Preload workflow count on mount
  useEffect(() => {
    brainResearcherAPI
      .fetchWorkflowCatalog({ limit: 1 })
      .then((response) => {
        setWorkflowCount(response.count)
      })
      .catch(() => {
        // Silently fail - count will show as "..."
      })
  }, [])

  // Load full workflows when sheet opens
  useEffect(() => {
    if (libraryOpen && officialPipelines.length === 0) {
      setWorkflowsLoading(true)
      brainResearcherAPI
        .fetchWorkflowCatalog({ limit: 100 })
        .then((response) => {
          const pipelines = response.workflows.map((w: WorkflowSummary) => ({
            id: w.id,
            title: w.id.replace(/^workflow_/, '').replace(/_/g, ' '),
            description: w.description,
            estRuntime: w.est_runtime,
            stage: w.stage,
          }))
          setOfficialPipelines(pipelines)
          setWorkflowCount(response.count)
        })
        .catch((err) => {
          console.error('Failed to load workflows:', err)
        })
        .finally(() => setWorkflowsLoading(false))
    }
  }, [libraryOpen, officialPipelines.length])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
        <SheetContent side="left" className="w-[88vw] max-w-sm overflow-y-auto p-0">
          <SheetHeader className="border-b px-4 py-4">
            <SheetTitle>Studio navigation</SheetTitle>
            <SheetDescription>Threads, runs, workflows, and resources.</SheetDescription>
          </SheetHeader>
          {renderSidebar(() => setSidebarOpen(false))}
        </SheetContent>
      </Sheet>

      <Sheet open={libraryOpen} onOpenChange={setLibraryOpen}>
        <SheetContent side="right" className="w-[92vw] max-w-[440px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Official workflows</SheetTitle>
            <SheetDescription>
              Pick an official workflow to prefill your plan. You can review checks before running.
            </SheetDescription>
          </SheetHeader>

          <div className="mt-6 space-y-3">
            {workflowsLoading ? (
              <div className="flex items-center justify-center py-8 text-muted-foreground">
                <RefreshCw className="h-5 w-5 animate-spin mr-2" />
                Loading workflows...
              </div>
            ) : officialPipelines.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No workflows available
              </div>
            ) : (
              officialPipelines.map((pipeline) => (
                <Card key={pipeline.id}>
                  <CardContent className="p-4 space-y-3">
                    <div className="space-y-1">
                      <div className="text-sm font-semibold capitalize">{pipeline.title}</div>
                      <div className="text-sm text-muted-foreground line-clamp-2">{pipeline.description}</div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="text-xs">
                          {STAGE_LABELS[pipeline.stage] || pipeline.stage}
                        </Badge>
                        {pipeline.estRuntime ? (
                          <Badge variant="secondary" className="text-xs">
                            {pipeline.estRuntime}
                          </Badge>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex items-center justify-end">
                      <Button
                        size="sm"
                        onClick={() => {
                          applyPipelineToPlan(pipeline.id)
                          setLibraryOpen(false)
                        }}
                      >
                        Add to Plan
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={kgOpen} onOpenChange={setKgOpen}>
        <KgSheet
          onOpenExplorer={() => {
            router.push('/kg')
            setKgOpen(false)
          }}
          onOpenSuggestions={() => {
            router.push('/kg?tab=suggestions')
            setKgOpen(false)
          }}
          onAskAssistant={() => {
            const prompt =
              'Use the internal BR-KG (Neo4j) first. Run a subgraph search around relevant concepts and include top nodes/edges in the answer. Avoid external web unless necessary.'
            router.push(`/studio?prompt=${encodeURIComponent(prompt)}`)
            setKgOpen(false)
          }}
        />
      </Sheet>

      {/* Header with real stats */}
      <div className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-gray-900">Studio</h1>
            <p className="text-gray-600 mt-1">
              Plan, validate, and hand off reproducible neuro workflows.
            </p>
            {datasetId ? (
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="secondary" className="text-xs">
                  Dataset: <span className="ml-1 font-medium truncate max-w-[220px]" title={datasetId}>{datasetId}</span>
                </Badge>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="lg:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu className="mr-2 h-4 w-4" />
              Menu
            </Button>
            <button
              type="button"
              onClick={() => {
                setChatKey((prev) => prev + 1)

                const params = new URLSearchParams(searchParams.toString())
                params.delete('thread')
                params.delete('threadId')
                params.delete('analysisId')
                params.delete('analysis')
                params.delete('runId')
                params.delete('jobId')

                const suffix = params.toString()
                router.replace(suffix ? `/studio?${suffix}` : '/studio')
              }}
              className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors"
            >
              <Plus className="h-4 w-4 inline mr-2" />
              New Chat
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-gray-400" />
              <div>
                <div className="text-xl font-semibold">{stats.total}</div>
                <div className="text-xs text-gray-600">Total Runs</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-gray-400" />
              <div>
                <div className="text-xl font-semibold">{stats.running}</div>
                <div className="text-xs text-gray-600">Running</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-gray-400" />
              <div>
                <div className="text-xl font-semibold">{stats.completed}</div>
                <div className="text-xs text-gray-600">Completed</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-gray-400" />
              <div>
                <div className="text-xl font-semibold">{stats.failed}</div>
                <div className="text-xs text-gray-600">Failed</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <div className="hidden w-80 overflow-y-auto border-r border-gray-200 bg-white lg:block">
          {renderSidebar()}
        </div>

        {/* Chat Interface */}
        <div className="min-h-0 min-w-0 flex-1 bg-gray-50">
          <ChatWorkspace
            key={chatKey}
            initialPrompt={initialPrompt}
            systemPrompt={systemPrompt}
            pipeline={pipeline}
            datasetId={datasetId}
            datasetVersion={datasetVersion}
            conceptId={conceptId}
            analysisId={analysisId}
            threadId={threadId}
            scenarioId={scenarioId}
            draftPrompt={draftPrompt}
            prefillParameters={prefillParameters}
            initialCanvasTab={initialCanvasTab}
            projectId={projectId}
            openMcpOnMount={openMcpOnMount}
          />
        </div>
      </div>
    </div>
  )
}
