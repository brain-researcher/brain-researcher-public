'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

type TaskMultihopPanelProps = {
  taskId: string
  taskLabel: string
  autoRunToken?: number
  entityNoun?: string
  overlayEnabled?: boolean
  onOverlayToggle?: (nextValue: boolean) => void
  onSubgraphReady?: (subgraph: { nodes: any[]; edges: any[] }) => void
  onApproveMerge?: () => void
}

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord | null => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as JsonRecord
  }
  return null
}

const asArray = <T = unknown,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : [])

const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

const asString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : null

const toNodeLabel = (node: unknown): string | null => {
  if (typeof node === 'string') return asString(node)
  const obj = asRecord(node)
  if (!obj) return null
  return (
    asString(obj.label) ||
    asString(obj.name) ||
    asString(obj.id) ||
    asString(obj.kg_id) ||
    null
  )
}

const pathToText = (path: unknown): string => {
  const obj = asRecord(path)
  if (!obj) return 'Unknown path'

  const candidates = [
    asArray(obj.nodes),
    asArray(obj.node_chain),
    asArray(obj.chain),
    asArray(obj.path),
  ]
  for (const chain of candidates) {
    const labels = chain.map(toNodeLabel).filter((label): label is string => Boolean(label))
    if (labels.length > 1) return labels.join(' -> ')
  }

  const start = asString(obj.start_node_id) || asString(obj.start_kg_id)
  const end = asString(obj.end_node_id) || asString(obj.target_kg_id)
  if (start && end) return `${start} -> ${end}`

  return asString(obj.path_type) || 'Unknown path'
}

const readDataField = (data: JsonRecord, key: string): unknown => {
  if (Object.prototype.hasOwnProperty.call(data, key)) return data[key]
  const outputs = asRecord(data.outputs)
  if (outputs && Object.prototype.hasOwnProperty.call(outputs, key)) return outputs[key]
  return undefined
}

type ParsedResult = {
  answer: string | null
  summary: JsonRecord
  warnings: string[]
  paths: unknown[]
  subgraph: { nodes: any[]; edges: any[] } | null
}

const normalizeSubgraph = (
  value: unknown,
): { nodes: any[]; edges: any[] } | null => {
  const record = asRecord(value)
  if (!record) return null
  const nodes = asArray(record.nodes)
  const edges = asArray(record.edges)
  if (!Array.isArray(record.nodes) && !Array.isArray(record.edges)) return null
  return { nodes, edges }
}

const parseToolResponse = (payload: unknown): ParsedResult => {
  const root = asRecord(payload) || {}
  const result = asRecord(root.result) || root
  const data = asRecord(result.data) || {}
  const answer = asString(readDataField(data, 'answer'))
  const summary = asRecord(readDataField(data, 'summary')) || {}
  const warnings = asArray(readDataField(data, 'warnings'))
    .map((item) => asString(item))
    .filter((item): item is string => Boolean(item))
  const paths = asArray(readDataField(data, 'paths'))
  const subgraph = normalizeSubgraph(readDataField(data, 'subgraph'))

  return { answer, summary, warnings, paths, subgraph }
}

export function TaskMultihopPanel({
  taskId,
  taskLabel,
  autoRunToken,
  entityNoun,
  overlayEnabled = false,
  onOverlayToggle,
  onSubgraphReady,
  onApproveMerge,
}: TaskMultihopPanelProps) {
  const [loading, setLoading] = useState(false)
  const [expanding, setExpanding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ParsedResult | null>(null)
  const [expandedSubgraph, setExpandedSubgraph] = useState<{
    nodes: any[]
    edges: any[]
  } | null>(null)
  const lastAutoRunToken = useRef<number | null>(null)

  const baseArgs = useMemo(
    () => ({
      question: taskId || taskLabel,
      max_hops: 2,
      max_results: 12,
      mode: 'breadth_first',
    }),
    [taskId, taskLabel],
  )

  const run = async (withSubgraph: boolean) => {
    const setBusy = withSubgraph ? setExpanding : setLoading
    setBusy(true)
    setError(null)
    try {
      const response = await fetch('/api/tools/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          tool: 'kg_multihop_qa',
          arguments: { ...baseArgs, return_subgraph: withSubgraph },
          timeout_ms: 30000,
        }),
      })
      const payload: unknown = await response.json().catch(() => ({}))
      if (!response.ok) {
        const payloadObj = asRecord(payload)
        const detail = asString(payloadObj?.detail) || asString(payloadObj?.error)
        throw new Error(detail || `HTTP ${response.status}`)
      }
      const parsed = parseToolResponse(payload)
      setResult(parsed)
      if (withSubgraph) {
        setExpandedSubgraph(parsed.subgraph)
        if (parsed.subgraph && onSubgraphReady) {
          onSubgraphReady(parsed.subgraph)
        }
      }
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'Failed to run kg_multihop_qa')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (autoRunToken === undefined || autoRunToken === null) return
    if (lastAutoRunToken.current === autoRunToken) return
    lastAutoRunToken.current = autoRunToken
    if (loading || expanding) return
    void run(false)
  }, [autoRunToken, loading, expanding])

  const summary = result?.summary || {}
  const pathCount = asNumber(summary.n_paths) ?? result?.paths.length ?? 0
  const seedCount = asNumber(summary.n_seed_entities)
  const hopsUsed = asNumber(summary.hops_used)
  const maxHops = asNumber(summary.max_hops)
  const nodeCount = asArray(expandedSubgraph?.nodes).length
  const edgeCount = asArray(expandedSubgraph?.edges).length
  const showSubgraphSummary = expandedSubgraph !== null

  return (
    <div className="rounded-lg border p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">Multihop reasoning</div>
          <div className="text-xs text-muted-foreground">
            Run `kg_multihop_qa` for this {entityNoun || 'entity'} and inspect paths.
          </div>
        </div>
        <Badge variant="outline" className="text-[11px]">
          kg_multihop_qa
        </Badge>
      </div>

      {!result ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => run(false)}
          disabled={loading}
          className="h-7 px-2 text-xs"
        >
          {loading ? 'Running...' : 'Run reasoning'}
        </Button>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <div>Paths: {pathCount}</div>
            <div>Seed entities: {seedCount ?? 'n/a'}</div>
            <div>Hops used: {hopsUsed ?? 'n/a'}</div>
            <div>Max hops: {maxHops ?? 'n/a'}</div>
          </div>

          {result.answer ? <div className="text-xs">{result.answer}</div> : null}

          <div>
            <div className="text-xs font-medium text-muted-foreground">Top paths</div>
            {result.paths.length > 0 ? (
              <ol className="mt-1 list-decimal list-inside space-y-1 text-xs">
                {result.paths.slice(0, 5).map((path, idx) => (
                  <li key={`mh-path-${idx}`} className="break-words">
                    {pathToText(path)}
                  </li>
                ))}
              </ol>
            ) : (
              <div className="mt-1 text-xs text-muted-foreground">No paths returned.</div>
            )}
          </div>

          {result.warnings.length > 0 ? (
            <div>
              <div className="text-xs font-medium text-amber-700">Warnings</div>
              <ul className="mt-1 list-disc list-inside space-y-1 text-xs text-amber-700">
                {result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => run(false)}
              disabled={loading}
              className="h-7 px-2 text-xs"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => run(true)}
              disabled={expanding}
              className="h-7 px-2 text-xs"
            >
              {expanding ? 'Expanding...' : 'Expand evidence'}
            </Button>
          </div>
        </div>
      )}

      {showSubgraphSummary ? (
        <div className="space-y-2">
          <div className="rounded-md border border-muted px-2 py-2 text-xs text-muted-foreground">
            Expanded subgraph: {nodeCount} nodes, {edgeCount} edges.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOverlayToggle?.(!overlayEnabled)}
              className="h-7 px-2 text-xs"
            >
              {overlayEnabled ? 'Hide overlay' : 'Show overlay'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onApproveMerge}
              disabled={!overlayEnabled}
              className="h-7 px-2 text-xs"
            >
              Approve merge
            </Button>
          </div>
          <div className="text-xs text-muted-foreground">
            Overlay is visible in the Graph view.
          </div>
        </div>
      ) : null}

      {error ? <div className="text-xs text-destructive">{error}</div> : null}
    </div>
  )
}
