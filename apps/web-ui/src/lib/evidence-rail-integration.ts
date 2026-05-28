// Evidence Rail Data Integration

import { serviceEndpoints } from '@/lib/service-endpoints'
import type {
  ChatRunCard,
  BackendRunCard,
  ExecutionStep,
  Artifact,
  DatasetInfo,
  ToolInfo,
  Citation as ChatCitation,
  FileAttachment,
  ResourceUsage,
  ToolCall,
  BranchEvent,
  PlannerEvent
} from '@/types/chat'

export interface ExportOptions {
  includeArtifacts: boolean
  includeProvenance: boolean
  includeCitations: boolean
  includeEnvironment: boolean
  generateQR: boolean
}

interface ProvenanceNode {
  id: string
  type: 'dataset' | 'tool' | 'parameter' | 'output'
  label: string
  metadata?: any
}

interface ProvenanceEdge {
  source: string
  target: string
  label?: string
}

interface ProvenanceGraph {
  nodes: ProvenanceNode[]
  edges: ProvenanceEdge[]
}

interface Citation {
  id: string
  title: string
  authors: string[]
  year: number
  journal?: string
  doi?: string
  url?: string
  type: 'paper' | 'dataset' | 'tool' | 'method'
}

interface LegacyRunCard {
  id: string
  version: string
  created_at: Date
  // Alias for chat.ts compatibility
  timestamp: Date
  prompt: string
  analysis: {
    name: string
    description: string
    pipeline: string
  }
  // Plural datasets from API
  datasets: {
    id: string
    name: string
    source: string
    n_subjects?: number
  }[]
  // Singular dataset for compatibility with types/chat.ts RunCard
  dataset?: {
    id: string
    name: string
    source: string
    version?: string
  }
  tools: {
    name: string
    version: string
    citation?: Citation
  }[]
  parameters: Record<string, any>
  outputs: {
    name: string
    type: string
    path: string
    size?: number
  }[]
  artifacts: any[]
  provenance: ProvenanceGraph
  citations: Citation[]
  reproducibility_score?: number
  // For chat.ts compatibility - required field with optional inner fields
  reproducibility: {
    dataHash?: string
    environmentHash?: string
    seedValue?: number
  }
}

interface StepSummary {
  stepId: string
  name?: string
  state: string
  executionTimeMs?: number
  runDir?: string
  error?: string
  violations?: Violation[]
}

interface DiagnosticsSummary {
  schema_version: string
  counts?: {
    warning?: number
    error?: number
    blocking?: number
  }
  top_codes?: { code: string; count: number }[]
  recommended_next_actions?: { action: string }[]
  sample_errors?: any[]
  sample_warnings?: any[]
}

interface ViolationLocation {
  component?: string | null
  stage?: string | null
  step_id?: string | null
  path?: string | null
}

interface EvidenceRef {
  type?: string
  uri?: string | null
  summary?: string | null
  pointer?: string | null
}

interface Violation {
  schema_version?: string
  code: string
  message: string
  severity?: 'info' | 'warn' | 'error' | 'critical'
  blocking?: boolean
  where?: ViolationLocation | null
  evidence?: EvidenceRef[]
  suggested_fix?: string | null
  details?: Record<string, any>
}

interface EvidenceData {
  jobId: string
  runCard?: LegacyRunCard
  mappedRunCard?: ChatRunCard  // Mapped to frontend schema
  provenance?: ProvenanceGraph
  citations?: Citation[]
  datasets?: any[]
  parameters?: Record<string, any>
  tools?: any[]
  artifacts?: any[]
  steps?: StepSummary[]
  diagnosticsSummary?: DiagnosticsSummary
  violations?: Violation[]
}

/**
 * Map backend RunCard (snake_case) to frontend RunCard (camelCase)
 * Handles null/undefined values gracefully for backward compatibility
 */
function mapRunCardFromBackend(data: BackendRunCard | any): ChatRunCard {
  // Map execution steps
  const normalizeStepStatus = (status: any): ExecutionStep['status'] => {
    const normalized = typeof status === 'string' ? status.toLowerCase() : ''
    if (normalized === 'success' || normalized === 'succeeded') return 'completed'
    if (normalized === 'error') return 'failed'
    if (normalized === 'skipped') return 'completed'
    return (status ?? 'pending') as ExecutionStep['status']
  }

  const mapStep = (step: any): ExecutionStep => ({
    id: step.id ?? '',
    name: step.name ?? '',
    tool: step.tool ?? '',
    args: step.args ?? {},
    status: normalizeStepStatus(step.status),
    preview: step.preview,
    timing: step.timing ? {
      startTime: new Date(step.timing.start_time ?? step.timing.startTime),
      endTime: step.timing.end_time ? new Date(step.timing.end_time) : undefined,
      duration: step.timing.duration_ms ?? step.timing.duration
    } : undefined,
    logs: step.logs,
    retryCount: step.retry_count ?? step.retryCount,
    error: step.error,
    produces: step.produces,
    branchGroupId: step.branch_group_id ?? step.branchGroupId,
    branchRank: step.branch_rank ?? step.branchRank,
    branchStepId: step.branch_step_id ?? step.branchStepId
  })

  // Map artifacts
  const mapArtifact = (art: any): Artifact => ({
    id: art.id ?? '',
    type: art.type ?? 'json',
    name: art.name ?? '',
    url: art.url ?? art.path ?? '',
    meta: art.meta ?? art.metadata,
    size: art.size ?? art.size_bytes,
    checksum: art.checksum,
    description: art.description
  })

  // Map datasets
  const mapDataset = (ds: any): DatasetInfo => ({
    id: ds.id ?? '',
    name: ds.name ?? '',
    source: ds.source ?? '',
    version: ds.version,
    nSubjects: ds.n_subjects ?? ds.nSubjects,
    nSessions: ds.n_sessions ?? ds.nSessions,
    tasks: ds.tasks ?? [],
    checksum: ds.checksum,
    bidsVersion: ds.bids_version ?? ds.bidsVersion
  })

  // Map tools
  const mapTool = (tool: any): ToolInfo => ({
    name: tool.name ?? '',
    version: tool.version ?? '',
    citation: tool.citation,
    doi: tool.doi,
    url: tool.url,
    checksum: tool.checksum
  })

  // Map citations
  const mapCitation = (cit: any): ChatCitation => ({
    id: cit.id,
    type: cit.type ?? 'reference',
    title: cit.title ?? '',
    authors: cit.authors ?? [],
    doi: cit.doi,
    url: cit.url,
    year: cit.year,
    description: cit.description,
    journal: cit.journal,
    bibtex: cit.bibtex
  })

  // Map attachments
  const mapAttachment = (att: any): FileAttachment => ({
    id: att.id ?? '',
    name: att.name ?? '',
    type: att.type ?? '',
    size: att.size ?? 0,
    url: att.url ?? '',
    upload_progress: att.upload_progress,
    storage: att.storage,
    path: att.path,
    checksum: att.checksum,
    uploadedBy: att.uploaded_by ?? att.uploadedBy,
    expiresAt: att.expires_at ?? att.expiresAt
  })

  // Map resource usage
  const mapResourceUsage = (ru: any): ResourceUsage => ({
    peakMemoryMb: ru?.peak_memory_mb ?? ru?.peakMemoryMb,
    cpuTimeSeconds: ru?.cpu_time_seconds ?? ru?.cpuTimeSeconds,
    gpuTimeSeconds: ru?.gpu_time_seconds ?? ru?.gpuTimeSeconds,
    diskIoMb: ru?.disk_io_mb ?? ru?.diskIoMb,
    networkIoMb: ru?.network_io_mb ?? ru?.networkIoMb
  })

  // Map tool calls
  const mapToolCall = (tc: any): ToolCall => ({
    id: tc.id ?? '',
    tool: tc.tool ?? tc.name ?? '',
    args: tc.args ?? tc.input ?? {},
    result: tc.result ?? tc.output,
    status: tc.status ?? (tc.error ? 'error' : 'success'),
    durationMs: tc.duration_ms ?? tc.durationMs,
    error: tc.error
  })

  const mapBranchEvent = (event: any): BranchEvent => ({
    eventType: event.event_type ?? event.eventType,
    branchGroupId: event.branch_group_id ?? event.branchGroupId,
    branchRank: event.branch_rank ?? event.branchRank,
    branchTool: event.branch_tool ?? event.branchTool,
    branchStepId: event.branch_step_id ?? event.branchStepId,
    branchId: event.branch_id ?? event.branchId,
    timestamp: event.ts ?? event.timestamp,
    error: event.error
  })

  const mapPlannerEvent = (event: any): PlannerEvent => ({
    eventType: event.event_type ?? event.eventType,
    timestamp: event.ts ?? event.timestamp,
    payload: event.payload,
    diff: event.diff,
    eventId: event.event_id ?? event.eventId
  })

  return {
    version: data.version ?? '1.0',
    id: data.id ?? '',
    timestamp: data.timestamp ?? new Date().toISOString(),
    title: data.title ?? data.analysis?.name ?? 'Analysis',
    description: data.description ?? data.analysis?.description ?? '',

    execution: {
      durationSeconds: data.execution?.duration_seconds ?? 0,
      steps: (data.execution?.steps ?? []).map(mapStep),
      environment: data.execution?.environment ?? {},
      resourceUsage: mapResourceUsage(data.execution?.resource_usage),
      branchEvents: (data.execution?.branch_events ?? []).map(mapBranchEvent),
      plannerEvents: (data.execution?.planner_events ?? []).map(mapPlannerEvent),
      plannerState: data.execution?.planner_state
    },

    inputs: {
      datasets: (data.inputs?.datasets ?? data.datasets ?? []).map(mapDataset),
      parameters: data.inputs?.parameters ?? data.parameters ?? {},
      attachments: (data.inputs?.attachments ?? []).map(mapAttachment)
    },

    outputs: {
      artifacts: (data.outputs?.artifacts ?? data.artifacts ?? []).map(mapArtifact),
      metrics: data.outputs?.metrics ?? {},
      plots: data.outputs?.plots,
      text: data.outputs?.text,
      toolCalls: (data.outputs?.tool_calls ?? []).map(mapToolCall),
      citations: (data.outputs?.citations ?? []).map(mapCitation)
    },

    provenance: {
      tools: (data.provenance?.tools ?? data.tools ?? []).map(mapTool),
      citations: (data.provenance?.citations ?? data.citations ?? []).map(mapCitation),
      dependencies: data.provenance?.dependencies ?? []
    },

    reproducibility: {
      score: data.reproducibility?.score ?? data.reproducibility_score,
      randomSeed: data.reproducibility?.random_seed,
      isReproducible: data.reproducibility?.is_reproducible,
      versions: data.reproducibility?.versions,
      checksums: data.reproducibility?.checksums,
      containerInfo: data.reproducibility?.container_info
    },

    // Legacy fields for backward compatibility
    prompt: data.prompt,
    dataset: data.datasets?.[0] ? mapDataset(data.datasets[0]) : data.dataset ? mapDataset(data.dataset) : undefined,
    tools: (data.tools ?? data.provenance?.tools ?? []).map(mapTool),
    parameters: data.parameters,
    citations: (data.citations ?? data.provenance?.citations ?? []).map(mapCitation),
    artifacts: (data.artifacts ?? data.outputs?.artifacts ?? []).map(mapArtifact),
    reproducibilityScore: data.reproducibility_score ?? data.reproducibility?.score
  }
}

function mapViolation(raw: any): Violation | null {
  if (!raw || typeof raw !== 'object') return null
  return {
    schema_version: raw.schema_version ?? raw.schemaVersion,
    code: raw.code,
    message: raw.message,
    severity: raw.severity,
    blocking: raw.blocking,
    where: raw.where ?? raw.location,
    evidence: Array.isArray(raw.evidence) ? raw.evidence : undefined,
    suggested_fix: raw.suggested_fix ?? raw.suggestedFix,
    details: raw.details,
  }
}

class EvidenceRailIntegration {
  private baseUrl: string | null

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl ?? null
  }

  private buildUrl(path: string) {
    if (this.baseUrl) {
      const normalizedBase = this.baseUrl.endsWith('/')
        ? this.baseUrl.slice(0, -1)
        : this.baseUrl
      return `${normalizedBase}${path.startsWith('/') ? path : `/${path}`}`
    }
    if (path.startsWith('/api/analyses')) {
      return path
    }
    return serviceEndpoints.orchestrator(path)
  }

  /**
   * Get complete evidence data for a job
   */
  async getEvidenceData(jobId: string): Promise<EvidenceData> {
    try {
      const observation = await this.getObservation(jobId)
      if (observation) {
        const runCard = observation.run_card ?? observation.runCard
        const provenance = observation.provenance
        const diagnosticsSummary =
          observation.diagnostics_summary ?? observation.diagnosticsSummary
        const artifacts = Array.isArray(observation.artifacts)
          ? observation.artifacts
          : []
        const rawSteps = Array.isArray(observation.steps) ? observation.steps : []
        const steps = rawSteps.map((step: any): StepSummary => ({
          stepId: step.step_id ?? step.stepId ?? 'unknown-step',
          name: step.name ?? undefined,
          state: step.state ?? 'unknown',
          executionTimeMs: step.execution_time_ms ?? step.executionTimeMs ?? undefined,
          runDir: step.run_dir ?? step.runDir ?? undefined,
          error: step.error ?? undefined,
          violations: Array.isArray(step.violations)
            ? step.violations
                .map(mapViolation)
                .filter((v): v is Violation => v !== null)
            : undefined,
        }))

        const runViolations: Violation[] | undefined = Array.isArray(
          observation.violations,
        )
          ? observation.violations
              .map(mapViolation)
              .filter((v): v is Violation => v !== null)
          : undefined

        const mappedRunCard = runCard ? mapRunCardFromBackend(runCard) : undefined

        return {
          jobId,
          runCard,
          mappedRunCard,
          provenance,
          citations: runCard?.citations,
          datasets: runCard?.datasets,
          parameters: runCard?.parameters,
          tools: runCard?.tools,
          artifacts,
          steps,
          diagnosticsSummary,
          violations: runViolations,
        }
      }

      // Back-compat: fetch all evidence data in parallel
      const [provenance, runCard, artifacts, steps] = await Promise.all([
        this.getProvenance(jobId),
        this.getRunCard(jobId),
        this.getArtifacts(jobId),
        this.getJobSteps(jobId),
      ])

      // Map runCard to frontend schema
      const mappedRunCard = runCard ? mapRunCardFromBackend(runCard) : undefined

      return {
        jobId,
        runCard,
        mappedRunCard,
        provenance,
        citations: runCard?.citations,
        datasets: runCard?.datasets,
        parameters: runCard?.parameters,
        tools: runCard?.tools,
        artifacts,
        steps
      }
    } catch (error) {
      console.error('Failed to fetch evidence data:', error)
      throw error
    }
  }

  async getObservation(jobId: string): Promise<any | null> {
    const response = await fetch(this.buildUrl(`/api/analyses/${jobId}/observation`))
    if (!response.ok) {
      if (response.status === 404) {
        return null
      }
      throw new Error(`Failed to fetch observation: ${response.statusText}`)
    }
    return await response.json()
  }

  /**
   * Get provenance graph for a job
   */
  async getProvenance(jobId: string): Promise<ProvenanceGraph> {
    const response = await fetch(this.buildUrl(`/api/analyses/${jobId}/provenance`))
    
    if (!response.ok) {
      throw new Error(`Failed to fetch provenance: ${response.statusText}`)
    }
    
    return await response.json()
  }

  /**
   * Get run card for a job (returns raw backend format)
   */
  async getRunCard(jobId: string): Promise<LegacyRunCard> {
    const response = await fetch(this.buildUrl(`/api/analyses/${jobId}/runcard`))

    if (!response.ok) {
      throw new Error(`Failed to fetch run card: ${response.statusText}`)
    }

    return await response.json()
  }

  /**
   * Get run card for a job mapped to frontend schema (camelCase)
   */
  async getMappedRunCard(jobId: string): Promise<ChatRunCard> {
    // Prefer canonical observation so callers don't depend on legacy endpoints.
    try {
      const observation = await this.getObservation(jobId)
      const runCard = observation?.run_card ?? observation?.runCard
      if (runCard) {
        return mapRunCardFromBackend(runCard)
      }
    } catch {
      // Fall back to legacy run card endpoint.
    }

    const rawRunCard = await this.getRunCard(jobId)
    return mapRunCardFromBackend(rawRunCard)
  }

  /**
   * Get artifacts for a job
   */
  async getArtifacts(jobId: string): Promise<any[]> {
    const response = await fetch(this.buildUrl(`/api/analyses/${jobId}/artifacts`))
    
    if (!response.ok) {
      throw new Error(`Failed to fetch artifacts: ${response.statusText}`)
    }
    
    const data = await response.json()
    if (!data || typeof data !== 'object') {
      return []
    }
    return Array.isArray(data.artifacts) ? data.artifacts : []
  }

  /**
   * Get recorded step summaries for a job
   */
  async getJobSteps(jobId: string): Promise<StepSummary[]> {
    try {
      const response = await fetch(this.buildUrl(`/api/analyses/${jobId}/steps`))
      if (!response.ok) {
        if (response.status === 404) {
          return []
        }
        throw new Error(`Failed to fetch job steps: ${response.statusText}`)
      }

      const data = await response.json()
      if (!data || typeof data !== 'object' || !Array.isArray(data.steps)) {
        return []
      }

      return data.steps.map((step: any): StepSummary => ({
        stepId: step.step_id ?? step.stepId ?? 'unknown-step',
        name: step.name ?? undefined,
        state: step.state ?? 'unknown',
        executionTimeMs: step.execution_time_ms ?? step.executionTimeMs ?? undefined,
        runDir: step.run_dir ?? step.runDir ?? undefined,
        error: step.error ?? undefined,
        violations: Array.isArray(step.violations)
          ? step.violations
              .map(mapViolation)
              .filter((v): v is Violation => v !== null)
          : undefined,
      }))
    } catch (error) {
      console.warn('Falling back to empty steps due to error:', error)
      return []
    }
  }

  /**
   * Add annotation to artifact
   */
  async addAnnotation(
    jobId: string,
    artifactId: string,
    annotation: string
  ): Promise<void> {
    const response = await fetch(
      this.buildUrl(`/api/analyses/${jobId}/artifacts/${artifactId}/annotate`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ annotation })
      }
    )
    
    if (!response.ok) {
      throw new Error(`Failed to add annotation: ${response.statusText}`)
    }
  }

  /**
   * Export run card
   */
  async exportRunCard(jobId: string, format: 'json' | 'yaml' | 'pdf' = 'json'): Promise<Blob> {
    // If no baseUrl is supplied, go through Next.js proxy to avoid CORS
    const url = this.baseUrl
      ? this.buildUrl(`/api/analyses/${jobId}/runcard/export?format=${format}`)
      : `/api/analyses/${jobId}/runcard/export?format=${format}`

    const response = await fetch(url)
    
    if (!response.ok) {
      throw new Error(`Failed to export run card: ${response.statusText}`)
    }
    
    return await response.blob()
  }

  /**
   * Export canonical observation (JSON/YAML only).
   */
  async exportObservation(
    jobId: string,
    format: 'json' | 'yaml' = 'json',
    options?: ExportOptions
  ): Promise<Blob> {
    const params = new URLSearchParams({
      format,
      includeArtifacts: String(options?.includeArtifacts ?? true),
      includeProvenance: String(options?.includeProvenance ?? true),
      includeCitations: String(options?.includeCitations ?? true),
      includeEnvironment: String(options?.includeEnvironment ?? true),
    })

    // If no baseUrl is supplied, go through Next.js proxy to avoid CORS.
    const url = this.baseUrl
      ? this.buildUrl(`/api/analyses/${jobId}/observation/export?${params}`)
      : `/api/analyses/${jobId}/observation/export?${params}`

    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`Failed to export observation: ${response.statusText}`)
    }
    return await response.blob()
  }

  /**
   * Generate citations in various formats
   */
  formatCitations(citations: Citation[], format: 'apa' | 'bibtex' | 'chicago' = 'apa'): string {
    if (!citations?.length) {
      return ''
    }
    return citations.map(citation => {
      switch (format) {
        case 'apa':
          return this.formatAPA(citation)
        case 'bibtex':
          return this.formatBibTeX(citation)
        case 'chicago':
          return this.formatChicago(citation)
        default:
          return this.formatAPA(citation)
      }
    }).join('\n\n')
  }

  private formatAPA(citation: Citation): string {
    const authors = (citation.authors && citation.authors.length > 0)
      ? citation.authors.join(', ')
      : 'Unknown authors'
    const year = citation.year ?? 'n.d.'
    const title = citation.title
    const journal = citation.journal || ''
    const doi = citation.doi ? ` https://doi.org/${citation.doi}` : ''
    
    return `${authors} (${year}). ${title}. ${journal}${doi}`
  }

  private formatBibTeX(citation: Citation): string {
    const type = citation.type === 'paper' ? 'article' : 'misc'
    const key = citation.id
    const authors = (citation.authors && citation.authors.length > 0)
      ? citation.authors.join(' and ')
      : 'Unknown'
    
    return `@${type}{${key},
  title={${citation.title}},
  author={${authors}},
  year={${citation.year}}${citation.journal ? `,
  journal={${citation.journal}}` : ''}${citation.doi ? `,
  doi={${citation.doi}}` : ''}
}`
  }

  private formatChicago(citation: Citation): string {
    const authors = (citation.authors && citation.authors.length > 0)
      ? citation.authors.join(', ')
      : 'Unknown authors'
    const year = citation.year ?? 'n.d.'
    const title = `"${citation.title}"`
    const journal = citation.journal ? ` ${citation.journal}` : ''
    
    return `${authors}. ${title}.${journal} (${year}).`
  }

  /**
   * Calculate reproducibility score
   */
  calculateReproducibilityScore(runCard: LegacyRunCard): number {
    const explicit = (runCard as any)?.reproducibility?.score ?? (runCard as any)?.reproducibility_score
    if (typeof explicit === 'number' && Number.isFinite(explicit)) {
      const normalized = explicit > 1 ? (explicit <= 100 ? explicit / 100 : 1) : explicit
      return Math.max(0, Math.min(1, normalized))
    }

    let score = 0
    const weights = {
      hasDatasets: 20,
      hasTools: 20,
      hasParameters: 20,
      hasCitations: 15,
      hasProvenance: 15,
      hasVersions: 10
    }
    
    if (runCard.datasets && runCard.datasets.length > 0) score += weights.hasDatasets
    if (runCard.tools && runCard.tools.length > 0) score += weights.hasTools
    if (runCard.parameters && Object.keys(runCard.parameters).length > 0) score += weights.hasParameters
    if (runCard.citations && runCard.citations.length > 0) score += weights.hasCitations
    if (runCard.provenance && runCard.provenance.nodes.length > 0) score += weights.hasProvenance
    if (runCard.tools?.every(t => t.version)) score += weights.hasVersions
    
    return Math.min(score, 100) / 100
  }
}

// React hooks for evidence rail
import { useState, useEffect, useCallback, useMemo } from 'react'

export function useEvidenceRail(jobId: string | null) {
  const [evidenceData, setEvidenceData] = useState<EvidenceData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const integration = useMemo(() => new EvidenceRailIntegration(), [])

  const loadEvidence = useCallback(async () => {
    if (!jobId) {
      setEvidenceData(null)
      setLoading(false)
      setError(null)
      return
    }

    setLoading(true)
    setError(null)

    try {
      const data = await integration.getEvidenceData(jobId)
      setEvidenceData(data)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [integration, jobId])

  useEffect(() => {
    void loadEvidence()
  }, [loadEvidence])

  const addAnnotation = useCallback(async (artifactId: string, annotation: string) => {
    if (!jobId) return

    try {
      await integration.addAnnotation(jobId, artifactId, annotation)
      await loadEvidence()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      throw err
    }
  }, [integration, jobId, loadEvidence])

  const exportRunCard = useCallback(async (
    format: 'json' | 'yaml' | 'pdf' = 'json',
    options?: ExportOptions
  ) => {
    if (!jobId) return null

    try {
      const blob = format === 'pdf'
        ? await integration.exportRunCard(jobId, format)
        : await integration.exportObservation(jobId, format, options)

      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = format === 'pdf'
        ? `result_package_${jobId}.${format}`
        : `observation_${jobId}.${format}`
      a.click()
      URL.revokeObjectURL(url)

      return blob
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      throw err
    }
  }, [integration, jobId])

  const formatCitations = useCallback((format: 'apa' | 'bibtex' | 'chicago' = 'apa') => {
    if (!evidenceData?.citations?.length) return ''
    return integration.formatCitations(evidenceData.citations, format)
  }, [evidenceData, integration])

  const reproducibilityScore = evidenceData?.runCard
    ? integration.calculateReproducibilityScore(evidenceData.runCard)
    : null

  return {
    evidenceData,
    loading,
    error,
    addAnnotation,
    exportRunCard,
    formatCitations,
    reproducibilityScore,
    reload: loadEvidence,
  }
}

export { EvidenceRailIntegration, mapRunCardFromBackend }
export type { EvidenceData, LegacyRunCard, Citation, ProvenanceGraph, StepSummary }
