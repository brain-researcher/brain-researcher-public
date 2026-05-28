'use client'

import { useState, useEffect } from 'react'
import {
  Database, 
  Wrench, 
  FileText, 
  Download, 
  Copy, 
  ExternalLink,
  BookOpen,
  Calendar,
  Hash,
  Save,
  Loader2,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Clock,
  XCircle,
  AlertTriangle,
  Workflow
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { ChatRunCard, Citation } from '@/types/chat'
import { BranchTimeline } from './branch-timeline'
import { useToast } from '@/hooks/use-toast'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import { useEvidenceRail } from '@/lib/evidence-rail-integration'
import { RunCardExporter } from './run-card-exporter'
import { cn } from '@/lib/utils'
import type { ExportOptions } from '@/lib/evidence-rail-integration'
import type { EvidenceData } from '@/lib/evidence-rail-integration'

interface EvidenceRailProps {
  runCard?: ChatRunCard
  jobId?: string
  className?: string
  transferAvailable?: boolean
  onTransferToPipeline?: () => void
  onEvidenceDataChange?: (data: EvidenceData | null) => void
}

function CitationItem({ citation }: { citation: Citation }) {
  const { toast } = useToast()

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast({
      title: "Copied to clipboard",
      description: "Citation copied successfully"
    })
  }

  const formatCitation = () => {
    if (citation.type === 'paper' && citation.authors && citation.year) {
      return `${citation.authors.join(', ')} (${citation.year}). ${citation.title}.`
    }
    return citation.title
  }

  return (
    <div className="p-3 border rounded-lg space-y-2">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="font-medium text-sm">{citation.title}</div>
          {citation.authors && (
            <div className="text-xs text-muted-foreground">
              {citation.authors.join(', ')}
              {citation.year && ` (${citation.year})`}
            </div>
          )}
          {citation.description && (
            <div className="text-xs text-muted-foreground mt-1">
              {citation.description}
            </div>
          )}
        </div>
        
        <div className="flex items-center gap-1 ml-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => copyToClipboard(formatCitation())}
          >
            <Copy className="h-3 w-3" />
          </Button>
          
          {(citation.doi || citation.url) && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              asChild
            >
              <a 
                href={citation.doi ? `https://doi.org/${citation.doi}` : citation.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            </Button>
          )}
        </div>
      </div>
      
      {citation.doi && (
        <div className="text-xs text-muted-foreground">
          DOI: {citation.doi}
        </div>
      )}
    </div>
  )
}

export function EvidenceRail({
  runCard,
  jobId,
  className,
  transferAvailable,
  onTransferToPipeline,
  onEvidenceDataChange,
}: EvidenceRailProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'citations' | 'reproducibility'>('overview')
  const [isExportModalOpen, setIsExportModalOpen] = useState(false)
  const [showSelectedOnly, setShowSelectedOnly] = useState(false)
  const { toast } = useToast()
  const { enabled: advancedMode } = useAdvancedMode()
  
  // Dynamic evidence loading when we have a jobId
  const {
    evidenceData,
    loading: evidenceLoading,
    error: evidenceError,
    addAnnotation,
    exportRunCard,
    formatCitations,
    reproducibilityScore,
    reload: reloadEvidence
  } = useEvidenceRail(jobId)

  useEffect(() => {
    onEvidenceDataChange?.(evidenceData)
  }, [evidenceData, onEvidenceDataChange])
  
  // Use dynamic evidence data if available, otherwise use provided runCard
  // Prefer mappedRunCard (already mapped to frontend schema) over raw runCard
  const currentRunCard = evidenceData?.mappedRunCard || runCard
  const currentCitations = evidenceData?.citations || runCard?.citations || []
  const currentArtifacts = currentRunCard?.artifacts || evidenceData?.artifacts || []
  const stepSummaries = evidenceData?.steps || []
  const diagnosticsSummary = evidenceData?.diagnosticsSummary
  const behaviorDiag = diagnosticsSummary && (diagnosticsSummary as any).behavior
  const violations = evidenceData?.violations ?? []
  const branchEvents = currentRunCard?.execution?.branchEvents || []
  const plannerState = currentRunCard?.execution?.plannerState
  const executionSteps = currentRunCard?.execution?.steps || []
  const hasBranchData = branchEvents.length > 0
    || executionSteps.some((step) => step.branchRank !== undefined || step.branchGroupId || step.branchStepId)
    || Boolean(plannerState && Object.keys(plannerState).length > 0)

  const handleExportRunCard = async (
    format: 'json' | 'yaml' | 'pdf',
    options: ExportOptions
  ) => {
    if (!jobId || !exportRunCard) {
      throw new Error('No job ID available for export')
    }
    await exportRunCard(format, options)
  }

  const saveToProject = () => {
    toast({
      title: "Saved to Project",
      description: "This run has been saved to your current project"
    })
  }

  const copyRunDir = async (runDir: string) => {
    try {
      await navigator.clipboard.writeText(runDir)
      toast({
        title: "Work directory copied",
        description: runDir
      })
    } catch (error) {
      toast({
        title: "Failed to copy work directory",
        description: String(error),
        variant: "destructive"
      })
    }
  }

  const formatDuration = (durationMs?: number) => {
    if (!durationMs || Number.isNaN(durationMs)) {
      return null
    }
    if (durationMs < 1000) {
      return `${Math.round(durationMs)} ms`
    }
    if (durationMs < 60_000) {
      return `${(durationMs / 1000).toFixed(1)} s`
    }
    const minutes = Math.floor(durationMs / 60_000)
    const seconds = Math.round((durationMs % 60_000) / 1000)
    return `${minutes}m ${seconds}s`
  }

  const renderStateIcon = (state: string) => {
    const normalized = state.toLowerCase()
    if (normalized === 'succeeded' || normalized === 'completed') {
      return <CheckCircle className="h-4 w-4 text-emerald-600" />
    }
    if (normalized === 'failed') {
      return <XCircle className="h-4 w-4 text-red-600" />
    }
    if (normalized === 'running' || normalized === 'in_progress') {
      return <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
    }
    if (normalized === 'cancelling' || normalized === 'pending') {
      return <Clock className="h-4 w-4 text-muted-foreground" />
    }
    return <AlertCircle className="h-4 w-4 text-muted-foreground" />
  }

  // Show loading state
  if (evidenceLoading) {
    return (
      <div className={cn('w-80 border-l bg-background p-4', className)}>
        <div className="text-center text-muted-foreground">
          <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin" />
          <p className="text-sm">Loading evidence...</p>
        </div>
      </div>
    )
  }

  // Show error state
  if (evidenceError) {
    return (
      <div className={cn('w-80 border-l bg-background p-4', className)}>
        <div className="text-center text-muted-foreground">
          <AlertCircle className="h-8 w-8 mx-auto mb-2 text-red-500" />
          <p className="text-sm mb-2">Failed to load evidence</p>
          <Button variant="outline" size="sm" onClick={reloadEvidence}>
            <RefreshCw className="h-3 w-3 mr-1" />
            Retry
          </Button>
        </div>
      </div>
    )
  }

  // Show empty state
  if (!currentRunCard) {
    return (
      <div className={cn('w-80 border-l bg-muted/20 p-4', className)}>
        <div className="text-center text-muted-foreground">
          <FileText className="h-8 w-8 mx-auto mb-2" />
          <p className="text-sm">Start a run to see evidence and provenance</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('w-80 border-l bg-background p-4 overflow-y-auto', className)}>
      <div className="space-y-4">
        {/* Header */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">Evidence & Provenance</h3>
            {jobId && reloadEvidence && (
              <Button variant="ghost" size="sm" onClick={reloadEvidence}>
                <RefreshCw className="h-3 w-3" />
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Complete traceability for reproducible research
          </p>
          <p className="text-xs text-muted-foreground">
            Result Package: Methods · Parameters · Artifacts (for reproducibility)
          </p>
          {reproducibilityScore !== null && reproducibilityScore !== undefined && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Reproducibility Score:</span>
              <span className={`text-xs font-bold ${
                reproducibilityScore >= 0.8 ? 'text-green-600' : 
                reproducibilityScore >= 0.6 ? 'text-yellow-600' : 'text-red-600'
              }`}>
                {Math.round(reproducibilityScore * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={saveToProject} className="flex-1">
            <Save className="h-3 w-3 mr-1" />
            Save
          </Button>
          <Button variant="outline" size="sm" onClick={() => setIsExportModalOpen(true)} className="flex-1">
            <Download className="h-3 w-3 mr-1" />
            Export
          </Button>
        </div>

        {advancedMode && transferAvailable && onTransferToPipeline && (
          <Button
            variant="default"
            size="sm"
            className="w-full"
            onClick={onTransferToPipeline}
          >
            <Workflow className="h-4 w-4 mr-2" />
            Open in Pipeline Builder
          </Button>
        )}

        <Separator />

        {/* Tab navigation */}
        <div className="flex border-b">
          {[
            { id: 'overview', label: 'Overview' },
            { id: 'citations', label: 'Citations' },
            { id: 'reproducibility', label: 'Reproduce' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="space-y-4">
          {activeTab === 'overview' && (
            <>
              {/* Diagnostics */}
              {diagnosticsSummary && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <AlertCircle className="h-4 w-4" />
                      Diagnostics
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Summary of warnings/errors and suggested next actions
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-3">
                    <div className="grid grid-cols-3 gap-2">
                      <div className="rounded border p-2">
                        <div className="text-[10px] text-muted-foreground">Warnings</div>
                        <div className="text-sm font-semibold">
                          {diagnosticsSummary.counts?.warning ?? 0}
                        </div>
                      </div>
                      <div className="rounded border p-2">
                        <div className="text-[10px] text-muted-foreground">Errors</div>
                        <div className="text-sm font-semibold">
                          {diagnosticsSummary.counts?.error ?? 0}
                        </div>
                      </div>
                      <div className="rounded border p-2">
                        <div className="text-[10px] text-muted-foreground">Blocking</div>
                        <div className="text-sm font-semibold">
                          {diagnosticsSummary.counts?.blocking ?? 0}
                        </div>
                      </div>
                    </div>

                    {Array.isArray(diagnosticsSummary.top_codes) && diagnosticsSummary.top_codes.length > 0 && (
                      <div className="space-y-1">
                        <div className="text-xs font-medium">Top codes</div>
                        <div className="space-y-1">
                          {diagnosticsSummary.top_codes.slice(0, 6).map((item) => (
                            <div key={item.code} className="flex items-center justify-between text-xs">
                              <span className="font-mono text-muted-foreground truncate">{item.code}</span>
                              <span className="tabular-nums text-muted-foreground">{item.count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {Array.isArray(diagnosticsSummary.recommended_next_actions) &&
                      diagnosticsSummary.recommended_next_actions.length > 0 && (
                        <div className="space-y-1">
                          <div className="text-xs font-medium">Recommended next actions</div>
                          <ul className="space-y-1 text-xs text-muted-foreground list-disc pl-4">
                            {diagnosticsSummary.recommended_next_actions
                              .slice(0, 5)
                              .map((item, idx) => (
                                <li key={`${idx}-${item.action}`}>{item.action}</li>
                              ))}
                          </ul>
                        </div>
                      )}
                  </CardContent>
                </Card>
              )}

              {/* Behavior policies & hashes */}
              {behaviorDiag && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Hash className="h-4 w-4" />
                      Behavioral Data
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Policies and integrity hashes for behavior events/sidecars
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-2 text-xs">
                    {Array.isArray(behaviorDiag.policies) && behaviorDiag.policies.length > 0 && (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-muted-foreground">Policies</div>
                        <div className="flex flex-wrap gap-1">
                          {behaviorDiag.policies.map((p: string) => (
                            <span key={p} className="px-2 py-1 bg-muted rounded text-[11px] font-mono">
                              {p}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {(behaviorDiag.events_checksum || behaviorDiag.sidecar_checksum) && (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-muted-foreground">Hashes</div>
                        {behaviorDiag.events_checksum && (
                          <div className="flex items-center gap-2 break-all">
                            <span className="text-[11px] text-muted-foreground">events.tsv</span>
                            <code className="text-[11px]">{behaviorDiag.events_checksum}</code>
                          </div>
                        )}
                        {behaviorDiag.sidecar_checksum && (
                          <div className="flex items-center gap-2 break-all">
                            <span className="text-[11px] text-muted-foreground">events.json</span>
                            <code className="text-[11px]">{behaviorDiag.sidecar_checksum}</code>
                          </div>
                        )}
                      </div>
                    )}
                    {(behaviorDiag.events_path || behaviorDiag.sidecar_path) && (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-muted-foreground">Downloads</div>
                        <div className="flex flex-col gap-1 text-[11px]">
                          {behaviorDiag.events_path && (
                            <a
                              href={behaviorDiag.events_path}
                              className="text-primary hover:underline inline-flex items-center gap-1"
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              events.tsv <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                          {behaviorDiag.sidecar_path && (
                            <a
                              href={behaviorDiag.sidecar_path}
                              className="text-primary hover:underline inline-flex items-center gap-1"
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              events.json <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Violations */}
              {violations.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                      Violations
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Blocking/warning issues detected during preflight or postcheck
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-2">
                    {violations.slice(0, 6).map((v, idx) => (
                      <div key={`${v.code}-${idx}`} className="border rounded p-2 space-y-1">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="font-mono text-muted-foreground truncate">{v.code}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] uppercase ${
                              v.blocking
                                ? 'bg-red-100 text-red-800'
                                : v.severity === 'error'
                                  ? 'bg-amber-100 text-amber-800'
                                  : 'bg-slate-100 text-slate-700'
                            }`}
                          >
                            {v.blocking ? 'blocking' : v.severity ?? 'warn'}
                          </span>
                        </div>
                        <div className="text-xs">{v.message}</div>
                        {v.where?.stage && (
                          <div className="text-[10px] text-muted-foreground">
                            Stage: {v.where.stage}
                            {v.where.step_id ? ` · Step: ${v.where.step_id}` : ''}
                          </div>
                        )}
                        {v.suggested_fix && (
                          <div className="text-[11px] text-muted-foreground">
                            Fix: {v.suggested_fix}
                          </div>
                        )}
                      </div>
                    ))}
                    {violations.length > 6 && (
                      <div className="text-[11px] text-muted-foreground">
                        +{violations.length - 6} more…
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Dataset */}
          {currentRunCard.dataset && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Database className="h-4 w-4" />
                  Dataset
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0 space-y-2">
                <div>
                  <div className="font-medium text-sm">{currentRunCard.dataset.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {currentRunCard.dataset.source}
                    {currentRunCard.dataset.version && ` v${currentRunCard.dataset.version}`}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Steps */}
          {stepSummaries.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Wrench className="h-4 w-4" />
                  Execution Steps
                </CardTitle>
                <CardDescription className="text-xs">
                  Recorded step executions for this run
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0 space-y-2">
                <div className="flex flex-col gap-2">
                  {stepSummaries.map((step) => {
                    const state = (step.state || '').toLowerCase()
                    const isFailed = state === 'failed'
                    const isCompleted = state === 'completed' || state === 'succeeded'

                    return (
                      <div
                        key={step.stepId}
                        className={`rounded-md border p-3 space-y-2 transition-colors ${
                          isFailed
                            ? 'border-red-300 bg-red-50'
                            : isCompleted
                              ? 'border-emerald-200 bg-emerald-50/40'
                              : 'border-border/70'
                        }`}
                      >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="font-medium text-sm">
                            {step.name || step.stepId}
                          </div>
                          <div className="text-xs text-muted-foreground font-mono truncate">
                            {step.stepId}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {renderStateIcon(step.state)}
                          <span
                            className={`text-xs font-semibold uppercase tracking-wide ${
                              isFailed
                                ? 'text-red-700'
                                : isCompleted
                                  ? 'text-emerald-700'
                                  : 'text-muted-foreground'
                            }`}
                          >
                            {step.state}
                          </span>
                        </div>
                      </div>

                      {step.executionTimeMs && (
                        <div className="text-xs text-muted-foreground">
                          Duration: {formatDuration(step.executionTimeMs)}
                        </div>
                      )}

                      {step.error && (
                        <div className="mt-1 flex items-start gap-2 rounded bg-red-50 p-2 text-xs text-red-700">
                          <AlertCircle className="h-4 w-4 mt-0.5" />
                          <span className="whitespace-pre-wrap">{step.error}</span>
                        </div>
                      )}

                      {step.runDir && (
                        <div className="mt-1 flex items-center justify-between gap-2 rounded bg-muted/40 px-2 py-1">
                          <span className="text-[10px] font-mono truncate">{step.runDir}</span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-xs"
                            onClick={() => copyRunDir(step.runDir!)}
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            Copy path
                          </Button>
                        </div>
                      )}
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {hasBranchData && (
            <Card>
              <CardHeader className="pb-2 space-y-1">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Workflow className="h-4 w-4" />
                      Branch Timeline
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Fallback branches and outcomes captured from the result package
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Label htmlFor="branch-selected-only" className="text-xs text-muted-foreground">
                      Selected only
                    </Label>
                    <Switch
                      id="branch-selected-only"
                      checked={showSelectedOnly}
                      onCheckedChange={setShowSelectedOnly}
                    />
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <BranchTimeline
                  branchEvents={branchEvents}
                  plannerState={plannerState}
                  steps={executionSteps}
                  selectedOnly={showSelectedOnly}
                />
              </CardContent>
            </Card>
          )}

          {/* Tools */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                    <Wrench className="h-4 w-4" />
                    Tools & Versions
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
                  {currentRunCard.tools.map((tool, index) => (
                    <div key={index} className="flex justify-between text-sm">
                      <span>{tool.name}</span>
                      <span className="text-muted-foreground">{tool.version}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>

              {/* Parameters */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Parameters</CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
                    {JSON.stringify(currentRunCard.parameters, null, 2)}
                  </pre>
                </CardContent>
              </Card>

              {/* Artifacts */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Generated Artifacts</CardTitle>
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
              {currentArtifacts.map((artifact) => (
                    <div key={artifact.id} className="flex items-center justify-between text-sm">
                      <div>
                        <div className="font-medium">{artifact.name}</div>
                        <div className="text-xs text-muted-foreground">{artifact.type}</div>
                      </div>
                      <Button variant="ghost" size="sm" asChild>
                        <a href={artifact.url} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </Button>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </>
          )}

          {activeTab === 'citations' && (
            <div className="space-y-3">
              {currentCitations.length > 0 ? (
                currentCitations.map((citation, index) => (
                  <CitationItem key={index} citation={citation} />
                ))
              ) : (
                <div className="text-center text-muted-foreground py-8">
                  <BookOpen className="h-8 w-8 mx-auto mb-2" />
                  <p className="text-sm">No citations available</p>
                </div>
              )}
              {formatCitations && currentCitations.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Export Citations</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-2">
                    <div className="flex gap-1">
                      {['apa', 'bibtex', 'chicago'].map(format => (
                        <Button
                          key={format}
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            const formatted = formatCitations(format as any)
                            navigator.clipboard.writeText(formatted)
                            toast({
                              title: "Citations Copied",
                              description: `Citations in ${format.toUpperCase()} format copied to clipboard`
                            })
                          }}
                          className="text-xs"
                        >
                          {format.toUpperCase()}
                        </Button>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {activeTab === 'reproducibility' && (
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Calendar className="h-4 w-4" />
                    Execution Info
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span>Run ID:</span>
                    <span className="font-mono text-xs">{currentRunCard.id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Timestamp:</span>
                    <span>{currentRunCard.timestamp.toLocaleString()}</span>
                  </div>
                </CardContent>
              </Card>

              {currentRunCard.reproducibility && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Hash className="h-4 w-4" />
                      Reproducibility
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-2 text-sm">
                    {currentRunCard.reproducibility.score !== undefined && (
                      <div className="flex justify-between">
                        <span>Reproducibility Score:</span>
                        <span className="font-mono">{Math.round(currentRunCard.reproducibility.score * 100)}%</span>
                      </div>
                    )}
                    {currentRunCard.reproducibility.isReproducible !== undefined && (
                      <div className="flex justify-between">
                        <span>Is Reproducible:</span>
                        <span className={currentRunCard.reproducibility.isReproducible ? 'text-green-600' : 'text-red-600'}>
                          {currentRunCard.reproducibility.isReproducible ? 'Yes' : 'No'}
                        </span>
                      </div>
                    )}
                    {currentRunCard.reproducibility.randomSeed !== undefined && (
                      <div className="flex justify-between">
                        <span>Random Seed:</span>
                        <span className="font-mono">{currentRunCard.reproducibility.randomSeed}</span>
                      </div>
                    )}
                    {currentRunCard.reproducibility.checksums && Object.keys(currentRunCard.reproducibility.checksums).length > 0 && (
                      <div>
                        <div className="font-medium">Checksums:</div>
                        {Object.entries(currentRunCard.reproducibility.checksums).map(([key, value]) => (
                          <div key={key} className="font-mono text-xs text-muted-foreground break-all">
                            {key}: {value}
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              <div className="text-xs text-muted-foreground p-3 bg-muted rounded">
                <strong>Reproducibility Note:</strong> This Result Package contains all information 
                needed to reproduce this run. Download the JSON file and use it with 
                the same dataset to get identical results.
              </div>
            </div>
          )}
        </div>
        
        {/* Run Card Exporter Modal */}
        <RunCardExporter
          isOpen={isExportModalOpen}
          onClose={() => setIsExportModalOpen(false)}
          runCard={currentRunCard}
          jobId={jobId}
          onExport={handleExportRunCard}
        />
      </div>
    </div>
  )
}
