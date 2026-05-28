'use client'

import { useState, useEffect, useCallback } from 'react'
import { serviceEndpoints } from '@/lib/service-endpoints'
import { Brain, DownloadCloud } from 'lucide-react'

type EmbeddingKind = 'text' | 'activation'

type NiclipEmbedding = {
  study_id: string
  publication_id?: string | null
  kind: EmbeddingKind
  model?: string
  text_section?: string
  activation_method?: string
  activation_summary?: string
  normalization?: string
  dimension?: number
  vector_norm?: number
  storage_path?: string
  storage_index?: number
}

const DEFAULT_STUDY_ID = '9065511'

export function NiclipEmbeddingCard() {
  const [studyId, setStudyId] = useState(DEFAULT_STUDY_ID)
  const [kind, setKind] = useState<EmbeddingKind>('text')
  const [result, setResult] = useState<NiclipEmbedding | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchEmbedding = useCallback(async () => {
    const trimmed = studyId.trim()
    if (!trimmed) {
      setError('Study ID is required')
      setResult(null)
      return
    }

    setLoading(true)
    setError(null)
    try {
      // Use direct path - next.config.js rewrites /api/niclip/* to BR-KG
      const response = await fetch('/api/niclip/embedding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ study_id: trimmed, kind, include_vector: false }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data?.error || 'Failed to fetch NICLIP embedding')
      }
      setResult(data as NiclipEmbedding)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch NICLIP embedding')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [studyId, kind])

  useEffect(() => {
    fetchEmbedding()
  }, [fetchEmbedding])

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-purple-500" />
          <div>
            <h2 className="font-semibold text-gray-900">NICLIP Embedding Explorer</h2>
            <p className="text-sm text-gray-500">On-demand vectors from the Neurosynth spine</p>
          </div>
        </div>
        {result && (
          <span className="text-xs text-gray-500 capitalize">{result.kind}</span>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-[2fr,1fr,auto]">
        <input
          value={studyId}
          onChange={event => setStudyId(event.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="PMID or neurosynth ID"
        />
        <select
          value={kind}
          onChange={event => setKind(event.target.value as EmbeddingKind)}
          className="border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="text">Text / abstract</option>
          <option value="activation">Activation summary</option>
        </select>
        <button
          onClick={fetchEmbedding}
          disabled={loading}
          className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-60"
        >
          {loading ? 'Loading…' : 'Preview'}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {result && (
        <dl className="grid gap-4 md:grid-cols-2 text-sm text-gray-700">
          <div>
            <dt className="text-gray-500">Study</dt>
            <dd className="font-medium">{result.study_id}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Publication</dt>
            <dd className="font-medium">{result.publication_id ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Model</dt>
            <dd className="font-medium">{result.model ?? 'BrainGPT-7B-v0.2'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Dimension</dt>
            <dd className="font-medium">{result.dimension ?? 0} dims</dd>
          </div>
          {result.kind === 'activation' && (
            <div>
              <dt className="text-gray-500">Activation summary</dt>
              <dd className="font-medium">{result.activation_summary ?? 'unknown'}</dd>
            </div>
          )}
          <div>
            <dt className="text-gray-500">Vector norm</dt>
            <dd className="font-medium">{result.vector_norm?.toFixed(4) ?? '—'}</dd>
          </div>
          <div className="md:col-span-2">
            <dt className="text-gray-500">Storage pointer</dt>
            <dd className="font-medium flex items-center gap-2">
              <DownloadCloud className="h-4 w-4 text-blue-500" />
              <span className="truncate">{result.storage_path}</span>
              <span className="text-xs text-gray-500">#{result.storage_index}</span>
            </dd>
          </div>
        </dl>
      )}
    </div>
  )
}
