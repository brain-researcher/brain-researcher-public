'use client'

import { ReactNode, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Database, FileText, Wrench, TestTube, Brain, Info, Network, Code2 } from 'lucide-react'
import { ConceptOverviewTab } from './ConceptOverviewTab'
import { EvidenceListItem, EmptyState, EvidenceItem } from './EvidenceListItem'
import { TaskMultihopPanel } from './TaskMultihopPanel'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'

interface ConceptSummary {
  id: string
  label: string
  definition?: string
  uri?: string
  synonyms?: string[]
  scheme?: string
  cohort_meta?: {
    dataset_id?: string | null
    n_subjects?: number | null
    age_range?: string | null
    sex_distribution?: Record<string, number> | null
    linked_datasets?: Array<{ id?: string; name?: string; url?: string | null }>
  }
}

interface EvidenceData {
  counts?: {
    statmaps?: number
    coords?: number
    timeseries?: number
    datasets?: number
    papers?: number
    tasks?: number
    task_neighbors?: number
    contrasts?: number
    tools?: number
    studies?: number
  }
  groups?: {
    statmaps?: EvidenceItem[]
    coords?: EvidenceItem[]
    timeseries?: EvidenceItem[]
    datasets?: EvidenceItem[]
    papers?: EvidenceItem[]
    tasks?: EvidenceItem[]
    task_neighbors?: EvidenceItem[]
    contrasts?: EvidenceItem[]
    tools?: EvidenceItem[]
    studies?: EvidenceItem[]
  }
  meta?: {
    source_mode?: string
    include_paths?: boolean
    sources_used?: string[]
  }
  diagnostics?: {
    coverage?: {
      requested_groups?: string[]
      covered_groups?: string[]
      ratio?: number
      paths?: number
    }
  }
}

interface ConceptHierarchy {
  parents?: Array<{ id: string; label: string }>
  children?: Array<{ id: string; label: string }>
}

type RelatedNodeSummary = {
  id: string
  label: string
  type: string
  edgeCount: number
  relationTypes: string[]
}

type RelatedEdgeSummary = {
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

interface ExplorerDetailsPanelProps {
  lens?: 'onvoc' | 'task' | 'disease' | 'population'
  concept: ConceptSummary | null
  evidence: EvidenceData | null
  showUnverifiedEvidence?: boolean
  onShowUnverifiedEvidenceChange?: (nextValue: boolean) => void
  showOntologyDirectLinks?: boolean
  onShowOntologyDirectLinksChange?: (nextValue: boolean) => void
  showTaskNeighbors?: boolean
  onShowTaskNeighborsChange?: (nextValue: boolean) => void
  isLoadingEvidence?: boolean
  hierarchy?: ConceptHierarchy | null
  tasks?: Array<{ id: string; label: string; datasetCount: number; description?: string; doi?: string; pmid?: string; neurostore_id?: string; source?: string }>
  mappedConcepts?: Array<{ id: string; label: string; source?: string }>
  datasetsFromGraph?: Array<{
    id: string
    label: string
    source?: string
    modalities?: string[]
    statmapCount?: number
    citeLinks?: string[]
    source_repo_bucket?: string
    source_repo_version?: string
    source_repo_versions?: string[]
  }>
  contrastsFromGraph?: Array<{ id: string; label: string; source?: string; statmapCount?: number }>
  relatedNodes?: RelatedNodeSummary[]
  relatedEdges?: RelatedEdgeSummary[]
  multihopOverlayEnabled?: boolean
  onMultihopOverlayToggle?: (nextValue: boolean) => void
  onMultihopSubgraphReady?: (subgraph: { nodes: any[]; edges: any[] }) => void
  onMultihopOverlayApprove?: () => void
}

type SparseSection = {
  key: string
  label: string
  count: number
  content: ReactNode
}

export function ExplorerDetailsPanel({
  lens = 'onvoc',
  concept,
  evidence,
  showUnverifiedEvidence = false,
  onShowUnverifiedEvidenceChange,
  showOntologyDirectLinks = false,
  onShowOntologyDirectLinksChange,
  showTaskNeighbors = false,
  onShowTaskNeighborsChange,
  isLoadingEvidence = false,
  hierarchy = null,
  tasks = [],
  mappedConcepts = [],
  datasetsFromGraph = [],
  contrastsFromGraph = [],
  relatedNodes = [],
  relatedEdges = [],
  multihopOverlayEnabled = false,
  onMultihopOverlayToggle,
  onMultihopSubgraphReady,
  onMultihopOverlayApprove,
}: ExplorerDetailsPanelProps) {
  const [activeTab, setActiveTab] = useState('overview')
  const [layoutMode, setLayoutMode] = useState<'auto' | 'tabs'>('auto')
  const router = useRouter()
  const showConceptsTab = lens === 'onvoc'

  const counts = evidence?.counts || {}
  const groups = evidence?.groups || {}
  const evidenceMeta = evidence?.meta || {}
  const coverageDiagnostics = evidence?.diagnostics?.coverage
  const coverageRatio = typeof coverageDiagnostics?.ratio === 'number'
    ? Math.round(coverageDiagnostics.ratio * 100)
    : null
  const taskEvidenceItems = groups.tasks || []
  const taskNeighborEvidenceItems = groups.task_neighbors || []
  const contrastEvidenceItems = groups.contrasts || []
  const toolEvidenceItems = groups.tools || []
  const studyEvidenceItems = groups.studies || []

  const taskCount = counts.tasks ?? taskEvidenceItems.length
  const taskNeighborCount = counts.task_neighbors ?? taskNeighborEvidenceItems.length
  const useTaskGraphFallback = lens !== 'task' && taskEvidenceItems.length === 0 && tasks.length > 0
  const contrastCount =
    contrastEvidenceItems.length > 0 ? contrastEvidenceItems.length : contrastsFromGraph.length
  const totalRelatedNodeCount = relatedNodes.length
  const totalRelatedEdgeCount = relatedEdges.length
  const visibleRelatedEdges = showOntologyDirectLinks
    ? relatedEdges
    : relatedEdges.filter((edge) => !edge.isOntologyDirect)
  const hiddenOntologyDirectEdgeCount = Math.max(
    0,
    totalRelatedEdgeCount - visibleRelatedEdges.length,
  )
  const relatedNodeById = new Map(relatedNodes.map((node) => [node.id, node]))
  const visibleNodeAccumulator = new Map<
    string,
    {
      id: string
      label: string
      type: string
      edgeCount: number
      relationTypes: Set<string>
    }
  >()
  visibleRelatedEdges.forEach((edge) => {
    const endpoints = [
      { id: edge.sourceId, label: edge.sourceLabel, type: edge.sourceType },
      { id: edge.targetId, label: edge.targetLabel, type: edge.targetType },
    ]
    endpoints.forEach((endpoint) => {
      const existing = visibleNodeAccumulator.get(endpoint.id)
      if (existing) {
        existing.edgeCount += 1
        existing.relationTypes.add(edge.relationType)
        return
      }
      const knownNode = relatedNodeById.get(endpoint.id)
      visibleNodeAccumulator.set(endpoint.id, {
        id: endpoint.id,
        label: knownNode?.label || endpoint.label || endpoint.id,
        type: knownNode?.type || endpoint.type || 'unknown',
        edgeCount: 1,
        relationTypes: new Set([edge.relationType]),
      })
    })
  })
  const visibleRelatedNodes: RelatedNodeSummary[] = Array.from(
    visibleNodeAccumulator.values(),
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
  const relatedNodeCount = visibleRelatedNodes.length
  const relatedEdgeCount = visibleRelatedEdges.length
  const toolCount = counts.tools ?? toolEvidenceItems.length
  const studyCount = counts.studies ?? studyEvidenceItems.length
  const datasetCount = counts.datasets ?? groups.datasets?.length ?? datasetsFromGraph.length
  const paperCount = counts.papers ?? groups.papers?.length ?? 0
  const mapCount = counts.statmaps ?? groups.statmaps?.length ?? 0
  const coordCount = counts.coords ?? groups.coords?.length ?? 0
  const timeseriesCount = counts.timeseries ?? groups.timeseries?.length ?? 0
  const conceptsCount = mappedConcepts.length
  const totalEvidenceCount =
    Number(mapCount) +
    Number(coordCount) +
    Number(timeseriesCount) +
    Number(datasetCount) +
    Number(paperCount) +
    Number(taskCount) +
    Number(taskNeighborCount) +
    Number(contrastCount) +
    Number(toolCount) +
    Number(studyCount)
  const hasDatasetsSection = Number(datasetCount) > 0
  const hasTasksSection = taskCount > 0 || useTaskGraphFallback || taskNeighborCount > 0
  const hasContrastsSection = contrastCount > 0
  const hasToolsSection = toolCount > 0
  const hasStudiesSection = studyCount > 0
  const hasPapersSection = Number(paperCount) > 0
  const hasMapsSection = Number(mapCount) > 0
  const hasConnectionsSection = totalRelatedNodeCount > 0 || totalRelatedEdgeCount > 0
  const hasConceptsSection = showConceptsTab && conceptsCount > 0

  const nonOverviewSectionCount = [
    hasDatasetsSection,
    hasTasksSection,
    hasContrastsSection,
    hasToolsSection,
    hasStudiesSection,
    hasPapersSection,
    hasMapsSection,
    hasConnectionsSection,
    hasConceptsSection,
  ].filter(Boolean).length

  const isSparseEntity =
    !isLoadingEvidence && (totalEvidenceCount === 0 || nonOverviewSectionCount <= 2)
  const useSparseLayout = layoutMode === 'auto' && isSparseEntity
  const showSparseEvidenceHint = useSparseLayout && nonOverviewSectionCount === 0
  const hasAnyEvidenceSection = nonOverviewSectionCount > 0
  const isZeroCoverage = coverageRatio !== null && coverageRatio <= 0
  const noEvidenceAvailable = !isLoadingEvidence && !isZeroCoverage && !hasAnyEvidenceSection

  const [showInlineMultihopPanel, setShowInlineMultihopPanel] = useState(false)
  const [multihopAutoRunToken, setMultihopAutoRunToken] = useState(0)
  const [conceptHandoffOpen, setConceptHandoffOpen] = useState(false)

  const visibleTabs: string[] = [
    'overview',
    ...(hasDatasetsSection ? ['datasets'] : []),
    ...(hasTasksSection ? ['tasks'] : []),
    ...(hasContrastsSection ? ['contrasts'] : []),
    ...(hasToolsSection ? ['tools'] : []),
    ...(hasStudiesSection ? ['studies'] : []),
    ...(hasPapersSection ? ['papers'] : []),
    ...(hasMapsSection ? ['brain-maps'] : []),
    ...(hasConnectionsSection ? ['connections'] : []),
    ...(hasConceptsSection ? ['concepts'] : []),
  ]

  useEffect(() => {
    if (!showConceptsTab && activeTab === 'concepts') {
      setActiveTab('overview')
    }
  }, [showConceptsTab, activeTab])

  useEffect(() => {
    if (useSparseLayout) return
    if (!visibleTabs.includes(activeTab)) {
      setActiveTab('overview')
    }
  }, [activeTab, useSparseLayout, visibleTabs])

  // Empty state when no concept selected
  if (!concept) {
    const entityNoun = { onvoc: 'concept', task: 'task', disease: 'disorder', population: 'cohort' }[lens] ?? 'entity'
    return (
      <Card className="h-full flex items-center justify-center">
        <CardContent className="text-center py-12">
          <Network className="h-16 w-16 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-lg font-semibold mb-2">No {entityNoun} selected</h3>
          <p className="text-sm text-muted-foreground max-w-sm">
            Select a {entityNoun} from the list on the left to view linked datasets and evidence.
          </p>
        </CardContent>
      </Card>
    )
  }

  const conceptHandoffPayload: HandoffTemplatePayload = {
    kind: 'template',
    workflowId: 'kg_context',
    workflowLabel: `KG concept: ${concept.label}`,
    promptOverride: [
      `Continue Brain Researcher analysis grounded in this KG concept.`,
      `Concept: ${concept.label} (${concept.id})`,
      concept.definition ? `Definition: ${concept.definition}` : '',
      '',
      `Load context with br.kg_context(concept_id="${concept.id}") and explore neighbors via br.kg_neighbors(node_id="${concept.id}").`,
    ]
      .filter(Boolean)
      .join('\n'),
    title: `Hand off — ${concept.label}`,
  }

  const onOpenDeepResearchPrompt = () => {
    const prompt = [
      'I found this concept has sparse/empty evidence coverage in BR-KG.',
      'Please run deep research and propose evidence-backed links across task, paper, and dataset sources.',
      `Concept: ${concept.label} (${concept.id})`,
    ].join('\n')
    router.push(`/studio?prompt=${encodeURIComponent(prompt)}`)
  }

  const onRunMultihopReasoning = () => {
    setShowInlineMultihopPanel(true)
    setMultihopAutoRunToken((prev) => prev + 1)
  }

  const linkedDataset = concept?.cohort_meta?.linked_datasets?.[0]
  const populationDatasetId = linkedDataset?.id || concept?.cohort_meta?.dataset_id || null
  const canRouteToDatasetPage =
    typeof populationDatasetId === 'string' &&
    (populationDatasetId.startsWith('ds:') ||
      populationDatasetId.startsWith('dandi:') ||
      /^ds\d+/i.test(populationDatasetId))

  const overviewContent = (
    <ConceptOverviewTab
      concept={concept}
      hierarchy={hierarchy ?? undefined}
      isLoading={isLoadingEvidence}
    />
  )

  const datasetsContent = isLoadingEvidence ? (
    <div className="space-y-3">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-24 bg-muted rounded-lg animate-pulse" />
      ))}
    </div>
  ) : groups.datasets && groups.datasets.length > 0 ? (
    <div className="space-y-3">
      {groups.datasets.map((dataset, idx) => (
        <EvidenceListItem
          key={dataset.id || idx}
          item={dataset}
          type="dataset"
        />
      ))}
    </div>
  ) : datasetsFromGraph.length > 0 ? (
    <div className="space-y-3">
      {datasetsFromGraph.map((d) => (
        <div
          key={d.id}
          className="border rounded-lg p-3 text-sm flex items-start justify-between gap-2"
        >
          <div>
            <div className="font-semibold text-gray-800">{d.label}</div>
            <div className="text-xs text-gray-500">{d.id}</div>
            <div className="text-[11px] text-gray-600 mt-1">
              Stat maps: {d.statmapCount || 0}
            </div>
            {d.source_repo_bucket ? (
              <div className="text-[11px] text-gray-600 mt-1">
                S3 bucket: {d.source_repo_bucket}
              </div>
            ) : null}
            {d.source_repo_version ? (
              <div className="text-[11px] text-gray-600 mt-1">
                Version: {d.source_repo_version}
              </div>
            ) : null}
            {(d.source_repo_versions || []).length > 0 ? (
              <div className="text-[11px] text-gray-600 mt-1">
                Versions: {d.source_repo_versions.join(', ')}
              </div>
            ) : null}
            <div className="text-xs text-gray-600 flex flex-wrap gap-1 mt-1">
              {d.source && (
                <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded border border-blue-100">
                  {d.source}
                </span>
              )}
              {(d.modalities || []).slice(0, 5).map((m) => (
                <span key={m} className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded border border-gray-200">
                  {m}
                </span>
              ))}
              {d.modalities && d.modalities.length > 5 && <span className="text-gray-500">…</span>}
              {(d.citeLinks || []).slice(0, 2).map((link) => (
                <span key={link} className="px-2 py-0.5 bg-green-50 text-green-700 rounded border border-green-100">
                  cite
                </span>
              ))}
            </div>
          </div>
          <Badge variant="outline" className="text-[11px]">Dataset</Badge>
        </div>
      ))}
    </div>
  ) : (
    <EmptyState type="dataset" />
  )

  const tasksContent = (
    <div className="space-y-3">
      {taskEvidenceItems.length > 0 ? (
        <div className="space-y-3">
          {taskEvidenceItems.map((task, idx) => (
            <EvidenceListItem
              key={task.id || idx}
              item={task}
              type="task"
            />
          ))}
        </div>
  ) : useTaskGraphFallback ? (
        <div className="space-y-3">
          {tasks.map((t) => (
            <div key={t.id} className="border rounded-lg p-3 text-sm space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold text-gray-800">{t.label}</div>
                  <div className="text-xs text-gray-500">Datasets: {t.datasetCount}</div>
                </div>
                <Badge variant="outline" className="text-[11px]">Task</Badge>
              </div>
              {t.description && <p className="text-xs text-gray-700 leading-snug">{t.description}</p>}
              <div className="flex flex-wrap gap-2 text-[11px] text-gray-600">
                {t.doi && (
                  <a
                    href={`https://doi.org/${encodeURIComponent(t.doi)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded border border-blue-100 hover:underline"
                  >
                    doi: {t.doi}
                  </a>
                )}
                {t.pmid && (
                  <a
                    href={`https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(t.pmid)}/`}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded border border-emerald-100 hover:underline"
                  >
                    pmid: {t.pmid}
                  </a>
                )}
                {t.neurostore_id && <span className="px-2 py-0.5 bg-purple-50 text-purple-700 rounded border border-purple-100">{t.neurostore_id}</span>}
                {t.source && <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded border border-gray-200">{t.source}</span>}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          type="study"
          message={
            lens === 'task'
              ? 'No task aliases linked to this task yet.'
              : 'No tasks linked to this concept in the current subgraph.'
          }
        />
      )}

      {lens === 'task' ? (
        <div className="rounded-lg border p-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Related task neighbors</div>
              <div className="text-xs text-muted-foreground">
                Show broader connected tasks (outside canonical aliases).
              </div>
            </div>
            <div className="flex items-center gap-2">
              {taskNeighborCount > 0 ? (
                <Badge variant="secondary" className="text-xs h-5 px-1.5">
                  {taskNeighborCount}
                </Badge>
              ) : null}
              <Switch
                id="show-task-neighbors"
                checked={showTaskNeighbors}
                onCheckedChange={(checked) =>
                  onShowTaskNeighborsChange?.(Boolean(checked))
                }
              />
            </div>
          </div>
          {showTaskNeighbors ? (
            taskNeighborEvidenceItems.length > 0 ? (
              <div className="space-y-3">
                {taskNeighborEvidenceItems.map((task, idx) => (
                  <EvidenceListItem
                    key={task.id || idx}
                    item={task}
                    type="task"
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                type="study"
                message="No neighboring tasks linked to this task in the current graph."
              />
            )
          ) : null}
        </div>
      ) : null}

      {lens === 'task' ? (
        <TaskMultihopPanel
          taskId={concept.id}
          taskLabel={concept.label}
          entityNoun="task"
          overlayEnabled={multihopOverlayEnabled}
          onOverlayToggle={onMultihopOverlayToggle}
          onSubgraphReady={onMultihopSubgraphReady}
          onApproveMerge={onMultihopOverlayApprove}
        />
      ) : null}
    </div>
  )

  const contrastsContent = contrastEvidenceItems.length > 0 ? (
    <div className="space-y-3">
      {contrastEvidenceItems.map((contrast, idx) => (
        <EvidenceListItem
          key={contrast.id || idx}
          item={contrast}
          type="contrast"
        />
      ))}
    </div>
  ) : contrastsFromGraph.length === 0 ? (
    <EmptyState type="study" message="No contrasts linked to this concept in the current subgraph." />
  ) : (
    <div className="space-y-3">
      {contrastsFromGraph.map((c) => (
        <div key={c.id} className="border rounded-lg p-3 text-sm flex items-center justify-between">
          <div>
            <div className="font-semibold text-gray-800">{c.label}</div>
            <div className="text-xs text-gray-500">{c.id}</div>
            {c.statmapCount !== undefined && (
              <div className="text-[11px] text-gray-600 mt-1">Stat maps: {c.statmapCount}</div>
            )}
          </div>
          <Badge variant="outline" className="text-[11px]">{c.source || 'contrast'}</Badge>
        </div>
      ))}
    </div>
  )

  const toolsContent = toolEvidenceItems.length > 0 ? (
    <div className="space-y-3">
      {toolEvidenceItems.map((tool, idx) => (
        <EvidenceListItem
          key={tool.id || idx}
          item={tool}
          type="tool"
        />
      ))}
    </div>
  ) : (
    <EmptyState
      type="tool"
      message="No tool associations linked to this concept."
    />
  )

  const studiesContent = studyEvidenceItems.length > 0 ? (
    <div className="space-y-3">
      {studyEvidenceItems.map((study, idx) => (
        <EvidenceListItem
          key={study.id || idx}
          item={study}
          type="study"
        />
      ))}
    </div>
  ) : (
    <EmptyState
      type="study"
      message="No study associations linked to this concept."
    />
  )

  const papersContent = isLoadingEvidence ? (
    <div className="space-y-3">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-24 bg-muted rounded-lg animate-pulse" />
      ))}
    </div>
  ) : groups.papers && groups.papers.length > 0 ? (
    <div className="space-y-3">
      {groups.papers.map((paper, idx) => (
        <EvidenceListItem
          key={paper.pmid || idx}
          item={paper}
          type="paper"
        />
      ))}
    </div>
  ) : (
    <EmptyState type="paper" />
  )

  const mapsContent = isLoadingEvidence ? (
    <div className="space-y-3">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-24 bg-muted rounded-lg animate-pulse" />
      ))}
    </div>
  ) : groups.statmaps && groups.statmaps.length > 0 ? (
    <div className="space-y-3">
      {groups.statmaps.map((statmap, idx) => (
        <EvidenceListItem
          key={statmap.map_id || idx}
          item={statmap}
          type="statmap"
        />
      ))}
    </div>
  ) : (
    <EmptyState type="statmap" />
  )

  const conceptsContent = mappedConcepts.length === 0 ? (
    <EmptyState type="study" message="No concept mappings found." />
  ) : (
    <div className="space-y-3">
      {mappedConcepts.map((mc) => (
        <div key={mc.id} className="border rounded-lg p-3 text-sm flex items-center justify-between">
          <div>
            <div className="font-semibold text-gray-800">{mc.label}</div>
            <div className="text-xs text-gray-500">{mc.id}</div>
          </div>
          <Badge variant="outline" className="text-[11px]">{mc.source || 'cognitive_atlas'}</Badge>
        </div>
      ))}
    </div>
  )

  const connectionsContent = (
    <div className="space-y-3">
      <div className="rounded-lg border p-3 text-xs text-muted-foreground flex flex-wrap gap-2">
        <span className="font-medium text-foreground">1-hop neighborhood</span>
        <span>Nodes: {relatedNodeCount}</span>
        <span>Edges: {relatedEdgeCount}</span>
        {hiddenOntologyDirectEdgeCount > 0 ? (
          <span className="text-amber-700">
            Hidden ontology direct links: {hiddenOntologyDirectEdgeCount}
          </span>
        ) : null}
      </div>

      {relatedNodeCount === 0 && relatedEdgeCount === 0 ? (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground">
          {hiddenOntologyDirectEdgeCount > 0
            ? 'Only ontology direct links are available for this task. Enable "Show ontology direct links (raw)" to inspect them.'
            : 'No related nodes or edges found in the current subgraph snapshot.'}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border">
            <div className="px-3 py-2 border-b bg-muted/30 text-sm font-medium">
              Related nodes
            </div>
            <div className="max-h-72 overflow-auto divide-y">
              {visibleRelatedNodes.slice(0, 80).map((node) => (
                <div key={node.id} className="px-3 py-2 text-sm space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="font-medium truncate">{node.label}</div>
                      <div className="text-xs text-muted-foreground truncate">
                        {node.id}
                      </div>
                    </div>
                    <Badge variant="outline" className="text-[11px] shrink-0">
                      {node.type}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-1 text-[11px] text-muted-foreground">
                    <span>edges: {node.edgeCount}</span>
                    {node.relationTypes.slice(0, 3).map((relationType) => (
                      <span
                        key={`${node.id}-${relationType}`}
                        className="px-1.5 py-0.5 rounded bg-slate-100 border text-slate-700"
                      >
                        {relationType}
                      </span>
                    ))}
                    {node.relationTypes.length > 3 ? (
                      <span>+{node.relationTypes.length - 3} more</span>
                    ) : null}
                  </div>
                </div>
              ))}
              {visibleRelatedNodes.length > 80 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Showing first 80 nodes.
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-lg border">
            <div className="px-3 py-2 border-b bg-muted/30 text-sm font-medium">
              Related edges
            </div>
            <div className="max-h-72 overflow-auto divide-y">
              {visibleRelatedEdges.slice(0, 120).map((edge) => (
                <div key={edge.id} className="px-3 py-2 text-sm space-y-1">
                  <div className="font-medium text-xs text-muted-foreground">
                    {edge.relationType}
                  </div>
                  <div className="leading-snug">
                    <span className="font-medium">{edge.sourceLabel}</span>
                    <span className="text-muted-foreground px-1">
                      {edge.direction === 'outgoing' ? '->' : '<-'}
                    </span>
                    <span className="font-medium">{edge.targetLabel}</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">
                    {`${edge.sourceId} -> ${edge.targetId}`}
                  </div>
                </div>
              ))}
              {visibleRelatedEdges.length > 120 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Showing first 120 edges.
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  )

  const sparseSectionCandidates: Array<SparseSection | null> = [
    hasPapersSection ? { key: 'papers', label: 'Papers', count: Number(paperCount), content: papersContent } : null,
    hasDatasetsSection ? { key: 'datasets', label: 'Datasets', count: Number(datasetCount), content: datasetsContent } : null,
    hasMapsSection ? { key: 'brain-maps', label: 'Maps', count: Number(mapCount), content: mapsContent } : null,
    hasStudiesSection ? { key: 'studies', label: 'Studies', count: Number(studyCount), content: studiesContent } : null,
    hasTasksSection ? { key: 'tasks', label: 'Tasks', count: Number(taskCount), content: tasksContent } : null,
    hasContrastsSection ? { key: 'contrasts', label: 'Contrasts', count: Number(contrastCount), content: contrastsContent } : null,
    hasToolsSection ? { key: 'tools', label: 'Tools', count: Number(toolCount), content: toolsContent } : null,
    hasConnectionsSection ? { key: 'connections', label: 'Connections', count: Number(relatedEdgeCount), content: connectionsContent } : null,
    hasConceptsSection ? { key: 'concepts', label: 'Concepts', count: Number(conceptsCount), content: conceptsContent } : null,
  ]
  const sparseSections: SparseSection[] = sparseSectionCandidates.filter(
    (section): section is SparseSection => section !== null,
  )

  return (
    <>
    <Card className="h-full flex flex-col">
      {/* Header */}
      <CardHeader className="border-b pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="text-lg">{concept.label}</CardTitle>
            <p className="text-sm text-muted-foreground">{concept.id}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => setConceptHandoffOpen(true)}
            >
              <Code2 className="mr-2 h-3 w-3" />
              Hand off
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                const params = new URLSearchParams()
                params.set('tab', 'plan')
                params.set('conceptId', concept.id)
                router.push(`/studio?${params.toString()}`)
              }}
            >
              Open in Studio
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                const prompt = [
                  'I am exploring BR-KG and want to incorporate this concept into my analysis.',
                  `Concept: ${concept.label} (${concept.id})`,
                  concept.definition ? `Definition: ${concept.definition}` : '',
                  '',
                  'Please recommend:',
                  '- Relevant datasets (and why)',
                  '- The best official workflow/template to use first',
                  '- How to add this concept as context to my plan safely',
                ]
                  .filter(Boolean)
                  .join('\n')
                router.push(`/studio?prompt=${encodeURIComponent(prompt)}`)
              }}
            >
              Ask Assistant
            </Button>
            {lens === 'population' ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!canRouteToDatasetPage && !hasDatasetsSection}
                onClick={() => {
                  if (canRouteToDatasetPage && populationDatasetId) {
                    router.push(`/datasets/${encodeURIComponent(populationDatasetId)}`)
                    return
                  }
                  setLayoutMode('tabs')
                  setActiveTab('datasets')
                }}
              >
                {canRouteToDatasetPage ? 'Open dataset' : 'Show KG datasets'}
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!hasDatasetsSection}
                onClick={() => {
                  setLayoutMode('tabs')
                  setActiveTab('datasets')
                }}
              >
                Show KG datasets
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4 pt-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Switch
              id="show-unverified-evidence"
              checked={showUnverifiedEvidence}
              onCheckedChange={(checked) =>
                onShowUnverifiedEvidenceChange?.(Boolean(checked))
              }
            />
            <label htmlFor="show-unverified-evidence" className="cursor-pointer">
              Show unverified evidence
            </label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="auto-layout"
              checked={layoutMode === 'auto'}
              onCheckedChange={(checked) => setLayoutMode(checked ? 'auto' : 'tabs')}
            />
            <label htmlFor="auto-layout" className="cursor-pointer">
              Auto layout
            </label>
          </div>
          {lens === 'task' ? (
            <div className="flex items-center gap-2">
              <Switch
                id="show-ontology-direct-links"
                checked={showOntologyDirectLinks}
                onCheckedChange={(checked) =>
                  onShowOntologyDirectLinksChange?.(Boolean(checked))
                }
              />
              <label htmlFor="show-ontology-direct-links" className="cursor-pointer">
                Show ontology direct links (raw)
              </label>
            </div>
          ) : null}
        </div>
        {lens === 'task' ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {evidenceMeta.source_mode ? (
              <Badge variant="outline" className="text-[10px]">
                source: {evidenceMeta.source_mode}
              </Badge>
            ) : null}
            {Array.isArray(evidenceMeta.sources_used) && evidenceMeta.sources_used.length > 0 ? (
              <Badge variant="outline" className="text-[10px]">
                channels: {evidenceMeta.sources_used.join(', ')}
              </Badge>
            ) : null}
            {coverageRatio !== null ? (
              <Badge variant="outline" className="text-[10px]">
                coverage: {coverageRatio}%
              </Badge>
            ) : null}
          </div>
        ) : null}

        {isZeroCoverage || noEvidenceAvailable ? (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <div className="font-semibold">Evidence enrichment available</div>
            <div className="mt-1 text-amber-900/80">
              Run local evidence enrichment so the UI can surface dataset + paper + task links.
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onRunMultihopReasoning}
              >
                Run multihop reasoning
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onOpenDeepResearchPrompt}
              >
                Open deep-research prompt
              </Button>
            </div>
            {showInlineMultihopPanel ? (
              <div className="mt-3">
                <TaskMultihopPanel
                  taskId={concept.id}
                  taskLabel={concept.label}
                  autoRunToken={multihopAutoRunToken}
                  entityNoun={
                    { onvoc: 'concept', task: 'task', disease: 'disorder', population: 'cohort' }[
                      lens
                    ] ?? 'entity'
                  }
                  overlayEnabled={multihopOverlayEnabled}
                  onOverlayToggle={onMultihopOverlayToggle}
                  onSubgraphReady={onMultihopSubgraphReady}
                  onApproveMerge={onMultihopOverlayApprove}
                />
              </div>
            ) : null}
        </div>
      ) : null}
      </CardHeader>

      {showSparseEvidenceHint ? (
        <div className="mx-6 mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          No linked evidence for this entity yet.
        </div>
      ) : null}

      {useSparseLayout ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="p-6 space-y-6">
              <div className="space-y-3">
                <div className="text-sm font-semibold text-foreground">Overview</div>
                {overviewContent}
              </div>
              {sparseSections.map((section) => (
                <div key={section.key} className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-semibold text-foreground">{section.label}</div>
                    {section.count > 0 ? (
                      <Badge variant="secondary" className="text-xs h-5 px-1.5">
                        {section.count}
                      </Badge>
                    ) : null}
                  </div>
                  {section.content}
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
          <div className="px-6 pt-4">
            <TabsList className="w-full justify-start h-auto flex-wrap">
              <TabsTrigger value="overview" className="gap-2 text-xs">
                <Info className="h-3.5 w-3.5" />
                Overview
              </TabsTrigger>
              {hasDatasetsSection ? (
                <TabsTrigger value="datasets" className="gap-2 text-xs">
                  <Database className="h-3.5 w-3.5" />
                  Datasets
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {Number(datasetCount)}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasTasksSection ? (
                <TabsTrigger value="tasks" className="gap-2 text-xs">
                  <TestTube className="h-3.5 w-3.5" />
                  Tasks
                  {taskCount > 0 ? (
                    <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                      {taskCount}
                    </Badge>
                  ) : null}
                </TabsTrigger>
              ) : null}
              {hasContrastsSection ? (
                <TabsTrigger value="contrasts" className="gap-2 text-xs">
                  <TestTube className="h-3.5 w-3.5" />
                  Contrasts
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {contrastCount}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasToolsSection ? (
                <TabsTrigger value="tools" className="gap-2 text-xs">
                  <Wrench className="h-3.5 w-3.5" />
                  Tools
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {toolCount}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasStudiesSection ? (
                <TabsTrigger value="studies" className="gap-2 text-xs">
                  <TestTube className="h-3.5 w-3.5" />
                  Studies
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {studyCount}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasPapersSection ? (
                <TabsTrigger value="papers" className="gap-2 text-xs">
                  <FileText className="h-3.5 w-3.5" />
                  Papers
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {Number(paperCount)}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasMapsSection ? (
                <TabsTrigger value="brain-maps" className="gap-2 text-xs">
                  <Brain className="h-3.5 w-3.5" />
                  Maps
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {Number(mapCount)}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasConnectionsSection ? (
                <TabsTrigger value="connections" className="gap-2 text-xs">
                  <Network className="h-3.5 w-3.5" />
                  Connections
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {relatedEdgeCount}
                  </Badge>
                </TabsTrigger>
              ) : null}
              {hasConceptsSection ? (
                <TabsTrigger value="concepts" className="gap-2 text-xs">
                  <Network className="h-3.5 w-3.5" />
                  Concepts
                  <Badge variant="secondary" className="ml-1 text-xs h-5 px-1.5">
                    {conceptsCount}
                  </Badge>
                </TabsTrigger>
              ) : null}
            </TabsList>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            <ScrollArea className="h-full">
              <div className="p-6">
                <TabsContent value="overview" className="mt-0">
                  {overviewContent}
                </TabsContent>
                {hasDatasetsSection ? (
                  <TabsContent value="datasets" className="mt-0">
                    {datasetsContent}
                  </TabsContent>
                ) : null}
                {hasTasksSection ? (
                  <TabsContent value="tasks" className="mt-0">
                    {tasksContent}
                  </TabsContent>
                ) : null}
                {hasContrastsSection ? (
                  <TabsContent value="contrasts" className="mt-0">
                    {contrastsContent}
                  </TabsContent>
                ) : null}
                {hasToolsSection ? (
                  <TabsContent value="tools" className="mt-0">
                    {toolsContent}
                  </TabsContent>
                ) : null}
                {hasStudiesSection ? (
                  <TabsContent value="studies" className="mt-0">
                    {studiesContent}
                  </TabsContent>
                ) : null}
                {hasPapersSection ? (
                  <TabsContent value="papers" className="mt-0">
                    {papersContent}
                  </TabsContent>
                ) : null}
                {hasMapsSection ? (
                  <TabsContent value="brain-maps" className="mt-0">
                    {mapsContent}
                  </TabsContent>
                ) : null}
                {hasConnectionsSection ? (
                  <TabsContent value="connections" className="mt-0">
                    {connectionsContent}
                  </TabsContent>
                ) : null}
                {hasConceptsSection ? (
                  <TabsContent value="concepts" className="mt-0">
                    {conceptsContent}
                  </TabsContent>
                ) : null}
              </div>
            </ScrollArea>
          </div>
        </Tabs>
      )}
    </Card>
    <HandoffModal
      open={conceptHandoffOpen}
      onClose={() => setConceptHandoffOpen(false)}
      mode="template"
      payload={conceptHandoffPayload}
    />
    </>
  )
}
