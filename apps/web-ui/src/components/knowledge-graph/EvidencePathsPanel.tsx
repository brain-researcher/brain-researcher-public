'use client'

type EvidencePathNode = {
  id?: string
  label?: string
  name?: string
  type?: string
}

export type EvidencePath = {
  id?: string
  path_type?: string
  match_method?: string
  hops?: number
  confidence?: number | null
  support_sources?: string[]
  nodes?: Array<EvidencePathNode | string>
  node_chain?: Array<EvidencePathNode | string>
  chain?: Array<EvidencePathNode | string>
  path?: Array<EvidencePathNode | string>
}

type EvidencePathsPanelProps = {
  paths: EvidencePath[]
  loading?: boolean
  error?: string | null
}

const normalizeConfidence = (value: number) => {
  const scaled = value > 1 ? value / 100 : value
  return Math.max(0, Math.min(1, scaled))
}

const confidenceBadgeClass = (confidence: number | null) => {
  if (confidence === null) {
    return 'bg-gray-100 text-gray-700 border-gray-200'
  }
  if (confidence >= 0.8) {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  }
  if (confidence >= 0.5) {
    return 'bg-amber-50 text-amber-700 border-amber-200'
  }
  return 'bg-rose-50 text-rose-700 border-rose-200'
}

const toNodeLabel = (node: EvidencePathNode | string) => {
  if (typeof node === 'string') return node
  return node.label || node.name || node.id || node.type || ''
}

const getNodeChain = (path: EvidencePath) => {
  const chain = path.nodes || path.node_chain || path.chain || path.path || []
  if (!Array.isArray(chain)) return []
  return chain.map(toNodeLabel).filter((label) => Boolean(label))
}

const getSupportSources = (path: EvidencePath) => {
  if (Array.isArray(path.support_sources)) {
    return path.support_sources
  }
  return []
}

export function EvidencePathsPanel({
  paths,
  loading = false,
  error = null,
}: EvidencePathsPanelProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">Evidence paths</h3>
        {!loading && <span className="text-xs text-gray-500">{paths.length}</span>}
      </div>

      {loading && (
        <div className="text-sm text-gray-500">Loading evidence paths...</div>
      )}

      {!loading && error && (
        <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {!loading && !error && paths.length === 0 && (
        <div className="text-sm text-gray-500">No evidence paths found for this entity.</div>
      )}

      {!loading && !error && paths.length > 0 && (
        <div className="space-y-2">
          {paths.slice(0, 12).map((path, index) => {
            const chain = getNodeChain(path)
            const hops =
              typeof path.hops === 'number'
                ? path.hops
                : chain.length > 1
                  ? chain.length - 1
                  : null
            const sources = getSupportSources(path)
            const confidence =
              typeof path.confidence === 'number'
                ? normalizeConfidence(path.confidence)
                : null
            const confidenceLabel =
              confidence === null ? 'confidence: n/a' : `confidence: ${Math.round(confidence * 100)}%`

            return (
              <div
                key={path.id || `${path.path_type || 'path'}-${index}`}
                className="border border-gray-200 rounded-md p-2 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-gray-800 truncate">
                      {path.path_type || 'unknown_path'}
                    </div>
                    <div className="text-[11px] text-gray-500 flex items-center gap-2">
                      <span>hops: {hops ?? 'n/a'}</span>
                      {path.match_method && (
                        <span className="truncate">method: {path.match_method}</span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${confidenceBadgeClass(confidence)}`}
                  >
                    {confidenceLabel}
                  </span>
                </div>

                {sources.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {sources.slice(0, 5).map((source) => (
                      <span
                        key={`${path.id || index}-${source}`}
                        className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100"
                      >
                        {source}
                      </span>
                    ))}
                    {sources.length > 5 && (
                      <span className="text-[11px] text-gray-500 px-1">
                        +{sources.length - 5} more
                      </span>
                    )}
                  </div>
                )}

                <div
                  className="text-[11px] text-gray-700 truncate"
                  title={chain.join(' -> ')}
                >
                  {chain.length > 0 ? chain.join(' -> ') : 'No node chain available.'}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
