"use client"

import { useState, useEffect } from 'react'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { KGPipeline, AgentPlanResponse, PlanRequest } from '@/types/kg-responses'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { PromotedBadge } from '@/components/ui/promoted-badge'
import { CopyButton } from '@/components/ui/copy-button'
import { buildPlanCurl } from '@/lib/curl-builder'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Sparkles,
  ChevronRight,
  ChevronDown,
  Loader2,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Settings,
  Code
} from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'

const MODALITY_OPTIONS = [
  { value: 'fMRI', label: 'fMRI - Functional MRI' },
  { value: 'dMRI', label: 'dMRI - Diffusion MRI' },
  { value: 'sMRI', label: 'sMRI - Structural MRI' },
  { value: 'MEG', label: 'MEG - Magnetoencephalography' },
  { value: 'EEG', label: 'EEG - Electroencephalography' },
  { value: 'PET', label: 'PET - Positron Emission Tomography' },
  { value: 'CT', label: 'CT - Computed Tomography' },
  { value: 'iEEG', label: 'iEEG - Intracranial EEG' },
]

type QuickPlanTabProps = {
  onPlanResponse?: (plan: AgentPlanResponse | null) => void
  onOpenPlannerTrace?: () => void
}

export function QuickPlanTab({ onPlanResponse, onOpenPlannerTrace }: QuickPlanTabProps) {
  // Step 1: Configuration state
  const [pipelines, setPipelines] = useState<KGPipeline[]>([])
  const [loadingPipelines, setLoadingPipelines] = useState(true)
  const [selectedPipeline, setSelectedPipeline] = useState<string>('')
  const [selectedModalities, setSelectedModalities] = useState<string[]>([])
  const [inputsJSON, setInputsJSON] = useState('{}')

  // Step 2: Plan results state
  const [planResponse, setPlanResponse] = useState<AgentPlanResponse | null>(null)
  const [loadingPlan, setLoadingPlan] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)

  // Advanced controls
  const [useKGHints, setUseKGHints] = useState(true)
  const [kgHintWeight, setKgHintWeight] = useState([0.5])
  const [promotedWeight, setPromotedWeight] = useState([0.3])
  const [debugSelection, setDebugSelection] = useState(true)

  // UI state
  const [currentStep, setCurrentStep] = useState<1 | 2>(1)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [payloadOpen, setPayloadOpen] = useState(false)

  // Fetch pipelines on mount
  useEffect(() => {
    const fetchPipelines = async () => {
      try {
        const response = await brainResearcherAPI.fetchKGPipelines()
        setPipelines(response.pipelines || [])
      } catch (err) {
        console.error('Error fetching pipelines:', err)
      } finally {
        setLoadingPipelines(false)
      }
    }
    fetchPipelines()
  }, [])

  const handleGeneratePlan = async () => {
    if (!selectedPipeline || selectedModalities.length === 0) {
      setPlanError('Please select a pipeline and at least one modality')
      return
    }

    setLoadingPlan(true)
    setPlanError(null)

    try {
      let inputs = {}
      try {
        inputs = JSON.parse(inputsJSON || '{}')
      } catch (e) {
        throw new Error('Invalid JSON in inputs field')
      }

      const payload: PlanRequest = {
        pipeline: selectedPipeline,
        domain: 'neuroimaging',
        modality: selectedModalities,
        inputs,
        debug_selection: debugSelection,
        use_kg_hints: useKGHints,
        kg_hint_weight: kgHintWeight[0],
        promoted_weight: promotedWeight[0],
      }

      const response = await brainResearcherAPI.requestPlan(payload)
      setPlanResponse(response)
      onPlanResponse?.(response)
      setCurrentStep(2)
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : 'Failed to generate plan')
      console.error('Error generating plan:', err)
      onPlanResponse?.(null)
    } finally {
      setLoadingPlan(false)
    }
  }

  const handleReplan = () => {
    handleGeneratePlan()
  }

  const handleReset = () => {
    setCurrentStep(1)
    setPlanResponse(null)
    setPlanError(null)
    onPlanResponse?.(null)
  }

  const formatReason = (reason: any) => {
    if (typeof reason === 'string') return { text: reason, multiline: false }
    try {
      return { text: JSON.stringify(reason, null, 2), multiline: true }
    } catch {
      return { text: String(reason), multiline: false }
    }
  }

  const renderBehaviorPolicyOptions = (reasons: any[] | null | undefined) => {
    if (!Array.isArray(reasons)) return null
    const entry = reasons.find(
      (r) => r && typeof r === 'object' && r.code === 'behavior_policy_options'
    )
    if (!entry) return null
    const table = entry.table as string | undefined
    const policies = Array.isArray(entry.policies) ? entry.policies : []
    const policyIds = policies
      .map((p: any) => p?.policy_id)
      .filter((p: any) => typeof p === 'string' && p.trim().length > 0)
    return { table, policyIds, policies }
  }

  const getCandidateScore = (candidate: any): number | null => {
    if (!candidate) return null
    if (typeof candidate.score === 'number') return candidate.score
    if (typeof candidate.final_score === 'number') return candidate.final_score
    if (typeof candidate.metadata?.catalog_score === 'number') return candidate.metadata.catalog_score
    return null
  }

  const getPlanConfidence = (plan: any): number | null => {
    const v = plan?.run_summary?.plan_conf ?? plan?.plan_conf ?? plan?.confidence_score
    return typeof v === 'number' ? v : null
  }

  const getCurrentPayload = (): PlanRequest => ({
    pipeline: selectedPipeline,
    domain: 'neuroimaging',
    modality: selectedModalities,
    inputs: JSON.parse(inputsJSON || '{}'),
    debug_selection: debugSelection,
    use_kg_hints: useKGHints,
    kg_hint_weight: kgHintWeight[0],
    promoted_weight: promotedWeight[0],
  })

  const handleModalityToggle = (modality: string) => {
    setSelectedModalities(prev =>
      prev.includes(modality)
        ? prev.filter(m => m !== modality)
        : [...prev, modality]
    )
  }

  return (
    <div className="space-y-6">
      {/* Stepper indicator */}
      <div className="flex items-center gap-4">
        <div className={`flex items-center gap-2 ${currentStep === 1 ? 'text-blue-600 font-semibold' : 'text-gray-500'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
            currentStep === 1 ? 'bg-blue-600 text-white' : 'bg-gray-200'
          }`}>
            1
          </div>
          <span>Configure</span>
        </div>
        <ChevronRight className="h-4 w-4 text-gray-400" />
        <div className={`flex items-center gap-2 ${currentStep === 2 ? 'text-blue-600 font-semibold' : 'text-gray-500'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
            currentStep === 2 ? 'bg-blue-600 text-white' : 'bg-gray-200'
          }`}>
            2
          </div>
          <span>Review Plan</span>
        </div>
      </div>

      {/* Step 1: Configuration */}
      {currentStep === 1 && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-blue-600" />
                Generate Pipeline Plan
              </CardTitle>
              <CardDescription>
                Select a pipeline template and modality to get AI-recommended tools
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Pipeline selection */}
              <div className="space-y-2">
                <Label htmlFor="pipeline">Pipeline Template</Label>
                {loadingPipelines ? (
                  <div className="flex items-center gap-2 text-gray-500">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Loading pipelines...</span>
                  </div>
                ) : (
                  <Select value={selectedPipeline} onValueChange={setSelectedPipeline}>
                    <SelectTrigger id="pipeline">
                      <SelectValue placeholder="Choose a pipeline..." />
                    </SelectTrigger>
                    <SelectContent>
                      {pipelines.map(pipeline => (
                        <SelectItem key={pipeline.id} value={pipeline.id}>
                          {pipeline.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {selectedPipeline && pipelines.find(p => p.id === selectedPipeline)?.description && (
                  <p className="text-sm text-gray-600">
                    {pipelines.find(p => p.id === selectedPipeline)?.description}
                  </p>
                )}
              </div>

              {/* Modality selection */}
              <div className="space-y-3">
                <Label>Modality (select one or more)</Label>
                <div className="grid grid-cols-2 gap-3">
                  {MODALITY_OPTIONS.map(option => (
                    <div key={option.value} className="flex items-center space-x-2">
                      <Checkbox
                        id={option.value}
                        checked={selectedModalities.includes(option.value)}
                        onCheckedChange={() => handleModalityToggle(option.value)}
                      />
                      <label
                        htmlFor={option.value}
                        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                      >
                        {option.label}
                      </label>
                    </div>
                  ))}
                </div>
              </div>

              {/* Optional inputs */}
              <div className="space-y-2">
                <Label htmlFor="inputs">Inputs (JSON, optional)</Label>
                <Textarea
                  id="inputs"
                  value={inputsJSON}
                  onChange={(e) => setInputsJSON(e.target.value)}
                  placeholder="Enter JSON inputs"
                  className="font-mono text-sm"
                  rows={3}
                />
              </div>

              {/* Advanced controls */}
              <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
                <CollapsibleTrigger asChild>
                  <Button variant="outline" size="sm" className="w-full">
                    <Settings className="h-4 w-4 mr-2" />
                    Advanced Controls
                    {advancedOpen ? <ChevronDown className="h-4 w-4 ml-auto" /> : <ChevronRight className="h-4 w-4 ml-auto" />}
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-4 space-y-4">
                  {/* Use KG hints toggle */}
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label>Use Knowledge Graph Hints</Label>
                      <p className="text-sm text-gray-500">
                        Incorporate KG tool metadata in selection
                      </p>
                    </div>
                    <Switch
                      checked={useKGHints}
                      onCheckedChange={setUseKGHints}
                    />
                  </div>

                  {/* KG hint weight slider */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>KG Hint Weight</Label>
                      <span className="text-sm text-gray-600">{kgHintWeight[0].toFixed(2)}</span>
                    </div>
                    <Slider
                      value={kgHintWeight}
                      onValueChange={setKgHintWeight}
                      min={0}
                      max={1}
                      step={0.1}
                      disabled={!useKGHints}
                    />
                  </div>

                  {/* Promoted weight slider */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>Promoted Tool Weight</Label>
                      <span className="text-sm text-gray-600">{promotedWeight[0].toFixed(2)}</span>
                    </div>
                    <Slider
                      value={promotedWeight}
                      onValueChange={setPromotedWeight}
                      min={0}
                      max={1}
                      step={0.1}
                    />
                  </div>

                  {/* Debug selection toggle */}
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label>Debug Selection</Label>
                      <p className="text-sm text-gray-500">
                        Show selection reasons and candidates
                      </p>
                    </div>
                    <Switch
                      checked={debugSelection}
                      onCheckedChange={setDebugSelection}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>

              {/* Error display */}
              {planError && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{planError}</AlertDescription>
                </Alert>
              )}

              {/* Generate button */}
              <Button
                onClick={handleGeneratePlan}
                disabled={!selectedPipeline || selectedModalities.length === 0 || loadingPlan}
                className="w-full"
                size="lg"
              >
                {loadingPlan ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Generating Plan...
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4 mr-2" />
                    Generate Plan
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Step 2: Plan Results */}
      {currentStep === 2 && planResponse && (
        <div className="space-y-6">
          {/* Plan Summary (always visible) */}
          <Card>
            <CardContent className="py-4 flex flex-wrap items-center gap-2">
              {(() => {
                const conf = getPlanConfidence(planResponse)
                if (conf === null) return (
                  <Badge variant="outline">Plan confidence: N/A</Badge>
                )
                return (
                  <Badge variant="outline">Plan confidence: {Math.round(conf * 100)}%</Badge>
                )
              })()}
              <Badge variant="secondary">
                Chosen tool: {planResponse.chosen_tool_name || planResponse.chosen_tool}
              </Badge>
              {Array.isArray((planResponse as any).planner_events) &&
                (planResponse as any).planner_events.some((e: any) => e?.event_type === 'recovery_triggered') && (
                  <Badge variant="destructive">Recovery used</Badge>
                )}
              {typeof planResponse.run_summary?.uncertainty_penalty === 'number' &&
                planResponse.run_summary.uncertainty_penalty >= 0.05 && (
                  <Badge variant="outline" className="text-yellow-700 border-yellow-300">
                    High uncertainty
                  </Badge>
                )}
              {onOpenPlannerTrace && (
                <Button size="sm" variant="outline" onClick={onOpenPlannerTrace}>
                  Open Planner Trace
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Chosen Tool Card */}
          <Card className="border-2 border-blue-600">
            <CardHeader>
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    Chosen Tool
                  </CardTitle>
                  <CardDescription className="mt-1">
                    AI-selected tool for your pipeline
                  </CardDescription>
                </div>
                {planResponse.metadata?.is_promoted !== undefined && planResponse.metadata.is_promoted && (
                  <PromotedBadge />
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <h3 className="text-2xl font-bold text-gray-900">
                  {planResponse.chosen_tool_name || planResponse.chosen_tool}
                </h3>
                {planResponse.chosen_family && (
                  <Badge variant="secondary" className="mt-2">
                    Family: {planResponse.chosen_family}
                  </Badge>
                )}
              </div>

              {/* Selection Reasons */}
                  {planResponse.selection_reasons && planResponse.selection_reasons.length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2">Selection Reasons</h4>
                      <ul className="space-y-2">
                        {planResponse.selection_reasons.map((reason, idx) => {
                      const fmt = formatReason(reason)
                      return (
                        <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                          <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                          <span className={fmt.multiline ? 'whitespace-pre-wrap font-mono text-xs' : ''}>
                            {fmt.text}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}

              {/* Mask / constraint reasons (default-on) */}
              {Array.isArray(planResponse.mask_reasons) && planResponse.mask_reasons.length > 0 && (
                <div>
                  <h4 className="font-medium mb-2">Constraint / Mask Reasons</h4>
                  <ul className="space-y-2">
                    {planResponse.mask_reasons.slice(0, 10).map((v, idx) => (
                      <li key={`${v.code}-${idx}`} className="flex items-start gap-2 text-sm text-gray-700">
                        <AlertCircle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
                        <span className="font-mono text-xs text-gray-900">{v.code}</span>
                        <span className="flex-1">{v.message}</span>
                        {v.blocking ? (
                          <Badge variant="destructive" className="text-[10px]">blocking</Badge>
                        ) : (
                          <Badge variant="outline" className="text-[10px]">
                            {v.severity || 'warn'}
                          </Badge>
                        )}
                      </li>
                    ))}
                  </ul>
                  {planResponse.mask_reasons.length > 10 && (
                    <div className="text-xs text-gray-500 mt-2">
                      +{planResponse.mask_reasons.length - 10} more…
                    </div>
                  )}
                </div>
              )}

              {/* Behavior policy picker if available */}
              {(() => {
                const info = renderBehaviorPolicyOptions(planResponse.selection_reasons)
                if (!info || !info.policyIds?.length) return null
                const currentInputs = JSON.parse(inputsJSON || '{}')
                const currentPolicy = currentInputs?.policy_id || currentInputs?.policy || ''
                return (
                  <div className="border rounded-md p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm font-medium">Behavior Policy</div>
                        <div className="text-xs text-muted-foreground">Applies to behavior.qc_scan/export_bids</div>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          if (info.table) {
                            navigator.clipboard.writeText(info.table).catch(() => undefined)
                          }
                        }}
                      >
                        Copy table
                      </Button>
                    </div>
                    {info.policies && info.policies.length > 0 && (
                      <div className="overflow-auto">
                        <table className="w-full text-[11px] border border-border rounded">
                          <thead className="bg-muted/40">
                            <tr>
                              <th className="px-2 py-1 text-left">policy_id</th>
                              <th className="px-2 py-1 text-left">rt_min</th>
                              <th className="px-2 py-1 text-left">rt_max</th>
                              <th className="px-2 py-1 text-left">acc_min</th>
                              <th className="px-2 py-1 text-left">miss_max</th>
                              <th className="px-2 py-1 text-left">notes</th>
                            </tr>
                          </thead>
                          <tbody>
                            {info.policies.map((p: any) => (
                              <tr key={p.policy_id}>
                                <td className="px-2 py-1 font-mono">{p.policy_id}</td>
                                <td className="px-2 py-1">{p.rt_min_sec ?? '-'}</td>
                                <td className="px-2 py-1">{p.rt_max_sec ?? '-'}</td>
                                <td className="px-2 py-1">{p.accuracy_min ?? '-'}</td>
                                <td className="px-2 py-1">{p.miss_rate_max ?? '-'}</td>
                                <td className="px-2 py-1 max-w-[200px] truncate">
                                  {Array.isArray(p.notes) ? p.notes.join(' | ') : p.notes ?? '-'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {info.table && (
                      <pre className="bg-muted/60 text-[11px] font-mono p-2 rounded whitespace-pre-wrap max-h-32 overflow-auto">
                        {info.table}
                      </pre>
                    )}
                    <div className="space-y-2">
                      <Label className="text-xs">Choose policy_id</Label>
                      <Select
                        value={currentPolicy}
                        onValueChange={(val) => {
                          try {
                            const parsed = JSON.parse(inputsJSON || '{}')
                            parsed.policy_id = val
                            setInputsJSON(JSON.stringify(parsed, null, 2))
                            setPlanResponse((prev) =>
                              prev
                                ? {
                                    ...prev,
                                    selection_reasons: prev.selection_reasons,
                                  }
                                : prev
                            )
                          } catch (e) {
                            console.error('Failed to set policy_id', e)
                          }
                        }}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="behavior_default_v1" />
                        </SelectTrigger>
                        <SelectContent>
                          {info.policyIds.map((pid: string) => (
                            <SelectItem key={pid} value={pid}>
                              {pid}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )
              })()}

              {/* Metadata */}
              {planResponse.metadata && (
                <div className="flex flex-wrap gap-2 pt-2">
                  {planResponse.metadata.selection_time_ms !== undefined && (
                    <Badge variant="outline">
                      Selected in {planResponse.metadata.selection_time_ms}ms
                    </Badge>
                  )}
                  {planResponse.metadata.kg_hint_score !== undefined && (
                    <Badge variant="outline">
                      KG Score: {planResponse.metadata.kg_hint_score.toFixed(2)}
                    </Badge>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Candidates (if debug enabled) */}
                  {planResponse.candidates && planResponse.candidates.length > 0 && (
                    <Collapsible>
                      <CollapsibleTrigger asChild>
                        <Card className="cursor-pointer hover:bg-gray-50">
                          <CardHeader>
                            <div className="flex items-center justify-between">
                              <CardTitle className="text-base">
                                Other Candidates ({planResponse.candidates.length})
                              </CardTitle>
                              <ChevronRight className="h-4 w-4" />
                            </div>
                          </CardHeader>
                        </Card>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="space-y-3 mt-3">
                          {planResponse.candidates.map((candidate, idx) => (
                            <Card key={idx}>
                              <CardHeader className="pb-3">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <CardTitle className="text-sm">
                                      {candidate.tool_name || (candidate as any).tool_id || candidate.tool}
                                    </CardTitle>
                                    {candidate.metadata?.is_promoted && <PromotedBadge showIcon={false} />}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {candidate.source && (
                                      <Badge variant="outline">{candidate.source}</Badge>
                                    )}
                                    <Badge variant={candidate.available === false ? 'destructive' : 'secondary'}>
                                      {candidate.available === false ? 'Unavailable' : 'Available'}
                                    </Badge>
                                    <Badge variant="outline">
                                      {(() => {
                                        const score = getCandidateScore(candidate)
                                        return score !== null ? `Score: ${score.toFixed(2)}` : 'Score: N/A'
                                      })()}
                                    </Badge>
                                  </div>
                                </div>
                              </CardHeader>
                              {((candidate.reasons && candidate.reasons.length > 0) || candidate.unavailable_reason || candidate.explanation) && (
                                <CardContent className="pt-0">
                                  <ul className="space-y-1">
                                    {[
                                      ...(candidate.reasons || []),
                                      ...(candidate.unavailable_reason ? [candidate.unavailable_reason] : []),
                                      candidate.explanation,
                                    ]
                                      .filter(Boolean)
                                      .map((reason, ridx) => {
                                      const fmt = formatReason(reason)
                                      return (
                                        <li key={ridx} className="text-xs text-gray-600 flex items-start gap-1">
                                          <span>•</span>
                                          <span className={fmt.multiline ? 'whitespace-pre-wrap font-mono' : ''}>
                                            {fmt.text}
                                          </span>
                                        </li>
                                      )
                                    })}
                                  </ul>
                                </CardContent>
                              )}
                            </Card>
                          ))}
                </div>
              </CollapsibleContent>
            </Collapsible>
          )}

          {/* Request Payload */}
          <Collapsible open={payloadOpen} onOpenChange={setPayloadOpen}>
            <CollapsibleTrigger asChild>
              <Card className="cursor-pointer hover:bg-gray-50">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Code className="h-4 w-4" />
                      Request Payload
                    </CardTitle>
                    {payloadOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </div>
                </CardHeader>
              </Card>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <Card className="mt-3">
                <CardContent className="pt-6">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <Label className="text-sm font-medium">JSON Payload</Label>
                      <CopyButton
                        content={JSON.stringify(getCurrentPayload(), null, 2)}
                        label="Copy JSON"
                        variant="outline"
                        size="sm"
                      />
                    </div>
                    <pre className="bg-gray-50 p-4 rounded-lg text-xs overflow-x-auto">
                      {JSON.stringify(getCurrentPayload(), null, 2)}
                    </pre>

                    <div className="flex items-center justify-between pt-2 border-t">
                      <Label className="text-sm font-medium">cURL Command</Label>
                      <CopyButton
                        content={buildPlanCurl(getCurrentPayload(), debugSelection)}
                        label="Copy cURL"
                        variant="outline"
                        size="sm"
                      />
                    </div>
                    <pre className="bg-gray-50 p-4 rounded-lg text-xs overflow-x-auto">
                      {buildPlanCurl(getCurrentPayload(), debugSelection)}
                    </pre>
                  </div>
                </CardContent>
              </Card>
            </CollapsibleContent>
          </Collapsible>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <Button onClick={handleReset} variant="outline">
              <ChevronRight className="h-4 w-4 mr-2 rotate-180" />
              Back to Configuration
            </Button>
            <Button onClick={handleReplan} disabled={loadingPlan}>
              {loadingPlan ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Re-planning...
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Re-plan with Current Settings
                </>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
