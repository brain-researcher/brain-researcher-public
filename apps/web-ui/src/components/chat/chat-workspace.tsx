'use client'

import { useCallback, useEffect, useMemo, useRef, useState, useId } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { Bot, FileText, Workflow, Loader2, WifiOff, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ToastAction } from '@/components/ui/toast'
import { ChatComposer } from './chat-composer'
import { MessageList } from './message-list'
import { StudioWelcomeScreen } from './studio-welcome-screen'
import { EvidenceRail } from './evidence-rail'
import { DiagnosisCard } from './diagnosis-card'
import { AttemptSwitcher } from './attempt-switcher'
import { StudioPlanPanel } from './studio-plan-panel'
import { Brain3D } from '@/components/brain/Brain3D'
import { VisualizationPanel } from '@/components/visualization/visualization-panel'
import { CopilotPanel } from '@/components/copilot/copilot-panel'
import { ShareModal } from '@/components/share/share-modal'
import { McpConfigurationModal } from '@/components/mcp/mcp-configuration-modal'
import { StepsList } from '@/components/landing/StepsList'
import { AnalysisStreamEventsPanel } from '@/components/progress/analysis-stream-events-panel'
import { RealTimeProgress } from '@/components/ui/real-time-progress'
import { LiveRegion, ScreenReaderOnly } from '@/components/accessibility'
import { useChat } from '@/hooks/use-chat'
import { useCopilot } from '@/hooks/use-copilot'
import { useWebSocket } from '@/lib/websocket-manager'
import {
  buildCheckpointMessagePatch,
  extractCheckpointIdFromBoundary,
  normalizeCheckpointMetadata,
} from '@/lib/chat-checkpoints'
import { useAriaLive } from '@/hooks/use-aria-live'
import { useRunCard, invalidateRunCardCache } from '@/hooks/use-run-card'
import { ChatRunCard, ExecutionStep, Message } from '@/types/chat'
import { ANALYSIS_TYPES } from '@/config/analysis-presets'
import { fetchWorkflowGraph, fetchBrainMaps } from '@/lib/visualizations'
import { KnowledgeGraph, BrainMapData } from '@/types/visualization'
import { API_ENDPOINTS } from '@/lib/config'
import { resolveRealtimeWsBaseUrl, serviceEndpoints } from '@/lib/service-endpoints'
import {
  readCreditsBalance,
  subscribeCreditsUpdates,
  syncCreditsBalanceFromServer,
} from '@/lib/credits'
import { formatDuration } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import { WorkspaceSwitcher } from '@/components/workspace/workspace-switcher'
import {
  extractArtifactName,
  extractArtifactUrl,
  isBrainMapArtifact,
  pickPreferredBrainMapArtifact,
} from '@/lib/brain-map-artifacts'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { openSSE } from '@/lib/api'
import { buildStudioDatasetsPickerHref } from '@/lib/studio-navigation'
import {
  applyRepairPlanPatchToDraft,
  type RepairProposal,
} from '@/lib/chat-repair'
import { buildLatestPlanContinuationPrompt } from '@/lib/mcp-plan-handoff'
import {
  buildRepairInputArtifacts,
  deriveRepairSignalSummary,
} from '@/lib/studio-repair-context'
import type { AnalysisStreamEventV1, ArtifactV1 } from '@/types/contracts.generated'
import type { Edge, Node } from 'reactflow'
import type { AnalysisDetail } from '@/types/analysis'
import type { EvidenceData } from '@/lib/evidence-rail-integration'
import { ChevronDown, ChevronUp, Copy, Download, ExternalLink, Terminal, Wrench, X } from 'lucide-react'

type ChatMode = 'chat' | 'coding' | 'neuro'

type PipelineSnapshot = {
  nodes: Node[]
  edges: Edge[]
}

type PipelineLabelInfo = {
  pipelineId: string
  title: string
}

type PlanComposerContext = {
  datasetId: string | null
  datasetVersion: string | null
  datasetResourceSummary?: {
    selectedVersion: string | null
    readinessStatus: string | null
    bucketCheckState: string | null
    versionCheckMode: string | null
    resolvedVersion: string | null
    subjectsCount: number | null
    totalMatchedFiles: number | null
    s3Uri: string | null
    openneuroUrl: string | null
    sourceRepoUrl: string | null
  }
  analysisId: string | null
  analysisLabel: string | null
  pipelineId: string | null
  pipelineLabel: string | null
}

type StreamLogLine = {
  timestamp: string
  stream: 'stdout' | 'stderr'
  line: string
}

type StreamArtifactEntry = {
  timestamp: string
  artifact: ArtifactV1
}

type StudioRepairContext = {
  run_id: string
  thread_id: string | null
  analysis_id: string | null
  tool_name: string | null
  error_type: string | null
  error_message: string | null
  repair_attempt_count: number
  failing_step: {
    id: string | null
    name: string | null
    tool: string | null
    status: string | null
    error: string | null
  } | null
  diagnosis: {
    title: string
    message: string | null
    what_happened: string[]
    suggested_actions: string[]
  }
  primary_violation?: {
    code: string | null
    message: string | null
    severity: string | null
    blocking: boolean
    suggested_fix: string | null
    where: {
      step_id: string | null
      stage: string | null
      component: string | null
      path: string | null
    } | null
  } | null
  diagnostics_codes?: string[]
  sample_errors?: string[]
  plan_snapshot: {
    dataset_id: string | null
    dataset_version: string | null
    analysis_id: string | null
    pipeline_id: string | null
    parameter_values: Record<string, unknown>
    dataset_resource_summary?: PlanComposerContext['datasetResourceSummary']
  }
  input_artifacts: Array<Record<string, unknown>>
  log_tail: string[]
}

const PIPELINE_LABELS_BY_ID = new Map<string, PipelineLabelInfo>(
  ANALYSIS_TYPES.flatMap((analysis) =>
    analysis.pipelines.map((pipeline) => [
      pipeline.id,
      {
        pipelineId: pipeline.id,
        title: `${analysis.label} · ${pipeline.label}`,
      },
    ]),
  ),
)

const KNOWN_PIPELINE_IDS = new Set(
  ANALYSIS_TYPES.flatMap((analysis) => analysis.pipelines.map((pipeline) => pipeline.id)),
)

const PIPELINE_SNAPSHOT_KEY = 'br:pipeline-builder:snapshot'
const SHARED_PLAN_STORAGE_KEY = 'br:plan:last'

function resourceSummaryEqual(
  left: PlanComposerContext['datasetResourceSummary'],
  right: PlanComposerContext['datasetResourceSummary'],
): boolean {
  if (!left && !right) return true
  if (!left || !right) return false
  return (
    left.selectedVersion === right.selectedVersion &&
    left.readinessStatus === right.readinessStatus &&
    left.bucketCheckState === right.bucketCheckState &&
    left.versionCheckMode === right.versionCheckMode &&
    left.resolvedVersion === right.resolvedVersion &&
    left.subjectsCount === right.subjectsCount &&
    left.totalMatchedFiles === right.totalMatchedFiles &&
    left.s3Uri === right.s3Uri &&
    left.openneuroUrl === right.openneuroUrl &&
    left.sourceRepoUrl === right.sourceRepoUrl
  )
}

function getString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function getRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function parseTemplateId(value: unknown): { analysisId: string; pipelineId: string } | null {
  const raw = getString(value)
  if (!raw) return null
  const parts = raw.split(/[:/]/).filter(Boolean)
  if (parts.length !== 2) return null
  const [analysisId, pipelineId] = parts
  if (!analysisId || !pipelineId) return null
  return { analysisId, pipelineId }
}

function findSuggestedPipelineId(message: Message): string | null {
  const meta = message.metadata
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null

  const pipelineDirect =
    getString((meta as any).pipeline_id) ||
    getString((meta as any).pipelineId) ||
    getString((meta as any).pipeline)
  if (pipelineDirect && KNOWN_PIPELINE_IDS.has(pipelineDirect)) return pipelineDirect

  const templateDirect =
    parseTemplateId((meta as any).template_id) || parseTemplateId((meta as any).templateId)
  if (templateDirect && KNOWN_PIPELINE_IDS.has(templateDirect.pipelineId)) {
    return templateDirect.pipelineId
  }

  const toolCalls = (meta as any).tool_calls
  if (Array.isArray(toolCalls)) {
    for (const tc of toolCalls) {
      const pipelineCandidate =
        getString(tc?.pipeline_id) || getString(tc?.pipelineId) || getString(tc?.pipeline)
      if (pipelineCandidate && KNOWN_PIPELINE_IDS.has(pipelineCandidate)) return pipelineCandidate

      const fromTemplate = parseTemplateId(tc?.template_id) || parseTemplateId(tc?.templateId)
      if (fromTemplate && KNOWN_PIPELINE_IDS.has(fromTemplate.pipelineId)) return fromTemplate.pipelineId

      const result = tc?.result ?? tc?.output
      if (result && typeof result === 'object' && !Array.isArray(result)) {
        const pipelineFromResult =
          getString((result as any).pipeline_id) ||
          getString((result as any).pipelineId) ||
          getString((result as any).pipeline)
        if (pipelineFromResult && KNOWN_PIPELINE_IDS.has(pipelineFromResult)) {
          return pipelineFromResult
        }

        const templateFromResult =
          parseTemplateId((result as any).template_id) || parseTemplateId((result as any).templateId)
        if (templateFromResult && KNOWN_PIPELINE_IDS.has(templateFromResult.pipelineId)) {
          return templateFromResult.pipelineId
        }
      }
    }
  }

  return null
}

const extractSummaryBullets = (raw: unknown): string[] => {
  const text = typeof raw === 'string' ? raw.replace(/\r/g, '').trim() : ''
  if (!text) return []

  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  const bulletLines = lines
    .filter((line) => /^[-*•]\s+/.test(line))
    .map((line) => line.replace(/^[-*•]\s+/, '').trim())
    .filter(Boolean)

  if (bulletLines.length >= 2) return bulletLines.slice(0, 3)

  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)

  if (sentences.length === 0) return []
  return sentences.slice(0, 3)
}

const scoreKeyArtifact = (artifact: { name?: string; type?: string }): number => {
  const name = String(artifact?.name ?? '').toLowerCase()
  const type = String(artifact?.type ?? '').toLowerCase()

  if (type.includes('log') || name.includes('stdout') || name.includes('stderr') || name.endsWith('.log')) {
    return -100
  }

  let score = 0
  if (name.includes('report') || name.endsWith('.html') || name.endsWith('.pdf')) score += 50
  if (name.includes('methods') || name.endsWith('.md') || name.endsWith('.txt')) score += 35
  if (name.endsWith('.csv') || name.endsWith('.tsv')) score += 30
  if (name.endsWith('.json')) score += 20
  if (name.endsWith('.nii') || name.endsWith('.nii.gz')) score -= 5
  if (type === 'html' || type === 'report') score += 10
  if (type === 'table') score += 5
  if (type === 'image') score += 2

  return score
}

const buildSnapshotFromSteps = (steps: ExecutionStep[]): PipelineSnapshot => {
  const nodes: Node[] = steps.map((step, index) => {
    const fallbackId = `step-${index + 1}`
    const nodeId = step.id?.trim() ? step.id : fallbackId

    return {
      id: nodeId,
      type: 'pipeline',
      position: { x: 140 + index * 240, y: 80 },
      data: {
        label: step.name || step.tool || `Step ${index + 1}`,
        status: step.status,
        tool: { name: step.tool },
        summary: step.preview,
        parameters: step.args,
        type: 'process',
        metadata: {
          args: step.args,
          preview: step.preview,
        }
      }
    }
  })

  const edges: Edge[] = nodes.slice(1).map((node, idx) => {
    const previous = nodes[idx]
    return {
      id: `edge-${previous.id}-${node.id}`,
      source: previous.id,
      target: node.id,
      type: 'smoothstep'
    }
  })

  return { nodes, edges }
}

type DiagnosisDetails = {
  whatHappened: string[]
  suggestedActions: string[]
}

const buildDiagnosisDetailsFromEvidence = (evidenceData: EvidenceData | null): DiagnosisDetails => {
  const whatHappened: string[] = []
  const suggestedActions: string[] = []

  if (!evidenceData) {
    return { whatHappened, suggestedActions }
  }

  const violations = Array.isArray(evidenceData.violations) ? evidenceData.violations : []
  const blockingViolations = violations.filter(
    (violation) =>
      violation?.blocking ||
      violation?.severity === 'error' ||
      violation?.severity === 'critical',
  )
  const primaryViolations = (blockingViolations.length ? blockingViolations : violations).slice(0, 6)

  for (const violation of primaryViolations) {
    const whereParts: string[] = []
    const where = violation.where
    if (where?.step_id) whereParts.push(`step ${where.step_id}`)
    if (where?.stage) whereParts.push(where.stage)
    if (where?.component) whereParts.push(where.component)
    if (where?.path) whereParts.push(where.path)
    const whereLabel = whereParts.length ? ` (${whereParts.join(', ')})` : ''

    const code = typeof violation.code === 'string' ? violation.code : 'unknown'
    const message = typeof violation.message === 'string' ? violation.message : ''
    whatHappened.push(`${code}: ${message}${whereLabel}`.trim())

    if (typeof violation.suggested_fix === 'string' && violation.suggested_fix.trim()) {
      suggestedActions.push(violation.suggested_fix.trim())
    }
  }

  const steps = Array.isArray(evidenceData.steps) ? evidenceData.steps : []
  const failedSteps = steps
    .filter((step) => {
      const state = typeof step.state === 'string' ? step.state.toLowerCase() : ''
      return state === 'failed' || state === 'error'
    })
    .slice(0, 4)
  for (const step of failedSteps) {
    const label = step.name || step.stepId || 'step'
    const err = typeof step.error === 'string' && step.error.trim() ? step.error.trim() : ''
    whatHappened.push(err ? `Step "${label}": ${err}` : `Step "${label}" failed`)
  }

  const nextActions = evidenceData.diagnosticsSummary?.recommended_next_actions
  if (Array.isArray(nextActions)) {
    for (const item of nextActions.slice(0, 6)) {
      if (!item || typeof item.action !== 'string' || !item.action.trim()) continue
      suggestedActions.push(item.action.trim())
    }
  }

  return {
    whatHappened: Array.from(new Set(whatHappened.filter(Boolean))),
    suggestedActions: Array.from(new Set(suggestedActions.filter(Boolean))),
  }
}

interface ChatWorkspaceProps {
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

export function ChatWorkspace({
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
}: ChatWorkspaceProps) {
  const [chatMode, setChatMode] = useState<ChatMode>('chat')
  const {
    messages,
    isLoading,
    submitPrompt,
    cancelExecution,
    replaceMessages,
    addMessage,
    setCodingMode,
    threadId: chatThreadId,
    connectionState,
    resetConnectionState,
  } = useChat()
  const { data: session } = useSession()
  const { enabled: advancedMode, hydrated: advancedModeHydrated } = useAdvancedMode()
  const codingMode = chatMode === 'coding'
  const [canvasTab, setCanvasTab] = useState<'plan' | 'results' | 'charts' | 'steps'>(() => {
    if (initialCanvasTab) return initialCanvasTab
    // Make verification visible by default when opening Studio without a specific run.
    return analysisId ? 'results' : 'plan'
  })
  const defaultRepoRoot = process.env.NEXT_PUBLIC_REPO_ROOT
  const [explainOnly, setExplainOnly] = useState(false)
  const [repoRootInput, setRepoRootInput] = useState<string>(defaultRepoRoot || '')
  const [filePathsInput, setFilePathsInput] = useState<string>('')
  const defaultT1w = process.env.NEXT_PUBLIC_T1W_IMAGE
  const defaultStatMap = process.env.NEXT_PUBLIC_STAT_MAP
  const defaultBold = process.env.NEXT_PUBLIC_BOLD_FILE
  const defaultMask = process.env.NEXT_PUBLIC_MASK_FILE
  const copilot = useCopilot()
  const { announceLoading, announceComplete, announceError } = useAriaLive()
  const router = useRouter()
  const { toast } = useToast()
  const [currentRunCard, setCurrentRunCard] = useState<ChatRunCard | undefined>()
  const [showVisualizations, setShowVisualizations] = useState(false)
  const [promptSubmitted, setPromptSubmitted] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | undefined>()
  const [showProgress, setShowProgress] = useState(false)
  const [lastFailure, setLastFailure] = useState<{ jobId: string; message: string } | null>(null)
  const [activeRepairContext, setActiveRepairContext] = useState<StudioRepairContext | null>(null)
  const [repairAttemptsByRunId, setRepairAttemptsByRunId] = useState<Record<string, number>>({})
  const [localThreadId, setLocalThreadId] = useState<string | undefined>()
  const [resumeCheckpointId, setResumeCheckpointId] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState('')
  const [latestSnapshot, setLatestSnapshot] = useState<PipelineSnapshot | null>(null)
  const [planPanelNonce, setPlanPanelNonce] = useState(0)
  const [planValidationNonce, setPlanValidationNonce] = useState(0)
  const [planEditing, setPlanEditing] = useState(false)
  const [planIsEmpty, setPlanIsEmpty] = useState<boolean>(
    () => !datasetId && !conceptId && !pipeline,
  )
  const [planComposerContext, setPlanComposerContext] = useState<PlanComposerContext>({
    datasetId: datasetId ?? null,
    datasetVersion: datasetVersion ?? null,
    analysisId: null,
    analysisLabel: null,
    pipelineId: pipeline ?? null,
    pipelineLabel: pipeline
      ? (PIPELINE_LABELS_BY_ID.get(pipeline)?.title ?? pipeline)
      : null,
  })
  const [mcpModalOpen, setMcpModalOpen] = useState(false)
  const hasAutoOpenedMcpRef = useRef(false)
  const editingStartedAtRef = useRef<number | null>(null)
  const autoPersistedThreadInUrlRef = useRef<string | null>(null)
  const skipHistoryLoadForThreadRef = useRef<string | null>(null)
  const [pendingPlanSuggestion, setPendingPlanSuggestion] = useState<{
    pipelineId: string
    messageId?: string
  } | null>(null)
  const [replacePlanDialogOpen, setReplacePlanDialogOpen] = useState(false)
  const [replacePlanCandidateId, setReplacePlanCandidateId] = useState<string | null>(null)
  const replacePlanUndoRef = useRef<{
    search: string
    planDraftRaw: string | null
  } | null>(null)
  const lastSuggestionMessageIdRef = useRef<string | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const [shareModalOpen, setShareModalOpen] = useState(false)
  const [streamEventsOpen, setStreamEventsOpen] = useState(false)
  const [streamLogLines, setStreamLogLines] = useState<StreamLogLine[]>([])
  const [streamArtifacts, setStreamArtifacts] = useState<StreamArtifactEntry[]>([])
  const [streamUnknownCount, setStreamUnknownCount] = useState(0)
  const [artifactPreviewOpen, setArtifactPreviewOpen] = useState(false)
  const [artifactPreviewTarget, setArtifactPreviewTarget] = useState<{
    name: string
    url: string
  } | null>(null)
  const [artifactPreviewBody, setArtifactPreviewBody] = useState<string | null>(null)
  const [artifactPreviewError, setArtifactPreviewError] = useState<string | null>(null)
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false)
  const [selectedViewerArtifact, setSelectedViewerArtifact] = useState<{
    name: string
    url: string
    analysisId: string | null
  } | null>(null)
  const [evidenceRailData, setEvidenceRailData] = useState<EvidenceData | null>(null)
  const [analysisDetail, setAnalysisDetail] = useState<AnalysisDetail | null>(null)
  const [analysisDetailError, setAnalysisDetailError] = useState<string | null>(null)
  const [analysisDetailLoading, setAnalysisDetailLoading] = useState(false)
  const [consoleOpen, setConsoleOpen] = useState(false)
  const [consoleDismissedForJobId, setConsoleDismissedForJobId] = useState<string | null>(null)
  const [kgSuggestionsCount, setKgSuggestionsCount] = useState<number | null>(null)
  const [visualizationData, setVisualizationData] = useState<{
    knowledgeGraph: KnowledgeGraph | null
    brainMaps: BrainMapData[]
  }>({
    knowledgeGraph: null,
    brainMaps: []
  })
  const [threadLoading, setThreadLoading] = useState(false)
  const [threadLoadError, setThreadLoadError] = useState<string | null>(null)
  const [copilotInjectedText, setCopilotInjectedText] = useState<string | null>(null)
  const reactUserId = useId()
  const studioBrainViewerEnabled = (() => {
    const raw = (process.env.NEXT_PUBLIC_ENABLE_STUDIO_BRAIN_VIEWER_BETA || '').trim().toLowerCase()
    if (raw) {
      return !['0', 'false', 'off'].includes(raw)
    }
    return process.env.NODE_ENV !== 'production'
  })()
  const stableUserId = `user-${reactUserId.replace(/[:]/g, '')}`
  const wsUserId = session?.user?.id || session?.user?.email || stableUserId
  const wsUserName = session?.user?.name || session?.user?.email || 'Anonymous'
  const hasExplicitThreadParam = typeof threadId === 'string' && threadId.trim().length > 0
  const effectiveThreadId = threadId || localThreadId || chatThreadId
  const autoOpenedViewerAnalysisIdsRef = useRef<Set<string>>(new Set())

  const persistCanvasTab = useCallback(
    (nextTab: 'plan' | 'results' | 'charts' | 'steps') => {
      try {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)
        params.set('tab', nextTab)
        const query = params.toString()
        router.replace(query ? `/studio?${query}` : `/studio?tab=${nextTab}`)
      } catch (error) {
        console.warn('Failed to persist Studio tab in URL', error)
      }
    },
    [router],
  )

  useEffect(() => {
    setPlanComposerContext((prev) => {
      const nextDataset = datasetId ?? null
      const nextVersion = datasetVersion ?? null
      const nextPipeline = prev.pipelineId ?? pipeline ?? null
      const nextPipelineLabel = nextPipeline
        ? (PIPELINE_LABELS_BY_ID.get(nextPipeline)?.title ?? nextPipeline)
        : null
      if (
        prev.datasetId === nextDataset &&
        prev.datasetVersion === nextVersion &&
        prev.pipelineId === nextPipeline &&
        prev.pipelineLabel === nextPipelineLabel
      ) {
        return prev
      }
      return {
        ...prev,
        datasetId: nextDataset,
        datasetVersion: nextVersion,
        datasetResourceSummary:
          nextDataset && prev.datasetId === nextDataset ? prev.datasetResourceSummary : undefined,
        pipelineId: nextPipeline,
        pipelineLabel: nextPipelineLabel,
      }
    })
  }, [datasetId, datasetVersion, pipeline])

  const handlePlanContextChange = useCallback(
    (next: {
      datasetId: string | null
      datasetVersion: string | null
      analysisId: string | null
      analysisLabel: string | null
      pipelineId: string | null
      pipelineLabel: string | null
      datasetResourceSummary?: {
        selectedVersion: string | null
        readinessStatus: string | null
        bucketCheckState: string | null
        versionCheckMode: string | null
        resolvedVersion: string | null
        subjectsCount: number | null
        totalMatchedFiles: number | null
        s3Uri: string | null
        openneuroUrl: string | null
        sourceRepoUrl: string | null
      }
    }) => {
      setPlanComposerContext((prev) => {
        const pipelineId = next.pipelineId ?? null
        const resolvedPipelineLabel = pipelineId
          ? (PIPELINE_LABELS_BY_ID.get(pipelineId)?.title ?? pipelineId)
          : null
        const nextSummary = next.datasetResourceSummary ?? prev.datasetResourceSummary
        const nextState: PlanComposerContext = {
          ...prev,
          ...next,
          datasetResourceSummary: nextSummary,
          pipelineLabel: resolvedPipelineLabel,
          analysisLabel: next.analysisId ?? null,
        }
        if (
          prev.datasetId === nextState.datasetId &&
          prev.datasetVersion === nextState.datasetVersion &&
          prev.analysisId === nextState.analysisId &&
          prev.analysisLabel === nextState.analysisLabel &&
          prev.pipelineId === nextState.pipelineId &&
          prev.pipelineLabel === nextState.pipelineLabel &&
          resourceSummaryEqual(prev.datasetResourceSummary, nextState.datasetResourceSummary)
        ) {
          return prev
        }
        return nextState
      })
    },
    [],
  )

  // Track which job ID to fetch run card for (set when job completes)
  const [completedJobId, setCompletedJobId] = useState<string | undefined>(() => analysisId)
  const evidenceJobId = activeJobId || completedJobId
  const currentPlanRecord = getRecord(analysisDetail?.plan)
  const currentPlanHandoff =
    getRecord(currentPlanRecord?.handoff_pack) || getRecord(currentPlanRecord?.handoff)
  const currentJobRecord = getRecord(analysisDetail?.job)
  const currentJobPlanRecord =
    getRecord(currentJobRecord?.plan_of_record) || getRecord(currentJobRecord?.plan)
  const currentJobPlanSummary = getRecord(currentJobRecord?.plan_summary)
  const currentPlanId =
    getString(currentPlanRecord?.plan_id) ||
    getString(currentPlanHandoff?.plan_id) ||
    getString(currentJobPlanRecord?.plan_id) ||
    getString(currentJobPlanSummary?.plan_id) ||
    getString(currentPlanRecord?.analysis_id)
  const currentWorkflowId =
    getString(currentPlanHandoff?.workflow_id) ||
    getString(currentPlanHandoff?.chosen_tool) ||
    planComposerContext.pipelineId ||
    pipeline ||
    getString(currentPlanRecord?.workflow_id)
  const currentWorkflowLabel =
    planComposerContext.pipelineLabel ||
    (currentWorkflowId
      ? PIPELINE_LABELS_BY_ID.get(currentWorkflowId)?.title || currentWorkflowId
      : getString(currentPlanRecord?.workflow_id))
  const currentPlanDatasetId =
    getString(currentPlanRecord?.dataset_ref) ||
    planComposerContext.datasetId ||
    datasetId ||
    null
  const currentPlanDatasetVersion =
    planComposerContext.datasetVersion ||
    datasetVersion ||
    null
  const mcpContinuationPrompt = buildLatestPlanContinuationPrompt({
    planId: currentPlanId,
    threadId: effectiveThreadId || null,
    workflowId: currentWorkflowId,
    workflowLabel: currentWorkflowLabel,
    datasetId: currentPlanDatasetId,
    datasetVersion: currentPlanDatasetVersion,
    handoffPack: currentPlanHandoff,
  })
  const [creditsBalance, setCreditsBalance] = useState<number | null>(null)
  const canvasTabColumnsClass = advancedMode ? 'grid-cols-4' : 'grid-cols-3'

  const openBrainMapArtifact = useCallback(
    (
      artifact: unknown,
      analysisIdForArtifact?: string | null,
      options?: { markAutoOpened?: boolean },
    ): boolean => {
      const url = extractArtifactUrl(artifact)
      if (!url) return false

      const name = extractArtifactName(artifact) ?? 'Brain map'
      const resolvedAnalysisId =
        typeof analysisIdForArtifact === 'string' && analysisIdForArtifact.trim().length > 0
          ? analysisIdForArtifact.trim()
          : evidenceJobId || analysisId || null

      setSelectedViewerArtifact({ name, url, analysisId: resolvedAnalysisId })
      setCanvasTab('charts')
      persistCanvasTab('charts')

      if (options?.markAutoOpened && resolvedAnalysisId) {
        autoOpenedViewerAnalysisIdsRef.current.add(resolvedAnalysisId)
      }

      return true
    },
    [analysisId, evidenceJobId, persistCanvasTab],
  )

  useEffect(() => {
    if (!initialCanvasTab) return
    setCanvasTab(initialCanvasTab)
  }, [initialCanvasTab])

  useEffect(() => {
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    let cancelled = false
    const refresh = () => {
      if (!cancelled) setCreditsBalance(readCreditsBalance())
    }

    const refreshRemote = async () => {
      await syncCreditsBalanceFromServer()
      refresh()
    }

    refresh()
    void refreshRemote()

    const unsubscribe = subscribeCreditsUpdates(refresh)
    const onVisible = () => {
      if (!document.hidden) {
        void refreshRemote()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      unsubscribe()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  useEffect(() => {
    const authed = Boolean(session?.user) || (process.env.NODE_ENV !== 'production' && document.cookie.split(';').some((c) => c.trim() === 'br_e2e_auth=1'))
    if (!authed) {
      setKgSuggestionsCount(null)
      return
    }

    let cancelled = false
    const loadSuggestions = async () => {
      try {
        const res = await fetch('/api/neurokg/suggestions', { cache: 'no-store' })
        if (!res.ok) {
          if (!cancelled) setKgSuggestionsCount(0)
          return
        }
        const data = (await res.json().catch(() => null)) as any
        const count = typeof data?.count === 'number' ? data.count : Array.isArray(data?.items) ? data.items.length : 0
        if (!cancelled) setKgSuggestionsCount(count)
      } catch {
        if (!cancelled) setKgSuggestionsCount(0)
      }
    }

    void loadSuggestions()
    return () => {
      cancelled = true
    }
  }, [completedJobId, session?.user])

  useEffect(() => {
    if (!evidenceJobId || (showProgress && activeJobId)) {
      setAnalysisDetail(null)
      setAnalysisDetailError(null)
      setAnalysisDetailLoading(false)
      return
    }

    let cancelled = false
    setAnalysisDetailLoading(true)
    setAnalysisDetailError(null)

    void (async () => {
      try {
        const res = await fetch(`/api/analyses/${encodeURIComponent(evidenceJobId)}`, {
          cache: 'no-store',
        })
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load run (${res.status})`)
        }

        const detail = (await res.json()) as AnalysisDetail
        if (cancelled) return
        setAnalysisDetail(detail)
      } catch (error) {
        if (cancelled) return
        setAnalysisDetail(null)
        setAnalysisDetailError(error instanceof Error ? error.message : String(error))
      } finally {
        if (cancelled) return
        setAnalysisDetailLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [activeJobId, evidenceJobId, showProgress])

  useEffect(() => {
    if (!analysisId) return
    if (analysisId === activeJobId) return
    setCompletedJobId(analysisId)
    setCurrentRunCard(undefined)
    setLatestSnapshot(null)
    setShowVisualizations(false)
    setVisualizationData({ knowledgeGraph: null, brainMaps: [] })
    setSelectedViewerArtifact(null)
    setShareModalOpen(false)
    setStreamEventsOpen(false)
    setStreamLogLines([])
    setStreamArtifacts([])
    setStreamUnknownCount(0)
  }, [analysisId, activeJobId])

  // Typed analysis stream → lightweight buffers for Console/Artifacts wiring.
  useEffect(() => {
    setStreamLogLines([])
    setStreamArtifacts([])
    setStreamUnknownCount(0)

    if (!evidenceJobId) return

    let cancelled = false
    let sse: EventSource | null = null

    const endpoint = `/api/analyses/${encodeURIComponent(evidenceJobId)}/analysis-stream`

    const handle = (evt: MessageEvent) => {
      if (cancelled) return
      const rawText = typeof evt.data === 'string' ? evt.data : ''
      if (!rawText) return
      let parsed: unknown = null
      try {
        parsed = JSON.parse(rawText)
      } catch {
        setStreamUnknownCount((prev) => prev + 1)
        return
      }

      if (!parsed || typeof parsed !== 'object') {
        setStreamUnknownCount((prev) => prev + 1)
        return
      }

      const event = parsed as AnalysisStreamEventV1 & Record<string, any>
      const eventType = event.event_type
      if (typeof eventType !== 'string') {
        setStreamUnknownCount((prev) => prev + 1)
        return
      }

      if (eventType === 'log.line') {
        const stream = event.payload?.stream
        const line = event.payload?.line
        if ((stream === 'stdout' || stream === 'stderr') && typeof line === 'string') {
          setStreamLogLines((prev) => {
            const next = [...prev, { timestamp: event.timestamp, stream, line }]
            return next.length > 250 ? next.slice(next.length - 250) : next
          })
        } else {
          setStreamUnknownCount((prev) => prev + 1)
        }
        return
      }

      if (eventType === 'artifact.written') {
        const artifact = event.payload?.artifact as ArtifactV1 | undefined
        if (artifact && typeof artifact === 'object' && typeof artifact.uri === 'string') {
          setStreamArtifacts((prev) => {
            const next = [...prev, { timestamp: event.timestamp, artifact }]
            return next.length > 100 ? next.slice(next.length - 100) : next
          })
        } else {
          setStreamUnknownCount((prev) => prev + 1)
        }
        return
      }

      // For the Console summary we only surface a subset of event types; count everything else
      // as "unknown" so the UI can still indicate activity without breaking.
      setStreamUnknownCount((prev) => prev + 1)
    }

    try {
      sse = openSSE(endpoint)
    } catch (error) {
      console.warn('Failed to open analysis stream SSE:', error)
      return
    }

    const knownEventNames = [
      'analysis_stream_event',
      'job.started',
      'tool.call.started',
      'tool.call.finished',
      'artifact.written',
      'log.line',
      'observation.appended',
      'analysis.completed',
      'error',
    ]

    for (const name of knownEventNames) {
      sse.addEventListener(name, handle as any)
    }
    sse.onmessage = handle as any
    sse.onerror = () => {
      if (cancelled) return
      setStreamUnknownCount((prev) => prev + 1)
    }

    return () => {
      cancelled = true
      if (sse) {
        try {
          sse.close()
        } catch {
          // ignore
        }
      }
    }
  }, [evidenceJobId])

  useEffect(() => {
    if (!artifactPreviewOpen || !artifactPreviewTarget?.url) return
    let cancelled = false
    const controller = new AbortController()

    setArtifactPreviewLoading(true)
    setArtifactPreviewBody(null)
    setArtifactPreviewError(null)

    void (async () => {
      try {
        const res = await fetch(artifactPreviewTarget.url, { signal: controller.signal })
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `HTTP ${res.status}`)
        }
        const text = await res.text()
        if (cancelled) return
        setArtifactPreviewBody(text)
      } catch (error) {
        if (cancelled) return
        setArtifactPreviewError(error instanceof Error ? error.message : String(error))
      } finally {
        if (cancelled) return
        setArtifactPreviewLoading(false)
      }
    })()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [artifactPreviewOpen, artifactPreviewTarget?.url])

  useEffect(() => {
    if (!advancedModeHydrated) return
    if (!advancedMode && canvasTab === 'steps') {
      setCanvasTab('results')
    }
  }, [advancedModeHydrated, advancedMode, canvasTab])

  // Fetch run card from Evidence Rail API when job completes
  const {
    runCard: fetchedRunCard,
    isLoading: isRunCardLoading,
    error: runCardError,
    refetch: refetchRunCard,
  } = useRunCard(completedJobId, {
    fetchOnMount: true,
    onSuccess: (runCard) => {
      // Use fetched run card if available
      setCurrentRunCard(runCard)
    },
    onError: (error) => {
      console.warn('Failed to fetch run card from API, using local data:', error)
      // Keep the locally-constructed run card as fallback
    },
  })

  // Keep old codingMode state in sync for legacy paths
  useEffect(() => {
    if (typeof setCodingMode === 'function') {
      setCodingMode(chatMode === 'coding')
    }
  }, [chatMode, setCodingMode])

  // WebSocket for real-time updates
  const orchestratorWsBase = resolveRealtimeWsBaseUrl()
  const wsJobsPath = `${orchestratorWsBase.replace(/\/$/, '')}/jobs`

  const wsOptions = activeJobId
    ? {
        url: wsJobsPath,
        documentId: activeJobId,
        userId: wsUserId,
        userName: wsUserName,
        autoConnect: true,
      }
    : undefined

  const webSocket = useWebSocket(wsOptions || {
    url: '',
    documentId: '',
    userId: '',
    userName: '',
    autoConnect: false
  }, {
    onMessage: (message) => {
      if (message.type === 'progress_update' && message.data) {
        // Handle real-time progress updates
        console.log('Progress update:', message.data)
      } else if (message.type === 'execution_complete') {
        setActiveJobId(undefined)
        setShowProgress(false)
        setShowVisualizations(true)
      }
    },
    onError: (error) => {
      console.warn('WebSocket error:', error)
    }
  })
  const disconnectWebSocket = webSocket.disconnect

  // Submit initial prompt if provided
  const buildParameters = useCallback((extra?: Record<string, any>) => {
    const merged = { ...(prefillParameters || {}), ...(extra || {}) }
    if (scenarioId) {
      merged.scenario_id = scenarioId
    }
    return Object.keys(merged).length ? merged : undefined
  }, [scenarioId, prefillParameters])

  useEffect(() => {
    if (effectiveThreadId) return
    if (initialPrompt && !promptSubmitted) {
        submitPrompt(initialPrompt, [], {
          pipeline,
          datasetId,
          datasetVersion,
          parameters: buildParameters(),
          systemPrompt,
          scenarioId,
          resumeCheckpointId,
          threadId: effectiveThreadId,
        })
      setPromptSubmitted(true)
    }
  }, [initialPrompt, pipeline, datasetId, datasetVersion, submitPrompt, promptSubmitted, systemPrompt, scenarioId, buildParameters, resumeCheckpointId, effectiveThreadId])

  useEffect(() => {
    if (hasExplicitThreadParam) return
    if (activeJobId) return
    const resolvedThreadId =
      typeof effectiveThreadId === 'string' && effectiveThreadId.trim()
        ? effectiveThreadId.trim()
        : ''
    if (!resolvedThreadId) return
    if (autoPersistedThreadInUrlRef.current === resolvedThreadId) return

    try {
      if (typeof window === 'undefined') return
      const params = new URLSearchParams(window.location.search)
      const existingThreadParam = params.get('thread') || params.get('threadId')
      if (existingThreadParam && existingThreadParam.trim()) return

      skipHistoryLoadForThreadRef.current = resolvedThreadId
      autoPersistedThreadInUrlRef.current = resolvedThreadId

      params.delete('threadId')
      params.set('thread', resolvedThreadId)

      const query = params.toString()
      router.replace(query ? `/studio?${query}` : '/studio')
    } catch (error) {
      console.warn('Failed to persist resolved thread in Studio URL', error)
    }
  }, [activeJobId, effectiveThreadId, hasExplicitThreadParam, router])

  const loadThreadHistory = useCallback(async () => {
    if (!threadId || threadId === 'default') {
      setThreadLoading(false)
      setThreadLoadError(null)
      return
    }

    if (skipHistoryLoadForThreadRef.current && threadId === skipHistoryLoadForThreadRef.current) {
      skipHistoryLoadForThreadRef.current = null
      setThreadLoading(false)
      setThreadLoadError(null)
      return
    }

    if (localThreadId && threadId === localThreadId) {
      setThreadLoading(false)
      setThreadLoadError(null)
      return
    }

    setThreadLoading(true)
    setThreadLoadError(null)

    try {
      const res = await fetch(
        `/api/threads/${encodeURIComponent(threadId)}/messages?limit=200`,
        { cache: 'no-store' },
      )
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `Failed to load thread (${res.status})`)
      }

      const payload = (await res.json()) as any
      const rawMessages = Array.isArray(payload?.messages)
        ? payload.messages
        : Array.isArray(payload?.items)
          ? payload.items
          : []

      const nextMessages = rawMessages
        .filter(Boolean)
        .map((msg: any, idx: number) => {
          const roleRaw = msg?.role || msg?.type || msg?.sender || 'assistant'
          const role = String(roleRaw).toLowerCase()
          const type = role === 'user' ? 'user' : role === 'system' ? 'system' : 'assistant'
          const content = String(msg?.content ?? msg?.text ?? msg?.message ?? '')
          const id = String(msg?.id ?? msg?.message_id ?? `${threadId}-${idx}`)
          const tsRaw = msg?.timestamp ?? msg?.created_at ?? msg?.createdAt ?? null
          const timestamp = (() => {
            if (!tsRaw) return new Date()
            if (typeof tsRaw === 'number') {
              return new Date(tsRaw > 1e11 ? tsRaw : tsRaw * 1000)
            }
            if (typeof tsRaw === 'string') {
              const parsed = Date.parse(tsRaw)
              return Number.isNaN(parsed) ? new Date() : new Date(parsed)
            }
            return new Date()
          })()

          const checkpointId = extractCheckpointIdFromBoundary(msg)
          return {
            id,
            type,
            content,
            timestamp,
            ...buildCheckpointMessagePatch({
              payload: msg,
              metadata: normalizeCheckpointMetadata(msg?.metadata, checkpointId),
              fallbackCheckpointId: checkpointId,
            }),
          }
        })

      replaceMessages(nextMessages)
      setPromptSubmitted(true)
    } catch (error) {
      console.error('Failed to load thread history', error)
      setThreadLoadError(error instanceof Error ? error.message : String(error))
    } finally {
      setThreadLoading(false)
    }
  }, [replaceMessages, threadId, localThreadId])

  useEffect(() => {
    void loadThreadHistory()
  }, [loadThreadHistory])

  // Track execution status and update progress display
  useEffect(() => {
    const latestMessage = messages[messages.length - 1]
    const executionBlock = latestMessage?.executionBlock
    const lastCkpt = latestMessage?.lastCheckpointId

    if (lastCkpt && lastCkpt !== resumeCheckpointId) {
      setResumeCheckpointId(lastCkpt)
    } else if (!lastCkpt && resumeCheckpointId) {
      // Clear stale checkpoint when newer assistant messages don't carry one
      setResumeCheckpointId(null)
    }
    const status = executionBlock?.status

    if (status === 'running' && executionBlock.id) {
      setActiveJobId(executionBlock.id)
      setShowProgress(true)

      if (executionBlock.id !== analysisId) {
        try {
          if (typeof window !== 'undefined') {
            const params = new URLSearchParams(window.location.search)
            params.set('analysisId', executionBlock.id)
            params.set('tab', 'results')
            const query = params.toString()
            router.replace(query ? `/studio?${query}` : '/studio?tab=results')
          }
        } catch (error) {
          console.warn('Failed to persist Studio URL params', error)
        }
      }
    }

    const isTerminalStatus = status && ['completed', 'failed', 'cancelled', 'review_blocked'].includes(status)
    if (isTerminalStatus) {
      setActiveJobId(undefined)
      setShowProgress(false)
      disconnectWebSocket()
    }

    if (status === 'completed' && executionBlock) {
      // Trigger fetch from Evidence Rail API for persisted run card
      // This will update currentRunCard via the onSuccess callback
      if (!analysisId && executionBlock.id && executionBlock.id !== completedJobId) {
        // Invalidate cache to ensure fresh data
        invalidateRunCardCache(executionBlock.id)
        setCompletedJobId(executionBlock.id)
      }

      // Build a local fallback run card from execution block data
      // This provides immediate display while API fetch is in progress
      const datasetFromMetadata = executionBlock.metadata?.dataset
      const datasetFallback = datasetId
        ? {
            id: datasetId,
            name: datasetId,
            source: 'unknown',
            version: executionBlock.metadata?.datasetVersion,
          }
        : null
      const datasetsForRunCard = datasetFromMetadata
        ? [datasetFromMetadata]
        : datasetFallback
          ? [datasetFallback]
          : []

      const toolsUsed = Array.from(
        new Set(executionBlock.steps.filter(step => step.tool).map(step => step.tool))
      ).map(toolName => ({
        name: toolName || 'unknown',
        version: executionBlock.metadata?.toolVersions?.[toolName || ''] || 'unknown'
      }))

      const allParameters = executionBlock.steps.reduce((acc, step) => {
        if (step.args) {
          Object.assign(acc, step.args)
        }
        return acc
      }, {} as Record<string, any>)

      const citations = Array.isArray(executionBlock.metadata?.citations)
        ? executionBlock.metadata.citations
        : []

      // Build local fallback run card (will be replaced by API data if available)
      const localRunCard: ChatRunCard = {
        id: executionBlock.id,
        timestamp: latestMessage.timestamp,
        title: `Analysis: ${executionBlock.metadata?.pipeline || 'custom'}`,
        description: messages.find(m => m.type === 'user')?.content?.slice(0, 200) || '',
        execution: {
          durationSeconds: executionBlock.endTime && executionBlock.startTime
            ? (executionBlock.endTime.getTime() - executionBlock.startTime.getTime()) / 1000
            : 0,
          steps: executionBlock.steps || [],
          environment: executionBlock.metadata?.environment || {},
          resourceUsage: executionBlock.metadata?.resourceUsage || {}
        },
        inputs: {
          datasets: datasetsForRunCard as any,
          parameters: allParameters,
          attachments: []
        },
        outputs: {
          artifacts: executionBlock.artifacts || [],
          metrics: {},
          toolCalls: [],
          citations
        },
        provenance: {
          tools: toolsUsed,
          citations: citations as any,
          dependencies: []
        },
        reproducibility: {
          score: executionBlock.metadata?.reproducibility?.score,
          randomSeed: executionBlock.metadata?.reproducibility?.seedValue,
          isReproducible: executionBlock.metadata?.reproducibility?.isReproducible
        },
        // Legacy fields for backward compatibility
        prompt: messages.find(m => m.type === 'user')?.content || '',
        dataset: (datasetsForRunCard[0] as any) || undefined,
        tools: toolsUsed,
        parameters: allParameters,
        citations: citations as any,
        artifacts: executionBlock.artifacts
      }

      // Only set local run card if we don't already have API data
      if (!fetchedRunCard) {
        setCurrentRunCard(localRunCard)
      }
      setShowVisualizations(true)

      const preferredBrainMap = pickPreferredBrainMapArtifact(executionBlock.artifacts ?? [])
      if (
        studioBrainViewerEnabled &&
        preferredBrainMap &&
        executionBlock.id &&
        !autoOpenedViewerAnalysisIdsRef.current.has(executionBlock.id)
      ) {
        openBrainMapArtifact(preferredBrainMap, executionBlock.id, { markAutoOpened: true })
      }

      if (executionBlock.steps?.length) {
        setLatestSnapshot(buildSnapshotFromSteps(executionBlock.steps))
      } else {
        setLatestSnapshot(null)
      }
    }

    if (status && status !== 'completed') {
      setShowVisualizations(false)
      setLatestSnapshot(null)
    }
  }, [
    messages,
    datasetId,
    disconnectWebSocket,
    resumeCheckpointId,
    completedJobId,
    fetchedRunCard,
    analysisId,
    openBrainMapArtifact,
    router,
    studioBrainViewerEnabled,
  ])

  useEffect(() => {
    if (!evidenceJobId || analysisDetail?.status !== 'completed') return
    setShowVisualizations(true)
  }, [analysisDetail?.status, evidenceJobId])

  useEffect(() => {
    if (!selectedViewerArtifact?.analysisId || !evidenceJobId) return
    if (selectedViewerArtifact.analysisId === evidenceJobId) return
    setSelectedViewerArtifact(null)
  }, [evidenceJobId, selectedViewerArtifact])

  const currentRunCardId = currentRunCard?.id ?? null

  // Fetch visualization data when job completes or visualizations are shown
  useEffect(() => {
    const fetchVisualizationData = async () => {
      // Use activeJobId or extract from currentRunCard
      const jobId = activeJobId || currentRunCardId

      if (showVisualizations && jobId) {
        try {
          const [graph, maps] = await Promise.all([
            fetchWorkflowGraph(jobId),
            fetchBrainMaps(jobId)
          ])
          setVisualizationData({ knowledgeGraph: graph, brainMaps: maps })
        } catch (error) {
          console.error('Failed to fetch visualization data:', error)
          // Keep empty state on error
          setVisualizationData({ knowledgeGraph: null, brainMaps: [] })
        }
      }
    }

    fetchVisualizationData()
  }, [showVisualizations, activeJobId, currentRunCardId])

  const handleRunCreated = useCallback(
    (jobId: string, createdThreadId?: string | null) => {
      setCurrentRunCard(undefined)
      setCompletedJobId(undefined)
      setLatestSnapshot(null)
      setShowVisualizations(false)
      setLastFailure(null)
      setActiveRepairContext(null)
      setVisualizationData({ knowledgeGraph: null, brainMaps: [] })

      setActiveJobId(jobId)
      setShowProgress(true)
      setCanvasTab('results')

      const nextThreadId = createdThreadId || undefined
      if (nextThreadId) {
        setLocalThreadId(nextThreadId)
      }

      try {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)

        params.delete('analysis')
        params.delete('runId')
        params.delete('jobId')
        params.delete('threadId')

        params.set('analysisId', jobId)
        if (nextThreadId) {
          params.set('thread', nextThreadId)
        }
        params.set('tab', 'results')

        const query = params.toString()
        router.replace(query ? `/studio?${query}` : '/studio?tab=results')
      } catch (error) {
        console.warn('Failed to persist Studio URL params', error)
      }
    },
    [router],
  )

  const handleRetry = useCallback(
    async (jobId: string) => {
      try {
        const response = await fetch(`/api/analyses/${encodeURIComponent(jobId)}/retry`, {
          method: 'POST',
        })
        if (!response.ok) {
          const text = await response.text().catch(() => '')
          throw new Error(text || `Retry failed (${response.status})`)
        }
        const data = (await response.json().catch(() => null)) as
          | { job_id?: string; run_id?: string; analysis_id?: string }
          | null
        const nextJobId =
          (typeof data?.job_id === 'string' && data.job_id.trim()) ||
          (typeof data?.run_id === 'string' && data.run_id.trim()) ||
          (typeof data?.analysis_id === 'string' && data.analysis_id.trim()) ||
          jobId
        handleRunCreated(nextJobId, effectiveThreadId)
      } catch (error) {
        console.error('Retry failed', error)
        toast({
          title: 'Retry failed',
          description: error instanceof Error ? error.message : String(error),
          variant: 'destructive',
        })
      }
    },
    [effectiveThreadId, handleRunCreated, toast],
  )

  const handleSelectAttempt = useCallback(
    (nextAnalysisId: string) => {
      try {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)
        params.set('analysisId', nextAnalysisId)
        params.set('tab', 'results')
        const query = params.toString()
        router.replace(query ? `/studio?${query}` : '/studio?tab=results')
      } catch (error) {
        console.warn('Failed to persist Studio URL params', error)
      }
    },
    [router],
  )

  const handleInsertParameter = (suggestion: any) => {
    const paramText = copilot.insertParameter(suggestion)
    setCopilotInjectedText(paramText)
  }

  const handleInsertMethod = (recommendation: any) => {
    const methodPrompt = copilot.insertMethod(recommendation)
    const fallbackPrompt = `Use method: ${String(recommendation?.name || 'recommended_method')}`
    setCopilotInjectedText(methodPrompt?.trim() ? methodPrompt : fallbackPrompt)
  }

  const handleAskAgent = useCallback(
    (prompt: string) => {
      const tools = chatMode === 'coding' ? { mode: 'coding' } : undefined
      const repo_root = repoRootInput?.trim() || defaultRepoRoot
      const file_paths = filePathsInput
        .split(/[,\n]/)
        .map((p) => p.trim())
        .filter(Boolean)
      const ctx =
        chatMode === 'coding'
          ? {
              repo_root,
              file_paths,
              apply: false,
              dry_run: true,
              preview: true,
              force_code_agent: !repo_root,
              explain_only: explainOnly || undefined,
            }
          : undefined

      submitPrompt(prompt, [], {
        mode: 'simple',
        pipeline,
        datasetId,
        datasetVersion,
        parameters: buildParameters(),
        systemPrompt,
        scenarioId,
        codingMode,
        threadId: effectiveThreadId,
        tools,
        ctx,
        repoRoot: repo_root,
        filePaths: ctx?.file_paths,
        forceCodeAgent: chatMode === 'coding' && !repo_root,
        explainOnly: explainOnly,
      })
    },
    [
      buildParameters,
      chatMode,
      codingMode,
      datasetId,
      datasetVersion,
      defaultRepoRoot,
      effectiveThreadId,
      explainOnly,
      filePathsInput,
      pipeline,
      repoRootInput,
      scenarioId,
      submitPrompt,
      systemPrompt,
    ],
  )

  const handleWelcomePickPipeline = useCallback(
    (nextPipelineId: string) => {
      if (!nextPipelineId) return
      try {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)
        params.set('pipeline', nextPipelineId)
        params.delete('template')
        router.replace(buildStudioDatasetsPickerHref(params))
        setCanvasTab('plan')
      } catch (error) {
        console.warn('Failed to select workflow from Welcome Screen', error)
        toast({
          title: 'Failed to select workflow',
          description: error instanceof Error ? error.message : String(error),
          variant: 'destructive',
        })
      }
    },
    [router, setCanvasTab, toast],
  )

  const openMcpModal = useCallback(() => setMcpModalOpen(true), [])

  useEffect(() => {
    if (!openMcpOnMount || hasAutoOpenedMcpRef.current) return
    hasAutoOpenedMcpRef.current = true
    setMcpModalOpen(true)
  }, [openMcpOnMount])

  const applyReplacePlan = useCallback(
    (nextPipelineId: string) => {
      try {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)
        params.set('pipeline', nextPipelineId)
        params.delete('template')
        params.set('tab', 'plan')
        router.replace(`/studio?${params.toString()}`)
      } catch (error) {
        console.warn('Failed to replace plan', error)
      }
    },
    [router],
  )

  const buildPlanStorageKey = useCallback(() => {
    const threadKey =
      typeof effectiveThreadId === 'string' && effectiveThreadId.trim()
        ? effectiveThreadId.trim()
        : 'default'
    return `br:plan:${threadKey}`
  }, [effectiveThreadId])

  const handleApplyRepairProposal = useCallback(
    (proposal: RepairProposal) => {
      if (typeof window === 'undefined' || !proposal.planPatch) return

      try {
        const storageKey = buildPlanStorageKey()
        const currentDraftRaw =
          window.localStorage?.getItem(storageKey) ??
          window.localStorage?.getItem(SHARED_PLAN_STORAGE_KEY) ??
          null
        const nextDraft = applyRepairPlanPatchToDraft(currentDraftRaw, proposal.planPatch, {
          datasetId: planComposerContext.datasetId ?? datasetId ?? null,
          datasetVersion: planComposerContext.datasetVersion ?? datasetVersion ?? null,
          analysisId: planComposerContext.analysisId ?? null,
          pipelineId: planComposerContext.pipelineId ?? pipeline ?? null,
        })

        if (!nextDraft) {
          throw new Error('Repair proposal did not include an applicable plan patch.')
        }

        const encoded = JSON.stringify(nextDraft)
        window.localStorage.setItem(storageKey, encoded)
        window.localStorage.setItem(SHARED_PLAN_STORAGE_KEY, encoded)

        const patch = proposal.planPatch as Record<string, unknown>
        const patchDatasetId =
          typeof patch.dataset_id === 'string'
            ? patch.dataset_id.trim()
            : typeof patch.datasetId === 'string'
              ? patch.datasetId.trim()
              : ''
        const patchDatasetVersion =
          typeof patch.dataset_version === 'string'
            ? patch.dataset_version.trim()
            : typeof patch.datasetVersion === 'string'
              ? patch.datasetVersion.trim()
              : ''
        const patchPipelineId =
          typeof patch.pipeline_id === 'string'
            ? patch.pipeline_id.trim()
            : typeof patch.pipelineId === 'string'
              ? patch.pipelineId.trim()
              : ''

        const params = new URLSearchParams(window.location.search)
        params.delete('analysisId')
        params.delete('analysis')
        params.delete('runId')
        params.delete('jobId')
        params.set('tab', 'plan')
        if (patchDatasetId) params.set('datasetId', patchDatasetId)
        if (patchDatasetVersion) params.set('datasetVersion', patchDatasetVersion)
        if (patchPipelineId) {
          params.set('pipeline', patchPipelineId)
          params.delete('template')
        }

        setPlanPanelNonce((prev) => prev + 1)
        setCanvasTab('plan')
        router.replace(`/studio?${params.toString()}`)

        toast({
          title: 'Repair fix applied',
          description: 'Studio plan updated with the proposed change.',
          duration: 2500,
        })
      } catch (error) {
        toast({
          title: 'Failed to apply repair fix',
          description: error instanceof Error ? error.message : String(error),
          variant: 'destructive',
        })
      }
    },
    [
      buildPlanStorageKey,
      datasetId,
      datasetVersion,
      pipeline,
      planComposerContext.analysisId,
      planComposerContext.datasetId,
      planComposerContext.datasetVersion,
      planComposerContext.pipelineId,
      router,
      toast,
    ],
  )

  const handleRevalidateRepairProposal = useCallback(
    (proposal: RepairProposal) => {
      setCanvasTab('plan')
      setPlanValidationNonce((prev) => prev + 1)
      toast({
        title: 'Re-validating in Studio',
        description:
          proposal.validationIntent ||
          'Running the updated Studio validation plan.',
        duration: 2500,
      })
    },
    [toast],
  )

  const handleRepairHandOff = useCallback(
    (proposal: RepairProposal) => {
      setMcpModalOpen(true)
      toast({
        title: 'Hand off to IDE',
        description:
          proposal.handoff?.reason ||
          'Use IDE/cluster handoff for repairs that need environment or external code changes.',
        duration: 3000,
      })
    },
    [toast],
  )

  const getCanvasTabFromSearch = useCallback((search: string): typeof canvasTab => {
    const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
    const raw = params.get('tab')
    if (!raw) return 'results'
    const normalized = raw.trim().toLowerCase()
    if (normalized === 'plan') return 'plan'
    if (normalized === 'results') return 'results'
    if (normalized === 'charts') return 'charts'
    if (normalized === 'steps') return 'steps'
    return 'results'
  }, [])

  const openReplacePlanDialog = useCallback(
    (nextPipelineId: string) => {
      if (!nextPipelineId || nextPipelineId === pipeline) return

      if (planEditing) {
        setCanvasTab('plan')
        setPendingPlanSuggestion({ pipelineId: nextPipelineId })
        return
      }

      setReplacePlanCandidateId(nextPipelineId)
      setReplacePlanDialogOpen(true)
    },
    [pipeline, planEditing],
  )

  const confirmReplacePlan = useCallback(() => {
    const nextPipelineId = replacePlanCandidateId
    if (!nextPipelineId) {
      setReplacePlanDialogOpen(false)
      return
    }

    try {
      if (typeof window === 'undefined') return
      const currentSearch = window.location.search || ''
      const storageKey = buildPlanStorageKey()
      const previousDraft = window.localStorage?.getItem(storageKey) ?? null

      replacePlanUndoRef.current = {
        search: currentSearch,
        planDraftRaw: previousDraft,
      }
    } catch (error) {
      console.warn('Failed to capture undo snapshot for Replace Plan', error)
      replacePlanUndoRef.current = null
    }

    setReplacePlanDialogOpen(false)
    setReplacePlanCandidateId(null)
    setPendingPlanSuggestion(null)
    setPlanPanelNonce((prev) => prev + 1)
    setCanvasTab('plan')
    applyReplacePlan(nextPipelineId)

    toast({
      title: 'Plan replaced',
      description: 'Your plan has been updated. You can undo this change.',
      action: (
        <ToastAction
          altText="Undo plan replacement"
          onClick={() => {
            const snapshot = replacePlanUndoRef.current
            if (!snapshot) return

            try {
              if (typeof window === 'undefined') return
              const storageKey = buildPlanStorageKey()
              if (snapshot.planDraftRaw === null) {
                window.localStorage?.removeItem(storageKey)
              } else {
                window.localStorage?.setItem(storageKey, snapshot.planDraftRaw)
              }
            } catch (error) {
              console.warn('Failed to restore plan draft during undo', error)
            }

            setPlanPanelNonce((prev) => prev + 1)
            setCanvasTab(getCanvasTabFromSearch(snapshot.search))
            try {
              router.replace(`/studio${snapshot.search}`)
            } catch (error) {
              console.warn('Failed to undo plan replacement', error)
            }
          }}
        >
          Undo
        </ToastAction>
      ),
    })
  }, [applyReplacePlan, buildPlanStorageKey, getCanvasTabFromSearch, replacePlanCandidateId, router, toast])

  const handleReplacePlan = useCallback(
    (nextPipelineId: string) => {
      openReplacePlanDialog(nextPipelineId)
    },
    [openReplacePlanDialog],
  )

  useEffect(() => {
    if (planEditing) {
      editingStartedAtRef.current = Date.now()
      return
    }
    editingStartedAtRef.current = null
  }, [planEditing])

  useEffect(() => {
    if (!planEditing) return
    const editingStartedAt = editingStartedAtRef.current
    if (!editingStartedAt) return

    const latestAssistant = [...messages]
      .reverse()
      .find((msg) => msg.type === 'assistant' && msg.timestamp.getTime() >= editingStartedAt)

    if (!latestAssistant) return
    if (lastSuggestionMessageIdRef.current === latestAssistant.id) return

    const suggestedPipelineId = findSuggestedPipelineId(latestAssistant)
    if (!suggestedPipelineId) return
    if (pipeline && suggestedPipelineId === pipeline) return
    if (pendingPlanSuggestion?.pipelineId === suggestedPipelineId) return

    lastSuggestionMessageIdRef.current = latestAssistant.id
    setPendingPlanSuggestion({ pipelineId: suggestedPipelineId, messageId: latestAssistant.id })
  }, [messages, pendingPlanSuggestion?.pipelineId, pipeline, planEditing])

  const handleOpenInPipelineBuilder = useCallback(() => {
    if (!latestSnapshot) return

    try {
      if (typeof window === 'undefined' || !window.localStorage) {
        throw new Error('Local storage is unavailable in this context')
      }

      window.localStorage.setItem(
        PIPELINE_SNAPSHOT_KEY,
        JSON.stringify({
          nodes: latestSnapshot.nodes,
          edges: latestSnapshot.edges
        })
      )

      toast({
        title: 'Pipeline ready',
        description: 'Opening Pipeline Builder…'
      })

      router.push('/pipeline-builder')
    } catch (error) {
      console.error('Failed to send steps to Pipeline Builder', error)
      toast({
        title: 'Transfer failed',
        description: 'Could not copy steps into the builder. Please try again.',
        variant: 'destructive'
      })
    }
  }, [latestSnapshot, router, toast])

  const diagnosisDetails = buildDiagnosisDetailsFromEvidence(evidenceRailData)
  const statusIndicatesFailure =
    analysisDetail?.status === 'failed' || analysisDetail?.status === 'timeout'
  const hasLastFailureForJob = Boolean(lastFailure && evidenceJobId === lastFailure.jobId)
  const inferredFailure =
    !analysisDetail &&
    !analysisDetailLoading &&
    Boolean(
      (Array.isArray(evidenceRailData?.violations) &&
        evidenceRailData.violations.some(
          (violation) =>
            violation?.blocking ||
            violation?.severity === 'error' ||
            violation?.severity === 'critical',
        )) ||
        (Array.isArray(evidenceRailData?.steps) &&
          evidenceRailData.steps.some((step) => {
            const state = typeof step.state === 'string' ? step.state.toLowerCase() : ''
            return state === 'failed' || state === 'error'
          })),
    )
  const showDiagnosisCard =
    Boolean(evidenceJobId) && (hasLastFailureForJob || statusIndicatesFailure || inferredFailure)
  const diagnosisMessage = hasLastFailureForJob ? lastFailure?.message : undefined

  const diagnosisToolLabel = useMemo(() => {
    const runCard = evidenceRailData?.mappedRunCard || currentRunCard
    const runSteps = Array.isArray(runCard?.execution?.steps) ? runCard.execution.steps : []
    const failedRunStep =
      runSteps.find((step) => {
        const state = typeof step.status === 'string' ? step.status.toLowerCase() : ''
        return Boolean(step.error) || state === 'failed' || state === 'error'
      }) || null

    const runTool = failedRunStep?.tool ? String(failedRunStep.tool).trim() : ''
    if (runTool) return runTool

    const runName = failedRunStep?.name ? String(failedRunStep.name).trim() : ''
    if (runName) return runName

    const evidenceSteps = Array.isArray(evidenceRailData?.steps) ? evidenceRailData.steps : []
    const failedEvidenceStep =
      evidenceSteps.find((step) => {
        const state = typeof step.state === 'string' ? step.state.toLowerCase() : ''
        return Boolean(step.error) || state === 'failed' || state === 'error'
      }) || null

    const evidenceName =
      failedEvidenceStep?.name && typeof failedEvidenceStep.name === 'string'
        ? failedEvidenceStep.name.trim()
        : ''
    if (evidenceName) return evidenceName

    const templatePipelineId =
      analysisDetail?.template?.pipeline_id &&
      typeof analysisDetail.template.pipeline_id === 'string'
        ? analysisDetail.template.pipeline_id.trim()
        : ''
    if (templatePipelineId) return templatePipelineId

    const templateName =
      analysisDetail?.template?.name && typeof analysisDetail.template.name === 'string'
        ? analysisDetail.template.name.trim()
        : ''
    if (templateName) return templateName

    const violations = Array.isArray(evidenceRailData?.violations) ? evidenceRailData.violations : []
    const primaryViolation =
      violations.find(
        (violation) =>
          violation?.blocking ||
          violation?.severity === 'critical' ||
          violation?.severity === 'error',
      ) || violations[0]

    const component =
      primaryViolation?.where?.component && typeof primaryViolation.where.component === 'string'
        ? primaryViolation.where.component.trim()
        : ''
    if (component) return component

    const stage =
      primaryViolation?.where?.stage && typeof primaryViolation.where.stage === 'string'
        ? primaryViolation.where.stage.trim()
        : ''
    if (stage) return stage

    return null
  }, [analysisDetail, currentRunCard, evidenceRailData])

  const diagnosisToolHref = useMemo(() => {
    if (!diagnosisToolLabel) return undefined
    const encoded = encodeURIComponent(diagnosisToolLabel)
    return `/library/tools?q=${encoded}&tool=${encoded}`
  }, [diagnosisToolLabel])

  const buildAskAgentSwitchVersionPrompt = useCallback(
    (jobId: string, toolLabel: string, summaryMessage?: string) => {
      const details = buildDiagnosisDetailsFromEvidence(evidenceRailData)
      const lines: string[] = []

      lines.push('Help me resolve this failure by switching tool/version or pipeline.')
      lines.push(`Run/job ID: ${jobId}`)
      lines.push(`Failing tool/step: ${toolLabel}`)
      if (datasetId) lines.push(`Dataset: ${datasetId}`)
      if (pipeline) lines.push(`Current pipeline: ${pipeline}`)
      if (analysisDetail?.status) lines.push(`Status: ${analysisDetail.status}`)

      if (summaryMessage?.trim()) {
        lines.push('')
        lines.push('Error summary:')
        lines.push(summaryMessage.trim())
      }

      if (details.whatHappened.length > 0) {
        lines.push('')
        lines.push('What happened:')
        for (const item of details.whatHappened.slice(0, 6)) {
          lines.push(`- ${item}`)
        }
      }

      lines.push('')
      lines.push('Please propose one or more options:')
      lines.push('- Recommend a safer version (or alternative tool/pipeline) and explain why.')
      lines.push('- Suggest minimal plan changes (parameters, pipeline switch) to retry successfully.')
      lines.push('- If a different pipeline/template is best, provide its id/name so I can Replace Plan.')
      return lines.join('\n')
    },
    [analysisDetail?.status, datasetId, evidenceRailData, pipeline],
  )

  const diagnosisTitle = (() => {
    if (analysisDetail?.status === 'timeout') return 'Diagnosis: Timeout'

    const blockingViolation = Array.isArray(evidenceRailData?.violations)
      ? evidenceRailData.violations.some(
          (violation) =>
            violation?.blocking ||
            violation?.severity === 'critical' ||
            violation?.severity === 'error',
        )
      : false

    if (blockingViolation) return 'Diagnosis: Data validation error'

    const stepFailure = Array.isArray(evidenceRailData?.steps)
      ? evidenceRailData.steps.some((step) => {
          const state = typeof step.state === 'string' ? step.state.toLowerCase() : ''
          return Boolean(step.error) || state === 'failed' || state === 'error'
        })
      : false

    if (stepFailure) return 'Diagnosis: Workflow error'

    return 'Diagnosis'
  })()

  const buildRepairContext = useCallback(
    (jobId: string, summaryMessage?: string): StudioRepairContext => {
      const attemptCount = (repairAttemptsByRunId[jobId] ?? 0) + 1
      const runCard = evidenceRailData?.mappedRunCard || currentRunCard
      const repairSignals = deriveRepairSignalSummary({
        evidenceData: evidenceRailData,
        runCard,
        analysisStatus: analysisDetail?.status,
        summaryMessage,
        diagnosisMessage,
        fallbackToolName: diagnosisToolLabel,
      })
      const parameterValues =
        (evidenceRailData?.parameters && typeof evidenceRailData.parameters === 'object'
          ? evidenceRailData.parameters
          : runCard?.inputs?.parameters) || {}
      const failedRunStep =
        Array.isArray(runCard?.execution?.steps) && repairSignals.failingStep?.id
          ? runCard.execution.steps.find(
              (step) => step.id === repairSignals.failingStep?.id,
            ) ?? null
          : null
      const stepLogTail = Array.isArray(failedRunStep?.logs)
        ? failedRunStep.logs
            .map((entry) =>
              entry && typeof entry === 'object' && 'message' in entry
                ? String(entry.message || '').trim()
                : '',
            )
            .filter(Boolean)
            .slice(-6)
        : []
      const streamTail = streamLogLines.slice(-8).map((entry) => entry.line).filter(Boolean)
      const logTail = Array.from(new Set([...stepLogTail, ...streamTail])).slice(-12)

      return {
        run_id: jobId,
        thread_id: effectiveThreadId ?? null,
        analysis_id:
          (typeof analysisDetail?.analysis_id === 'string' && analysisDetail.analysis_id) ||
          (typeof analysisDetail?.run_id === 'string' && analysisDetail.run_id) ||
          (typeof analysisDetail?.job_id === 'string' && analysisDetail.job_id) ||
          null,
        tool_name: repairSignals.toolName,
        error_type: repairSignals.errorType,
        error_message: repairSignals.errorMessage,
        repair_attempt_count: attemptCount,
        failing_step: repairSignals.failingStep,
        diagnosis: {
          title: diagnosisTitle,
          message: summaryMessage?.trim() || diagnosisMessage || null,
          what_happened: diagnosisDetails.whatHappened,
          suggested_actions: diagnosisDetails.suggestedActions,
        },
        primary_violation: repairSignals.primaryViolation,
        diagnostics_codes: repairSignals.diagnosticsCodes,
        sample_errors: repairSignals.sampleErrors,
        plan_snapshot: {
          dataset_id: planComposerContext.datasetId ?? datasetId ?? null,
          dataset_version: planComposerContext.datasetVersion ?? datasetVersion ?? null,
          analysis_id: planComposerContext.analysisId ?? null,
          pipeline_id: planComposerContext.pipelineId ?? pipeline ?? null,
          parameter_values:
            parameterValues && typeof parameterValues === 'object'
              ? (parameterValues as Record<string, unknown>)
              : {},
          dataset_resource_summary: planComposerContext.datasetResourceSummary,
        },
        input_artifacts: buildRepairInputArtifacts(
          runCard,
          evidenceRailData?.artifacts || currentRunCard?.outputs?.artifacts,
        ),
        log_tail: logTail,
      }
    },
    [
      analysisDetail,
      currentRunCard,
      datasetId,
      datasetVersion,
      diagnosisDetails.suggestedActions,
      diagnosisDetails.whatHappened,
      diagnosisMessage,
      diagnosisTitle,
      diagnosisToolLabel,
      effectiveThreadId,
      evidenceRailData,
      pipeline,
      planComposerContext.analysisId,
      planComposerContext.datasetId,
      planComposerContext.datasetResourceSummary,
      planComposerContext.datasetVersion,
      planComposerContext.pipelineId,
      repairAttemptsByRunId,
      streamLogLines,
    ],
  )

  const buildRepairPrompt = useCallback((repairContext: StudioRepairContext) => {
    const lines: string[] = []
    lines.push('Repair this failed Studio validation run.')
    lines.push('Stay in Studio if possible and prefer the smallest plan/config change that can be re-validated here.')
    lines.push('Explain the root cause briefly, then propose the specific fix.')
    lines.push('If you can express the fix as plan/config updates, append exactly one fenced json block.')
    lines.push('The json block may only use these keys: plan_patch, recipe_patch_preview, validation_intent, handoff.')
    lines.push('Use handoff.required=true only if this needs environment, dependency, or external IDE/code changes.')
    lines.push(`Run/job ID: ${repairContext.run_id}`)
    if (repairContext.failing_step?.name || repairContext.failing_step?.id) {
      lines.push(
        `Failing step: ${repairContext.failing_step.name || repairContext.failing_step.id}`,
      )
    }
    if (repairContext.tool_name) lines.push(`Tool: ${repairContext.tool_name}`)
    if (repairContext.error_message) lines.push(`Error summary: ${repairContext.error_message}`)
    return lines.join('\n')
  }, [])

  const handleRepairInStudio = useCallback(
    (jobId: string, summaryMessage?: string) => {
      const repairContext = buildRepairContext(jobId, summaryMessage)
      const repo_root = repoRootInput?.trim() || defaultRepoRoot
      const file_paths = filePathsInput
        .split(/[,\n]/)
        .map((p) => p.trim())
        .filter(Boolean)

      setChatMode('coding')
      setActiveRepairContext(repairContext)
      setRepairAttemptsByRunId((prev) => ({
        ...prev,
        [jobId]: repairContext.repair_attempt_count,
      }))

      submitPrompt(buildRepairPrompt(repairContext), [], {
        mode: 'simple',
        pipeline: repairContext.plan_snapshot.pipeline_id ?? undefined,
        datasetId: repairContext.plan_snapshot.dataset_id ?? undefined,
        datasetVersion: repairContext.plan_snapshot.dataset_version ?? undefined,
        datasetResourceSummary: repairContext.plan_snapshot.dataset_resource_summary ?? undefined,
        parameters: repairContext.plan_snapshot.parameter_values,
        systemPrompt,
        scenarioId,
        codingMode: true,
        threadId: effectiveThreadId,
        tools: { mode: 'coding' },
        ctx: {
          repo_root,
          file_paths,
          apply: false,
          dry_run: true,
          preview: true,
          explain_only: false,
          repair_context: repairContext,
        },
        repoRoot: repo_root,
        filePaths: file_paths,
      })
    },
    [
      buildRepairContext,
      buildRepairPrompt,
      defaultRepoRoot,
      effectiveThreadId,
      filePathsInput,
      repoRootInput,
      scenarioId,
      submitPrompt,
      systemPrompt,
    ],
  )

  const summarySourceText =
    (typeof evidenceRailData?.mappedRunCard?.outputs?.text === 'string' &&
      evidenceRailData.mappedRunCard.outputs.text) ||
    (typeof currentRunCard?.outputs?.text === 'string' && currentRunCard.outputs.text) ||
    (typeof evidenceRailData?.mappedRunCard?.description === 'string' &&
      evidenceRailData.mappedRunCard.description) ||
    (typeof currentRunCard?.description === 'string' && currentRunCard.description) ||
    ''
  const summaryBullets = extractSummaryBullets(summarySourceText)

  const allArtifacts = (() => {
    const runCard = evidenceRailData?.mappedRunCard || currentRunCard
    const artifacts = runCard?.outputs?.artifacts || runCard?.artifacts || []
    if (!Array.isArray(artifacts) || artifacts.length === 0) return []
    return [...artifacts].filter((artifact) => artifact && typeof artifact === 'object')
  })()
  const artifactCount = allArtifacts.length
  const preferredBrainMapArtifact = useMemo(
    () => pickPreferredBrainMapArtifact(allArtifacts),
    [allArtifacts],
  )

  const keyArtifacts = useMemo(() => {
    if (!allArtifacts.length) return []
    const rankedArtifacts = [...allArtifacts]
      .sort((a: any, b: any) => scoreKeyArtifact(b) - scoreKeyArtifact(a))
    const topArtifacts = rankedArtifacts.slice(0, 3)
    if (!preferredBrainMapArtifact || topArtifacts.includes(preferredBrainMapArtifact)) {
      return topArtifacts
    }
    return [...rankedArtifacts.slice(0, 2), preferredBrainMapArtifact]
  }, [allArtifacts, preferredBrainMapArtifact])

  useEffect(() => {
    if (
      !studioBrainViewerEnabled ||
      !evidenceJobId ||
      analysisDetail?.status !== 'completed' ||
      !preferredBrainMapArtifact
    ) {
      return
    }
    if (autoOpenedViewerAnalysisIdsRef.current.has(evidenceJobId)) return
    openBrainMapArtifact(preferredBrainMapArtifact, evidenceJobId, { markAutoOpened: true })
  }, [
    analysisDetail?.status,
    evidenceJobId,
    openBrainMapArtifact,
    preferredBrainMapArtifact,
    studioBrainViewerEnabled,
  ])

  const statusIndicatesSuccess = analysisDetail?.status === 'completed'
  const hasResultContent = summaryBullets.length > 0 || keyArtifacts.length > 0 || artifactCount > 0
  const showSuccessBlocks =
    Boolean(evidenceJobId) &&
    !showProgress &&
    !showDiagnosisCard &&
    (Boolean(statusIndicatesSuccess) || hasResultContent)

  const consoleJobId = evidenceJobId
  const showConsole = Boolean(consoleJobId) && consoleDismissedForJobId !== consoleJobId

  useEffect(() => {
    if (!consoleJobId) return
    setConsoleDismissedForJobId(null)
  }, [consoleJobId])

  useEffect(() => {
    if (!consoleJobId) return
    if (showProgress || showDiagnosisCard) {
      setConsoleOpen(true)
    }
  }, [consoleJobId, showDiagnosisCard, showProgress])

  const topBarStatus = showProgress
    ? 'running'
    : analysisDetail?.status
      ? analysisDetail.status
      : showDiagnosisCard
        ? 'failed'
        : evidenceJobId
          ? 'unknown'
          : null

  const topBarStatusLabel = (() => {
    if (!topBarStatus) return 'No run'
    switch (topBarStatus) {
      case 'pending':
      case 'queued':
        return 'Queued'
      case 'running':
      case 'retrying':
      case 'cancelling':
        return 'Running'
      case 'completed':
        return 'Succeeded'
      case 'failed':
      case 'timeout':
        return 'Failed'
      case 'cancelled':
        return 'Cancelled'
      default:
        return 'Unknown'
    }
  })()

  const topBarStatusVariant = (() => {
    if (!topBarStatus) return 'secondary'
    switch (topBarStatus) {
      case 'failed':
      case 'timeout':
        return 'destructive'
      case 'completed':
        return 'outline'
      case 'running':
      case 'retrying':
      case 'cancelling':
        return 'secondary'
      default:
        return 'secondary'
    }
  })() as 'default' | 'secondary' | 'destructive' | 'outline'

  const topBarStatusDotClass = (() => {
    if (!topBarStatus) return 'bg-muted-foreground/40'
    switch (topBarStatus) {
      case 'running':
      case 'retrying':
      case 'cancelling':
        return 'bg-blue-500'
      case 'completed':
        return 'bg-green-500'
      case 'failed':
      case 'timeout':
        return 'bg-red-500'
      case 'queued':
      case 'pending':
        return 'bg-slate-400'
      default:
        return 'bg-muted-foreground/40'
    }
  })()

  const openConsole = () => {
    if (!consoleJobId) return
    setConsoleDismissedForJobId(null)
    setConsoleOpen(true)
  }

  const downloadConsoleLogs = () => {
    if (!consoleJobId) return
    if (typeof window === 'undefined' || typeof document === 'undefined') return
    if (!streamLogLines.length) {
      toast({
        title: 'No logs yet',
        description: 'Streamed log lines have not arrived yet.',
        duration: 2500,
      })
      return
    }

    const lines = streamLogLines.map((entry) => {
      const clock = entry.timestamp ? entry.timestamp : ''
      return `${clock} [${entry.stream}] ${entry.line}`
    })
    const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `analysis-${consoleJobId}-logs.txt`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const resultTimestampLabel = (() => {
    const finishedAt = analysisDetail?.finished_at
    const createdAt = analysisDetail?.created_at
    const timestampSec = typeof finishedAt === 'number' ? finishedAt : typeof createdAt === 'number' ? createdAt : null
    if (!timestampSec) return null
    const dt = new Date(timestampSec * 1000)
    return Number.isNaN(dt.getTime()) ? null : dt.toLocaleString()
  })()

  const resultDurationLabel = (() => {
    const startedAt = analysisDetail?.started_at
    const finishedAt = analysisDetail?.finished_at
    if (typeof startedAt !== 'number' || typeof finishedAt !== 'number') return null
    const seconds = Math.max(0, finishedAt - startedAt)
    return formatDuration(seconds)
  })()

  const replacePlanFromTitle = pipeline
    ? PIPELINE_LABELS_BY_ID.get(pipeline)?.title ?? pipeline
    : 'None'
  const replacePlanToTitle = replacePlanCandidateId
    ? PIPELINE_LABELS_BY_ID.get(replacePlanCandidateId)?.title ?? replacePlanCandidateId
    : ''

  const artifactPreviewKind = useMemo(() => {
    const url = artifactPreviewTarget?.url?.toLowerCase?.() ?? ''
    const name = artifactPreviewTarget?.name?.toLowerCase?.() ?? ''
    if (url.endsWith('.html') || url.endsWith('.htm') || name.endsWith('.html') || name.endsWith('.htm')) {
      return 'html'
    }
    return 'text'
  }, [artifactPreviewTarget])

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      {evidenceJobId ? (
        <ShareModal
          analysisId={evidenceJobId}
          open={shareModalOpen}
          onOpenChange={setShareModalOpen}
        />
      ) : null}

      <Dialog
        open={artifactPreviewOpen}
        onOpenChange={(open) => {
          setArtifactPreviewOpen(open)
          if (!open) {
            setArtifactPreviewTarget(null)
            setArtifactPreviewBody(null)
            setArtifactPreviewError(null)
            setArtifactPreviewLoading(false)
          }
        }}
      >
        <DialogContent className="max-w-3xl" data-testid="artifact-preview-dialog">
          <DialogHeader>
            <DialogTitle>
              Preview: {artifactPreviewTarget?.name ? artifactPreviewTarget.name : 'Artifact'}
            </DialogTitle>
            <DialogDescription className="sr-only">
              Preview the selected artifact content or rendered HTML output.
            </DialogDescription>
          </DialogHeader>
          {artifactPreviewLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading preview…
            </div>
          ) : artifactPreviewError ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              Failed to load preview: {artifactPreviewError}
            </div>
          ) : artifactPreviewKind === 'html' ? (
            <div className="h-[60vh] overflow-hidden rounded-md border bg-background">
              <iframe
                title="Artifact preview"
                className="h-full w-full"
                sandbox="allow-same-origin"
                srcDoc={artifactPreviewBody ?? ''}
              />
            </div>
          ) : (
            <pre className="max-h-[60vh] overflow-auto rounded-md border bg-background p-3 text-xs">
              {artifactPreviewBody ?? ''}
            </pre>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={replacePlanDialogOpen}
        onOpenChange={(open) => {
          setReplacePlanDialogOpen(open)
          if (!open) {
            setReplacePlanCandidateId(null)
          }
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Replace plan?</DialogTitle>
            <DialogDescription className="sr-only">
              Review the impact summary before replacing the current plan.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="space-y-1">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Impact summary
              </div>
              <div className="space-y-2 rounded-md border bg-muted/30 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium">Dataset</div>
                  <div className="text-right text-muted-foreground">
                    {datasetId ? datasetId : 'None'} (unchanged)
                  </div>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium">Pipeline</div>
                  <div className="text-right text-muted-foreground">
                    {replacePlanFromTitle} → {replacePlanToTitle}
                  </div>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium">Parameters</div>
                  <div className="text-right text-muted-foreground">
                    Custom step parameters will reset.
                  </div>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium">Estimate</div>
                  <div className="text-right text-muted-foreground">
                    Credits and runtime will be re-checked.
                  </div>
                </div>
              </div>
            </div>

            <div className="text-xs text-muted-foreground">
              Tip: after replacing, click “Undo” in the toast to restore the previous plan.
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setReplacePlanDialogOpen(false)
                setReplacePlanCandidateId(null)
              }}
            >
              Cancel
            </Button>
            <Button type="button" onClick={confirmReplacePlan}>
              Replace Plan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <McpConfigurationModal
        open={mcpModalOpen}
        onOpenChange={setMcpModalOpen}
        planId={currentPlanId}
        threadId={effectiveThreadId || null}
        workflowId={currentWorkflowId}
        workflowLabel={currentWorkflowLabel}
        datasetId={currentPlanDatasetId}
        datasetVersion={currentPlanDatasetVersion}
        continuationPrompt={mcpContinuationPrompt}
        onManageInSettings={() => {
          setMcpModalOpen(false)
          router.push('/settings?tab=integrations')
        }}
      />

      <div className="bg-white border-b border-gray-200 px-4 py-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <WorkspaceSwitcher />
          {evidenceJobId ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push(`/analyses/${encodeURIComponent(evidenceJobId)}`)}
            >
              Run: #{evidenceJobId.slice(0, 8)}
            </Button>
          ) : (
            <span className="text-sm text-muted-foreground">No run selected</span>
          )}

          {consoleJobId ? (
            <Button variant="outline" size="sm" onClick={openConsole}>
              <span
                aria-hidden
                className={`mr-2 inline-flex h-2 w-2 rounded-full ${topBarStatusDotClass}`}
              />
              <span className="mr-2">{topBarStatusLabel}</span>
              <Terminal className="h-4 w-4 text-muted-foreground" />
            </Button>
          ) : (
            <Badge variant={topBarStatusVariant} className="inline-flex items-center gap-2">
              <span aria-hidden className={`inline-flex h-2 w-2 rounded-full ${topBarStatusDotClass}`} />
              <span>{topBarStatusLabel}</span>
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push('/kg?tab=suggestions')}
          >
            KG
            {kgSuggestionsCount ? (
              <span className="ml-2 inline-flex items-center gap-1 text-xs">
                <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-2 font-medium text-primary-foreground">
                  {kgSuggestionsCount}
                </span>
                <span className="text-muted-foreground">new</span>
              </span>
            ) : null}
          </Button>
          {hydrated && evidenceJobId ? (
            <Button variant="outline" size="sm" onClick={() => setShareModalOpen(true)}>
              Share
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => router.push('/settings?tab=credits')}>
            Credits
            <span className="ml-2 text-xs text-muted-foreground">
              {creditsBalance == null ? 'TBD' : creditsBalance.toLocaleString()}
            </span>
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:grid lg:grid-cols-[minmax(0,1fr)_420px]">
        {/* Main chat area */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* Chat header with copilot toggle */}
          <div className="flex flex-col gap-3 border-b p-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-semibold">Studio</h1>
            <div className="inline-flex items-center overflow-hidden rounded-md border text-xs">
                {(['chat', 'coding', 'neuro'] as ChatMode[]).map(mode => (
                  <button
                    key={mode}
                    type="button"
                    className={`px-3 py-1 capitalize transition-colors ${chatMode === mode ? 'bg-muted text-foreground' : 'bg-background text-muted-foreground hover:bg-muted/70'}`}
                    onClick={() => {
                      setChatMode(mode)
                      // Reset explain-only when switching modes.
                      setExplainOnly(false)
                    }}
                  >
                    {mode}
                  </button>
                ))}
            </div>
          </div>
          {chatMode === 'coding' && (
            <div className="flex w-full flex-col gap-2 text-xs text-muted-foreground md:w-auto md:flex-row md:flex-wrap md:items-center">
              <div className="flex min-w-0 items-center gap-2">
                <span className="whitespace-nowrap">Repo root</span>
                <Input
                  value={repoRootInput}
                  onChange={(e) => setRepoRootInput(e.target.value)}
                  placeholder="Repository path"
                  className="h-8 w-full text-xs md:w-48"
                />
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <span className="whitespace-nowrap">Files</span>
                <Input
                  value={filePathsInput}
                  onChange={(e) => setFilePathsInput(e.target.value)}
                  placeholder="Files or glob patterns"
                  className="h-8 w-full text-xs md:w-56"
                />
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {resumeCheckpointId && (
                <span className="text-xs text-muted-foreground" title="Last checkpoint">
                  Last checkpoint: {resumeCheckpointId}
                </span>
              )}
              {webSocket.isConnected && (
                <div className="flex items-center gap-1 text-xs text-green-600">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  Live
                </div>
              )}
              {/* SSE Connection State Indicator */}
              {connectionState === 'connected' && (
                <div className="flex items-center gap-1 text-xs text-green-600">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  Streaming
                </div>
              )}
              {connectionState === 'reconnecting' && (
                <div className="flex items-center gap-1 text-xs text-yellow-600">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Reconnecting…
                </div>
              )}
              {connectionState === 'failed' && (
                <div className="flex items-center gap-1.5 text-xs text-red-600">
                  <WifiOff className="h-3 w-3" />
                  <span>Connection lost</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-1.5 text-xs text-red-600 hover:text-red-700"
                    onClick={resetConnectionState}
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    Retry
                  </Button>
                </div>
              )}
              {!showProgress && completedJobId && (
                <Button
                  size="sm"
                  onClick={() => router.push(`/analyses/${encodeURIComponent(completedJobId)}`)}
                  className="flex items-center gap-2"
                >
                  <FileText className="h-4 w-4" />
                  View Result Package
                </Button>
              )}
              {advancedMode && latestSnapshot && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleOpenInPipelineBuilder}
                  className="flex items-center gap-2"
                >
                  <Workflow className="h-4 w-4" />
                  Pipeline Builder
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={copilot.toggleCopilot}
                className="flex items-center gap-2"
              >
                <Bot className="h-4 w-4" />
                AI Copilot
              </Button>
            </div>
          </div>

          {/* Neuro quick presets */}
          {chatMode === 'neuro' && (
            <div className="flex flex-wrap gap-2 px-4 pb-2 text-xs">
              <Button
                size="sm"
                variant="secondary"
                className="w-full justify-start sm:w-auto sm:justify-center"
                onClick={() => {
                  if (!defaultT1w) {
                    toast({
                      title: 'T1 path not set',
                      description: 'Set NEXT_PUBLIC_T1W_IMAGE to enable this preset.',
                      variant: 'destructive'
                    })
                    return
                  }
                  submitPrompt('preprocess my T1 to MNI', [], {
                    mode: 'simple',
                    tools: undefined,
                    threadId: effectiveThreadId,
                    ctx: {
                      use_planning_engine: true,
                      pipeline_preview: true,
                      preview: true,
                      t1w_image: defaultT1w,
                      work_dir: '/tmp/br_work',
                      output_dir: '/tmp/br_out',
                    }
                  })
                }}
              >
                T1 → MNI (preview)
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="w-full justify-start sm:w-auto sm:justify-center"
                onClick={() => {
                  if (!defaultStatMap) {
                    toast({
                      title: 'Stat map not set',
                      description: 'Set NEXT_PUBLIC_STAT_MAP to enable this preset.',
                      variant: 'destructive'
                    })
                    return
                  }
                  submitPrompt('visualize this stat map', [], {
                    mode: 'simple',
                    tools: undefined,
                    threadId: effectiveThreadId,
                    ctx: {
                      stat_map: defaultStatMap,
                      display_mode: 'ortho',
                      preview: true,
                      use_planning_engine: true,
                    }
                  })
                }}
              >
                Viz stat map
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="w-full justify-start sm:w-auto sm:justify-center"
                onClick={() => {
                  if (!defaultBold || !defaultMask) {
                    toast({
                      title: 'BOLD or mask not set',
                      description: 'Set NEXT_PUBLIC_BOLD_FILE and NEXT_PUBLIC_MASK_FILE to enable this preset.',
                      variant: 'destructive'
                    })
                    return
                  }
                  submitPrompt('run ICA+FIX+ClustSim on this BOLD', [], {
                    mode: 'simple',
                    tools: undefined,
                    threadId: effectiveThreadId,
                    ctx: {
                      use_planning_engine: true,
                      pipeline_preview: true,
                      preview: true,
                      bold_file: defaultBold,
                      mask_file: defaultMask,
                      work_dir: '/tmp/br_work',
                      output_dir: '/tmp/br_out',
                    }
                  })
                }}
              >
                ICA/FIX/ClustSim
              </Button>
            </div>
          )}
          
          {threadLoading ? (
            <div className="px-4 py-2 border-b text-xs text-muted-foreground flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading thread history…
            </div>
          ) : null}

          {threadLoadError ? (
            <div className="px-4 py-2 border-b text-xs text-red-700 bg-red-50 flex items-center justify-between gap-2">
              <span className="truncate">Failed to load thread: {threadLoadError}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => void loadThreadHistory()}
              >
                Retry
              </Button>
            </div>
          ) : null}

          {activeRepairContext ? (
            <div className="px-4 py-3 border-b">
              <Alert variant="warning">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <AlertTitle className="flex items-center gap-2">
                      <Wrench className="h-4 w-4" />
                      Repair mode active
                    </AlertTitle>
                    <AlertDescription>
                      Repairing run {activeRepairContext.run_id.slice(0, 8)}
                      {activeRepairContext.failing_step?.name
                        ? ` at ${activeRepairContext.failing_step.name}`
                        : ''}
                      {activeRepairContext.tool_name ? ` using ${activeRepairContext.tool_name}` : ''}.
                    </AlertDescription>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>Attempt {activeRepairContext.repair_attempt_count}</span>
                      {activeRepairContext.error_type ? (
                        <span>Error type: {activeRepairContext.error_type}</span>
                      ) : null}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setActiveRepairContext(null)
                      setChatMode('chat')
                    }}
                  >
                    Exit repair
                  </Button>
                </div>
              </Alert>
            </div>
          ) : null}

          {messages.length === 0 && planIsEmpty ? (
            <StudioWelcomeScreen
              onSubmitPrompt={handleAskAgent}
              onPickPipeline={handleWelcomePickPipeline}
              onOpenMcpModal={openMcpModal}
            />
          ) : (
            <MessageList
              messages={messages}
              onCancelExecution={cancelExecution}
              onResumeFromCheckpoint={(ckpt) => {
                setResumeCheckpointId(ckpt)
                // optionally auto-submit? leaving manual: populate composer via callback
              }}
              onAskAgent={handleAskAgent}
              onReplacePlan={handleReplacePlan}
              onApplyRepair={handleApplyRepairProposal}
              onRevalidateRepair={handleRevalidateRepairProposal}
              onHandOffRepair={handleRepairHandOff}
            />
          )}

          <div className="p-4 border-t">
            {resumeCheckpointId && (
              <div className="flex items-center justify-between mb-2 text-xs text-muted-foreground">
                <span>Resuming from checkpoint {resumeCheckpointId}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  onClick={() => setResumeCheckpointId(null)}
                >
                  Clear
                </Button>
              </div>
            )}
            <ChatComposer 
              initialValue={draftPrompt}
              injectedText={copilotInjectedText}
              onConsumeInjectedText={() => setCopilotInjectedText(null)}
              onSubmit={(prompt, attachments) => {
                const activeResume = resumeCheckpointId
                const effectiveDatasetId = planComposerContext.datasetId ?? datasetId
                const effectiveDatasetVersion =
                  planComposerContext.datasetVersion ?? datasetVersion
                const effectivePipeline = planComposerContext.pipelineId ?? pipeline
                const effectiveResourceSummary =
                  planComposerContext.datasetResourceSummary
                const tools = chatMode === 'coding' ? { mode: 'coding' } : undefined
                const repo_root = repoRootInput?.trim() || defaultRepoRoot
                const file_paths = filePathsInput
                  .split(/[,\n]/)
                  .map(p => p.trim())
                  .filter(Boolean)
                const baseCtx = chatMode === 'coding'
                  ? {
                      repo_root,
                      file_paths,
                      apply: false,
                      dry_run: true,
                      preview: true,
                      force_code_agent: !repo_root,
                      explain_only: explainOnly || undefined,
                    }
                  : undefined
                const ctx = baseCtx

                submitPrompt(prompt, attachments, {
                  mode: 'simple',
                  pipeline: effectivePipeline ?? undefined,
                  datasetId: effectiveDatasetId ?? undefined,
                  datasetVersion: effectiveDatasetVersion ?? undefined,
                  datasetResourceSummary: effectiveResourceSummary ?? undefined,
                  parameters: {
                    ...(buildParameters() || {}),
                  },
                  systemPrompt,
                  scenarioId,
                  resumeCheckpointId: activeResume,
                  codingMode,
                  threadId: effectiveThreadId,
                  tools,
                  ctx,
                  repoRoot: repo_root,
                  filePaths: ctx?.file_paths,
                  forceCodeAgent: chatMode === 'coding' && !repo_root,
                  explainOnly: explainOnly,
                })
                if (activeResume) {
                  setResumeCheckpointId(null)
                }
              }}
              isLoading={isLoading}
              codingMode={codingMode}
              onToggleCodingMode={() => setChatMode((prev) => prev === 'coding' ? 'chat' : 'coding')}
              explainOnly={explainOnly}
              onToggleExplainOnly={() => setExplainOnly((prev) => !prev)}
              context={{
                dataset: planComposerContext.datasetId ?? undefined,
                datasetVersion: planComposerContext.datasetVersion ?? undefined,
                pipeline: planComposerContext.pipelineLabel ?? undefined,
              }}
            />
          </div>
        </div>

        {/* Studio canvas */}
        <div className="min-h-[42vh] overflow-hidden border-t bg-background lg:min-h-0 lg:border-l lg:border-t-0">
          <Tabs
            value={canvasTab}
            onValueChange={(value) => setCanvasTab(value as typeof canvasTab)}
            className="h-full flex flex-col overflow-hidden"
          >
            <div className="p-4 border-b">
              <TabsList className={`grid h-auto w-full ${canvasTabColumnsClass} sm:inline-flex sm:h-9 sm:w-auto sm:justify-start`}>
                <TabsTrigger value="plan" className="min-w-0 px-2 sm:px-3">Plan</TabsTrigger>
                <TabsTrigger value="results" className="min-w-0 px-2 sm:px-3">Results</TabsTrigger>
                <TabsTrigger value="charts" className="min-w-0 px-2 sm:px-3">Charts</TabsTrigger>
                {advancedMode ? <TabsTrigger value="steps" className="min-w-0 px-2 sm:px-3">Steps</TabsTrigger> : null}
              </TabsList>
            </div>

            <TabsContent value="plan" className="mt-0 flex-1 overflow-y-auto p-4">
              <div className="space-y-4">
                {pendingPlanSuggestion ? (
                  <Alert variant="warning">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <AlertTitle>Agent has a new plan suggestion</AlertTitle>
                        <AlertDescription>
                          {planEditing
                            ? 'Finish editing Step Inspector to apply the suggestion.'
                            : 'Review and apply the suggestion when ready.'}
                        </AlertDescription>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          size="sm"
                          disabled={planEditing}
                          onClick={() => openReplacePlanDialog(pendingPlanSuggestion.pipelineId)}
                        >
                          Replace Plan
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setPendingPlanSuggestion(null)}
                        >
                          Dismiss
                        </Button>
                      </div>
                    </div>
                  </Alert>
                ) : null}
                <StudioPlanPanel
                  key={`plan-${planPanelNonce}`}
                  datasetId={datasetId}
                  datasetVersion={datasetVersion}
                  conceptId={conceptId}
                  projectId={projectId}
                  initialPipelineId={pipeline}
                  threadId={effectiveThreadId}
                  dagJobId={activeJobId || analysisId}
                  onEditingChange={setPlanEditing}
                  onEmptyPlanChange={setPlanIsEmpty}
                  onContextChange={handlePlanContextChange}
                  onRunCreated={handleRunCreated}
                  onAskAgent={handleAskAgent}
                  validationRequestNonce={planValidationNonce}
                />
                {advancedMode && latestSnapshot ? (
                  <Button variant="outline" size="sm" onClick={handleOpenInPipelineBuilder}>
                    Open in Pipeline Builder
                  </Button>
                ) : null}
              </div>
            </TabsContent>

            <TabsContent value="results" className="mt-0 flex-1 overflow-hidden">
              <div className="h-full flex flex-col overflow-hidden">
                {showProgress && activeJobId ? (
                  <div className="p-4 border-b bg-blue-50/50">
                    <RealTimeProgress
                      jobId={activeJobId}
                      onCancel={() => cancelExecution(activeJobId)}
                      onComplete={() => {
                        const finishedJobId = activeJobId
                        setShowProgress(false)
                        setActiveJobId(undefined)
                        setLastFailure(null)
                        if (finishedJobId && finishedJobId !== completedJobId) {
                          invalidateRunCardCache(finishedJobId)
                          setCompletedJobId(finishedJobId)
                        }
                        setShowVisualizations(true)
                      }}
                      onError={(error) => {
                        console.error('Execution error:', error)
                        const finishedJobId = activeJobId
                        setShowProgress(false)
                        setActiveJobId(undefined)
                        setShowVisualizations(false)
                        if (finishedJobId) {
                          invalidateRunCardCache(finishedJobId)
                          setCompletedJobId(finishedJobId)
                          const message =
                            error instanceof Error
                              ? error.message
                              : typeof error === 'string'
                                ? error
                                : JSON.stringify(error)
                          setLastFailure({ jobId: finishedJobId, message })
                        }
                      }}
                      // Prefer the UI BFF for SSE (stable contract), but keep orchestrator polling as fallback.
                      sseEndpoint={(() => {
                        const manual = (process.env.NEXT_PUBLIC_SSE_ENDPOINT || '').trim()
                        const defaultEndpoint = '/api/analyses'
                        if (!manual) {
                          return defaultEndpoint
                        }
                        if (serviceEndpoints.useProxy && !manual.startsWith('/')) {
                          return defaultEndpoint
                        }
                        return manual
                      })()}
                      pollingEndpoint={(() => {
                        const manual = (process.env.NEXT_PUBLIC_POLLING_ENDPOINT || '').trim()
                        const defaultEndpoint = '/api/analyses'
                        if (!manual) {
                          return defaultEndpoint
                        }
                        if (serviceEndpoints.useProxy && !manual.startsWith('/')) {
                          return defaultEndpoint
                        }
                        return manual
                      })()}
                    />
                  </div>
                ) : null}

                <div className="flex-1 overflow-hidden">
                  {showProgress && activeJobId ? (
                    <div className="h-full p-4">
                      <div className="text-sm font-medium">Running…</div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        The result package will appear here when the run completes.
                      </div>
                    </div>
                  ) : !evidenceJobId ? (
                    <div className="h-full p-4">
                      <div className="text-sm font-medium">No results yet</div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        Complete your plan and click &quot;Approve &amp; Run&quot; to start.
                      </div>
                      <div className="mt-3">
                        <Button size="sm" onClick={() => setCanvasTab('plan')}>
                          View Plan
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="h-full flex flex-col overflow-hidden">
                      <div className="p-4 border-b flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span>Run: {evidenceJobId.slice(0, 8)}</span>
                            <Badge variant={topBarStatusVariant}>{topBarStatusLabel}</Badge>
                            {resultTimestampLabel ? <span>• {resultTimestampLabel}</span> : null}
                            {resultDurationLabel ? <span>• Duration: {resultDurationLabel}</span> : null}
                          </div>
                          {analysisDetailError ? (
                            <div className="text-xs text-red-600">Failed to load run metadata.</div>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-2">
                          {hydrated ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => setShareModalOpen(true)}
                            >
                              Share
                            </Button>
                          ) : null}
                          <Button variant="outline" size="sm" asChild>
                            <a href={`/api/analyses/${encodeURIComponent(evidenceJobId)}/export`}>
                              Export ZIP
                            </a>
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => router.push(`/analyses/${encodeURIComponent(evidenceJobId)}`)}
                          >
                            Detail
                          </Button>
                        </div>
                      </div>
                      {effectiveThreadId && effectiveThreadId !== 'default' ? (
                        <div className="p-4 border-b">
                          <AttemptSwitcher
                            threadId={effectiveThreadId}
                            currentAnalysisId={evidenceJobId}
                            onSelect={handleSelectAttempt}
                          />
                        </div>
                      ) : null}

                      {showSuccessBlocks && evidenceJobId ? (
                        <div className="p-4 border-b space-y-3">
                          <Card>
                            <CardHeader className="pb-2">
                              <CardTitle className="text-sm">Summary</CardTitle>
                            </CardHeader>
                            <CardContent className="pt-0">
                              {summaryBullets.length ? (
                                <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-5">
                                  {summaryBullets.map((line) => (
                                    <li key={line}>{line}</li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="text-sm text-muted-foreground">
                                  No summary yet.
                                </div>
                              )}
                            </CardContent>
                          </Card>

                          <Card>
                            <CardHeader className="pb-2">
                              <div className="flex items-center justify-between gap-2">
                                <CardTitle className="text-sm">Key outputs</CardTitle>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => router.push(`/analyses/${encodeURIComponent(evidenceJobId)}`)}
                                >
                                  View all{artifactCount ? ` (${artifactCount})` : ''}
                                </Button>
                              </div>
                            </CardHeader>
                            <CardContent className="pt-0 space-y-2">
                              {keyArtifacts.length ? (
                                keyArtifacts.map((artifact: any, idx: number) => (
                                  (() => {
                                    const artifactUrl = extractArtifactUrl(artifact)
                                    const artifactName = extractArtifactName(artifact) ?? 'Artifact'
                                    const brainMapArtifact = isBrainMapArtifact(artifact)

                                    return (
                                      <div
                                        key={String(artifact?.id || idx)}
                                        className="flex items-center justify-between gap-3"
                                      >
                                        <div className="min-w-0">
                                          <div className="text-sm font-medium truncate">
                                            {artifactName}
                                          </div>
                                          {artifact?.type ? (
                                            <div className="text-xs text-muted-foreground">
                                              {String(artifact.type)}
                                            </div>
                                          ) : null}
                                        </div>
                                        <div className="flex items-center gap-1">
                                          {brainMapArtifact && studioBrainViewerEnabled ? (
                                            <Button
                                              variant="outline"
                                              size="sm"
                                              className="h-8"
                                              onClick={() =>
                                                openBrainMapArtifact(artifact, evidenceJobId || analysisId || null)
                                              }
                                            >
                                              View brain map
                                            </Button>
                                          ) : null}
                                          {artifactUrl ? (
                                            <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
                                              <a href={artifactUrl} target="_blank" rel="noopener noreferrer">
                                                <ExternalLink className="h-4 w-4" />
                                              </a>
                                            </Button>
                                          ) : null}
                                          {artifactUrl && !brainMapArtifact ? (
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8"
                                              aria-label="Preview"
                                              onClick={() => {
                                                setArtifactPreviewTarget({
                                                  name: artifactName,
                                                  url: artifactUrl,
                                                })
                                                setArtifactPreviewOpen(true)
                                              }}
                                            >
                                              <FileText className="h-4 w-4" />
                                            </Button>
                                          ) : null}
                                          {artifactUrl ? (
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="h-8 w-8"
                                              onClick={async () => {
                                                try {
                                                  await navigator.clipboard.writeText(artifactUrl)
                                                  toast({
                                                    title: 'Link copied',
                                                    description: 'Artifact URL copied to clipboard.',
                                                    duration: 2000,
                                                  })
                                                } catch (err) {
                                                  toast({
                                                    title: 'Failed to copy link',
                                                    description: err instanceof Error ? err.message : String(err),
                                                    variant: 'destructive',
                                                    duration: 4000,
                                                  })
                                                }
                                              }}
                                            >
                                              <Copy className="h-4 w-4" />
                                            </Button>
                                          ) : null}
                                        </div>
                                      </div>
                                    )
                                  })()
                                ))
                              ) : (
                                <div className="text-sm text-muted-foreground">
                                  No artifacts yet.
                                </div>
                              )}
                            </CardContent>
                          </Card>

                          {kgSuggestionsCount && kgSuggestionsCount > 0 ? (
                            <Card>
                              <CardHeader className="pb-2">
                                <CardTitle className="text-sm">KG Suggestions ({kgSuggestionsCount})</CardTitle>
                              </CardHeader>
                              <CardContent className="pt-0 space-y-2">
                                <div className="text-sm text-muted-foreground">
                                  {kgSuggestionsCount} findings can be added to the Knowledge Graph.
                                </div>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => router.push('/kg?tab=suggestions')}
                                >
                                  Review Suggestions
                                </Button>
                              </CardContent>
                            </Card>
                          ) : null}
                        </div>
                      ) : null}

                      {showDiagnosisCard && evidenceJobId ? (
                        <div className="p-4 border-b bg-red-50/50">
                          <DiagnosisCard
                            title={diagnosisTitle}
                            message={diagnosisMessage}
                            whatHappened={diagnosisDetails.whatHappened}
                            suggestedActions={diagnosisDetails.suggestedActions}
                            viewToolHref={diagnosisToolHref}
                            onSwitchVersion={
                              diagnosisToolLabel
                                ? () => {
                                    setCanvasTab('plan')
                                    handleAskAgent(
                                      buildAskAgentSwitchVersionPrompt(
                                        evidenceJobId,
                                        diagnosisToolLabel,
                                        diagnosisMessage,
                                      ),
                                    )
                                  }
                                : undefined
                            }
                            onAskAgent={() => {
                              handleRepairInStudio(evidenceJobId, diagnosisMessage)
                            }}
                            onRetry={() => handleRetry(evidenceJobId)}
                            onViewLogs={() => {
                              openConsole()
                              if (advancedMode) setCanvasTab('steps')
                            }}
                          />
                        </div>
                      ) : null}
                      <div className="flex-1 overflow-hidden">
                        <EvidenceRail
                          runCard={currentRunCard}
                          jobId={evidenceJobId}
                          className="w-full h-full border-l-0"
                          transferAvailable={advancedMode ? Boolean(latestSnapshot) : false}
                          onTransferToPipeline={
                            advancedMode && latestSnapshot ? handleOpenInPipelineBuilder : undefined
                          }
                          onEvidenceDataChange={setEvidenceRailData}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="charts" className="mt-0 flex-1 overflow-hidden">
              {studioBrainViewerEnabled && selectedViewerArtifact ? (
                <div className="h-full overflow-y-auto p-4">
                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <CardTitle className="text-sm">Brain map viewer</CardTitle>
                          <div className="mt-1 truncate text-sm text-muted-foreground">
                            {selectedViewerArtifact.name}
                          </div>
                        </div>
                        {showVisualizations ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setSelectedViewerArtifact(null)
                            }}
                          >
                            Show charts
                          </Button>
                        ) : null}
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <Brain3D
                        key={`${selectedViewerArtifact.analysisId || 'standalone'}:${selectedViewerArtifact.url}`}
                        jobId={selectedViewerArtifact.analysisId || undefined}
                        config={
                          selectedViewerArtifact.analysisId
                            ? undefined
                            : { baseVolume: selectedViewerArtifact.url }
                        }
                        preferredOverlayName={selectedViewerArtifact.name}
                        preferredOverlayUrl={selectedViewerArtifact.url}
                        height="600px"
                      />
                    </CardContent>
                  </Card>
                </div>
              ) : showVisualizations ? (
                <div className="h-full overflow-y-auto">
                  <VisualizationPanel
                    knowledgeGraph={visualizationData.knowledgeGraph || undefined}
                    brainMaps={visualizationData.brainMaps}
                    className="p-4"
                  />
                </div>
              ) : (
                <div className="h-full p-4">
                  <div className="text-sm font-medium">No charts yet</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Complete a run to see visualizations here.
                  </div>
                  <div className="mt-3">
                    <Button asChild variant="outline" size="sm">
                      <Link href="/charts">View Demo Charts</Link>
                    </Button>
                  </div>
                </div>
              )}
            </TabsContent>

            {advancedMode ? (
              <TabsContent value="steps" className="mt-0 flex-1 overflow-hidden">
                {evidenceJobId ? (
                  <div className="h-full overflow-y-auto">
                    <Dialog open={streamEventsOpen} onOpenChange={setStreamEventsOpen}>
                      <DialogContent className="max-w-3xl">
                        <DialogHeader>
                          <DialogTitle>Run stream events</DialogTitle>
                          <DialogDescription className="sr-only">
                            Inspect the live stream event log for this run.
                          </DialogDescription>
                        </DialogHeader>
                        <AnalysisStreamEventsPanel analysisId={evidenceJobId} />
                      </DialogContent>
                    </Dialog>

                    <div className="p-4 border-b flex items-center justify-between gap-2">
                      <div className="text-sm font-medium">Steps</div>
                      <Button variant="outline" size="sm" onClick={() => setStreamEventsOpen(true)}>
                        View stream events
                      </Button>
                    </div>
                    <div className="p-4 pt-0">
                      <StepsList jobId={evidenceJobId} enableStreaming onAskAgent={handleAskAgent} />
                    </div>
                  </div>
                ) : (
                  <div className="h-full p-4">
                    <div className="text-sm font-medium">No steps to show</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      Start a run to stream step-level progress and logs.
                    </div>
                    <div className="mt-3">
                      <Button variant="outline" size="sm" onClick={() => router.push('/analyses')}>
                        Browse runs
                      </Button>
                    </div>
                  </div>
                )}
              </TabsContent>
            ) : null}
          </Tabs>
        </div>
      </div>

      {showConsole && consoleJobId ? (
        <div className="border-t bg-background" data-testid="console-panel">
          <div className="px-4 py-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm">
              <Terminal className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium">Console</span>
              <span className="text-muted-foreground">
                {showProgress ? 'Running' : showDiagnosisCard ? 'Error' : '—'}
              </span>
              <span className="text-muted-foreground">•</span>
              <span className="text-xs text-muted-foreground">
                Job {consoleJobId.slice(0, 8)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {hydrated ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setConsoleOpen((prev) => !prev)}
                  >
                    {consoleOpen ? (
                      <>
                        <ChevronDown className="mr-2 h-4 w-4" />
                        Collapse
                      </>
                    ) : (
                      <>
                        <ChevronUp className="mr-2 h-4 w-4" />
                        Logs
                      </>
                    )}
                  </Button>
                  {showDiagnosisCard ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleRepairInStudio(consoleJobId, diagnosisMessage)}
                    >
                      Repair in Studio
                    </Button>
                  ) : null}
                  <Button size="sm" variant="outline" onClick={downloadConsoleLogs}>
                    <Download className="mr-2 h-4 w-4" />
                    Download logs
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8"
                    onClick={() => setConsoleDismissedForJobId(consoleJobId)}
                    aria-label="Dismiss console"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </>
              ) : (
                <div className="text-xs text-muted-foreground">Loading…</div>
              )}
            </div>
          </div>

          {consoleOpen ? (
            <div className="border-t max-h-80 overflow-y-auto">
              <div className="p-4">
                {streamLogLines.length || streamArtifacts.length || streamUnknownCount ? (
                  <div className="mb-4 rounded-lg border bg-muted/10 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Stream
                      </div>
                      {streamUnknownCount ? (
                        <Badge variant="outline" className="text-xs" data-testid="console-stream-unknown">
                          Unknown events {streamUnknownCount}
                        </Badge>
                      ) : null}
                    </div>
                    {streamLogLines.length ? (
                      <pre
                        data-testid="console-stream-logs"
                        className="mt-2 max-h-28 overflow-auto rounded-md border bg-background p-2 text-xs"
                      >
                        {streamLogLines
                          .slice(-20)
                          .map((entry) => `${entry.timestamp} [${entry.stream}] ${entry.line}`)
                          .join('\n')}
                      </pre>
                    ) : (
                      <div className="mt-2 text-xs text-muted-foreground">No streamed logs yet.</div>
                    )}
                    {streamArtifacts.length ? (
                      <div className="mt-3 space-y-1" data-testid="console-stream-artifacts">
                        {streamArtifacts.slice(-5).map((entry, idx) => (
                          <div
                            key={`${entry.artifact.uri}-${idx}`}
                            className="text-xs text-muted-foreground break-all"
                            data-testid={`console-stream-artifact-${idx}`}
                          >
                            {entry.artifact.uri}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <StepsList jobId={consoleJobId} enableStreaming onAskAgent={handleAskAgent} />
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Copilot panel */}
      <CopilotPanel
        isOpen={copilot.isOpen}
        messages={copilot.messages}
        suggestions={copilot.suggestions}
        recommendations={copilot.recommendations}
        isLoading={copilot.isLoading}
        onClose={copilot.toggleCopilot}
        onSendMessage={copilot.sendMessage}
        onInsertParameter={handleInsertParameter}
        onInsertMethod={handleInsertMethod}
        onClearMessages={copilot.clearMessages}
        filters={copilot.filters}
        onUpdateFilters={copilot.setFilters}
      />
    </div>
  )
}
