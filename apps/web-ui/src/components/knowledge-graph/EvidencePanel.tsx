type EvidenceGroups = {
  statmaps: Array<{ map_id: string; space?: string; atlas?: string; contrast?: string; url?: string }>
  coords: Array<{ coord_id?: string; x?: number; y?: number; z?: number; space?: string; study_id?: string }>
  timeseries: Array<{ ts_id: string; subject_id?: string; run_id?: string; atlas?: string; url?: string }>
  datasets: Array<{ dataset_id: string; source?: string }>
  papers: Array<{ pmid?: string; doi?: string; title?: string }>
}

type NodeLite = { id: string; label: string; type?: string; connections?: number; size?: number; properties?: Record<string, any> }

type GraphNode = { data: { id: string; label: string; type?: string; meta?: Record<string, any> } }
type GraphEdge = { data: { source: string; target: string; type?: string } }

type Props = {
  evidence: EvidenceGroups
  selectedNode: NodeLite | null
  setSelectedNode: (n: NodeLite | null) => void
  allNodes?: GraphNode[]
  allEdges?: GraphEdge[]
}

function safeLabel(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

export function EvidencePanel({ evidence, selectedNode, setSelectedNode, allNodes = [], allEdges = [] }: Props) {
  const nodeById = new Map(
    allNodes
      .filter((n) => n?.data?.id)
      .map((n) => [n.data.id, n]),
  )

  const getNeighborsByType = (nodeId: string, wantedTypes: string[]) => {
    const wanted = wantedTypes.map(t => t.toLowerCase())
    const neighbors: Array<{ id: string; label: string; type?: string }> = []
    allEdges.forEach(e => {
      let neighborId: string | null = null
      if (e?.data?.source === nodeId) neighborId = e.data.target
      else if (e?.data?.target === nodeId) neighborId = e.data.source
      if (!neighborId) return
      const n = nodeById.get(neighborId)
      if (!n) return
      const nType = (n.data.type || '').toLowerCase()
      if (wanted.length === 0 || wanted.includes(nType)) {
        neighbors.push({
          id: neighborId,
          label: safeLabel(n.data.label, neighborId),
          type: n.data.type,
        })
      }
    })
    // de-dupe by id
    const seen = new Set<string>()
    return neighbors.filter(n => {
      if (seen.has(n.id)) return false
      seen.add(n.id)
      return true
    })
  }

  const isTask = selectedNode?.type?.toLowerCase() === 'task'
  const taskDatasets = selectedNode ? getNeighborsByType(selectedNode.id, ['dataset', 'dataresource']) : []
  const taskContrasts = selectedNode ? getNeighborsByType(selectedNode.id, ['contrast']) : []
  const taskStatmaps = selectedNode ? getNeighborsByType(selectedNode.id, ['statmap', 'statisticalmap']) : []
  const taskConcepts = selectedNode ? getNeighborsByType(selectedNode.id, ['concept', 'onvocclass']) : []
  const taskFamilies = selectedNode ? getNeighborsByType(selectedNode.id, ['taskfamily']) : []

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-2">Evidence</h3>
        <div className="space-y-3 text-sm text-gray-700">
          <div className="font-semibold">Stat maps ({evidence.statmaps.length})</div>
          {evidence.statmaps.length === 0 && <div className="text-gray-500 text-xs">None yet.</div>}
          {evidence.statmaps.slice(0, 6).map((m) => (
            <div key={m.map_id} className="flex items-center justify-between border rounded px-2 py-1 text-xs">
              <div>
                <div className="font-semibold">{m.contrast || m.map_id}</div>
                <div className="text-gray-500">{m.space}{m.atlas ? ` • ${m.atlas}` : ''}</div>
              </div>
              {m.url && <a href={m.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">Open</a>}
            </div>
          ))}

          <div className="font-semibold pt-2">Coordinates ({evidence.coords.length})</div>
          {evidence.coords.length === 0 && <div className="text-gray-500 text-xs">None yet.</div>}

          <div className="font-semibold pt-2">Time-series ({evidence.timeseries.length})</div>
          {evidence.timeseries.length === 0 && <div className="text-gray-500 text-xs">None yet.</div>}

          <div className="font-semibold pt-2">Datasets ({evidence.datasets.length})</div>
          {evidence.datasets.length === 0 && <div className="text-gray-500 text-xs">None yet.</div>}

          <div className="font-semibold pt-2">Papers ({evidence.papers.length})</div>
          {evidence.papers.length === 0 && <div className="text-gray-500 text-xs">None yet.</div>}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-2">Node details</h3>
        {selectedNode ? (
          <div className="space-y-2 text-sm">
            <div className="font-semibold">{safeLabel(selectedNode.label, selectedNode.id)}</div>
            <div className="text-gray-600">Type: {selectedNode.type || 'unknown'} · Degree: {selectedNode.connections ?? 0}</div>

            {isTask && (
              <div className="space-y-3 pt-2">
                {taskFamilies.length > 0 && (
                  <div className="flex flex-wrap gap-1 text-xs">
                    <span className="text-gray-500">Families:</span>
                    {taskFamilies.slice(0, 8).map(f => (
                      <span key={f.id} className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full">{f.label}</span>
                    ))}
                  </div>
                )}
                {taskConcepts.length > 0 && (
                  <div className="flex flex-wrap gap-1 text-xs">
                    <span className="text-gray-500">ONVOC:</span>
                    {taskConcepts.slice(0, 8).map(c => (
                      <span key={c.id} className="px-2 py-0.5 bg-purple-100 text-purple-800 rounded-full">{c.label}</span>
                    ))}
                  </div>
                )}
                {taskDatasets.length > 0 && (
                  <div className="text-xs text-gray-700 space-y-1">
                    <div className="text-gray-500">Datasets ({taskDatasets.length})</div>
                    <div className="flex flex-wrap gap-1">
                      {taskDatasets.slice(0, 8).map(d => (
                        <span key={d.id} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-md border border-blue-100">{d.label}</span>
                      ))}
                      {taskDatasets.length > 8 && <span className="text-gray-500">…</span>}
                    </div>
                  </div>
                )}
                {taskContrasts.length > 0 && (
                  <div className="text-xs text-gray-700 space-y-1">
                    <div className="text-gray-500">Contrasts ({taskContrasts.length})</div>
                    <div className="flex flex-wrap gap-1">
                      {taskContrasts.slice(0, 8).map(d => (
                        <span key={d.id} className="px-2 py-0.5 bg-amber-50 text-amber-700 rounded-md border border-amber-100">{d.label}</span>
                      ))}
                      {taskContrasts.length > 8 && <span className="text-gray-500">…</span>}
                    </div>
                  </div>
                )}
                {taskStatmaps.length > 0 && (
                  <div className="text-xs text-gray-700 space-y-1">
                    <div className="text-gray-500">Stat maps ({taskStatmaps.length})</div>
                    <div className="flex flex-wrap gap-1">
                      {taskStatmaps.slice(0, 8).map(d => (
                        <span key={d.id} className="px-2 py-0.5 bg-green-50 text-green-700 rounded-md border border-green-100">{d.label}</span>
                      ))}
                      {taskStatmaps.length > 8 && <span className="text-gray-500">…</span>}
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="border-t border-gray-200 pt-2 text-xs space-y-1">
              {Object.entries(selectedNode.properties || {}).slice(0, 12).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <span className="text-gray-500">{k}</span>
                  <span className="truncate">{String(v)}</span>
                </div>
              ))}
              {Object.keys(selectedNode.properties || {}).length === 0 && (
                <div className="text-gray-500">No additional properties.</div>
              )}
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-xs text-gray-500 underline hover:text-gray-700"
            >
              Clear selection
            </button>
          </div>
        ) : (
          <div className="text-sm text-gray-500">Click a node to see details.</div>
        )}
      </div>
    </div>
  )
}
