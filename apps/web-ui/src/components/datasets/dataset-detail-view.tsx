"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Code2, ExternalLink, FlaskConical, Layers, ListChecks, Loader2, Sparkles, Tags, Thermometer, Users } from "lucide-react"

import { ANALYSIS_TYPES, PipelineOption } from "@/config/analysis-presets"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { HandoffModal, type HandoffTemplatePayload } from "@/components/handoff/HandoffModal"
import { canonicalizeTemplateSelection } from "@/lib/workflow-template-aliases"
import { DatasetDetailResponse } from "@/types/datasets-search"

// Pipeline response from /api/pipelines
interface ApiPipelineStep {
  order: number
  tool: string
  description: string
  paramNames: string[]
}

interface ApiPipeline {
  id: string
  name: string
  description: string
  modalities: string[]
  steps: ApiPipelineStep[]
}

type PlanCheckStatus = "pending" | "passed" | "warning" | "blocked"

interface PlanCheck {
  id: string
  label: string
  status: PlanCheckStatus
  detail?: string
}

type LaunchDecision = {
  status?: "runnable" | "runnable_with_warning" | "blocked" | "handoff_only" | "manual_admin_only"
  code?: string
  can_launch?: boolean
  primary_action?: "launch" | "sign_in" | "grant_credits" | "handoff" | "fix_inputs"
  reason?: string
}

type WorkflowCapabilityContract = {
  canonical_workflow_id?: string | null
  mcp_recipe?: {
    status?: "available" | "unavailable" | "manual_admin_only"
    supported_targets?: string[]
    preferred_target?: string | null
    handoff_prompt?: string
  }
}

type PreflightGuidance = {
  kind?: string
  runtime_target?: string
  install_path?: string
  summary?: string
  detail?: string | null
  required_env_vars?: string[]
  container_images?: Record<string, string>
  supported_recipe_targets?: string[]
}

type LaunchablePipelineOption = PipelineOption & {
  apiSteps?: ApiPipelineStep[]
  launchAnalysisId?: string
  launchPipelineId?: string
  launchSource?: "static_preset" | "workflow_alias"
}

// Helper to infer analysis type from pipeline ID/name
function inferAnalysisType(id: string, name: string): string {
  const lowerName = (id + " " + name).toLowerCase()
  if (lowerName.includes("multiverse")) return "multiverse_glm"
  if (lowerName.includes("glm") || lowerName.includes("first_level")) return "glm"
  if (lowerName.includes("connectivity") || lowerName.includes("parcellation")) return "connectivity"
  if (lowerName.includes("prep") || lowerName.includes("qc") || lowerName.includes("mriqc")) return "preprocess"
  return "glm" // default fallback
}

type ValidationIssue = {
  id: string
  severity: "error" | "warning"
  title: string
  detail?: string
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function coerceStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((entry) => (typeof entry === "string" ? entry.trim() : "")).filter(Boolean)
}

function coerceCount(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (Array.isArray(value)) return value.length
  return null
}

function coercePreflightGuidance(value: unknown): PreflightGuidance | null {
  const record = safeRecord(value)
  if (!record) return null
  const containerImages = safeRecord(record.container_images)
  const normalizedImages: Record<string, string> = {}
  if (containerImages) {
    for (const [key, rawValue] of Object.entries(containerImages)) {
      if (typeof rawValue === "string" && rawValue.trim()) {
        normalizedImages[key] = rawValue.trim()
      }
    }
  }
  return {
    kind: typeof record.kind === "string" ? record.kind : undefined,
    runtime_target: typeof record.runtime_target === "string" ? record.runtime_target : undefined,
    install_path: typeof record.install_path === "string" ? record.install_path : undefined,
    summary: typeof record.summary === "string" ? record.summary : undefined,
    detail:
      typeof record.detail === "string"
        ? record.detail
        : record.detail === null
          ? null
          : undefined,
    required_env_vars: coerceStringList(record.required_env_vars),
    supported_recipe_targets: coerceStringList(record.supported_recipe_targets),
    container_images: Object.keys(normalizedImages).length ? normalizedImages : undefined,
  }
}

function sanitizeStudioReturnTo(raw: string | null): string | null {
  if (typeof raw !== "string") return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith("/studio")) return null
  try {
    const normalized = new URL(trimmed, "http://localhost")
    if (!normalized.pathname.startsWith("/studio")) return null
    return `${normalized.pathname}${normalized.search}`
  } catch {
    return null
  }
}

export function displaySizeHuman(value: unknown): string {
  if (typeof value !== "string") return "N/A"
  const trimmed = value.trim()
  if (!trimmed || /\bnan\b/i.test(trimmed) || /^n\/?a$/i.test(trimmed)) return "N/A"
  return trimmed
}

interface DatasetDetailViewProps {
  dataset: DatasetDetailResponse
}

export function DatasetDetailView({ dataset }: DatasetDetailViewProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [analysisDialogOpen, setAnalysisDialogOpen] = useState(false)
  const [selectedAnalysis, setSelectedAnalysis] = useState<string | null>(null)
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  // Multiverse-specific params
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [maxModels, setMaxModels] = useState(3)
  // Dynamic pipelines from API
  const [apiPipelines, setApiPipelines] = useState<ApiPipeline[]>([])
  const [pipelinesLoading, setPipelinesLoading] = useState(false)
  const [preflightLoading, setPreflightLoading] = useState(false)
  const [preflightChecks, setPreflightChecks] = useState<PlanCheck[]>([])
  const [preflightError, setPreflightError] = useState<string | null>(null)
  const [preflightHandoffPack, setPreflightHandoffPack] = useState<Record<string, unknown> | null>(null)
  const [preflightGuidance, setPreflightGuidance] = useState<PreflightGuidance | null>(null)
  const [launchDecision, setLaunchDecision] = useState<LaunchDecision | null>(null)
  const [workflowCapability, setWorkflowCapability] = useState<WorkflowCapabilityContract | null>(null)
  const [activeTab, setActiveTab] = useState("overview")
  const [handoffOpen, setHandoffOpen] = useState(false)
  const [handoffTemplatePayload, setHandoffTemplatePayload] = useState<HandoffTemplatePayload | null>(null)
  const [quality, setQuality] = useState<unknown | null>(null)
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityError, setQualityError] = useState<string | null>(null)

  // Fetch pipelines from API when dialog opens
  useEffect(() => {
    if (analysisDialogOpen && apiPipelines.length === 0) {
      setPipelinesLoading(true)
      fetch("/api/pipelines")
        .then((res) => res.json())
        .then((data: { pipelines?: ApiPipeline[] }) => {
          setApiPipelines(data.pipelines || [])
        })
        .catch((err) => {
          console.error("Failed to fetch pipelines:", err)
        })
        .finally(() => {
          setPipelinesLoading(false)
      })
    }
  }, [analysisDialogOpen, apiPipelines.length])

  const fetchQuality = useCallback(async () => {
    if (!dataset.id) return
    setQualityLoading(true)
    setQualityError(null)
    try {
      const res = await fetch(`/api/datasets/${encodeURIComponent(dataset.id)}/quality`, {
        cache: "no-store",
      })
      if (!res.ok) {
        const text = await res.text().catch(() => "")
        throw new Error(text || `Failed to load validation (${res.status})`)
      }
      const json = await res.json().catch(() => null)
      setQuality(json)
    } catch (err) {
      setQuality(null)
      setQualityError(err instanceof Error ? err.message : String(err))
    } finally {
      setQualityLoading(false)
    }
  }, [dataset.id])

  useEffect(() => {
    setQuality(null)
    setQualityError(null)
    setQualityLoading(false)
  }, [dataset.id])

  useEffect(() => {
    if (activeTab !== "validation") return
    if (qualityLoading) return
    if (quality) return
    void fetchQuality()
  }, [activeTab, fetchQuality, quality, qualityLoading])

  // Normalize human-readable task labels ("balloon analog risk task") to BIDS-style identifiers
  // expected by the backend/pipeline ("balloonanalogrisktask").
  const normalizeTaskLabel = (task: string) => task.trim().toLowerCase().replace(/[^a-z0-9]+/g, "")
  const qualitySummary = useMemo(() => {
    const record = safeRecord(quality)
    const bids = record ? safeRecord(record["bids_validation"]) : null
    const valid = bids && typeof bids["valid"] === "boolean" ? (bids["valid"] as boolean) : null
    const warnings = bids ? coerceCount(bids["warnings"]) : null
    const errors = bids ? coerceCount(bids["errors"]) : null
    const score = record && typeof record["score"] === "number" && Number.isFinite(record["score"])
      ? (record["score"] as number)
      : null
    return { valid, warnings, errors, score }
  }, [quality])

  const resourceAddresses = dataset.resource_addresses
  const datasetVersionOptions = useMemo(
    () =>
      Array.isArray(resourceAddresses?.versions)
        ? resourceAddresses.versions.filter(
            (option): option is NonNullable<typeof resourceAddresses.versions>[number] =>
              Boolean(option && typeof option.id === "string" && option.id.trim()),
          )
        : [],
    [resourceAddresses?.versions],
  )
  const defaultDatasetVersion = useMemo(() => {
    const fromResources =
      typeof resourceAddresses?.default_version === "string" &&
      resourceAddresses.default_version.trim()
        ? resourceAddresses.default_version.trim()
        : null
    if (fromResources) return fromResources
    const recommended = datasetVersionOptions.find((option) => option.recommended)
    if (recommended?.id) return recommended.id
    return datasetVersionOptions[0]?.id || null
  }, [datasetVersionOptions, resourceAddresses?.default_version])
  const safeReturnTo = useMemo(
    () => sanitizeStudioReturnTo(searchParams?.get("returnTo") ?? null),
    [searchParams],
  )
  const buildStudioPlanHref = useCallback(
    (datasetVersion: string | null) => {
      const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin
      const base = safeReturnTo || "/studio?tab=plan"
      try {
        const url = new URL(base, origin)
        url.searchParams.set("datasetId", dataset.id)
        url.searchParams.delete("dataset")
        url.searchParams.set("tab", "plan")
        if (datasetVersion) {
          url.searchParams.set("datasetVersion", datasetVersion)
          url.searchParams.delete("dataset_version")
        }
        return `${url.pathname}?${url.searchParams.toString()}`
      } catch {
        const suffix = datasetVersion
          ? `&datasetVersion=${encodeURIComponent(datasetVersion)}`
          : ""
        return `/studio?tab=plan&datasetId=${encodeURIComponent(dataset.id)}${suffix}`
      }
    },
    [dataset.id, safeReturnTo],
  )
  const planHref = useMemo(
    () => buildStudioPlanHref(defaultDatasetVersion),
    [buildStudioPlanHref, defaultDatasetVersion],
  )
  const resourceReadinessStatus = (resourceAddresses?.readiness?.status || "").toLowerCase()
  const resourceReadinessVariant =
    resourceReadinessStatus === "ready" || resourceReadinessStatus === "healed"
      ? "default"
      : resourceReadinessStatus === "blocked"
        ? "destructive"
        : "secondary"
  const bucketCheckState = resourceAddresses?.source_access?.bucket_check?.state || null
  const bucketCheckMethod = resourceAddresses?.source_access?.bucket_check?.method || null
  const bucketCheckMessage = resourceAddresses?.source_access?.bucket_check?.message || null
  const versionCheckMode = resourceAddresses?.source_access?.version_check?.mode || null
  const resolvedSourceVersion =
    resourceAddresses?.source_access?.version_check?.resolved || null
  const sourceAvailableVersions = Array.isArray(resourceAddresses?.source_access?.available_versions)
    ? resourceAddresses.source_access.available_versions
    : []
  const resourceStatusCopy = useMemo(() => {
    if (!resourceAddresses) return null
    const status = (resourceAddresses.readiness?.status || "").trim().toLowerCase()
    const reason = resourceAddresses.readiness?.reason?.trim()
    const localMounted = Boolean(
      resourceAddresses.exists_summary?.local_bids_available ||
        resourceAddresses.storage_summary?.bids_path_available,
    )

    if (status === "auth_required") {
      return {
        label: "Sign in required",
        detail: reason || "Sign in to verify mounts, file readiness, and backend access.",
      }
    }

    if (status === "degraded") {
      return {
        label: "Degraded",
        detail: reason || "Runtime checks did not complete; static source address hints are available.",
      }
    }

    if (localMounted) {
      return {
        label: "Mounted",
        detail: reason || "A local BIDS path is available for authenticated runtime checks.",
      }
    }

    if (status === "ready" || status === "healed") {
      return {
        label: status === "healed" ? "Ready after repair" : "Ready",
        detail: reason || "Backend readiness checks passed.",
      }
    }

    if (bucketCheckState === "verified_present") {
      return {
        label: "Source verified",
        detail: bucketCheckMessage || "The source bucket was reachable, but no local mount was reported.",
      }
    }

    if (bucketCheckState === "permission_denied") {
      return {
        label: "Access restricted",
        detail: bucketCheckMessage || "The source exists, but credentials or approval are required.",
      }
    }

    if (status === "blocked") {
      return {
        label: "Blocked",
        detail: reason || bucketCheckMessage || "Readiness checks reported a blocker.",
      }
    }

    return {
      label: "Status unknown",
      detail: reason || bucketCheckMessage || "Only catalog metadata is available for this dataset.",
    }
  }, [bucketCheckMessage, bucketCheckState, resourceAddresses])
  const resourceTraceSummary = resourceAddresses?.trace_summary ?? []
  const resourceRequiredFiles = resourceAddresses?.required_files
  const nonOpenNeuroRepoUrl = resourceAddresses?.addresses.source_repo_url || dataset.primary_url

  const validationIssues = useMemo(() => {
    const issues: ValidationIssue[] = []
    const record = safeRecord(quality)
    if (!record) return issues

    const bids = safeRecord(record["bids_validation"])
    const bidsValid = bids && typeof bids["valid"] === "boolean" ? (bids["valid"] as boolean) : null
    const bidsErrorsRaw = bids ? bids["errors"] : null
    const bidsWarningsRaw = bids ? bids["warnings"] : null

    if (Array.isArray(bidsErrorsRaw)) {
      bidsErrorsRaw.forEach((entry, idx) => {
        const obj = safeRecord(entry)
        const message =
          typeof entry === "string"
            ? entry
            : typeof obj?.message === "string"
              ? obj.message
              : JSON.stringify(entry)
        issues.push({
          id: `bids_error_${idx + 1}`,
          severity: "error",
          title: "BIDS validation error",
          detail: message,
        })
      })
    } else {
      const count = coerceCount(bidsErrorsRaw)
      if (count && count > 0) {
        issues.push({
          id: "bids_errors",
          severity: "error",
          title: `BIDS validation reported ${count} error${count === 1 ? "" : "s"}`,
        })
      } else if (bidsValid === false) {
        issues.push({
          id: "bids_invalid",
          severity: "error",
          title: "BIDS validation reported invalid dataset",
        })
      }
    }

    if (Array.isArray(bidsWarningsRaw)) {
      bidsWarningsRaw.forEach((entry, idx) => {
        const obj = safeRecord(entry)
        const message =
          typeof entry === "string"
            ? entry
            : typeof obj?.message === "string"
              ? obj.message
              : JSON.stringify(entry)
        issues.push({
          id: `bids_warning_${idx + 1}`,
          severity: "warning",
          title: "BIDS validation warning",
          detail: message,
        })
      })
    } else {
      const count = coerceCount(bidsWarningsRaw)
      if (count && count > 0) {
        issues.push({
          id: "bids_warnings",
          severity: "warning",
          title: `BIDS validation reported ${count} warning${count === 1 ? "" : "s"}`,
        })
      }
    }

    const completeness = safeRecord(record["completeness"])
    const missingFiles = coerceStringList(completeness?.["missing_files"])
    const missingMetadata = coerceStringList(completeness?.["missing_metadata"])
    missingFiles.forEach((value, idx) => {
      issues.push({
        id: `missing_file_${idx + 1}`,
        severity: "error",
        title: "Missing required file",
        detail: value,
      })
    })
    missingMetadata.forEach((value, idx) => {
      issues.push({
        id: `missing_metadata_${idx + 1}`,
        severity: "warning",
        title: "Missing metadata",
        detail: value,
      })
    })

    const consistency = safeRecord(record["consistency"])
    const naming = typeof consistency?.["naming_convention"] === "string" ? (consistency["naming_convention"] as string) : ""
    if (naming && naming.toLowerCase() !== "consistent") {
      issues.push({
        id: "naming_convention",
        severity: "warning",
        title: "Naming convention not consistent",
        detail: naming,
      })
    }
    const fileFormat = typeof consistency?.["file_format"] === "string" ? (consistency["file_format"] as string) : ""
    if (fileFormat && fileFormat.toLowerCase() !== "valid") {
      issues.push({
        id: "file_format",
        severity: "warning",
        title: "File format not valid",
        detail: fileFormat,
      })
    }

    return issues
  }, [quality])

  const buildValidationPrompt = useCallback(
    (issue: ValidationIssue) => {
      return [
        `I want to fix a dataset validation issue.`,
        `Dataset: ${dataset.name} (id: ${dataset.id}, source: ${dataset.source_repo})`,
        dataset.primary_url ? `URL: ${dataset.primary_url}` : "",
        "",
        `Issue (${issue.severity}): ${issue.title}`,
        issue.detail ? `Details: ${issue.detail}` : "",
        "",
        "Please:",
        "- Explain what this means in BIDS terms.",
        "- Suggest how to fix it (or a safe workaround).",
        "- Tell me what to do next in Brain Researcher (Plan/Checks/Run).",
      ]
        .filter(Boolean)
        .join("\n")
    },
    [dataset],
  )

  const stats = useMemo(
    () => [
      {
        label: "Participants",
        icon: Users,
        value: dataset.subjects_count != null ? dataset.subjects_count.toLocaleString() : "—",
      },
      {
        label: "Sessions",
        icon: Layers,
        value: dataset.sessions_count != null ? dataset.sessions_count.toLocaleString() : "—",
      },
      {
        label: "Modalities",
        icon: Thermometer,
        value: dataset.modalities.length ? dataset.modalities.join(", ") : "N/A",
      },
      {
        label: "Access",
        icon: Sparkles,
        value: dataset.access_type,
      },
    ],
    [dataset],
  )

  const datasetModalitySet = useMemo(() => new Set(dataset.modalities.map((mod) => mod.toLowerCase())), [dataset.modalities])
  const subjectLabels = useMemo(() => dataset.subject_labels ?? [], [dataset.subject_labels])
  const phenotypeSummary = useMemo(
    () =>
      [...(dataset.phenotype_summary ?? [])].sort(
        (a, b) => (b.total_observations ?? 0) - (a.total_observations ?? 0),
      ),
    [dataset.phenotype_summary],
  )
  const hasNeurobagelAnnotations = subjectLabels.length > 0 || phenotypeSummary.length > 0
  const renderNeurobagelAnnotations = (options?: {
    maxLabels?: number
    maxPhenotypes?: number
    cardClassName?: string
  }) => {
    if (!hasNeurobagelAnnotations) return null
    const maxLabels = options?.maxLabels ?? 24
    const maxPhenotypes = options?.maxPhenotypes ?? 12

    return (
      <div className={cn("rounded-xl border bg-card p-5 shadow-sm", options?.cardClassName)}>
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">Neurobagel cohort annotations</p>
          {(dataset.annotation_sources?.length || dataset.annotation_updated_at) && (
            <p className="text-xs text-muted-foreground">
              {dataset.annotation_sources?.length
                ? `Sources: ${dataset.annotation_sources.join(", ")}`
                : "Source: catalog annotations"}
              {dataset.annotation_updated_at
                ? ` • Updated ${new Date(dataset.annotation_updated_at).toLocaleDateString()}`
                : ""}
            </p>
          )}
        </div>
        {subjectLabels.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {subjectLabels.slice(0, maxLabels).map((label) => (
              <Badge key={label} variant="outline" className="text-xs">
                {label}
              </Badge>
            ))}
            {subjectLabels.length > maxLabels && (
              <Badge variant="secondary" className="text-xs">
                +{subjectLabels.length - maxLabels} more
              </Badge>
            )}
          </div>
        )}
        {phenotypeSummary.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border">
            <table className="min-w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Phenotype</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Unique subjects</th>
                  <th className="px-3 py-2">Observations (rows)</th>
                </tr>
              </thead>
              <tbody>
                {phenotypeSummary.slice(0, maxPhenotypes).map((item) => (
                  <tr key={item.column ?? item.name} className="border-t">
                    <td className="px-3 py-2 font-medium text-foreground">{item.name}</td>
                    <td className="px-3 py-2 text-muted-foreground">{item.category || "phenotype"}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {typeof item.unique_subjects === "number"
                        ? item.unique_subjects.toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {(item.total_observations ?? 0).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {phenotypeSummary.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Unique subjects are participant-level counts when participant identifiers are available; observations are row-level and can exceed participants for multi-session or repeated records.
          </p>
        )}
      </div>
    )
  }
  const analysisOptions = useMemo(
    () =>
      ANALYSIS_TYPES.map((type) => ({
        ...type,
        supported: type.modalities.length === 0 || type.modalities.some((mod) => datasetModalitySet.has(mod)),
      })),
    [datasetModalitySet],
  )
  const selectedAnalysisConfig = analysisOptions.find((option) => option.id === selectedAnalysis)

  // Merge static pipeline presets with dynamic API data
  // API pipelines override/enhance static ones by ID match
  const pipelineOptions = useMemo(() => {
    if (!selectedAnalysisConfig) return []

    // Build a map of API pipelines by ID for quick lookup
    const apiPipelineMap = new Map(apiPipelines.map((p) => [p.id, p]))

    // Enhance static pipelines with API data where available
    const mergedPipelines: LaunchablePipelineOption[] = selectedAnalysisConfig.pipelines
      .filter((pipeline) =>
        pipeline.modalities.length === 0 || pipeline.modalities.some((mod) => datasetModalitySet.has(mod)),
      )
      .map((pipeline) => {
        const apiPipeline = apiPipelineMap.get(pipeline.id)
        if (apiPipeline) {
          // Enhance with API data (description, steps)
          return {
            ...pipeline,
            description: apiPipeline.description || pipeline.description,
            apiSteps: apiPipeline.steps,
            launchSource: "static_preset",
          }
        }
        return { ...pipeline, launchSource: "static_preset" }
      })

    // Also add any API pipelines that match the selected analysis type but aren't in static presets
    // Filter by modality compatibility with dataset
    for (const apiPipeline of apiPipelines) {
      const alreadyExists = mergedPipelines.some((p) => p.id === apiPipeline.id)
      if (alreadyExists) continue

      // Check if modalities are compatible
      const modalityMatch =
        apiPipeline.modalities.length === 0 ||
        apiPipeline.modalities.some((mod) => datasetModalitySet.has(mod.toLowerCase()))
      if (!modalityMatch) continue

      // Infer analysis type from pipeline ID or name
      const pipelineType = inferAnalysisType(apiPipeline.id, apiPipeline.name)
      if (pipelineType !== selectedAnalysisConfig.id) continue

      const launchSelection = canonicalizeTemplateSelection({
        analysisId: pipelineType,
        pipelineId: apiPipeline.id,
      })
      if (launchSelection.analysisId !== "dynamic_workflow") continue

      // Add as a dynamic pipeline
      mergedPipelines.push({
        id: apiPipeline.id,
        label: apiPipeline.name,
        description: apiPipeline.description,
        modalities: apiPipeline.modalities,
        estRuntime: "varies",
        runConfig: {
          pipelineType: pipelineType as "preprocessing" | "glm" | "connectivity" | "multiverse",
          tool: launchSelection.pipelineId,
        },
        apiSteps: apiPipeline.steps,
        launchAnalysisId: launchSelection.analysisId,
        launchPipelineId: launchSelection.pipelineId,
        launchSource: "workflow_alias",
      })
    }

    return mergedPipelines
  }, [datasetModalitySet, selectedAnalysisConfig, apiPipelines])

  const selectedPipelineConfig = pipelineOptions.find((pipeline) => pipeline.id === selectedPipeline)
  const launchAnalysisId =
    selectedPipelineConfig?.launchAnalysisId ?? selectedAnalysisConfig?.id ?? null
  const launchPipelineId =
    selectedPipelineConfig?.launchPipelineId ?? selectedPipelineConfig?.id ?? null
  const preflightBlocked = launchDecision
    ? launchDecision.can_launch === false
    : preflightChecks.some((check) => check.status === "blocked")
  const preflightGuidanceKind = preflightGuidance?.kind?.toLowerCase() ?? ""
  const preflightGuidanceIsHandoff =
    preflightGuidanceKind.includes("handoff") ||
    preflightGuidanceKind.includes("recipe") ||
    Boolean(preflightGuidance?.supported_recipe_targets?.length)
  const capabilityRecipeAvailable = workflowCapability?.mcp_recipe?.status === "available"
  const handoffIsPrimary =
    launchDecision?.primary_action === "handoff" ||
    (preflightBlocked && capabilityRecipeAvailable) ||
    preflightGuidanceIsHandoff
  const hostedBlockedRecipeAvailable =
    launchDecision?.can_launch === false &&
    launchDecision.primary_action === "handoff" &&
    capabilityRecipeAvailable
  const launchDecisionLabel = hostedBlockedRecipeAvailable
    ? "Hosted blocked, MCP recipe still available"
    : launchDecision?.can_launch === false
      ? "Launch unavailable"
      : launchDecision?.status === "runnable_with_warning"
        ? "Launch allowed with warning"
        : "Launch ready"
  const preflightGuidanceTitle = preflightGuidanceIsHandoff
    ? "Get MCP recipe for local execution"
    : preflightGuidance?.runtime_target === "neurodesk"
      ? "Set up Neurodesk runtime"
      : "Runtime setup required"
  const preflightContainerImages = preflightGuidance?.container_images
    ? Object.values(preflightGuidance.container_images)
    : []
  const launchParameters = useMemo(
    () =>
      selectedAnalysis === "multiverse_glm"
        ? { task: selectedTask, max_models: maxModels }
        : {},
    [maxModels, selectedAnalysis, selectedTask],
  )
  useEffect(() => {
    if (!analysisDialogOpen || !launchAnalysisId || !launchPipelineId) {
      setPreflightLoading(false)
      setPreflightChecks([])
      setPreflightError(null)
      setPreflightHandoffPack(null)
      setPreflightGuidance(null)
      setLaunchDecision(null)
      setWorkflowCapability(null)
      return
    }

    const controller = new AbortController()
    setPreflightLoading(true)
    setPreflightChecks([])
    setPreflightError(null)
    setPreflightHandoffPack(null)
    setPreflightGuidance(null)
    setLaunchDecision(null)
    setWorkflowCapability(null)

    fetch("/api/plan/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        dataset_id: dataset.id,
        analysis_id: launchAnalysisId,
        pipeline_id: launchPipelineId,
        parameters: launchParameters,
      }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null)
        if (!response.ok) {
          const detail =
            payload && typeof payload.detail === "string"
              ? payload.detail
              : "Launch checks failed."
          throw new Error(detail)
        }
        const checks = Array.isArray(payload?.checks) ? payload.checks : []
        setPreflightChecks(
          checks.filter((check: unknown): check is PlanCheck => {
            const record = safeRecord(check)
            const status = typeof record?.status === "string" ? record.status : ""
            return ["pending", "passed", "warning", "blocked"].includes(status)
          }),
        )
        setPreflightHandoffPack(safeRecord(payload?.handoff_pack))
        setPreflightGuidance(coercePreflightGuidance(payload?.guidance))
        const decision = safeRecord(payload?.launch_decision)
        setLaunchDecision(decision ? (decision as LaunchDecision) : null)
        const capability = safeRecord(payload?.capability)
        setWorkflowCapability(capability ? (capability as WorkflowCapabilityContract) : null)
      })
      .catch((error) => {
        if (controller.signal.aborted) return
        setPreflightError(error instanceof Error ? error.message : "Launch checks failed.")
        setPreflightGuidance(null)
        setLaunchDecision(null)
        setWorkflowCapability(null)
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreflightLoading(false)
      })

    return () => controller.abort()
  }, [
    analysisDialogOpen,
    dataset.id,
    launchAnalysisId,
    launchParameters,
    launchPipelineId,
  ])

  const handleLaunchAnalysis = () => {
    setAnalysisError(null)
    setAnalysisDialogOpen(true)
  }

  const resetAnalysisDialogState = () => {
    setSelectedAnalysis(null)
    setSelectedPipeline(null)
    setAnalysisError(null)
    setIsSubmitting(false)
    setSelectedTask(null)
    setMaxModels(3)
    setPreflightLoading(false)
    setPreflightChecks([])
    setPreflightError(null)
    setPreflightHandoffPack(null)
    setPreflightGuidance(null)
    setLaunchDecision(null)
    setWorkflowCapability(null)
  }

  const handleDialogOpenChange = (open: boolean) => {
    setAnalysisDialogOpen(open)
    if (!open) {
      resetAnalysisDialogState()
    }
  }

  const currentHandoffPayload: HandoffTemplatePayload = handoffTemplatePayload ?? {
    kind: 'template',
    workflowId: workflowCapability?.canonical_workflow_id || launchPipelineId || selectedPipeline || '<workflow_id>',
    workflowLabel: selectedPipelineConfig?.label || launchPipelineId || selectedPipeline,
    datasetId: dataset.id,
    datasetVersion: defaultDatasetVersion,
    targetRuntime: workflowCapability?.mcp_recipe?.preferred_target ?? null,
    supportedTargets: workflowCapability?.mcp_recipe?.supported_targets ?? null,
    promptOverride: workflowCapability?.mcp_recipe?.handoff_prompt ?? null,
    unresolvedInputs:
      !launchPipelineId && !selectedPipeline && !workflowCapability?.canonical_workflow_id
        ? ['workflow_id']
        : [],
  }

  const openDatasetHandoff = () => {
    setHandoffTemplatePayload(null)
    setHandoffOpen(true)
  }

  const openSelectedWorkflowHandoff = () => {
    const recipeLookup = preflightHandoffPack
      ? safeRecord(preflightHandoffPack["recipe_lookup"])
      : null
    const recipeParams = safeRecord(recipeLookup?.params)
    setHandoffTemplatePayload({
      ...currentHandoffPayload,
      params: recipeParams ?? launchParameters,
    })
    setAnalysisDialogOpen(false)
    resetAnalysisDialogState()
    setHandoffOpen(true)
  }

  const handleConfirmAnalysis = async () => {
    if (
      !selectedAnalysisConfig ||
      !selectedPipelineConfig ||
      !launchAnalysisId ||
      !launchPipelineId ||
      isSubmitting ||
      preflightBlocked
    ) {
      return
    }

    // For multiverse, require task selection if tasks are available
    if (selectedAnalysis === "multiverse_glm" && dataset.tasks?.length && !selectedTask) {
      setAnalysisError("Please select a task for multiverse analysis.")
      return
    }

    try {
      setIsSubmitting(true)
      setAnalysisError(null)

      // Build params, adding multiverse-specific ones if applicable
      const response = await fetch("/api/analyses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          dataset_id: dataset.id,
          analysis_id: launchAnalysisId,
          pipeline_id: launchPipelineId,
          parameters: launchParameters,
        }),
      })

      if (!response.ok) {
        let message = "Failed to start analysis."
        try {
          const errorBody = await response.json()
          if (errorBody && typeof errorBody.detail === "string") {
            message = errorBody.detail
          }
        } catch (error) {
          console.error("Unable to parse run error", error)
        }
        setAnalysisError(message)
        return
      }

      const data: { analysis_id?: string; run_id?: string; job_id?: string } = await response.json()
      const analysisId = data.analysis_id || data.run_id || data.job_id
      if (!analysisId) {
        setAnalysisError("Run created but missing identifier. Please check Runs.")
        return
      }

      setAnalysisDialogOpen(false)
      setSelectedAnalysis(null)
      setSelectedPipeline(null)
      router.push(`/analyses/${analysisId}`)
    } catch (error) {
      console.error("Failed to start analysis", error)
      setAnalysisError("Failed to start analysis. Please try again.")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[320px,minmax(0,1fr)]">
      <aside className="space-y-6 rounded-2xl border bg-card p-6 shadow-sm">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary" className="w-fit">
              {dataset.source_repo}
            </Badge>
            {dataset.onvoc?.labels?.length ? (
              <Badge variant="outline" className="flex items-center gap-1 text-xs font-medium">
                <Sparkles className="h-4 w-4 text-amber-500" />
                {dataset.onvoc.labels[0]}
                {dataset.onvoc.labels.length > 1 ? ` (+${dataset.onvoc.labels.length - 1})` : ''}
              </Badge>
            ) : null}
          </div>
          <h1 className="text-2xl font-semibold leading-tight">{dataset.name}</h1>
          <p className="text-sm text-muted-foreground">
            {dataset.description || "No description available."}
          </p>
        </div>
        <div className="flex flex-col gap-3">
          <Button onClick={openDatasetHandoff}>
            <Code2 className="mr-2 h-4 w-4" />
            Hand off
          </Button>
          <Button variant="outline" asChild>
            <Link href={planHref}>Open in Studio</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={dataset.primary_url} target="_blank" rel="noreferrer">
              Open dataset
              <ExternalLink className="ml-2 h-4 w-4" />
            </Link>
          </Button>
          <Button variant="ghost" onClick={handleLaunchAnalysis}>
            Run analysis
            <FlaskConical className="ml-2 h-4 w-4" />
          </Button>
        </div>
        <Separator />
        <div className="space-y-4">
          {stats.map((stat) => (
            <div key={stat.label} className="flex items-start gap-3">
              <stat.icon className="mt-1 h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
                <p className="text-sm font-medium">{stat.value}</p>
              </div>
            </div>
          ))}
        </div>
        <Separator />
        <div className="space-y-2 text-sm text-muted-foreground">
          <div>
            <span className="font-medium text-foreground">License:</span> {dataset.license}
          </div>
          <div>
            <span className="font-medium text-foreground">Category:</span> {dataset.category ?? "N/A"}
          </div>
          <div>
            <span className="font-medium text-foreground">Center:</span> {dataset.center ?? "N/A"}
          </div>
          <div>
            <span className="font-medium text-foreground">Consortium:</span> {dataset.consortium ?? "N/A"}
          </div>
        </div>
        {resourceAddresses ? (
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source addresses</p>
            <div className="space-y-2 rounded-xl border bg-muted/20 p-3 text-sm text-muted-foreground">
              {resourceAddresses.unavailable ? (
                <p>
                  Address resolution unavailable
                  {resourceAddresses.error ? `: ${resourceAddresses.error}` : "."}
                </p>
              ) : null}
              {resourceAddresses.source_kind === "openneuro" ? (
                <>
                  {resourceAddresses.addresses.openneuro_url ? (
                    <div>
                      <span className="font-medium text-foreground">OpenNeuro:</span>{" "}
                      <a
                        className="text-primary hover:underline"
                        href={resourceAddresses.addresses.openneuro_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {resourceAddresses.addresses.openneuro_url}
                      </a>
                    </div>
                  ) : null}
                  {resourceAddresses.addresses.s3_uri ? (
                    <div>
                      <span className="font-medium text-foreground">AWS S3:</span>{" "}
                      <code className="rounded bg-background px-1 py-0.5 text-xs">
                        {resourceAddresses.addresses.s3_uri}
                      </code>
                    </div>
                  ) : null}
                </>
              ) : (
                <div>
                  <span className="font-medium text-foreground">Source repository:</span>{" "}
                  {nonOpenNeuroRepoUrl ? (
                    <a className="text-primary hover:underline" href={nonOpenNeuroRepoUrl} target="_blank" rel="noreferrer">
                      {nonOpenNeuroRepoUrl}
                    </a>
                  ) : (
                    "N/A"
                  )}
                </div>
              )}
              {resourceAddresses.readiness?.status ? (
                <div className="pt-1">
                  <Badge variant={resourceReadinessVariant}>
                    Resource status: {resourceStatusCopy?.label ?? resourceAddresses.readiness.status}
                  </Badge>
                  {resourceStatusCopy?.detail ? (
                    <p className="mt-1 text-xs text-muted-foreground">{resourceStatusCopy.detail}</p>
                  ) : null}
                </div>
              ) : null}
              {bucketCheckState ? (
                <div className="text-xs">
                  <span className="font-medium text-foreground">Bucket check:</span>{" "}
                  {bucketCheckState}
                  {bucketCheckMethod ? ` via ${bucketCheckMethod}` : ""}
                  {bucketCheckMessage ? ` · ${bucketCheckMessage}` : ""}
                </div>
              ) : null}
              {versionCheckMode ? (
                <div className="text-xs">
                  <span className="font-medium text-foreground">Version verification:</span>{" "}
                  {versionCheckMode}
                  {resolvedSourceVersion ? ` · resolved ${resolvedSourceVersion}` : ""}
                </div>
              ) : null}
              {datasetVersionOptions.length ? (
                <div className="pt-1">
                  <div className="font-medium text-foreground">Available versions</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {datasetVersionOptions.map((option) => (
                      <Badge
                        key={option.id}
                        variant={option.id === defaultDatasetVersion ? "default" : "outline"}
                        className="text-[10px]"
                      >
                        {option.label}
                        {option.availability === "available" ? " · verified" : ""}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
              {sourceAvailableVersions.length ? (
                <div className="pt-1">
                  <div className="font-medium text-foreground">Source-reported versions</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {sourceAvailableVersions.map((option) => (
                      <Badge
                        key={`source-${option.id}`}
                        variant={option.state === "verified" ? "default" : "outline"}
                        className="text-[10px]"
                      >
                        {option.label}
                        {option.state === "verified" ? " · verified" : " · metadata"}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
        {dataset.tags.length > 0 && (
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Tags</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {dataset.tags.map((tag) => (
                <Badge key={tag} variant="outline" className="text-xs">
                  {tag}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </aside>
      <section className="space-y-6">
        <Tabs defaultValue="overview" onValueChange={setActiveTab} className="w-full">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="tasks">Tasks & Conditions</TabsTrigger>
            <TabsTrigger value="acquisition">Acquisition & Modalities</TabsTrigger>
            <TabsTrigger value="access">Files & Access</TabsTrigger>
            <TabsTrigger value="validation">Validation</TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="mt-4 space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h2 className="text-lg font-semibold">Summary</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {dataset.description || "No additional summary provided."}
              </p>
            </div>
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold">Key metadata</h3>
              <dl className="mt-3 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
                <div>
                  <dt className="font-medium text-foreground">Repository ID</dt>
                  <dd>{dataset.source_repo_id ?? "N/A"}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Has derivatives</dt>
                  <dd>{dataset.has_derivatives ? "Yes" : "Not specified"}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Species</dt>
                  <dd>{dataset.species.join(", ")}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Diseases / conditions</dt>
                  <dd>{dataset.disease_flags.length ? dataset.disease_flags.join(", ") : "N/A"}</dd>
                </div>
              </dl>
            </div>
          </TabsContent>
          <TabsContent value="tasks" className="mt-4 space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold flex items-center gap-2">
                <ListChecks className="h-4 w-4" /> Task paradigms
              </h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {dataset.tasks.length ? (
                  dataset.tasks.map((task) => (
                    <Badge key={task} variant="outline">
                      {task}
                    </Badge>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">Not specified</p>
                )}
              </div>
            </div>
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Tags className="h-4 w-4" /> Populations & conditions
              </h3>
              <dl className="mt-3 grid gap-4 text-sm text-muted-foreground sm:grid-cols-2">
                <div>
                  <dt className="font-medium text-foreground">Species</dt>
                  <dd>{dataset.species.join(", ")}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Disease flags</dt>
                  <dd>{dataset.disease_flags.length ? dataset.disease_flags.join(", ") : "N/A"}</dd>
                </div>
                {dataset.age_range && (
                  <div>
                    <dt className="font-medium text-foreground">Age range</dt>
                    <dd>
                      {dataset.age_range.min}–{dataset.age_range.max} {dataset.age_range.units}
                    </dd>
                  </div>
                )}
              </dl>
              {hasNeurobagelAnnotations && (
                <div className="mt-4 space-y-3">
                  <Separator />
                  {renderNeurobagelAnnotations({ cardClassName: "p-0 border-0 shadow-none" })}
                </div>
              )}
            </div>
          </TabsContent>
          <TabsContent value="acquisition" className="mt-4 space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold">Modalities</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {dataset.modalities.length ? (
                  dataset.modalities.map((modality) => (
                    <Badge key={modality} variant="secondary">
                      {modality}
                    </Badge>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">Not specified</span>
                )}
              </div>
            </div>
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold">Acquisition notes</h3>
              <p className="text-sm text-muted-foreground">
                {dataset.acquisitions.length ? dataset.acquisitions.join(", ") : "No acquisition metadata provided."}
              </p>
            </div>
          </TabsContent>
          <TabsContent value="access" className="mt-4 space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold">Files & repository links</h3>
              <dl className="mt-3 space-y-2 text-sm text-muted-foreground">
                <div>
                  <dt className="font-medium text-foreground">Primary URL</dt>
                  <dd>
                    <a className="text-primary hover:underline" href={dataset.primary_url} target="_blank" rel="noreferrer">
                      {dataset.primary_url}
                    </a>
                  </dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Repository</dt>
                  <dd>{dataset.source_repo}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">License</dt>
                  <dd>{dataset.license}</dd>
                </div>
                {datasetVersionOptions.length ? (
                  <div>
                    <dt className="font-medium text-foreground">Version options</dt>
                    <dd className="mt-2 flex flex-wrap gap-2">
                      {datasetVersionOptions.map((option) => {
                        const href = buildStudioPlanHref(option.id)
                        return (
                          <Link
                            key={option.id}
                            href={href}
                            className={cn(
                              "rounded-md border px-2 py-1 text-xs hover:bg-muted",
                              option.id === defaultDatasetVersion && "border-primary text-primary",
                            )}
                          >
                            {option.label}
                            {option.id === defaultDatasetVersion ? " (recommended)" : ""}
                          </Link>
                        )
                      })}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </div>
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="text-base font-semibold">Additional metadata</h3>
              <dl className="mt-3 space-y-2 text-sm text-muted-foreground">
                <div>
                  <dt className="font-medium text-foreground">Approximate size</dt>
                  <dd>{displaySizeHuman(dataset.size_human)}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Has derivatives</dt>
                  <dd>{dataset.has_derivatives ? "Yes" : "Not specified"}</dd>
                </div>
                <div>
                  <dt className="font-medium text-foreground">Updated</dt>
                  <dd>{dataset.updated_at ? new Date(dataset.updated_at).toLocaleDateString() : "N/A"}</dd>
                </div>
              </dl>
            </div>
          </TabsContent>
          <TabsContent value="validation" className="mt-4 space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold">Validation</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Lightweight checks from backend services. Use “Ask Agent to fix” for remediation steps.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void fetchQuality()}
                  disabled={qualityLoading}
                >
                  {qualityLoading ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Refreshing…
                    </span>
                  ) : (
                    "Refresh"
                  )}
                </Button>
              </div>

              {qualityError ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                  {qualityError}
                </div>
              ) : null}

              {!quality && !qualityLoading && !qualityError ? (
                <div className="text-sm text-muted-foreground">
                  Open this tab to run a lightweight validation check.
                </div>
              ) : null}

              {quality ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge
                    variant={
                      qualitySummary.valid === true
                        ? "default"
                        : qualitySummary.valid === false
                          ? "destructive"
                          : "secondary"
                    }
                  >
                    {qualitySummary.valid === true
                      ? "BIDS valid"
                      : qualitySummary.valid === false
                        ? "BIDS invalid"
                        : "BIDS status unknown"}
                  </Badge>
                  <Badge variant="outline">Errors: {qualitySummary.errors ?? "—"}</Badge>
                  <Badge variant="outline">Warnings: {qualitySummary.warnings ?? "—"}</Badge>
                  <Badge variant="secondary">
                    Score: {typeof qualitySummary.score === "number" ? qualitySummary.score.toFixed(1) : "—"}
                  </Badge>
                </div>
              ) : null}
            </div>

            {resourceAddresses ? (
              <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="text-base font-semibold">Resource readiness</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Dataset source resolution summary used by the planner and data loader.
                    </p>
                  </div>
                  {resourceAddresses.readiness?.status ? (
                    <Badge variant={resourceReadinessVariant}>
                      {resourceAddresses.readiness.status}
                    </Badge>
                  ) : null}
                </div>

                {resourceAddresses.readiness?.reason ? (
                  <p className="text-sm text-muted-foreground">{resourceAddresses.readiness.reason}</p>
                ) : null}

                {resourceAddresses.unavailable ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                    {resourceAddresses.error || "Resource address lookup failed."}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge variant="outline">
                        Required files:{" "}
                        {typeof resourceRequiredFiles?.required_passed === "number"
                          ? resourceRequiredFiles.required_passed
                          : "—"}
                        /
                        {typeof resourceRequiredFiles?.required_total === "number"
                          ? resourceRequiredFiles.required_total
                          : "—"}
                      </Badge>
                      {resourceRequiredFiles?.analysis_goal ? (
                        <Badge variant="secondary">Goal: {resourceRequiredFiles.analysis_goal}</Badge>
                      ) : null}
                      {typeof resourceAddresses.dataset_summary?.subjects_count === "number" ? (
                        <Badge variant="outline">
                          Subjects: {resourceAddresses.dataset_summary.subjects_count}
                        </Badge>
                      ) : null}
                      {resourceAddresses.selected_version ? (
                        <Badge variant="secondary">
                          Version: {resourceAddresses.selected_version}
                        </Badge>
                      ) : null}
                    </div>
                    {resourceAddresses.storage_summary ? (
                      <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground space-y-1">
                        <div>
                          Mounted BIDS:{" "}
                          <span className="font-medium text-foreground">
                            {resourceAddresses.storage_summary.bids_path_available ? "yes" : "no"}
                          </span>
                        </div>
                        {resourceAddresses.storage_summary.bids_path ? (
                          <div>
                            BIDS path:{" "}
                            <code className="rounded bg-background px-1 py-0.5 text-[11px]">
                              {resourceAddresses.storage_summary.bids_path}
                            </code>
                          </div>
                        ) : null}
                        {resourceAddresses.storage_summary.available_derivatives?.length ? (
                          <div>
                            Available derivatives:{" "}
                            {resourceAddresses.storage_summary.available_derivatives.join(", ")}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {resourceAddresses.files_summary?.groups?.length ? (
                      <div className="rounded-md border bg-muted/20 p-3">
                        <div className="text-xs font-medium text-foreground mb-2">
                          Required-file pattern groups
                        </div>
                        <div className="space-y-1 text-xs text-muted-foreground">
                          {resourceAddresses.files_summary.groups.map((group, index) => (
                            <div key={`${group.name || "group"}_${index}`}>
                              <span className="font-medium text-foreground">
                                {group.name || `group_${index + 1}`}
                              </span>
                              {`: `}
                              {group.passed ? "passed" : "failed"} · min {group.min_matches}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="overflow-x-auto rounded-lg border">
                      <table className="min-w-full text-sm">
                        <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                          <tr>
                            <th className="px-3 py-2">Stage</th>
                            <th className="px-3 py-2">Kind</th>
                            <th className="px-3 py-2">Hit</th>
                          </tr>
                        </thead>
                        <tbody>
                          {resourceTraceSummary.length ? (
                            resourceTraceSummary.map((item, index) => (
                              <tr key={`${item.stage}_${item.kind}_${index}`} className="border-t">
                                <td className="px-3 py-2 text-foreground">{item.stage}</td>
                                <td className="px-3 py-2 text-muted-foreground">{item.kind}</td>
                                <td className="px-3 py-2">
                                  <Badge variant={item.hit ? "default" : "secondary"}>
                                    {item.hit ? "yes" : "no"}
                                  </Badge>
                                </td>
                              </tr>
                            ))
                          ) : (
                            <tr className="border-t">
                              <td className="px-3 py-2 text-muted-foreground" colSpan={3}>
                                No trace summary available.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ) : null}

            {quality ? (
              validationIssues.length ? (
                <div className="space-y-3">
                  {validationIssues.map((issue) => (
                    <div key={issue.id} className="rounded-xl border bg-card p-5 shadow-sm">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge
                              variant={issue.severity === "error" ? "destructive" : "secondary"}
                              className="text-xs"
                            >
                              {issue.severity === "error" ? "Error" : "Warning"}
                            </Badge>
                            <div className="text-sm font-medium">{issue.title}</div>
                          </div>
                          {issue.detail ? (
                            <div className="mt-2 text-sm text-muted-foreground break-words">
                              {issue.detail}
                            </div>
                          ) : null}
                        </div>
                        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              const prompt = buildValidationPrompt(issue)
                              router.push(
                                `/studio?tab=plan&datasetId=${encodeURIComponent(dataset.id)}&prompt=${encodeURIComponent(prompt)}`,
                              )
                            }}
                          >
                            Ask Agent to fix
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border bg-card p-5 shadow-sm">
                  <div className="text-sm font-medium">No issues reported</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    The validation endpoint did not report errors or warnings for this dataset.
                  </div>
                </div>
              )
            ) : null}
          </TabsContent>
        </Tabs>
      </section>
      <Dialog open={analysisDialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="max-w-2xl space-y-6">
          <DialogHeader>
            <DialogTitle>Run analysis</DialogTitle>
            <DialogDescription>
              Choose a workflow for <span className="font-medium text-foreground">{dataset.name}</span> and Brain Researcher will pre-populate the
              job configuration.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div>
              <p className="text-sm font-medium text-foreground">1. Choose an analysis type</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {analysisOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    disabled={!option.supported}
                    onClick={() => {
                      setSelectedAnalysis(option.id)
                      setSelectedPipeline(null)
                    }}
                    className={cn(
                      "rounded-2xl border p-4 text-left transition hover:border-primary/60",
                      selectedAnalysis === option.id && "border-primary ring-2 ring-primary",
                      !option.supported && "cursor-not-allowed opacity-40",
                    )}
                  >
                    <p className="text-base font-semibold">{option.label}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{option.description}</p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Requires: {option.modalities.length ? option.modalities.join(", ") : "Any modality"}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {selectedAnalysisConfig && (
              <div>
                <p className="text-sm font-medium text-foreground">2. Select a pipeline</p>
                {pipelinesLoading ? (
                  <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading pipelines...
                  </div>
                ) : pipelineOptions.length ? (
                  <div className="mt-3 space-y-3">
                    {pipelineOptions.map((pipeline) => {
                      const pipelineWithSteps = pipeline as PipelineOption & { apiSteps?: ApiPipelineStep[] }
                      return (
                        <button
                          key={pipeline.id}
                          type="button"
                          onClick={() => setSelectedPipeline(pipeline.id)}
                          className={cn(
                            "w-full rounded-2xl border p-4 text-left transition hover:border-primary/60",
                            selectedPipeline === pipeline.id && "border-primary ring-2 ring-primary",
                          )}
                        >
                          <p className="text-sm font-semibold text-foreground">{pipeline.label}</p>
                          <p className="text-sm text-muted-foreground">{pipeline.description}</p>
                          {/* Show pipeline steps if available from API */}
                          {pipelineWithSteps.apiSteps && pipelineWithSteps.apiSteps.length > 0 && (
                            <div className="mt-2 space-y-1">
                              <p className="text-xs font-medium text-muted-foreground">Pipeline steps:</p>
                              <ul className="ml-4 list-disc text-xs text-muted-foreground">
                                {pipelineWithSteps.apiSteps.map((step, idx) => (
                                  <li key={idx}>
                                    <span className="font-mono">{step.tool}</span>
                                    {step.description && ` - ${step.description}`}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          <p className="mt-2 text-xs text-muted-foreground">
                            Modalities: {pipeline.modalities.length ? pipeline.modalities.join(", ") : "Any"}
                          </p>
                          <p className="text-xs text-muted-foreground">Est. runtime: {pipeline.estRuntime}</p>
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">
                    No compatible pipelines available for this dataset. Try selecting a different analysis or use Dataset Finder filters.
                  </p>
                )}
              </div>
            )}

            {selectedAnalysis === "multiverse_glm" && selectedPipeline && (
              <div>
                <p className="text-sm font-medium text-foreground">3. Configure multiverse parameters</p>
                <div className="mt-3 space-y-4">
                  {dataset.tasks && dataset.tasks.length > 0 && (
                    <div className="space-y-2">
                      <label htmlFor="task-select" className="text-sm font-medium text-foreground">
                        Task
                      </label>
                      <select
                        id="task-select"
                        className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                        value={selectedTask || ""}
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
                    <p className="text-xs text-muted-foreground">
                      Number of GLM variants to generate (HRF × confounds × high-pass combinations)
                    </p>
                  </div>
                </div>
              </div>
            )}

            {selectedPipelineConfig && selectedAnalysisConfig && (
              <div className="rounded-2xl border bg-muted/30 p-4 text-sm text-muted-foreground">
                <p>
                  <span className="font-semibold text-foreground">Dataset:</span> {dataset.name}
                </p>
                <p>
                  <span className="font-semibold text-foreground">Pipeline:</span> {selectedPipelineConfig.label}
                </p>
                <p>
                  <span className="font-semibold text-foreground">Analysis:</span> {selectedAnalysisConfig.label}
                </p>
                <p>
                  <span className="font-semibold text-foreground">Runtime:</span> {selectedPipelineConfig.estRuntime}
                </p>
                {selectedPipelineConfig.launchSource === "workflow_alias" && launchPipelineId ? (
                  <p>
                    <span className="font-semibold text-foreground">Launch workflow:</span> {launchPipelineId}
                  </p>
                ) : null}
              </div>
            )}

            {selectedPipelineConfig ? (
              <div className="rounded-lg border bg-background p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-foreground">Launch checks</span>
                  {preflightLoading ? (
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Checking
                    </span>
                  ) : null}
                </div>
                <div className="mt-2 space-y-2">
                  {preflightError ? (
                    <p className="text-xs text-amber-700">{preflightError}</p>
                  ) : null}
                  {launchDecision ? (
                    <div
                      className={cn(
                        "rounded-md border px-3 py-2 text-xs",
                        hostedBlockedRecipeAvailable
                          ? "border-amber-200 bg-amber-50 text-amber-900"
                          : launchDecision.can_launch === false
                          ? "border-red-200 bg-red-50 text-red-800"
                          : launchDecision.status === "runnable_with_warning"
                            ? "border-amber-200 bg-amber-50 text-amber-800"
                            : "border-emerald-200 bg-emerald-50 text-emerald-800",
                      )}
                    >
                      <span className="font-medium">{launchDecisionLabel}</span>
                      {launchDecision.reason ? <span>: {launchDecision.reason}</span> : null}
                    </div>
                  ) : null}
                  {preflightGuidance ? (
                    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                      <div className="font-medium">{preflightGuidanceTitle}</div>
                      <p className="mt-1">
                        {preflightGuidance.summary ||
                          "This workflow needs a handoff runtime before it can execute."}
                      </p>
                      {preflightGuidanceIsHandoff ? (
                        <p className="mt-1">
                          Long-running workflows can take tens of minutes to hours and depend on dataset mounts,
                          container modules, and license or environment setup. Use the recipe handoff instead of
                          starting this from the hosted UI.
                        </p>
                      ) : null}
                      <div className="mt-2 flex flex-wrap gap-2">
                        {preflightGuidance.runtime_target ? (
                          <Badge variant="outline">Runtime: {preflightGuidance.runtime_target}</Badge>
                        ) : null}
                        {preflightGuidance.supported_recipe_targets?.length ? (
                          <Badge variant="outline">
                            Targets: {preflightGuidance.supported_recipe_targets.join(", ")}
                          </Badge>
                        ) : null}
                        {preflightGuidance.required_env_vars?.length ? (
                          <Badge variant="outline">
                            Env: {preflightGuidance.required_env_vars.join(", ")}
                          </Badge>
                        ) : null}
                        {preflightContainerImages.length ? (
                          <Badge variant="outline">
                            Images: {preflightContainerImages.join(", ")}
                          </Badge>
                        ) : null}
                      </div>
                      {preflightGuidance.detail ? (
                        <p className="mt-2 break-words text-amber-800">{preflightGuidance.detail}</p>
                      ) : null}
                    </div>
                  ) : null}
                  {preflightChecks
                    .filter((check) => check.status === "blocked" || check.status === "warning")
                    .map((check) => (
                      <div
                        key={check.id}
                        className={cn(
                          "rounded-md border px-3 py-2 text-xs",
                          check.status === "blocked"
                            ? "border-red-200 bg-red-50 text-red-800"
                            : "border-amber-200 bg-amber-50 text-amber-800",
                        )}
                      >
                        <span className="font-medium">{check.label}</span>
                        {check.detail ? <span>: {check.detail}</span> : null}
                      </div>
                    ))}
                  {!preflightLoading &&
                  !preflightError &&
                  preflightChecks.length > 0 &&
                  !preflightChecks.some((check) => check.status === "blocked" || check.status === "warning") ? (
                    <p className="text-xs text-muted-foreground">Ready to launch.</p>
                  ) : null}
                </div>
              </div>
            ) : null}

            {analysisError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                {analysisError}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => handleDialogOpenChange(false)}>
              Cancel
            </Button>
            {handoffIsPrimary ? (
              <>
                <Button
                  onClick={openSelectedWorkflowHandoff}
                  disabled={!selectedPipelineConfig || preflightLoading}
                >
                  <Code2 className="mr-2 h-4 w-4" />
                  Hand off
                </Button>
                <Button
                  variant="outline"
                  onClick={handleConfirmAnalysis}
                  disabled={!selectedPipelineConfig || isSubmitting || preflightLoading || preflightBlocked}
                >
                  {isSubmitting ? "Starting..." : "Launch analysis"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  onClick={openSelectedWorkflowHandoff}
                  disabled={!selectedPipelineConfig || preflightLoading}
                >
                  <Code2 className="mr-2 h-4 w-4" />
                  Hand off
                </Button>
                <Button
                  onClick={handleConfirmAnalysis}
                  disabled={!selectedPipelineConfig || isSubmitting || preflightLoading || preflightBlocked}
                >
                  {isSubmitting ? "Starting..." : "Launch analysis"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <HandoffModal
        open={handoffOpen}
        onClose={() => {
          setHandoffOpen(false)
          setHandoffTemplatePayload(null)
        }}
        mode="template"
        payload={currentHandoffPayload}
      />
    </div>
  )
}
