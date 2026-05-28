export type ExplorerNodeKind =
  | 'task'
  | 'dataset'
  | 'contrast'
  | 'concept'
  | 'statmap'
  | 'paper'
  | 'timeseries'
  | 'tool'
  | 'study'
  | 'unknown'

type ExplorerNodeInput = {
  id?: string
  type?: string
  labels?: string[]
  meta?: Record<string, any>
}

const TASK_LABELS = new Set(['task', 'taskspec', 'taskdef', 'taskanalysis'])
const DATASET_LABELS = new Set(['dataset', 'dataresource', 'openneurodataset'])
const CONTRAST_LABELS = new Set(['contrast', 'contrastspec'])
const CONCEPT_LABELS = new Set(['concept', 'onvocclass', 'ontologyconcept'])
const STATMAP_LABELS = new Set(['statmap', 'statsmap', 'statisticalmap'])
const PAPER_LABELS = new Set(['publication', 'paper'])
const TIMESERIES_LABELS = new Set(['timeseries', 'timeseriesrecord'])
const TOOL_LABELS = new Set(['tool', 'toolversion'])
const STUDY_LABELS = new Set(['study', 'experiment'])

const DATASET_STATMAP_EDGE_TYPES = new Set([
  'has_statmap',
  'generated_from',
  'derived_from',
  'has_resource',
  'from_dataset',
  'uses_dataset',
])

const CONTRAST_STATMAP_EDGE_TYPES = new Set([
  'measures_contrast',
  'derived_from',
  'has_contrast',
  'contrast_of',
  'describes_contrast',
])

const COGNITIVE_ATLAS_ID_PREFIXES = ['trm_', 'ctp_', 'con_']
const CONCEPT_MAPPING_EDGE_TYPES = new Set(['maps_to', 'same_as'])
const MIN_MAPS_TO_MAPPING_CONFIDENCE = 0.85
const MIN_SAME_AS_MAPPING_CONFIDENCE = 0.9

function normalize(input: string | undefined | null): string {
  return (input || '').trim().toLowerCase()
}

function asString(input: unknown): string {
  return typeof input === 'string' ? input.trim() : ''
}

function normalizeConfidence(input: unknown): number | null {
  if (typeof input === 'number' && Number.isFinite(input)) return input
  if (typeof input === 'string' && input.trim()) {
    const parsed = Number(input)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function allLabels(node: ExplorerNodeInput): string[] {
  const labels = Array.isArray(node.labels) ? node.labels : []
  if (labels.length > 0) {
    return labels.map((v) => normalize(v)).filter(Boolean)
  }
  const fallback = normalize(node.type)
  return fallback ? [fallback] : []
}

export function inferExplorerNodeKind(node: ExplorerNodeInput): ExplorerNodeKind {
  const id = normalize(node.id)
  const labels = allLabels(node)

  if (labels.some((label) => TASK_LABELS.has(label))) return 'task'
  if (labels.some((label) => DATASET_LABELS.has(label))) return 'dataset'
  if (labels.some((label) => CONTRAST_LABELS.has(label))) return 'contrast'
  if (labels.some((label) => STATMAP_LABELS.has(label))) return 'statmap'
  if (labels.some((label) => PAPER_LABELS.has(label))) return 'paper'
  if (labels.some((label) => TIMESERIES_LABELS.has(label))) return 'timeseries'
  if (labels.some((label) => TOOL_LABELS.has(label))) return 'tool'
  if (labels.some((label) => STUDY_LABELS.has(label))) return 'study'
  if (labels.some((label) => CONCEPT_LABELS.has(label))) return 'concept'
  if (id.startsWith('onvoc_') || id.startsWith('trm_')) return 'concept'
  return 'unknown'
}

export function isCognitiveAtlasConcept(node: ExplorerNodeInput): boolean {
  const metaSource = normalize(node.meta?.source)
  if (metaSource === 'cognitive_atlas') return true
  const id = normalize(node.id)
  return COGNITIVE_ATLAS_ID_PREFIXES.some((prefix) => id.startsWith(prefix))
}

export function isConceptMappingEdgeType(edgeType: string | undefined): boolean {
  return CONCEPT_MAPPING_EDGE_TYPES.has(normalize(edgeType))
}

export function passesConceptMappingConfidence(input: unknown, edgeType?: string): boolean {
  const confidence = normalizeConfidence(input)
  // Missing confidence is treated as unknown provenance and is allowed.
  if (confidence === null) return true
  const normalizedType = normalize(edgeType)
  if (normalizedType === 'same_as') {
    return confidence >= MIN_SAME_AS_MAPPING_CONFIDENCE
  }
  return confidence >= MIN_MAPS_TO_MAPPING_CONFIDENCE
}

type ConceptMappingNode = {
  id: string
  label?: string
  kind?: ExplorerNodeKind | string
  source?: string
}

type ConceptMappingEdge = {
  source: string
  target: string
  type?: string
  confidence?: unknown
}

export function computeMappedConceptsFromSubgraph(
  selectedConceptId: string,
  nodes: ConceptMappingNode[],
  edges: ConceptMappingEdge[],
): Array<{ id: string; label: string; source?: string }> {
  const selectedId = asString(selectedConceptId)
  if (!selectedId) return []

  const conceptNodes = new Map<string, { label: string; source?: string; isCognitiveAtlas: boolean }>()
  nodes.forEach((node) => {
    const nodeId = asString(node.id)
    if (!nodeId) return
    if (normalize(typeof node.kind === 'string' ? node.kind : '') !== 'concept') return
    const isCognitiveAtlas = isCognitiveAtlasConcept({
      id: nodeId,
      type: 'Concept',
      meta: { source: node.source },
    })
    conceptNodes.set(nodeId, {
      label: asString(node.label) || nodeId,
      source: asString(node.source) || undefined,
      isCognitiveAtlas,
    })
  })

  const mappedById = new Map<string, { id: string; label: string; source?: string }>()
  edges.forEach((edge) => {
    if (!isConceptMappingEdgeType(edge.type)) return
    if (!passesConceptMappingConfidence(edge.confidence, edge.type)) return

    const sourceId = asString(edge.source)
    const targetId = asString(edge.target)
    if (!sourceId || !targetId) return

    const neighborId =
      sourceId === selectedId ? targetId : targetId === selectedId ? sourceId : null
    if (!neighborId || neighborId === selectedId) return

    const conceptNode = conceptNodes.get(neighborId)
    if (!conceptNode) return
    if (!conceptNode.isCognitiveAtlas) return

    mappedById.set(neighborId, {
      id: neighborId,
      label: conceptNode.label,
      source: conceptNode.source,
    })
  })

  return Array.from(mappedById.values()).sort((a, b) => {
    const labelCompare = a.label.localeCompare(b.label)
    if (labelCompare !== 0) return labelCompare
    return a.id.localeCompare(b.id)
  })
}

export function isDatasetStatmapEdgeType(edgeType: string | undefined): boolean {
  return DATASET_STATMAP_EDGE_TYPES.has(normalize(edgeType))
}

export function isContrastStatmapEdgeType(edgeType: string | undefined): boolean {
  return CONTRAST_STATMAP_EDGE_TYPES.has(normalize(edgeType))
}

type OntologyDirectEdgeInput = {
  edgeType?: string
  source: ExplorerNodeInput
  target: ExplorerNodeInput
}

export function isOntologyDirectTaskConceptEdge({
  edgeType,
  source,
  target,
}: OntologyDirectEdgeInput): boolean {
  if (normalize(edgeType) !== 'in_onvoc') {
    return false
  }

  const sourceKind = inferExplorerNodeKind(source)
  const targetKind = inferExplorerNodeKind(target)
  return (
    (sourceKind === 'task' && targetKind === 'concept') ||
    (sourceKind === 'concept' && targetKind === 'task')
  )
}
