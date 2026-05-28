'use client'

import { ReactFlowProvider, type Edge, type Node } from 'reactflow'
import { useState, useCallback, useEffect, useRef } from 'react'
import yaml from 'js-yaml'
import { EnhancedPipelineVisualization } from '@/components/workflow/EnhancedPipelineVisualization'
import ToolPalette from '@/components/workflow/ToolPalette'
import PropertiesPanel from '@/components/workflow/PropertiesPanel'
import ExecutionPanel from '@/components/workflow/ExecutionPanel'
import { ResourceMonitor } from '@/components/pipeline/ResourceMonitor'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useLocalStorage } from '@/hooks/use-local-storage'
import { QuickPlanTab } from '@/components/pipeline/QuickPlanTab'
import { PlannerTracePanel } from '@/components/pipeline/PlannerTracePanel'
import type { PipelineNodeData } from '@/components/workflow/PipelineNode'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { openSSE } from '@/lib/api'
import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import type {
  ExecutePipelinePayload,
  PipelineExecutionResponse,
  PipelineExecutionStep
} from '@/types/pipeline'
import {
  Save,
  Download,
  Upload,
  Play,
  Settings,
  FileText,
  FilePlus,
  AlertCircle,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Terminal,
  Activity
} from 'lucide-react'

type PipelineSnapshot = {
  nodes: Node[]
  edges: Edge[]
}

const createEmptySnapshot = (): PipelineSnapshot => ({ nodes: [], edges: [] })

const cloneSnapshot = (snapshot: PipelineSnapshot): PipelineSnapshot =>
  JSON.parse(JSON.stringify(snapshot ?? createEmptySnapshot())) as PipelineSnapshot

type ExecutionStatus = 'success' | 'error' | 'warning' | 'running'

const mapExecutionStatus = (status: string): ExecutionStatus => {
  const normalized = status?.toLowerCase?.() ?? status
  switch (normalized) {
    case 'completed':
    case 'succeeded':
      return 'success'
    case 'failed':
    case 'timeout':
    case 'cancelled':
      return 'error'
    case 'running':
      return 'running'
    case 'retrying':
    case 'queued':
    case 'claimed':
    case 'pending':
    default:
      return 'warning'
  }
}

export default function PipelineBuilderPage() {
  const [isMounted, setIsMounted] = useState(false)
  const [activeTab, setActiveTab] = useState('visual')
  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [showProperties, setShowProperties] = useState(false)
  const [showToolPalette, setShowToolPalette] = useState(true)
  const [showExecutionPanel, setShowExecutionPanel] = useState(false)
  const [showResourceMonitor, setShowResourceMonitor] = useState(false)
  const [showPlannerTrace, setShowPlannerTrace] = useState(false)
  const [latestPlanResponse, setLatestPlanResponse] = useState<any>(null)
  const [pipelineId] = useState(`builder-${Date.now()}`)
  const [executionResults, setExecutionResults] = useState<any[]>([])
  const [isExecuting, setIsExecuting] = useState(false)
  const [resourceNodes, setResourceNodes] = useState<Record<string, PipelineNodeData>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false)
  const [templateYaml, setTemplateYaml] = useState('')
  const [templateValidationErrors, setTemplateValidationErrors] = useState<string[]>([])
  const [templateValidationWarnings, setTemplateValidationWarnings] = useState<string[]>([])
  const [templateSaveError, setTemplateSaveError] = useState<string | null>(null)
  const [templateSavePending, setTemplateSavePending] = useState(false)
  const [templateIsValid, setTemplateIsValid] = useState<boolean | null>(null)
  const jobStreamRef = useRef<EventSource | null>(null)
  const planStepsRef = useRef<PipelineExecutionStep[]>([])
  const nodeIdByStepIdRef = useRef<Record<string, string>>({})
  const stepTimingRef = useRef<Record<string, { start?: number }>>({})
  const [savedSnapshot, setSavedSnapshot] = useLocalStorage<PipelineSnapshot>(
    'br:pipeline-builder:snapshot',
    createEmptySnapshot()
  )
  const [loadedSnapshot, setLoadedSnapshot] = useState<PipelineSnapshot>(() => createEmptySnapshot())
  const [currentSnapshot, setCurrentSnapshot] = useState<PipelineSnapshot>(() => createEmptySnapshot())
  const isHydratedFromStorage = useRef(false)

  const normalizeNodeType = (value: any): PipelineNodeData['type'] => {
    return value === 'input' || value === 'analysis' || value === 'output' ? value : 'process'
  }

  const slugify = (value: string) => {
    if (!value) return ''
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
  }

  const sortNodesForTemplate = (snapshot: PipelineSnapshot) => {
    const nodes = snapshot.nodes ?? []
    const edges = snapshot.edges ?? []
    if (!nodes.length) return []

    const nodeById = new Map(nodes.map(node => [node.id, node]))
    const adjacency = new Map<string, string[]>()
    const inDegree = new Map<string, number>()

    nodes.forEach(node => {
      adjacency.set(node.id, [])
      inDegree.set(node.id, 0)
    })

    edges.forEach(edge => {
      if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) return
      adjacency.get(edge.source)?.push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
    })

    const sortByPosition = (a: Node, b: Node) => {
      const ax = a.position?.x ?? 0
      const bx = b.position?.x ?? 0
      if (ax !== bx) return ax - bx
      const ay = a.position?.y ?? 0
      const by = b.position?.y ?? 0
      return ay - by
    }

    const queue = nodes.filter(node => (inDegree.get(node.id) ?? 0) === 0).sort(sortByPosition)
    const ordered: Node[] = []

    while (queue.length) {
      const node = queue.shift()
      if (!node) break
      ordered.push(node)
      const nextNodes = adjacency.get(node.id) ?? []
      nextNodes.forEach(targetId => {
        const nextDegree = (inDegree.get(targetId) ?? 0) - 1
        inDegree.set(targetId, nextDegree)
        if (nextDegree === 0) {
          const targetNode = nodeById.get(targetId)
          if (targetNode) {
            queue.push(targetNode)
            queue.sort(sortByPosition)
          }
        }
      })
    }

    if (ordered.length !== nodes.length) {
      return [...nodes].sort(sortByPosition)
    }

    return ordered
  }

  const buildTemplateFromSnapshot = useCallback((snapshot: PipelineSnapshot) => {
    const now = new Date().toISOString()
    const compactTimestamp = now.replace(/[-:.TZ]/g, '')
    const nodes = snapshot.nodes ?? []
    const edges = snapshot.edges ?? []
    const orderedNodes = sortNodesForTemplate(snapshot)
    const stepNameByNodeId = new Map<string, string>()
    const usedStepNames = new Set<string>()

    orderedNodes.forEach((node, index) => {
      const baseName = slugify(
        (node.data as any)?.tool?.id ??
          (node.data as any)?.tool?.name ??
          node.data?.label ??
          `step_${index + 1}`
      )
      let stepName = baseName || `step_${index + 1}`
      let suffix = 1
      while (usedStepNames.has(stepName)) {
        stepName = `${baseName || 'step'}_${suffix}`
        suffix += 1
      }
      usedStepNames.add(stepName)
      stepNameByNodeId.set(node.id, stepName)
    })

    const dependsByNode = new Map<string, string[]>()
    edges.forEach(edge => {
      const sourceName = stepNameByNodeId.get(edge.source)
      const targetName = stepNameByNodeId.get(edge.target)
      if (!sourceName || !targetName) return
      const deps = dependsByNode.get(edge.target) ?? []
      if (!deps.includes(sourceName)) {
        deps.push(sourceName)
      }
      dependsByNode.set(edge.target, deps)
    })

    const tags = Array.from(
      new Set(
        nodes
          .map(node => (node.data as any)?.category ?? (node.data as any)?.tool?.category)
          .filter(Boolean) as string[]
      )
    )

    const steps = orderedNodes.map((node, index) => {
      const stepName = stepNameByNodeId.get(node.id) ?? `step_${index + 1}`
      const toolName =
        (node.data as any)?.tool?.id ??
        (node.data as any)?.tool?.name ??
        (node.data as any)?.metadata?.tool ??
        node.data?.label ??
        node.id
      const description =
        (node.data as any)?.tool?.description ??
        (node.data as any)?.metadata?.description ??
        `Run ${node.data?.label ?? toolName}`
      const parameters =
        node.data?.parameters && typeof node.data.parameters === 'object'
          ? node.data.parameters
          : {}
      const depends_on = dependsByNode.get(node.id) ?? []
      const step: Record<string, unknown> = {
        name: stepName,
        tool: toolName,
        description,
        parameters
      }
      if (depends_on.length) {
        step.depends_on = depends_on
      }
      return step
    })

    return {
      id: `pipeline_${compactTimestamp}`,
      name: `Pipeline Template ${now.slice(0, 10)}`,
      description: 'Generated from the pipeline builder canvas.',
      version: '1.0.0',
      category: 'custom',
      author: 'UI User',
      created_at: now,
      status: 'draft',
      tags,
      parameters: [],
      steps,
      outputs: {},
      metadata: {
        generated_from: 'pipeline_builder',
        pipeline_id: pipelineId,
        node_count: nodes.length,
        edge_count: edges.length
      }
    }
  }, [pipelineId])

  const buildTemplateYaml = useCallback(() => {
    const templateData = buildTemplateFromSnapshot(currentSnapshot)
    const payload = { templates: { [templateData.id]: templateData } }
    return yaml.dump(payload, { sortKeys: false, noRefs: true })
  }, [buildTemplateFromSnapshot, currentSnapshot])

  const parseTemplateYaml = useCallback((source: string) => {
    const parsed = yaml.load(source)
    if (!parsed || typeof parsed !== 'object') {
      throw new Error('Template YAML must parse to an object.')
    }

    if (Object.prototype.hasOwnProperty.call(parsed, 'templates')) {
      const templatesObj = (parsed as any).templates
      let normalizedTemplates: Record<string, unknown> | unknown[] | null = null

      if (templatesObj instanceof Map) {
        normalizedTemplates = Object.fromEntries(templatesObj)
      } else if (Array.isArray(templatesObj)) {
        normalizedTemplates = templatesObj
      } else if (typeof templatesObj === 'string') {
        try {
          const parsedTemplates = yaml.load(templatesObj)
          if (parsedTemplates && typeof parsedTemplates === 'object') {
            normalizedTemplates = parsedTemplates as Record<string, unknown>
          }
        } catch {
          normalizedTemplates = null
        }
      } else if (templatesObj && typeof templatesObj === 'object') {
        normalizedTemplates = templatesObj as Record<string, unknown>
      }

      if (!normalizedTemplates) {
        throw new Error('templates must be a mapping of template ids.')
      }

      const entries = Array.isArray(normalizedTemplates)
        ? normalizedTemplates.map((entry, index) => [String(index), entry] as const)
        : Object.entries(normalizedTemplates as Record<string, unknown>)

      if (entries.length !== 1) {
        throw new Error('Please provide exactly one template inside templates:.')
      }

      const [templateId, data] = entries[0]
      let normalizedEntry: Record<string, unknown> | null = null

      if (data && typeof data === 'object') {
        normalizedEntry = data as Record<string, unknown>
      } else if (typeof data === 'string') {
        try {
          const parsedEntry = yaml.load(data)
          if (parsedEntry && typeof parsedEntry === 'object') {
            normalizedEntry = parsedEntry as Record<string, unknown>
          }
        } catch {
          normalizedEntry = null
        }
      }

      if (!normalizedEntry) {
        throw new Error('Template entry must be an object.')
      }

      const payload = { ...normalizedEntry }
      if (!payload.id) {
        payload.id = templateId
      }
      return payload
    }

    return parsed as Record<string, unknown>
  }, [])

  const validateTemplateData = useCallback((templateData: Record<string, unknown>) => {
    const errors: string[] = []
    const warnings: string[] = []

    const idValue = typeof templateData.id === 'string' ? templateData.id.trim() : ''
    if (!idValue) errors.push('Template must have an id.')
    const nameValue = typeof templateData.name === 'string' ? templateData.name.trim() : ''
    if (!nameValue) errors.push('Template must have a name.')
    const versionValue = typeof templateData.version === 'string' ? templateData.version.trim() : ''
    if (!versionValue) errors.push('Template must have a version.')

    if (!templateData.category) {
      warnings.push('Template category is missing.')
    }
    if (!templateData.author) {
      warnings.push('Template author is missing.')
    }
    if (!templateData.created_at) {
      warnings.push('Template created_at is missing.')
    }

    const parametersValue = templateData.parameters
    if (parametersValue !== undefined) {
      if (!Array.isArray(parametersValue)) {
        errors.push('Template parameters must be a list.')
      } else {
        const paramNames = new Set<string>()
        parametersValue.forEach((param: any) => {
          const paramName = typeof param?.name === 'string' ? param.name.trim() : ''
          if (!paramName) {
            errors.push('All parameters must have a name.')
            return
          }
          if (paramNames.has(paramName)) {
            errors.push(`Duplicate parameter name: ${paramName}.`)
          }
          paramNames.add(paramName)
          if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(paramName)) {
            errors.push(`Invalid parameter name: ${paramName}.`)
          }
        })
      }
    }

    const stepsValue = templateData.steps
    if (!Array.isArray(stepsValue) || stepsValue.length === 0) {
      errors.push('Template must include at least one step.')
      return { errors, warnings }
    }

    const stepNames = new Set<string>()
    stepsValue.forEach((step: any, index: number) => {
      const stepName = typeof step?.name === 'string' ? step.name.trim() : ''
      if (!stepName) {
        errors.push(`Step ${index + 1} is missing a name.`)
        return
      }
      if (stepNames.has(stepName)) {
        errors.push(`Duplicate step name: ${stepName}.`)
      }
      stepNames.add(stepName)

      const toolName = typeof step?.tool === 'string' ? step.tool.trim() : ''
      if (!toolName) {
        errors.push(`Step '${stepName}' must specify a tool.`)
      }
    })

    const dependenciesMap = new Map<string, string[]>()
    stepsValue.forEach((step: any) => {
      const stepName = typeof step?.name === 'string' ? step.name.trim() : ''
      if (!stepName) return
      const rawDeps = step?.depends_on
      if (rawDeps === undefined || rawDeps === null) return
      const deps = Array.isArray(rawDeps) ? rawDeps : [rawDeps]
      const normalizedDeps = deps
        .map(dep => (typeof dep === 'string' ? dep.trim() : ''))
        .filter(dep => dep.length > 0)
      const invalidDeps = deps.filter(dep => typeof dep !== 'string' || !dep.trim())
      if (invalidDeps.length > 0) {
        errors.push(`Step '${stepName}' has invalid dependency values.`)
      }
      dependenciesMap.set(stepName, normalizedDeps)
      normalizedDeps.forEach(dep => {
        if (!stepNames.has(dep)) {
          errors.push(`Step '${stepName}' depends on unknown step: ${dep}.`)
        }
      })
    })

    const visited = new Set<string>()
    const stack = new Set<string>()
    const hasCycle = (node: string): boolean => {
      if (stack.has(node)) return true
      if (visited.has(node)) return false
      visited.add(node)
      stack.add(node)
      const deps = dependenciesMap.get(node) ?? []
      for (const dep of deps) {
        if (hasCycle(dep)) return true
      }
      stack.delete(node)
      return false
    }

    for (const stepName of Array.from(stepNames)) {
      if (hasCycle(stepName)) {
        errors.push('Template has circular dependencies.')
        break
      }
    }

    return { errors, warnings }
  }, [])

  const closeJobStream = useCallback(() => {
    if (jobStreamRef.current) {
      jobStreamRef.current.close()
      jobStreamRef.current = null
    }
    stepTimingRef.current = {}
  }, [])

  const resolvePlanStepByStepId = useCallback((stepId?: string) => {
    if (!stepId) return undefined
    const mappedNodeId = nodeIdByStepIdRef.current[stepId]
    if (mappedNodeId) {
      return planStepsRef.current.find(step => step.node_id === mappedNodeId)
    }
    const match = stepId.match(/step_(\d+)/)
    if (match) {
      const index = Number(match[1]) - 1
      if (Number.isFinite(index) && planStepsRef.current[index]) {
        return planStepsRef.current[index]
      }
    }
    return undefined
  }, [])

  const resolveNodeIdForStep = useCallback((stepId?: string) => {
    if (!stepId) return undefined
    const mappedNodeId = nodeIdByStepIdRef.current[stepId]
    if (mappedNodeId) return mappedNodeId
    const planStep = resolvePlanStepByStepId(stepId)
    return planStep?.node_id
  }, [resolvePlanStepByStepId])

  const updatePipelineNode = useCallback((nodeId: string, data: Record<string, any>) => {
    if (!nodeId) return
    window.dispatchEvent(
      new CustomEvent('pipeline:update-node', {
        detail: { nodeId, data }
      })
    )
  }, [])

  const updateExecutionResult = useCallback((nodeId: string, patch: Record<string, any>) => {
    setExecutionResults(prev => {
      const idx = prev.findIndex(result => result.nodeId === nodeId)
      if (idx === -1) {
        return [
          ...prev,
          {
            nodeId,
            tool: patch.tool ?? nodeId,
            status: patch.status ?? 'running',
            ...patch
          }
        ]
      }
      const next = [...prev]
      next[idx] = {
        ...next[idx],
        ...patch,
        nodeId,
      }
      return next
    })
  }, [])

  const updateResourceNode = useCallback((nodeId: string, update: Partial<PipelineNodeData>) => {
    setResourceNodes(prev => {
      const current = prev[nodeId]
      if (!current) {
        return prev
      }
      return {
        ...prev,
        [nodeId]: {
          ...current,
          ...update,
          resources: update.resources ?? current.resources,
          metadata: {
            ...current.metadata,
            ...(update.metadata || {}),
          }
        }
      }
    })
  }, [])

  const startJobStream = useCallback((jobId: string, steps: PipelineExecutionStep[] = []) => {
    closeJobStream()

    planStepsRef.current = steps
    nodeIdByStepIdRef.current = steps.reduce<Record<string, string>>((acc, step) => {
      acc[`step_${step.order + 1}`] = step.node_id
      return acc
    }, {})

    const streamPath = `/api/analyses/${jobId}/events`
    let source: EventSource | null = null
    try {
      source = openSSE(streamPath)
    } catch (err) {
      console.warn('Failed to open job SSE stream', err)
      setIsExecuting(false)
      updateExecutionResult('pipeline', {
        tool: 'Pipeline Builder',
        status: 'error',
        error: 'Failed to open job event stream.',
        timestamp: new Date().toISOString(),
      })
      return
    }

    jobStreamRef.current = source

    const handleStepEvent = (payload: any) => {
      const step = payload?.step ?? payload
      const stepId = step?.id ?? payload?.step_id
      const nodeId = resolveNodeIdForStep(stepId) ?? stepId ?? step?.name ?? step?.tool
      if (!nodeId) return
      const planStep = resolvePlanStepByStepId(stepId)
      const statusValue = mapExecutionStatus(step?.status ?? payload?.status ?? '')
      const output = step?.preview ?? payload?.preview
      const error = payload?.error ?? step?.error
      const timing = step?.timing ?? payload?.timing
      const durationField =
        typeof timing?.duration_ms === 'number'
          ? timing.duration_ms
          : typeof timing?.durationMs === 'number'
          ? timing.durationMs
          : undefined
      const startTimeValue = timing?.start_time ?? timing?.startTime
      const endTimeValue = timing?.end_time ?? timing?.endTime

      const timingKey = stepId || nodeId
      const timingState = stepTimingRef.current[timingKey] || {}
      if (!timingState.start && startTimeValue) {
        const parsedStart = Date.parse(startTimeValue)
        if (!Number.isNaN(parsedStart)) {
          timingState.start = parsedStart
        }
      }
      if (!timingState.start && statusValue === 'running') {
        timingState.start = Date.now()
      }
      if (timingState.start) {
        stepTimingRef.current[timingKey] = timingState
      }

      let durationMs = durationField
      if (durationMs === undefined && startTimeValue && endTimeValue) {
        const parsedStart = Date.parse(startTimeValue)
        const parsedEnd = Date.parse(endTimeValue)
        if (!Number.isNaN(parsedStart) && !Number.isNaN(parsedEnd)) {
          durationMs = parsedEnd - parsedStart
        }
      }
      if (
        durationMs === undefined &&
        timingState.start &&
        (statusValue === 'success' || statusValue === 'error')
      ) {
        durationMs = Date.now() - timingState.start
      }
      if (durationMs === undefined && timingState.start && statusValue === 'running') {
        durationMs = Date.now() - timingState.start
      }
      if (durationMs !== undefined && durationMs < 0) {
        durationMs = undefined
      }

      updateExecutionResult(nodeId, {
        tool: step?.tool ?? planStep?.tool ?? step?.name ?? planStep?.name ?? nodeId,
        status: statusValue,
        output: statusValue === 'success' ? output : undefined,
        error: statusValue === 'error' ? error || output : undefined,
        duration: durationMs,
        timestamp: new Date().toISOString(),
        recovery: payload?.recovery ?? step?.recovery,
        error_taxonomy: payload?.error_taxonomy ?? step?.metadata?.error_taxonomy,
      })

      if (statusValue === 'success' || statusValue === 'error') {
        delete stepTimingRef.current[timingKey]
      }
    }

    const handleResourceSnapshot = (snapshot: Record<string, any>) => {
      if (!snapshot) return
      Object.entries(snapshot).forEach(([nodeId, nodeSnapshot]) => {
        updateResourceNode(nodeId, {
          status: nodeSnapshot?.status ?? 'pending',
          progress: nodeSnapshot?.progress ?? 0,
          resources: nodeSnapshot?.resources ?? {},
        })
        updatePipelineNode(nodeId, {
          status: nodeSnapshot?.status ?? 'pending',
          progress: nodeSnapshot?.progress ?? 0,
          resources: nodeSnapshot?.resources ?? {},
        })
      })
    }

  const handleJobStatus = (status: string) => {
    if (!status) return
    const normalized = status.toLowerCase()
    const terminalStates = new Set(['completed', 'failed', 'cancelled', 'timeout'])
    if (terminalStates.has(normalized)) {
      setIsExecuting(false)
      closeJobStream()
    }
  }

    source.addEventListener('step', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        handleStepEvent(JSON.parse(message.data))
      } catch (err) {
        console.warn('Failed to parse step event', err)
      }
    })

    source.addEventListener('step_update', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        handleStepEvent(JSON.parse(message.data))
      } catch (err) {
        console.warn('Failed to parse step_update event', err)
      }
    })

    source.addEventListener('status', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        const payload = JSON.parse(message.data)
        handleJobStatus(payload?.status)
      } catch (err) {
        console.warn('Failed to parse status event', err)
      }
    })

    source.addEventListener('resource_update', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        const payload = JSON.parse(message.data)
        if (!payload?.node_id) return
        updateResourceNode(payload.node_id, {
          status: payload.status ?? 'pending',
          progress: payload.progress ?? 0,
          resources: payload.resources ?? {},
        })
        updatePipelineNode(payload.node_id, {
          status: payload.status ?? 'pending',
          progress: payload.progress ?? 0,
          resources: payload.resources ?? {},
        })
      } catch (err) {
        console.warn('Failed to parse resource_update event', err)
      }
    })

    source.addEventListener('resources', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        const payload = JSON.parse(message.data)
        handleResourceSnapshot(payload?.snapshot ?? payload)
      } catch (err) {
        console.warn('Failed to parse resources event', err)
      }
    })

    source.addEventListener('plan', (evt: Event) => {
      const message = evt as MessageEvent
      try {
        const payload = JSON.parse(message.data)
        const steps: PipelineExecutionStep[] = Array.isArray(payload?.steps)
          ? (payload.steps as PipelineExecutionStep[])
          : []
        if (steps.length > 0) {
          planStepsRef.current = steps
          nodeIdByStepIdRef.current = steps.reduce<Record<string, string>>((acc, step) => {
            if (step?.node_id && typeof step?.order === 'number') {
              acc[`step_${step.order + 1}`] = step.node_id
            }
            return acc
          }, {})
        }
      } catch (err) {
        console.warn('Failed to parse plan event', err)
      }
    })

    source.addEventListener('error', () => {
      console.warn('Job SSE stream error')
    })
  }, [closeJobStream, resolveNodeIdForStep, resolvePlanStepByStepId, updateExecutionResult, updatePipelineNode, updateResourceNode])

  useEffect(() => {
    setIsMounted(true)
  }, [])

  useEffect(() => {
    if (isHydratedFromStorage.current) return
    setLoadedSnapshot(cloneSnapshot(savedSnapshot))
    setCurrentSnapshot(cloneSnapshot(savedSnapshot))
    isHydratedFromStorage.current = true
  }, [savedSnapshot])

  useEffect(() => {
    return () => {
      closeJobStream()
    }
  }, [closeJobStream])

  const handleSnapshotChange = useCallback((snapshot: PipelineSnapshot) => {
    setCurrentSnapshot(cloneSnapshot(snapshot))
  }, [])

  const handleNodeSelect = useCallback((node: any) => {
    setSelectedNode(node)
    if (node) {
      setShowProperties(true)
    }
  }, [])

  const handleNodeUpdate = useCallback((nodeId: string, data: any) => {
    updatePipelineNode(nodeId, data)
    setResourceNodes(prev => {
      if (!prev[nodeId]) return prev

      const nextResources = data?.resources
        ? { ...prev[nodeId].resources, ...data.resources }
        : prev[nodeId].resources

      return {
        ...prev,
        [nodeId]: {
          ...prev[nodeId],
          ...data,
          resources: nextResources
        }
      }
    })
  }, [updatePipelineNode])

  const handleSavePipeline = useCallback(() => {
    const snapshotToSave = cloneSnapshot(currentSnapshot)
    setSavedSnapshot(snapshotToSave)
    console.log('Saved pipeline snapshot:', snapshotToSave)
  }, [currentSnapshot, setSavedSnapshot])
  
  const handleLoadPipeline = useCallback(() => {
    const snapshotToLoad = cloneSnapshot(savedSnapshot)
    setLoadedSnapshot(snapshotToLoad)
    setCurrentSnapshot(snapshotToLoad)
    setResourceNodes({})
    setExecutionResults([])
    setSelectedNode(null)
    console.log('Loaded pipeline snapshot:', snapshotToLoad)
  }, [savedSnapshot])

  const handleExportPipeline = useCallback(() => {
    const exportPayload = {
      pipelineId,
      generatedAt: new Date().toISOString(),
      nodes: currentSnapshot.nodes,
      edges: currentSnapshot.edges
    }

    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
      type: 'application/json'
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${pipelineId}-pipeline.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }, [pipelineId, currentSnapshot])

  const handleOpenTemplateDialog = useCallback(() => {
    const generatedYaml = buildTemplateYaml()
    setTemplateYaml(generatedYaml)
    setTemplateDialogOpen(true)
    setTemplateValidationErrors([])
    setTemplateValidationWarnings([])
    setTemplateSaveError(null)
    setTemplateIsValid(null)
  }, [buildTemplateYaml])

  const handleTemplateYamlChange = useCallback((value: string) => {
    setTemplateYaml(value)
    setTemplateValidationErrors([])
    setTemplateValidationWarnings([])
    setTemplateSaveError(null)
    setTemplateIsValid(null)
  }, [])

  const handleValidateTemplate = useCallback(() => {
    setTemplateSaveError(null)
    try {
      const payload = parseTemplateYaml(templateYaml)
      const { errors, warnings } = validateTemplateData(payload)
      setTemplateValidationErrors(errors)
      setTemplateValidationWarnings(warnings)
      setTemplateIsValid(errors.length === 0)
      return { payload, errors }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Template YAML is invalid.'
      setTemplateValidationErrors([message])
      setTemplateValidationWarnings([])
      setTemplateIsValid(false)
      return null
    }
  }, [parseTemplateYaml, templateYaml, validateTemplateData])

  const handleSaveTemplate = useCallback(async () => {
    const validation = handleValidateTemplate()
    if (!validation || validation.errors.length > 0) {
      return
    }
    setTemplateSavePending(true)
    setTemplateSaveError(null)
    try {
      await brainResearcherAPI.createWorkflowTemplate(validation.payload, true)
      setTemplateDialogOpen(false)
    } catch (err) {
      setTemplateSaveError(err instanceof Error ? err.message : 'Failed to save template.')
    } finally {
      setTemplateSavePending(false)
    }
  }, [handleValidateTemplate])

  const handleRunPipeline = useCallback(async () => {
    setIsExecuting(true)
    setShowExecutionPanel(true)
    setShowResourceMonitor(true)
    closeJobStream()

    if (!currentSnapshot.nodes.length) {
      setIsExecuting(false)
      setExecutionResults([
        {
          nodeId: 'pipeline',
          tool: 'Pipeline Builder',
          status: 'error',
          error: 'No pipeline nodes to execute. Add tools first.',
          timestamp: new Date().toISOString(),
        },
      ])
      return
    }

    const activeNodes = currentSnapshot.nodes

    const payload: ExecutePipelinePayload = {
      pipeline_id: pipelineId,
      name: `Pipeline ${pipelineId}`,
      nodes: activeNodes.map(node => ({
        id: node.id,
        label: node.data?.tool?.name ?? node.data?.label ?? node.id,
        tool: node.data?.tool?.name ?? node.data?.label ?? null,
        type: (node.data as any)?.type ?? node.type ?? null,
        category: (node.data as any)?.category ?? null,
        parameters: node.data?.parameters ?? {},
        metadata: {
          description: (node.data as any)?.description,
          summary: (node.data as any)?.summary,
          tags: (node.data as any)?.tags
        },
        config: {
          width: node.width,
          height: node.height
        },
        position: node.position
      })),
      edges: currentSnapshot.edges.map(edge => {
        const rawMetadata = edge.data && typeof edge.data === 'object' ? edge.data : {}
        const metadata = Object.fromEntries(
          Object.entries(rawMetadata).filter(([, value]) => typeof value !== 'function')
        )
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: (rawMetadata as any)?.label ?? edge.label ?? null,
          metadata
        }
      })
    }

    try {
      const response: PipelineExecutionResponse = await brainResearcherAPI.executePipeline(payload)

      if (!response.steps || response.steps.length === 0) {
        throw new Error('Pipeline execution response did not include steps')
      }

      const now = new Date().toISOString()
      const initialResults = response.steps.map(step => ({
        nodeId: step.node_id,
        tool: step.tool,
        status: mapExecutionStatus(step.status),
        output: step.summary ?? undefined,
        timestamp: now
      }))

      setExecutionResults(initialResults)
      startJobStream(response.job_id, response.steps)

      const resourceState = response.steps.reduce<Record<string, PipelineNodeData>>((acc, step) => {
        const snapshot = response.resource_snapshot[step.node_id]
        const typeValue = normalizeNodeType(snapshot?.node_type)
        acc[step.node_id] = {
          label: snapshot?.label ?? step.name,
          type: typeValue,
          status: snapshot?.status === 'completed'
            ? 'completed'
            : snapshot?.status === 'running'
            ? 'running'
            : 'pending',
          progress: snapshot?.progress ?? 0,
          resources: snapshot?.resources ?? {},
          metadata: {
            tool: step.tool,
            category: snapshot?.node_type ?? undefined,
            description: step.summary ?? undefined
          }
        }
        return acc
      }, {})

      setResourceNodes(resourceState)

      response.steps.forEach(step => {
        const snapshot = resourceState[step.node_id]
        if (!snapshot) return
        updatePipelineNode(step.node_id, {
          status: snapshot.status,
          progress: snapshot.progress,
          resources: snapshot.resources,
          metadata: snapshot.metadata
        })
      })
    } catch (error) {
      console.error('Pipeline execution failed:', error)
      setIsExecuting(false)
      setExecutionResults([
        {
          nodeId: 'pipeline',
          tool: 'Pipeline Builder',
          status: 'error',
          error: error instanceof Error ? error.message : 'Pipeline execution failed',
          timestamp: new Date().toISOString(),
        },
      ])
    }
  }, [
    currentSnapshot.edges,
    currentSnapshot.nodes,
    pipelineId,
    updatePipelineNode,
    startJobStream,
    closeJobStream
  ])
  
  return (
    <NavigationWrapper>
      {/* Don't render pipeline builder on server to avoid hydration mismatch */}
      {!isMounted ? (
        <div suppressHydrationWarning className="flex items-center justify-center h-screen bg-gray-50">
          <div className="text-center">
            <div className="inline-flex items-center gap-2">
              <div className="h-4 w-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
              <span className="text-gray-600">Loading pipeline builder...</span>
            </div>
          </div>
        </div>
      ) : (
        <div suppressHydrationWarning className="min-h-screen bg-gray-50">

      {/* Tabs Navigation */}
      <div className="fixed top-16 left-0 right-0 z-10 bg-white border-b">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <div className="max-w-7xl mx-auto px-4">
            <TabsList className="grid w-full max-w-md grid-cols-2">
              <TabsTrigger value="visual">Visual Builder</TabsTrigger>
              <TabsTrigger value="quickplan">Quick Plan</TabsTrigger>
            </TabsList>
          </div>
        </Tabs>
      </div>

      {/* Tab Content */}
      <div className="mt-[4rem]">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <AdvancedViewBanner canonicalHref="/studio" />
        </div>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsContent value="visual" className="mt-0">
            {/* Toolbar for Visual Builder */}
            <div className="fixed top-28 left-0 right-0 z-10 bg-white border-b px-4 py-2">
        <div className="flex items-center justify-between max-w-full">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowToolPalette(!showToolPalette)}
            >
              {showToolPalette ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              Tools
            </Button>
            <div className="h-6 w-px bg-gray-300" />
            <Button variant="ghost" size="sm" onClick={handleSavePipeline}>
              <Save className="h-4 w-4 mr-2" />
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={handleLoadPipeline}>
              <Upload className="h-4 w-4 mr-2" />
              Load
            </Button>
            <Button variant="ghost" size="sm" onClick={handleExportPipeline}>
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
            <Button variant="ghost" size="sm" onClick={handleOpenTemplateDialog}>
              <FilePlus className="h-4 w-4 mr-2" />
              Save as Template
            </Button>
          </div>
          
          <div className="flex items-center gap-2">
            <Button variant="default" size="sm" onClick={handleRunPipeline} disabled={isExecuting}>
              <Play className="h-4 w-4 mr-2" />
              {isExecuting ? 'Running...' : 'Run Pipeline'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowExecutionPanel(!showExecutionPanel)}
              className={showExecutionPanel ? 'bg-gray-100' : ''}
            >
              <Terminal className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowResourceMonitor(!showResourceMonitor)}
              className={showResourceMonitor ? 'bg-gray-100' : ''}
            >
              <Activity className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowProperties(!showProperties)}
            >
              <Settings className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowPlannerTrace(true)}
              className={showPlannerTrace ? 'bg-gray-100' : ''}
            >
              <FileText className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
      
      <div className="flex h-[calc(100vh-12rem)] mt-[4rem]">
        {/* Left sidebar - Tool Palette */}
        {showToolPalette && (
          <div className="w-72 border-r bg-white shadow-sm overflow-hidden flex flex-col">
            <div className="p-4 border-b bg-gray-50">
              <h3 className="font-semibold text-sm text-gray-700">Neuroimaging Tools</h3>
              <p className="text-xs text-gray-500 mt-1">Drag tools to the canvas</p>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <ToolPalette
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
              />
            </div>
          </div>
        )}
        
        {/* Main canvas area */}
        <div className="flex-1 relative bg-gray-50">
          <ReactFlowProvider>
            <EnhancedPipelineVisualization
              pipelineId={pipelineId}
              initialNodes={loadedSnapshot.nodes}
              initialEdges={loadedSnapshot.edges}
              onNodeSelect={handleNodeSelect}
              onSnapshotChange={handleSnapshotChange}
              showTimeline={true}
              showMinimap={true}
              className="h-full"
            />
          </ReactFlowProvider>
        </div>
        
        {/* Right sidebar - Properties Panel */}
        <Sheet open={showProperties && !!selectedNode} onOpenChange={setShowProperties}>
          <SheetContent side="right" className="w-96 p-0">
            <SheetHeader className="p-4 border-b">
              <SheetTitle>Node Properties</SheetTitle>
            </SheetHeader>
            <div className="p-4 overflow-y-auto h-[calc(100vh-10rem)]">
              {selectedNode && (
                <PropertiesPanel
                  node={selectedNode}
                  onClose={() => setShowProperties(false)}
                  onUpdate={handleNodeUpdate}
                />
              )}
            </div>
          </SheetContent>
        </Sheet>

        {/* Planner Trace Drawer */}
        <Sheet open={showPlannerTrace} onOpenChange={setShowPlannerTrace}>
          <SheetContent side="right" className="w-[520px] max-w-full p-0">
            <SheetHeader className="p-4 border-b">
              <SheetTitle>Planner Trace</SheetTitle>
            </SheetHeader>
            <div className="p-4 overflow-y-auto h-[calc(100vh-10rem)]">
              <PlannerTracePanel plan={latestPlanResponse} />
            </div>
          </SheetContent>
        </Sheet>

        {/* Save as Template Dialog */}
        <Dialog open={templateDialogOpen} onOpenChange={setTemplateDialogOpen}>
          <DialogContent className="max-w-4xl">
            <DialogHeader>
              <DialogTitle>Save as Template</DialogTitle>
              <DialogDescription>
                Generate a workflow template from the current pipeline graph. Edit the YAML, validate it, then save.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <Textarea
                value={templateYaml}
                onChange={(event) => handleTemplateYamlChange(event.target.value)}
                className="min-h-[320px] font-mono text-xs"
              />

              {templateSaveError && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{templateSaveError}</AlertDescription>
                </Alert>
              )}

              {templateValidationErrors.length > 0 && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    <div className="font-semibold">Validation errors</div>
                    <ul className="list-disc pl-5">
                      {templateValidationErrors.map((error, index) => (
                        <li key={`template-error-${index}`}>{error}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}

              {templateValidationWarnings.length > 0 && (
                <Alert>
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    <div className="font-semibold">Validation warnings</div>
                    <ul className="list-disc pl-5">
                      {templateValidationWarnings.map((warning, index) => (
                        <li key={`template-warning-${index}`}>{warning}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}

              {templateIsValid && templateValidationErrors.length === 0 && (
                <Alert>
                  <CheckCircle className="h-4 w-4" />
                  <AlertDescription>Template validation passed.</AlertDescription>
                </Alert>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleValidateTemplate} disabled={templateSavePending}>
                Validate
              </Button>
              <Button onClick={handleSaveTemplate} disabled={templateSavePending}>
                {templateSavePending ? 'Saving...' : 'Save Template'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Execution Panel - Bottom drawer */}
        {showExecutionPanel && (
          <div className="fixed bottom-0 left-0 right-0 z-40 bg-white border-t shadow-lg" style={{ height: '300px' }}>
            <ExecutionPanel
              results={executionResults}
              isExecuting={isExecuting}
              onClose={() => setShowExecutionPanel(false)}
            />
          </div>
        )}

        {/* Resource Monitor - Right side panel */}
        {showResourceMonitor && (
          <div className="fixed right-4 top-20 z-30 w-96">
            <Card className="shadow-xl">
              <ResourceMonitor
                pipelineId={pipelineId}
                nodes={resourceNodes}
                className="h-96"
                showHistory={true}
              />
            </Card>
          </div>
        )}
      </div>
          </TabsContent>

          <TabsContent value="quickplan" className="mt-0">
            <div className="bg-gray-50 min-h-[calc(100vh-12rem)] pt-10 pb-12">
              <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
                <QuickPlanTab
                  onPlanResponse={setLatestPlanResponse}
                  onOpenPlannerTrace={() => setShowPlannerTrace(true)}
                />
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </div>
      </div>
      )}
    </NavigationWrapper>
  )
}
