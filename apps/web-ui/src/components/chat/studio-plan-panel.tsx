'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { Code2, Loader2, Sparkles } from 'lucide-react'

import { ANALYSIS_TYPES, PipelineOption } from '@/config/analysis-presets'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import type { WorkflowDetail as DynamicWorkflowDetail } from '@/lib/api/workflows'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { CREDITS_UPDATED_EVENT } from '@/lib/credits'
import { resolveKgConceptSummaryUrl } from '@/lib/service-endpoints'
import { cn } from '@/lib/utils'
import { buildDatasetsPickerHref, buildStudioPlanHref } from '@/lib/studio-navigation'
import { legacyPipelineWorkflowAlias } from '@/lib/workflow-template-aliases'
import type { DatasetDetailResponse, DatasetResourceAddresses } from '@/types/datasets-search'
import { PlanAdvancedPanel } from '@/components/chat/plan/plan-advanced-panel'
import { PlanDagView } from '@/components/chat/plan-dag-view'
import { ReadOnlyPlanAlertsCard } from '@/components/chat/plan/read-only-plan-alerts-card'
import { ReadOnlyPlanHeader } from '@/components/chat/plan/read-only-plan-header'
import { ReadOnlyPlanRunGate } from '@/components/chat/plan/read-only-plan-run-gate'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'
import { ReadOnlyPlanSummaryCard } from '@/components/chat/plan/read-only-plan-summary-card'
import type {
  StudioPlanProjectionAlert,
  StudioPlanProjectionRow,
  StudioPlanProjectionStatus,
} from '@/components/chat/plan/studio-plan-projection-types'
import { useDagStepStatusByOrder } from '@/components/chat/use-dag-step-status'

type ApiPipelineStep = {
  order: number
  tool: string
  description: string
  paramNames: string[]
  paramSchema?: ApiStepParamSchema
  schemas?: Record<string, ApiStepParamSchema>
}

type ApiPipeline = {
  id: string
  name: string
  description: string
  modalities: string[]
  steps: ApiPipelineStep[]
}

type ParameterDialogMode = 'pipeline' | 'step'

type ParameterDialogContext = {
  mode: ParameterDialogMode
  title: string
  step?: ApiPipelineStep
}

type ApiParamPrimitiveType = 'string' | 'number' | 'integer' | 'boolean'

type ApiStepParamProperty = {
  type?: ApiParamPrimitiveType
  title?: string
  description?: string
  enum?: string[]
  default?: unknown
}

type ApiStepParamSchema = {
  version?: string
  required?: string[]
  properties?: Record<string, ApiStepParamProperty>
}

type DynamicWorkflowSchemaResponse = {
  workflow_id?: string
  version?: string
  schema?: {
    type?: string
    required?: string[]
    properties?: Record<string, unknown>
  }
  defaults?: {
    merged?: Record<string, unknown>
    [key: string]: unknown
  }
  discovered_inputs?: string[]
}

const WORKFLOW_INPUT_REF_PATTERN = /\$\{inputs\.([a-zA-Z0-9_]+)(?::-[^}]*)?\}/g

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function uniqueTextValues(values: unknown[]): string[] {
  const out: string[] = []
  for (const value of values) {
    if (Array.isArray(value)) {
      for (const entry of value) {
        const text = normalizeText(entry)
        if (text && !out.includes(text)) out.push(text)
      }
      continue
    }
    const text = normalizeText(value)
    if (text && !out.includes(text)) out.push(text)
  }
  return out
}

function inferPrimitiveType(value: unknown): ApiParamPrimitiveType | undefined {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  if (typeof value === 'string') return 'string'
  return undefined
}

function normalizeSchemaProperty(raw: unknown): ApiStepParamProperty {
  const source = safeRecord(raw) ?? {}
  const out: ApiStepParamProperty = {}
  if (typeof source.type === 'string') {
    const normalized = source.type.trim().toLowerCase()
    if (
      normalized === 'string' ||
      normalized === 'number' ||
      normalized === 'integer' ||
      normalized === 'boolean'
    ) {
      out.type = normalized
    }
  }
  if (typeof source.title === 'string') out.title = source.title
  if (typeof source.description === 'string') out.description = source.description
  if (Array.isArray(source.enum)) {
    out.enum = source.enum
      .map((entry) => (typeof entry === 'string' ? entry.trim() : String(entry)))
      .filter((entry) => entry.length > 0)
  }
  if (Object.prototype.hasOwnProperty.call(source, 'default')) {
    out.default = source.default
  }
  return out
}

function collectWorkflowInputRefs(value: unknown, output: Set<string>) {
  if (typeof value === 'string') {
    const pattern = new RegExp(WORKFLOW_INPUT_REF_PATTERN.source, 'g')
    let match = pattern.exec(value)
    while (match) {
      const key = match[1]?.trim()
      if (key) output.add(key)
      match = pattern.exec(value)
    }
    return
  }
  if (Array.isArray(value)) {
    value.forEach((entry) => collectWorkflowInputRefs(entry, output))
    return
  }
  if (value && typeof value === 'object') {
    Object.values(value).forEach((entry) => collectWorkflowInputRefs(entry, output))
  }
}

function extractWorkflowInputRefs(value: unknown): string[] {
  const keys = new Set<string>()
  collectWorkflowInputRefs(value, keys)
  return Array.from(keys)
}

function normalizeTaskLabel(task: string) {
  return task.trim().toLowerCase().replace(/[^a-z0-9]+/g, '')
}

type PlanCheckStatus = 'pending' | 'passed' | 'warning' | 'blocked'

type PlanCheck = { id: string; label: string; status: PlanCheckStatus; detail?: string }

type LaunchDecision = {
  status?: 'runnable' | 'runnable_with_warning' | 'blocked' | 'handoff_only' | 'manual_admin_only'
  code?: string
  can_launch?: boolean
  primary_action?: 'launch' | 'sign_in' | 'grant_credits' | 'handoff' | 'fix_inputs'
  reason?: string
}

type WorkflowExecutionStatus = {
  recipe_generated?: boolean
  runtime_available?: boolean
  hosted_executed?: boolean
  artifact_verified?: boolean
  runtime_scope?: 'hosted_preflight' | string
  recommended_backend?: 'hosted' | 'local_backend' | 'manual_admin' | 'unresolved' | string
  message?: string
}

type PlanChecksResponse = {
  checks: PlanCheck[]
  launch_decision?: LaunchDecision | null
  execution_status?: WorkflowExecutionStatus | null
  estimate?: {
    runtime?: string
    credits?: number | null
  }
  effective_config?: PlanEffectiveConfig | null
  guidance?: PreflightGuidance | null
  handoff_pack?: Record<string, unknown> | null
}

type PlanEffectiveConfigEntry = {
  key: string
  origin: 'base' | 'default' | 'user' | 'inferred'
  value: unknown
}

type PlanEffectiveConfig = {
  analysis_id: string
  pipeline_id: string
  pipeline_label?: string
  pipeline_type?: string
  tool_id: string
  dataset_id: string
  dataset_version?: string
  parameters: PlanEffectiveConfigEntry[]
  parameter_values: Record<string, unknown>
}

type GuidanceAction = {
  id?: string
  label?: string
  href?: string
  external?: boolean
}

type PreflightGuidance = {
  kind?: string
  access_mode?: string
  runtime_target?: string
  install_path?: string
  summary?: string
  detail?: string | null
  next_action_url?: string | null
  docs_urls?: string[]
  required_modules?: string[]
  required_env_vars?: string[]
  container_images?: Record<string, string>
  supported_recipe_targets?: string[]
  workflow_id?: string | null
  actions?: GuidanceAction[]
}

function guidanceActionLabel(action: GuidanceAction): string {
  if ((action.id || '').toLowerCase() === 'neurodesk-play') return 'Open in Neurodesk Play'
  return action.label || 'Open setup guide'
}

function hasEnabledSearchFlag(searchParams: URLSearchParams, names: string[]): boolean {
  return names.some((name) => {
    const value = searchParams.get(name)
    if (value === null) return false
    const normalized = value.trim().toLowerCase()
    return normalized === '' || normalized === '1' || normalized === 'true' || normalized === 'yes'
  })
}

type PlanDraftStorageV1 = {
  version: 1
  updated_at: number
  dataset_id?: string | null
  dataset_version?: string | null
  concept_ids?: string[]
  intent?: string
  intent_touched?: boolean
  analysis_id?: string | null
  pipeline_id?: string | null
  task?: string | null
  max_models?: number
  parameter_overrides?: Record<string, unknown>
}

const SHARED_PLAN_STORAGE_KEY = 'br:plan:last'

function parsePlanDraft(raw: string | null): PlanDraftStorageV1 | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PlanDraftStorageV1>
    if (parsed.version !== 1) return null
    return {
      version: 1,
      updated_at:
        typeof parsed.updated_at === 'number' && Number.isFinite(parsed.updated_at)
          ? parsed.updated_at
          : 0,
      dataset_id: parsed.dataset_id ?? null,
      dataset_version:
        typeof parsed.dataset_version === 'string'
          ? parsed.dataset_version
          : parsed.dataset_version === null
            ? null
            : undefined,
      concept_ids: Array.isArray(parsed.concept_ids) ? parsed.concept_ids : [],
      intent: typeof parsed.intent === 'string' ? parsed.intent : undefined,
      intent_touched: Boolean(parsed.intent_touched),
      analysis_id: typeof parsed.analysis_id === 'string' ? parsed.analysis_id : null,
      pipeline_id: typeof parsed.pipeline_id === 'string' ? parsed.pipeline_id : null,
      task: typeof parsed.task === 'string' ? parsed.task : null,
      max_models:
        typeof parsed.max_models === 'number' && Number.isFinite(parsed.max_models)
          ? parsed.max_models
          : undefined,
      parameter_overrides:
        parsed.parameter_overrides &&
        typeof parsed.parameter_overrides === 'object' &&
        !Array.isArray(parsed.parameter_overrides)
          ? parsed.parameter_overrides
          : undefined,
    }
  } catch {
    return null
  }
}

function pickRestorePlanDraft(
  threadDraft: PlanDraftStorageV1 | null,
  sharedDraft: PlanDraftStorageV1 | null,
): PlanDraftStorageV1 | null {
  if (threadDraft && sharedDraft) {
    const threadUpdatedAt =
      typeof threadDraft.updated_at === 'number' && Number.isFinite(threadDraft.updated_at)
        ? threadDraft.updated_at
        : 0
    const sharedUpdatedAt =
      typeof sharedDraft.updated_at === 'number' && Number.isFinite(sharedDraft.updated_at)
        ? sharedDraft.updated_at
        : 0
    if (threadUpdatedAt !== sharedUpdatedAt) {
      return threadUpdatedAt > sharedUpdatedAt ? threadDraft : sharedDraft
    }
    const threadIntent =
      typeof threadDraft.intent === 'string' ? threadDraft.intent.trim() : ''
    const sharedIntent =
      typeof sharedDraft.intent === 'string' ? sharedDraft.intent.trim() : ''
    if (!threadIntent && sharedIntent) return sharedDraft
    return threadDraft
  }
  return threadDraft ?? sharedDraft
}

type StudioPlanPanelProps = {
  datasetId?: string
  datasetVersion?: string
  conceptId?: string
  projectId?: string
  initialPipelineId?: string
  threadId?: string
  dagJobId?: string
  onContextChange?: (context: {
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
  }) => void
  onEditingChange?: (editing: boolean) => void
  onEmptyPlanChange?: (empty: boolean) => void
  onRunCreated?: (jobId: string, threadId?: string | null) => void
  onAskAgent?: (prompt: string) => void
  validationRequestNonce?: number
}

export function StudioPlanPanel({
  datasetId,
  datasetVersion,
  conceptId,
  projectId,
  initialPipelineId,
  threadId,
  dagJobId,
  onContextChange,
  onEditingChange,
  onEmptyPlanChange,
  onRunCreated,
  onAskAgent,
  validationRequestNonce,
}: StudioPlanPanelProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { status: authStatus } = useSession()
  const showFixReviewControls = useMemo(
    () => hasEnabledSearchFlag(searchParams, ['studioReviewDebug', 'studioFixReview']),
    [searchParams],
  )
  const pipelineSectionRef = useRef<HTMLDivElement | null>(null)
  const multiverseSectionRef = useRef<HTMLDivElement | null>(null)
  const intentInputRef = useRef<HTMLInputElement | null>(null)

  const [intent, setIntent] = useState('')
  const [intentTouched, setIntentTouched] = useState(false)
  const [dataset, setDataset] = useState<DatasetDetailResponse | null>(null)
  const [datasetLoading, setDatasetLoading] = useState(Boolean(datasetId))
  const [datasetError, setDatasetError] = useState<string | null>(null)
  const [datasetResources, setDatasetResources] = useState<DatasetResourceAddresses | null>(null)
  const [datasetResourcesLoading, setDatasetResourcesLoading] = useState(false)
  const [datasetResourcesError, setDatasetResourcesError] = useState<string | null>(null)
  const [selectedDatasetVersion, setSelectedDatasetVersion] = useState<string | null>(
    datasetVersion?.trim() || null,
  )
  const [conceptIds, setConceptIds] = useState<string[]>([])
  const [conceptLabels, setConceptLabels] = useState<Record<string, string>>({})

  const [apiPipelines, setApiPipelines] = useState<ApiPipeline[]>([])
  const [pipelinesLoading, setPipelinesLoading] = useState(false)

  // Dynamic workflow loaded from /api/workflows/{id} when not found in ANALYSIS_TYPES
  const [dynamicWorkflow, setDynamicWorkflow] = useState<DynamicWorkflowDetail | null>(null)
  const [dynamicWorkflowLoading, setDynamicWorkflowLoading] = useState(false)
  const [dynamicWorkflowError, setDynamicWorkflowError] = useState<string | null>(null)
  const [dynamicWorkflowSchema, setDynamicWorkflowSchema] = useState<DynamicWorkflowSchemaResponse | null>(null)
  const [dynamicWorkflowSchemaLoading, setDynamicWorkflowSchemaLoading] = useState(false)
  const [dynamicWorkflowSchemaError, setDynamicWorkflowSchemaError] = useState<string | null>(null)

  const [selectedAnalysis, setSelectedAnalysis] = useState<string | null>(null)
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [maxModels, setMaxModels] = useState(3)
  const [parameterOverrides, setParameterOverrides] = useState<Record<string, unknown>>({})
  const [parameterDialogContext, setParameterDialogContext] = useState<ParameterDialogContext | null>(null)
  const [parameterDraft, setParameterDraft] = useState<Record<string, unknown>>({})
  const [stepSchemaByVersion, setStepSchemaByVersion] = useState<Record<string, ApiStepParamSchema> | null>(null)
  const [stepSchemaVersion, setStepSchemaVersion] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [toolsUsedOpen, setToolsUsedOpen] = useState(false)
  const [stepsView, setStepsView] = useState<'card' | 'dag'>('card')

  const [creditsRevision, setCreditsRevision] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null
    try {
      return window.localStorage?.getItem('br:credits:updated_at') ?? null
    } catch {
      return null
    }
  })

  const storageKey = useMemo(() => {
    const threadKey = typeof threadId === 'string' && threadId.trim() ? threadId.trim() : 'default'
    return `br:plan:${threadKey}`
  }, [threadId])
  const previousDatasetIdRef = useRef<string | undefined>(datasetId)
  const pendingRestoreRef = useRef<PlanDraftStorageV1 | null>(null)
  const latestIntentRef = useRef(intent)
  const latestIntentTouchedRef = useRef(intentTouched)
  const leavingStudioRef = useRef(false)
  const lastValidationRequestRef = useRef(0)
  const [autosaveReady, setAutosaveReady] = useState(false)

  const [planChecks, setPlanChecks] = useState<PlanCheck[] | null>(null)
  const [checksLoading, setChecksLoading] = useState(false)
  const [checksError, setChecksError] = useState<string | null>(null)
  const [estimate, setEstimate] = useState<PlanChecksResponse['estimate'] | null>(null)
  const [launchDecision, setLaunchDecision] = useState<LaunchDecision | null>(null)
  const [effectiveConfig, setEffectiveConfig] = useState<PlanEffectiveConfig | null>(null)
  const [handoffPack, setHandoffPack] = useState<Record<string, unknown> | null>(null)
  const [studioHandoffOpen, setStudioHandoffOpen] = useState(false)
  const [studioHandoffPayload, setStudioHandoffPayload] =
    useState<HandoffTemplatePayload | null>(null)
  const [environmentGuidance, setEnvironmentGuidance] = useState<PreflightGuidance | null>(null)
  const [executionStatus, setExecutionStatus] = useState<WorkflowExecutionStatus | null>(null)
  const [effectiveCopyStatus, setEffectiveCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle')
  const [checksRefreshToken, setChecksRefreshToken] = useState(0)

  const buildDraftPayload = useCallback((): PlanDraftStorageV1 => {
    return {
      version: 1,
      updated_at: Date.now(),
      dataset_id: datasetId ?? null,
      dataset_version: selectedDatasetVersion ?? null,
      concept_ids: conceptIds,
      intent: latestIntentRef.current,
      intent_touched: latestIntentTouchedRef.current,
      analysis_id: selectedAnalysis ?? null,
      pipeline_id: selectedPipeline ?? null,
      task: selectedTask ?? null,
      max_models: maxModels,
      parameter_overrides: parameterOverrides,
    }
  }, [
    conceptIds,
    datasetId,
    selectedDatasetVersion,
    maxModels,
    parameterOverrides,
    selectedAnalysis,
    selectedPipeline,
    selectedTask,
  ])

  useEffect(() => {
    latestIntentRef.current = intent
  }, [intent])

  useEffect(() => {
    latestIntentTouchedRef.current = intentTouched
  }, [intentTouched])

  const writePlanDraft = useCallback(
    (draft: PlanDraftStorageV1) => {
      if (typeof window === 'undefined') return
      try {
        const encoded = JSON.stringify(draft)
        window.localStorage.setItem(storageKey, encoded)
        window.localStorage.setItem(SHARED_PLAN_STORAGE_KEY, encoded)
      } catch (error) {
        console.warn('Failed to save plan draft:', error)
      }
    },
    [storageKey],
  )

  const persistPlanDraftNow = useCallback(
    (overrides?: Partial<PlanDraftStorageV1>) => {
      const draft = { ...buildDraftPayload(), ...(overrides ?? {}), updated_at: Date.now() }
      writePlanDraft(draft)
    },
    [buildDraftPayload, writePlanDraft],
  )

  const persistCurrentIntentDraftNow = useCallback(() => {
    const currentIntent = intentInputRef.current?.value ?? latestIntentRef.current
    const currentIntentTouched = currentIntent.trim().length > 0
    latestIntentRef.current = currentIntent
    latestIntentTouchedRef.current = currentIntentTouched
    persistPlanDraftNow({
      intent: currentIntent,
      intent_touched: currentIntentTouched,
    })
  }, [persistPlanDraftNow])

  const closeParameterDialog = useCallback(() => {
    setParameterDialogContext(null)
    setStepSchemaByVersion(null)
    setStepSchemaVersion(null)
  }, [])

  useEffect(() => {
    onEditingChange?.(Boolean(parameterDialogContext))
  }, [onEditingChange, parameterDialogContext])

  useEffect(() => {
    onContextChange?.({
      datasetId: datasetId ?? null,
      datasetVersion: selectedDatasetVersion ?? null,
      analysisId: selectedAnalysis ?? null,
      analysisLabel: selectedAnalysis ?? null,
      pipelineId: selectedPipeline ?? null,
      pipelineLabel: selectedPipeline ?? null,
      datasetResourceSummary: datasetResources
        ? {
            selectedVersion:
              typeof datasetResources.selected_version === 'string'
                ? datasetResources.selected_version
                : null,
            readinessStatus:
              typeof datasetResources.readiness?.status === 'string'
                ? datasetResources.readiness.status
                : null,
            bucketCheckState:
              typeof datasetResources.source_access?.bucket_check?.state === 'string'
                ? datasetResources.source_access.bucket_check.state
                : null,
            versionCheckMode:
              typeof datasetResources.source_access?.version_check?.mode === 'string'
                ? datasetResources.source_access.version_check.mode
                : null,
            resolvedVersion:
              typeof datasetResources.source_access?.version_check?.resolved === 'string'
                ? datasetResources.source_access.version_check.resolved
                : null,
            subjectsCount:
              typeof datasetResources.dataset_summary?.subjects_count === 'number'
                ? datasetResources.dataset_summary.subjects_count
                : null,
            totalMatchedFiles:
              typeof datasetResources.files_summary?.total_matched_files === 'number'
                ? datasetResources.files_summary.total_matched_files
                : null,
            s3Uri:
              typeof datasetResources.addresses?.s3_uri === 'string'
                ? datasetResources.addresses.s3_uri
                : null,
            openneuroUrl:
              typeof datasetResources.addresses?.openneuro_url === 'string'
                ? datasetResources.addresses.openneuro_url
                : null,
            sourceRepoUrl:
              typeof datasetResources.addresses?.source_repo_url === 'string'
                ? datasetResources.addresses.source_repo_url
                : null,
          }
        : undefined,
    })
  }, [
    datasetResources,
    datasetId,
    onContextChange,
    selectedAnalysis,
    selectedDatasetVersion,
    selectedPipeline,
  ])

  useEffect(() => {
    if (typeof window === 'undefined') return
    setAutosaveReady(false)
    try {
      const parsed = pickRestorePlanDraft(
        parsePlanDraft(window.localStorage.getItem(storageKey)),
        parsePlanDraft(window.localStorage.getItem(SHARED_PLAN_STORAGE_KEY)),
      )
      if (!parsed) return
      const restoredIntent = typeof parsed.intent === 'string' ? parsed.intent : ''
      const hasRestoredIntent = restoredIntent.trim().length > 0

      const savedDatasetId =
        typeof parsed.dataset_id === 'string' && parsed.dataset_id.trim()
          ? parsed.dataset_id.trim()
          : null
      const datasetMatches = !datasetId || !savedDatasetId || savedDatasetId === datasetId
      if (!datasetMatches) {
        // Avoid leaking plan intent across different datasets.
        return
      }

      pendingRestoreRef.current = parsed as PlanDraftStorageV1

      if (typeof parsed.intent === 'string') {
        setIntent(restoredIntent)
        latestIntentRef.current = restoredIntent
        latestIntentTouchedRef.current = Boolean(parsed.intent_touched) || hasRestoredIntent
        setIntentTouched(Boolean(parsed.intent_touched) || hasRestoredIntent)
      }
      if (typeof parsed.dataset_version === 'string' && parsed.dataset_version.trim()) {
        setSelectedDatasetVersion(parsed.dataset_version.trim())
      } else if (parsed.dataset_version === null) {
        setSelectedDatasetVersion(null)
      }

      if (Array.isArray(parsed.concept_ids)) {
        const normalizedConcepts = parsed.concept_ids
          .filter((value): value is string => typeof value === 'string')
          .map((value) => value.trim())
          .filter(Boolean)
        if (normalizedConcepts.length) {
          setConceptIds(Array.from(new Set(normalizedConcepts)).slice(0, 12))
        }
      }

      if (typeof parsed.max_models === 'number' && Number.isFinite(parsed.max_models)) {
        setMaxModels(Math.max(1, Math.min(20, Math.floor(parsed.max_models))))
      }

      if (
        !initialPipelineId &&
        typeof parsed.analysis_id === 'string' &&
        parsed.analysis_id.trim()
      ) {
        setSelectedAnalysis(parsed.analysis_id.trim())
      }

      if (!initialPipelineId && typeof parsed.pipeline_id === 'string' && parsed.pipeline_id.trim()) {
        setSelectedPipeline(parsed.pipeline_id.trim())
      }

      if (typeof parsed.task === 'string' && parsed.task.trim()) {
        setSelectedTask(parsed.task.trim())
      }
    } catch (error) {
      console.warn('Failed to restore plan draft from localStorage:', error)
    } finally {
      setAutosaveReady(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, storageKey])

  useEffect(() => {
    const trimmed = typeof conceptId === 'string' ? conceptId.trim() : ''
    if (!trimmed) return
    setConceptIds((prev) => {
      if (prev.includes(trimmed)) return prev
      return [...prev, trimmed].slice(0, 12)
    })
  }, [conceptId])

  useEffect(() => {
    if (!conceptIds.length) return

    const missing = conceptIds.filter((id) => !conceptLabels[id])
    if (!missing.length) return

    let cancelled = false
    const controller = new AbortController()

    const load = async () => {
      const updates: Record<string, string> = {}
      await Promise.all(
        missing.map(async (id) => {
          try {
            const res = await fetch(resolveKgConceptSummaryUrl(id), {
              cache: 'no-store',
              signal: controller.signal,
            })
            if (!res.ok) return
            const json = (await res.json().catch(() => null)) as any
            const label = typeof json?.label === 'string' ? json.label.trim() : ''
            if (!label) return
            updates[id] = label
          } catch {
            // ignore
          }
        }),
      )

      if (cancelled) return
      if (!Object.keys(updates).length) return
      setConceptLabels((prev) => ({ ...prev, ...updates }))
    }

    void load()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [conceptIds, conceptLabels])

  useEffect(() => {
    const previousDatasetId = previousDatasetIdRef.current
    if (previousDatasetId !== datasetId) {
      setSelectedTask(null)
    }
    previousDatasetIdRef.current = datasetId
  }, [datasetId])

  useEffect(() => {
    if (!datasetId) {
      setDataset(null)
      setDatasetError(null)
      setDatasetLoading(false)
      setSelectedDatasetVersion(null)
      return
    }

    let cancelled = false
    setDatasetLoading(true)
    setDatasetError(null)

    fetch(`/api/catalog/datasets/${encodeURIComponent(datasetId)}`)
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load dataset (${res.status})`)
        }
        return (await res.json()) as DatasetDetailResponse
      })
      .then((data) => {
        if (cancelled) return
        setDataset(data)
      })
      .catch((err) => {
        if (cancelled) return
        setDataset(null)
        setDatasetError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (cancelled) return
        setDatasetLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [datasetId])

  useEffect(() => {
    if (!datasetId) return
    const normalized = datasetVersion?.trim() || null
    if (normalized) {
      setSelectedDatasetVersion((prev) => (prev === normalized ? prev : normalized))
    }
  }, [datasetId, datasetVersion])

  useEffect(() => {
    if (!datasetId) {
      setDatasetResources(null)
      setDatasetResourcesError(null)
      setDatasetResourcesLoading(false)
      return
    }

    let cancelled = false
    setDatasetResourcesLoading(true)
    setDatasetResourcesError(null)
    const requestedVersion =
      selectedDatasetVersion?.trim() || datasetVersion?.trim() || ''
    const resourceUrl = requestedVersion
      ? `/api/catalog/datasets/${encodeURIComponent(datasetId)}/resources?datasetVersion=${encodeURIComponent(requestedVersion)}`
      : `/api/catalog/datasets/${encodeURIComponent(datasetId)}/resources`

    fetch(resourceUrl)
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load dataset resources (${res.status})`)
        }
        return (await res.json()) as DatasetResourceAddresses
      })
      .then((data) => {
        if (cancelled) return
        setDatasetResources(data)
      })
      .catch((err) => {
        if (cancelled) return
        setDatasetResources(null)
        setDatasetResourcesError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (cancelled) return
        setDatasetResourcesLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [datasetId, datasetVersion, selectedDatasetVersion])

  const datasetVersionOptions = useMemo(() => {
    const fromResources = Array.isArray(datasetResources?.versions)
      ? datasetResources.versions
          .filter((entry) => typeof entry?.id === 'string' && entry.id.trim())
          .map((entry) => ({
            id: entry.id.trim(),
            label:
              typeof entry.label === 'string' && entry.label.trim()
                ? entry.label.trim()
                : entry.id.trim(),
            source: entry.source,
            availability: entry.availability,
            recommended: Boolean(entry.recommended),
          }))
      : []
    if (fromResources.length) return fromResources

    const sourceVersion =
      typeof dataset?.source_version === 'string' && dataset.source_version.trim()
        ? dataset.source_version.trim()
        : null
    if (sourceVersion) {
      return [
        {
          id: sourceVersion,
          label: sourceVersion,
          source: 'catalog' as const,
          availability: 'unknown' as const,
          recommended: true,
        },
      ]
    }
    return []
  }, [dataset?.source_version, datasetResources?.versions])

  useEffect(() => {
    if (!datasetId) return
    if (!datasetVersionOptions.length) {
      setSelectedDatasetVersion(null)
      return
    }

    const hasCurrentSelection =
      typeof selectedDatasetVersion === 'string' &&
      datasetVersionOptions.some((option) => option.id === selectedDatasetVersion)
    if (hasCurrentSelection) return

    const preferredFromUrl = datasetVersion?.trim()
    if (
      preferredFromUrl &&
      datasetVersionOptions.some((option) => option.id === preferredFromUrl)
    ) {
      setSelectedDatasetVersion(preferredFromUrl)
      return
    }

    const defaultVersion =
      datasetResources?.default_version?.trim() ||
      datasetVersionOptions.find((option) => option.recommended)?.id ||
      datasetVersionOptions[0]?.id ||
      null
    setSelectedDatasetVersion(defaultVersion)
  }, [
    datasetId,
    datasetResources?.default_version,
    datasetVersion,
    datasetVersionOptions,
    selectedDatasetVersion,
  ])

  useEffect(() => {
    if (!datasetId) return
    if (apiPipelines.length > 0) return

    let cancelled = false
    setPipelinesLoading(true)
    fetch('/api/pipelines')
      .then((res) => res.json())
      .then((data: { pipelines?: ApiPipeline[] }) => {
        if (cancelled) return
        setApiPipelines(data.pipelines || [])
      })
      .catch((err) => {
        console.error('Failed to fetch pipelines:', err)
      })
      .finally(() => {
        if (cancelled) return
        setPipelinesLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [datasetId, apiPipelines.length])

  const datasetModalitySet = useMemo(() => {
    return new Set((dataset?.modalities ?? []).map((mod) => mod.toLowerCase()))
  }, [dataset?.modalities])

  const analysisOptions = useMemo(() => {
    return ANALYSIS_TYPES.map((type) => ({
      ...type,
      supported:
        !datasetId ||
        type.modalities.length === 0 ||
        type.modalities.some((mod) => datasetModalitySet.has(mod.toLowerCase())),
    }))
  }, [datasetId, datasetModalitySet])

  const dynamicWorkflowSchemaProperties = useMemo(() => {
    const propertiesRaw =
      safeRecord(dynamicWorkflowSchema?.schema)?.properties &&
      typeof safeRecord(dynamicWorkflowSchema?.schema)?.properties === 'object'
        ? (safeRecord(dynamicWorkflowSchema?.schema)?.properties as Record<string, unknown>)
        : {}
    const normalized: Record<string, ApiStepParamProperty> = {}
    for (const [key, raw] of Object.entries(propertiesRaw)) {
      normalized[key] = normalizeSchemaProperty(raw)
    }
    return normalized
  }, [dynamicWorkflowSchema?.schema])

  const dynamicWorkflowRequiredKeys = useMemo(() => {
    const requiredRaw = safeRecord(dynamicWorkflowSchema?.schema)?.required
    if (!Array.isArray(requiredRaw)) return []
    return requiredRaw
      .filter((entry): entry is string => typeof entry === 'string')
      .map((entry) => entry.trim())
      .filter(Boolean)
  }, [dynamicWorkflowSchema?.schema])

  const dynamicWorkflowDiscoveredInputs = useMemo(() => {
    const raw = dynamicWorkflowSchema?.discovered_inputs
    if (!Array.isArray(raw)) return []
    const seen = new Set<string>()
    const normalized: string[] = []
    for (const entry of raw) {
      if (typeof entry !== 'string') continue
      const key = entry.trim()
      if (!key || seen.has(key)) continue
      seen.add(key)
      normalized.push(key)
    }
    return normalized
  }, [dynamicWorkflowSchema?.discovered_inputs])

  const dynamicWorkflowDefaultParameters = useMemo(() => {
    const schemaDefaults: Record<string, unknown> = {}
    for (const [key, prop] of Object.entries(dynamicWorkflowSchemaProperties)) {
      if (Object.prototype.hasOwnProperty.call(prop, 'default')) {
        schemaDefaults[key] = prop.default
      }
    }
    const inferredDefaults = safeRecord(dynamicWorkflowSchema?.defaults)?.merged
    const normalizedInferredDefaults =
      inferredDefaults && typeof inferredDefaults === 'object'
        ? (inferredDefaults as Record<string, unknown>)
        : {}
    const catalogDefaults =
      safeRecord(dynamicWorkflow?.params)?.defaults &&
      typeof safeRecord(dynamicWorkflow?.params)?.defaults === 'object'
        ? (safeRecord(dynamicWorkflow?.params)?.defaults as Record<string, unknown>)
        : {}

    return {
      ...normalizedInferredDefaults,
      ...schemaDefaults,
      ...catalogDefaults,
    }
  }, [dynamicWorkflow?.params, dynamicWorkflowSchema?.defaults, dynamicWorkflowSchemaProperties])

  const dynamicWorkflowSteps = useMemo<ApiPipelineStep[]>(() => {
    if (!dynamicWorkflow?.runtime?.steps?.length) return []
    return dynamicWorkflow.runtime.steps.map((step, idx) => {
      const stepParams = safeRecord(step?.params) ?? {}
      const inputKeys = extractWorkflowInputRefs(stepParams)
      const paramNames = inputKeys.length ? inputKeys : dynamicWorkflowDiscoveredInputs
      const required = dynamicWorkflowRequiredKeys.filter((key) => paramNames.includes(key))
      const properties: Record<string, ApiStepParamProperty> = {}

      for (const key of paramNames) {
        const existing = dynamicWorkflowSchemaProperties[key]
        if (existing) {
          properties[key] = { ...existing }
        } else {
          const inferredType = inferPrimitiveType(dynamicWorkflowDefaultParameters[key])
          properties[key] = {
            ...(inferredType ? { type: inferredType } : {}),
            description: `Input parameter ${key}.`,
          }
        }
        if (
          !Object.prototype.hasOwnProperty.call(properties[key], 'default') &&
          Object.prototype.hasOwnProperty.call(dynamicWorkflowDefaultParameters, key)
        ) {
          properties[key].default = dynamicWorkflowDefaultParameters[key]
        }
      }

      return {
        order: idx + 1,
        tool: step.tool,
        description: `${step.tool} step`,
        paramNames,
        paramSchema: paramNames.length
          ? {
              version: dynamicWorkflowSchema?.version,
              required,
              properties,
            }
          : undefined,
      }
    })
  }, [
    dynamicWorkflow?.runtime?.steps,
    dynamicWorkflowDefaultParameters,
    dynamicWorkflowDiscoveredInputs,
    dynamicWorkflowRequiredKeys,
    dynamicWorkflowSchema?.version,
    dynamicWorkflowSchemaProperties,
  ])

  const selectedAnalysisConfig = useMemo(() => {
    // Handle synthetic dynamic_workflow analysis type
    if (selectedAnalysis === 'dynamic_workflow' && dynamicWorkflow) {
      return {
        id: 'dynamic_workflow',
        label: 'Dynamic Workflow',
        description: dynamicWorkflow.description || '',
        modalities: dynamicWorkflow.modalities ?? [],
        pipelines: [{
          id: dynamicWorkflow.id,
          label: dynamicWorkflow.description || dynamicWorkflow.id,
          description: dynamicWorkflow.description || '',
          modalities: dynamicWorkflow.modalities ?? [],
          estRuntime: dynamicWorkflow.est_runtime || 'TBD',
          runConfig: {
            pipelineType: 'preprocessing' as const,
            tool: dynamicWorkflow.runtime?.steps?.[0]?.tool || 'dynamic',
            defaultParameters: dynamicWorkflowDefaultParameters,
          },
        }],
        supported: true,
      }
    }
    return analysisOptions.find((option) => option.id === selectedAnalysis) || null
  }, [analysisOptions, dynamicWorkflow, dynamicWorkflowDefaultParameters, selectedAnalysis])

  const pipelineOptions = useMemo(() => {
    if (!selectedAnalysisConfig) return []

    // Handle dynamic workflow - return single pipeline with steps from workflow
    if (selectedAnalysis === 'dynamic_workflow' && dynamicWorkflow) {
      return [{
        id: dynamicWorkflow.id,
        label: dynamicWorkflow.description || dynamicWorkflow.id,
        description: dynamicWorkflow.description || '',
        modalities: dynamicWorkflow.modalities ?? [],
        estRuntime: dynamicWorkflow.est_runtime || 'TBD',
        runConfig: {
          pipelineType: 'preprocessing' as const,
          tool: dynamicWorkflow.runtime?.steps?.[0]?.tool || 'dynamic',
          defaultParameters: dynamicWorkflowDefaultParameters,
        },
        apiSteps: dynamicWorkflowSteps,
        isDynamic: true,
      }] as (PipelineOption & { apiSteps?: ApiPipelineStep[]; isDynamic?: boolean })[]
    }

    const apiPipelineMap = new Map(apiPipelines.map((p) => [p.id, p]))

    const merged: (PipelineOption & { apiSteps?: ApiPipelineStep[] })[] =
      selectedAnalysisConfig.pipelines
        .filter(
          (pipeline) =>
            !datasetId ||
            pipeline.modalities.length === 0 ||
            pipeline.modalities.some((mod) => datasetModalitySet.has(mod.toLowerCase())),
        )
        .map((pipeline) => {
          const apiPipeline = apiPipelineMap.get(pipeline.id)
          if (!apiPipeline) return pipeline
          return {
            ...pipeline,
            description: apiPipeline.description || pipeline.description,
            apiSteps: apiPipeline.steps,
          }
        })

    return merged
  }, [
    apiPipelines,
    datasetId,
    datasetModalitySet,
    dynamicWorkflow,
    dynamicWorkflowDefaultParameters,
    dynamicWorkflowSteps,
    selectedAnalysis,
    selectedAnalysisConfig,
  ])

  const selectedPipelineConfig = useMemo(() => {
    // First check static pipeline options
    const staticMatch = pipelineOptions.find((pipeline) => pipeline.id === selectedPipeline)
    if (staticMatch) return staticMatch
    
    // If dynamic workflow is loaded and matches, create a synthetic config
    if (dynamicWorkflow && selectedPipeline === dynamicWorkflow.id) {
      return {
        id: dynamicWorkflow.id,
        label: dynamicWorkflow.description || dynamicWorkflow.id,
        description: dynamicWorkflow.description || '',
        modalities: dynamicWorkflow.modalities ?? [],
        estRuntime: dynamicWorkflow.est_runtime || 'TBD',
        runConfig: {
          pipelineType: 'preprocessing' as const,
          tool: dynamicWorkflow.runtime?.steps?.[0]?.tool || 'dynamic',
          defaultParameters: dynamicWorkflowDefaultParameters,
        },
        apiSteps: dynamicWorkflowSteps,
        isDynamic: true,
      } as PipelineOption & { apiSteps?: ApiPipelineStep[]; isDynamic?: boolean }
    }
    
    return null
  }, [
    dynamicWorkflow,
    dynamicWorkflowDefaultParameters,
    dynamicWorkflowSteps,
    pipelineOptions,
    selectedPipeline,
  ])

  const pipelineStepOrders = useMemo(() => {
    const steps =
      (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] })?.apiSteps ?? []
    return steps.map((step, idx) => step.order || idx + 1)
  }, [selectedPipelineConfig])

  const dagStatusByOrder = useDagStepStatusByOrder({
    jobId: dagJobId,
    stepOrders: pipelineStepOrders,
    enabled: stepsView === 'dag' && Boolean(dagJobId),
  })

  const toolsUsed = useMemo(() => {
    const steps = (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] })?.apiSteps ?? []
    const unique = new Set<string>()
    for (const step of steps) {
      const tool = typeof step?.tool === 'string' ? step.tool.trim() : ''
      if (tool) unique.add(tool)
    }
    return Array.from(unique)
  }, [selectedPipelineConfig])

  // Check if a pipeline ID exists in the static ANALYSIS_TYPES
  const isStaticPipelineId = useMemo(() => {
    const staticIds = new Set(
      ANALYSIS_TYPES.flatMap((analysis) => analysis.pipelines.map((p) => p.id))
    )
    return (id: string) => staticIds.has(id)
  }, [])

  // Fetch dynamic workflow from API when initialPipelineId is not in static types
  // Use a ref to track the current fetch to handle race conditions properly
  const fetchIdRef = useRef<string | null>(null)
  
  useEffect(() => {
    if (!initialPipelineId) return
    if (isStaticPipelineId(initialPipelineId)) return
    // Already have this workflow loaded
    if (dynamicWorkflow?.id === initialPipelineId) return

    // Track this fetch
    const fetchId = initialPipelineId
    fetchIdRef.current = fetchId
    
    setDynamicWorkflowLoading(true)
    setDynamicWorkflowError(null)
    // Clear any static selection to avoid showing static pipelines during loading
    setSelectedAnalysis(null)
    setSelectedPipeline(null)

    brainResearcherAPI.fetchWorkflowById(initialPipelineId)
      .then((workflow) => {
        // Only apply if this is still the current fetch
        if (fetchIdRef.current !== fetchId) return
        setDynamicWorkflow(workflow)
        // Set the pipeline ID directly for dynamic workflows
        setSelectedPipeline(workflow.id)
        // Use a synthetic analysis type for dynamic workflows
        setSelectedAnalysis('dynamic_workflow')
        setDynamicWorkflowLoading(false)
      })
      .catch((err) => {
        // Only apply if this is still the current fetch
        if (fetchIdRef.current !== fetchId) return
        console.error('Failed to fetch dynamic workflow:', err)
        setDynamicWorkflowError(err instanceof Error ? err.message : String(err))
        setDynamicWorkflowLoading(false)
      })
    // Note: Removed dynamicWorkflowLoading from deps to avoid race condition
    // where the effect re-runs on loading state change and cancels itself
  }, [initialPipelineId, isStaticPipelineId, dynamicWorkflow?.id])

  useEffect(() => {
    if (!dynamicWorkflow?.id) {
      setDynamicWorkflowSchema(null)
      setDynamicWorkflowSchemaLoading(false)
      setDynamicWorkflowSchemaError(null)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    setDynamicWorkflowSchemaLoading(true)
    setDynamicWorkflowSchemaError(null)

    fetch(`/api/workflows/${encodeURIComponent(dynamicWorkflow.id)}/schema`, {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load workflow schema (${res.status})`)
        }
        return (await res.json()) as unknown
      })
      .then((payload) => {
        if (cancelled) return
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
          setDynamicWorkflowSchema(null)
          return
        }
        setDynamicWorkflowSchema(payload as DynamicWorkflowSchemaResponse)
      })
      .catch((error) => {
        if (cancelled) return
        setDynamicWorkflowSchema(null)
        setDynamicWorkflowSchemaError(error instanceof Error ? error.message : String(error))
      })
      .finally(() => {
        if (cancelled) return
        setDynamicWorkflowSchemaLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [dynamicWorkflow?.id])

  useEffect(() => {
    if (initialPipelineId) return
    setDynamicWorkflow(null)
    setDynamicWorkflowLoading(false)
    setDynamicWorkflowError(null)
    setDynamicWorkflowSchema(null)
    setDynamicWorkflowSchemaLoading(false)
    setDynamicWorkflowSchemaError(null)
    setSelectedAnalysis((prev) => (prev === 'dynamic_workflow' ? null : prev))
    setSelectedPipeline((prev) => {
      if (!prev) return prev
      if (!isStaticPipelineId(prev)) return null
      return prev
    })
  }, [initialPipelineId, isStaticPipelineId])

  // Handle static pipeline matching (existing logic)
  useEffect(() => {
    if (!initialPipelineId) return
    if (selectedPipeline) return
    // Skip if this is a dynamic workflow
    if (!isStaticPipelineId(initialPipelineId)) return
    const match = pipelineOptions.find((p) => p.id === initialPipelineId)
    if (!match) return
    setSelectedPipeline(match.id)
  }, [initialPipelineId, isStaticPipelineId, pipelineOptions, selectedPipeline])

  useEffect(() => {
    if (!initialPipelineId) return
    if (selectedAnalysis) return
    // Skip if this is a dynamic workflow
    if (!isStaticPipelineId(initialPipelineId)) return
    const match = analysisOptions.find((analysis) =>
      analysis.pipelines.some((p) => p.id === initialPipelineId),
    )
    if (!match) return
    setSelectedAnalysis(match.id)
  }, [analysisOptions, initialPipelineId, isStaticPipelineId, selectedAnalysis])

  useEffect(() => {
    setParameterOverrides({})
    setParameterDraft({})
    closeParameterDialog()
  }, [closeParameterDialog, selectedPipeline])

  useEffect(() => {
    if (!pendingRestoreRef.current) return
    const restored = pendingRestoreRef.current
    if (restored.pipeline_id && restored.pipeline_id === selectedPipeline) {
      const overrides = restored.parameter_overrides
      if (overrides && typeof overrides === 'object' && !Array.isArray(overrides)) {
        setParameterOverrides(overrides)
      }
      pendingRestoreRef.current = { ...restored, parameter_overrides: undefined }
    }
  }, [selectedPipeline])

  useEffect(() => {
    if (!selectedPipeline) return
    if (leavingStudioRef.current) return
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/studio')) return
    const liveParams =
      typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search)
        : searchParams
    const hasRunContext =
      Boolean(dagJobId) ||
      Boolean(liveParams.get('analysisId')) ||
      Boolean(liveParams.get('analysis')) ||
      Boolean(liveParams.get('runId')) ||
      Boolean(liveParams.get('jobId'))
    if (hasRunContext) return
    const current = new URLSearchParams(searchParams.toString())
    if (current.get('pipeline') === selectedPipeline && current.get('tab') === 'plan') return
    current.set('pipeline', selectedPipeline)
    current.set('tab', 'plan')
    router.replace(`/studio?${current.toString()}`, { scroll: false })
  }, [dagJobId, router, searchParams, selectedPipeline])

  useEffect(() => {
    if (leavingStudioRef.current) return
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/studio')) return
    const liveParams =
      typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search)
        : searchParams
    const hasRunContext =
      Boolean(dagJobId) ||
      Boolean(liveParams.get('analysisId')) ||
      Boolean(liveParams.get('analysis')) ||
      Boolean(liveParams.get('runId')) ||
      Boolean(liveParams.get('jobId'))
    if (hasRunContext) return
    const current = new URLSearchParams(searchParams.toString())
    const normalizedVersion =
      typeof selectedDatasetVersion === 'string' && selectedDatasetVersion.trim()
        ? selectedDatasetVersion.trim()
        : null
    const currentVersion = current.get('datasetVersion') || current.get('dataset_version')

    if (!normalizedVersion && !currentVersion) return
    if (normalizedVersion && currentVersion === normalizedVersion) return

    if (normalizedVersion) {
      current.set('datasetVersion', normalizedVersion)
      current.delete('dataset_version')
    } else {
      current.delete('datasetVersion')
      current.delete('dataset_version')
    }
    current.set('tab', 'plan')
    router.replace(`/studio?${current.toString()}`, { scroll: false })
  }, [dagJobId, router, searchParams, selectedDatasetVersion])

  const hasPersistableDraft = useMemo(() => {
    if (intent.trim().length > 0) return true
    if (datasetId) return true
    if (selectedAnalysis) return true
    if (selectedPipeline) return true
    if (selectedTask) return true
    if (selectedDatasetVersion) return true
    if (conceptIds.length > 0) return true
    if (Object.keys(parameterOverrides).length > 0) return true
    if (maxModels !== 3) return true
    return false
  }, [
    conceptIds.length,
    datasetId,
    intent,
    maxModels,
    parameterOverrides,
    selectedAnalysis,
    selectedDatasetVersion,
    selectedPipeline,
    selectedTask,
  ])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!autosaveReady) return
    if (!hasPersistableDraft) return

    const timer = window.setTimeout(() => {
      persistPlanDraftNow()
    }, 500)

    return () => window.clearTimeout(timer)
  }, [
    autosaveReady,
    hasPersistableDraft,
    persistPlanDraftNow,
  ])

  const multiverseNeedsTask = Boolean(
    selectedAnalysis === 'multiverse_glm' && datasetId && !datasetLoading,
  )

  const checkParameters = useMemo(() => {
    const extra: Record<string, unknown> = { ...parameterOverrides }
    if (selectedAnalysis === 'multiverse_glm') {
      if (selectedTask) extra.task = selectedTask
      extra.max_models = maxModels
    }
    return extra
  }, [maxModels, parameterOverrides, selectedAnalysis, selectedTask])

  const checkPayloadKey = useMemo(() => {
    const payload = {
      dataset_id: datasetId ?? null,
      dataset_version: selectedDatasetVersion ?? null,
      analysis_id: selectedAnalysis ?? null,
      pipeline_id: selectedPipeline ?? null,
      parameters: checkParameters,
      auth_status: authStatus,
      credits_rev: creditsRevision,
      checks_refresh_token: checksRefreshToken,
    }
    try {
      return JSON.stringify(payload)
    } catch {
      return `${datasetId ?? ''}:${selectedAnalysis ?? ''}:${selectedPipeline ?? ''}:${authStatus}:${creditsRevision ?? ''}:${checksRefreshToken}`
    }
  }, [
    authStatus,
    checkParameters,
    checksRefreshToken,
    creditsRevision,
    datasetId,
    selectedAnalysis,
    selectedDatasetVersion,
    selectedPipeline,
  ])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const storageKey = 'br:credits:updated_at'

    const refresh = () => {
      try {
        const next = window.localStorage?.getItem(storageKey) ?? null
        setCreditsRevision(next)
      } catch {
        setCreditsRevision(null)
      }
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== storageKey) return
      refresh()
    }

    const handleVisibility = () => {
      if (document.hidden) return
      refresh()
    }

    window.addEventListener('storage', handleStorage)
    window.addEventListener(CREDITS_UPDATED_EVENT, refresh)
    document.addEventListener('visibilitychange', handleVisibility)
    refresh()

    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener(CREDITS_UPDATED_EVENT, refresh)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  const defaultIntent = useMemo(() => {
    if (selectedAnalysisConfig && selectedPipelineConfig) {
      return `${selectedAnalysisConfig.label} · ${selectedPipelineConfig.label}`
    }
    if (selectedPipelineConfig) return selectedPipelineConfig.label
    if (selectedAnalysisConfig) return selectedAnalysisConfig.label
    return ''
  }, [selectedAnalysisConfig, selectedPipelineConfig])

  useEffect(() => {
    if (!autosaveReady) return
    if (intentTouched) return
    setIntent(defaultIntent)
  }, [autosaveReady, defaultIntent, intentTouched])

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    setChecksError(null)

    const shouldSkip =
      !datasetId && !selectedAnalysis && !selectedPipeline && Object.keys(checkParameters).length === 0
    if (shouldSkip) {
      setPlanChecks(null)
      setEstimate(null)
      setLaunchDecision(null)
      setEffectiveConfig(null)
      setHandoffPack(null)
      setEnvironmentGuidance(null)
      setExecutionStatus(null)
      setChecksLoading(false)
      return () => controller.abort()
    }

    setChecksLoading(true)
    setLaunchDecision(null)
    setExecutionStatus(null)

    const timer = setTimeout(() => {
      fetch('/api/plan/checks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          dataset_id: datasetId,
          dataset_version: selectedDatasetVersion,
          analysis_id: selectedAnalysis,
          pipeline_id: selectedPipeline,
          parameters: checkParameters,
        }),
        cache: 'no-store',
        signal: controller.signal,
      })
        .then(async (res) => {
          const text = await res.text().catch(() => '')
          let json: any = null
          try {
            json = text ? JSON.parse(text) : null
          } catch {
            json = null
          }

          if (!res.ok) {
            const detail = json?.detail || json?.error || text || `HTTP ${res.status}`
            throw new Error(detail)
          }

          return json as PlanChecksResponse
        })
        .then((data) => {
          if (cancelled) return
          setPlanChecks(Array.isArray(data?.checks) ? data.checks : [])
          setEstimate(data?.estimate ?? null)
          setLaunchDecision(safeRecord(data?.launch_decision) ? data.launch_decision ?? null : null)
          setEffectiveConfig(data?.effective_config ?? null)
          setHandoffPack(data?.handoff_pack ?? null)
          setEnvironmentGuidance(data?.guidance ?? null)
          setExecutionStatus(
            safeRecord(data?.execution_status) ? data.execution_status ?? null : null,
          )
          setChecksError(null)
        })
        .catch((err) => {
          if (cancelled) return
          setPlanChecks(null)
          setEstimate(null)
          setLaunchDecision(null)
          setEffectiveConfig(null)
          setHandoffPack(null)
          setEnvironmentGuidance(null)
          setExecutionStatus(null)
          setChecksError(err instanceof Error ? err.message : String(err))
        })
        .finally(() => {
          if (cancelled) return
          setChecksLoading(false)
        })
    }, 500)

    return () => {
      cancelled = true
      clearTimeout(timer)
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkPayloadKey, datasetId, selectedAnalysis, selectedDatasetVersion, selectedPipeline, checkParameters])

  const checks = useMemo((): PlanCheck[] => {
    if (planChecks) return planChecks

    const datasetStatus: PlanCheckStatus = !datasetId
      ? 'blocked'
      : datasetLoading
        ? 'pending'
        : datasetError
          ? 'blocked'
          : 'passed'

    const workflowStatus: PlanCheckStatus = selectedPipeline ? 'passed' : 'blocked'
    const inputsStatus: PlanCheckStatus = selectedAnalysis ? 'passed' : 'blocked'

    const fallback: PlanCheck[] = [
      { id: 'data_validated', label: 'Data validated', status: datasetStatus },
      { id: 'workflow_compatible', label: 'Workflow compatible', status: workflowStatus },
      { id: 'inputs_provided', label: 'All inputs provided', status: inputsStatus },
      {
        id: 'credits_sufficient',
        label: 'Credits sufficient',
        status: 'warning',
        detail: 'Credits check unavailable; retrying in background.',
      },
    ]

    if (multiverseNeedsTask && !selectedTask) {
      fallback.push({
        id: 'task',
        label: 'Task selected',
        status: 'blocked',
        detail: 'Select a task for multiverse analysis.',
      })
    }

    if (checksError) {
      fallback.push({
        id: 'verification_available',
        label: 'Verification service available',
        status: 'blocked',
        detail:
          'Verification API is unavailable. Run is blocked until checks recover and pass.',
      })
    }

    return fallback
  }, [
    checksError,
    datasetError,
    datasetId,
    datasetLoading,
    multiverseNeedsTask,
    planChecks,
    selectedAnalysis,
    selectedPipeline,
    selectedTask,
  ])

  const hasPendingChecks = checksLoading || checks.some((check) => check.status === 'pending')
  const hasBlockedChecks = checks.some((check) => check.status === 'blocked')
  const hasWarningChecks = checks.some((check) => check.status === 'warning')
  const authBlocked = checks.some((check) => check.id === 'authenticated' && check.status === 'blocked')
  const verificationUnavailable = Boolean(checksError)
  const launchDecisionBlocked = launchDecision?.can_launch === false
  const visibleChecks = useMemo(
    () => checks.filter((check) => check.id !== 'credits_sufficient'),
    [checks],
  )
  const hasVisibleBlockedChecks = visibleChecks.some((check) => check.status === 'blocked')
  const hasVisibleWarningChecks = visibleChecks.some((check) => check.status === 'warning')
  const selectedWorkflowRecipeTargets = useMemo(
    () =>
      selectedAnalysis === 'dynamic_workflow' && dynamicWorkflow?.id === selectedPipeline
        ? dynamicWorkflow.supported_recipe_targets ?? []
        : environmentGuidance?.supported_recipe_targets ?? [],
    [
      dynamicWorkflow?.id,
      dynamicWorkflow?.supported_recipe_targets,
      environmentGuidance?.supported_recipe_targets,
      selectedAnalysis,
      selectedPipeline,
    ],
  )
  const selectedWorkflowRecipeLaunchable =
    selectedAnalysis === 'dynamic_workflow' && dynamicWorkflow?.id === selectedPipeline
      ? typeof dynamicWorkflow.execution_recipe_available === 'boolean'
        ? dynamicWorkflow.execution_recipe_available
        : selectedWorkflowRecipeTargets.length > 0
      : environmentGuidance?.supported_recipe_targets
        ? selectedWorkflowRecipeTargets.length > 0
        : null
  const canRun =
    Boolean(datasetId && selectedAnalysisConfig && selectedPipelineConfig) &&
    !verificationUnavailable &&
    !launchDecisionBlocked &&
    !hasPendingChecks &&
    !hasBlockedChecks
  const canOpenFullRunHandoff = Boolean(selectedAnalysisConfig && selectedPipelineConfig)
  const launchDecisionLabel =
    launchDecision?.can_launch === false
      ? launchDecision.status === 'handoff_only'
        ? 'Handoff only'
        : launchDecision.status === 'manual_admin_only'
          ? 'Manual/admin only'
          : 'Launch blocked'
      : launchDecision?.status === 'runnable_with_warning'
        ? 'Launch allowed with warning'
        : launchDecision?.status === 'runnable'
          ? 'Launch ready'
          : null
  const executionStatusVisible = Boolean(
    executionStatus?.message &&
      (executionStatus.recommended_backend === 'local_backend' ||
        executionStatus.recommended_backend === 'manual_admin'),
  )

  const projectionStatus: StudioPlanProjectionStatus = isSubmitting
    ? 'running'
    : hasVisibleBlockedChecks || verificationUnavailable || launchDecisionBlocked
      ? 'blocked'
      : hasVisibleWarningChecks
        ? 'warning'
        : 'ready'

  const projectionIntentSummary = useMemo(() => {
    const trimmedIntent = intent.trim()
    if (trimmedIntent) return trimmedIntent
    if (defaultIntent) return defaultIntent
    return 'Describe your goal in chat and the agent will build a runnable analysis plan.'
  }, [defaultIntent, intent])

  const projectionProvenance = useMemo(() => {
    const hasAdvancedEdits =
      intentTouched ||
      Boolean(selectedDatasetVersion) ||
      Boolean(selectedTask) ||
      conceptIds.length > 0 ||
      Object.keys(parameterOverrides).length > 0 ||
      maxModels !== 3

    return hasAdvancedEdits
      ? 'Current draft reflects chat context plus advanced editor changes.'
      : 'Current draft was proposed from the active chat context.'
  }, [
    conceptIds.length,
    intentTouched,
    maxModels,
    parameterOverrides,
    selectedDatasetVersion,
    selectedTask,
  ])

  const projectionSummaryRows = useMemo((): StudioPlanProjectionRow[] => {
    const datasetValue = datasetId
      ? dataset?.name
        ? `${dataset.name} (${datasetId})${selectedDatasetVersion ? ` · ${selectedDatasetVersion}` : ''}`
        : `${datasetId}${selectedDatasetVersion ? ` · ${selectedDatasetVersion}` : ''}`
      : 'No dataset selected'
    const datasetDetail = datasetId
      ? datasetLoading
        ? 'Loading dataset metadata…'
        : datasetError
          ? datasetError
          : [
              dataset?.modalities?.length ? dataset.modalities.join(', ') : null,
              typeof dataset?.subjects_count === 'number' ? `${dataset.subjects_count} subjects` : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'Dataset metadata ready'
      : 'Ask the agent to choose a dataset, or open Advanced to pick one manually.'

    const workflowValue = selectedPipelineConfig?.label || selectedPipeline || 'No workflow selected'
    const workflowDetailParts = [
      selectedAnalysisConfig?.label || null,
      selectedPipelineConfig?.description || null,
      selectedPipelineConfig?.estRuntime ? `est. ${selectedPipelineConfig.estRuntime}` : null,
    ].filter(Boolean)
    const workflowDetail =
      workflowDetailParts.join(' · ') ||
      'The agent has not committed a workflow yet. Continue in chat or use Advanced.'

    const selectedApiSteps =
      (selectedPipelineConfig as (PipelineOption & { apiSteps?: ApiPipelineStep[] }) | null)?.apiSteps ?? []
    const executionDetailParts: string[] = []
    if (selectedApiSteps.length) {
      executionDetailParts.push(`${selectedApiSteps.length} steps`)
    }
    if (selectedTask) {
      executionDetailParts.push(`task=${selectedTask}`)
    }
    const overrideCount = Object.keys(parameterOverrides).length
    if (overrideCount) {
      executionDetailParts.push(`${overrideCount} override${overrideCount === 1 ? '' : 's'}`)
    }
    if (conceptIds.length) {
      executionDetailParts.push(`${conceptIds.length} concept${conceptIds.length === 1 ? '' : 's'}`)
    }

    return [
      {
        id: 'dataset',
        label: 'Dataset',
        value: datasetValue,
        detail: datasetDetail,
        status: datasetId ? (datasetError ? 'blocked' : datasetLoading ? 'warning' : 'passed') : 'blocked',
      },
      {
        id: 'workflow',
        label: 'Workflow',
        value: workflowValue,
        detail: workflowDetail,
        status: selectedPipelineConfig ? 'passed' : 'blocked',
      },
      {
        id: 'execution-shape',
        label: 'Execution shape',
        value: executionDetailParts.length ? executionDetailParts.join(' · ') : 'No execution details yet',
        detail:
          executionDetailParts.length > 0
            ? 'Advanced editor still exposes the full parameter and step controls.'
            : 'Once the agent selects a workflow, step shape and parameters will appear here.',
        status:
          selectedAnalysis === 'multiverse_glm' && !selectedTask
            ? 'blocked'
            : selectedPipelineConfig
              ? 'info'
              : 'blocked',
      },
    ]
  }, [
    conceptIds.length,
    dataset,
    datasetError,
    datasetId,
    datasetLoading,
    parameterOverrides,
    selectedAnalysis,
    selectedAnalysisConfig,
    selectedDatasetVersion,
    selectedPipeline,
    selectedPipelineConfig,
    selectedTask,
  ])

  const guidanceCardVisible = useMemo(() => {
    if (!environmentGuidance) return false
    const kind = environmentGuidance.kind?.toLowerCase() ?? ''
    const runtimeTarget = environmentGuidance.runtime_target?.toLowerCase() ?? ''
    return kind.includes('neurodesk') || runtimeTarget === 'neurodesk'
  }, [environmentGuidance])

  const projectionAlerts = useMemo((): StudioPlanProjectionAlert[] => {
    return visibleChecks
      .filter((check) => check.status === 'blocked' || check.status === 'warning')
      .map((check) => ({
        id: check.id,
        severity: check.status === 'blocked' ? 'blocked' : 'warning',
        label: check.label,
        message:
          check.detail ||
          (check.status === 'blocked'
            ? 'This issue blocks execution until it is resolved.'
            : 'This issue should be reviewed before execution.'),
      }))
  }, [visibleChecks])

  useEffect(() => {
    setEffectiveCopyStatus('idle')
  }, [effectiveConfig, handoffPack])

  const effectiveConfigPayload = useMemo(() => {
    if (!effectiveConfig) return null
    const origins = Object.fromEntries(
      (effectiveConfig.parameters ?? []).map((entry) => [entry.key, entry.origin]),
    )
    return {
      analysis_id: effectiveConfig.analysis_id,
      pipeline_id: effectiveConfig.pipeline_id,
      pipeline_label: effectiveConfig.pipeline_label,
      pipeline_type: effectiveConfig.pipeline_type,
      tool_id: effectiveConfig.tool_id,
      dataset_id: effectiveConfig.dataset_id,
      dataset_version: effectiveConfig.dataset_version,
      parameters: effectiveConfig.parameter_values,
      origins,
      ...(handoffPack ? { handoff_pack: handoffPack } : {}),
    }
  }, [effectiveConfig, handoffPack])

  const effectiveConfigJson = useMemo(() => {
    if (!effectiveConfigPayload) return ''
    try {
      return JSON.stringify(effectiveConfigPayload, null, 2)
    } catch {
      return ''
    }
  }, [effectiveConfigPayload])

  const copyEffectiveConfig = useCallback(async () => {
    if (!effectiveConfigJson) return
    try {
      await navigator.clipboard.writeText(effectiveConfigJson)
      setEffectiveCopyStatus('copied')
    } catch {
      setEffectiveCopyStatus('error')
    }
  }, [effectiveConfigJson])

  const exportEffectiveConfig = useCallback(() => {
    if (!effectiveConfigJson) return
    const blob = new Blob([effectiveConfigJson], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const pipelineTag =
      (effectiveConfig?.pipeline_id || selectedPipeline || 'pipeline').replace(/[^a-zA-Z0-9._-]+/g, '_')
    link.href = url
    link.download = `effective-run-config-${pipelineTag}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }, [effectiveConfig, effectiveConfigJson, selectedPipeline])

  const showEmptyPlanCard =
    !datasetId &&
    conceptIds.length === 0 &&
    !selectedAnalysis &&
    !selectedPipeline &&
    !intentTouched

  useEffect(() => {
    onEmptyPlanChange?.(showEmptyPlanCard)
  }, [onEmptyPlanChange, showEmptyPlanCard])

  const openDatasetPicker = () => {
    leavingStudioRef.current = true
    persistCurrentIntentDraftNow()
    const current = new URLSearchParams(searchParams.toString())
    if (selectedPipelineConfig) {
      current.set('pipeline', selectedPipelineConfig.id)
      current.delete('template')
    }
    if (selectedDatasetVersion) {
      current.set('datasetVersion', selectedDatasetVersion)
    } else {
      current.delete('datasetVersion')
      current.delete('dataset_version')
    }
    const target = buildDatasetsPickerHref(buildStudioPlanHref(current))
    if (typeof window !== 'undefined') {
      window.location.assign(target)
      return
    }
    router.push(target)
  }

  const openSignIn = useCallback(() => {
    leavingStudioRef.current = true
    persistCurrentIntentDraftNow()
    const current = new URLSearchParams(searchParams.toString())
    const callbackUrl = buildStudioPlanHref(current)
    router.push(`/auth/login?callbackUrl=${encodeURIComponent(callbackUrl)}`)
  }, [persistCurrentIntentDraftNow, router, searchParams])

  const scrollToSection = (section: HTMLDivElement | null) => {
    if (!section) return
    section.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const openLibraryDrawer = () => {
    const current = new URLSearchParams(searchParams.toString())
    current.set('tab', 'plan')
    current.set('openLibrary', '1')
    const suffix = current.toString()
    router.push(suffix ? `/studio?${suffix}` : '/studio?tab=plan&openLibrary=1')
  }

  const buildAskAgentPromptForEmptyPlan = () => {
    const lines: string[] = []
    lines.push('My plan is empty. Help me build a reproducible analysis plan.')
    lines.push('Recommend an official workflow/template and ask any clarifying questions you need.')
    lines.push('If a dataset is required, suggest a few good starting datasets and how to choose one.')
    return lines.join('\n')
  }

  const buildAskAgentPromptForCheck = useCallback((check: PlanCheck) => {
    const datasetBase = dataset?.name ? `${dataset.name} (${dataset.id})` : datasetId || 'none'
    const datasetLabel = selectedDatasetVersion
      ? `${datasetBase} @ ${selectedDatasetVersion}`
      : datasetBase
    const analysisLabel = selectedAnalysisConfig?.label || selectedAnalysis || 'none'
    const pipelineLabel = selectedPipelineConfig?.label || selectedPipeline || 'none'
    const selectedApiSteps =
      (selectedPipelineConfig as (PipelineOption & { apiSteps?: ApiPipelineStep[] }) | null)?.apiSteps ?? []
    const stepTools = Array.from(
      new Set(
        selectedApiSteps
          .map((step) => (typeof step.tool === 'string' ? step.tool.trim() : ''))
          .filter(Boolean),
      ),
    )
    const lines: string[] = []
    lines.push('Help me fix this blocked/warning plan check.')
    if (intent.trim()) lines.push(`Intent: ${intent.trim()}`)
    lines.push(`Dataset: ${datasetLabel}`)
    lines.push(`Analysis: ${analysisLabel}`)
    lines.push(`Pipeline: ${pipelineLabel}`)
    if (selectedAnalysis === 'dynamic_workflow' && dynamicWorkflow) {
      lines.push(`Workflow ID: ${dynamicWorkflow.id}`)
      if (stepTools.length) lines.push(`Workflow step tools: ${stepTools.join(', ')}`)
      lines.push('Local workflow source: workflow_catalog.')
      lines.push('Use local workflow/tool IDs only. Do not suggest external platforms.')
    }
    lines.push(`Check: ${check.label} (${check.status})`)
    if (check.detail) lines.push(`Detail: ${check.detail}`)
    lines.push('Suggest concrete changes (pipeline/version/parameters) to make the plan runnable.')
    return lines.join('\n')
  }, [
    dataset,
    datasetId,
    dynamicWorkflow,
    intent,
    selectedAnalysis,
    selectedAnalysisConfig,
    selectedDatasetVersion,
    selectedPipeline,
    selectedPipelineConfig,
  ])

  const handleAskAgentToRevisePlan = useCallback(() => {
    if (!onAskAgent) return
    const topIssue =
      visibleChecks.find((check) => check.status === 'blocked') ??
      visibleChecks.find((check) => check.status === 'warning')
    if (topIssue) {
      onAskAgent(buildAskAgentPromptForCheck(topIssue))
      return
    }
    const datasetBase = dataset?.name ? `${dataset.name} (${dataset.id})` : datasetId || 'none'
    const datasetLabel = selectedDatasetVersion ? `${datasetBase} @ ${selectedDatasetVersion}` : datasetBase
    const lines: string[] = []
    lines.push('Review my current plan and suggest the next best revision.')
    if (intent.trim()) lines.push(`Intent: ${intent.trim()}`)
    lines.push(`Dataset: ${datasetLabel}`)
    lines.push(`Analysis: ${selectedAnalysisConfig?.label || selectedAnalysis || 'none'}`)
    lines.push(`Pipeline: ${selectedPipelineConfig?.label || selectedPipeline || 'none'}`)
    onAskAgent(lines.join('\n'))
  }, [
    buildAskAgentPromptForCheck,
    dataset,
    datasetId,
    intent,
    onAskAgent,
    selectedAnalysis,
    selectedAnalysisConfig,
    selectedDatasetVersion,
    selectedPipeline,
    selectedPipelineConfig,
    visibleChecks,
  ])

  const pipelineDefaultParameters = useMemo(
    () => selectedPipelineConfig?.runConfig?.defaultParameters ?? {},
    [selectedPipelineConfig],
  )

  const buildStudioHandoffPayload = useCallback((): HandoffTemplatePayload | null => {
    if (!selectedAnalysisConfig || !selectedPipelineConfig) return null

    const recipeLookup = safeRecord(handoffPack?.recipe_lookup)
    const execution = safeRecord(handoffPack?.execution)
    const recipeParams = safeRecord(recipeLookup?.params)
    const effectiveParams = safeRecord(effectiveConfig?.parameter_values)
    const params: Record<string, unknown> = {
      ...pipelineDefaultParameters,
      ...checkParameters,
      ...(effectiveParams ?? {}),
      ...(recipeParams ?? {}),
    }

    if (datasetId && !normalizeText(params.dataset_id)) {
      params.dataset_id = datasetId
    }
    if (selectedTask && !normalizeText(params.task)) {
      params.task = selectedTask
    }

    const aliasWorkflowId =
      legacyPipelineWorkflowAlias(selectedPipelineConfig.id) ||
      legacyPipelineWorkflowAlias(selectedPipeline)
    const workflowId =
      normalizeText(recipeLookup?.tool_id) ||
      normalizeText(handoffPack?.workflow_id) ||
      normalizeText(handoffPack?.chosen_tool) ||
      normalizeText(environmentGuidance?.workflow_id) ||
      aliasWorkflowId ||
      (selectedPipeline?.startsWith('workflow_') ? selectedPipeline : null) ||
      normalizeText(effectiveConfig?.tool_id) ||
      normalizeText(selectedPipelineConfig.runConfig.tool) ||
      selectedPipelineConfig.id
    const supportedTargets = uniqueTextValues([
      recipeLookup?.supported_targets,
      recipeLookup?.supported_recipe_targets,
      execution?.supported_recipe_targets,
      environmentGuidance?.supported_recipe_targets,
      dynamicWorkflow?.supported_recipe_targets,
      selectedWorkflowRecipeTargets,
    ])
    const targetRuntime =
      normalizeText(recipeLookup?.target_runtime) ||
      normalizeText(execution?.target_runtime) ||
      normalizeText(environmentGuidance?.runtime_target) ||
      normalizeText(dynamicWorkflow?.primary_target)
    const unresolvedInputs: string[] = []
    if (!normalizeText(params.dataset_id)) unresolvedInputs.push('dataset_id')
    if (multiverseNeedsTask && !selectedTask) unresolvedInputs.push('task')

    const notes = uniqueTextValues([
      launchDecision?.reason
        ? `Hosted launch status: ${launchDecision.reason}`
        : launchDecisionBlocked
          ? 'Hosted launch is blocked for this plan.'
          : null,
      executionStatus?.message ? `Runtime guidance: ${executionStatus.message}` : null,
      verificationUnavailable && checksError
        ? `Studio verification unavailable: ${checksError}`
        : null,
      ...visibleChecks
        .filter((check) => check.status === 'blocked' || check.status === 'warning')
        .map((check) => `${check.label}: ${check.detail || check.status}`),
      'Do not assume hosted execution has run; use MCP to fetch the recipe, verify runtime requirements, then execute in the selected IDE or cluster.',
    ])

    return {
      kind: 'template',
      title: 'Hand off Studio plan',
      workflowId,
      workflowLabel: `${selectedAnalysisConfig.label} · ${selectedPipelineConfig.label}`,
      datasetId: datasetId ?? null,
      datasetVersion: selectedDatasetVersion ?? null,
      targetRuntime,
      supportedTargets: supportedTargets.length ? supportedTargets : null,
      params,
      unresolvedInputs,
      notes,
    }
  }, [
    checkParameters,
    checksError,
    datasetId,
    dynamicWorkflow?.primary_target,
    dynamicWorkflow?.supported_recipe_targets,
    effectiveConfig,
    environmentGuidance?.runtime_target,
    environmentGuidance?.supported_recipe_targets,
    environmentGuidance?.workflow_id,
    executionStatus?.message,
    handoffPack,
    launchDecision?.reason,
    launchDecisionBlocked,
    multiverseNeedsTask,
    pipelineDefaultParameters,
    selectedAnalysisConfig,
    selectedDatasetVersion,
    selectedPipeline,
    selectedPipelineConfig,
    selectedTask,
    selectedWorkflowRecipeTargets,
    verificationUnavailable,
    visibleChecks,
  ])

  const openPipelineParameters = () => {
    const fallbackParamNames = Array.from(
      new Set(
        (
          (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] })?.apiSteps ?? []
        ).flatMap((step) =>
          Array.isArray(step?.paramNames)
            ? step.paramNames.map((name) => (typeof name === 'string' ? name.trim() : '')).filter(Boolean)
            : [],
        ),
      ),
    )
    const fallbackDraft = fallbackParamNames.reduce<Record<string, unknown>>((acc, key) => {
      if (Object.prototype.hasOwnProperty.call(parameterOverrides, key)) {
        acc[key] = (parameterOverrides as Record<string, unknown>)[key]
      } else if (Object.prototype.hasOwnProperty.call(pipelineDefaultParameters, key)) {
        acc[key] = (pipelineDefaultParameters as Record<string, unknown>)[key]
      } else {
        acc[key] = ''
      }
      return acc
    }, {})
    const baseDraft = {
      ...pipelineDefaultParameters,
      ...parameterOverrides,
    }

    setParameterDialogContext({ mode: 'pipeline', title: 'Configure parameters' })
    setParameterDraft(Object.keys(baseDraft).length ? baseDraft : fallbackDraft)
    setStepSchemaByVersion(null)
    setStepSchemaVersion(null)
  }

  const openStepInspector = (step: ApiPipelineStep) => {
    const draft: Record<string, unknown> = {}
    const defaults = pipelineDefaultParameters as Record<string, unknown>
    const overrides = parameterOverrides as Record<string, unknown>

    const schemaMap =
      step.schemas && typeof step.schemas === 'object' && !Array.isArray(step.schemas)
        ? step.schemas
        : null
    const schemaFromMapVersion = schemaMap ? Object.keys(schemaMap)[0] : null
    const schemaFromStep = step.paramSchema ?? null
    const initialVersion =
      (schemaFromStep?.version && schemaFromStep.version in (schemaMap ?? {}) ? schemaFromStep.version : null) ||
      schemaFromStep?.version ||
      schemaFromMapVersion
    setStepSchemaByVersion(schemaMap)
    setStepSchemaVersion(initialVersion)

    const initialSchema = (initialVersion && schemaMap?.[initialVersion]) || schemaFromStep
    const schemaKeys = initialSchema?.properties ? Object.keys(initialSchema.properties) : []
    const keys = schemaKeys.length ? schemaKeys : Array.isArray(step.paramNames) ? step.paramNames : []
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(overrides, key)) {
        draft[key] = overrides[key]
      } else if (Object.prototype.hasOwnProperty.call(defaults, key)) {
        draft[key] = defaults[key]
      } else if (initialSchema?.properties && Object.prototype.hasOwnProperty.call(initialSchema.properties, key)) {
        const propDefault = initialSchema.properties[key]?.default
        if (propDefault !== undefined) {
          draft[key] = propDefault
        } else if (initialSchema.properties[key]?.type === 'boolean') {
          draft[key] = false
        } else {
          draft[key] = ''
        }
      } else {
        draft[key] = ''
      }
    }

    setParameterDialogContext({
      mode: 'step',
      title: `Step ${step.order || 0}: ${step.tool || 'Step'}`,
      step,
    })
    setParameterDraft(draft)
  }

  const handleParameterDialogCancel = useCallback(() => {
    closeParameterDialog()
  }, [closeParameterDialog])

  const activeStepSchema = useMemo((): ApiStepParamSchema | null => {
    if (parameterDialogContext?.mode !== 'step') return null
    const step = parameterDialogContext.step
    if (!step) return null
    if (stepSchemaByVersion && stepSchemaVersion && stepSchemaByVersion[stepSchemaVersion]) {
      return stepSchemaByVersion[stepSchemaVersion]
    }
    return step.paramSchema ?? null
  }, [parameterDialogContext, stepSchemaByVersion, stepSchemaVersion])

  const stepVersions = useMemo((): string[] => {
    if (parameterDialogContext?.mode !== 'step') return []
    const schemaVersions = stepSchemaByVersion ? Object.keys(stepSchemaByVersion) : []
    const versions = schemaVersions.length ? schemaVersions : activeStepSchema?.version ? [activeStepSchema.version] : []
    return Array.from(new Set(versions)).filter(Boolean)
  }, [activeStepSchema?.version, parameterDialogContext, stepSchemaByVersion])

  const stepValidationErrors = useMemo((): Record<string, string> => {
    if (parameterDialogContext?.mode !== 'step') return {}
    if (!activeStepSchema?.properties) return {}
    const required = new Set(
      (activeStepSchema.required ?? []).filter(
        (k): k is string => typeof k === 'string' && k.trim().length > 0,
      ),
    )
    const errors: Record<string, string> = {}

    for (const [key, prop] of Object.entries(activeStepSchema.properties)) {
      const value = parameterDraft[key]
      const isRequired = required.has(key)
      const type = prop?.type

      const isBlank =
        value == null ||
        (typeof value === 'string' && value.trim() === '') ||
        (Array.isArray(value) && value.length === 0)

      if (isRequired && isBlank) {
        errors[key] = 'Required'
        continue
      }

      if (isBlank) continue

      if (type === 'number' || type === 'integer') {
        const parsed = typeof value === 'number' ? value : Number(value)
        if (!Number.isFinite(parsed)) {
          errors[key] = 'Must be a number'
        } else if (type === 'integer' && !Number.isInteger(parsed)) {
          errors[key] = 'Must be an integer'
        }
      }

      if (type === 'boolean' && typeof value !== 'boolean') {
        errors[key] = 'Must be true/false'
      }

      if (prop?.enum?.length && typeof value === 'string' && !prop.enum.includes(value)) {
        errors[key] = 'Invalid selection'
      }
    }

    return errors
  }, [activeStepSchema, parameterDialogContext?.mode, parameterDraft])
  const stepHasValidationErrors = Object.keys(stepValidationErrors).length > 0

  const handleParameterDialogSave = useCallback(() => {
    if (!parameterDialogContext) return
    if (parameterDialogContext.mode === 'step' && stepHasValidationErrors) {
      return
    }
    if (parameterDialogContext.mode === 'pipeline') {
      setParameterOverrides(parameterDraft)
    } else {
      setParameterOverrides((prev) => ({ ...prev, ...parameterDraft }))
    }
    closeParameterDialog()
  }, [closeParameterDialog, parameterDialogContext, parameterDraft, stepHasValidationErrors])

  const buildAskAgentPromptForStep = (step: ApiPipelineStep, params: Record<string, unknown>) => {
    const datasetBase = dataset?.name ? `${dataset.name} (${dataset.id})` : datasetId || 'none'
    const datasetLabel = selectedDatasetVersion
      ? `${datasetBase} @ ${selectedDatasetVersion}`
      : datasetBase
    const analysisLabel = selectedAnalysisConfig?.label || selectedAnalysis || 'none'
    const pipelineLabel = selectedPipelineConfig?.label || selectedPipeline || 'none'
    const stepLabel = `${step.order || 0}. ${step.tool || 'step'}`
    const lines: string[] = []
    lines.push('Help me configure this pipeline step.')
    if (intent.trim()) lines.push(`Intent: ${intent.trim()}`)
    lines.push(`Dataset: ${datasetLabel}`)
    lines.push(`Analysis: ${analysisLabel}`)
    lines.push(`Pipeline: ${pipelineLabel}`)
    lines.push(`Step: ${stepLabel}`)
    if (step.description) lines.push(`Description: ${step.description}`)
    if (step.paramNames?.length) {
      lines.push(`Parameters: ${step.paramNames.join(', ')}`)
    }
    if (Object.keys(params).length) {
      lines.push('')
      lines.push('Current parameter values:')
      lines.push(JSON.stringify(params, null, 2))
    }
    lines.push('')
    lines.push('Please suggest sensible parameter values and explain tradeoffs.')
    return lines.join('\n')
  }

  const handleConfirmAnalysis = useCallback(async () => {
    if (!datasetId || !selectedAnalysisConfig || !selectedPipelineConfig || isSubmitting) return

    if (hasPendingChecks) {
      setAnalysisError('Checks are still running. Please wait a moment and try again.')
      return
    }

    if (verificationUnavailable) {
      setAnalysisError('Verification is unavailable. Please retry checks before running.')
      return
    }

    if (launchDecisionBlocked) {
      setAnalysisError(launchDecision?.reason || 'Resolve blocked launch checks before running.')
      return
    }

    if (!canRun) {
      setAnalysisError('Please resolve blocked checks before running.')
      return
    }

    try {
      setIsSubmitting(true)
      setAnalysisError(null)

      const extraParams: Record<string, unknown> = { ...checkParameters }
      const params = Object.keys(extraParams).length ? extraParams : undefined

      const response = await fetch('/api/analyses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset_id: datasetId,
          dataset_version: selectedDatasetVersion ?? undefined,
          project_id: projectId ?? 'default',
          analysis_id: selectedAnalysisConfig.id,
          pipeline_id: selectedPipelineConfig.id,
          ...(conceptIds.length ? { concept_ids: conceptIds } : {}),
          parameters: params,
          ...(intent.trim() ? { title: intent.trim() } : {}),
          ...(threadId ? { thread: { mode: 'reuse', thread_id: threadId } } : {}),
        }),
      })

      if (!response.ok) {
        let message = 'Failed to start run.'
        try {
          const errorBody = await response.json()
          if (errorBody && typeof errorBody.detail === 'string') {
            message = errorBody.detail
          }
        } catch (error) {
          console.error('Unable to parse run error', error)
        }
        setAnalysisError(message)
        return
      }

      const data: {
        analysis_id?: string
        run_id?: string
        job_id?: string
        thread_id?: string | null
      } = await response.json()
      const analysisId = data.analysis_id || data.run_id || data.job_id
      if (!analysisId) {
        setAnalysisError('Run created but missing identifier. Please check Runs.')
        return
      }

      onRunCreated?.(analysisId, data.thread_id)
    } catch (error) {
      console.error('Failed to start run', error)
      setAnalysisError('Failed to start run. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }, [
    canRun,
    checkParameters,
    conceptIds,
    datasetId,
    hasPendingChecks,
    isSubmitting,
    launchDecision?.reason,
    launchDecisionBlocked,
    onRunCreated,
    projectId,
    selectedAnalysisConfig,
    selectedDatasetVersion,
    selectedPipelineConfig,
    threadId,
    verificationUnavailable,
    intent,
  ])

  const handleOpenFullRun = useCallback(() => {
    if (!canOpenFullRunHandoff) {
      setAnalysisError('Select a workflow before handing off a full run.')
      return
    }
    const payload = buildStudioHandoffPayload()
    if (!payload) {
      setAnalysisError('Complete the plan before handing off a full run.')
      return
    }
    setAnalysisError(null)
    setStudioHandoffPayload(payload)
    setStudioHandoffOpen(true)
  }, [
    buildStudioHandoffPayload,
    canOpenFullRunHandoff,
  ])

  useEffect(() => {
    if (!validationRequestNonce) return
    if (validationRequestNonce === lastValidationRequestRef.current) return
    if (!autosaveReady || isSubmitting) return
    if (!datasetId || !selectedAnalysisConfig || !selectedPipelineConfig) return

    lastValidationRequestRef.current = validationRequestNonce
    void handleConfirmAnalysis()
  }, [
    autosaveReady,
    datasetId,
    handleConfirmAnalysis,
    isSubmitting,
    selectedAnalysisConfig,
    selectedPipelineConfig,
    validationRequestNonce,
  ])

  return (
    <div className="space-y-6">
      {showEmptyPlanCard ? (
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 rounded-md bg-muted p-2 text-muted-foreground">
              <Sparkles className="h-4 w-4" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium">Your plan is empty</div>
              <div className="mt-1 text-sm text-muted-foreground">
                Add data, select a workflow, or describe your goal and I&apos;ll help build a plan.
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button type="button" size="sm" onClick={openLibraryDrawer}>
                  Browse Workflows
                </Button>
                {onAskAgent ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => onAskAgent(buildAskAgentPromptForEmptyPlan())}
                  >
                    Ask Agent
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <Dialog
        open={Boolean(parameterDialogContext)}
        onOpenChange={(open) => {
          if (!open) {
            closeParameterDialog()
          }
        }}
      >
        <DialogContent
          className="max-w-lg"
          aria-describedby="plan-parameter-dialog-description"
          data-testid={
            parameterDialogContext?.mode === 'step'
              ? 'step-inspector'
              : 'pipeline-parameters'
          }
        >
          <DialogHeader>
            <DialogTitle>{parameterDialogContext?.title || 'Configure parameters'}</DialogTitle>
            <DialogDescription id="plan-parameter-dialog-description" className="sr-only">
              Configure pipeline and step parameters for the current analysis plan.
            </DialogDescription>
          </DialogHeader>
          {parameterDialogContext?.mode === 'step' && parameterDialogContext.step?.description ? (
            <div className="text-sm text-muted-foreground">
              {parameterDialogContext.step.description}
            </div>
          ) : null}
          {parameterDialogContext?.mode === 'step' && stepVersions.length > 1 ? (
            <div className="space-y-2">
              <Label className="text-sm font-medium">Version</Label>
              <select
                data-testid="step-version-select"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={stepSchemaVersion ?? stepVersions[0] ?? ''}
                onChange={(e) => {
                  const next = e.target.value
                  setStepSchemaVersion(next || null)
                  if (!next || !stepSchemaByVersion || !stepSchemaByVersion[next]) return
                  const schema = stepSchemaByVersion[next]
                  const keys = schema.properties ? Object.keys(schema.properties) : []
                  setParameterDraft((prev) => {
                    const defaults = pipelineDefaultParameters as Record<string, unknown>
                    const overrides = parameterOverrides as Record<string, unknown>
                    const nextDraft: Record<string, unknown> = {}
                    for (const key of keys) {
                      if (Object.prototype.hasOwnProperty.call(prev, key)) {
                        nextDraft[key] = prev[key]
                        continue
                      }
                      if (Object.prototype.hasOwnProperty.call(overrides, key)) {
                        nextDraft[key] = overrides[key]
                        continue
                      }
                      if (Object.prototype.hasOwnProperty.call(defaults, key)) {
                        nextDraft[key] = defaults[key]
                        continue
                      }
                      const propDefault = schema.properties?.[key]?.default
                      if (propDefault !== undefined) {
                        nextDraft[key] = propDefault
                        continue
                      }
                      if (schema.properties?.[key]?.type === 'boolean') {
                        nextDraft[key] = false
                        continue
                      }
                      nextDraft[key] = ''
                    }
                    return nextDraft
                  })
                }}
              >
                {stepVersions.map((version) => (
                  <option key={version} value={version}>
                    {version}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {Object.keys(parameterDraft).length ? (
            <div className="space-y-4">
              {Object.entries(parameterDraft)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, value]) => (
                  <div key={key} className="space-y-2">
                    <Label className="font-mono text-xs" data-testid={`step-label-${key}`}>
                      {key}
                      {activeStepSchema?.required?.includes(key) ? (
                        <span className="text-red-500"> *</span>
                      ) : null}
                    </Label>
                    {typeof value === 'boolean' ? (
                      <div className="flex items-center justify-between rounded-md border bg-background px-3 py-2">
                        <span className="text-sm text-muted-foreground">
                          {value ? 'Enabled' : 'Disabled'}
                        </span>
                        <Switch
                          checked={value}
                          data-testid={`step-param-${key}`}
                          onCheckedChange={(checked) =>
                            setParameterDraft((prev) => ({ ...prev, [key]: checked }))
                          }
                        />
                      </div>
                    ) : typeof value === 'number' ? (
                      <Input
                        type="number"
                        name={key}
                        aria-label={key}
                        data-testid={`step-param-${key}`}
                        value={Number.isFinite(value) ? value : 0}
                        aria-invalid={Boolean(stepValidationErrors[key])}
                        className={cn(stepValidationErrors[key] ? 'border-red-500 focus-visible:ring-red-500' : '')}
                        onChange={(e) =>
                          setParameterDraft((prev) => ({
                            ...prev,
                            [key]: e.target.value === '' ? '' : Number(e.target.value),
                          }))
                        }
                      />
                    ) : (
                      activeStepSchema?.properties?.[key]?.enum?.length ? (
                        <select
                          name={key}
                          aria-label={key}
                          data-testid={`step-param-${key}`}
                          className={cn(
                            'w-full rounded-md border bg-background px-3 py-2 text-sm',
                            stepValidationErrors[key] ? 'border-red-500 focus-visible:ring-red-500' : '',
                          )}
                          value={value == null ? '' : String(value)}
                          aria-invalid={Boolean(stepValidationErrors[key])}
                          onChange={(e) =>
                            setParameterDraft((prev) => ({ ...prev, [key]: e.target.value }))
                          }
                        >
                          {(activeStepSchema.properties?.[key]?.enum ?? []).map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          name={key}
                          aria-label={key}
                          data-testid={`step-param-${key}`}
                          value={value == null ? '' : String(value)}
                          aria-invalid={Boolean(stepValidationErrors[key])}
                          className={cn(stepValidationErrors[key] ? 'border-red-500 focus-visible:ring-red-500' : '')}
                          onChange={(e) =>
                            setParameterDraft((prev) => ({ ...prev, [key]: e.target.value }))
                          }
                        />
                      )
                    )}
                    {stepValidationErrors[key] ? (
                      <div className="text-xs text-red-600">{stepValidationErrors[key]}</div>
                    ) : null}
                  </div>
                ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              {parameterDialogContext?.mode === 'step'
                ? 'This step has no configurable parameters yet.'
                : 'This pipeline has no configurable parameters yet.'}
            </div>
          )}
          {parameterDialogContext?.mode === 'step' && parameterDialogContext.step && onAskAgent ? (
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  const step = parameterDialogContext.step!
                  onAskAgent(buildAskAgentPromptForStep(step, parameterDraft))
                }}
              >
                Ask Agent about this step
              </Button>
            </div>
          ) : null}
          <DialogFooter className="flex items-center justify-between gap-2 sm:justify-between">
            <Button
              type="button"
              variant="outline"
              data-testid="plan-params-reset"
              onClick={() => {
                if (!parameterDialogContext) return
                const defaults = pipelineDefaultParameters as Record<string, unknown>
                if (parameterDialogContext.mode === 'pipeline') {
                  setParameterDraft({ ...defaults })
                  return
                }
                const step = parameterDialogContext.step
                if (!step) return
                const next: Record<string, unknown> = {}
                const keys = Array.isArray(step.paramNames) ? step.paramNames : []
                for (const key of keys) {
                  if (Object.prototype.hasOwnProperty.call(defaults, key)) {
                    next[key] = defaults[key]
                  } else {
                    next[key] = ''
                  }
                }
                setParameterDraft(next)
              }}
              disabled={
                parameterDialogContext?.mode === 'pipeline'
                  ? !Object.keys(pipelineDefaultParameters).length
                  : !parameterDialogContext?.step?.paramNames?.length
              }
            >
              Reset
            </Button>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                data-testid="plan-params-cancel"
                onClick={handleParameterDialogCancel}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={parameterDialogContext?.mode === 'step' ? stepHasValidationErrors : false}
                data-testid="plan-params-save"
                onClick={handleParameterDialogSave}
              >
                Save
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {!showEmptyPlanCard ? (
        <>
          <ReadOnlyPlanHeader
            title="Plan"
            status={projectionStatus}
            intentSummary={projectionIntentSummary}
            provenance={projectionProvenance}
          />
          <ReadOnlyPlanSummaryCard rows={projectionSummaryRows} />
          <ReadOnlyPlanAlertsCard
            alerts={projectionAlerts}
            onAskAgent={onAskAgent ? handleAskAgentToRevisePlan : undefined}
          />
          {guidanceCardVisible && environmentGuidance ? (
            <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-950/80 via-slate-900/80 to-slate-950/80 p-4 text-sm text-muted-foreground shadow-lg ring-1 ring-white/10">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-primary-300">Neurodesk setup</p>
                  <p className="text-base font-semibold text-white">
                    {environmentGuidance.summary || 'This workflow needs a Neurodesk-backed runtime'}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setChecksRefreshToken((value) => value + 1)}
                  disabled={checksLoading}
                >
                  {checksLoading ? 'Re-checking …' : 'Re-check environment'}
                </Button>
              </div>

              <div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-2">
                {environmentGuidance.runtime_target ? (
                  <div>
                    <p className="font-semibold text-white">Runtime</p>
                    <p>{environmentGuidance.runtime_target}</p>
                  </div>
                ) : null}
                {environmentGuidance.install_path ? (
                  <div>
                    <p className="font-semibold text-white">Recommended path</p>
                    <p>{environmentGuidance.install_path.replace('_', ' ')}</p>
                  </div>
                ) : null}
                {environmentGuidance.required_modules?.length ? (
                  <div>
                    <p className="font-semibold text-white">Modules</p>
                    <p className="text-xs">{environmentGuidance.required_modules.join(', ')}</p>
                  </div>
                ) : null}
                {environmentGuidance.required_env_vars?.length ? (
                  <div>
                    <p className="font-semibold text-white">Env vars</p>
                    <p className="text-xs">{environmentGuidance.required_env_vars.join(', ')}</p>
                  </div>
                ) : null}
              </div>

              {environmentGuidance.detail ? (
                <div className="mt-3 text-xs text-slate-200">{environmentGuidance.detail}</div>
              ) : null}

              <div className="mt-4 flex flex-wrap gap-2">
                {(environmentGuidance.actions ?? []).map((action, index) => (
                  <Button
                    key={`${action.id ?? action.label ?? action.href ?? 'action'}-${index}`}
                    asChild
                    size="sm"
                    variant="secondary"
                  >
                    <a href={action.href || environmentGuidance.next_action_url || '#'} rel="noreferrer" target="_blank">
                      {guidanceActionLabel(action)}
                    </a>
                  </Button>
                ))}
                {environmentGuidance.next_action_url ? (
                  <Button asChild size="sm">
                    <a href={environmentGuidance.next_action_url} target="_blank" rel="noreferrer">
                      Open Neurodesk guide
                    </a>
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
          {executionStatusVisible && executionStatus ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-amber-700">
                    Execution status
                  </p>
                  <p className="mt-1 font-semibold">{executionStatus.message}</p>
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-md border border-amber-200 bg-white/70 px-2 py-1.5">
                  <p className="font-semibold">recipe_generated</p>
                  <p>{executionStatus.recipe_generated ? 'true' : 'false'}</p>
                </div>
                <div className="rounded-md border border-amber-200 bg-white/70 px-2 py-1.5">
                  <p className="font-semibold">runtime_available</p>
                  <p>{executionStatus.runtime_available ? 'true' : 'false'}</p>
                </div>
                <div className="rounded-md border border-amber-200 bg-white/70 px-2 py-1.5">
                  <p className="font-semibold">hosted_executed</p>
                  <p>{executionStatus.hosted_executed ? 'true' : 'false'}</p>
                </div>
                <div className="rounded-md border border-amber-200 bg-white/70 px-2 py-1.5">
                  <p className="font-semibold">artifact_verified</p>
                  <p>{executionStatus.artifact_verified ? 'true' : 'false'}</p>
                </div>
              </div>
            </div>
          ) : null}
          <ReadOnlyPlanRunGate
            status={projectionStatus}
            runtime={estimate?.runtime || selectedPipelineConfig?.estRuntime || 'TBD'}
            primaryLabel={
              authBlocked ? 'Sign in to run' : hasVisibleWarningChecks ? 'Run with warnings' : 'Run'
            }
            secondaryLabel={onAskAgent ? 'Ask agent' : undefined}
            canRun={authBlocked ? true : canRun}
            isSubmitting={isSubmitting}
            onPrimaryAction={authBlocked ? openSignIn : handleConfirmAnalysis}
            onSecondaryAction={onAskAgent ? handleAskAgentToRevisePlan : undefined}
          />
          {analysisError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {analysisError}
            </div>
          ) : null}
        </>
      ) : null}

      <PlanAdvancedPanel description="Manual editing, verification details, step inspection, and full-run handoff stay here.">
      <div className="space-y-2">
        <div className="text-sm font-medium">Intent</div>
        <div className="text-sm text-muted-foreground">
          A one-line goal for this plan. You can edit it before running.
        </div>
        <Input
          ref={intentInputRef}
          value={intent}
          placeholder="Describe the plan goal…"
          disabled={!autosaveReady}
          onChange={(e) => {
            const nextIntent = e.target.value
            const nextTouched = nextIntent.trim().length > 0
            latestIntentRef.current = nextIntent
            latestIntentTouchedRef.current = nextTouched
            setIntentTouched(nextTouched)
            setIntent(nextIntent)
            persistPlanDraftNow({ intent: nextIntent, intent_touched: nextTouched })
          }}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-sm font-medium">Data</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {!datasetId
                ? 'No dataset selected yet.'
                : datasetLoading
                  ? 'Loading dataset…'
                  : dataset?.name || datasetId}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={openDatasetPicker}
            disabled={!autosaveReady}
          >
            {datasetId ? 'Change' : 'Browse'}
          </Button>
        </div>
        {datasetError ? (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-3">
            {datasetError}
          </div>
        ) : null}
        {dataset ? (
          <div className="text-xs text-muted-foreground">
            Modalities: {dataset.modalities.length ? dataset.modalities.join(', ') : '—'}
            {dataset.subjects_count != null ? ` · ${dataset.subjects_count} subjects` : ''}
          </div>
        ) : null}
        {datasetId ? (
          <div className="rounded-md border bg-muted/20 p-3 text-xs">
            <div className="font-medium text-foreground">Dataset version</div>
            {datasetVersionOptions.length ? (
              <div className="mt-2 space-y-2">
                <select
                  data-testid="plan-dataset-version-select"
                  className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                  value={selectedDatasetVersion ?? ''}
                  onChange={(event) => {
                    const next = event.target.value.trim()
                    const normalized = next || null
                    setSelectedDatasetVersion(normalized)
                    persistPlanDraftNow({ dataset_version: normalized })
                  }}
                >
                  {!selectedDatasetVersion ? (
                    <option value="" disabled>
                      Select a version…
                    </option>
                  ) : null}
                  {datasetVersionOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                      {option.recommended ? ' · recommended' : ''}
                      {option.availability === 'available' ? ' · mounted' : ''}
                    </option>
                  ))}
                </select>
                <div className="text-muted-foreground">
                  Selected: <span className="font-medium text-foreground">{selectedDatasetVersion || 'none'}</span>
                </div>
              </div>
            ) : (
              <div className="mt-1 text-muted-foreground">
                No explicit version metadata found. Plan will use current mounted/catalog data.
              </div>
            )}
          </div>
        ) : null}
        {datasetResourcesLoading ? (
          <div className="text-xs text-muted-foreground">Checking dataset access paths…</div>
        ) : null}
        {datasetResources ? (
          <div className="rounded-md border bg-muted/20 p-3 text-xs">
            <div className="font-medium text-foreground">Data access</div>
            <div className="mt-1 text-muted-foreground">
              {datasetResources.unavailable
                ? 'Access checks unavailable. Using catalog metadata only.'
                : datasetResources.readiness?.status?.toLowerCase() === 'degraded'
                  ? 'Access checks degraded. Using static source address hints.'
                : 'Access addresses resolved from backend checks.'}
            </div>
            <div className="mt-2 space-y-1 text-muted-foreground">
              {datasetResources.addresses?.s3_uri ? (
                <div>
                  AWS/S3 mount: <span className="font-mono text-foreground">{datasetResources.addresses.s3_uri}</span>
                </div>
              ) : null}
              {datasetResources.addresses?.openneuro_url ? (
                <div>
                  OpenNeuro: <span className="font-mono text-foreground">{datasetResources.addresses.openneuro_url}</span>
                </div>
              ) : null}
              {datasetResources.addresses?.source_repo_url ? (
                <div>
                  Source URL: <span className="font-mono text-foreground">{datasetResources.addresses.source_repo_url}</span>
                </div>
              ) : null}
              {datasetResources.source_access?.bucket_check?.state ? (
                <div>
                  Bucket check:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.source_access.bucket_check.state}
                  </span>
                  {datasetResources.source_access.bucket_check.method
                    ? ` via ${datasetResources.source_access.bucket_check.method}`
                    : ''}
                  {datasetResources.source_access.bucket_check.cache_hit
                    ? ' (cached)'
                    : ''}
                  {datasetResources.source_access.bucket_check.message
                    ? ` · ${datasetResources.source_access.bucket_check.message}`
                    : ''}
                </div>
              ) : null}
              {datasetResources.readiness?.status ? (
                <div>
                  Readiness: <span className="font-medium text-foreground">{datasetResources.readiness.status}</span>
                  {datasetResources.readiness.reason ? ` (${datasetResources.readiness.reason})` : ''}
                </div>
              ) : null}
              {datasetResources.selected_version ? (
                <div>
                  Version:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.selected_version}
                  </span>
                </div>
              ) : null}
              {datasetResources.exists_summary?.version_selection_mode === 'metadata_only' &&
              datasetResources.selected_version ? (
                <div>
                  Version scope:{" "}
                  <span className="font-medium text-foreground">
                    metadata/planning only (mount resolution uses current local data)
                  </span>
                </div>
              ) : null}
              {datasetResources.source_access?.version_check?.mode ? (
                <div>
                  Version verification:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.source_access.version_check.mode}
                  </span>
                  {datasetResources.source_access.version_check.resolved
                    ? ` · resolved ${datasetResources.source_access.version_check.resolved}`
                    : ''}
                </div>
              ) : null}
              {datasetResources.source_access?.available_versions?.length ? (
                <div>
                  Source versions:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.source_access.available_versions
                      .map((version) =>
                        version.state === 'verified'
                          ? `${version.label} (verified)`
                          : `${version.label} (metadata)`,
                      )
                      .slice(0, 4)
                      .join(', ')}
                    {datasetResources.source_access.available_versions.length > 4
                      ? ` +${datasetResources.source_access.available_versions.length - 4} more`
                      : ''}
                  </span>
                </div>
              ) : null}
              {typeof datasetResources.dataset_summary?.subjects_count === 'number' ? (
                <div>
                  Subjects:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.dataset_summary.subjects_count}
                  </span>
                </div>
              ) : null}
              {datasetResources.storage_summary?.available_derivatives?.length ? (
                <div>
                  Derivatives:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.storage_summary.available_derivatives.join(', ')}
                  </span>
                </div>
              ) : null}
              {typeof datasetResources.files_summary?.total_matched_files === 'number' ? (
                <div>
                  File matches:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.files_summary.total_matched_files}
                  </span>
                </div>
              ) : null}
              {typeof datasetResources.exists_summary?.dataset_in_catalog === 'boolean' ? (
                <div>
                  Catalog:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.exists_summary.dataset_in_catalog ? 'found' : 'not found'}
                  </span>
                </div>
              ) : null}
              {typeof datasetResources.exists_summary?.local_bids_available === 'boolean' ? (
                <div>
                  Mounted data:{" "}
                  <span className="font-medium text-foreground">
                    {datasetResources.exists_summary.local_bids_available ? 'available' : 'not detected'}
                  </span>
                </div>
              ) : null}
              {!datasetResources.addresses?.s3_uri &&
              !datasetResources.addresses?.openneuro_url &&
              !datasetResources.addresses?.source_repo_url ? (
                <div>No mount/source address is currently available for this dataset.</div>
              ) : null}
            </div>
          </div>
        ) : null}
        {datasetResourcesError ? (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
            {datasetResourcesError}
          </div>
        ) : null}

        <div className="rounded-lg border bg-muted/20 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Concepts
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {conceptIds.length ? `${conceptIds.length} selected` : 'No concepts added yet.'}
              </div>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => router.push('/kg')}>
              Browse concepts
            </Button>
          </div>
          {conceptIds.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {conceptIds.map((id) => {
                const label = conceptLabels[id]
                const display = label || id
                const title = label ? `${label} (${id})` : id
                return (
                  <Badge key={id} variant="outline" className="flex items-center gap-1 pr-1">
                    <span className="max-w-[200px] truncate" title={title}>
                      {display}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove concept ${id}`}
                      className="ml-1 rounded-full px-1 text-muted-foreground hover:text-foreground"
                      onClick={() => setConceptIds((prev) => prev.filter((value) => value !== id))}
                    >
                      ×
                    </button>
                  </Badge>
                )
              })}
            </div>
          ) : null}
        </div>
      </div>

      <div className="space-y-3">
        <div ref={pipelineSectionRef} className="text-sm font-medium">
          Pipeline
        </div>
        
        {/* Dynamic workflow loaded from API - show workflow details directly */}
        {dynamicWorkflowLoading ? (
          <div className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading workflow details…
          </div>
        ) : dynamicWorkflowError ? (
          <div className="text-sm text-red-600">
            Failed to load workflow: {dynamicWorkflowError}
          </div>
        ) : dynamicWorkflow ? (
          <div className="space-y-3">
            <div className="rounded-2xl border border-primary ring-2 ring-primary p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-foreground">{dynamicWorkflow.description || dynamicWorkflow.id}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Stage: {dynamicWorkflow.stage} · Cost: {dynamicWorkflow.cost_tier}
                  </div>
                  {dynamicWorkflow.modalities?.length ? (
                    <div className="text-xs text-muted-foreground">
                      Modalities: {dynamicWorkflow.modalities.join(', ')}
                    </div>
                  ) : null}
                  {dynamicWorkflow.est_runtime ? (
                    <div className="text-xs text-muted-foreground">
                      Est. runtime: {dynamicWorkflow.est_runtime}
                    </div>
                  ) : null}
                </div>
                <Badge variant="secondary">Dynamic</Badge>
              </div>
              {dynamicWorkflow.runtime?.steps?.length ? (
                <div className="mt-3 space-y-1">
                  <div className="text-xs font-medium text-muted-foreground">Pipeline steps ({dynamicWorkflow.runtime.steps.length}):</div>
                  <ul className="ml-4 list-disc text-xs text-muted-foreground">
                    {dynamicWorkflow.runtime.steps.map((step, idx) => (
                      <li key={idx}>
                        <span className="font-mono">{step.tool}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {dynamicWorkflowSchemaLoading ? (
                <div className="mt-2 text-xs text-muted-foreground">Loading parameter contract…</div>
              ) : null}
              {dynamicWorkflowSchemaError ? (
                <div className="mt-2 text-xs text-amber-700">
                  Parameter schema unavailable; using inferred inputs.
                </div>
              ) : null}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                // Clear dynamic selection first so URL sync effects do not re-apply pipeline.
                setDynamicWorkflow(null)
                setDynamicWorkflowLoading(false)
                setDynamicWorkflowError(null)
                setDynamicWorkflowSchema(null)
                setDynamicWorkflowSchemaLoading(false)
                setDynamicWorkflowSchemaError(null)
                setSelectedAnalysis(null)
                setSelectedPipeline(null)
                setSelectedTask(null)

                const current = new URLSearchParams(searchParams.toString())
                current.delete('pipeline')
                current.delete('template')
                current.delete('pickDataset')
                current.set('tab', 'plan')
                const suffix = current.toString()
                const target = suffix ? `/studio?${suffix}` : '/studio?tab=plan'
                if (typeof window !== 'undefined') {
                  window.location.assign(target)
                  return
                }
                router.replace(target, { scroll: false })
              }}
            >
              Choose different workflow
            </Button>
          </div>
        ) : (
          /* Static analysis type selector */
          <div className="space-y-2">
            <div className="text-sm text-muted-foreground">1. Choose a workflow family</div>
            <div className="space-y-2">
              {analysisOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => {
                    setSelectedAnalysis(option.id)
                    setSelectedPipeline(null)
                    setSelectedTask(null)
                  }}
                  disabled={!option.supported}
                  className={cn(
                    'w-full rounded-2xl border p-3 text-left transition hover:border-primary/60 disabled:opacity-50 disabled:cursor-not-allowed',
                    selectedAnalysis === option.id && 'border-primary ring-2 ring-primary',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-foreground">{option.label}</div>
                      <div className="text-sm text-muted-foreground">{option.description}</div>
                    </div>
                    {!option.supported ? <Badge variant="secondary">Incompatible</Badge> : null}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Only show pipeline selector for static analysis types, not dynamic workflows */}
        {selectedAnalysisConfig && !dynamicWorkflow && !dynamicWorkflowLoading ? (
          <div className="space-y-2">
            <div className="text-sm text-muted-foreground">2. Choose a pipeline</div>
            {pipelinesLoading ? (
              <div className="text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading pipelines…
              </div>
            ) : pipelineOptions.length ? (
              <div className="space-y-3">
                {pipelineOptions.map((pipelineOption) => {
                  const pipelineWithSteps = pipelineOption as PipelineOption & {
                    apiSteps?: ApiPipelineStep[]
                  }
                  return (
                    <button
                      key={pipelineOption.id}
                      type="button"
                      onClick={() => setSelectedPipeline(pipelineOption.id)}
                      className={cn(
                        'w-full rounded-2xl border p-4 text-left transition hover:border-primary/60',
                        selectedPipeline === pipelineOption.id &&
                          'border-primary ring-2 ring-primary',
                      )}
                    >
                      <div className="text-sm font-semibold text-foreground">{pipelineOption.label}</div>
                      <div className="text-sm text-muted-foreground">{pipelineOption.description}</div>
                      {pipelineWithSteps.apiSteps && pipelineWithSteps.apiSteps.length > 0 ? (
                        <div className="mt-2 space-y-1">
                          <div className="text-xs font-medium text-muted-foreground">Pipeline steps:</div>
                          <ul className="ml-4 list-disc text-xs text-muted-foreground">
                            {pipelineWithSteps.apiSteps.map((step, idx) => (
                              <li key={idx}>
                                <span className="font-mono">{step.tool}</span>
                                {step.description ? ` - ${step.description}` : ''}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <div className="mt-2 text-xs text-muted-foreground">
                        Modalities:{' '}
                        {pipelineOption.modalities.length
                          ? pipelineOption.modalities.join(', ')
                          : 'Any'}
                      </div>
                      <div className="text-xs text-muted-foreground">Est. runtime: {pipelineOption.estRuntime}</div>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                No compatible pipelines available for this dataset.
              </div>
            )}
          </div>
        ) : null}

        {selectedPipelineConfig ? (
          <div className="flex items-center justify-end gap-2">
            {Object.keys(parameterOverrides).length ? (
              <div className="text-xs text-muted-foreground" data-testid="parameter-overrides-count">
                {Object.keys(parameterOverrides).length} override
                {Object.keys(parameterOverrides).length === 1 ? '' : 's'} applied
              </div>
            ) : null}
            <Button type="button" variant="outline" size="sm" onClick={openPipelineParameters}>
              Configure
            </Button>
          </div>
        ) : null}

        {selectedPipelineConfig &&
        (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] }).apiSteps?.length ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium text-foreground">Steps</div>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  size="sm"
                  variant={stepsView === 'card' ? 'default' : 'outline'}
                  data-testid="plan-view-toggle-card"
                  onClick={() => setStepsView('card')}
                >
                  Card View
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={stepsView === 'dag' ? 'default' : 'outline'}
                  data-testid="plan-view-toggle-dag"
                  onClick={() => setStepsView('dag')}
                >
                  DAG View
                </Button>
              </div>
            </div>
            {stepsView === 'dag' ? (
              <div className="space-y-2">
                <PlanDagView
                  steps={
                    (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] })
                      .apiSteps!
                  }
                  statusByOrder={dagStatusByOrder}
                  onStepSelect={(order) => {
                    const steps =
                      (selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] })
                        .apiSteps ?? []
                    const match =
                      steps.find((step) => (step.order || 0) === order) ??
                      steps[order - 1]
                    if (!match) return
                    openStepInspector(match)
                  }}
                />
                <div className="text-xs text-muted-foreground">Click a node to inspect parameters.</div>
              </div>
            ) : (
              <div className="rounded-2xl border bg-card divide-y">
                {(selectedPipelineConfig as PipelineOption & { apiSteps?: ApiPipelineStep[] }).apiSteps!.map(
                  (step) => (
                    <div
                      key={`${step.order}-${step.tool}`}
                      className="p-4 flex items-start justify-between gap-3"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-foreground">
                          {step.order ? `${step.order}. ` : ''}
                          <span className="font-mono">{step.tool}</span>
                        </div>
                        {step.description ? (
                          <div className="mt-1 text-xs text-muted-foreground">
                            {step.description}
                          </div>
                        ) : null}
                        {step.paramNames?.length ? (
                          <div className="mt-2 text-xs text-muted-foreground">
                            Params: {step.paramNames.slice(0, 6).join(', ')}
                            {step.paramNames.length > 6 ? '…' : ''}
                          </div>
                        ) : (
                          <div className="mt-2 text-xs text-muted-foreground">
                            No configurable parameters.
                          </div>
                        )}
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openStepInspector(step)}
                      >
                        Inspect
                      </Button>
                    </div>
                  ),
                )}
              </div>
            )}
          </div>
        ) : null}

        {toolsUsed.length ? (
          <div className="rounded-2xl border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-sm font-medium text-foreground">Tools used ({toolsUsed.length})</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Browse tool metadata and ask the assistant to wire it safely into your plan.
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setToolsUsedOpen((prev) => !prev)}
              >
                {toolsUsedOpen ? 'Hide' : 'Show'}
              </Button>
            </div>

            {toolsUsedOpen ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {toolsUsed.map((tool) => (
                  <Button
                    key={tool}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const q = encodeURIComponent(tool)
                      router.push(`/library/tools?q=${q}&tool=${q}`)
                    }}
                  >
                    <span className="font-mono text-xs">{tool}</span>
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {selectedAnalysis === 'multiverse_glm' && selectedPipeline ? (
          <div ref={multiverseSectionRef} className="space-y-3">
            <div className="text-sm font-medium text-foreground">3. Configure multiverse parameters</div>
            <div className="space-y-4">
              {datasetLoading ? (
                <div className="text-xs text-muted-foreground">Loading dataset task metadata…</div>
              ) : dataset?.tasks?.length ? (
                <div className="space-y-2">
                  <label htmlFor="task-select" className="text-sm font-medium text-foreground">
                    Task
                  </label>
                  <select
                    id="task-select"
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={selectedTask || ''}
                    onChange={(e) => setSelectedTask(e.target.value || null)}
                  >
                    <option value="">Select a task...</option>
                    {dataset.tasks.map((task) => (
                      <option key={task} value={normalizeTaskLabel(task)}>
                        {task}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="space-y-2">
                  <label htmlFor="task-input" className="text-sm font-medium text-foreground">
                    Task
                  </label>
                  <input
                    id="task-input"
                    type="text"
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    placeholder="Enter task label (e.g., nback)"
                    value={selectedTask || ''}
                    onChange={(e) => {
                      const normalized = normalizeTaskLabel(e.target.value)
                      setSelectedTask(normalized || null)
                    }}
                  />
                  <div className="text-xs text-muted-foreground">
                    {datasetError
                      ? 'Dataset task metadata is unavailable. Provide an explicit task label to continue.'
                      : 'Dataset metadata does not list tasks. Provide an explicit task label to continue.'}
                  </div>
                </div>
              )}
              <div className="space-y-2">
                <label htmlFor="max-models" className="text-sm font-medium text-foreground">
                  Max models
                </label>
                <input
                  id="max-models"
                  type="number"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={maxModels}
                  min={1}
                  max={20}
                  onChange={(e) => setMaxModels(parseInt(e.target.value, 10) || 3)}
                />
                <div className="text-xs text-muted-foreground">
                  Number of GLM variants to generate (HRF × confounds × high-pass combinations)
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="space-y-3">
        <div className="text-sm font-medium">Verify</div>
        {checksError ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div>Verification unavailable: {checksError}</div>
            <div className="mt-2">
              Run is blocked until verification checks become available.
            </div>
            <div className="mt-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setChecksRefreshToken((value) => value + 1)}
              >
                Retry verification
              </Button>
            </div>
          </div>
        ) : null}
        <div className="space-y-2">
          {checksLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Running verification…
            </div>
          ) : null}
          {launchDecision && launchDecisionLabel ? (
            <div
              className={cn(
                'rounded-md border px-3 py-2 text-xs',
                launchDecision.can_launch === false
                  ? 'border-red-200 bg-red-50 text-red-800'
                  : launchDecision.status === 'runnable_with_warning'
                    ? 'border-amber-200 bg-amber-50 text-amber-800'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-800',
              )}
            >
              <span className="font-medium">{launchDecisionLabel}</span>
              {launchDecision.reason ? <span>: {launchDecision.reason}</span> : null}
            </div>
          ) : null}
          {visibleChecks.map((check) => (
            <div key={check.id} className="flex items-start justify-between gap-3 text-sm">
              <div className="min-w-0">
                <div className="text-muted-foreground">{check.label}</div>
                {check.detail ? (
                  <div className="text-xs text-muted-foreground">{check.detail}</div>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                {check.id === 'authenticated' && check.status === 'blocked' ? (
                  <Button type="button" variant="outline" size="sm" onClick={openSignIn}>
                    Sign in
                  </Button>
                ) : null}
                {check.id === 'workflow_compatible' && check.status === 'blocked' ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => scrollToSection(pipelineSectionRef.current)}
                  >
                    Review pipeline
                  </Button>
                ) : null}
                {check.id === 'inputs_provided' && check.status === 'blocked' ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => scrollToSection(pipelineSectionRef.current)}
                  >
                    Fill inputs
                  </Button>
                ) : null}
                {['task', 'max_models'].includes(check.id) && (check.status === 'blocked' || check.status === 'warning') ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => scrollToSection(multiverseSectionRef.current)}
                  >
                    Review multiverse
                  </Button>
                ) : null}
                {showFixReviewControls &&
                onAskAgent &&
                (check.status === 'blocked' || check.status === 'warning') &&
                check.id !== 'authenticated' ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onAskAgent(buildAskAgentPromptForCheck(check))}
                  >
                    Ask Agent to fix
                  </Button>
                ) : null}
                {check.id === 'data_validated' && check.status === 'blocked' ? (
                  <Button variant="outline" size="sm" onClick={openDatasetPicker}>
                    Browse
                  </Button>
                ) : null}
                {check.status === 'passed' ? (
                  <Badge>Passed</Badge>
                ) : check.status === 'pending' ? (
                  <Badge variant="secondary">Pending</Badge>
                ) : check.status === 'warning' ? (
                  <Badge variant="outline">Warning</Badge>
                ) : (
                  <Badge variant="destructive">Blocked</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {effectiveConfig ? (
        <div className="space-y-2">
          <div className="text-sm font-medium">Effective Run Config</div>
          <div className="rounded-md border bg-muted/20 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-muted-foreground">
                Final resolved execution payload (parameters plus dataset context) with origin (user/default/inferred/base).
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant="outline" size="sm" onClick={copyEffectiveConfig}>
                  Copy JSON
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={exportEffectiveConfig}>
                  Export JSON
                </Button>
              </div>
            </div>
            {effectiveCopyStatus === 'copied' ? (
              <div className="mt-2 text-[11px] text-emerald-700">Copied effective config.</div>
            ) : null}
            {effectiveCopyStatus === 'error' ? (
              <div className="mt-2 text-[11px] text-amber-700">Copy failed. Use Export JSON.</div>
            ) : null}
            <div className="mt-2 max-h-52 overflow-auto rounded border bg-background p-2 font-mono text-[11px]">
              <pre>{effectiveConfigJson}</pre>
            </div>
            {effectiveConfig.parameters?.length ? (
              <div className="mt-2 grid gap-1">
                {effectiveConfig.parameters.map((entry) => (
                  <div key={entry.key} className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-foreground">{entry.key}</span>
                    <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
                      {entry.origin}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <div className="text-sm font-medium">Estimate</div>
        {selectedPipelineConfig || estimate?.runtime ? (
          <div className="text-sm text-muted-foreground">
            Runtime: {estimate?.runtime || selectedPipelineConfig?.estRuntime || 'TBD'}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            Select a pipeline to see a runtime estimate.
          </div>
        )}
      </div>

      <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
        Studio runs are for validation: verify inputs, parameters, expected outputs, and failure modes here.
        Use full run handoff when you are ready to execute in your IDE or cluster.
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => router.push('/analyses')}>
          View runs
        </Button>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {selectedWorkflowRecipeLaunchable !== null ? (
            <span className="text-xs text-muted-foreground">
              {selectedWorkflowRecipeLaunchable
                ? `Recipe: ${selectedWorkflowRecipeTargets.join(', ') || 'available'}`
                : 'Manual/admin-only'}
            </span>
          ) : null}
          {hasVisibleWarningChecks ? (
            <span className="text-xs text-muted-foreground">Warnings present</span>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleOpenFullRun}
            disabled={!canOpenFullRunHandoff}
          >
            <Code2 className="mr-2 h-3.5 w-3.5" />
            Hand off to Codex/Cursor
          </Button>
        </div>
      </div>
      </PlanAdvancedPanel>
      {studioHandoffPayload ? (
        <HandoffModal
          open={studioHandoffOpen}
          onClose={() => setStudioHandoffOpen(false)}
          mode="template"
          payload={studioHandoffPayload}
        />
      ) : null}
    </div>
  )
}
