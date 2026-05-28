'use client'

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Network } from 'lucide-react'
import { CytoscapeGraph } from './CytoscapeGraph'
import { GraphErrorBoundary } from './GraphErrorBoundary'
import { CatalogHeader, ConceptSummary } from './CatalogHeader'
import { EvidencePanel } from './EvidencePanel'
import { EvidencePath, EvidencePathsPanel } from './EvidencePathsPanel'
import { GraphViewTabs, ViewMode } from './GraphViewTabs'
import { QueryBuilderPanel, QueryType } from './QueryBuilderPanel'
import { ConceptSearchPanel } from './ConceptSearchPanel'
import { ConceptTreeNode } from './ConceptTreeNode'
import { ExplorerDetailsPanel } from './ExplorerDetailsPanel'
import { KnowledgeGraphChatModal } from './KnowledgeGraphChatModal'
import {
  computeMappedConceptsFromSubgraph,
  inferExplorerNodeKind,
  isContrastStatmapEdgeType,
  isDatasetStatmapEdgeType,
  isOntologyDirectTaskConceptEdge,
} from './node-kinds'
import {
  resolveKgGraphUrl,
  resolveKgHealthUrl,
  resolveKgQueryUrl,
  resolveKgConceptsUrl,
  resolveKgConceptTreeUrl,
  resolveKgConceptUrl,
  resolveKgConceptSummaryUrl,
  resolveKgConceptEvidenceUrl,
  resolveKgConceptEvidencePathsUrl,
  resolveKgConceptChildrenUrl,
  resolveKgLensEntitiesUrl,
  resolveKgLensTaskTreeUrl,
  resolveKgLensEntitySummaryUrl,
  resolveKgLensEntityEvidenceUrl,
  resolveKgLensEntityEvidencePathsUrl,
} from '@/lib/service-endpoints'
import { useAuth } from '@/hooks/use-auth'

interface GraphNode {
  id: string
  label: string
  type: string
  size: number
  connections: number
  properties?: Record<string, any>
}

type GraphPayloadNode = {
  data: {
    id: string
    label: string
    type: string
    labels?: string[]
    degree?: number
    size?: number
    meta?: Record<string, any>
    overlay?: boolean
  }
}

type GraphPayloadEdge = {
  data: {
    id: string
    source: string
    target: string
    type?: string
    weight?: number
    confidence?: number
    overlay?: boolean
  }
}

type Concept = {
  id: string
  label: string
  display_label?: string
  category?: string | null
  collapsed_count?: number
  collapsed_ids?: string[]
  counts?: Record<string, number>
  family_id?: string | null
  family_label?: string | null
  family_description?: string | null
  subfamily_id?: string | null
  subfamily_label?: string | null
  paradigm_name?: string | null
  match_method?: string | null
  match_score?: number | null
}

type EvidenceGroups = {
  statmaps: any[]
  coords: any[]
  timeseries: any[]
  datasets: any[]
  papers: any[]
  tasks: any[]
  task_neighbors: any[]
  contrasts: any[]
  tools: any[]
  studies: any[]
}

type EvidenceCounts = {
  statmaps: number
  coords: number
  timeseries: number
  datasets: number
  papers: number
  tasks: number
  task_neighbors: number
  contrasts: number
  tools: number
  studies: number
}

const EMPTY_EVIDENCE_GROUPS: EvidenceGroups = {
  statmaps: [],
  coords: [],
  timeseries: [],
  datasets: [],
  papers: [],
  tasks: [],
  task_neighbors: [],
  contrasts: [],
  tools: [],
  studies: [],
}

const EMPTY_EVIDENCE_COUNTS: EvidenceCounts = {
  statmaps: 0,
  coords: 0,
  timeseries: 0,
  datasets: 0,
  papers: 0,
  tasks: 0,
  task_neighbors: 0,
  contrasts: 0,
  tools: 0,
  studies: 0,
}

const toSafeString = (value: unknown): string => (typeof value === 'string' ? value : '')

const toDisplayLabel = (value: unknown, fallback: string): string => {
  const label = toSafeString(value).trim()
  return label || fallback
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === 'object' && !Array.isArray(value))

const asRecordArray = <T,>(value: unknown): T[] =>
  Array.isArray(value)
    ? value.filter(isRecord).map((item) => item as T)
    : []

const resolveNodeId = (node: any, fallback: string): string =>
  toSafeString(node?.kg_id) || toSafeString(node?.id) || fallback

const resolveNodeLabel = (node: any, fallback: string): string =>
  toDisplayLabel(node?.label, toDisplayLabel(node?.name, fallback))

const resolveNodeType = (node: any): string =>
  toSafeString(node?.node_type) || toSafeString(node?.type) || 'unknown'

const buildGraphFromSubgraph = (subgraph: { nodes?: any[]; edges?: any[] }): { nodes: GraphPayloadNode[]; edges: GraphPayloadEdge[] } => {
  const rawNodes = Array.isArray(subgraph.nodes) ? subgraph.nodes : []
  const rawEdges = Array.isArray(subgraph.edges) ? subgraph.edges : []
  const degreeMap = new Map<string, number>()

  rawEdges.forEach((edge: any) => {
    const source = toSafeString(edge?.source) || toSafeString(edge?.start_node_id)
    const target = toSafeString(edge?.target) || toSafeString(edge?.end_node_id)
    if (!source || !target) return
    degreeMap.set(source, (degreeMap.get(source) || 0) + 1)
    degreeMap.set(target, (degreeMap.get(target) || 0) + 1)
  })

  const nodes = rawNodes.map((node: any, idx: number) => {
    const fallbackId = `overlay-node-${idx}`
    const id = resolveNodeId(node, fallbackId)
    const label = resolveNodeLabel(node, id)
    const type = resolveNodeType(node)
    const degree = degreeMap.get(id) || 0
    return {
      data: {
        id,
        label,
        type,
        labels: Array.isArray(node?.labels) ? node.labels : type ? [type] : [],
        degree,
        size: Math.max(1, degree || 1),
        meta: node?.properties || node?.props || {},
        overlay: true,
      },
    }
  })

  const edges = rawEdges.map((edge: any, idx: number) => {
    const source = toSafeString(edge?.source) || toSafeString(edge?.start_node_id)
    const target = toSafeString(edge?.target) || toSafeString(edge?.end_node_id)
    return {
      data: {
        id: toSafeString(edge?.id) || `${source}-${target}-${idx}`,
        source,
        target,
        type: toSafeString(edge?.type) || toSafeString(edge?.relation) || 'RELATED_TO',
        weight: edge?.properties?.weight ?? edge?.weight ?? 1,
        confidence: edge?.properties?.confidence ?? edge?.confidence,
        overlay: true,
      },
    }
  })

  return { nodes, edges }
}

const mergeGraphData = (
  base: { nodes: GraphPayloadNode[]; edges: GraphPayloadEdge[] },
  overlay: { nodes: GraphPayloadNode[]; edges: GraphPayloadEdge[] },
  markOverlay: boolean,
) => {
  const mergedNodesById = new Map<string, GraphPayloadNode>()
  base.nodes.forEach((node) => mergedNodesById.set(node.data.id, node))
  overlay.nodes.forEach((node) => {
    const existing = mergedNodesById.get(node.data.id)
    if (existing) {
      if (markOverlay) {
        existing.data.overlay = true
      }
      return
    }
    mergedNodesById.set(
      node.data.id,
      markOverlay ? node : { ...node, data: { ...node.data, overlay: undefined } },
    )
  })

  const edgeKey = (edge: GraphPayloadEdge) =>
    `${edge.data.source}|${edge.data.target}|${edge.data.type || ''}`
  const mergedEdgesByKey = new Map<string, GraphPayloadEdge>()
  base.edges.forEach((edge) => mergedEdgesByKey.set(edgeKey(edge), edge))
  overlay.edges.forEach((edge) => {
    const key = edgeKey(edge)
    if (mergedEdgesByKey.has(key)) {
      if (markOverlay) {
        const existing = mergedEdgesByKey.get(key)
        if (existing) existing.data.overlay = true
      }
      return
    }
    mergedEdgesByKey.set(
      key,
      markOverlay ? edge : { ...edge, data: { ...edge.data, overlay: undefined } },
    )
  })

  return {
    nodes: Array.from(mergedNodesById.values()),
    edges: Array.from(mergedEdgesByKey.values()),
  }
}

const deriveExplorerFromGraph = (
  nodes: GraphPayloadNode[],
  edges: GraphPayloadEdge[],
  selectedConceptId: string | null,
  setRelatedEdges: (value: RelatedGraphEdge[]) => void,
  setRelatedNodes: (value: RelatedGraphNode[]) => void,
  setTasks: (value: Array<{ id: string; label: string; datasetCount: number; description?: string; doi?: string; pmid?: string; neurostore_id?: string; source?: string }>) => void,
  setDatasets: (value: Array<{ id: string; label: string; source?: string; modalities?: string[]; source_repo_bucket?: string; source_repo_version?: string; source_repo_versions?: string[] }>) => void,
  setContrasts: (value: Array<{ id: string; label: string; source?: string; statmapCount?: number }>) => void,
  setMappedConceptsFn: (value: Array<{ id: string; label: string; source?: string }>) => void,
  setGraphStatsFn: (value: { nodes: number; edges: number; clusters: number; density: number }) => void,
) => {
  if (!selectedConceptId) {
    setRelatedEdges([])
    setRelatedNodes([])
    setTasks([])
    setDatasets([])
    setContrasts([])
    setMappedConceptsFn([])
    setGraphStatsFn({ nodes: nodes.length, edges: edges.length, clusters: 0, density: 0 })
    return
  }

  const nodeById = new Map<
    string,
    { label: string; type: string; labels: string[]; meta: Record<string, unknown> }
  >()
  nodes.forEach((node) => {
    nodeById.set(node.data.id, {
      label: node.data.label || node.data.id,
      type: node.data.type || 'unknown',
      labels: Array.isArray(node.data.labels) ? node.data.labels : [],
      meta: node.data.meta || {},
    })
  })

  const kindById = new Map<string, string>()
  const adjacency = new Map<string, Array<{ neighbor: string; edgeType?: string }>>()
  const pushAdj = (from: string, neighbor: string, edgeType?: string) => {
    if (!adjacency.has(from)) adjacency.set(from, [])
    adjacency.get(from)!.push({ neighbor, edgeType })
  }

  nodes.forEach((node) => {
    const kind = inferExplorerNodeKind({
      id: node.data.id,
      type: node.data.type,
      labels: node.data.labels,
      meta: node.data.meta,
    })
    kindById.set(node.data.id, kind)
  })

  edges.forEach((edge) => {
    pushAdj(edge.data.source, edge.data.target, edge.data.type)
    pushAdj(edge.data.target, edge.data.source, edge.data.type)
  })

  const directEdges = edges.filter(
    (edge) =>
      edge.data.source === selectedConceptId || edge.data.target === selectedConceptId,
  )
  const relatedEdgeSummaries: RelatedGraphEdge[] = directEdges.map((edge, idx) => {
    const sourceId = edge.data.source
    const targetId = edge.data.target
    const sourceNode = nodeById.get(sourceId)
    const targetNode = nodeById.get(targetId)
    const isOutgoing = sourceId === selectedConceptId
    const isOntologyDirect = isOntologyDirectTaskConceptEdge({
      edgeType: edge.data.type,
      source: {
        id: sourceId,
        type: sourceNode?.type,
        labels: sourceNode?.labels,
        meta: sourceNode?.meta as Record<string, any> | undefined,
      },
      target: {
        id: targetId,
        type: targetNode?.type,
        labels: targetNode?.labels,
        meta: targetNode?.meta as Record<string, any> | undefined,
      },
    })
    return {
      id: edge.data.id || `${sourceId}-${targetId}-${idx}`,
      sourceId,
      sourceLabel: sourceNode?.label || sourceId,
      sourceType: sourceNode?.type || 'unknown',
      targetId,
      targetLabel: targetNode?.label || targetId,
      targetType: targetNode?.type || 'unknown',
      relationType: edge.data.type || 'RELATED_TO',
      direction: isOutgoing ? 'outgoing' : 'incoming',
      isOntologyDirect,
    }
  })
  setRelatedEdges(relatedEdgeSummaries)

  const relatedNodeAccumulator = new Map<
    string,
    {
      id: string
      label: string
      type: string
      edgeCount: number
      relationTypes: Set<string>
    }
  >()
  relatedEdgeSummaries.forEach((edge) => {
    const neighborId = edge.direction === 'outgoing' ? edge.targetId : edge.sourceId
    const neighborNode = nodeById.get(neighborId)
    const existing = relatedNodeAccumulator.get(neighborId)
    if (existing) {
      existing.edgeCount += 1
      existing.relationTypes.add(edge.relationType)
      return
    }
    relatedNodeAccumulator.set(neighborId, {
      id: neighborId,
      label: neighborNode?.label || neighborId,
      type: neighborNode?.type || 'unknown',
      edgeCount: 1,
      relationTypes: new Set([edge.relationType]),
    })
  })

  const relatedNodeSummaries: RelatedGraphNode[] = Array.from(
    relatedNodeAccumulator.values(),
  )
    .map((node) => ({
      id: node.id,
      label: node.label,
      type: node.type,
      edgeCount: node.edgeCount,
      relationTypes: Array.from(node.relationTypes).sort(),
    }))
    .sort((a, b) => {
      if (b.edgeCount !== a.edgeCount) return b.edgeCount - a.edgeCount
      return a.label.localeCompare(b.label)
    })
  setRelatedNodes(relatedNodeSummaries)

  const datasetIds = new Set(
    nodes
      .filter((n) => kindById.get(n.data.id) === 'dataset')
      .map((n) => n.data.id),
  )
  const statmapIds = new Set(
    nodes
      .filter((n) => kindById.get(n.data.id) === 'statmap')
      .map((n) => n.data.id),
  )

  const taskNodes = nodes.filter((n) => kindById.get(n.data.id) === 'task')
  const tasksSummaries = taskNodes.map((t) => {
    const tid = t.data.id
    const datasetNeighbors = new Set<string>()
    const neighbors = adjacency.get(tid) || []
    neighbors.forEach(({ neighbor }) => {
      if (datasetIds.has(neighbor)) datasetNeighbors.add(neighbor)
    })
    neighbors.forEach(({ neighbor }) => {
      if (!statmapIds.has(neighbor)) return
      ;(adjacency.get(neighbor) || []).forEach(({ neighbor: dsNeighbor, edgeType }) => {
        if (datasetIds.has(dsNeighbor) && isDatasetStatmapEdgeType(edgeType)) {
          datasetNeighbors.add(dsNeighbor)
        }
      })
    })

    return {
      id: tid,
      label: t.data.label,
      datasetCount: datasetNeighbors.size,
      description: (t.data.meta as any)?.description,
      doi: (t.data.meta as any)?.doi,
      pmid: (t.data.meta as any)?.pmid,
      neurostore_id: (t.data.meta as any)?.neurostore_id,
      source: (t.data.meta as any)?.source,
    }
  })
  setTasks(tasksSummaries)

  const mapped = computeMappedConceptsFromSubgraph(
    selectedConceptId,
    nodes.map((n) => ({
      id: n.data.id,
      label: n.data.label,
      kind: kindById.get(n.data.id),
      source: (n.data.meta as any)?.source,
    })),
    edges.map((edge) => ({
      source: edge.data.source,
      target: edge.data.target,
      type: edge.data.type,
      confidence: edge.data.confidence,
    })),
  )
  setMappedConceptsFn(mapped)

  const datasetNodes = nodes.filter((n) => kindById.get(n.data.id) === 'dataset')
  const datasetsSummaries = datasetNodes.map((d) => {
    const did = d.data.id
    let smCount = 0
    ;(adjacency.get(did) || []).forEach(({ neighbor, edgeType }) => {
      if (statmapIds.has(neighbor) && isDatasetStatmapEdgeType(edgeType)) smCount += 1
    })
    return {
      id: did,
      label: d.data.label,
      source: (d.data.meta as any)?.source,
      modalities: (d.data.meta as any)?.modalities,
      source_repo_bucket: (d.data.meta as any)?.source_repo_bucket,
      source_repo_version: (d.data.meta as any)?.source_repo_version,
      source_repo_versions: (d.data.meta as any)?.source_repo_versions,
      statmapCount: smCount,
    }
  })
  setDatasets(datasetsSummaries)

  const contrastNodes = nodes.filter((n) => kindById.get(n.data.id) === 'contrast')
  const contrastsSummaries = contrastNodes.map((c) => {
    const cid = c.data.id
    let smCount = 0
    ;(adjacency.get(cid) || []).forEach(({ neighbor, edgeType }) => {
      if (statmapIds.has(neighbor) && isContrastStatmapEdgeType(edgeType)) smCount += 1
    })
    return {
      id: cid,
      label: c.data.label,
      source: (c.data.meta as any)?.source,
      statmapCount: smCount,
    }
  })
  setContrasts(contrastsSummaries.length > 0 ? contrastsSummaries : [])

  const totalNodes = nodes.length
  const totalEdges = edges.length
  const density =
    totalNodes > 1 ? Number(((2 * totalEdges) / (totalNodes * (totalNodes - 1))).toFixed(4)) : 0
  setGraphStatsFn({
    nodes: totalNodes,
    edges: totalEdges,
    clusters: 0,
    density,
  })
}

const parseEvidencePathsPayload = (payload: unknown): EvidencePath[] => {
  if (Array.isArray(payload)) {
    return payload as EvidencePath[]
  }
  if (!payload || typeof payload !== 'object') {
    return []
  }

  const payloadObject = payload as Record<string, unknown>
  const diagnostics =
    payloadObject.diagnostics && typeof payloadObject.diagnostics === 'object'
      ? (payloadObject.diagnostics as Record<string, unknown>)
      : null
  const groups =
    payloadObject.groups && typeof payloadObject.groups === 'object'
      ? (payloadObject.groups as Record<string, unknown>)
      : null

  const candidates: unknown[] = [
    payloadObject.paths,
    payloadObject.items,
    diagnostics?.paths,
    groups?.paths,
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate as EvidencePath[]
    }
  }
  return []
}

const parseConceptListPayload = (payload: unknown): Concept[] => {
  const normalizeConcepts = (items: unknown): Concept[] =>
    asRecordArray<Concept>(items)
      .map((item, index) => {
        const id = toDisplayLabel(item.id, `concept-${index}`)
        return {
          ...item,
          id,
          label: toDisplayLabel(item.label, id),
          display_label:
            item.display_label != null
              ? toDisplayLabel(item.display_label, id)
              : undefined,
        }
      })
      .filter((item) => item.id.length > 0)

  if (Array.isArray(payload)) {
    return normalizeConcepts(payload)
  }
  if (!payload || typeof payload !== 'object') {
    return []
  }
  const payloadObject = payload as Record<string, unknown>
  if (Array.isArray(payloadObject.items)) {
    return normalizeConcepts(payloadObject.items)
  }
  if (Array.isArray(payloadObject.concepts)) {
    return normalizeConcepts(payloadObject.concepts)
  }
  return []
}

const parseTaskTreePayload = (payload: unknown): TaskFamilyTreeNode[] => {
  if (!payload || typeof payload !== 'object') {
    return []
  }
  const payloadObject = payload as TaskTreePayload
  return asRecordArray<TaskFamilyTreeNode>(payloadObject.families)
}

const isUnavailablePayload = (
  payload: unknown,
): payload is { ok: false; error?: string; upstream_status?: number } => {
  if (!payload || typeof payload !== 'object') {
    return false
  }
  const candidate = payload as Record<string, unknown>
  return candidate.ok === false && typeof candidate.error === 'string'
}

const buildTaskTreeState = (families: TaskFamilyTreeNode[]) => {
  const flatTasks: Concept[] = []
  const familyTree: ConceptTreeNode[] = asRecordArray<TaskFamilyTreeNode>(
    families,
  ).map((family, familyIndex) => {
    const familyId = toDisplayLabel(family.id, `family-${familyIndex}`)
    const subfamilies = asRecordArray<TaskSubfamilyTreeNode>(family.children)
    return {
      id: `family:${familyId}`,
      label: toDisplayLabel(family.label, familyId),
      depth: 0,
      collapsedCount: family.task_count,
      hasChildren: subfamilies.length > 0,
      selectable: false,
      children: subfamilies.map((subfamily, subfamilyIndex) => {
        const subfamilyId = toDisplayLabel(
          subfamily.id,
          `${familyId}:subfamily-${subfamilyIndex}`,
        )
        const tasks = asRecordArray<Concept>(subfamily.children)
        return {
          id: `subfamily:${subfamilyId}`,
          label: toDisplayLabel(subfamily.label, subfamilyId),
          depth: 1,
          collapsedCount: subfamily.task_count,
          hasChildren: tasks.length > 0,
          selectable: false,
          children: tasks.map((task, taskIndex) => {
            const taskId = toDisplayLabel(
              task.id,
              `${subfamilyId}:task-${taskIndex}`,
            )
            const taskLabel = toDisplayLabel(
              task.display_label || task.label,
              taskId,
            )
            flatTasks.push({
              ...task,
              id: taskId,
              label: taskLabel,
              display_label: task.display_label
                ? toDisplayLabel(task.display_label, taskId)
                : taskLabel,
            })
            return {
              id: taskId,
              label: taskLabel,
              depth: 2,
              collapsedCount: task.collapsed_count,
              hasChildren: false,
              selectable: true,
              children: [],
            }
          }),
        }
      }),
    }
  })

  const defaultExpanded = familyTree
    .filter((node) => node.id !== TASK_UNMAPPED_FAMILY_NODE_ID)
    .slice(0, 4)
    .map((node) => node.id)

  return { flatTasks, familyTree, defaultExpanded }
}

const sanitizeTreeNode = (
  node: unknown,
  fallbackPrefix = 'node',
): ConceptTreeNode | null => {
  if (!isRecord(node)) return null
  const id = toDisplayLabel(node.id, `${fallbackPrefix}:unknown`)
  return {
    ...node,
    id,
    label: toDisplayLabel(node.label, id),
    depth: typeof node.depth === 'number' ? node.depth : 0,
    children: asRecordArray<ConceptTreeNode>(node.children)
      .map((child, index) => sanitizeTreeNode(child, `${id}:child:${index}`))
      .filter((child): child is ConceptTreeNode => child !== null),
  }
}

const RETRYABLE_STATUS_CODES = new Set([429, 500, 502, 503, 504])
const SERVICE_UNAVAILABLE_STATUS_CODES = new Set([500, 502, 503, 504])
const SERVICE_RECOVERY_POLL_MS = 30_000

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

const isAbortLikeError = (error: unknown): boolean => {
  if (error instanceof DOMException) {
    return error.name === 'AbortError'
  }
  if (error && typeof error === 'object' && 'name' in error) {
    return (error as { name?: unknown }).name === 'AbortError'
  }
  return false
}

const isExpectedServiceUnavailableError = (error: unknown): boolean => {
  if (isAbortLikeError(error)) return true
  const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase()
  return (
    message.includes('failed to fetch') ||
    message.includes('fetch failed') ||
    message.includes('networkerror') ||
    message.includes('network error') ||
    message.includes('load failed') ||
    message.includes('503') ||
    message.includes('502') ||
    message.includes('500')
  )
}

const logUnexpectedKgError = (message: string, error: unknown) => {
  if (isExpectedServiceUnavailableError(error)) return
  console.error(message, error)
}

const withTimeoutSignal = (outerSignal: AbortSignal | null | undefined, timeoutMs: number) => {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  let onAbort: (() => void) | null = null

  if (outerSignal) {
    if (outerSignal.aborted) {
      controller.abort()
    } else {
      onAbort = () => controller.abort()
      outerSignal.addEventListener('abort', onAbort, { once: true })
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timeout)
      if (outerSignal && onAbort) {
        outerSignal.removeEventListener('abort', onAbort)
      }
    },
  }
}

type RetryOptions = {
  retries?: number
  timeoutMs?: number
  backoffMs?: number
  retryOn?: Set<number>
}

const fetchWithRetry = async (
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: RetryOptions = {},
): Promise<Response> => {
  const retries = options.retries ?? 2
  const timeoutMs = options.timeoutMs ?? 8000
  const backoffMs = options.backoffMs ?? 250
  const retryOn = options.retryOn ?? RETRYABLE_STATUS_CODES
  let attempt = 0
  let lastError: unknown = null

  while (attempt <= retries) {
    if (init.signal?.aborted) {
      throw new DOMException('Request aborted', 'AbortError')
    }
    const { signal, cleanup } = withTimeoutSignal(init.signal, timeoutMs)
    try {
      const response = await fetch(input, { ...init, signal })
      cleanup()
      if (
        (typeof window !== 'undefined' && SERVICE_UNAVAILABLE_STATUS_CODES.has(response.status)) ||
        !retryOn.has(response.status) ||
        attempt === retries
      ) {
        return response
      }
    } catch (error) {
      cleanup()
      if ((error as Error)?.name === 'AbortError' || init.signal?.aborted) {
        throw error
      }
      lastError = error
      if (attempt === retries) {
        throw error
      }
    }

    const delayMs = Math.min(backoffMs * 2 ** attempt, 2000)
    await sleep(delayMs)
    attempt += 1
  }

  throw lastError instanceof Error ? lastError : new Error('Request failed')
}

type ConceptHierarchy = {
  parents?: Array<{ id: string; label: string }>
  children?: Array<{ id: string; label: string }>
}

type RelatedGraphNode = {
  id: string
  label: string
  type: string
  edgeCount: number
  relationTypes: string[]
}

type RelatedGraphEdge = {
  id: string
  sourceId: string
  sourceLabel: string
  sourceType: string
  targetId: string
  targetLabel: string
  targetType: string
  relationType: string
  direction: 'incoming' | 'outgoing'
  isOntologyDirect?: boolean
}

type TaskFamilyTreeNode = {
  id: string
  label: string
  description?: string
  task_count?: number
  children?: TaskSubfamilyTreeNode[]
}

type TaskSubfamilyTreeNode = {
  id: string
  label: string
  task_count?: number
  children?: Concept[]
}

type TaskTreePayload = {
  families?: TaskFamilyTreeNode[]
}

const TASK_UNMAPPED_FAMILY_ID = 'tf_unmapped'
const TASK_UNMAPPED_FAMILY_NODE_ID = `family:${TASK_UNMAPPED_FAMILY_ID}`
const TASK_TREE_CACHE_KEY = 'br-kg:task-tree:v1'
const TASK_TREE_LIMIT = '2000'
const TASK_TREE_FETCH_TIMEOUT_MS = 30000

export type ExplorerLens = 'onvoc' | 'task' | 'disease' | 'population'

type LensConfig = {
  label: string
  defaultView: ViewMode
  nodeTypes: string[]
  scheme?: string
}

const LENS_CONFIG: Record<ExplorerLens, LensConfig> = {
  onvoc: {
    label: 'ONVOC',
    defaultView: 'explorer',
    nodeTypes: ['Concept'],
    scheme: 'ONVOC',
  },
  task: {
    label: 'Task',
    defaultView: 'explorer',
    nodeTypes: ['Task', 'TaskSpec', 'TaskDef', 'TaskAnalysis', 'TaskFamily'],
  },
  disease: {
    label: 'Disease',
    defaultView: 'explorer',
    nodeTypes: ['Concept', 'ONVOC', 'OnvocClass', 'OntologyConcept', 'Dataset', 'DataResource'],
    scheme: 'ONVOC',
  },
  population: {
    label: 'Population',
    defaultView: 'explorer',
    nodeTypes: ['Population', 'Cohort', 'SubjectGroup', 'Dataset', 'DataResource'],
  },
}

const KG_SEARCH_SUGGESTIONS = [
  {
    label: 'default mode network',
    description: 'Resting-state network seed for broad DMN queries.',
  },
  {
    label: 'resting-state fMRI',
    description: 'Functional connectivity and resting-state analysis seed.',
  },
  {
    label: 'connectome',
    description: 'Connectivity graph and connectomics seed.',
  },
  {
    label: 'atlas extraction',
    query: 'atlas-based signal extraction',
    description: 'Atlas parcellation and time-series extraction seed.',
  },
]

type LinearKnowledgeGraphProps = {
  lens?: ExplorerLens
}

export function LinearKnowledgeGraph({ lens = 'onvoc' }: LinearKnowledgeGraphProps) {
  const { isAuthenticated } = useAuth()
  const lensConfig = LENS_CONFIG[lens]
  const explorerEnabled = true
  const isOnvocLens = lens === 'onvoc'
  const isTaskLens = lens === 'task'
  const isDiseaseLens = lens === 'disease'
  const supportsLazyOntologyTree = isOnvocLens
  const [loading, setLoading] = useState(true)
  const [serviceDown, setServiceDown] = useState(false)
  const [selectedView, setSelectedView] = useState<ViewMode>(lensConfig.defaultView)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [backendSource, setBackendSource] = useState<string>('')
  const [concepts, setConcepts] = useState<Concept[]>([])
  const [conceptTree, setConceptTree] = useState<ConceptTreeNode[]>([])
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null)
  const [conceptSummary, setConceptSummary] = useState<ConceptSummary | null>(null)
  const [conceptHierarchy, setConceptHierarchy] = useState<ConceptHierarchy | null>(null)
  const [evidence, setEvidence] = useState<EvidenceGroups>(EMPTY_EVIDENCE_GROUPS)
  const [evidenceCounts, setEvidenceCounts] = useState<EvidenceCounts>(EMPTY_EVIDENCE_COUNTS)
  const [evidenceMeta, setEvidenceMeta] = useState<Record<string, any> | null>(null)
  const [evidenceDiagnostics, setEvidenceDiagnostics] = useState<Record<string, any> | null>(null)
  const [evidencePaths, setEvidencePaths] = useState<EvidencePath[]>([])
  const [graphStats, setGraphStats] = useState({
    nodes: 0,
    edges: 0,
    clusters: 0,
    density: 0
  })
  const [graphData, setGraphData] = useState<{ nodes: any[], edges: any[] }>({ nodes: [], edges: [] })
  const [tasksForConcept, setTasksForConcept] = useState<Array<{ id: string; label: string; datasetCount: number; description?: string; doi?: string; pmid?: string; neurostore_id?: string; source?: string }>>([])
  const [mappedConcepts, setMappedConcepts] = useState<Array<{ id: string; label: string; source?: string }>>([])
  const [datasetsForConcept, setDatasetsForConcept] = useState<
    Array<{
      id: string
      label: string
      source?: string
      modalities?: string[]
      source_repo_bucket?: string
      source_repo_version?: string
      source_repo_versions?: string[]
    }>
  >([])
  const [contrastsForConcept, setContrastsForConcept] = useState<Array<{ id: string; label: string; source?: string; statmapCount?: number }>>([])
  const [relatedNodesForConcept, setRelatedNodesForConcept] = useState<RelatedGraphNode[]>([])
  const [relatedEdgesForConcept, setRelatedEdgesForConcept] = useState<RelatedGraphEdge[]>([])
  const [recentNodes, setRecentNodes] = useState<GraphNode[]>([])
  const [overlaySubgraphRaw, setOverlaySubgraphRaw] = useState<{ nodes: any[]; edges: any[] } | null>(null)
  const [overlayEnabled, setOverlayEnabled] = useState(false)

  const handleOverlaySubgraphReady = useCallback((subgraph: { nodes: any[]; edges: any[] }) => {
    setOverlaySubgraphRaw(subgraph)
    setOverlayEnabled(true)
  }, [])

  const handleOverlayToggle = useCallback((next: boolean) => {
    setOverlayEnabled(Boolean(next))
  }, [])

  const handleOverlayApprove = useCallback(() => {
    if (!overlaySubgraphRaw) return
    const overlayGraph = buildGraphFromSubgraph(overlaySubgraphRaw)
    const merged = mergeGraphData(graphData, overlayGraph, false)
    setGraphData({ nodes: merged.nodes, edges: merged.edges })
    deriveExplorerFromGraph(
      merged.nodes,
      merged.edges,
      selectedConceptId,
      setRelatedEdgesForConcept,
      setRelatedNodesForConcept,
      setTasksForConcept,
      setDatasetsForConcept,
      setContrastsForConcept,
      setMappedConcepts,
      setGraphStats,
    )
    setOverlaySubgraphRaw(null)
    setOverlayEnabled(false)
  }, [
    graphData,
    overlaySubgraphRaw,
    selectedConceptId,
    setGraphStats,
    setMappedConcepts,
    setTasksForConcept,
    setDatasetsForConcept,
    setContrastsForConcept,
  ])

  const overlayGraph = useMemo(() => {
    if (!overlaySubgraphRaw) return null
    return buildGraphFromSubgraph(overlaySubgraphRaw)
  }, [overlaySubgraphRaw])

  const displayGraphData = useMemo(() => {
    if (!overlayEnabled || !overlayGraph) return graphData
    return mergeGraphData(graphData, overlayGraph, true)
  }, [graphData, overlayEnabled, overlayGraph])
  const mappedConceptsRequestRef = useRef(0)
  const evidencePathsRequestRef = useRef(0)
  const mappedConceptsSelectionRef = useRef<string | null>(null)
  const subgraphSelectionRef = useRef<string | null>(null)
  const [qbType, setQbType] = useState<QueryType>('paths')
  const [qbStartId, setQbStartId] = useState('')
  const [qbDepth, setQbDepth] = useState(2)
  const [qbLoading, setQbLoading] = useState(false)
  const [qbError, setQbError] = useState<string | null>(null)
  const [qbResultCounts, setQbResultCounts] = useState<{ nodes: number; edges: number } | null>(null)
  const [featureFilter, setFeatureFilter] = useState<string | undefined>(undefined)

  // State for lazy-loading tree
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
  const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set())
  const [spaceFilter, setSpaceFilter] = useState<string | undefined>(undefined)
  const [atlasFilter, setAtlasFilter] = useState<string | undefined>(undefined)

  // Router for navigation
  const router = useRouter()

  // State for chat modal
  const [isChatOpen, setIsChatOpen] = useState(false)
  const [taskTreeError, setTaskTreeError] = useState<string | null>(null)
  const [reloadNonce, setReloadNonce] = useState(0)

  // State for evidence type filtering
  const [evidenceTypeFilter, setEvidenceTypeFilter] = useState<string[]>(['all'])
  const [showUnverifiedEvidence, setShowUnverifiedEvidence] = useState(true)
  const [showOntologyDirectLinks, setShowOntologyDirectLinks] = useState(false)
  const [showTaskNeighbors, setShowTaskNeighbors] = useState(false)
  const [isLoadingEvidence, setIsLoadingEvidence] = useState(false)
  const [isLoadingEvidencePaths, setIsLoadingEvidencePaths] = useState(false)
  const [evidencePathsError, setEvidencePathsError] = useState<string | null>(null)

  const probeHealth = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetchWithRetry(resolveKgHealthUrl(), {}, {
        retries: 2,
        timeoutMs: 3000,
        backoffMs: 250,
      })
      const healthy = res.ok
      setServiceDown(!healthy)
      return healthy
    } catch {
      setServiceDown(true)
      return false
    }
  }, [])

  const handleSelectConcept = useCallback((conceptId: string | null, label?: string) => {
    setSelectedConceptId(conceptId)
    if (!conceptId) {
      setConceptSummary(null)
      return
    }
    const fallbackLabel = toDisplayLabel(label, conceptId)
    setConceptSummary((prev) => {
      if (prev?.id === conceptId && prev?.label === fallbackLabel) {
        return prev
      }
      return {
        id: conceptId,
        label: fallbackLabel,
        status: 'unknown',
        origin: `neo4j:${lens}`,
      }
    })
  }, [lens])

  const handleGraphNodeClick = useCallback((node: any) => {
    const degree = node.degree ?? node.connections ?? 0
    const size = Math.max(1, node.size ?? degree)
    if (typeof node?.id === 'string' && node.id.trim()) {
      handleSelectConcept(node.id, typeof node?.label === 'string' ? node.label : undefined)
    }
    const nodeId = toDisplayLabel(node?.id, 'selected-node')
    setSelectedNode({
      id: nodeId,
      label: toDisplayLabel(node?.label, nodeId),
      type: node.type ?? 'unknown',
      size,
      connections: degree,
      properties: node.meta ?? {},
    })
  }, [handleSelectConcept])

  const loadGraphData = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: isOnvocLens ? '75' : '120' })
      lensConfig.nodeTypes.forEach((nodeType) => params.append('node_types', nodeType))
      if (lensConfig.scheme) {
        params.set('scheme', lensConfig.scheme)
      }
      const url = resolveKgGraphUrl(params)
      const res = await fetchWithRetry(url, {}, { retries: 2, timeoutMs: 10000 })
      if (res.ok) {
        const data = await res.json()
        setServiceDown(false)

        const nodesCount =
          data.counts?.nodes ?? data.stats?.total_nodes ?? (data.nodes ? data.nodes.length : 0) ?? 0
        const edgesCount =
          data.counts?.edges ?? data.stats?.total_edges ?? (data.edges ? data.edges.length : 0) ?? 0
        const uniqueTypes = new Set<string>()
        ;(data.nodes || []).forEach((n: any) => {
          if (n?.type) uniqueTypes.add(n.type)
        })
        const clusters =
          data.stats?.node_types ? Object.keys(data.stats.node_types).length : uniqueTypes.size || 0
        const density = nodesCount > 1 ? (2 * edgesCount) / (nodesCount * (nodesCount - 1)) : 0

        setGraphStats({
          nodes: nodesCount,
          edges: edgesCount,
          clusters,
          density: Number.isFinite(density) ? Number(density.toFixed(4)) : 0
        })
        setBackendSource(`${data.backend || 'Neo4j'} · ${lensConfig.label}`)

        if (data.nodes && data.edges) {
          const degreeMap = new Map<string, number>()
          data.edges.forEach((edge: any) => {
            if (!edge) return
            const weight = edge.properties?.weight ?? 1
            degreeMap.set(edge.source, (degreeMap.get(edge.source) || 0) + weight)
            degreeMap.set(edge.target, (degreeMap.get(edge.target) || 0) + weight)
          })

          const nodeSummaries: GraphNode[] = data.nodes.map((n: any, index: number) => {
            const id = resolveNodeId(n, `graph-node-${index}`)
            const backendDegree = n.connections ?? n.degree ?? 0
            const computedDegree = degreeMap.get(id) || 0
            const degree = backendDegree || computedDegree
            const baseSize = n.size ?? n.properties?.size ?? 0
            const size = Math.max(1, baseSize || degree || 1)
            return {
              id,
              label: resolveNodeLabel(n, id),
              type: n.type ?? 'unknown',
              size,
              connections: degree,
              properties: n.properties ?? {}
            }
          })

          const cytoscapeNodes = nodeSummaries.map((node) => ({
            data: {
              id: node.id,
              label: node.label,
              type: node.type,
              degree: node.connections,
              size: node.size,
              meta: node.properties
            }
          }))

          const cytoscapeEdges = data.edges.map((e: any, index: number) => {
            const weight = e.properties?.weight ?? 1
            return {
              data: {
                id: e.id || `${e.source}-${e.target}-${index}`,
                source: e.source,
                target: e.target,
                type: e.type,
                weight
              }
            }
          })

          setGraphData({ nodes: cytoscapeNodes, edges: cytoscapeEdges })

          const rankedNodes = [...nodeSummaries].sort((a, b) => b.connections - a.connections)
          setRecentNodes(rankedNodes.slice(0, 6))
        }
      } else if (SERVICE_UNAVAILABLE_STATUS_CODES.has(res.status)) {
        setServiceDown(true)
      }
    } catch (e) {
      console.error('Failed to load graph data:', e)
      setServiceDown(true)
    }
  }, [isOnvocLens, lensConfig])

  // Load selected concept summary + evidence + subgraph
  useEffect(() => {
    const requestId = ++mappedConceptsRequestRef.current
    const controller = new AbortController()
    const isCurrentRequest = () => mappedConceptsRequestRef.current === requestId
    const setMappedConceptsIfCurrent = (
      nextValue: Array<{ id: string; label: string; source?: string }>,
    ) => {
      // Prevent older async loads from overwriting concept mappings for a newer selection.
      if (!isCurrentRequest()) return
      setMappedConcepts(nextValue)
    }
    const setIsLoadingEvidenceIfCurrent = (nextValue: boolean) => {
      if (!isCurrentRequest()) return
      setIsLoadingEvidence(nextValue)
    }

    if (mappedConceptsSelectionRef.current !== selectedConceptId) {
      mappedConceptsSelectionRef.current = selectedConceptId
      setMappedConceptsIfCurrent([])
    }

    const loadConceptData = async () => {
      if (!selectedConceptId) {
        setMappedConceptsIfCurrent([])
        setIsLoadingEvidenceIfCurrent(false)
        setEvidencePaths([])
        setEvidencePathsError(null)
        setIsLoadingEvidencePaths(false)
        setRelatedNodesForConcept([])
        setRelatedEdgesForConcept([])
        setEvidenceMeta(null)
        setEvidenceDiagnostics(null)
        subgraphSelectionRef.current = null
        return
      }

      const subgraphSelectionKey = `${lens}:${selectedConceptId}`
      const shouldLoadSubgraph = subgraphSelectionRef.current !== subgraphSelectionKey

      // Set loading state when a concept is selected.
      setIsLoadingEvidenceIfCurrent(true)
      setRelatedNodesForConcept([])
      setRelatedEdgesForConcept([])
      const fallbackConcept = concepts.find((item) => item.id === selectedConceptId)
      const fallbackLabel =
        toDisplayLabel(fallbackConcept?.display_label || fallbackConcept?.label, selectedConceptId)
      setConceptSummary((prev) => {
        if (prev?.id === selectedConceptId && prev?.label === fallbackLabel) {
          return prev
        }
        return {
          id: selectedConceptId,
          label: fallbackLabel,
          status: 'unknown',
          origin: `neo4j:${lens}`,
        }
      })
      // Summary enrich is background-only so task clicks remain responsive.
      void (async () => {
        try {
          const summaryUrl = isOnvocLens
            ? resolveKgConceptSummaryUrl(selectedConceptId)
            : resolveKgLensEntitySummaryUrl(lens, selectedConceptId)
          const summaryRes = await fetchWithRetry(
            summaryUrl,
            { signal: controller.signal },
            isTaskLens
              ? { retries: 1, timeoutMs: 6500, backoffMs: 300 }
              : { retries: 2, timeoutMs: 7000 },
          )
          if (!isCurrentRequest()) return
          if (summaryRes.ok) {
            const s = await summaryRes.json()
            if (!isCurrentRequest()) return
            setConceptSummary({
              ...s,
              id: toDisplayLabel(s?.id, selectedConceptId),
              label: toDisplayLabel(s?.label, fallbackLabel),
            })
            setServiceDown(false)
            setBackendSource('Neo4j')
          }
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') return
          logUnexpectedKgError('summary fetch failed', e)
        }
      })()

      // Fetch hierarchy only for ONVOC ontology nodes.
      if (supportsLazyOntologyTree) {
        try {
          const conceptRes = await fetchWithRetry(
            resolveKgConceptUrl(selectedConceptId),
            { signal: controller.signal },
            {
              retries: 1,
              timeoutMs: 7000,
            },
          )
          if (!isCurrentRequest()) return
          if (conceptRes.ok) {
            const conceptData = await conceptRes.json()
            if (!isCurrentRequest()) return
            setConceptHierarchy({
              parents: conceptData.parents || [],
              children: conceptData.children || []
            })
          }
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') return
          logUnexpectedKgError('concept hierarchy fetch failed', e)
          setConceptHierarchy(null)
        }
      } else {
        setConceptHierarchy(null)
      }

      const loadEvidence = async () => {
        try {
          const params = new URLSearchParams({ limit: '50', include_mediated: 'true' })
          if (featureFilter) params.set('types', featureFilter)
          if (spaceFilter) params.set('space', spaceFilter)
          if (atlasFilter) params.set('atlas', atlasFilter)
          if (!showUnverifiedEvidence) params.set('verified_only', 'true')
          if (isTaskLens) {
            params.set('task_scope', 'aliases')
            params.set('include_task_neighbors', showTaskNeighbors ? 'true' : 'false')
            // Fast default for task lens; avoid live retrieval on every click.
            params.set('source_mode', 'graph_only')
            params.set('include_paths', 'false')
          }
          const evidenceUrl = isOnvocLens
            ? resolveKgConceptEvidenceUrl(selectedConceptId, params)
            : resolveKgLensEntityEvidenceUrl(lens, selectedConceptId, params)
          const evRes = await fetchWithRetry(
            evidenceUrl,
            { signal: controller.signal },
            isTaskLens ? { retries: 1, timeoutMs: 7000 } : { retries: 2, timeoutMs: 8000 },
          )
          if (!isCurrentRequest()) return
          if (evRes.ok) {
            const ev = await evRes.json()
            if (!isCurrentRequest()) return
            setEvidenceMeta(ev.meta ?? null)
            setEvidenceDiagnostics(ev.diagnostics ?? null)
            const nextCounts: EvidenceCounts = {
              ...EMPTY_EVIDENCE_COUNTS,
              ...(ev.counts ?? {}),
            }
            setEvidenceCounts(nextCounts)
            setEvidence(
              ev.groups
                ? { ...EMPTY_EVIDENCE_GROUPS, ...ev.groups }
                : EMPTY_EVIDENCE_GROUPS,
            )
            setServiceDown(false)
          } else {
            setEvidenceCounts(EMPTY_EVIDENCE_COUNTS)
            setEvidenceMeta(null)
            setEvidenceDiagnostics(null)
            if (SERVICE_UNAVAILABLE_STATUS_CODES.has(evRes.status)) {
              setServiceDown(true)
            }
          }
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') return
          logUnexpectedKgError('evidence fetch failed', e)
          setEvidenceCounts(EMPTY_EVIDENCE_COUNTS)
          setEvidenceMeta(null)
          setEvidenceDiagnostics(null)
          setServiceDown(true)
        } finally {
          setIsLoadingEvidenceIfCurrent(false)
        }
      }

      const loadSubgraph = async () => {
        try {
          // Depth=2 + higher node cap keeps ONVOC neighbors visible without
          // over-traversing far-away concept hierarchy.
          const res = await fetchWithRetry(
            resolveKgQueryUrl(),
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                start_id: selectedConceptId,
                depth: 2,
                limit: isTaskLens ? 600 : 1200,
              }),
              signal: controller.signal,
            },
            isTaskLens ? { retries: 1, timeoutMs: 7000 } : { retries: 2, timeoutMs: 10000 },
          )
          if (!isCurrentRequest()) return
          const data = await res.json()
          if (!isCurrentRequest()) return
          if (res.ok && data.nodes && data.edges) {
            setServiceDown(false)
            const degreeMap = new Map<string, number>()
            data.edges.forEach((edge: any) => {
              if (!edge) return
              degreeMap.set(edge.source, (degreeMap.get(edge.source) || 0) + 1)
              degreeMap.set(edge.target, (degreeMap.get(edge.target) || 0) + 1)
            })
            const nodes = (data.nodes || []).map((n: any, idx: number) => ({
              data: {
                id: resolveNodeId(n, `n-${idx}`),
                label: resolveNodeLabel(
                  { ...n, name: n.props?.label ?? n.props?.name ?? n.props?.title },
                  resolveNodeId(n, `n-${idx}`),
                ),
                type: n.type ?? (n.labels ? n.labels[0] : 'unknown'),
                labels:
                  Array.isArray(n.labels) && n.labels.length > 0
                    ? n.labels
                    : n.type
                      ? [n.type]
                      : [],
                degree: degreeMap.get(n.id) || 0,
                size: Math.max(1, degreeMap.get(n.id) || 1),
                meta: n.props || n.properties || {},
              },
            }))
            const edges = (data.edges || []).map((e: any, idx: number) => ({
              data: {
                id: e.id || `${e.source}-${e.target}-${idx}`,
                source: e.source,
                target: e.target,
                type: e.type,
                weight: e.properties?.weight ?? 1,
                confidence: e.properties?.confidence ?? e.confidence,
              },
            }))
            setGraphData({ nodes, edges })

          const nodeById = new Map<
            string,
            { label: string; type: string; labels: string[]; meta: Record<string, unknown> }
          >()
          nodes.forEach((node: any) => {
            nodeById.set(node.data.id, {
              label: node.data.label || node.data.id,
              type: node.data.type || 'unknown',
              labels: Array.isArray(node.data.labels) ? node.data.labels : [],
              meta: node.data.meta || {},
            })
          })

          const kindById = new Map<string, string>()
          const adjacency = new Map<string, Array<{ neighbor: string; edgeType?: string }>>()
          const pushAdj = (from: string, neighbor: string, edgeType?: string) => {
            if (!adjacency.has(from)) adjacency.set(from, [])
            adjacency.get(from)!.push({ neighbor, edgeType })
          }

          nodes.forEach((node: any) => {
            const kind = inferExplorerNodeKind({
              id: node.data.id,
              type: node.data.type,
              labels: node.data.labels,
              meta: node.data.meta,
            })
            kindById.set(node.data.id, kind)
          })
          edges.forEach((edge: any) => {
            pushAdj(edge.data.source, edge.data.target, edge.data.type)
            pushAdj(edge.data.target, edge.data.source, edge.data.type)
          })

          const directEdges = edges.filter(
            (edge: any) =>
              edge.data.source === selectedConceptId || edge.data.target === selectedConceptId,
          )
          const relatedEdgeSummaries: RelatedGraphEdge[] = directEdges.map(
            (edge: any, idx: number) => {
              const sourceId = edge.data.source
              const targetId = edge.data.target
              const sourceNode = nodeById.get(sourceId)
              const targetNode = nodeById.get(targetId)
              const isOutgoing = sourceId === selectedConceptId
              const isOntologyDirect = isOntologyDirectTaskConceptEdge({
                edgeType: edge.data.type,
                source: {
                  id: sourceId,
                  type: sourceNode?.type,
                  labels: sourceNode?.labels,
                  meta: sourceNode?.meta as Record<string, any> | undefined,
                },
                target: {
                  id: targetId,
                  type: targetNode?.type,
                  labels: targetNode?.labels,
                  meta: targetNode?.meta as Record<string, any> | undefined,
                },
              })
              return {
                id: edge.data.id || `${sourceId}-${targetId}-${idx}`,
                sourceId,
                sourceLabel: sourceNode?.label || sourceId,
                sourceType: sourceNode?.type || 'unknown',
                targetId,
                targetLabel: targetNode?.label || targetId,
                targetType: targetNode?.type || 'unknown',
                relationType: edge.data.type || 'RELATED_TO',
                direction: isOutgoing ? 'outgoing' : 'incoming',
                isOntologyDirect,
              }
            },
          )
          setRelatedEdgesForConcept(relatedEdgeSummaries)

          const relatedNodeAccumulator = new Map<
            string,
            {
              id: string
              label: string
              type: string
              edgeCount: number
              relationTypes: Set<string>
            }
          >()

          relatedEdgeSummaries.forEach((edge) => {
            const neighborId = edge.direction === 'outgoing' ? edge.targetId : edge.sourceId
            const neighborNode = nodeById.get(neighborId)
            const existing = relatedNodeAccumulator.get(neighborId)
            if (existing) {
              existing.edgeCount += 1
              existing.relationTypes.add(edge.relationType)
              return
            }
            relatedNodeAccumulator.set(neighborId, {
              id: neighborId,
              label: neighborNode?.label || neighborId,
              type: neighborNode?.type || 'unknown',
              edgeCount: 1,
              relationTypes: new Set([edge.relationType]),
            })
          })

          const relatedNodeSummaries: RelatedGraphNode[] = Array.from(
            relatedNodeAccumulator.values(),
          )
            .map((node) => ({
              id: node.id,
              label: node.label,
              type: node.type,
              edgeCount: node.edgeCount,
              relationTypes: Array.from(node.relationTypes).sort(),
            }))
            .sort((a, b) => {
              if (b.edgeCount !== a.edgeCount) return b.edgeCount - a.edgeCount
              return a.label.localeCompare(b.label)
            })
          setRelatedNodesForConcept(relatedNodeSummaries)

          const datasetIds = new Set(
            nodes
              .filter((n: any) => kindById.get(n.data.id) === 'dataset')
              .map((n: any) => n.data.id),
          )
          const statmapIds = new Set(
            nodes
              .filter((n: any) => kindById.get(n.data.id) === 'statmap')
              .map((n: any) => n.data.id),
          )

          const taskNodes = nodes.filter((n: any) => kindById.get(n.data.id) === 'task')
          const tasksSummaries = taskNodes.map((t: any) => {
            const tid = t.data.id
            const datasetNeighbors = new Set<string>()
            const neighbors = adjacency.get(tid) || []
            neighbors.forEach(({ neighbor }) => {
              if (datasetIds.has(neighbor)) datasetNeighbors.add(neighbor)
            })
            // Fallback via task -> statmap -> dataset path.
            neighbors.forEach(({ neighbor }) => {
              if (!statmapIds.has(neighbor)) return
              ;(adjacency.get(neighbor) || []).forEach(({ neighbor: dsNeighbor, edgeType }) => {
                if (datasetIds.has(dsNeighbor) && isDatasetStatmapEdgeType(edgeType)) {
                  datasetNeighbors.add(dsNeighbor)
                }
              })
            })

            return {
              id: tid,
              label: toDisplayLabel(t.data.label, tid),
              datasetCount: datasetNeighbors.size,
              description: t.data.meta?.description,
              doi: t.data.meta?.doi,
              pmid: t.data.meta?.pmid,
              neurostore_id: t.data.meta?.neurostore_id,
              source: t.data.meta?.source,
            }
          })
          setTasksForConcept(tasksSummaries)

          const mapped = computeMappedConceptsFromSubgraph(
            selectedConceptId,
            nodes.map((n: any) => ({
              id: n.data.id,
              label: n.data.label,
              kind: kindById.get(n.data.id),
              source: n.data.meta?.source,
            })),
            edges.map((edge: any) => ({
              source: edge.data.source,
              target: edge.data.target,
              type: edge.data.type,
              confidence: edge.data.confidence,
            })),
          )
          setMappedConceptsIfCurrent(mapped)

          const datasetNodes = nodes.filter((n: any) => kindById.get(n.data.id) === 'dataset')
          const datasetsSummaries = datasetNodes.map((d: any) => {
            const did = d.data.id
            let smCount = 0
            ;(adjacency.get(did) || []).forEach(({ neighbor, edgeType }) => {
              if (statmapIds.has(neighbor) && isDatasetStatmapEdgeType(edgeType)) smCount += 1
            })
            const sourceRepoBucket =
              d.data.meta?.source_repo_bucket ||
              d.data.meta?.source_bucket ||
              d.data.meta?.bucket
            const sourceRepoVersion =
              d.data.meta?.source_repo_version || d.data.meta?.version
            const rawVersions = d.data.meta?.source_repo_versions
            const parsedVersions =
              Array.isArray(rawVersions)
                ? rawVersions.filter((value): value is string => typeof value === 'string')
                : typeof rawVersions === 'string'
                  ? rawVersions
                      .split(',')
                      .map((v: string) => v.trim())
                      .filter((v: string) => v.length > 0)
                  : []
            return {
              id: did,
              label: toDisplayLabel(d.data.label, did),
              source:
                d.data.meta?.source_repo ||
                d.data.meta?.source_repo_bucket ||
                d.data.meta?.source,
              modalities: d.data.meta?.modalities || d.data.meta?.modalities_list || [],
              statmapCount: smCount,
              citeLinks: d.data.meta?.cite_links || [],
              source_repo_bucket: sourceRepoBucket,
              source_repo_version: sourceRepoVersion,
              source_repo_versions: parsedVersions,
            }
          })
          setDatasetsForConcept(datasetsSummaries)

          const contrastNodes = nodes.filter((n: any) => kindById.get(n.data.id) === 'contrast')
          const contrastsSummaries = contrastNodes.map((c: any) => {
            const cid = c.data.id
            let smCount = 0
            ;(adjacency.get(cid) || []).forEach(({ neighbor, edgeType }) => {
              if (statmapIds.has(neighbor) && isContrastStatmapEdgeType(edgeType)) smCount += 1
            })
            return {
              id: cid,
              label: toDisplayLabel(c.data.label, cid),
              source: c.data.meta?.source,
              statmapCount: smCount,
            }
          })

          if (contrastsSummaries.length > 0) {
            setContrastsForConcept(contrastsSummaries)
          } else {
            setContrastsForConcept([])
          }

          setGraphStats({
            nodes: data.counts?.nodes ?? nodes.length,
            edges: data.counts?.edges ?? edges.length,
            clusters: graphStats.clusters,
            density:
              (data.counts?.nodes ?? nodes.length) > 1
                ? Number(
                    (
                      (2 * (data.counts?.edges ?? edges.length)) /
                      ((data.counts?.nodes ?? nodes.length) *
                        ((data.counts?.nodes ?? nodes.length) - 1))
                    ).toFixed(4),
                  )
                : 0,
          })
          setBackendSource('Neo4j')
          subgraphSelectionRef.current = subgraphSelectionKey
        } else {
          setMappedConceptsIfCurrent([])
          if (SERVICE_UNAVAILABLE_STATUS_CODES.has(res.status)) {
            setServiceDown(true)
          }
        }
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') return
        logUnexpectedKgError('subgraph fetch failed', e)
        setRelatedNodesForConcept([])
        setRelatedEdgesForConcept([])
        setMappedConceptsIfCurrent([])
        setServiceDown(true)
      }
    }

    if (shouldLoadSubgraph) {
      await Promise.allSettled([loadEvidence(), loadSubgraph()])
    } else {
      await loadEvidence()
    }
    }

    void loadConceptData()

    return () => {
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    concepts,
    selectedConceptId,
    featureFilter,
    spaceFilter,
    atlasFilter,
    showUnverifiedEvidence,
    showTaskNeighbors,
    explorerEnabled,
    supportsLazyOntologyTree,
    isOnvocLens,
    lens,
  ])

  useEffect(() => {
    const requestId = ++evidencePathsRequestRef.current
    const controller = new AbortController()
    const isCurrentRequest = () => evidencePathsRequestRef.current === requestId
    const setEvidencePathsIfCurrent = (nextValue: EvidencePath[]) => {
      if (!isCurrentRequest()) return
      setEvidencePaths(nextValue)
    }
    const setEvidencePathsErrorIfCurrent = (nextValue: string | null) => {
      if (!isCurrentRequest()) return
      setEvidencePathsError(nextValue)
    }
    const setIsLoadingEvidencePathsIfCurrent = (nextValue: boolean) => {
      if (!isCurrentRequest()) return
      setIsLoadingEvidencePaths(nextValue)
    }

    if (!selectedConceptId || selectedView === 'explorer') {
      setEvidencePathsIfCurrent([])
      setEvidencePathsErrorIfCurrent(null)
      setIsLoadingEvidencePathsIfCurrent(false)
      return () => controller.abort()
    }

    const loadEvidencePaths = async () => {
      setIsLoadingEvidencePathsIfCurrent(true)
      setEvidencePathsIfCurrent([])
      setEvidencePathsErrorIfCurrent(null)
      try {
        const pathParams = new URLSearchParams({
          limit: '50',
          include_mediated: 'true',
        })
        if (!showUnverifiedEvidence) {
          pathParams.set('verified_only', 'true')
        }
        const evidencePathsUrl = isOnvocLens
          ? resolveKgConceptEvidencePathsUrl(selectedConceptId, pathParams)
          : resolveKgLensEntityEvidencePathsUrl(lens, selectedConceptId, pathParams)
        const pathRes = await fetchWithRetry(
          evidencePathsUrl,
          { signal: controller.signal },
          {
            retries: isTaskLens ? 1 : 2,
            timeoutMs: isTaskLens ? 7000 : 8000,
          },
        )
        if (!isCurrentRequest()) return
        if (pathRes.ok) {
          const payload: unknown = await pathRes.json()
          if (!isCurrentRequest()) return
          setEvidencePathsIfCurrent(parseEvidencePathsPayload(payload))
          setEvidencePathsErrorIfCurrent(null)
          setServiceDown(false)
          return
        }
        if (pathRes.status === 404) {
          // Backward compatibility: older BR-KG builds don't expose /evidence/paths.
          const fallbackParams = new URLSearchParams(pathParams)
          fallbackParams.set('include_paths', 'true')
          if (featureFilter) fallbackParams.set('types', featureFilter)
          if (spaceFilter) fallbackParams.set('space', spaceFilter)
          if (atlasFilter) fallbackParams.set('atlas', atlasFilter)
          if (isTaskLens) {
            fallbackParams.set('task_scope', 'aliases')
            fallbackParams.set('include_task_neighbors', showTaskNeighbors ? 'true' : 'false')
            fallbackParams.set('source_mode', 'graph_plus_live')
          }
          const fallbackEvidenceUrl = isOnvocLens
            ? resolveKgConceptEvidenceUrl(selectedConceptId, fallbackParams)
            : resolveKgLensEntityEvidenceUrl(lens, selectedConceptId, fallbackParams)
          const fallbackRes = await fetchWithRetry(
            fallbackEvidenceUrl,
            { signal: controller.signal },
            {
              retries: isTaskLens ? 1 : 2,
              timeoutMs: isTaskLens ? 7000 : 8000,
            },
          )
          if (!isCurrentRequest()) return
          if (fallbackRes.ok) {
            const payload: unknown = await fallbackRes.json()
            if (!isCurrentRequest()) return
            setEvidencePathsIfCurrent(parseEvidencePathsPayload(payload))
            setEvidencePathsErrorIfCurrent(null)
            setServiceDown(false)
          } else {
            let pathError = `Unable to load evidence paths (${fallbackRes.status})`
            try {
              const body: unknown = await fallbackRes.json()
              if (
                body &&
                typeof body === 'object' &&
                typeof (body as Record<string, unknown>).error === 'string'
              ) {
                pathError = String((body as Record<string, unknown>).error)
              }
            } catch {
              // no-op: keep fallback status message
            }
            setEvidencePathsIfCurrent([])
            setEvidencePathsErrorIfCurrent(pathError)
            if (SERVICE_UNAVAILABLE_STATUS_CODES.has(fallbackRes.status)) {
              setServiceDown(true)
            }
          }
          return
        }

        let pathError = `Unable to load evidence paths (${pathRes.status})`
        try {
          const body: unknown = await pathRes.json()
          if (
            body &&
            typeof body === 'object' &&
            typeof (body as Record<string, unknown>).error === 'string'
          ) {
            pathError = String((body as Record<string, unknown>).error)
          }
        } catch {
          // no-op: keep fallback status message
        }
        setEvidencePathsIfCurrent([])
        setEvidencePathsErrorIfCurrent(pathError)
        if (SERVICE_UNAVAILABLE_STATUS_CODES.has(pathRes.status)) {
          setServiceDown(true)
        }
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') return
        logUnexpectedKgError('evidence paths fetch failed', e)
        setEvidencePathsIfCurrent([])
        setEvidencePathsErrorIfCurrent('Unable to load evidence paths')
        setServiceDown(true)
      } finally {
        setIsLoadingEvidencePathsIfCurrent(false)
      }
    }

    void loadEvidencePaths()

    return () => {
      controller.abort()
    }
  }, [
    selectedConceptId,
    selectedView,
    featureFilter,
    spaceFilter,
    atlasFilter,
    showUnverifiedEvidence,
    showTaskNeighbors,
    isOnvocLens,
    isTaskLens,
    lens,
  ])

  useEffect(() => {
    setLoading(true)
    setServiceDown(false)
    setSelectedNode(null)
    setSelectedView(lensConfig.defaultView)
    setBackendSource('')
    setIsChatOpen(false)
    setConcepts([])
    setConceptTree([])
    setSelectedConceptId(null)
    setConceptSummary(null)
    setConceptHierarchy(null)
    setEvidence(EMPTY_EVIDENCE_GROUPS)
    setEvidenceCounts(EMPTY_EVIDENCE_COUNTS)
    setEvidencePaths([])
    setEvidencePathsError(null)
    setIsLoadingEvidencePaths(false)
    setExpandedNodes(new Set())
    setLoadingNodes(new Set())
    setFeatureFilter(undefined)
    setSpaceFilter(undefined)
    setAtlasFilter(undefined)
    setShowUnverifiedEvidence(true)
    setShowOntologyDirectLinks(false)
    setShowTaskNeighbors(false)
    setTasksForConcept([])
    setMappedConcepts([])
    setDatasetsForConcept([])
    setContrastsForConcept([])
    setRelatedNodesForConcept([])
    setRelatedEdgesForConcept([])
    setTaskTreeError(null)
    setOverlaySubgraphRaw(null)
    setOverlayEnabled(false)
    subgraphSelectionRef.current = null

    let cancelled = false
    const timer = setTimeout(() => {
      if (!cancelled) setLoading(false)
    }, 1000)

    // Probe health in parallel with data loads.
    void probeHealth()

    // Load lens entities list.
    const loadConcepts = async () => {
      try {
        if (isTaskLens) {
          setTaskTreeError(null)
          const applyTaskTree = (families: TaskFamilyTreeNode[]) => {
            const { flatTasks, familyTree, defaultExpanded } = buildTaskTreeState(families)
            setConcepts(flatTasks)
            setConceptTree(familyTree)
            setExpandedNodes((prev) => (prev.size > 0 ? prev : new Set(defaultExpanded)))
            setServiceDown(false)

          }

          let hasCachedTree = false
          if (typeof window !== 'undefined') {
            try {
              const rawCached = window.sessionStorage.getItem(TASK_TREE_CACHE_KEY)
              if (rawCached) {
                const cachedFamilies = parseTaskTreePayload(JSON.parse(rawCached))
                if (cachedFamilies.length > 0) {
                  applyTaskTree(cachedFamilies)
                  hasCachedTree = true
                }
              }
            } catch (cacheError) {
              console.warn('Task tree cache restore failed', cacheError)
            }
          }

          const taskParams = new URLSearchParams({
            limit: TASK_TREE_LIMIT,
            include_unmapped: 'true',
          })
          const taskTreeRes = await fetchWithRetry(resolveKgLensTaskTreeUrl(taskParams), {}, {
            retries: 1,
            timeoutMs: TASK_TREE_FETCH_TIMEOUT_MS,
            backoffMs: 400,
          })
          const payload: unknown = await taskTreeRes.json().catch(() => null)
          if (!taskTreeRes.ok || isUnavailablePayload(payload)) {
            const upstreamStatus =
              taskTreeRes.ok && isUnavailablePayload(payload)
                ? payload.upstream_status || 503
                : taskTreeRes.status
            if (!hasCachedTree) {
              setConcepts([])
              setConceptTree([])
              setSelectedConceptId(null)
              setTaskTreeError(`Task tree unavailable (${upstreamStatus})`)
            }
            if (SERVICE_UNAVAILABLE_STATUS_CODES.has(upstreamStatus)) {
              setServiceDown(true)
            }
            return
          }
          const families = parseTaskTreePayload(payload)
          if (families.length > 0) {
            applyTaskTree(families)
            if (typeof window !== 'undefined') {
              try {
                window.sessionStorage.setItem(
                  TASK_TREE_CACHE_KEY,
                  JSON.stringify({ families }),
                )
              } catch (cacheError) {
                console.warn('Task tree cache write failed', cacheError)
              }
            }
          } else if (!hasCachedTree) {
            setConcepts([])
            setConceptTree([])
            setSelectedConceptId(null)
            setTaskTreeError('Task tree unavailable')
          }
          return
        }

        const params = new URLSearchParams({
          limit: isDiseaseLens ? '300' : '2000',
        })
        const listUrl = isOnvocLens
          ? resolveKgConceptsUrl(params)
          : resolveKgLensEntitiesUrl(lens, params)
        const res = await fetchWithRetry(
          listUrl,
          {},
          isDiseaseLens
            ? {
                retries: 0,
                timeoutMs: 15000,
              }
            : {
                retries: 2,
                timeoutMs: 10000,
              },
        )
        if (res.ok) {
          const payload: unknown = await res.json()
          const data = parseConceptListPayload(payload)
            .filter((item) => typeof item.id === 'string' && item.id.trim().length > 0)
            .map((item) => ({
              ...item,
              label: toDisplayLabel(item.label, item.id),
              display_label: item.display_label
                ? toDisplayLabel(item.display_label, item.id)
                : item.display_label,
            }))
          setConcepts(data)
          setServiceDown(false)
          if (!isOnvocLens) {
            setConceptTree(
              (data || []).map((item: Concept) => ({
                id: item.id,
                label: toDisplayLabel(item.display_label || item.label, item.id),
                depth: 0,
                collapsedCount: item.collapsed_count,
                children: [],
                hasChildren: false,
                selectable: true,
              })),
            )
          }
        } else if (SERVICE_UNAVAILABLE_STATUS_CODES.has(res.status)) {
          setServiceDown(true)
        }
      } catch (e) {
        logUnexpectedKgError('Failed to load concepts', e)
        const isAbortError = isAbortLikeError(e)
        if (!isAbortError || isTaskLens) {
          setServiceDown(true)
        }
        if (isTaskLens) {
          setConcepts([])
          setConceptTree([])
          setSelectedConceptId(null)
          setTaskTreeError('Task tree unavailable')
        }
      }
    }

    // Load ontology tree roots for explorer lenses with hierarchy.
    const loadTree = async () => {
      if (!supportsLazyOntologyTree) {
        return
      }
      try {
        if (isOnvocLens) {
          const params = new URLSearchParams({ max_depth: '0', limit: '50' })
          const res = await fetchWithRetry(resolveKgConceptTreeUrl(params), {}, {
            retries: 2,
            timeoutMs: 8000,
          })
          if (res.ok) {
            const data = await res.json()
            const roots = asRecordArray<ConceptTreeNode>(data.roots)
              .map((node) => sanitizeTreeNode(node))
              .filter((node): node is ConceptTreeNode => node !== null)
              .map((node) => ({
                ...node,
                hasChildren: node.children.length > 0,
              }))
            setConceptTree(roots)
            setServiceDown(false)
          } else if (SERVICE_UNAVAILABLE_STATUS_CODES.has(res.status)) {
            setServiceDown(true)
          }
        }
      } catch (e) {
        logUnexpectedKgError('Failed to load concept tree', e)
        setServiceDown(true)
      }
    }

    if (supportsLazyOntologyTree) loadTree()
    loadConcepts()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [
    lens,
    explorerEnabled,
    lensConfig,
    isOnvocLens,
    isTaskLens,
    isDiseaseLens,
    supportsLazyOntologyTree,
    probeHealth,
    reloadNonce,
  ])

  useEffect(() => {
    if (selectedView === 'explorer') {
      return
    }
    void loadGraphData()
  }, [selectedView, loadGraphData])

  useEffect(() => {
    if (!serviceDown) {
      return
    }
    let cancelled = false
    const recover = async () => {
      const healthy = await probeHealth()
      if (!cancelled && healthy) {
        setReloadNonce((value) => value + 1)
      }
    }

    const intervalId = window.setInterval(() => {
      void recover()
    }, SERVICE_RECOVERY_POLL_MS)
    void recover()

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [serviceDown, probeHealth])

  const runQueryBuilder = async () => {
    setQbError(null)
    setQbResultCounts(null)
    if (!qbStartId.trim()) {
      setQbError('Enter a start node ID')
      return
    }
    setQbLoading(true)
    try {
      const res = await fetchWithRetry(
        resolveKgQueryUrl(),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            start_id: qbStartId.trim(),
            depth: qbDepth,
            limit: 150,
            query_type: qbType,
          }),
        },
        { retries: 1, timeoutMs: 10000 },
      )
      const data = await res.json()
      if (!res.ok) {
        if (SERVICE_UNAVAILABLE_STATUS_CODES.has(res.status)) {
          setServiceDown(true)
        }
        throw new Error(data?.error || 'Query failed')
      }
      setServiceDown(false)
      const degreeMap = new Map<string, number>()
      ;(data.edges || []).forEach((edge: any) => {
        if (!edge) return
        degreeMap.set(edge.source, (degreeMap.get(edge.source) || 0) + 1)
        degreeMap.set(edge.target, (degreeMap.get(edge.target) || 0) + 1)
      })
      const mappedNodes: GraphNode[] = (data.nodes || []).map((n: any) => ({
        id: n.id,
        label: n.label ?? n.props?.name ?? n.props?.title ?? n.id,
        type: (n.labels && n.labels[0]) || 'unknown',
        size: Math.max(1, n.props?.size || degreeMap.get(n.id) || 1),
        connections: degreeMap.get(n.id) || 0,
        properties: n.props || {},
      }))
      setGraphData({ nodes: data.nodes || [], edges: data.edges || [] })
      setRecentNodes(mappedNodes.slice(0, 8))
      setGraphStats((prev) => ({
        nodes: data.counts?.nodes ?? prev.nodes,
        edges: data.counts?.edges ?? prev.edges,
        clusters: prev.clusters,
        density:
          data.counts && data.counts.nodes > 1
            ? Number(((2 * (data.counts.edges || 0)) / (data.counts.nodes * (data.counts.nodes - 1))).toFixed(4))
            : prev.density,
      }))
      setQbResultCounts(data.counts || { nodes: (data.nodes || []).length, edges: (data.edges || []).length })
      setSelectedView('graph')
    } catch (err: any) {
      setQbError(err.message || 'Query failed')
    } finally {
      setQbLoading(false)
    }
  }

  // Fetch children of a specific concept for lazy loading
  const fetchChildren = async (conceptId: string): Promise<ConceptTreeNode[]> => {
    if (!supportsLazyOntologyTree) {
      return []
    }
    try {
      const url = resolveKgConceptChildrenUrl(conceptId)
      const res = await fetchWithRetry(url, {}, { retries: 1, timeoutMs: 8000 })
      if (res.ok) {
        const data = await res.json()
        return asRecordArray<ConceptTreeNode>(data.children)
          .map((child, index) => sanitizeTreeNode(child, `${conceptId}:child:${index}`))
          .filter((child): child is ConceptTreeNode => child !== null)
      }
    } catch (e) {
      logUnexpectedKgError(`Failed to fetch children for ${conceptId}`, e)
    }
    return []
  }

  // Toggle expand/collapse state and lazy-load children if needed
  const handleToggleNode = async (conceptId: string) => {
    // If already expanded, just collapse
    if (expandedNodes.has(conceptId)) {
      setExpandedNodes(prev => {
        const next = new Set(prev)
        next.delete(conceptId)
        return next
      })
      return
    }

    // Find the node in the tree
    const findNode = (nodes: ConceptTreeNode[]): ConceptTreeNode | null => {
      for (const node of nodes) {
        if (node.id === conceptId) return node
        if (node.children) {
          const found = findNode(node.children)
          if (found) return found
        }
      }
      return null
    }

    const node = findNode(conceptTree)
    if (!node) return

    // If children are not loaded yet and this lens supports lazy ontology fetch, fetch now.
    if (supportsLazyOntologyTree && (!node.children || node.children.length === 0) && node.hasChildren) {
      setLoadingNodes(prev => new Set(prev).add(conceptId))
      const children = await fetchChildren(conceptId)
      setLoadingNodes(prev => {
        const next = new Set(prev)
        next.delete(conceptId)
        return next
      })

      // Update tree with fetched children
      const updateTree = (nodes: ConceptTreeNode[]): ConceptTreeNode[] => {
        return nodes.map(n => {
          if (n.id === conceptId) {
            return { ...n, children }
          }
          if (n.children) {
            return { ...n, children: updateTree(n.children) }
          }
          return n
        })
      }

      setConceptTree(prevTree => updateTree(prevTree))
    }

    // Expand the node
    setExpandedNodes(prev => new Set(prev).add(conceptId))
  }

  const normalizedQuery = searchQuery.trim().toLowerCase()

  const matchesQuery = (label: string) =>
    normalizedQuery ? toSafeString(label).toLowerCase().includes(normalizedQuery) : true

  const filterTree = (node: ConceptTreeNode): ConceptTreeNode | null => {
    const filteredChildren = (node.children || [])
      .map(filterTree)
      .filter((c): c is ConceptTreeNode => c !== null)
    if (matchesQuery(node.label) || filteredChildren.length > 0) {
      return { ...node, children: filteredChildren }
    }
    return null
  }

  const filteredTree =
    conceptTree
      .map(filterTree)
      .filter((n): n is ConceptTreeNode => n !== null)

  const handleUseSearchInMcp = (query: string) => {
    const params = new URLSearchParams()
    params.set('tab', 'integrations')
    params.set('handoff', 'coding-agent')
    params.set('kgQuery', query)
    router.push(`/settings?${params.toString()}`)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-pulse text-gray-500">Loading knowledge graph...</div>
      </div>
    )
  }

  if (serviceDown) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center p-6 bg-white border rounded-lg">
          <Network className="h-10 w-10 text-gray-400 mx-auto mb-2" />
          <div className="font-semibold mb-1">Knowledge Graph is unavailable</div>
          <div className="text-sm text-gray-600 mb-3">
            Unable to reach the knowledge graph service. Showing interface without live data.
          </div>
          <div className="text-sm text-gray-500">
            Auto-retrying every 6 seconds. This view will recover automatically when the
            knowledge graph is back.
          </div>
        </div>
      </div>
    )
  }

  // Filter evidence based on evidenceTypeFilter
  const filteredEvidence: EvidenceGroups = evidenceTypeFilter.includes('all')
      ? evidence
    : {
        statmaps: evidenceTypeFilter.includes('statmaps') ? evidence.statmaps : [],
        coords: evidenceTypeFilter.includes('coords') ? evidence.coords : [],
        timeseries: evidenceTypeFilter.includes('timeseries') ? evidence.timeseries : [],
        datasets: evidenceTypeFilter.includes('datasets') ? evidence.datasets : [],
        papers: evidenceTypeFilter.includes('papers') ? evidence.papers : [],
        tasks: evidenceTypeFilter.includes('tasks') ? evidence.tasks : [],
        task_neighbors: evidenceTypeFilter.includes('tasks') ? evidence.task_neighbors : [],
        contrasts: evidenceTypeFilter.includes('contrasts') ? evidence.contrasts : [],
        tools: evidenceTypeFilter.includes('tools') ? evidence.tools : [],
        studies: evidenceTypeFilter.includes('studies') ? evidence.studies : [],
      }

  const filteredEvidenceCounts: EvidenceCounts = evidenceTypeFilter.includes('all')
    ? evidenceCounts
    : {
        statmaps: evidenceTypeFilter.includes('statmaps') ? evidenceCounts.statmaps : 0,
        coords: evidenceTypeFilter.includes('coords') ? evidenceCounts.coords : 0,
        timeseries: evidenceTypeFilter.includes('timeseries') ? evidenceCounts.timeseries : 0,
        datasets: evidenceTypeFilter.includes('datasets') ? evidenceCounts.datasets : 0,
        papers: evidenceTypeFilter.includes('papers') ? evidenceCounts.papers : 0,
        tasks: evidenceTypeFilter.includes('tasks') ? evidenceCounts.tasks : 0,
        task_neighbors: evidenceTypeFilter.includes('tasks') ? evidenceCounts.task_neighbors : 0,
        contrasts: evidenceTypeFilter.includes('contrasts') ? evidenceCounts.contrasts : 0,
        tools: evidenceTypeFilter.includes('tools') ? evidenceCounts.tools : 0,
        studies: evidenceTypeFilter.includes('studies') ? evidenceCounts.studies : 0,
      }

  return (
    <div className="space-y-6">
      {/* Catalog Header with filters */}
      <CatalogHeader
        lens={lens}
        summary={conceptSummary ?? undefined}
        backendSource={backendSource}
        onToggle={(filters) => {
          setFeatureFilter(filters.feature)
          setSpaceFilter(filters.space)
          setAtlasFilter(filters.atlas)
        }}
        onPrimary={{
          onSearchData: () => {
            if (selectedConceptId) {
              const q = (conceptSummary?.label || selectedConceptId).trim()
              setSearchQuery(q)
              setSelectedView('explorer')
            }
          },
          onMaps: () => {
            setEvidenceTypeFilter(['statmaps', 'coords'])
          },
          onAsk: () => {
            if (!isAuthenticated) {
              const callbackUrl =
                typeof window !== 'undefined'
                  ? `${window.location.pathname}${window.location.search}`
                  : '/kg'
              router.push(`/auth/login?callbackUrl=${encodeURIComponent(callbackUrl)}`)
              return
            }
            setIsChatOpen(true)
          }
        }}
      />

      {/* View Tabs */}
      <GraphViewTabs
        selectedView={selectedView}
        onViewChange={setSelectedView}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        showExplorerTab
        showQueryBuilderTab={false}
      />

      {/* Explorer View: 2-column layout */}
      {selectedView === 'explorer' && (
        <div className="grid grid-cols-5 gap-6">
          {/* Left: Concept Search Panel */}
          <div className="col-span-2">
            <ConceptSearchPanel
              panelTitle={
                isOnvocLens
                  ? 'ONVOC Concepts'
                  : isTaskLens
                    ? 'Task Families'
                    : `${lensConfig.label} Entities`
              }
              searchPlaceholder={
                isOnvocLens
                  ? 'Search concepts'
                  : isTaskLens
                    ? 'Search task / subfamily / family'
                    : `Search ${lensConfig.label.toLowerCase()} entities`
              }
              loadingMessage={
                isTaskLens
                  ? taskTreeError || 'Loading task family tree…'
                  : 'Loading concept tree…'
              }
              emptyMessage={isTaskLens ? 'No tasks match your search.' : 'No concepts match your search.'}
              searchSuggestions={KG_SEARCH_SUGGESTIONS}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              onUseSearchInMcp={handleUseSearchInMcp}
              filteredTree={filteredTree}
              conceptTree={conceptTree}
              selectedConceptId={selectedConceptId}
              expandedNodes={expandedNodes}
              loadingNodes={loadingNodes}
              onToggleNode={handleToggleNode}
              onSelectConcept={handleSelectConcept}
            />
          </div>

          {/* Right: Concept Details Panel */}
          <div className="col-span-3">
            <ExplorerDetailsPanel
              lens={lens}
              concept={conceptSummary}
              evidence={{
                counts: filteredEvidenceCounts,
                groups: filteredEvidence as any,
                meta: evidenceMeta ?? undefined,
                diagnostics: evidenceDiagnostics ?? undefined,
              }}
              showUnverifiedEvidence={showUnverifiedEvidence}
              onShowUnverifiedEvidenceChange={setShowUnverifiedEvidence}
              showOntologyDirectLinks={showOntologyDirectLinks}
              onShowOntologyDirectLinksChange={setShowOntologyDirectLinks}
              showTaskNeighbors={showTaskNeighbors}
              onShowTaskNeighborsChange={setShowTaskNeighbors}
              isLoadingEvidence={isLoadingEvidence}
              hierarchy={conceptHierarchy}
              tasks={tasksForConcept}
              mappedConcepts={mappedConcepts}
              datasetsFromGraph={datasetsForConcept}
              contrastsFromGraph={contrastsForConcept}
              relatedNodes={relatedNodesForConcept}
              relatedEdges={relatedEdgesForConcept}
              multihopOverlayEnabled={overlayEnabled}
              onMultihopOverlayToggle={handleOverlayToggle}
              onMultihopSubgraphReady={handleOverlaySubgraphReady}
              onMultihopOverlayApprove={handleOverlayApprove}
            />
          </div>
        </div>
      )}

      {/* Graph/Query Views: Keep existing 3-column layout */}
      {selectedView !== 'explorer' && (
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 bg-white rounded-lg border border-gray-200">
            {selectedView === 'graph' && (
              <GraphErrorBoundary>
                <CytoscapeGraph
                  nodes={displayGraphData.nodes}
                  edges={displayGraphData.edges}
                  onNodeClick={handleGraphNodeClick}
                />
              </GraphErrorBoundary>
            )}

            {selectedView === 'query' && (
              <QueryBuilderPanel
                queryType={qbType}
                startId={qbStartId}
                depth={qbDepth}
                loading={qbLoading}
                error={qbError}
                resultCounts={qbResultCounts}
                onQueryTypeChange={setQbType}
                onStartIdChange={setQbStartId}
                onDepthChange={setQbDepth}
                onRun={runQueryBuilder}
              />
            )}
          </div>

          <div className="col-span-1 space-y-4">
            <EvidencePathsPanel
              paths={evidencePaths}
              loading={isLoadingEvidencePaths}
              error={evidencePathsError}
            />

            <EvidencePanel
              evidence={filteredEvidence}
              selectedNode={selectedNode}
              setSelectedNode={setSelectedNode as any}
              allNodes={displayGraphData.nodes}
              allEdges={displayGraphData.edges}
            />
          </div>
        </div>
      )}

      {/* Knowledge Graph Chat Modal */}
      <KnowledgeGraphChatModal
        isOpen={isChatOpen}
        onClose={() => setIsChatOpen(false)}
        conceptId={selectedConceptId}
        conceptLabel={conceptSummary?.label}
      />
    </div>
  )
}
