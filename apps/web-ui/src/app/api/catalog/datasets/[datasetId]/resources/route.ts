import { NextRequest, NextResponse } from "next/server"

import { getDataset } from "@/lib/server/dataset-catalog"
import { forwardAuthHeaders, resolveAgentBaseUrl } from "@/lib/server/downstream"
import type {
  DatasetDetailResponse,
  DatasetResourceAddresses,
} from "@/types/datasets-search"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

const DEFAULT_RESOURCE_UPSTREAM_TIMEOUT_MS = 5000

interface Params {
  params: { datasetId: string }
}

function resolveResourceUpstreamTimeoutMs(): number {
  const raw = Number(process.env.BR_DATASET_RESOURCE_TIMEOUT_MS)
  if (Number.isFinite(raw) && raw > 0) return raw
  return DEFAULT_RESOURCE_UPSTREAM_TIMEOUT_MS
}

function timeoutMessage(timeoutMs: number): string {
  return `resource_readiness_timeout_after_${timeoutMs}ms`
}

function isReadinessTimeout(error?: string): boolean {
  return Boolean(error && /^resource_readiness_timeout_after_\d+ms$/.test(error.trim()))
}

function decodeDatasetId(datasetId: string): string {
  let decoded = datasetId.trim()
  for (let i = 0; i < 2; i += 1) {
    try {
      const next = decodeURIComponent(decoded).trim()
      if (!next || next === decoded) break
      decoded = next
    } catch {
      break
    }
  }
  return decoded
}

function inferOpenNeuroId(datasetRef: string): string | null {
  const match = datasetRef.match(/ds\d{6}/i)
  if (match) return match[0].toLowerCase()
  const parts = datasetRef.split(":").filter(Boolean)
  const suffix = parts.at(-1)
  if (suffix && /^ds\d{6}$/i.test(suffix)) return suffix.toLowerCase()
  return null
}

function normalizeDatasetQuery(datasetId: string): string[] {
  const decoded = decodeDatasetId(datasetId)
  const candidates = [decoded]
  if (decoded.startsWith("ds:")) {
    const parts = decoded.split(":").filter(Boolean)
    const suffix = parts.at(-1)
    if (suffix && suffix !== decoded) candidates.push(suffix)
  }
  const openNeuroMatch = decoded.match(/ds\d{6}/i)
  if (openNeuroMatch && !candidates.includes(openNeuroMatch[0])) {
    candidates.push(openNeuroMatch[0])
  }
  return candidates
}

function findCatalogDataset(datasetRef: string): DatasetDetailResponse | null {
  const candidates = normalizeDatasetQuery(datasetRef)
  for (const candidate of candidates) {
    const match = getDataset(candidate)
    if (match) return match
  }
  return null
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

function asString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined
  const trimmed = value.trim()
  return trimmed.length ? trimmed : undefined
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((entry) => (typeof entry === "string" ? entry.trim() : ""))
    .filter(Boolean)
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function asBooleanParam(value: string | null, fallback = true): boolean {
  if (value == null) return fallback
  const normalized = value.trim().toLowerCase()
  if (!normalized) return fallback
  if (["0", "false", "no", "off"].includes(normalized)) return false
  if (["1", "true", "yes", "on"].includes(normalized)) return true
  return fallback
}

function cleanHumanSize(value: unknown): string | undefined {
  const size = asString(value)
  if (!size || /\bnan\b/i.test(size) || /^n\/?a$/i.test(size)) return undefined
  return size
}

function parseJsonSafely(raw: string): Record<string, unknown> {
  if (!raw) return {}
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return {}
  }
}

type SourceAccessMetadata = NonNullable<DatasetResourceAddresses["source_access"]>

function parseSourceAccess(toolData?: Record<string, unknown>): SourceAccessMetadata | undefined {
  const row = asRecord(toolData?.source_access)
  if (!Object.keys(row).length) return undefined

  const bucketCheck = asRecord(row.bucket_check)
  const versionCheck = asRecord(row.version_check)
  const rawAvailableVersions = Array.isArray(row.available_versions)
    ? row.available_versions
    : []

  const availableVersions = rawAvailableVersions
    .map((item) => {
      const entry = asRecord(item)
      const id = asString(entry.id)
      if (!id) return null
      const label = asString(entry.label) || id
      return {
        id,
        label,
        source: asString(entry.source) || "source_repo",
        state: asString(entry.state) === "verified" ? ("verified" as const) : ("metadata" as const),
        created_at: asString(entry.created_at),
        recommended: Boolean(entry.recommended),
      }
    })
    .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry))

  return {
    provider:
      asString(row.provider) === "openneuro" ||
      asString(row.provider) === "s3" ||
      asString(row.provider) === "http" ||
      asString(row.provider) === "other"
        ? (asString(row.provider) as SourceAccessMetadata["provider"])
        : undefined,
    bucket_uri: asString(row.bucket_uri),
    bucket_check: {
      state: asString(bucketCheck.state) as any,
      method: asString(bucketCheck.method) as any,
      checked_at: asString(bucketCheck.checked_at),
      message: asString(bucketCheck.message),
      latency_ms: asNumber(bucketCheck.latency_ms),
      cache_hit:
        typeof bucketCheck.cache_hit === "boolean"
          ? bucketCheck.cache_hit
          : undefined,
    },
    version_check: {
      mode: asString(versionCheck.mode) as any,
      requested: asString(versionCheck.requested),
      resolved: asString(versionCheck.resolved),
    },
    available_versions: availableVersions.length ? availableVersions : undefined,
  }
}

type DatasetVersionOption = NonNullable<DatasetResourceAddresses["versions"]>[number]

type VersionMetadata = Pick<
  DatasetResourceAddresses,
  "exists_summary" | "versions" | "default_version" | "selected_version"
>

type ResourceMetadata = Pick<
  DatasetResourceAddresses,
  "dataset_summary" | "storage_summary" | "files_summary" | "mount_trace"
>

function canonicalVersionId(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return "current"
  const semantic = trimmed.match(/\bv?(\d+\.\d+\.\d+)\b/i)
  if (semantic) return `v${semantic[1]}`
  const openNeuroDoi = trimmed.match(/openneuro\.[^.]+\.(v\d+\.\d+\.\d+)/i)
  if (openNeuroDoi) return openNeuroDoi[1].toLowerCase()
  return trimmed
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "current"
}

function extractVersionFromText(raw?: string): string | undefined {
  if (!raw) return undefined
  const text = raw.trim()
  if (!text) return undefined
  const semantic = text.match(/\bv?(\d+\.\d+\.\d+)\b/i)
  if (semantic) return `v${semantic[1]}`
  const openNeuroDoi = text.match(/openneuro\.[^.]+\.(v\d+\.\d+\.\d+)/i)
  if (openNeuroDoi) return openNeuroDoi[1].toLowerCase()
  return undefined
}

function buildVersionMetadata(args: {
  datasetRef: string
  openNeuroId: string | null
  catalogDataset: DatasetDetailResponse | null
  toolData?: Record<string, unknown>
  preferredVersion?: string | null
}): VersionMetadata {
  const { datasetRef, openNeuroId, catalogDataset, toolData, preferredVersion } = args
  const remoteUrls = asRecord(toolData?.remote_urls)
  const sourceAccess = parseSourceAccess(toolData)
  const localAvailable = Boolean(toolData?.is_bids_available)
  const derivativeCount = asStringArray(toolData?.available_derivatives).length

  const options = new Map<string, DatasetVersionOption>()
  const addOption = (
    option: DatasetVersionOption,
    priority: "first" | "last" = "first",
  ) => {
    if (options.has(option.id)) return
    if (priority === "last") {
      options.set(option.id, option)
      return
    }
    options.set(option.id, option)
  }

  const sourceVersion = asString(catalogDataset?.source_version)
  const sourceAvailableVersions = Array.isArray(sourceAccess?.available_versions)
    ? sourceAccess.available_versions
    : []
  for (const entry of sourceAvailableVersions) {
    const id = asString(entry.id)
    if (!id) continue
    const label = asString(entry.label) || id
    const state = asString(entry.state)
    addOption({
      id,
      label,
      source: "source_repo",
      availability: state === "verified" ? "available" : "unknown",
      recommended: Boolean(entry.recommended),
    })
  }

  if (sourceVersion) {
    addOption({
      id: canonicalVersionId(sourceVersion),
      label: sourceVersion,
      source: "catalog",
      availability: localAvailable ? "available" : "unknown",
      recommended: true,
    })
  }

  const sourceCandidates = [
    asString(remoteUrls["primary"]),
    asString(remoteUrls["openneuro"]),
    asString(catalogDataset?.primary_url),
  ]
  for (const candidate of sourceCandidates) {
    const version = extractVersionFromText(candidate)
    if (!version) continue
    addOption({
      id: canonicalVersionId(version),
      label: version,
      source: "source_repo",
      availability: "unknown",
    })
  }

  if (openNeuroId) {
    addOption(
      {
        id: "latest",
        label: `latest (${openNeuroId})`,
        source: "source_repo",
        availability: "unknown",
      },
      "last",
    )
  }

  if (localAvailable) {
    addOption({
      id: "mounted-current",
      label: "mounted copy (current)",
      source: "mounted",
      availability: "available",
      recommended: options.size === 0,
    })
  }

  if (options.size === 0) {
    addOption({
      id: "current",
      label: "current",
      source: "default",
      availability: "unknown",
      recommended: true,
    })
  }

  const versions = Array.from(options.values())
  const defaultVersion =
    asString(sourceAccess?.version_check?.resolved) ||
    versions.find((item) => item.recommended)?.id ||
    versions[0]?.id
  const selectedVersion =
    preferredVersion && versions.some((item) => item.id === preferredVersion)
      ? preferredVersion
      : asString(sourceAccess?.version_check?.resolved) || defaultVersion

  const versionSelectionMode: "metadata_only" | "full_resolution" =
    sourceAccess?.version_check?.mode === "verified"
      ? "full_resolution"
      : "metadata_only"

  return {
    exists_summary: {
      dataset_in_catalog: Boolean(catalogDataset),
      local_bids_available: localAvailable,
      source_repo: asString(catalogDataset?.source_repo),
      source_repo_id: asString(catalogDataset?.source_repo_id),
      source_version: sourceVersion,
      derivatives_count: derivativeCount,
      version_selection_mode: versionSelectionMode,
    },
    versions,
    default_version: defaultVersion,
    selected_version: selectedVersion,
  }
}

function buildDatasetSummary(
  datasetRef: string,
  catalogDataset: DatasetDetailResponse | null,
): DatasetResourceAddresses["dataset_summary"] {
  if (!catalogDataset) {
    return {
      dataset_id: datasetRef,
    }
  }
  return {
    dataset_id: catalogDataset.id,
    name: catalogDataset.name,
    subjects_count: catalogDataset.subjects_count,
    sessions_count: catalogDataset.sessions_count,
    modalities: catalogDataset.modalities,
    tasks: catalogDataset.tasks,
    source_repo: catalogDataset.source_repo,
    source_repo_id: catalogDataset.source_repo_id,
    access_type: catalogDataset.access_type,
    source_version: catalogDataset.source_version,
  }
}

function buildStorageSummary(args: {
  catalogDataset: DatasetDetailResponse | null
  toolData?: Record<string, unknown>
  includeSensitivePaths: boolean
}): DatasetResourceAddresses["storage_summary"] {
  const { catalogDataset, toolData, includeSensitivePaths } = args
  const derivativesRaw = asRecord(toolData?.derivatives)
  const availableDerivatives = asStringArray(toolData?.available_derivatives)
  const availableSet = new Set(availableDerivatives)
  const derivativeEntries = Object.entries(derivativesRaw)
    .map(([kind, value]) => {
      const path = asString(value)
      const available = Boolean(path) || availableSet.has(kind)
      return {
        kind,
        path: includeSensitivePaths ? path : undefined,
        available,
      }
    })
    .filter((entry) => entry.kind)

  const bidsPath = asString(toolData?.bids_path)
  const bidsAvailable = Boolean(toolData?.is_bids_available)
  const sizeBytes = asNumber(toolData?.size_bytes)

  return {
    bids_path_available: bidsAvailable,
    bids_path: includeSensitivePaths ? bidsPath : undefined,
    size_bytes: sizeBytes,
    size_human: cleanHumanSize(catalogDataset?.size_human),
    available_derivatives: availableDerivatives,
    derivatives: derivativeEntries.length ? derivativeEntries : undefined,
  }
}

function buildFilesSummary(
  toolData?: Record<string, unknown>,
): DatasetResourceAddresses["files_summary"] {
  const requiredRaw = asRecord(toolData?.required_files)
  const groupsRaw = Array.isArray(requiredRaw["groups"])
    ? requiredRaw["groups"]
    : []
  const groups = groupsRaw
    .map((group) => {
      const row = asRecord(group)
      const countsRaw = asRecord(row["counts"])
      const counts = Object.fromEntries(
        Object.entries(countsRaw)
          .map(([pattern, value]) => [pattern, asNumber(value) ?? 0])
          .filter(([pattern]) => Boolean(pattern)),
      )
      return {
        name: asString(row["name"]),
        patterns: asStringArray(row["patterns"]),
        counts,
        min_matches: asNumber(row["min_matches"]) ?? 1,
        optional: Boolean(row["optional"]),
        passed: Boolean(row["passed"]),
      }
    })
    .filter((group) => group.patterns.length > 0 || group.name)

  const totalMatchedFiles = groups.reduce((acc, group) => {
    const subtotal = Object.values(group.counts as Record<string, number>).reduce(
      (sum, value) => sum + Number(value || 0),
      0,
    )
    return acc + subtotal
  }, 0)

  return {
    analysis_goal: asString(requiredRaw["analysis_goal"]),
    required_total: asNumber(requiredRaw["required_total"]),
    required_passed: asNumber(requiredRaw["required_passed"]),
    all_required_passed:
      typeof requiredRaw["all_required_passed"] === "boolean"
        ? requiredRaw["all_required_passed"]
        : undefined,
    total_matched_files: groups.length ? totalMatchedFiles : undefined,
    missing_patterns: asStringArray(requiredRaw["missing_patterns"]),
    groups: groups.length ? groups : undefined,
  }
}

function buildMountTrace(args: {
  toolData?: Record<string, unknown>
  includeSensitivePaths: boolean
}): DatasetResourceAddresses["mount_trace"] {
  const { toolData, includeSensitivePaths } = args
  const traceRaw = Array.isArray(toolData?.source_trace) ? toolData.source_trace : []
  if (!traceRaw.length) return undefined

  const trace = traceRaw
    .map((entry) => {
      const row = asRecord(entry)
      return {
        stage: asString(row["stage"]) || "unknown",
        kind: asString(row["kind"]) || "unknown",
        hit: Boolean(row["hit"]),
        root: includeSensitivePaths ? asString(row["root"]) : undefined,
        candidate: includeSensitivePaths
          ? asString(row["candidate"])
          : undefined,
        note: asString(row["note"]),
      }
    })
    .slice(0, 48)

  return trace.length ? trace : undefined
}

function buildResourceMetadata(args: {
  datasetRef: string
  catalogDataset: DatasetDetailResponse | null
  toolData?: Record<string, unknown>
  includeSensitivePaths: boolean
}): ResourceMetadata {
  const { datasetRef, catalogDataset, toolData, includeSensitivePaths } = args
  return {
    dataset_summary: buildDatasetSummary(datasetRef, catalogDataset),
    storage_summary: buildStorageSummary({
      catalogDataset,
      toolData,
      includeSensitivePaths,
    }),
    files_summary: buildFilesSummary(toolData),
    mount_trace: buildMountTrace({ toolData, includeSensitivePaths }),
  }
}

function withVersionMetadata(
  base: DatasetResourceAddresses,
  metadata: VersionMetadata,
): DatasetResourceAddresses {
  return {
    ...base,
    ...metadata,
  }
}

function withResourceMetadata(
  base: DatasetResourceAddresses,
  metadata: ResourceMetadata,
): DatasetResourceAddresses {
  return {
    ...base,
    ...metadata,
  }
}

function fallbackResponse(
  datasetRef: string,
  openNeuroId: string | null,
  error?: string,
): DatasetResourceAddresses {
  const sourceKind: "openneuro" | "other" = openNeuroId ? "openneuro" : "other"
  const openneuroUrl = openNeuroId
    ? `https://openneuro.org/datasets/${openNeuroId}`
    : undefined
  const s3Uri = openNeuroId ? `s3://openneuro.org/${openNeuroId}` : undefined

  return {
    dataset_ref: datasetRef,
    source_kind: sourceKind,
    addresses: {
      openneuro_url: openneuroUrl,
      s3_uri: s3Uri,
    },
    source_access: {
      provider: openNeuroId ? "openneuro" : "other",
      bucket_uri: s3Uri,
      bucket_check: {
        state: "unknown",
        method: "none",
      },
      version_check: {
        mode: "metadata_only",
      },
    },
    unavailable: true,
    error,
  }
}

function degradedOpenNeuroTimeoutResponse(
  datasetRef: string,
  openNeuroId: string,
  error: string,
): DatasetResourceAddresses {
  const openneuroUrl = `https://openneuro.org/datasets/${openNeuroId}`
  const s3Uri = `s3://openneuro.org/${openNeuroId}`
  return {
    dataset_ref: datasetRef,
    source_kind: "openneuro",
    addresses: {
      openneuro_url: openneuroUrl,
      s3_uri: s3Uri,
    },
    source_access: {
      provider: "openneuro",
      bucket_uri: s3Uri,
      bucket_check: {
        state: "unreachable",
        message: "Backend readiness check timed out; using static OpenNeuro address hints.",
      },
      version_check: {
        mode: "metadata_only",
      },
    },
    readiness: {
      status: "degraded",
      reason:
        "Backend readiness checks timed out. Static OpenNeuro source addresses are available, but mount and file readiness were not verified.",
    },
    unavailable: false,
    error,
  }
}

function fallbackOrDegradedTimeoutResponse(
  datasetRef: string,
  openNeuroId: string | null,
  error?: string,
): DatasetResourceAddresses {
  if (openNeuroId && isReadinessTimeout(error)) {
    return degradedOpenNeuroTimeoutResponse(datasetRef, openNeuroId, error)
  }
  return fallbackResponse(datasetRef, openNeuroId, error)
}

function authRequiredResponse(
  datasetRef: string,
  openNeuroId: string | null,
): DatasetResourceAddresses {
  const sourceKind: "openneuro" | "other" = openNeuroId ? "openneuro" : "other"
  const openneuroUrl = openNeuroId
    ? `https://openneuro.org/datasets/${openNeuroId}`
    : undefined
  const s3Uri = openNeuroId ? `s3://openneuro.org/${openNeuroId}` : undefined

  return {
    dataset_ref: datasetRef,
    source_kind: sourceKind,
    addresses: {
      openneuro_url: openneuroUrl,
      s3_uri: s3Uri,
    },
    source_access: {
      provider: openNeuroId ? "openneuro" : "other",
      bucket_uri: s3Uri,
      bucket_check: {
        state: "unknown",
        method: "none",
        message: "sign in required for runtime verification",
      },
      version_check: {
        mode: "metadata_only",
      },
    },
    readiness: {
      status: "auth_required",
      reason: "Sign in to run backend readiness checks.",
    },
    unavailable: false,
  }
}

function isMissingBearerError(err?: string): boolean {
  if (!err) return false
  const normalized = err.trim().toLowerCase()
  if (!normalized) return false
  return (
    normalized.includes("missing_bearer_token") ||
    normalized.includes("authorization header required") ||
    normalized.includes("bearer token")
  )
}

function normalizeResponse(
  datasetRef: string,
  openNeuroId: string | null,
  catalogDataset: DatasetDetailResponse | null,
  toolData: Record<string, unknown>,
  includeSensitivePaths: boolean,
): DatasetResourceAddresses {
  const remoteUrls = asRecord(toolData["remote_urls"])
  const sourceAccess = parseSourceAccess(toolData)
  const sourceKind: "openneuro" | "other" =
    openNeuroId || sourceAccess?.provider === "openneuro" ? "openneuro" : "other"
  const openneuroUrl =
    asString(remoteUrls["openneuro"]) ||
    (openNeuroId ? `https://openneuro.org/datasets/${openNeuroId}` : undefined)
  const sourceRepoUrl = asString(remoteUrls["primary"])
  const s3Uri =
    asString(sourceAccess?.bucket_uri) ||
    (openNeuroId ? `s3://openneuro.org/${openNeuroId}` : undefined)

  const readinessRaw = asRecord(toolData["readiness"])
  const filesSummary = buildFilesSummary(toolData)
  const mountTrace = buildMountTrace({ toolData, includeSensitivePaths })

  return {
    dataset_ref: datasetRef,
    source_kind: sourceKind,
    dataset_summary: buildDatasetSummary(datasetRef, catalogDataset),
    storage_summary: buildStorageSummary({
      catalogDataset,
      toolData,
      includeSensitivePaths,
    }),
    files_summary: filesSummary,
    mount_trace: mountTrace,
    addresses: {
      openneuro_url: openneuroUrl,
      s3_uri: s3Uri,
      source_repo_url: sourceKind === "other" ? sourceRepoUrl : undefined,
    },
    source_access: sourceAccess,
    readiness: {
      status: asString(readinessRaw["status"]),
      reason: asString(readinessRaw["reason"]),
    },
    required_files: {
      analysis_goal: filesSummary.analysis_goal,
      required_total: filesSummary.required_total,
      required_passed: filesSummary.required_passed,
      all_required_passed: filesSummary.all_required_passed,
    },
    trace_summary: (mountTrace ?? [])
      .map((entry) => {
        return {
          stage: entry.stage,
          kind: entry.kind,
          hit: entry.hit,
        }
      })
      .slice(0, 24),
    unavailable: false,
  }
}

export async function GET(request: NextRequest, { params }: Params) {
  const datasetRef = decodeDatasetId(params.datasetId)
  const openNeuroId = inferOpenNeuroId(datasetRef)
  const catalogDataset = findCatalogDataset(datasetRef)
  const preferredVersion =
    asString(request.nextUrl.searchParams.get("datasetVersion")) ||
    asString(request.nextUrl.searchParams.get("dataset_version")) ||
    asString(request.nextUrl.searchParams.get("version")) ||
    null
  const checkSourceAccess = asBooleanParam(
    request.nextUrl.searchParams.get("checkSourceAccess") ||
      request.nextUrl.searchParams.get("check_source_access"),
    true,
  )
  const agentBase = resolveAgentBaseUrl()
  const headers = forwardAuthHeaders(request)
  headers.set("content-type", "application/json")
  const includeSensitivePaths = Boolean(headers.get("authorization"))

  // Public pages can be viewed without authentication. In that case we still
  // return source addresses, but skip agent-side readiness checks.
  if (!headers.get("authorization")) {
    const metadata = buildVersionMetadata({
      datasetRef,
      openNeuroId,
      catalogDataset,
      preferredVersion,
    })
    const resourceMetadata = buildResourceMetadata({
      datasetRef,
      catalogDataset,
      includeSensitivePaths: false,
    })
    return NextResponse.json(
      withResourceMetadata(
        withVersionMetadata(authRequiredResponse(datasetRef, openNeuroId), metadata),
        resourceMetadata,
      ),
    )
  }

  const timeoutMs = resolveResourceUpstreamTimeoutMs()
  const upstreamController = new AbortController()
  const timeout = setTimeout(() => {
    upstreamController.abort(new Error(timeoutMessage(timeoutMs)))
  }, timeoutMs)
  const abortFromRequest = () => {
    upstreamController.abort(new Error("request_aborted"))
  }
  request.signal.addEventListener("abort", abortFromRequest, { once: true })

  try {
    const toolArgs = {
      dataset_ref: datasetRef,
      dataset_version: preferredVersion || undefined,
      analysis_goal: "generic",
      auto_heal: false,
      run_bids_validation: true,
      enforce_semantic_gate: false,
      check_source_access: checkSourceAccess,
    }
    const upstream = await fetch(`${agentBase}/api/tools/run`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        tool: "datasets.list_resources",
        arguments: toolArgs,
        args: toolArgs,
      }),
      cache: "no-store",
      signal: upstreamController.signal,
    })

    const text = await upstream.text().catch(() => "")
    const payload = parseJsonSafely(text)
    if (!upstream.ok) {
      const err =
        asString(asRecord(payload)["error"]) ||
        asString(asRecord(payload)["detail"]) ||
        upstream.statusText
      if (isMissingBearerError(err)) {
        const metadata = buildVersionMetadata({
          datasetRef,
          openNeuroId,
          catalogDataset,
          preferredVersion,
        })
        const resourceMetadata = buildResourceMetadata({
          datasetRef,
          catalogDataset,
          includeSensitivePaths,
        })
        return NextResponse.json(
          withResourceMetadata(
            withVersionMetadata(authRequiredResponse(datasetRef, openNeuroId), metadata),
            resourceMetadata,
          ),
        )
      }
      const metadata = buildVersionMetadata({
        datasetRef,
        openNeuroId,
        catalogDataset,
        preferredVersion,
      })
      const resourceMetadata = buildResourceMetadata({
        datasetRef,
        catalogDataset,
        includeSensitivePaths,
      })
      return NextResponse.json(
        withResourceMetadata(
          withVersionMetadata(
            fallbackOrDegradedTimeoutResponse(datasetRef, openNeuroId, err),
            metadata,
          ),
          resourceMetadata,
        ),
      )
    }

    const result = asRecord(asRecord(payload)["result"])
    const toolStatus = asString(result["status"])
    const toolError = asString(result["error"])
    const toolData = asRecord(result["data"])

    if (toolStatus === "error") {
      if (isMissingBearerError(toolError)) {
        const metadata = buildVersionMetadata({
          datasetRef,
          openNeuroId,
          catalogDataset,
          toolData,
          preferredVersion,
        })
        const resourceMetadata = buildResourceMetadata({
          datasetRef,
          catalogDataset,
          toolData,
          includeSensitivePaths,
        })
        return NextResponse.json(
          withResourceMetadata(
            withVersionMetadata(authRequiredResponse(datasetRef, openNeuroId), metadata),
            resourceMetadata,
          ),
        )
      }
      const metadata = buildVersionMetadata({
        datasetRef,
        openNeuroId,
        catalogDataset,
        toolData,
        preferredVersion,
      })
      const resourceMetadata = buildResourceMetadata({
        datasetRef,
        catalogDataset,
        toolData,
        includeSensitivePaths,
      })
      return NextResponse.json(
        withResourceMetadata(
          withVersionMetadata(
            fallbackOrDegradedTimeoutResponse(
              datasetRef,
              openNeuroId,
              toolError || "tool_error",
            ),
            metadata,
          ),
          resourceMetadata,
        ),
      )
    }

    const metadata = buildVersionMetadata({
      datasetRef,
      openNeuroId,
      catalogDataset,
      toolData,
      preferredVersion,
    })
    const resourceMetadata = buildResourceMetadata({
      datasetRef,
      catalogDataset,
      toolData,
      includeSensitivePaths,
    })
    return NextResponse.json(
      withResourceMetadata(
        withVersionMetadata(
          normalizeResponse(
            datasetRef,
            openNeuroId,
            catalogDataset,
            toolData,
            includeSensitivePaths,
          ),
          metadata,
        ),
        resourceMetadata,
      ),
    )
  } catch (error) {
    const abortedReason = upstreamController.signal.reason
    const message =
      abortedReason instanceof Error
        ? abortedReason.message
        : error instanceof Error
          ? error.message
          : "resources_fetch_failed"
    const metadata = buildVersionMetadata({
      datasetRef,
      openNeuroId,
      catalogDataset,
      preferredVersion,
    })
    const resourceMetadata = buildResourceMetadata({
      datasetRef,
      catalogDataset,
      includeSensitivePaths,
    })
    return NextResponse.json(
      withResourceMetadata(
        withVersionMetadata(
          fallbackOrDegradedTimeoutResponse(datasetRef, openNeuroId, message),
          metadata,
        ),
        resourceMetadata,
      ),
    )
  } finally {
    clearTimeout(timeout)
    request.signal.removeEventListener("abort", abortFromRequest)
  }
}
