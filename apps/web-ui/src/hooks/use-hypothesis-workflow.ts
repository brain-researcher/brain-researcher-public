'use client'

import { useCallback, useMemo, useState } from 'react'

import type {
  ClarifyQuestion,
  DirectionCandidate,
  HypothesisCanvas,
  PlanPatchResult,
  ResearchPreview,
  ValidationReport,
  WorkflowPlan,
  WorkflowStage,
} from '@/types/hypothesis'

type WorkflowContext = {
  datasetId?: string
  conceptId?: string
  taskId?: string
}

type ClarifyInput = {
  term: string
}

type RequestPreviewInput = {
  candidate?: DirectionCandidate | null
}

type ConfirmPreviewInput = {
  preview?: ResearchPreview | null
}

type GeneratePlanInput = {
  candidate?: DirectionCandidate | null
  preview?: ResearchPreview | null
  skipPreviewConfirmation?: boolean
}

type BusyAction =
  | 'clarify'
  | 'canvas'
  | 'candidates'
  | 'preview'
  | 'plan'
  | 'validate'
  | 'patch'
  | null

const STAGE_ORDER: WorkflowStage[] = [
  'clarify',
  'canvas',
  'candidates',
  'research_preview',
  'research_ready',
  'plan',
  'triage',
  'blocked',
  'ready_to_run',
]

const asString = (value: unknown): string => (typeof value === 'string' ? value : '')

const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

async function parseResponse(response: Response): Promise<Record<string, unknown> | null> {
  const text = await response.text().catch(() => '')
  if (!text) return null
  try {
    const parsed = JSON.parse(text)
    return asRecord(parsed)
  } catch {
    return { message: text }
  }
}

function stageIndex(stage: WorkflowStage): number {
  return STAGE_ORDER.indexOf(stage)
}

function asCanvas(value: unknown): HypothesisCanvas | null {
  const source = asRecord(value)
  if (!source) return null

  const term = asString(source.term).trim()
  if (!term) return null

  return {
    term,
    goal:
      (asString(source.goal).trim() as HypothesisCanvas['goal']) ||
      'mechanism_explanation',
    modality:
      (asString(source.modality).trim() as HypothesisCanvas['modality']) || 'fmri_task',
    population: asString(source.population) || 'Healthy adults',
    primary_outcome: asString(source.primary_outcome) || `${term} outcome`,
    constraints: asString(source.constraints) || 'No constraints specified.',
    research_question:
      asString(source.research_question) || `How is ${term} linked to measurable outcomes?`,
  }
}

function asCandidates(value: unknown): DirectionCandidate[] {
  if (!Array.isArray(value)) return []

  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item, index) => ({
      id: asString(item.id) || `dir-${index + 1}`,
      title: asString(item.title) || `Direction ${index + 1}`,
      hypothesis: asString(item.hypothesis) || 'No hypothesis provided.',
      independent_variable: asString(item.independent_variable) || 'Independent variable',
      dependent_variable: asString(item.dependent_variable) || 'Dependent variable',
      expected_signal: asString(item.expected_signal) || 'Expected signal not provided.',
      likely_data_source: asString(item.likely_data_source) || 'Data source not specified.',
      novelty_gap: asString(item.novelty_gap) || 'Novelty gap not specified.',
      risk_note: asString(item.risk_note) || 'Risk note not specified.',
    }))
}

function asPreview(value: unknown): ResearchPreview | null {
  const source = asRecord(value)
  if (!source) return null

  const coverage = Array.isArray(source.coverage_scope)
    ? source.coverage_scope.filter((item): item is string => typeof item === 'string')
    : []

  const knownGaps = Array.isArray(source.known_gaps)
    ? source.known_gaps.filter((item): item is string => typeof item === 'string')
    : []

  const estimatedMinutes =
    typeof source.estimated_minutes === 'number' ? source.estimated_minutes : 0
  const estimatedCredits =
    typeof source.estimated_credits === 'number' ? source.estimated_credits : 0

  return {
    coverage_scope: coverage,
    estimated_minutes: estimatedMinutes,
    estimated_credits: estimatedCredits,
    risk_level:
      asString(source.risk_level) === 'high'
        ? 'high'
        : asString(source.risk_level) === 'low'
          ? 'low'
          : 'medium',
    known_gaps: knownGaps,
  }
}

function asPlan(value: unknown): WorkflowPlan | null {
  const source = asRecord(value)
  if (!source) return null

  const id = asString(source.id).trim()
  if (!id) return null

  const toStringList = (input: unknown): string[] =>
    Array.isArray(input) ? input.filter((item): item is string => typeof item === 'string') : []

  return {
    id,
    mvp_steps: toStringList(source.mvp_steps),
    full_steps: toStringList(source.full_steps),
    falsifier: asString(source.falsifier),
    success_criteria: toStringList(source.success_criteria),
    assumptions: toStringList(source.assumptions),
  }
}

function asValidation(value: unknown): ValidationReport | null {
  const source = asRecord(value)
  if (!source) return null

  const statusRaw = asString(source.status)
  const status: ValidationReport['status'] =
    statusRaw === 'pass' || statusRaw === 'warn' || statusRaw === 'fail' ? statusRaw : 'fail'

  const triageSource = asRecord(source.triage)
  const triageStatusRaw = asString(triageSource?.status)
  const triageStatus: ValidationReport['triage']['status'] =
    triageStatusRaw === 'fixable' || triageStatusRaw === 'non_fixable' || triageStatusRaw === 'unknown'
      ? triageStatusRaw
      : 'unknown'

  const reasonCodes = Array.isArray(triageSource?.reason_codes)
    ? triageSource?.reason_codes.filter((item): item is ValidationReport['triage']['reason_codes'][number] => typeof item === 'string')
    : []

  const userActions = Array.isArray(triageSource?.user_actions)
    ? triageSource?.user_actions.filter((item): item is string => typeof item === 'string')
    : []

  const checksRaw = Array.isArray(source.checks) ? source.checks : []
  const checks = checksRaw
    .map((check) => asRecord(check))
    .filter((check): check is Record<string, unknown> => Boolean(check))
    .map((check, index) => {
      const checkStatusRaw = asString(check.status)
      const checkStatus: 'pass' | 'warn' | 'fail' =
        checkStatusRaw === 'pass' || checkStatusRaw === 'warn' || checkStatusRaw === 'fail'
          ? checkStatusRaw
          : 'fail'

      return {
        id: asString(check.id) || `check-${index + 1}`,
        label: asString(check.label) || 'Check',
        status: checkStatus,
        detail: asString(check.detail) || '',
      }
    })

  const blocked = asRecord(source.blocked_report)

  return {
    status,
    triage: {
      status: triageStatus,
      reason_codes: reasonCodes,
      user_actions: userActions,
    },
    checks,
    blocked_report: blocked
      ? {
          why_not: asString(blocked.why_not) || 'Path is currently blocked.',
          alternatives: Array.isArray(blocked.alternatives)
            ? blocked.alternatives.filter((item): item is string => typeof item === 'string')
            : [],
          required_inputs: Array.isArray(blocked.required_inputs)
            ? blocked.required_inputs.filter((item): item is string => typeof item === 'string')
            : [],
        }
      : null,
  }
}

function asPatch(value: unknown): PlanPatchResult | null {
  const source = asRecord(value)
  if (!source) return null

  const patchedPlan = asPlan(source.patched_plan)
  if (!patchedPlan) return null

  return {
    summary: asString(source.summary) || 'Applied automatic patch.',
    changed_steps: Array.isArray(source.changed_steps)
      ? source.changed_steps.filter((item): item is string => typeof item === 'string')
      : [],
    patched_plan: patchedPlan,
  }
}

export function useHypothesisWorkflow(context: WorkflowContext = {}) {
  const [started, setStarted] = useState(false)
  const [stage, setStage] = useState<WorkflowStage>('clarify')
  const [generalTerm, setGeneralTerm] = useState('')
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([])
  const [clarifyAnswers, setClarifyAnswers] = useState<Record<string, string>>({})
  const [canvas, setCanvas] = useState<HypothesisCanvas | null>(null)
  const [candidates, setCandidates] = useState<DirectionCandidate[]>([])
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [preview, setPreview] = useState<ResearchPreview | null>(null)
  const [previewConfirmed, setPreviewConfirmed] = useState(false)
  const [plan, setPlan] = useState<WorkflowPlan | null>(null)
  const [validation, setValidation] = useState<ValidationReport | null>(null)
  const [lastPatch, setLastPatch] = useState<PlanPatchResult | null>(null)
  const [patchCount, setPatchCount] = useState(0)
  const [busyAction, setBusyAction] = useState<BusyAction>(null)
  const [error, setError] = useState<string | null>(null)

  const selectedCandidate = useMemo(() => {
    if (!selectedCandidateId) return null
    return candidates.find((candidate) => candidate.id === selectedCandidateId) || null
  }, [candidates, selectedCandidateId])

  const canTriggerDeepResearch = stageIndex(stage) >= stageIndex('research_ready')
  const isReadyForExecution = stage === 'ready_to_run'

  const startClarify = useCallback(async ({ term }: ClarifyInput) => {
    const normalizedTerm = term.trim()
    if (!normalizedTerm) {
      throw new Error('Please provide a general term first.')
    }

    setBusyAction('clarify')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/clarify', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          term: normalizedTerm,
          context: {
            dataset_id: context.datasetId || null,
            concept_id: context.conceptId || null,
            task_id: context.taskId || null,
          },
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message =
          asString(payload?.message) || asString(payload?.error) || 'Failed to start clarify step.'
        throw new Error(message)
      }

      const suggestedCanvas = asCanvas(payload?.suggested_canvas)
      const questions = Array.isArray(payload?.questions)
        ? payload?.questions
            .map((item) => asRecord(item))
            .filter((item): item is Record<string, unknown> => Boolean(item))
            .map((item) => ({
              id: asString(item.id) || `q-${Math.random().toString(36).slice(2, 8)}`,
              prompt: asString(item.prompt) || 'Clarify this dimension',
              options: Array.isArray(item.options)
                ? item.options
                    .map((option) => asRecord(option))
                    .filter((option): option is Record<string, unknown> => Boolean(option))
                    .map((option, index) => ({
                      id: asString(option.id) || `opt-${index + 1}`,
                      label: asString(option.label) || asString(option.id) || `Option ${index + 1}`,
                    }))
                : [],
            }))
        : []

      setStarted(true)
      setGeneralTerm(normalizedTerm)
      setClarifyQuestions(questions)
      setClarifyAnswers({})
      setCanvas(suggestedCanvas)
      setCandidates([])
      setSelectedCandidateId(null)
      setPreview(null)
      setPreviewConfirmed(false)
      setPlan(null)
      setValidation(null)
      setLastPatch(null)
      setPatchCount(0)
      setStage('canvas')

      return suggestedCanvas
    } finally {
      setBusyAction(null)
    }
  }, [context.conceptId, context.datasetId, context.taskId])

  const updateClarifyAnswer = useCallback((questionId: string, value: string) => {
    setClarifyAnswers((previous) => ({
      ...previous,
      [questionId]: value,
    }))
  }, [])

  const syncCanvasFromAnswers = useCallback(async () => {
    if (!generalTerm.trim()) {
      throw new Error('Start from clarify before syncing canvas.')
    }

    setBusyAction('canvas')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/canvas', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          term: generalTerm,
          answers: clarifyAnswers,
          canvas,
          context: {
            dataset_id: context.datasetId || null,
            concept_id: context.conceptId || null,
            task_id: context.taskId || null,
          },
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message =
          asString(payload?.message) || asString(payload?.error) || 'Failed to sync canvas.'
        throw new Error(message)
      }

      const nextCanvas = asCanvas(payload?.canvas)
      if (!nextCanvas) {
        throw new Error('Canvas response was invalid.')
      }

      setCanvas(nextCanvas)
      setStage('canvas')
      return nextCanvas
    } finally {
      setBusyAction(null)
    }
  }, [canvas, clarifyAnswers, context.conceptId, context.datasetId, context.taskId, generalTerm])

  const updateCanvas = useCallback((patch: Partial<HypothesisCanvas>) => {
    setCanvas((previous) => {
      if (!previous) return previous
      return {
        ...previous,
        ...patch,
      }
    })
  }, [])

  const generateCandidates = useCallback(async () => {
    if (!canvas) {
      throw new Error('Canvas is not ready.')
    }

    setBusyAction('candidates')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/candidates', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          term: generalTerm,
          canvas,
          count: 5,
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message =
          asString(payload?.message) || asString(payload?.error) || 'Failed to generate candidates.'
        throw new Error(message)
      }

      const nextCandidates = asCandidates(payload?.candidates)
      if (!nextCandidates.length) {
        throw new Error('No candidates were generated.')
      }

      setCandidates(nextCandidates)
      setSelectedCandidateId(nextCandidates[0]?.id || null)
      setPreview(null)
      setPreviewConfirmed(false)
      setPlan(null)
      setValidation(null)
      setLastPatch(null)
      setPatchCount(0)
      setStage('candidates')

      return nextCandidates
    } finally {
      setBusyAction(null)
    }
  }, [canvas, generalTerm])

  const requestResearchPreview = useCallback(async (input: RequestPreviewInput = {}) => {
    const candidateToUse = input.candidate || selectedCandidate
    if (!canvas || !candidateToUse) {
      throw new Error('Select one candidate before requesting preview.')
    }

    setBusyAction('preview')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/research-preview', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          term: generalTerm,
          canvas,
          candidate: candidateToUse,
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message =
          asString(payload?.message) || asString(payload?.error) || 'Failed to generate research preview.'
        throw new Error(message)
      }

      const nextPreview = asPreview(payload?.preview)
      if (!nextPreview) {
        throw new Error('Preview response was invalid.')
      }

      setPreview(nextPreview)
      setPreviewConfirmed(false)
      setPlan(null)
      setValidation(null)
      setLastPatch(null)
      setPatchCount(0)
      setStage('research_preview')

      return nextPreview
    } finally {
      setBusyAction(null)
    }
  }, [canvas, generalTerm, selectedCandidate])

  const confirmPreview = useCallback((input: ConfirmPreviewInput = {}) => {
    const previewToConfirm = input.preview || preview
    if (!previewToConfirm) {
      throw new Error('Generate research preview first.')
    }

    if (!preview && input.preview) {
      setPreview(input.preview)
    }
    setPreviewConfirmed(true)
    setStage('research_ready')
  }, [preview])

  const generatePlan = useCallback(async (input: GeneratePlanInput = {}) => {
    const candidateToUse = input.candidate || selectedCandidate
    const previewToUse = input.preview || preview
    const previewIsConfirmed = input.skipPreviewConfirmation || previewConfirmed

    if (!canvas || !candidateToUse) {
      throw new Error('Canvas and candidate are required before plan generation.')
    }
    if (!previewToUse) {
      throw new Error('Generate research preview before generating a plan.')
    }
    if (!previewIsConfirmed) {
      throw new Error('Confirm research preview before generating a plan.')
    }

    setBusyAction('plan')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/plan', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          term: generalTerm,
          canvas,
          candidate: candidateToUse,
          preview: previewToUse,
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message = asString(payload?.message) || asString(payload?.error) || 'Failed to generate plan.'
        throw new Error(message)
      }

      const nextPlan = asPlan(payload?.plan)
      if (!nextPlan) {
        throw new Error('Plan response was invalid.')
      }

      setPlan(nextPlan)
      setValidation(null)
      setLastPatch(null)
      setPatchCount(0)
      setStage('plan')

      return nextPlan
    } finally {
      setBusyAction(null)
    }
  }, [canvas, generalTerm, preview, previewConfirmed, selectedCandidate])

  const validateCurrentPlan = useCallback(async (explicitPlan?: WorkflowPlan, explicitPatchCount?: number) => {
    const targetPlan = explicitPlan || plan
    if (!canvas || !targetPlan) {
      throw new Error('Canvas and plan are required for validation.')
    }

    setBusyAction('validate')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/validate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          canvas,
          plan: targetPlan,
          patch_count: explicitPatchCount ?? patchCount,
          context: {
            dataset_id: context.datasetId || null,
            concept_id: context.conceptId || null,
            task_id: context.taskId || null,
          },
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message = asString(payload?.message) || asString(payload?.error) || 'Failed to validate plan.'
        throw new Error(message)
      }

      const nextValidation = asValidation(payload?.validation)
      if (!nextValidation) {
        throw new Error('Validation response was invalid.')
      }

      setValidation(nextValidation)

      if (nextValidation.triage.status === 'non_fixable' || nextValidation.triage.status === 'unknown') {
        if (nextValidation.status === 'pass') {
          setStage('ready_to_run')
        } else {
          setStage('blocked')
        }
      } else if (nextValidation.status === 'pass' || nextValidation.status === 'warn') {
        setStage('ready_to_run')
      } else {
        setStage('triage')
      }

      return nextValidation
    } finally {
      setBusyAction(null)
    }
  }, [canvas, context.conceptId, context.datasetId, context.taskId, patchCount, plan])

  const applySinglePatchAndRevalidate = useCallback(async () => {
    if (!plan || !validation) {
      throw new Error('Plan and validation are required before patching.')
    }

    setBusyAction('patch')
    setError(null)

    try {
      const response = await fetch('/api/hypothesis/plan-patch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          plan,
          validation,
          patch_count: patchCount,
        }),
      })

      const payload = await parseResponse(response)
      if (!response.ok) {
        const message = asString(payload?.message) || asString(payload?.error) || 'Automatic patch failed.'
        throw new Error(message)
      }

      const patch = asPatch(payload?.patch)
      if (!patch) {
        throw new Error('Patch response was invalid.')
      }

      const nextPatchCount = patchCount + 1
      setPlan(patch.patched_plan)
      setPatchCount(nextPatchCount)
      setLastPatch(patch)
      setStage('plan')

      const revalidated = await validateCurrentPlan(patch.patched_plan, nextPatchCount)
      return { patch, validation: revalidated }
    } finally {
      setBusyAction(null)
    }
  }, [patchCount, plan, validateCurrentPlan, validation])

  const reset = useCallback(() => {
    setStarted(false)
    setStage('clarify')
    setGeneralTerm('')
    setClarifyQuestions([])
    setClarifyAnswers({})
    setCanvas(null)
    setCandidates([])
    setSelectedCandidateId(null)
    setPreview(null)
    setPreviewConfirmed(false)
    setPlan(null)
    setValidation(null)
    setLastPatch(null)
    setPatchCount(0)
    setBusyAction(null)
    setError(null)
  }, [])

  return {
    started,
    stage,
    generalTerm,
    clarifyQuestions,
    clarifyAnswers,
    canvas,
    candidates,
    selectedCandidateId,
    selectedCandidate,
    preview,
    previewConfirmed,
    plan,
    validation,
    lastPatch,
    patchCount,
    busyAction,
    isBusy: busyAction !== null,
    error,
    canTriggerDeepResearch,
    isReadyForExecution,
    setError,
    setSelectedCandidateId,
    updateClarifyAnswer,
    updateCanvas,
    startClarify,
    syncCanvasFromAnswers,
    generateCandidates,
    requestResearchPreview,
    confirmPreview,
    generatePlan,
    validateCurrentPlan,
    applySinglePatchAndRevalidate,
    reset,
  }
}
