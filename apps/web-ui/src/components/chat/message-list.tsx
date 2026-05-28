'use client'

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import Link from 'next/link'

// Type assertion for react-markdown compatibility with React 18
const Markdown = ReactMarkdown as React.ComponentType<{
  children: string
  remarkPlugins?: any[]
  rehypePlugins?: any[]
}>
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import { User, Bot } from 'lucide-react'
import { Message } from '@/types/chat'
import { ExecutionBlock } from './execution-block'
import { DiagnosisCard } from './diagnosis-card'
import { PlanCard } from './plan-card'
import { RepairCard } from './repair-card'
import { Button } from '@/components/ui/button'
import { ANALYSIS_TYPES } from '@/config/analysis-presets'
import { planForError } from '@/lib/errors'
import {
  extractRepairProposal,
  stripFirstJsonFence,
  type RepairProposal,
} from '@/lib/chat-repair'

interface MessageListProps {
  messages: Message[]
  onCancelExecution?: (jobId: string) => void
  onResumeFromCheckpoint?: (checkpointId: string) => void
  onAskAgent?: (prompt: string) => void
  onReplacePlan?: (pipelineId: string) => void
  onApplyRepair?: (proposal: RepairProposal) => void
  onRevalidateRepair?: (proposal: RepairProposal) => void
  onHandOffRepair?: (proposal: RepairProposal) => void
}

type PipelineCardInfo = {
  pipelineId: string
  title: string
  description?: string
  estRuntime?: string
}

const PIPELINE_BY_ID = new Map<string, PipelineCardInfo>(
  ANALYSIS_TYPES.flatMap((analysis) =>
    analysis.pipelines.map((pipeline) => [
      pipeline.id,
      {
        pipelineId: pipeline.id,
        title: `${analysis.label} · ${pipeline.label}`,
        description: pipeline.description,
        estRuntime: pipeline.estRuntime,
      },
    ]),
  ),
)

function getString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function formatCodingEventPreview(evt: any): string {
  const type = String(evt?.type || '').toLowerCase()
  const data = evt?.data

  if (type === 'done') {
    const totalLength =
      data && typeof data === 'object' && typeof data.total_length === 'number'
        ? data.total_length
        : null
    return totalLength != null ? `Completed (${totalLength} chars)` : 'Completed'
  }

  if (type === 'stream_end') {
    return 'Stream ended'
  }

  return typeof data === 'string' ? data : JSON.stringify(data)
}

function parseTemplateId(value: unknown): { analysisId: string; pipelineId: string } | null {
  const raw = getString(value)
  if (!raw) return null
  const parts = raw.split(/[:/]/).filter(Boolean)
  if (parts.length !== 2) return null
  const [analysisId, pipelineId] = parts
  if (!analysisId || !pipelineId) return null
  return { analysisId, pipelineId }
}

function findSuggestedPipelineId(message: Message): string | null {
  const meta = message.metadata
  if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
    const pipelineDirect =
      getString((meta as any).pipeline_id) ||
      getString((meta as any).pipelineId) ||
      getString((meta as any).pipeline)
    if (pipelineDirect && PIPELINE_BY_ID.has(pipelineDirect)) return pipelineDirect

    const templateDirect =
      parseTemplateId((meta as any).template_id) || parseTemplateId((meta as any).templateId)
    if (templateDirect && PIPELINE_BY_ID.has(templateDirect.pipelineId)) {
      return templateDirect.pipelineId
    }

    const toolCalls = (meta as any).tool_calls
    if (Array.isArray(toolCalls)) {
      for (const tc of toolCalls) {
        const pipelineCandidate =
          getString(tc?.pipeline_id) ||
          getString(tc?.pipelineId) ||
          getString(tc?.pipeline)
        if (pipelineCandidate && PIPELINE_BY_ID.has(pipelineCandidate)) return pipelineCandidate

        const fromTemplate = parseTemplateId(tc?.template_id) || parseTemplateId(tc?.templateId)
        if (fromTemplate && PIPELINE_BY_ID.has(fromTemplate.pipelineId)) return fromTemplate.pipelineId

        const result = tc?.result ?? tc?.output
        if (result && typeof result === 'object' && !Array.isArray(result)) {
          const pipelineFromResult =
            getString((result as any).pipeline_id) ||
            getString((result as any).pipelineId) ||
            getString((result as any).pipeline)
          if (pipelineFromResult && PIPELINE_BY_ID.has(pipelineFromResult)) {
            return pipelineFromResult
          }

          const templateFromResult =
            parseTemplateId((result as any).template_id) ||
            parseTemplateId((result as any).templateId)
          if (templateFromResult && PIPELINE_BY_ID.has(templateFromResult.pipelineId)) {
            return templateFromResult.pipelineId
          }
        }
      }
    }
  }

  return null
}

function findSuggestedToolLabel(message: Message): string | null {
  const meta = message.metadata
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null

  const metaRecord = meta as Record<string, unknown>

  const direct =
    getString((metaRecord as any).tool) ||
    getString((metaRecord as any).tool_name) ||
    getString((metaRecord as any).toolName)
  if (direct) return direct

  const toolCalls = (metaRecord as any).tool_calls
  if (Array.isArray(toolCalls)) {
    for (const tc of toolCalls) {
      const tool =
        getString(tc?.tool) ||
        getString(tc?.tool_name) ||
        getString(tc?.toolName) ||
        getString(tc?.name)
      if (tool) return tool

      const result = tc?.result ?? tc?.output
      if (result && typeof result === 'object' && !Array.isArray(result)) {
        const resultTool =
          getString((result as any).tool) ||
          getString((result as any).tool_name) ||
          getString((result as any).toolName) ||
          getString((result as any).name)
        if (resultTool) return resultTool
      }
    }
  }

  const recommendedTools = (metaRecord as any).recommended_tools ?? (metaRecord as any).recommendedTools
  if (Array.isArray(recommendedTools)) {
    for (const candidate of recommendedTools) {
      const tool =
        getString(candidate?.tool) ||
        getString(candidate?.name) ||
        getString(candidate?.tool_name) ||
        getString(candidate?.toolName) ||
        getString(candidate)
      if (tool) return tool
    }
  }

  return null
}

function asRecord(value: unknown): Record<string, any> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, any>
}

function asArray(value: unknown): any[] {
  return Array.isArray(value) ? value : []
}

function parseJsonLike(value: unknown): unknown {
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function getToolCallsFromMessage(message: Message): any[] {
  const meta = asRecord(message.metadata)
  if (!meta) return []
  const direct = asArray(meta.tool_calls)
  if (direct.length) return direct
  const runCard = asRecord(meta.runCard)
  const provenance = asRecord(runCard?.provenance)
  const execution = asRecord(runCard?.execution)
  return asArray(provenance?.tool_calls).length
    ? asArray(provenance?.tool_calls)
    : asArray(execution?.tool_calls)
}

function getToolCallName(toolCall: any): string {
  const candidates = [
    toolCall?.name,
    toolCall?.tool,
    toolCall?.tool_name,
    toolCall?.function?.name,
    toolCall?.plan?.tool,
    toolCall?.plan?.leaf_runtime_id,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim()
  }
  return ''
}

function isKgMultihopToolCall(toolCall: any): boolean {
  const name = getToolCallName(toolCall).toLowerCase()
  return (
    name === 'kg_multihop_qa' ||
    name === 'kg_multihop_qa_tool' ||
    name.endsWith('.kg_multihop_qa') ||
    name.endsWith('.kg_multihop_qa_tool')
  )
}

function extractToolArgs(toolCall: any): Record<string, any> {
  const candidates = [
    toolCall?.arguments,
    toolCall?.args,
    toolCall?.input,
    toolCall?.function?.arguments,
    toolCall?.plan?.params,
    toolCall?.plan?.arguments,
  ]
  for (const candidate of candidates) {
    const parsed = parseJsonLike(candidate)
    const record = asRecord(parsed)
    if (record) return { ...record }
  }
  return {}
}

function extractKgPayload(toolCall: any): Record<string, any> {
  const queue: unknown[] = [toolCall?.result, toolCall?.output]
  const visited = new Set<unknown>()

  while (queue.length > 0) {
    const current = queue.shift()
    if (!current || visited.has(current)) continue
    visited.add(current)

    const record = asRecord(current)
    if (record) {
      if (
        record.outputs ||
        record.summary ||
        record.paths ||
        record.top_paths ||
        record.answer ||
        record.subgraph
      ) {
        return record
      }
      const nestedData = asRecord(record.data)
      if (nestedData) queue.push(nestedData)
      const nestedResult = asRecord(record.result)
      if (nestedResult) queue.push(nestedResult)
      continue
    }

    const array = asArray(current)
    if (array.length) {
      queue.push(...array)
    }
  }

  return {}
}

function nodeLabel(node: unknown): string {
  const n = asRecord(node)
  if (!n) return ''
  const keys = ['label', 'name', 'id', 'kg_id', 'concept_id', 'task_id', 'region_id']
  for (const key of keys) {
    const value = n[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function formatPathText(path: unknown): string {
  const p = asRecord(path)
  if (!p) return ''
  const labels = asArray(p.nodes).map(nodeLabel).filter(Boolean).slice(0, 6)
  if (labels.length >= 2) return labels.join(' -> ')
  if (labels.length === 1) return labels[0]
  const startNode = p.start_node_id
  const endNode = p.end_node_id
  if (typeof startNode === 'string' && typeof endNode === 'string') {
    return `${startNode} -> ${endNode}`
  }
  return ''
}

type KgPreview = {
  summaryText: string | null
  summaryStats: Record<string, any>
  topPaths: string[]
  warnings: string[]
  hasSubgraph: boolean
  expandArgs: Record<string, any>
}

function buildKgPreview(toolCall: any): KgPreview {
  const payload = extractKgPayload(toolCall)
  const outputs = asRecord(payload.outputs) || {}
  const resultPreview = asRecord(toolCall?.result_preview) || {}
  const args = extractToolArgs(toolCall)

  const previewStats = asRecord(resultPreview.summary_stats) || {}
  const payloadSummary = asRecord(payload.summary) || {}
  const outputSummary = asRecord(outputs.summary) || {}
  const summaryStats = Object.keys(payloadSummary).length
    ? payloadSummary
    : Object.keys(outputSummary).length
      ? outputSummary
      : previewStats

  let summaryText: string | null = null
  if (typeof resultPreview.summary === 'string' && resultPreview.summary.trim()) {
    summaryText = resultPreview.summary.trim()
  } else if (typeof payload.answer === 'string' && payload.answer.trim()) {
    summaryText = payload.answer.trim()
  } else if (typeof outputs.answer === 'string' && outputs.answer.trim()) {
    summaryText = outputs.answer.trim()
  }

  const previewPaths = asArray(resultPreview.top_paths)
    .map((value) => String(value))
    .filter(Boolean)
    .slice(0, 5)

  const payloadPaths = asArray(payload.paths).length
    ? asArray(payload.paths)
    : asArray(payload.top_paths).length
      ? asArray(payload.top_paths)
      : asArray(outputs.paths).length
        ? asArray(outputs.paths)
        : asArray(outputs.top_paths)

  const topPaths = previewPaths.length
    ? previewPaths
    : payloadPaths.map(formatPathText).filter(Boolean).slice(0, 5)

  const warnings = asArray(payload.warnings).length
    ? asArray(payload.warnings)
    : asArray(outputs.warnings).length
      ? asArray(outputs.warnings)
      : asArray(resultPreview.warnings)

  const warningTexts = warnings.map((value) => String(value)).filter(Boolean)

  const subgraph = asRecord(payload.subgraph) || asRecord(outputs.subgraph) || {}
  const hasSubgraph =
    Boolean(resultPreview.has_subgraph) ||
    asArray(subgraph.nodes).length > 0 ||
    asArray(subgraph.edges).length > 0

  const expandArgs: Record<string, any> = {
    ...(asRecord(resultPreview.expand_args) || {}),
    ...args,
    return_subgraph: true,
  }

  if (!expandArgs.question && typeof summaryStats.question === 'string') {
    expandArgs.question = summaryStats.question
  }
  if (!expandArgs.max_hops && typeof summaryStats.max_hops === 'number') {
    expandArgs.max_hops = summaryStats.max_hops
  }

  return {
    summaryText,
    summaryStats,
    topPaths,
    warnings: warningTexts,
    hasSubgraph,
    expandArgs,
  }
}

function safeStringify(value: unknown, maxChars = 1600): string {
  try {
    const serialized = JSON.stringify(value, null, 2)
    if (serialized.length <= maxChars) return serialized
    return `${serialized.slice(0, maxChars)}\n...`
  } catch {
    return String(value)
  }
}

function getRepairAttemptCount(message: Message): number {
  const repairContext = asRecord(message.metadata?.repair_context)
  const rawCount = repairContext?.repair_attempt_count
  return typeof rawCount === 'number' && Number.isFinite(rawCount) ? rawCount : 0
}

function KgMultihopCard({ toolCall }: { toolCall: any }) {
  const [isExpanding, setIsExpanding] = useState(false)
  const [expandError, setExpandError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, any> | null>(null)

  const preview = buildKgPreview(toolCall)
  const summaryStats = preview.summaryStats
  const pathCount =
    typeof summaryStats.n_paths === 'number'
      ? summaryStats.n_paths
      : preview.topPaths.length

  const expandEvidence = async () => {
    setIsExpanding(true)
    setExpandError(null)
    try {
      const res = await fetch('/api/tools/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          tool: 'kg_multihop_qa',
          arguments: preview.expandArgs,
          timeout_ms: 30000,
        }),
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || payload?.error || `HTTP ${res.status}`)
      }
      setExpanded(payload)
    } catch (error) {
      setExpandError(error instanceof Error ? error.message : 'Failed to expand evidence')
    } finally {
      setIsExpanding(false)
    }
  }

  const expandedPayload = extractKgPayload({ result: expanded })
  const expandedOutputs = asRecord(expandedPayload.outputs) || {}
  const expandedSubgraph =
    asRecord(expandedPayload.subgraph) || asRecord(expandedOutputs.subgraph) || {}
  const expandedWarnings = asArray(expandedPayload.warnings).length
    ? asArray(expandedPayload.warnings)
    : asArray(expandedOutputs.warnings)
  const expandedNodeCount = asArray(expandedSubgraph.nodes).length
  const expandedEdgeCount = asArray(expandedSubgraph.edges).length

  return (
    <div className="rounded-md border border-border bg-background/70 p-3 space-y-2">
      <div className="text-xs font-medium text-muted-foreground">Tool result: kg_multihop_qa</div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <div>Paths: {pathCount}</div>
        <div>Seed entities: {summaryStats.n_seed_entities ?? 'n/a'}</div>
        <div>Hops used: {summaryStats.hops_used ?? 'n/a'}</div>
        <div>Max hops: {summaryStats.max_hops ?? preview.expandArgs.max_hops ?? 'n/a'}</div>
      </div>

      {preview.summaryText ? (
        <div className="text-xs text-foreground">{preview.summaryText}</div>
      ) : null}

      <div>
        <div className="text-xs font-medium text-muted-foreground">Top paths</div>
        {preview.topPaths.length ? (
          <ol className="mt-1 list-decimal list-inside space-y-1 text-xs">
            {preview.topPaths.map((path, idx) => (
              <li key={`${idx}-${path}`} className="break-words">{path}</li>
            ))}
          </ol>
        ) : (
          <div className="mt-1 text-xs text-muted-foreground">No paths returned.</div>
        )}
      </div>

      {preview.warnings.length ? (
        <div>
          <div className="text-xs font-medium text-amber-700">Warnings</div>
          <ul className="mt-1 list-disc list-inside space-y-1 text-xs text-amber-700">
            {preview.warnings.map((warning, idx) => (
              <li key={`${idx}-${warning}`}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="pt-1">
        <Button
          variant="outline"
          size="sm"
          className="h-7 px-2 text-xs"
          disabled={isExpanding}
          onClick={expandEvidence}
        >
          {isExpanding ? 'Expanding...' : 'Expand evidence'}
        </Button>
      </div>

      {expandError ? (
        <div className="text-xs text-destructive">{expandError}</div>
      ) : null}

      {expanded ? (
        <div className="rounded border border-border bg-muted/30 p-2 space-y-1">
          <div className="text-xs font-medium text-muted-foreground">Expanded subgraph</div>
          <div className="text-xs text-muted-foreground">
            Nodes: {expandedNodeCount} | Edges: {expandedEdgeCount}
          </div>
          <pre className="max-h-56 overflow-x-auto text-[11px] leading-relaxed">
            {safeStringify({
              summary: asRecord(expandedPayload.summary) || asRecord(expandedOutputs.summary) || {},
              subgraph: expandedSubgraph,
              warnings: expandedWarnings,
            })}
          </pre>
        </div>
      ) : null}
    </div>
  )
}

function MessageItem({ message, previousUserMessage, onCancelExecution, onResumeFromCheckpoint, onAskAgent, onReplacePlan, onApplyRepair, onRevalidateRepair, onHandOffRepair }: {
  message: Message
  previousUserMessage?: string | null
  onCancelExecution?: (jobId: string) => void 
  onResumeFromCheckpoint?: (checkpointId: string) => void
  onAskAgent?: (prompt: string) => void
  onReplacePlan?: (pipelineId: string) => void
  onApplyRepair?: (proposal: RepairProposal) => void
  onRevalidateRepair?: (proposal: RepairProposal) => void
  onHandOffRepair?: (proposal: RepairProposal) => void
}) {
  const isUser = message.type === 'user'
  const suggestedPipelineId = !isUser ? findSuggestedPipelineId(message) : null
  const suggestedPipeline = suggestedPipelineId ? PIPELINE_BY_ID.get(suggestedPipelineId) : null
  const suggestedToolLabel = !isUser ? findSuggestedToolLabel(message) : null
  const toolCalls = !isUser ? getToolCallsFromMessage(message) : []
  const kgMultihopCalls = !isUser ? toolCalls.filter(isKgMultihopToolCall) : []
  const repairProposal =
    !isUser && message.metadata?.repair_request
      ? extractRepairProposal(message.content)
      : null
  const repairAttemptCount = repairProposal ? getRepairAttemptCount(message) : 0
  const renderedContent = repairProposal
    ? (stripFirstJsonFence(message.content) || 'Structured repair proposal ready.')
    : message.content
  const suggestedToolHref = (() => {
    if (!suggestedToolLabel) return null
    const q = encodeURIComponent(suggestedToolLabel)
    return `/library/tools?q=${q}&tool=${q}`
  })()

  const errorPlan = !isUser && message.error ? planForError(message.metadata?.error_code) : null
  const showInlineErrorCard =
    !isUser &&
    Boolean(message.error) &&
    (message.metadata?.render === 'inline' || errorPlan?.kind === 'inline')

  return (
    <div className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
        isUser 
          ? 'bg-primary text-primary-foreground' 
          : 'bg-muted text-muted-foreground'
      }`}>
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div className={`flex-1 space-y-3 ${isUser ? 'text-right' : ''}`}>
        <div
          data-testid={isUser ? 'chat-message-user' : 'chat-message-assistant'}
          className={`inline-block max-w-[80%] p-3 rounded-lg ${
          isUser 
            ? 'bg-primary text-primary-foreground ml-auto' 
            : 'bg-muted'
        }`}
        >
          <div className="text-sm prose prose-slate dark:prose-invert max-w-none">
            <Markdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeSanitize]}
            >
              {renderedContent}
            </Markdown>
          </div>
          <div className="text-xs opacity-70 mt-1">
            {message.timestamp.toLocaleTimeString()}
          </div>
        </div>

        {message.executionBlock && (
          <div className={isUser ? 'text-left' : ''}>
            <ExecutionBlock 
              executionBlock={message.executionBlock}
              onCancel={onCancelExecution}
            />
          </div>
        )}

        {!isUser && suggestedPipeline ? (
          <div className={isUser ? 'text-left' : ''}>
            <PlanCard
              title={suggestedPipeline.title}
              description={suggestedPipeline.description}
              estRuntime={suggestedPipeline.estRuntime}
              onReplacePlan={
                onReplacePlan ? () => onReplacePlan(suggestedPipeline.pipelineId) : undefined
              }
              onAskAgent={
                onAskAgent
                  ? () =>
                      onAskAgent(
                        `I want to use the "${suggestedPipeline.title}" plan. How should I configure it and where does it fit in my analysis?`,
                      )
                  : undefined
              }
            />
          </div>
        ) : null}

        {!isUser && suggestedToolHref ? (
          <div className={isUser ? 'text-left' : ''}>
            <Button variant="outline" size="sm" asChild>
              <Link href={suggestedToolHref}>
                View tool details
              </Link>
            </Button>
          </div>
        ) : null}

        {!isUser && kgMultihopCalls.length ? (
          <div className={isUser ? 'text-left' : ''}>
            <div className="space-y-2">
              {kgMultihopCalls.map((toolCall, idx) => (
                <KgMultihopCard key={`kg-multihop-${idx}`} toolCall={toolCall} />
              ))}
            </div>
          </div>
        ) : null}

        {!isUser && repairProposal ? (
          <div className={isUser ? 'text-left' : ''}>
            <RepairCard
              proposal={repairProposal}
              attemptCount={repairAttemptCount}
              onApplyFix={onApplyRepair}
              onRevalidate={onRevalidateRepair}
              onHandOffToIde={onHandOffRepair}
            />
          </div>
        ) : null}

        {showInlineErrorCard ? (
          <div className={isUser ? 'text-left' : ''}>
            <DiagnosisCard
              title="Diagnosis"
              message={message.error || undefined}
              onRetry={
                onAskAgent && previousUserMessage
                  ? () => onAskAgent(previousUserMessage)
                  : undefined
              }
              onAskAgent={
                onAskAgent
                  ? () =>
                      onAskAgent(
                        `I hit this error:\n\n${message.error}\n\nPlease diagnose the cause and suggest the next step.`,
                      )
                  : undefined
              }
            />
          </div>
        ) : null}

        {!isUser && Array.isArray(message.metadata?.coding_events) && message.metadata?.coding_events.length > 0 && (
          <div className="bg-muted/60 border border-muted-foreground/20 rounded-md p-3 text-xs space-y-2">
            <div className="font-medium text-muted-foreground">Coding progress</div>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {message.metadata.coding_events.map((evt: any, idx: number) => (
                <div key={idx} className="flex gap-2">
                  <span className="uppercase tracking-wide text-[10px] font-semibold text-primary">
                    {String(evt?.type || 'event')}
                  </span>
                  <span className="text-muted-foreground/90 break-all">
                    {formatCodingEventPreview(evt)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {!isUser && message.lastCheckpointId && (
          <div className="flex gap-2 items-center text-xs text-muted-foreground">
            <span>Checkpoint: {message.lastCheckpointId}</span>
            {onResumeFromCheckpoint && (
              <button
                type="button"
                className="underline hover:text-primary"
                onClick={() => onResumeFromCheckpoint(message.lastCheckpointId!)}
                data-testid="resume-from-checkpoint"
              >
                Resume
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export function MessageList({
  messages,
  onCancelExecution,
  onResumeFromCheckpoint,
  onAskAgent,
  onReplacePlan,
  onApplyRepair,
  onRevalidateRepair,
  onHandOffRepair,
}: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = messagesEndRef.current
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-8">
        <div className="max-w-md space-y-4">
          <Bot className="h-12 w-12 mx-auto text-muted-foreground" />
          <div>
            <h3 className="font-semibold text-lg mb-2">Ready to analyze</h3>
            <p className="text-muted-foreground">
              Ask me anything about neuroimaging. I can run analyses, visualize data, 
              and help you explore datasets.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-6">
      {(() => {
        let lastUserMessage: string | null = null
        return messages.map((message) => {
          const previousUserMessage = lastUserMessage
          if (message.type === 'user') {
            lastUserMessage = message.content
          }
          return (
            <MessageItem
              key={message.id}
              message={message}
              previousUserMessage={previousUserMessage}
              onCancelExecution={onCancelExecution}
              onResumeFromCheckpoint={onResumeFromCheckpoint}
              onAskAgent={onAskAgent}
              onReplacePlan={onReplacePlan}
              onApplyRepair={onApplyRepair}
              onRevalidateRepair={onRevalidateRepair}
              onHandOffRepair={onHandOffRepair}
            />
          )
        })
      })()}
      <div ref={messagesEndRef} />
    </div>
  )
}
