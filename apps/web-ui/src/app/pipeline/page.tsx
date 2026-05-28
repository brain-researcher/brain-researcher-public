'use client'

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { ReactFlowProvider } from 'reactflow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Settings,
  Plus,
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  Layers,
  FileText,
  Bot
} from 'lucide-react'

// Import the PipelineVisualization component
import { PipelineVisualization } from '@/components/pipeline/PipelineVisualization'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { CopilotPanel } from '@/components/copilot/copilot-panel'
import { PipelineQueueMonitor } from '@/components/pipeline/PipelineQueueMonitor'
import { useDashboardData } from '@/hooks/useDashboardData'
import { WorkflowTemplatesTab } from '@/components/pipeline/WorkflowTemplatesTab'
import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import { serviceEndpoints } from '@/lib/service-endpoints'
import type { AnalysesListResponse, AnalysisSummary } from '@/types/analysis'
import { cn } from '@/lib/utils'
import { CopilotMessage, MethodRecommendation, ParameterSuggestion } from '@/types/copilot'

type JobListItem = {
  id: string
  name?: string | null
  prompt?: string | null
  description?: string | null
  status?: string | null
  progress?: number | null
  created_at?: string | null
  started_at?: string | null
  completed_at?: string | null
  estimated_completion?: string | null
  user_id?: string | null
  metadata?: Record<string, any> | null
}

const toIsoString = (value?: number | string | null) => {
  if (value == null) return null
  if (typeof value === 'string') return value
  if (!Number.isFinite(value)) return null
  const ms = value > 1e11 ? value : value * 1000
  return new Date(ms).toISOString()
}

const mapAnalysisToJob = (analysis: AnalysisSummary): JobListItem => ({
  id: analysis.analysis_id,
  name: analysis.title || analysis.template?.name || analysis.analysis_id,
  prompt: analysis.title || null,
  status: analysis.status,
  created_at: toIsoString(analysis.created_at),
  started_at: toIsoString(analysis.started_at),
  completed_at: toIsoString(analysis.finished_at),
  metadata: {
    parameters: {
      pipeline_id: analysis.template?.pipeline_id ?? null,
    },
    dataset: analysis.dataset ?? null,
    template: analysis.template ?? null,
  },
})

type PipelineStatusSnapshot = {
  pipeline_id?: string | null
  job_id?: string | null
  status?: string | null
  progress?: number | null
  pipeline?: {
    nodes?: Record<string, { status?: string | null } | null> | null
  } | null
}

type CopilotSuggestResponse = {
  suggestions: Array<{
    name: string
    description: string
    reason: string
    score: number
    autocomplete?: Record<string, any> | null
  }>
}

const mapCopilotSuggestionCategory = (
  name: string,
): ParameterSuggestion['category'] => {
  const key = name.toLowerCase()
  if (/(smooth|bandpass|filter|preproc|denoise|motion|slice|distortion)/.test(key)) {
    return 'preprocessing'
  }
  if (/(hrf|glm|design|contrast|model)/.test(key)) {
    return 'analysis'
  }
  if (/(threshold|pval|qval|fdr|cluster|alpha|beta)/.test(key)) {
    return 'statistics'
  }
  if (/(plot|figure|viz|visual|render|surface)/.test(key)) {
    return 'visualization'
  }
  return 'analysis'
}

const mapCopilotResponseToSuggestions = (
  response: CopilotSuggestResponse,
): ParameterSuggestion[] =>
  (response?.suggestions ?? []).map((suggestion, index) => {
    const autocomplete = suggestion.autocomplete || {}
    const fallbackValue =
      autocomplete && typeof autocomplete === 'object'
        ? autocomplete[suggestion.name] ?? Object.values(autocomplete)[0]
        : undefined
    const value =
      fallbackValue === undefined ? '' : typeof fallbackValue === 'string' || typeof fallbackValue === 'number'
        ? fallbackValue
        : JSON.stringify(fallbackValue)

    return {
      id: `${suggestion.name}-${index}`,
      name: suggestion.name,
      value,
      description: suggestion.description,
      category: mapCopilotSuggestionCategory(suggestion.name),
      reasoning: suggestion.reason,
      confidence: Math.max(0, Math.min(1, suggestion.score / 3)),
      source: 'best_practice',
    }
  })

export default function PipelinePage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const jobIdParamRaw = searchParams.get('job_id') || searchParams.get('jobId')
  const pipelineIdParam =
    searchParams.get('pipeline_id') || searchParams.get('pipelineId')
  const basePipelineId = pipelineIdParam || 'main-pipeline'
  const jobIdParam = jobIdParamRaw ? String(jobIdParamRaw) : null
  const [autoJobId, setAutoJobId] = useState<string | null>(null)
  const [autoJobStatusChecked, setAutoJobStatusChecked] = useState(false)
  const resolvedJobId = jobIdParam || autoJobId
  const resolvedPipelineId = jobIdParam || autoJobId || basePipelineId
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [copilotOpen, setCopilotOpen] = useState(false)
  const [copilotMinimized, setCopilotMinimized] = useState(false)
  const [copilotMessages, setCopilotMessages] = useState<CopilotMessage[]>([])
  const [copilotSuggestions, setCopilotSuggestions] = useState<ParameterSuggestion[]>([])
  const [copilotRecommendations, setCopilotRecommendations] = useState<MethodRecommendation[]>([])
  const [copilotLastQuery, setCopilotLastQuery] = useState<string | null>(null)
  const [copilotError, setCopilotError] = useState<string | null>(null)
  const [copilotLoading, setCopilotLoading] = useState(false)
  const lastCopilotRequestKeyRef = useRef<string | null>(null)
  const [copilotFilters, setCopilotFilters] = useState({
    exposures: [] as string[],
    domain: '',
    function: '',
    risk: '',
  })
  const {
    data: dashboardData,
    error: dashboardError,
    connected: dashboardConnected,
    refresh: refreshDashboard,
  } = useDashboardData()
  const [jobs, setJobs] = useState<JobListItem[]>([])
  const [jobsLoading, setJobsLoading] = useState(true)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [pipelineSnapshot, setPipelineSnapshot] = useState<PipelineStatusSnapshot | null>(null)
  const [pipelineSnapshotLoading, setPipelineSnapshotLoading] = useState(false)
  const [pipelineSnapshotError, setPipelineSnapshotError] = useState<string | null>(null)

  useEffect(() => {
    if (jobIdParam || autoJobId) return

    let cancelled = false
    const fetchStatus = async () => {
      setAutoJobStatusChecked(false)
      try {
        const response = await fetch(
          serviceEndpoints.orchestrator(`/api/pipeline/${basePipelineId}/status`),
          { headers: { 'Cache-Control': 'no-cache' } }
        )
        if (!response.ok) return
        const data = await response.json()
        if (cancelled) return

        const rawJobId =
          data?.job_id ||
          data?.execution?.job_id ||
          data?.execution?.id ||
          data?.execution?.run_id ||
          null
        if (rawJobId) {
          setAutoJobId(String(rawJobId))
        }
      } catch {
        // Ignore auto-bind failures; manual run is still available.
      } finally {
        if (!cancelled) {
          setAutoJobStatusChecked(true)
        }
      }
    }

    fetchStatus()
    return () => {
      cancelled = true
    }
  }, [jobIdParam, autoJobId, basePipelineId])

  useEffect(() => {
    if (!resolvedJobId) {
      setPipelineSnapshot(null)
      setPipelineSnapshotLoading(false)
      setPipelineSnapshotError(null)
      return
    }

    let cancelled = false

    const fetchSnapshot = async () => {
      setPipelineSnapshotLoading(true)
      setPipelineSnapshotError(null)
      try {
        const response = await fetch(
          serviceEndpoints.orchestrator(`/api/pipeline/${resolvedJobId}/status`),
          { headers: { 'Cache-Control': 'no-cache' } }
        )
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = (await response.json()) as PipelineStatusSnapshot
        if (cancelled) return
        setPipelineSnapshot(data)
      } catch (err) {
        if (cancelled) return
        setPipelineSnapshot(null)
        setPipelineSnapshotError(err instanceof Error ? err.message : 'Failed to load pipeline status')
      } finally {
        if (!cancelled) {
          setPipelineSnapshotLoading(false)
        }
      }
    }

    void fetchSnapshot()
    const timer = setInterval(fetchSnapshot, 5_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [resolvedJobId])

  useEffect(() => {
    let cancelled = false

    const fetchJobs = async () => {
      setJobsLoading(true)
      setJobsError(null)
      try {
        const response = await fetch('/api/analyses?limit=50', {
          headers: { 'Cache-Control': 'no-cache' },
        })
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = (await response.json()) as AnalysesListResponse
        if (cancelled) return
        const items = Array.isArray(data.items) ? data.items : []
        setJobs(items.map(mapAnalysisToJob))
      } catch (err) {
        if (cancelled) return
        setJobs([])
        setJobsError(err instanceof Error ? err.message : 'Failed to load analyses')
      } finally {
        if (!cancelled) {
          setJobsLoading(false)
        }
      }
    }

    fetchJobs()
    const timer = setInterval(fetchJobs, 15_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const pipelineStats = useMemo(() => {
    const queue = dashboardData?.jobMetrics?.queue
    if (queue) {
      const running = queue.running ?? 0
      const queued = queue.queued ?? 0
      const completed = queue.completed ?? 0
      const failed = queue.failed ?? 0
      return {
        total: running + queued + completed + failed,
        running,
        completed,
        failed,
        queued,
      }
    }

    if (jobsLoading) {
      return null
    }

    const counts = {
      running: 0,
      queued: 0,
      completed: 0,
      failed: 0,
    }

    for (const job of jobs) {
      const status = String(job.status || '').toLowerCase()
      if (status === 'running' || status === 'retrying' || status === 'claimed') {
        counts.running += 1
      } else if (status === 'queued' || status === 'pending') {
        counts.queued += 1
      } else if (status === 'completed' || status === 'succeeded') {
        counts.completed += 1
      } else if (status === 'failed' || status === 'error' || status === 'timeout') {
        counts.failed += 1
      }
    }

    return {
      total: counts.running + counts.queued + counts.completed + counts.failed,
      running: counts.running,
      completed: counts.completed,
      failed: counts.failed,
      queued: counts.queued,
    }
  }, [dashboardData, jobs, jobsLoading])

  const pipelineNodeStats = useMemo(() => {
    const nodes = pipelineSnapshot?.pipeline?.nodes
    if (!nodes || typeof nodes !== 'object') return null

    const counts = {
      pending: 0,
      running: 0,
      completed: 0,
      failed: 0,
    }

    const statuses = Object.values(nodes).map((node) =>
      String(node?.status ?? 'pending').toLowerCase()
    )

    if (statuses.length === 0) return null

    for (const status of statuses) {
      if (status === 'running' || status === 'retrying') {
        counts.running += 1
      } else if (status === 'completed' || status === 'succeeded') {
        counts.completed += 1
      } else if (status === 'failed' || status === 'error' || status === 'timeout') {
        counts.failed += 1
      } else {
        counts.pending += 1
      }
    }

    return {
      total: statuses.length,
      running: counts.running,
      completed: counts.completed,
      failed: counts.failed,
      queued: counts.pending,
    }
  }, [pipelineSnapshot])

  const pipelineGraphAvailable = useMemo(() => {
    const nodes = pipelineSnapshot?.pipeline?.nodes
    if (!nodes || typeof nodes !== 'object') return false
    return Object.keys(nodes).length > 0
  }, [pipelineSnapshot?.pipeline?.nodes])

  const pipelineCardsStats = useMemo(() => {
    if (resolvedJobId) {
      return pipelineNodeStats
    }
    return pipelineStats
  }, [resolvedJobId, pipelineNodeStats, pipelineStats])

  const pipelineCardsLoading = useMemo(() => {
    if (pipelineCardsStats) return false
    if (resolvedJobId) return pipelineSnapshotLoading
    return jobsLoading && !dashboardData?.jobMetrics?.queue
  }, [pipelineCardsStats, resolvedJobId, pipelineSnapshotLoading, jobsLoading, dashboardData?.jobMetrics?.queue])

  const activeJobs = useMemo(() => {
    return jobs.filter((job) => {
      const status = String(job.status || '').toLowerCase()
      return !['completed', 'failed', 'cancelled', 'canceled', 'skipped'].includes(status)
    })
  }, [jobs])

  const handleStartNewPipeline = useCallback(() => {
    router.push('/pipeline-builder')
  }, [router])

  const runLabel = useMemo(() => {
    if (jobIdParam) {
      return `Viewing ${jobIdParam}`
    }

    if (autoJobId) {
      return `Last run: ${autoJobId}`
    }

    return `Pipeline: ${basePipelineId}`
  }, [jobIdParam, autoJobId, basePipelineId])

  const fetchCopilotSuggestions = useCallback(async (query: string) => {
    setCopilotLoading(true)
    setCopilotError(null)
    try {
      const response = await fetch(
        serviceEndpoints.orchestrator('/copilot/suggest', { absolute: true }),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query,
            k: 8,
            metadata: {
              pipeline_id: basePipelineId,
              job_id: jobIdParam || autoJobId || undefined,
              selected_node_id: selectedNodeId || undefined,
            },
            exposures: copilotFilters.exposures?.length ? copilotFilters.exposures : undefined,
            domain: copilotFilters.domain || undefined,
            function: copilotFilters.function || undefined,
            risk: copilotFilters.risk || undefined,
          }),
        }
      )
      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as CopilotSuggestResponse
      const suggestions = mapCopilotResponseToSuggestions(data)
      setCopilotSuggestions(suggestions)
      setCopilotRecommendations([])
      return suggestions
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch copilot suggestions'
      setCopilotSuggestions([])
      setCopilotRecommendations([])
      setCopilotError(message)
      throw err
    } finally {
      setCopilotLoading(false)
    }
  }, [basePipelineId, jobIdParam, autoJobId, selectedNodeId, copilotFilters])

  useEffect(() => {
    if (!copilotOpen) return
    if (!copilotLastQuery) return

    const requestKey = JSON.stringify({
      query: copilotLastQuery,
      filters: copilotFilters,
      job_id: resolvedJobId,
      selected_node_id: selectedNodeId,
    })
    if (lastCopilotRequestKeyRef.current === requestKey) return
    lastCopilotRequestKeyRef.current = requestKey

    void fetchCopilotSuggestions(copilotLastQuery).catch(() => undefined)
  }, [copilotOpen, copilotFilters, copilotLastQuery, resolvedJobId, selectedNodeId, fetchCopilotSuggestions])

  const handleCopilotMessage = useCallback(async (message: string) => {
    const trimmed = message.trim()
    if (!trimmed) return

    const userMessage: CopilotMessage = {
      id: `${Date.now()}-user`,
      type: 'user',
      content: trimmed,
      timestamp: new Date(),
    }
    setCopilotMessages((prev) => [...prev, userMessage])

    lastCopilotRequestKeyRef.current = JSON.stringify({
      query: trimmed,
      filters: copilotFilters,
      job_id: resolvedJobId,
      selected_node_id: selectedNodeId,
    })
    setCopilotLastQuery(trimmed)

    try {
      const suggestions = await fetchCopilotSuggestions(trimmed)
      const copilotMessage: CopilotMessage = {
        id: `${Date.now()}-copilot`,
        type: 'copilot',
        content: suggestions.length
          ? `Updated suggestions (${suggestions.length}). Check the Params tab.`
          : 'No data yet.',
        timestamp: new Date(),
        suggestions,
      }
      setCopilotMessages((prev) => [...prev, copilotMessage])
    } catch (err) {
      const messageText =
        err instanceof Error ? err.message : 'Failed to fetch copilot suggestions.'
      const copilotMessage: CopilotMessage = {
        id: `${Date.now()}-copilot`,
        type: 'copilot',
        content: `Copilot unavailable: ${messageText}`,
        timestamp: new Date(),
      }
      setCopilotMessages((prev) => [...prev, copilotMessage])
    }
  }, [fetchCopilotSuggestions, copilotFilters, resolvedJobId, selectedNodeId])

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <AdvancedViewBanner canonicalHref="/analyses" />
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">Pipeline Management</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Design, monitor, and manage analysis pipelines.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCopilotOpen(!copilotOpen)}
                className={copilotOpen ? 'bg-blue-50 border-blue-300' : ''}
              >
                <Bot className="h-4 w-4 mr-2" />
                AI Assistant
              </Button>
              <Button size="sm" onClick={handleStartNewPipeline}>
                <Plus className="h-4 w-4 mr-2" />
                Pipeline Builder
              </Button>
            </div>
          </div>
          <div className="mt-3 text-xs text-gray-500">{runLabel}</div>
        </div>

        {/* Stats Cards */}
        {resolvedJobId && pipelineSnapshotError && (
          <div className="mb-4 text-sm text-red-600">
            Pipeline status unavailable: {pipelineSnapshotError}
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-8">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Total</p>
                  <p className="text-2xl font-bold" data-testid="pipeline-kpi-total">
                    {pipelineCardsLoading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                    ) : pipelineCardsStats ? (
                      pipelineCardsStats.total
                    ) : (
                      '–'
                    )}
                  </p>
                </div>
                <Layers className="h-8 w-8 text-gray-400" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Running</p>
                  <p className="text-2xl font-bold text-blue-600" data-testid="pipeline-kpi-running">
                    {pipelineCardsLoading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-blue-400" />
                    ) : pipelineCardsStats ? (
                      pipelineCardsStats.running
                    ) : (
                      '–'
                    )}
                  </p>
                </div>
                <Loader2
                  className={cn(
                    'h-8 w-8 text-blue-400',
                    pipelineCardsStats?.running ? 'animate-spin' : '',
                  )}
                />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Completed</p>
                  <p className="text-2xl font-bold text-green-600" data-testid="pipeline-kpi-completed">
                    {pipelineCardsLoading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-green-400" />
                    ) : pipelineCardsStats ? (
                      pipelineCardsStats.completed
                    ) : (
                      '–'
                    )}
                  </p>
                </div>
                <CheckCircle className="h-8 w-8 text-green-400" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Failed</p>
                  <p className="text-2xl font-bold text-red-600" data-testid="pipeline-kpi-failed">
                    {pipelineCardsLoading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-red-400" />
                    ) : pipelineCardsStats ? (
                      pipelineCardsStats.failed
                    ) : (
                      '–'
                    )}
                  </p>
                </div>
                <AlertCircle className="h-8 w-8 text-red-400" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Queued</p>
                  <p className="text-2xl font-bold text-yellow-600" data-testid="pipeline-kpi-queued">
                    {pipelineCardsLoading ? (
                      <Loader2 className="h-5 w-5 animate-spin text-yellow-400" />
                    ) : pipelineCardsStats ? (
                      pipelineCardsStats.queued
                    ) : (
                      '–'
                    )}
                  </p>
                </div>
                <Clock className="h-8 w-8 text-yellow-400" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Main Content */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="active">Active Pipelines</TabsTrigger>
            <TabsTrigger value="templates">Templates</TabsTrigger>
            <TabsTrigger value="monitoring">Monitoring</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Pipeline Visualization</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[600px] w-full border rounded-lg bg-white">
                  {!resolvedJobId && !autoJobStatusChecked ? (
                    <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Looking for recent pipeline runs…
                    </div>
                  ) : !resolvedJobId && autoJobStatusChecked ? (
                    <div className="h-full flex flex-col items-center justify-center text-center px-6">
                      <div className="text-lg font-semibold">No runs yet</div>
                      <div className="mt-2 text-sm text-muted-foreground max-w-md">
                        Run a pipeline to see a live graph of nodes and dependencies. This page will automatically
                        render from the latest job status.
                      </div>
                      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
                        <Button onClick={handleStartNewPipeline}>
                          <Plus className="h-4 w-4 mr-2" />
                          Open Pipeline Builder
                        </Button>
                        <Button variant="outline" onClick={() => setActiveTab('templates')}>
                          Browse Templates
                        </Button>
                      </div>
                    </div>
	                  ) : resolvedJobId &&
	                    !pipelineSnapshotLoading &&
	                    !pipelineSnapshotError &&
	                    pipelineSnapshot &&
	                    !pipelineGraphAvailable ? (
                    <div className="h-full flex flex-col items-center justify-center text-center px-6">
                      <div className="text-lg font-semibold">No pipeline graph for this run yet</div>
                      <div className="mt-2 text-sm text-muted-foreground max-w-md">
                        This job is running without a persisted node/edge graph. Start a pipeline from the builder
                        (or re-run a recent plan) to populate the visualization.
                      </div>
	                      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
	                        <Button onClick={handleStartNewPipeline}>
	                          <Plus className="h-4 w-4 mr-2" />
	                          Open Pipeline Builder
	                        </Button>
	                        <Button
	                          variant="outline"
	                          onClick={() =>
	                            router.push(`/jobs/${encodeURIComponent(resolvedJobId)}`)
	                          }
	                        >
	                          View Job Details
	                        </Button>
	                      </div>
	                    </div>
                  ) : (
                    <ReactFlowProvider>
                      <PipelineVisualization
                        pipelineId={resolvedPipelineId}
                        onNodeSelect={(node) => setSelectedNodeId(node?.id || null)}
                        showTimeline={true}
                        showMinimap={true}
                        showResourceMonitor={true}
                        height="100%"
                      />
                    </ReactFlowProvider>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="active" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Active Pipelines</CardTitle>
              </CardHeader>
              <CardContent>
                {jobsLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading jobs…
                  </div>
	                ) : jobsError ? (
	                  <div className="text-sm text-red-600">Failed to load jobs: {jobsError}</div>
	                ) : jobs.length === 0 ? (
	                  <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
	                    <div className="text-sm text-muted-foreground">No pipeline runs yet.</div>
	                    <div className="flex flex-wrap items-center justify-center gap-2">
	                      <Button size="sm" onClick={handleStartNewPipeline}>
	                        <Plus className="h-4 w-4 mr-2" />
	                        Open Pipeline Builder
	                      </Button>
	                      <Button
	                        size="sm"
	                        variant="outline"
	                        onClick={() => setActiveTab('templates')}
	                      >
	                        Browse Templates
	                      </Button>
	                    </div>
	                  </div>
	                ) : activeJobs.length === 0 ? (
	                  <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
	                    <div className="text-sm text-muted-foreground">
	                      No running pipelines right now.
	                    </div>
	                    <div className="flex flex-wrap items-center justify-center gap-2">
	                      <Button size="sm" onClick={handleStartNewPipeline}>
	                        <Plus className="h-4 w-4 mr-2" />
	                        Open Pipeline Builder
	                      </Button>
	                      <Button
	                        size="sm"
	                        variant="outline"
	                        onClick={() => setActiveTab('overview')}
	                      >
	                        View overview
	                      </Button>
	                    </div>
	                  </div>
	                ) : (
	                  <div className="space-y-4">
	                    {activeJobs.slice(0, 20).map((job) => {
	                        const status = String(job.status || 'unknown').toLowerCase()
                        const name =
                          job.name ||
                          job.metadata?.builder_pipeline?.name ||
                          job.metadata?.parameters?.pipeline_id ||
                          job.prompt ||
                          job.id

                        const badgeVariant =
                          status === 'running' || status === 'retrying' || status === 'claimed'
                            ? 'default'
                            : status === 'queued' || status === 'pending'
                              ? 'outline'
                              : status === 'failed' || status === 'error' || status === 'timeout'
                                ? 'destructive'
                                : 'secondary'

                        const createdAt = job.created_at ? new Date(job.created_at) : null
                        const startedAt = job.started_at ? new Date(job.started_at) : null
                        const completedAt = job.completed_at ? new Date(job.completed_at) : null
                        const estimatedAt = job.estimated_completion ? new Date(job.estimated_completion) : null

                        const timeLineParts: string[] = []
                        if (createdAt && !Number.isNaN(createdAt.getTime())) {
                          timeLineParts.push(`Created: ${createdAt.toLocaleString()}`)
                        }
                        if (startedAt && !Number.isNaN(startedAt.getTime())) {
                          timeLineParts.push(`Started: ${startedAt.toLocaleString()}`)
                        }
                        if (estimatedAt && !Number.isNaN(estimatedAt.getTime())) {
                          timeLineParts.push(`Est. completion: ${estimatedAt.toLocaleString()}`)
                        }
                        if (completedAt && !Number.isNaN(completedAt.getTime())) {
                          timeLineParts.push(`Completed: ${completedAt.toLocaleString()}`)
                        }

	                        const userLabelRaw =
	                          job.user_id || job.metadata?.user_id || job.metadata?.user
	                        const userLabel =
	                          userLabelRaw === undefined ||
	                          userLabelRaw === null ||
	                          userLabelRaw === ''
	                            ? null
	                            : String(userLabelRaw)

                        return (
                          <div key={job.id} className="border rounded-lg p-4">
                            <div className="flex items-start justify-between gap-4">
                              <div className="space-y-2">
	                                <div className="flex items-center gap-2">
	                                  <h3 className="font-semibold break-all">{name}</h3>
	                                  <Badge variant={badgeVariant as any}>{status}</Badge>
	                                </div>
	                                {userLabel && (
	                                  <p className="text-sm text-gray-500">User: {userLabel}</p>
	                                )}
	                                {timeLineParts.length > 0 && (
	                                  <p className="text-sm text-gray-500">{timeLineParts.join(' • ')}</p>
	                                )}
                                {job.metadata?.parameters?.pipeline_id && (
                                  <p className="text-xs text-muted-foreground">
                                    pipeline_id: {String(job.metadata.parameters.pipeline_id)}
                                  </p>
                                )}
                              </div>
                              <div className="text-right flex-shrink-0">
                                {typeof job.progress === 'number' && job.progress > 0 && (
                                  <div className="mb-2">
                                    <span className="text-sm font-medium">{Math.round(job.progress)}%</span>
                                  </div>
                                )}
                                <div className="flex gap-2 justify-end">
                                  <Button size="sm" variant="outline" asChild>
                                    <Link href={`/pipeline?job_id=${encodeURIComponent(job.id)}`}>
                                      <FileText className="h-4 w-4" />
                                    </Link>
                                  </Button>
	                                  <Button size="sm" variant="outline" asChild>
	                                    <Link href={`/jobs/${encodeURIComponent(job.id)}`}>
	                                      <Settings className="h-4 w-4" />
	                                    </Link>
	                                  </Button>
                                </div>
                              </div>
                            </div>
                            {typeof job.progress === 'number' && job.progress > 0 && (
                              <div className="mt-4">
                                <div className="w-full bg-gray-200 rounded-full h-2">
                                  <div
                                    className={cn(
                                      'rounded-full h-2 transition-all',
                                      status === 'failed' ? 'bg-red-500' : status === 'completed' ? 'bg-green-500' : 'bg-blue-500',
                                    )}
                                    style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}
                                  />
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="templates" className="space-y-4">
            <WorkflowTemplatesTab />
          </TabsContent>

          <TabsContent value="monitoring" className="space-y-4">
            <PipelineQueueMonitor
              dashboardData={dashboardData}
              dashboardError={dashboardError}
              connected={dashboardConnected}
              onRefresh={refreshDashboard}
              className="w-full"
            />

            {/* Additional monitoring cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <CardHeader>
                  <CardTitle>Queue Health</CardTitle>
                </CardHeader>
                <CardContent>
                  {dashboardError ? (
                    <div className="text-sm text-red-600">No data yet: {dashboardError}</div>
                  ) : !dashboardData ? (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-2 bg-blue-500 rounded-full animate-pulse" />
                          <span className="text-sm">Running</span>
                        </div>
                        <Badge variant="outline" className="text-blue-600">
                          {dashboardData.jobMetrics.queue.running}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-2 bg-gray-400 rounded-full" />
                          <span className="text-sm">Queued</span>
                        </div>
                        <Badge variant="outline" className="text-gray-600">
                          {dashboardData.jobMetrics.queue.queued}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-2 bg-red-500 rounded-full" />
                          <span className="text-sm">Failed</span>
                        </div>
                        <Badge variant="outline" className="text-red-600">
                          {dashboardData.jobMetrics.queue.failed}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-2 bg-green-500 rounded-full" />
                          <span className="text-sm">Completed</span>
                        </div>
                        <Badge variant="outline" className="text-green-600">
                          {dashboardData.jobMetrics.queue.completed}
                        </Badge>
                      </div>
                      <Separator className="my-3" />
                      <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                        <div>
                          <span className="font-medium">Oldest queued:</span>{' '}
                          {dashboardData.jobMetrics.oldestPendingSeconds == null
                            ? '–'
                            : `${Math.floor(dashboardData.jobMetrics.oldestPendingSeconds)}s`}
                        </div>
                        <div>
                          <span className="font-medium">Jobs/min:</span>{' '}
                          {dashboardData.jobMetrics.throughputPerMinute == null
                            ? '–'
                            : dashboardData.jobMetrics.throughputPerMinute.toFixed(1)}
                        </div>
                        <div>
                          <span className="font-medium">Workers:</span>{' '}
                          {dashboardData.jobMetrics.activeWorkers == null
                            ? '–'
                            : dashboardData.jobMetrics.activeWorkers}
                        </div>
                        <div>
                          <span className="font-medium">Source:</span>{' '}
                          {dashboardData.jobMetrics.queueSource || '–'}
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Updated: {new Date(dashboardData.timestamp).toLocaleString()}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Resource Allocation</CardTitle>
                </CardHeader>
                <CardContent>
                  {dashboardError ? (
                    <div className="text-sm text-red-600">No data yet: {dashboardError}</div>
                  ) : !dashboardData ? (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  ) : (
                    <div className="space-y-4">
                      {(() => {
                        const clamp = (value: number) => Math.max(0, Math.min(100, value))

                        const cluster = (dashboardData.resourceMetrics.cluster || {}) as Record<string, any>
                        const cpuRaw = Number.isFinite(cluster.cpuUsage)
                          ? cluster.cpuUsage
                          : Number.isFinite(cluster.cpu_usage)
                            ? cluster.cpu_usage
                            : null
                        const memoryRaw = Number.isFinite(cluster.memoryUsage)
                          ? cluster.memoryUsage
                          : Number.isFinite(cluster.memory_usage)
                            ? cluster.memory_usage
                            : null

                        const gpuSamples = dashboardData.resourceMetrics.gpuSamples || []
                        const latestGpu = gpuSamples[gpuSamples.length - 1]
                        const gpuValues = latestGpu
                          ? [latestGpu.gpu1, latestGpu.gpu2, latestGpu.gpu3, latestGpu.gpu4].filter((v) =>
                              Number.isFinite(v),
                            )
                          : []
                        const gpuRaw = gpuValues.length
                          ? gpuValues.reduce((sum, value) => sum + value, 0) / gpuValues.length
                          : null

                        const primaryStorage = dashboardData.storageMetrics.primary
                        const storageRaw =
                          primaryStorage?.total && primaryStorage.total > 0
                            ? (primaryStorage.used / primaryStorage.total) * 100
                            : null

                        const cpu = cpuRaw == null ? null : clamp(cpuRaw)
                        const memory = memoryRaw == null ? null : clamp(memoryRaw)
                        const gpu = gpuRaw == null ? null : clamp(gpuRaw)
                        const storage = storageRaw == null ? null : clamp(storageRaw)

                        return (
                          <>
                            <div>
                              <div className="flex justify-between text-sm mb-1">
                                <span>CPU</span>
                                <span className="font-medium">
                                  {cpu == null ? '–' : `${cpu.toFixed(1)}%`}
                                </span>
                              </div>
                              <div className="w-full bg-gray-200 rounded-full h-2">
                                <div
                                  className="bg-blue-500 rounded-full h-2"
                                  style={{ width: `${cpu == null ? 0 : cpu}%` }}
                                />
                              </div>
                            </div>
                            <div>
                              <div className="flex justify-between text-sm mb-1">
                                <span>Memory</span>
                                <span className="font-medium">
                                  {memory == null ? '–' : `${memory.toFixed(1)}%`}
                                </span>
                              </div>
                              <div className="w-full bg-gray-200 rounded-full h-2">
                                <div
                                  className="bg-green-500 rounded-full h-2"
                                  style={{ width: `${memory == null ? 0 : memory}%` }}
                                />
                              </div>
                            </div>
                            <div>
                              <div className="flex justify-between text-sm mb-1">
                                <span>GPU</span>
                                <span className="font-medium">
                                  {gpu == null ? '–' : `${gpu.toFixed(1)}%`}
                                </span>
                              </div>
                              <div className="w-full bg-gray-200 rounded-full h-2">
                                <div
                                  className="bg-purple-500 rounded-full h-2"
                                  style={{ width: `${gpu == null ? 0 : gpu}%` }}
                                />
                              </div>
                            </div>
                            <div>
                              <div className="flex justify-between text-sm mb-1">
                                <span>Storage</span>
                                <span className="font-medium">
                                  {storage == null ? '–' : `${storage.toFixed(0)}%`}
                                </span>
                              </div>
                              <div className="w-full bg-gray-200 rounded-full h-2">
                                <div
                                  className="bg-yellow-500 rounded-full h-2"
                                  style={{ width: `${storage == null ? 0 : storage}%` }}
                                />
                              </div>
                            </div>
                            <Separator className="my-3" />
                            <div className="text-xs text-muted-foreground">
                              Active jobs: {dashboardData.jobMetrics.queue.running} • Queue length: {dashboardData.jobMetrics.queue.queued}
                            </div>
                          </>
                        )
                      })()}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {/* Copilot Panel */}
      <CopilotPanel
        isOpen={copilotOpen}
        isMinimized={copilotMinimized}
        messages={copilotMessages}
        suggestions={copilotSuggestions}
        recommendations={copilotRecommendations}
        isLoading={copilotLoading}
        filters={copilotFilters}
        onUpdateFilters={(updates) => setCopilotFilters((prev) => ({ ...prev, ...updates }))}
        onClose={() => setCopilotOpen(false)}
        onMinimize={() => setCopilotMinimized(!copilotMinimized)}
        onSendMessage={handleCopilotMessage}
        onInsertParameter={(suggestion) => {
          console.log('Inserting parameter:', suggestion)
          // Implement parameter insertion logic
        }}
        onInsertMethod={(recommendation) => {
          console.log('Inserting method:', recommendation)
          // Implement method insertion logic
        }}
        onClearMessages={() => {
          setCopilotMessages([])
          setCopilotSuggestions([])
          setCopilotRecommendations([])
          setCopilotLastQuery(null)
          setCopilotError(null)
        }}
      />
      </div>
    </NavigationWrapper>
  )
}
