'use client'

import { memo } from 'react'

export type QueryType = 'paths' | 'neighbors' | 'clusters' | 'similar'

interface QueryBuilderPanelProps {
  queryType: QueryType
  startId: string
  depth: number
  loading: boolean
  error: string | null
  resultCounts: { nodes: number; edges: number } | null
  onQueryTypeChange: (type: QueryType) => void
  onStartIdChange: (id: string) => void
  onDepthChange: (depth: number) => void
  onRun: () => void
}

const QueryBuilderPanelRaw = ({
  queryType,
  startId,
  depth,
  loading,
  error,
  resultCounts,
  onQueryTypeChange,
  onStartIdChange,
  onDepthChange,
  onRun
}: QueryBuilderPanelProps) => {
  return (
    <div className="p-6 space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-1">
          <label className="text-sm text-gray-600">Query type</label>
          <select
            value={queryType}
            onChange={(e) => onQueryTypeChange(e.target.value as QueryType)}
            className="w-full mt-1 p-2 border rounded-lg text-sm"
          >
            <option value="paths">Paths</option>
            <option value="neighbors">Neighbors</option>
            <option value="clusters">Clusters</option>
            <option value="similar">Similar</option>
          </select>
        </div>
        <div className="col-span-1">
          <label className="text-sm text-gray-600">Start node ID</label>
          <input
            type="text"
            value={startId}
            onChange={(e) => onStartIdChange(e.target.value)}
            placeholder="Enter a start node ID"
            className="w-full mt-1 p-2 border rounded-lg text-sm"
          />
        </div>
        <div className="col-span-1">
          <label className="text-sm text-gray-600">Depth</label>
          <input
            type="number"
            min={1}
            max={6}
            value={depth}
            onChange={(e) => onDepthChange(Math.max(1, Math.min(6, Number(e.target.value))))}
            className="w-full mt-1 p-2 border rounded-lg text-sm"
          />
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded p-2">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={onRun}
          disabled={loading}
          className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 disabled:opacity-50"
        >
          {loading ? 'Running...' : 'Run query'}
        </button>
        {resultCounts && (
          <div className="text-sm text-gray-600">
            {resultCounts.nodes} nodes • {resultCounts.edges} edges
          </div>
        )}
      </div>
    </div>
  )
}

export const QueryBuilderPanel = memo(QueryBuilderPanelRaw)
