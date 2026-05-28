'use client'

import React, { useState, useEffect, useCallback } from 'react'
import {
  Search, Filter, ChevronDown, ChevronRight, ExternalLink,
  CheckCircle2, XCircle, AlertTriangle, Clock, Tag, Plus, RefreshCw,
  Upload, Database, Shield,
} from 'lucide-react'
import type {
  BenchmarkDataset, BenchmarkTaskRow, BenchmarkTaskDetail, BenchmarkExpectedOutput,
  ImportResult, TaxonomyResponse, TaskGovernanceStatus,
} from '@/types/benchmarks'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  imported: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  triaged: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  validated: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  active: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  deprecated: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  archived: 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[status] ?? STATUS_COLORS.imported}`}>
      {status}
    </span>
  )
}


const DIFFICULTY_STYLES: Record<string, string> = {
  easy: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:ring-emerald-800',
  medium: 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:ring-amber-800',
  hard: 'bg-orange-50 text-orange-700 ring-orange-200 dark:bg-orange-900/20 dark:text-orange-300 dark:ring-orange-800',
  expert: 'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-900/20 dark:text-rose-300 dark:ring-rose-800',
}

function DifficultyBadge({ difficulty }: { difficulty: string | null }) {
  const value = (difficulty ?? 'unknown').toLowerCase()
  const style =
    DIFFICULTY_STYLES[value] ??
    'bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:ring-gray-700'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {difficulty ?? 'Unknown'}
    </span>
  )
}

function TaskCard({
  task,
  onOpen,
}: {
  task: BenchmarkTaskRow
  onOpen: (datasetId: string, taskId: string) => void
}) {
  const category = task.gov_category || task.source_category || 'Uncategorized'
  const owner = task.gov_created_by_name || task.source_created_by_name || 'Unassigned'
  const tags = task.tags.slice(0, 4)

  return (
    <button
      type="button"
      onClick={() => onOpen(task.dataset_id, task.task_id)}
      className="group w-full rounded-xl border border-gray-200 bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md dark:border-gray-700 dark:bg-gray-900/60 dark:hover:border-blue-600"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-gray-500 dark:text-gray-400">{task.task_id}</p>
          <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">{category}</p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <StatusBadge status={task.gov_status ?? 'imported'} />
          <ChevronRight className="h-4 w-4 text-gray-400 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-500" />
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <DifficultyBadge difficulty={task.source_difficulty} />
        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
          Updated {formatEpoch(task.updated_at)}
        </span>
        <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
          Owner {owner}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {tags.length === 0 ? (
          <span className="text-xs text-gray-400">No tags</span>
        ) : (
          tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/20 dark:text-blue-300"
            >
              {tag}
            </span>
          ))
        )}
        {task.tags.length > 4 && (
          <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400">
            +{task.tags.length - 4}
          </span>
        )}
      </div>
    </button>
  )
}
function formatEpoch(epoch: number) {
  return new Date(epoch * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const PRIMARY_INPUT_KEYS = ['instruction', 'prompt', 'question', 'description'] as const

function normalizeEscapedText(value: string): string {
  return value.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n').replace(/\\t/g, '\t')
}

function parseJsonLikeString(value: string): unknown | null {
  const trimmed = value.trim()
  if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    return null
  }
}

function stringifyForDisplay(value: unknown): string {
  if (typeof value === 'string') {
    const normalized = normalizeEscapedText(value)
    const parsed = parseJsonLikeString(normalized)
    if (parsed !== null) return JSON.stringify(parsed, null, 2).replace(/\\n/g, '\n')
    return normalized
  }
  try {
    return JSON.stringify(value, null, 2).replace(/\\n/g, '\n')
  } catch {
    return String(value)
  }
}

function extractPrimaryInstruction(inputs: Record<string, unknown>): string | null {
  for (const key of PRIMARY_INPUT_KEYS) {
    const value = inputs[key]
    if (typeof value === 'string' && value.trim()) {
      const normalized = normalizeEscapedText(value)
      const parsed = parseJsonLikeString(normalized)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const nested = (parsed as Record<string, unknown>).instruction
        if (typeof nested === 'string' && nested.trim()) {
          return normalizeEscapedText(nested)
        }
      }
      return normalized
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const nested = (value as Record<string, unknown>).instruction
      if (typeof nested === 'string' && nested.trim()) {
        return normalizeEscapedText(nested)
      }
    }
  }
  return null
}

function buildAuxiliaryInputs(inputs: Record<string, unknown>): Record<string, unknown> {
  const result = Object.fromEntries(
    Object.entries(inputs).filter(
      ([key]) => !PRIMARY_INPUT_KEYS.includes(key as (typeof PRIMARY_INPUT_KEYS)[number])
    )
  )

  const rawInstruction = inputs.instruction
  if (typeof rawInstruction === 'string') {
    const parsed = parseJsonLikeString(normalizeEscapedText(rawInstruction))
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        if (key === 'instruction' || key in result) continue
        result[key] = value
      }
    }
  }

  return result
}

function isGroundTruthExpectedOutput(output: BenchmarkExpectedOutput): boolean {
  const kind = String(output.kind ?? '').toLowerCase()
  if (kind === 'gt_solution') return true
  return (
    'content' in output &&
    (output.title === 'Ground Truth' || output.visibility === 'authenticated')
  )
}

function splitExpectedOutputs(expectedOutputs: BenchmarkExpectedOutput[]) {
  const gtOutputs = expectedOutputs.filter((output) => isGroundTruthExpectedOutput(output))
  const standardOutputs = expectedOutputs.filter((output) => !isGroundTruthExpectedOutput(output))
  return { gtOutputs, standardOutputs }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function humanizeKey(rawKey: string): string {
  return rawKey
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function truncateInlineText(value: string, maxLength = 200): string {
  const normalized = value.trim().replace(/\s+/g, ' ')
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength - 1)}…`
}

function summarizeUnknown(value: unknown, maxLength = 200): string {
  if (value === null || value === undefined) return 'N/A'
  if (typeof value === 'string') return truncateInlineText(normalizeEscapedText(value), maxLength)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]'
    const preview = value.slice(0, 3).map((item) => summarizeUnknown(item, 80)).join(', ')
    const suffix = value.length > 3 ? ` (+${value.length - 3} more)` : ''
    return truncateInlineText(`${preview}${suffix}`, maxLength)
  }
  const record = asRecord(value)
  if (!record) return truncateInlineText(String(value), maxLength)
  const entries = Object.entries(record).slice(0, 2)
  if (entries.length === 0) return '{}'
  const combined = entries
    .map(([key, nested]) => `${humanizeKey(key)}: ${summarizeUnknown(nested, 70)}`)
    .join('; ')
  return truncateInlineText(combined, maxLength)
}

function extractGtPayload(output: BenchmarkExpectedOutput): Record<string, unknown> | null {
  const content = asRecord(output.content)
  if (!content) return null
  const payload = asRecord(content.gt_payload)
  return payload ?? content
}

function buildGtSilverSummary(payload: Record<string, unknown> | null) {
  if (!payload) {
    return [{ label: 'Silver Answer', value: 'Not available in this GT payload.' }]
  }
  const silver = payload.silver_answer
  const silverRecord = asRecord(silver)
  if (silverRecord) {
    const rows = Object.entries(silverRecord).slice(0, 4)
    if (rows.length > 0) {
      return rows.map(([key, value]) => ({
        label: humanizeKey(key),
        value: summarizeUnknown(value),
      }))
    }
  }
  return [{ label: 'Silver Answer', value: summarizeUnknown(silver) }]
}

function buildGtEvidenceSummary(payload: Record<string, unknown> | null) {
  if (!payload) {
    return {
      meta: 'No evidence anchor available.',
      quote: null as string | null,
    }
  }
  const evidence = asRecord(payload.evidence_anchor)
  if (!evidence) {
    return {
      meta: 'No evidence anchor available.',
      quote: null as string | null,
    }
  }
  const docId = typeof evidence.doc_id === 'string' ? evidence.doc_id : null
  const source = typeof evidence.source === 'string' ? evidence.source : null
  const section = typeof evidence.section === 'string' ? evidence.section : null
  const quote = typeof evidence.quote === 'string' ? truncateInlineText(normalizeEscapedText(evidence.quote), 280) : null
  const metaParts = [docId, source, section].filter((value): value is string => Boolean(value))
  const fallback =
    metaParts.length > 0
      ? metaParts.join(' · ')
      : `${Object.keys(evidence).length} evidence field(s)`
  return {
    meta: fallback,
    quote,
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/benchmarks/${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as Record<string, string>).detail ?? `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

type TabId = 'tasks' | 'datasets' | 'governance'

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-blue-500 text-blue-600 dark:text-blue-400'
          : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Tasks Tab
// ---------------------------------------------------------------------------

function TasksTab() {
  const [tasks, setTasks] = useState<BenchmarkTaskRow[]>([])
  const [datasets, setDatasets] = useState<BenchmarkDataset[]>([])
  const [taxonomy, setTaxonomy] = useState<TaxonomyResponse | null>(null)
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterTag, setFilterTag] = useState('')
  const [filterDifficulty, setFilterDifficulty] = useState('')
  const [selectedTask, setSelectedTask] = useState<BenchmarkTaskDetail | null>(null)
  const limit = 50

  // Load datasets + taxonomy on mount
  useEffect(() => {
    let cancelled = false

    const loadMetadata = async () => {
      setMetadataError(null)
      const [datasetsResult, taxonomyResult] = await Promise.allSettled([
        apiFetch<{ datasets: BenchmarkDataset[] }>('datasets'),
        apiFetch<TaxonomyResponse>('taxonomy'),
      ])
      if (cancelled) return

      const errors: string[] = []

      if (datasetsResult.status === 'fulfilled') {
        setDatasets(datasetsResult.value.datasets)
        if (datasetsResult.value.datasets.length > 0) {
          setSelectedDataset((current) => current || datasetsResult.value.datasets[0].dataset_id)
        }
      } else {
        setDatasets([])
        errors.push(`datasets: ${datasetsResult.reason instanceof Error ? datasetsResult.reason.message : 'request failed'}`)
      }

      if (taxonomyResult.status === 'fulfilled') {
        setTaxonomy(taxonomyResult.value)
      } else {
        setTaxonomy(null)
        errors.push(`taxonomy: ${taxonomyResult.reason instanceof Error ? taxonomyResult.reason.message : 'request failed'}`)
      }

      if (errors.length > 0) {
        setMetadataError(`Failed to load benchmark metadata (${errors.join('; ')})`)
      }
    }

    void loadMetadata()
    return () => {
      cancelled = true
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchTasks = useCallback(async () => {
    if (!selectedDataset) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (search) params.set('q', search)
      if (filterStatus) params.set('status', filterStatus)
      if (filterCategory) params.set('category', filterCategory)
      if (filterTag) params.set('tag', filterTag)
      if (filterDifficulty) params.set('difficulty', filterDifficulty)
      const data = await apiFetch<{ tasks: BenchmarkTaskRow[]; total: number }>(
        `datasets/${selectedDataset}/tasks?${params}`
      )
      setTasks(data.tasks)
      setTotal(data.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load tasks')
    } finally {
      setLoading(false)
    }
  }, [selectedDataset, offset, search, filterStatus, filterCategory, filterTag, filterDifficulty])

  useEffect(() => { fetchTasks() }, [fetchTasks])

  const openDetail = async (datasetId: string, taskId: string) => {
    try {
      const detail = await apiFetch<BenchmarkTaskDetail>(`tasks/${datasetId}/${taskId}`)
      setSelectedTask(detail)
    } catch { /* ignore */ }
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedDataset}
          onChange={(e) => { setSelectedDataset(e.target.value); setOffset(0) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">Select dataset</option>
          {datasets.map((d) => (
            <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>
          ))}
        </select>

        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-2.5 top-2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search tasks..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setOffset(0) }}
            className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 pl-8 pr-3 py-1.5 text-sm"
          />
        </div>

        <select
          value={filterStatus}
          onChange={(e) => { setFilterStatus(e.target.value); setOffset(0) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          {taxonomy?.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select
          value={filterCategory}
          onChange={(e) => { setFilterCategory(e.target.value); setOffset(0) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">All categories</option>
          {taxonomy?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        <select
          value={filterDifficulty}
          onChange={(e) => { setFilterDifficulty(e.target.value); setOffset(0) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">All difficulties</option>
          {taxonomy?.difficulties.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>

        <select
          value={filterTag}
          onChange={(e) => { setFilterTag(e.target.value); setOffset(0) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">All tags</option>
          {taxonomy?.tags.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <button type="button" onClick={fetchTasks} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700">
          <RefreshCw className="h-4 w-4 text-gray-500" />
        </button>
      </div>

      {/* Error */}
      {metadataError && (
        <div className="rounded-md bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {metadataError}
        </div>
      )}
      {error && (
        <div className="rounded-md bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Task Cards */}
      <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3 dark:border-gray-700 dark:bg-gray-900/30">
        {loading ? (
          <div className="rounded-lg bg-white p-8 text-center text-sm text-gray-400 dark:bg-gray-900 dark:text-gray-500">
            Loading tasks...
          </div>
        ) : tasks.length === 0 ? (
          <div className="rounded-lg bg-white p-8 text-center text-sm text-gray-400 dark:bg-gray-900 dark:text-gray-500">
            {selectedDataset ? 'No tasks found' : 'Select a dataset to view tasks'}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {tasks.map((t) => (
              <TaskCard key={`${t.dataset_id}/${t.task_id}`} task={t} onOpen={openDetail} />
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500 dark:text-gray-400">
            Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
              className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {selectedTask && <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTask(null)} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Task Detail Drawer
// ---------------------------------------------------------------------------

function TaskDetailDrawer({ task, onClose }: { task: BenchmarkTaskDetail; onClose: () => void }) {
  const [govForm, setGovForm] = useState({
    status: task.governance?.status ?? 'imported',
    category: task.governance?.category ?? '',
    owner: task.governance?.owner ?? '',
    notes: task.governance?.notes ?? '',
    created_by_name: task.governance?.created_by_name ?? task.source_created_by_name ?? '',
    created_by_email: task.governance?.created_by_email ?? '',
    created_by_profile: task.governance?.created_by_profile ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [expandedGt, setExpandedGt] = useState<Record<string, boolean>>({})

  const [valForm, setValForm] = useState({ validator: '', type: 'manual_review', result: 'pass', notes: '' })
  const [addingVal, setAddingVal] = useState(false)
  const instructionText = extractPrimaryInstruction(task.task_spec.inputs)
  const auxiliaryInputs = buildAuxiliaryInputs(task.task_spec.inputs)
  const { gtOutputs, standardOutputs } = splitExpectedOutputs(task.task_spec.expected_outputs)

  useEffect(() => {
    setExpandedGt({})
  }, [task.dataset_id, task.task_id])

  const saveGovernance = async () => {
    setSaving(true)
    try {
      await apiFetch(`tasks/${task.dataset_id}/${task.task_id}/governance`, {
        method: 'PATCH',
        body: JSON.stringify(govForm),
      })
    } finally { setSaving(false) }
  }

  const addValidation = async () => {
    setAddingVal(true)
    try {
      await apiFetch(`tasks/${task.dataset_id}/${task.task_id}/validations`, {
        method: 'POST',
        body: JSON.stringify(valForm),
      })
      setValForm({ validator: '', type: 'manual_review', result: 'pass', notes: '' })
    } finally { setAddingVal(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative w-full max-w-2xl bg-white dark:bg-gray-900 shadow-xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{task.task_id}</h2>
            <p className="text-sm text-gray-500">{task.dataset_id} &middot; {task.task_spec.name ?? ''}</p>
          </div>
          <button type="button" onClick={onClose} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded">
            &times;
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Governance */}
          <section>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
              <Shield className="h-4 w-4" /> Governance
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-gray-500">Status</span>
                <select
                  value={govForm.status}
                  onChange={(e) => setGovForm((f) => ({ ...f, status: e.target.value as TaskGovernanceStatus }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                >
                  {['imported', 'triaged', 'validated', 'active', 'deprecated', 'archived'].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Category</span>
                <input
                  value={govForm.category}
                  onChange={(e) => setGovForm((f) => ({ ...f, category: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Owner</span>
                <input
                  value={govForm.owner}
                  onChange={(e) => setGovForm((f) => ({ ...f, owner: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Notes</span>
                <input
                  value={govForm.notes}
                  onChange={(e) => setGovForm((f) => ({ ...f, notes: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Created by</span>
                <input
                  value={govForm.created_by_name}
                  onChange={(e) => setGovForm((f) => ({ ...f, created_by_name: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Created by email</span>
                <input
                  value={govForm.created_by_email}
                  onChange={(e) => setGovForm((f) => ({ ...f, created_by_email: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Created by profile</span>
                <input
                  value={govForm.created_by_profile}
                  onChange={(e) => setGovForm((f) => ({ ...f, created_by_profile: e.target.value }))}
                  className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                />
              </label>
            </div>
            <button
              type="button"
              onClick={saveGovernance}
              disabled={saving}
              className="mt-3 px-4 py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save governance'}
            </button>
          </section>

          {/* Instruction */}
          <section>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Instruction</h3>
            {instructionText ? (
              <pre className="bg-gray-50 dark:bg-gray-800 rounded p-3 text-xs overflow-x-auto whitespace-pre-wrap">
                {instructionText}
              </pre>
            ) : (
              <p className="text-xs text-gray-500">
                No primary instruction field found. Showing structured inputs below.
              </p>
            )}
            {Object.keys(auxiliaryInputs).length > 0 && (
              <div className="mt-2">
                <h4 className="text-xs text-gray-600 dark:text-gray-300 mb-2">
                  Structured Inputs (Harbor)
                </h4>
                <pre className="bg-gray-50 dark:bg-gray-800 rounded p-3 text-xs overflow-x-auto whitespace-pre-wrap">
                  {stringifyForDisplay(auxiliaryInputs)}
                </pre>
              </div>
            )}
          </section>

          {/* Expected Output */}
          {task.task_spec.expected_outputs.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Expected Output</h3>
              {standardOutputs.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-gray-500">Artifact / schema expectations</p>
                  {standardOutputs.map((output, index) => (
                    <div key={`out-${String(output.id ?? index)}`} className="bg-gray-50 dark:bg-gray-800 rounded p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-mono text-[11px] text-gray-500">
                          {String(output.id ?? `out_${index + 1}`)}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-[10px] font-medium text-gray-700 dark:text-gray-200">
                          expected
                        </span>
                      </div>
                      <pre className="text-xs overflow-x-auto whitespace-pre-wrap">
                        {stringifyForDisplay(output)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}

              {gtOutputs.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center gap-2 px-1">
                    <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">Ground Truth</span>
                    <span className="px-1.5 py-0.5 rounded bg-orange-100 text-[10px] font-medium text-orange-700 dark:bg-orange-900/30 dark:text-orange-300">
                      summarized by default
                    </span>
                  </div>
                  {gtOutputs.map((output, index) => {
                    const outputId = String(output.id ?? `gt_${index + 1}`)
                    const payload = extractGtPayload(output)
                    const summaryRows = buildGtSilverSummary(payload)
                    const evidenceSummary = buildGtEvidenceSummary(payload)
                    const content = asRecord(output.content)
                    const quality =
                      (typeof content?.gt_quality === 'string' && content.gt_quality) ||
                      (typeof payload?.quality === 'string' && payload.quality) ||
                      null
                    const isExpanded = expandedGt[outputId] ?? false

                    return (
                      <div
                        key={`gt-${outputId}`}
                        className="rounded-lg border-2 border-orange-300 bg-orange-50/90 dark:border-orange-700 dark:bg-orange-900/20"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedGt((prev) => ({ ...prev, [outputId]: !isExpanded }))
                          }
                          className="flex w-full items-center justify-between px-3 py-2 text-left"
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4 text-orange-700 dark:text-orange-300" />
                            ) : (
                              <ChevronRight className="h-4 w-4 text-orange-700 dark:text-orange-300" />
                            )}
                            <span className="font-mono text-[11px] text-gray-700 dark:text-gray-200">{outputId}</span>
                            <span className="px-1.5 py-0.5 rounded bg-orange-200 text-[10px] font-semibold text-orange-900 dark:bg-orange-800 dark:text-orange-100">
                              GT
                            </span>
                            {quality && (
                              <span className="px-1.5 py-0.5 rounded bg-white/80 text-[10px] font-medium text-orange-800 dark:bg-gray-800 dark:text-orange-200">
                                {quality}
                              </span>
                            )}
                            {typeof output.visibility === 'string' && output.visibility.trim() && (
                              <span className="px-1.5 py-0.5 rounded bg-gray-200 text-[10px] font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-200">
                                {output.visibility}
                              </span>
                            )}
                          </div>
                          <span className="text-[11px] font-medium text-orange-800 dark:text-orange-200">
                            {isExpanded ? 'Hide full GT' : 'Show full GT JSON'}
                          </span>
                        </button>

                        <div className="space-y-2 border-t border-orange-200 px-3 pb-3 pt-2 dark:border-orange-800/60">
                          <div className="rounded border border-orange-200 bg-white/90 p-2 dark:border-orange-800/70 dark:bg-gray-900/60">
                            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-orange-700 dark:text-orange-300">
                              Silver Answer
                            </p>
                            <div className="space-y-1">
                              {summaryRows.map((row) => (
                                <div key={row.label} className="text-xs">
                                  <span className="font-medium text-gray-700 dark:text-gray-200">{row.label}:</span>{' '}
                                  <span className="text-gray-600 dark:text-gray-300">{row.value}</span>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="rounded border border-orange-200 bg-white/90 p-2 dark:border-orange-800/70 dark:bg-gray-900/60">
                            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-orange-700 dark:text-orange-300">
                              Evidence Anchor
                            </p>
                            <p className="text-xs text-gray-700 dark:text-gray-200">{evidenceSummary.meta}</p>
                            {evidenceSummary.quote && (
                              <p className="mt-1 text-xs italic text-gray-600 dark:text-gray-300">
                                &ldquo;{evidenceSummary.quote}&rdquo;
                              </p>
                            )}
                          </div>

                          {isExpanded && (
                            <pre className="text-xs overflow-x-auto whitespace-pre-wrap rounded border border-orange-200 bg-orange-100/60 p-2 dark:border-orange-800/70 dark:bg-orange-950/30">
                              {stringifyForDisplay(output)}
                            </pre>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              {task.task_spec.scoring && (
                <div className="mt-2">
                  <span className="text-xs text-gray-500">Scoring:</span>
                  <pre className="bg-gray-50 dark:bg-gray-800 rounded p-2 text-xs mt-1 whitespace-pre-wrap">
                    {stringifyForDisplay(task.task_spec.scoring)}
                  </pre>
                </div>
              )}
            </section>
          )}

          {/* Tags */}
          {task.tags.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Tags</h3>
              <div className="flex flex-wrap gap-1">
                {task.tags.map((tag) => (
                  <span key={tag} className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 rounded text-xs">{tag}</span>
                ))}
              </div>
            </section>
          )}

          {/* Validations */}
          <section>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" /> Validations ({task.validations.length})
            </h3>
            {task.validations.length > 0 && (
              <div className="space-y-2 mb-3">
                {task.validations.map((v) => (
                  <div key={v.id} className="flex items-start gap-2 p-2 rounded bg-gray-50 dark:bg-gray-800 text-xs">
                    {v.result === 'pass' ? <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5" />
                      : v.result === 'fail' ? <XCircle className="h-4 w-4 text-red-500 mt-0.5" />
                      : <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5" />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{v.validator}</span>
                        <span className="text-gray-400">{v.type}</span>
                        <span className="text-gray-400 ml-auto">{formatEpoch(v.validated_at)}</span>
                      </div>
                      {v.notes && <p className="text-gray-500 mt-0.5">{v.notes}</p>}
                      {v.evidence_url && (
                        <a href={v.evidence_url} target="_blank" rel="noopener noreferrer"
                          className="text-blue-500 hover:underline inline-flex items-center gap-1 mt-0.5">
                          Evidence <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add validation form */}
            <div className="border border-gray-200 dark:border-gray-700 rounded p-3 space-y-2">
              <p className="text-xs font-medium text-gray-500">Add validation</p>
              <div className="grid grid-cols-3 gap-2">
                <input
                  placeholder="Validator"
                  value={valForm.validator}
                  onChange={(e) => setValForm((f) => ({ ...f, validator: e.target.value }))}
                  className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs"
                />
                <select
                  value={valForm.type}
                  onChange={(e) => setValForm((f) => ({ ...f, type: e.target.value }))}
                  className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs"
                >
                  {['manual_review', 'ci_tests', 'oracle_solution', 'security_audit', 'llm_judge'].map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <select
                  value={valForm.result}
                  onChange={(e) => setValForm((f) => ({ ...f, result: e.target.value }))}
                  className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs"
                >
                  {['pass', 'fail', 'needs_fix'].map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <input
                placeholder="Notes (optional)"
                value={valForm.notes}
                onChange={(e) => setValForm((f) => ({ ...f, notes: e.target.value }))}
                className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs"
              />
              <button
                type="button"
                onClick={addValidation}
                disabled={addingVal || !valForm.validator}
                className="px-3 py-1 bg-green-500 hover:bg-green-600 text-white text-xs rounded disabled:opacity-50"
              >
                {addingVal ? 'Adding...' : 'Add'}
              </button>
            </div>
          </section>

          {/* Source info */}
          <section>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">Source</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <dt className="text-gray-500">Dataset</dt>
              <dd>{task.dataset?.name ?? task.dataset_id}</dd>
              <dt className="text-gray-500">Version</dt>
              <dd>{task.dataset?.version ?? '-'}</dd>
              <dt className="text-gray-500">Created by</dt>
              <dd>{task.governance?.created_by_name ?? task.source_created_by_name ?? '-'}</dd>
              <dt className="text-gray-500">Content hash</dt>
              <dd className="font-mono truncate">{task.content_hash}</dd>
            </dl>
          </section>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Datasets Tab
// ---------------------------------------------------------------------------

function DatasetsTab() {
  const [datasets, setDatasets] = useState<BenchmarkDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Import form
  const [importUrl, setImportUrl] = useState('')
  const [importDatasetId, setImportDatasetId] = useState('')
  const [importVersion, setImportVersion] = useState('1.0')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const fetchDatasets = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await apiFetch<{ datasets: BenchmarkDataset[] }>('datasets')
      setDatasets(data.datasets)
    } catch (e) {
      setDatasets([])
      setLoadError(e instanceof Error ? e.message : 'Failed to load datasets')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchDatasets() }, [fetchDatasets])

  const doImport = async () => {
    if (!importUrl) return
    setImporting(true)
    setImportError(null)
    setImportResult(null)
    try {
      const result = await apiFetch<ImportResult>('import', {
        method: 'POST',
        body: JSON.stringify({
          url: importUrl,
          dataset_id: importDatasetId || undefined,
          version: importVersion || '1.0',
        }),
      })
      setImportResult(result)
      fetchDatasets()
    } catch (e) {
      setImportError(e instanceof Error ? e.message : 'Import failed')
    } finally { setImporting(false) }
  }

  return (
    <div className="space-y-6">
      {/* Import form */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
          <Upload className="h-4 w-4" /> Import benchmark dataset
        </h3>
        <div className="flex flex-wrap gap-3 items-end">
          <label className="block flex-1 min-w-[250px]">
            <span className="text-xs text-gray-500">Registry URL (JSON)</span>
            <input
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              placeholder="https://example.com/tasks.json"
              className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
            />
          </label>
          <label className="block w-40">
            <span className="text-xs text-gray-500">Dataset ID (optional)</span>
            <input
              value={importDatasetId}
              onChange={(e) => setImportDatasetId(e.target.value)}
              placeholder="auto-detect"
              className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
            />
          </label>
          <label className="block w-24">
            <span className="text-xs text-gray-500">Version</span>
            <input
              value={importVersion}
              onChange={(e) => setImportVersion(e.target.value)}
              className="mt-1 block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
            />
          </label>
          <button
            type="button"
            onClick={doImport}
            disabled={importing || !importUrl}
            className="px-4 py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded disabled:opacity-50"
          >
            {importing ? 'Importing...' : 'Import'}
          </button>
        </div>

        {importResult && (
          <div className="rounded bg-green-50 dark:bg-green-900/20 p-3 text-sm text-green-700 dark:text-green-300">
            Import {importResult.status}: {importResult.summary.added} added, {importResult.summary.updated} updated, {importResult.summary.skipped} skipped, {importResult.summary.failed} failed
          </div>
        )}
        {importError && (
          <div className="rounded bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">{importError}</div>
        )}
      </div>

      {/* Dataset list */}
      {loadError && (
        <div className="rounded bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {loadError}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading ? (
          <div className="col-span-full text-center text-gray-400 py-8">Loading datasets...</div>
        ) : datasets.length === 0 ? (
          <div className="col-span-full text-center text-gray-400 py-8">No datasets imported yet. Use the form above to import one.</div>
        ) : datasets.map((d) => (
          <div key={d.dataset_id} className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-start justify-between">
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">{d.name}</h4>
                <p className="text-xs text-gray-500 mt-0.5">{d.dataset_id} &middot; v{d.version}</p>
              </div>
              <StatusBadge status={d.status} />
            </div>
            {d.description && <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">{d.description}</p>}
            <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
              <span>Imported {formatEpoch(d.imported_at)}</span>
              <span>&middot;</span>
              <span>Updated {formatEpoch(d.updated_at)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Governance Tab (batch updates)
// ---------------------------------------------------------------------------

function GovernanceTab() {
  const [datasets, setDatasets] = useState<BenchmarkDataset[]>([])
  const [selectedDataset, setSelectedDataset] = useState('')
  const [taxonomy, setTaxonomy] = useState<TaxonomyResponse | null>(null)
  const [tasks, setTasks] = useState<BenchmarkTaskRow[]>([])
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const [tasksError, setTasksError] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchStatus, setBatchStatus] = useState('')
  const [batchCategory, setBatchCategory] = useState('')
  const [applying, setApplying] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const loadMetadata = async () => {
      setMetadataError(null)
      const [datasetsResult, taxonomyResult] = await Promise.allSettled([
        apiFetch<{ datasets: BenchmarkDataset[] }>('datasets'),
        apiFetch<TaxonomyResponse>('taxonomy'),
      ])
      if (cancelled) return

      const errors: string[] = []

      if (datasetsResult.status === 'fulfilled') {
        setDatasets(datasetsResult.value.datasets)
        if (datasetsResult.value.datasets.length > 0) {
          setSelectedDataset((current) => current || datasetsResult.value.datasets[0].dataset_id)
        }
      } else {
        setDatasets([])
        errors.push(`datasets: ${datasetsResult.reason instanceof Error ? datasetsResult.reason.message : 'request failed'}`)
      }

      if (taxonomyResult.status === 'fulfilled') {
        setTaxonomy(taxonomyResult.value)
      } else {
        setTaxonomy(null)
        errors.push(`taxonomy: ${taxonomyResult.reason instanceof Error ? taxonomyResult.reason.message : 'request failed'}`)
      }

      if (errors.length > 0) {
        setMetadataError(`Failed to load governance metadata (${errors.join('; ')})`)
      }
    }

    void loadMetadata()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedDataset) return
    setTasksError(null)
    apiFetch<{ tasks: BenchmarkTaskRow[] }>(`datasets/${selectedDataset}/tasks?limit=200`)
      .then((r) => setTasks(r.tasks))
      .catch((e) => {
        setTasks([])
        setTasksError(e instanceof Error ? e.message : 'Failed to load governance tasks')
      })
  }, [selectedDataset])

  const toggleId = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedIds.size === tasks.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(tasks.map((t) => t.task_id)))
  }

  const applyBatch = async () => {
    if (selectedIds.size === 0) return
    setApplying(true)
    setMessage(null)
    let ok = 0
    for (const taskId of Array.from(selectedIds)) {
      try {
        const body: Record<string, string> = {}
        if (batchStatus) body.status = batchStatus
        if (batchCategory) body.category = batchCategory
        if (Object.keys(body).length > 0) {
          await apiFetch(`tasks/${selectedDataset}/${taskId}/governance`, {
            method: 'PATCH',
            body: JSON.stringify(body),
          })
          ok++
        }
      } catch { /* continue */ }
    }
    setApplying(false)
    setMessage(`Updated ${ok} of ${selectedIds.size} tasks`)
  }

  return (
    <div className="space-y-4">
      {metadataError && (
        <div className="rounded bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {metadataError}
        </div>
      )}
      {tasksError && (
        <div className="rounded bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {tasksError}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={selectedDataset}
          onChange={(e) => { setSelectedDataset(e.target.value); setSelectedIds(new Set()) }}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          {datasets.map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}
        </select>

        <select
          value={batchStatus}
          onChange={(e) => setBatchStatus(e.target.value)}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm"
        >
          <option value="">Set status...</option>
          {['imported', 'triaged', 'validated', 'active', 'deprecated', 'archived'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <input
          placeholder="Set category..."
          value={batchCategory}
          onChange={(e) => setBatchCategory(e.target.value)}
          className="rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm w-40"
        />

        <button
          type="button"
          onClick={applyBatch}
          disabled={applying || selectedIds.size === 0 || (!batchStatus && !batchCategory)}
          className="px-4 py-1.5 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded disabled:opacity-50"
        >
          {applying ? 'Applying...' : `Apply to ${selectedIds.size} selected`}
        </button>

        {message && <span className="text-sm text-green-600 dark:text-green-400">{message}</span>}
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th className="px-4 py-2">
                <input type="checkbox" checked={selectedIds.size === tasks.length && tasks.length > 0} onChange={toggleAll} />
              </th>
              <th className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Task ID</th>
              <th className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Status</th>
              <th className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Category</th>
              <th className="px-4 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {tasks.map((t) => (
              <tr key={t.task_id} className={selectedIds.has(t.task_id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}>
                <td className="px-4 py-2">
                  <input type="checkbox" checked={selectedIds.has(t.task_id)} onChange={() => toggleId(t.task_id)} />
                </td>
                <td className="px-4 py-2 font-mono text-xs">{t.task_id}</td>
                <td className="px-4 py-2"><StatusBadge status={t.gov_status ?? 'imported'} /></td>
                <td className="px-4 py-2 text-xs">{t.gov_category || t.source_category || '-'}</td>
                <td className="px-4 py-2 text-xs">{t.owner || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function BenchmarkPage() {
  const [activeTab, setActiveTab] = useState<TabId>('tasks')

  return (
    <NavigationWrapper>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Benchmark Board</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Browse, govern, and import benchmark evaluation tasks.
          </p>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6 flex gap-0">
          <TabButton active={activeTab === 'tasks'} onClick={() => setActiveTab('tasks')}>Tasks</TabButton>
          <TabButton active={activeTab === 'datasets'} onClick={() => setActiveTab('datasets')}>Datasets</TabButton>
          <TabButton active={activeTab === 'governance'} onClick={() => setActiveTab('governance')}>Governance</TabButton>
        </div>

        {activeTab === 'tasks' && <TasksTab />}
        {activeTab === 'datasets' && <DatasetsTab />}
        {activeTab === 'governance' && <GovernanceTab />}
      </div>
    </NavigationWrapper>
  )
}
