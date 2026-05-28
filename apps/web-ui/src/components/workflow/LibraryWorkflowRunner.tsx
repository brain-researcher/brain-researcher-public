'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Code2 } from 'lucide-react'

import type {
  WorkflowDetail,
  WorkflowInputProperty,
  WorkflowInputsSchema,
} from '@/lib/api/workflows'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { buildCodingAgentHandoffHref } from '@/lib/coding-agent-handoff'
import {
  MCP_RECIPE_ACTION_LABEL,
  MCP_RUN_ACTION_LABEL,
} from '@/lib/mcp-recipe-handoff'

type RuntimeToolCheck = {
  tool_id?: string
  status?: string
  available?: boolean
  detail?: string | null
}

type SchemaApiPayload = {
  workflow_id: string
  direct_run_enabled: boolean
  schema_source: 'catalog' | 'runtime_placeholders'
  schema: WorkflowInputsSchema
  defaults: {
    schema_property_defaults: Record<string, unknown>
    workflow_defaults: Record<string, unknown>
    merged: Record<string, unknown>
  }
  discovered_inputs: string[]
  missing_contract_fields: string[]
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

type PreflightApiPayload = {
  ok?: boolean
  strict?: boolean
  resolved_params?: Record<string, unknown>
  checks?: RuntimeToolCheck[]
  warnings?: string[]
  missing_contract_fields?: string[]
  guidance?: PreflightGuidance
  error?: {
    code?: string
    message?: string
    details?: {
      issues?: Array<{ field?: string; message?: string }>
      checks?: RuntimeToolCheck[]
      warnings?: string[]
      guidance?: PreflightGuidance
    }
  }
}

type LibraryWorkflowRunnerProps = {
  workflow: WorkflowDetail
  datasetId?: string | null
  datasetVersion?: string | null
}

function safeObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function readErrorMessage(payload: unknown, fallback: string): string {
  const record = safeObject(payload)
  const nestedError = safeObject(record.error)
  const message = nestedError.message
  if (typeof message === 'string' && message.trim()) return message.trim()
  const detail = record.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  return fallback
}

function inferStatusTone(check: RuntimeToolCheck): 'passed' | 'blocked' | 'warning' {
  const status = String(check.status || '').toLowerCase()
  if (status === 'available' || check.available === true) return 'passed'
  if (status === 'missing') return 'blocked'
  return 'warning'
}

function guidanceActionLabel(action: GuidanceAction): string {
  if ((action.id || '').toLowerCase() === 'neurodesk-play') return 'Open in Neurodesk Play'
  return action.label || 'Open setup guide'
}

function hasRecordEntries(value: Record<string, string> | undefined): value is Record<string, string> {
  return Boolean(value && Object.keys(value).length > 0)
}

function normalizeValueForTextInput(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function renderPropertyHint(property: WorkflowInputProperty): string | null {
  const pieces: string[] = []
  if (property.description) pieces.push(property.description)
  if (typeof property.minimum === 'number' || typeof property.maximum === 'number') {
    const min = typeof property.minimum === 'number' ? property.minimum : '−∞'
    const max = typeof property.maximum === 'number' ? property.maximum : '+∞'
    pieces.push(`Range: ${min} to ${max}`)
  }
  if (property.example != null) {
    pieces.push(`Example: ${normalizeValueForTextInput(property.example)}`)
  }
  return pieces.length ? pieces.join(' · ') : null
}

function extractGuidance(payload: PreflightApiPayload): PreflightGuidance | null {
  const guidance =
    payload.guidance ?? payload.error?.details?.guidance ?? null
  return guidance ? guidance : null
}

export function LibraryWorkflowRunner({
  workflow,
  datasetId,
  datasetVersion,
}: LibraryWorkflowRunnerProps) {
  const router = useRouter()
  const normalizedDatasetId =
    typeof datasetId === 'string' && datasetId.trim() ? datasetId.trim() : null
  const normalizedDatasetVersion =
    typeof datasetVersion === 'string' && datasetVersion.trim() ? datasetVersion.trim() : null

  const [schemaPayload, setSchemaPayload] = useState<SchemaApiPayload | null>(null)
  const [loadingSchema, setLoadingSchema] = useState(true)
  const [schemaError, setSchemaError] = useState<string | null>(null)

  const [paramsDraft, setParamsDraft] = useState<Record<string, unknown>>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [validateBusy, setValidateBusy] = useState(false)
  const [guidance, setGuidance] = useState<PreflightGuidance | null>(null)

  const [validationSummary, setValidationSummary] = useState<string | null>(null)
  const [validationChecks, setValidationChecks] = useState<RuntimeToolCheck[]>([])
  const [validationWarnings, setValidationWarnings] = useState<string[]>([])

  const propertyEntries = useMemo(() => {
    const properties = schemaPayload?.schema?.properties ?? {}
    const required = new Set(schemaPayload?.schema?.required ?? [])
    return Object.entries(properties).sort(([left], [right]) => {
      const leftRequired = required.has(left) ? 0 : 1
      const rightRequired = required.has(right) ? 0 : 1
      if (leftRequired !== rightRequired) return leftRequired - rightRequired
      return left.localeCompare(right)
    })
  }, [schemaPayload])

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    const loadSchema = async () => {
      setLoadingSchema(true)
      setSchemaError(null)
      try {
        const response = await fetch(
          `/api/workflows/${encodeURIComponent(workflow.id)}/schema`,
          {
            method: 'GET',
            cache: 'no-store',
            signal: controller.signal,
          },
        )
        const payload = (await response.json().catch(() => ({}))) as SchemaApiPayload
        if (!response.ok) {
          throw new Error(readErrorMessage(payload, 'Failed to load workflow parameter schema.'))
        }
        if (cancelled) return
        setSchemaPayload(payload)
        setParamsDraft(payload.defaults?.merged ?? {})
      } catch (error) {
        if (cancelled) return
        setSchemaError(
          error instanceof Error
            ? error.message
            : 'Failed to load workflow parameter schema.',
        )
      } finally {
        if (!cancelled) setLoadingSchema(false)
      }
    }

    void loadSchema()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [workflow.id])

  const setFieldValue = useCallback((field: string, value: unknown) => {
    setParamsDraft((prev) => ({ ...prev, [field]: value }))
    setFieldErrors((prev) => {
      if (!(field in prev)) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
    setValidationSummary(null)
  }, [])

  const handleValidate = useCallback(async () => {
    setValidateBusy(true)
    setValidationSummary(null)
    setValidationChecks([])
    setValidationWarnings([])
    setFieldErrors({})
    setGuidance(null)

    try {
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}/preflight`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            params: paramsDraft,
            strict: true,
          }),
        },
      )
      const payload = (await response.json().catch(() => ({}))) as PreflightApiPayload
      setGuidance(extractGuidance(payload))
      const resolved = safeObject(payload.resolved_params)
      if (Object.keys(resolved).length > 0) {
        setParamsDraft(resolved)
      }

      if (response.status === 422) {
        const issues = payload.error?.details?.issues ?? []
        const nextErrors: Record<string, string> = {}
        for (const issue of issues) {
          if (issue.field && issue.message) nextErrors[issue.field] = issue.message
        }
        setFieldErrors(nextErrors)
        setValidationSummary(
          payload.error?.message ||
            'Validation failed. Please review the highlighted fields and try again.',
        )
        return
      }

      if (response.status === 409) {
        setValidationChecks(payload.error?.details?.checks ?? payload.checks ?? [])
        setValidationWarnings(payload.error?.details?.warnings ?? payload.warnings ?? [])
        setValidationSummary(
          payload.error?.message ||
            'This workflow is not runnable in the current environment. Review runtime checks.',
        )
        return
      }

      if (!response.ok) {
        setValidationSummary(
          readErrorMessage(payload, 'Validation service is unavailable. Please retry shortly.'),
        )
        return
      }

      setValidationChecks(payload.checks ?? [])
      setValidationWarnings(payload.warnings ?? [])
      if (payload.ok) {
        setValidationSummary(
          'Checks look ready. Open this workflow in Studio to validate it against a dataset.',
        )
      } else {
        setValidationSummary('Checks completed with warnings. Review them before validating in Studio.')
      }
    } catch (error) {
      setValidationSummary(
        error instanceof Error
          ? error.message
          : 'Validation service is unavailable. Please retry shortly.',
      )
    } finally {
      setValidateBusy(false)
    }
  }, [paramsDraft, workflow.id])

  const handleOpenInStudio = useCallback(() => {
    const query = new URLSearchParams()
    query.set('tab', 'plan')
    query.set('pipeline', workflow.id)
    query.set('singleWorkflow', '1')
    query.set('parameters', JSON.stringify(paramsDraft))
    router.push(`/studio?${query.toString()}`)
  }, [paramsDraft, router, workflow.id])

  const codingAgentHandoffHref = useMemo(
    () =>
      buildCodingAgentHandoffHref({
        datasetId: normalizedDatasetId,
        datasetVersion: normalizedDatasetVersion,
        workflowId: workflow.id,
        workflowLabel: workflow.id,
      }),
    [normalizedDatasetId, normalizedDatasetVersion, workflow.id],
  )

  const handleOpenInCodingAgent = useCallback(() => {
    router.push(codingAgentHandoffHref)
  }, [codingAgentHandoffHref, router])

  const guidanceKind = guidance?.kind?.toLowerCase() ?? ''
  const guidanceRuntimeTarget = guidance?.runtime_target?.toLowerCase() ?? ''
  const guidanceIsNeurodesk =
    guidanceKind.includes('neurodesk') || guidanceRuntimeTarget === 'neurodesk'
  const guidanceIsRecipeHandoff =
    guidanceKind.includes('handoff') ||
    guidanceKind.includes('recipe') ||
    Boolean(guidance?.supported_recipe_targets?.length)
  const guidanceCardVisible = Boolean(
    guidance &&
      (guidanceIsNeurodesk ||
        guidanceIsRecipeHandoff ||
        guidance.summary ||
        guidance.detail ||
        guidance.kind),
  )
  const guidanceEyebrow = guidanceIsNeurodesk
    ? 'Neurodesk setup'
    : guidanceIsRecipeHandoff
      ? 'Recipe handoff'
      : 'Execution guidance'
  const guidanceFallbackSummary = guidanceIsRecipeHandoff
    ? 'Run this workflow locally or in a coding agent'
    : guidanceIsNeurodesk
      ? 'This workflow needs a Neurodesk-backed runtime'
      : 'This workflow needs runtime setup before launch'
  const guidancePrimaryActionLabel = guidanceIsNeurodesk
    ? 'Open Neurodesk guide'
    : 'Open setup guide'
  const localRunRationale =
    guidanceIsRecipeHandoff || guidanceIsNeurodesk
      ? 'Long-running workflows can take tens of minutes to hours and depend on dataset mounts, container modules, and license or environment setup. Brain Researcher provides a recipe and handoff pack instead of starting this from the hosted UI.'
      : null
  const recipeTargets = workflow.supported_recipe_targets ?? []
  const recipeLaunchable =
    typeof workflow.execution_recipe_available === 'boolean'
      ? workflow.execution_recipe_available
      : recipeTargets.length > 0
  const allowRecheck = true

  if (loadingSchema) {
    return <div className="text-sm text-muted-foreground">Loading parameter schema...</div>
  }

  if (schemaError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Schema unavailable</AlertTitle>
        <AlertDescription>{schemaError}</AlertDescription>
      </Alert>
    )
  }

  if (!schemaPayload) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Schema unavailable</AlertTitle>
        <AlertDescription>Failed to load workflow parameter schema.</AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">
          Schema source: {schemaPayload.schema_source === 'catalog' ? 'catalog' : 'inferred'}
        </Badge>
        <Badge variant="secondary">Handoff: MCP recipe</Badge>
        <Badge variant={recipeLaunchable ? 'default' : 'outline'}>
          {recipeLaunchable
            ? `MCP recipe: ${recipeTargets.join(', ') || workflow.primary_target || 'available'}`
            : 'Manual/admin-only'}
        </Badge>
        {schemaPayload.missing_contract_fields.length > 0 ? (
          <Badge variant="secondary">
            Inferred fields: {schemaPayload.missing_contract_fields.join(', ')}
          </Badge>
        ) : null}
      </div>

      {!recipeLaunchable ? (
        <Alert>
          <AlertTitle>Manual/admin-only workflow</AlertTitle>
          <AlertDescription>
            No portable execution recipe is advertised for this workflow; use Studio only for validation and manual handoff.
          </AlertDescription>
        </Alert>
      ) : null}

      <Alert>
        <AlertTitle>MCP-first workflow handoff</AlertTitle>
        <AlertDescription>
          Review parameter defaults here, then get an MCP recipe for local, Neurodesk, container, or Slurm execution. Studio remains available for dataset-aware validation.
        </AlertDescription>
      </Alert>

      <div className="space-y-4 rounded-md border bg-background p-4">
        {propertyEntries.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            No configurable parameters were defined for this workflow.
          </div>
        ) : (
          propertyEntries.map(([field, property]) => {
            const isRequired = (schemaPayload.schema.required ?? []).includes(field)
            const value = paramsDraft[field]
            const hint = renderPropertyHint(property)
            const error = fieldErrors[field]

            return (
              <div key={field} className="space-y-2">
                <Label htmlFor={`workflow-param-${field}`} className="flex items-center gap-2">
                  <span className="font-mono text-xs">{field}</span>
                  {isRequired ? <Badge variant="destructive">Required</Badge> : null}
                </Label>

                {Array.isArray(property.enum) && property.enum.length > 0 ? (
                  <Select
                    value={normalizeValueForTextInput(value)}
                    onValueChange={(next) => setFieldValue(field, next)}
                  >
                    <SelectTrigger id={`workflow-param-${field}`}>
                      <SelectValue placeholder={`Select ${field}`} />
                    </SelectTrigger>
                    <SelectContent>
                      {property.enum.map((option) => {
                        const key = normalizeValueForTextInput(option)
                        return (
                          <SelectItem key={`${field}-${key}`} value={key}>
                            {key}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                ) : property.type === 'boolean' ? (
                  <div className="flex items-center gap-3">
                    <Switch
                      id={`workflow-param-${field}`}
                      checked={Boolean(value)}
                      onCheckedChange={(next) => setFieldValue(field, next)}
                    />
                    <span className="text-xs text-muted-foreground">
                      {Boolean(value) ? 'True' : 'False'}
                    </span>
                  </div>
                ) : property.type === 'object' || property.type === 'array' ? (
                  <Textarea
                    id={`workflow-param-${field}`}
                    value={normalizeValueForTextInput(value)}
                    onChange={(event) => setFieldValue(field, event.target.value)}
                    className="font-mono text-xs"
                    rows={4}
                  />
                ) : (
                  <Input
                    id={`workflow-param-${field}`}
                    type={property.type === 'number' || property.type === 'integer' ? 'number' : 'text'}
                    value={normalizeValueForTextInput(value)}
                    onChange={(event) => setFieldValue(field, event.target.value)}
                  />
                )}

                {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
                {error ? <div className="text-xs text-red-600">{error}</div> : null}
              </div>
            )
          })
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={handleOpenInCodingAgent} disabled={!recipeLaunchable}>
          <Code2 className="mr-2 h-4 w-4" />
          {MCP_RUN_ACTION_LABEL}
        </Button>
        <Button variant="outline" onClick={handleValidate} disabled={validateBusy || !recipeLaunchable}>
          {validateBusy ? 'Previewing recipe...' : MCP_RECIPE_ACTION_LABEL}
        </Button>
        <Button variant="outline" onClick={handleOpenInStudio} disabled={validateBusy}>
          Add to Studio plan
        </Button>
        <Button variant="outline" onClick={handleValidate} disabled={validateBusy}>
          {validateBusy ? 'Previewing checks...' : 'Preview checks'}
        </Button>
      </div>

      {validationSummary ? (
        <Alert>
          <AlertTitle>Checks preview</AlertTitle>
          <AlertDescription>{validationSummary}</AlertDescription>
        </Alert>
      ) : null}

      {guidanceCardVisible && guidance ? (
        <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-950/80 via-slate-900/80 to-slate-950/80 p-4 text-sm text-muted-foreground shadow-lg ring-1 ring-white/10">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-primary-300">
                {guidanceEyebrow}
              </p>
              <p className="text-base font-semibold text-white">
                {guidance.summary || guidanceFallbackSummary}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleValidate}
              disabled={!allowRecheck || validateBusy}
            >
              {validateBusy ? 'Re-checking …' : 'Re-check environment'}
            </Button>
          </div>

          <div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-2">
            {guidance.runtime_target ? (
              <div>
                <p className="font-semibold text-white">Runtime</p>
                <p>{guidance.runtime_target}</p>
              </div>
            ) : null}
            {guidance.install_path ? (
              <div>
                <p className="font-semibold text-white">Recommended path</p>
                <p>{guidance.install_path.replace('_', ' ')}</p>
              </div>
            ) : null}
            {guidance.required_modules?.length ? (
              <div>
                <p className="font-semibold text-white">Modules</p>
                <p className="text-xs">{guidance.required_modules.join(', ')}</p>
              </div>
            ) : null}
            {guidance.required_env_vars?.length ? (
              <div>
                <p className="font-semibold text-white">Env vars</p>
                <p className="text-xs">{guidance.required_env_vars.join(', ')}</p>
              </div>
            ) : null}
            {guidance.supported_recipe_targets?.length ? (
              <div>
                <p className="font-semibold text-white">Recipe targets</p>
                <p className="text-xs">{guidance.supported_recipe_targets.join(', ')}</p>
              </div>
            ) : null}
            {hasRecordEntries(guidance.container_images) ? (
              <div>
                <p className="font-semibold text-white">Container images</p>
                <p className="break-all text-xs">{Object.values(guidance.container_images).join(', ')}</p>
              </div>
            ) : null}
          </div>

          {localRunRationale ? (
            <div className="mt-3 rounded-md border border-white/10 bg-white/5 p-3 text-xs text-slate-100">
              {localRunRationale}
            </div>
          ) : null}

          {guidance.detail ? (
            <div className="mt-3 text-xs text-slate-200">{guidance.detail}</div>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            {(guidance.actions ?? []).map((action, index) => (
              <Button key={`${action.href || action.label || 'action'}-${index}`} asChild size="sm" variant="secondary">
                <a href={action.href || guidance.next_action_url || '#'} rel="noreferrer" target="_blank">
                  {guidanceActionLabel(action)}
                </a>
              </Button>
            ))}
            {guidance.next_action_url ? (
              <Button asChild size="sm">
                <a href={guidance.next_action_url} target="_blank" rel="noreferrer">
                  {guidancePrimaryActionLabel}
                </a>
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {validationChecks.length > 0 ? (
        <div className="rounded-md border bg-background p-3 space-y-2">
          <div className="text-sm font-medium">Runtime checks preview</div>
          {validationChecks.map((check, index) => {
            const tone = inferStatusTone(check)
            return (
              <div key={`${check.tool_id || 'tool'}-${index}`} className="text-xs text-muted-foreground">
                <Badge variant={tone === 'passed' ? 'default' : tone === 'blocked' ? 'destructive' : 'secondary'}>
                  {tone === 'passed' ? 'Passed' : tone === 'blocked' ? 'Blocked' : 'Warning'}
                </Badge>{' '}
                <span className="font-mono">{check.tool_id || 'unknown_tool'}</span>
                {check.status ? ` (${check.status})` : ''}
                {check.detail ? ` — ${check.detail}` : ''}
              </div>
            )
          })}
        </div>
      ) : null}

      {validationWarnings.length > 0 ? (
        <Alert>
          <AlertTitle>Warnings to review in Studio</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4 space-y-1">
              {validationWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}
