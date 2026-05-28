'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import { buildLatestPlanContinuationPrompt } from '@/lib/mcp-plan-handoff'
import { buildMcpRecipeCallText } from '@/lib/mcp-recipe-handoff'
import {
  buildHostedMcpSnippet,
  DEFAULT_MCP_CLOUD_URL,
  type HostedMcpClient,
} from '@/lib/mcp-config-snippets'

export type HandoffTemplatePayload = {
  kind: 'template'
  workflowId: string
  workflowLabel?: string | null
  datasetId?: string | null
  datasetVersion?: string | null
  targetRuntime?: string | null
  supportedTargets?: string[] | null
  params?: Record<string, unknown> | null
  unresolvedInputs?: string[]
  notes?: string[]
  promptOverride?: string | null
  title?: string | null
}

export type HandoffRunHandlePayload = {
  kind: 'run-handle'
  runId: string
  workflowId?: string | null
  workflowLabel?: string | null
  datasetId?: string | null
  title?: string | null
}

export type HandoffPayload = HandoffTemplatePayload | HandoffRunHandlePayload

export type HandoffModalProps = {
  open: boolean
  onClose: () => void
  mode: 'template' | 'run-handle'
  payload: HandoffPayload
}

type RunStatus = 'running' | 'completed' | 'failed' | 'unknown'

type ClientId = 'claude-code' | 'cursor' | 'codex' | 'manual'

type ClientButton = {
  id: ClientId
  label: string
  toastLabel: string
}

const CLIENT_BUTTONS: ClientButton[] = [
  { id: 'claude-code', label: 'Claude Code', toastLabel: 'Claude Code' },
  { id: 'cursor', label: 'Cursor', toastLabel: 'Cursor' },
  { id: 'codex', label: 'Codex', toastLabel: 'Codex' },
  { id: 'manual', label: 'Copy Manual', toastLabel: 'Manual' },
]

function buildTemplateExtras(payload: HandoffTemplatePayload): string {
  const notes = (payload.notes || []).map((note) => note.trim()).filter(Boolean)
  const unresolved = (payload.unresolvedInputs || []).filter((key) => key && key.trim())
  const blocks: string[] = []

  if (notes.length) {
    blocks.push(`Studio context:\n${notes.map((note) => `- ${note}`).join('\n')}`)
  }

  if (unresolved.length) {
    const placeholderLines = unresolved.map((key) => `- ${key}: <${key}>`)
    blocks.push(`Inputs to resolve before execution:\n${placeholderLines.join('\n')}`)
  }

  return blocks.join('\n\n')
}

function appendTemplateExtras(base: string, payload: HandoffTemplatePayload): string {
  const extras = buildTemplateExtras(payload)
  return extras ? `${base}\n\n${extras}` : base
}

function buildTemplatePrompt(payload: HandoffTemplatePayload): string {
  if (payload.promptOverride && payload.promptOverride.trim()) {
    const override = payload.promptOverride.trim()
    const hasDatasetContext =
      Boolean(payload.datasetId?.trim()) ||
      typeof payload.params?.dataset_id === 'string'
    if (!hasDatasetContext || override.includes('dataset_id')) {
      return appendTemplateExtras(override, payload)
    }
    const recipeCall = buildMcpRecipeCallText({
      workflowId: payload.workflowId,
      targetRuntime: payload.targetRuntime,
      supportedTargets: payload.supportedTargets,
      datasetId: payload.datasetId,
      params: payload.params ?? {},
    })
    const baseWithRecipe = [
      override,
      payload.datasetId ? `Dataset context: ${payload.datasetId}` : '',
      recipeCall ? `Preferred MCP recipe call:\n${recipeCall}` : '',
    ]
      .filter(Boolean)
      .join('\n\n')
    return appendTemplateExtras(baseWithRecipe, payload)
  }
  const base = buildLatestPlanContinuationPrompt({
    workflowId: payload.workflowId,
    workflowLabel: payload.workflowLabel || payload.workflowId,
    datasetId: payload.datasetId,
    datasetVersion: payload.datasetVersion,
    handoffPack: null,
  })
  return appendTemplateExtras(base, payload)
}

function buildRunHandlePrompt(payload: HandoffRunHandlePayload): string {
  const lines = [
    `Continue Brain Researcher run ${payload.runId}.`,
    `Call br.attach_run('${payload.runId}') in your notebook, then list artifacts via br.list_artifacts(run_id='${payload.runId}').`,
  ]
  const contextParts: string[] = []
  if (payload.workflowLabel || payload.workflowId) {
    contextParts.push(`workflow "${payload.workflowLabel || payload.workflowId}"`)
  }
  if (payload.datasetId) contextParts.push(`dataset "${payload.datasetId}"`)
  if (contextParts.length) lines.push(`Context: ${contextParts.join(', ')}.`)
  return lines.join(' ')
}

function buildPromptBody(payload: HandoffPayload): string {
  return payload.kind === 'template'
    ? buildTemplatePrompt(payload)
    : buildRunHandlePrompt(payload)
}

function buildRecipeBody(payload: HandoffPayload): string {
  if (payload.kind === 'run-handle') {
    return `br.attach_run("${payload.runId}")`
  }
  const callText = buildMcpRecipeCallText({
    workflowId: payload.workflowId,
    targetRuntime: payload.targetRuntime,
    supportedTargets: payload.supportedTargets,
    datasetId: payload.datasetId,
    params: payload.params ?? {},
  })
  return callText || `get_execution_recipe(tool_id="${payload.workflowId}")`
}

function buildClipboardForClient(client: ClientId, prompt: string, recipe: string): string {
  switch (client) {
    case 'claude-code':
      return `Use Brain Researcher MCP (mcp__brain-researcher__*) to run this handoff.\n\n${prompt}\n\nSuggested MCP call:\n${recipe}`
    case 'cursor':
      return `@brain-researcher\n\n${prompt}\n\nSuggested MCP call:\n${recipe}`
    case 'codex':
      return `# Codex MCP handoff (mcp_servers.brain-researcher)\n\n${prompt}\n\nSuggested MCP call:\n${recipe}`
    case 'manual':
      return `${prompt}\n\n${recipe}`
  }
}

export function HandoffModal({ open, onClose, mode, payload }: HandoffModalProps) {
  const { toast } = useToast()
  const [serverConfigTab, setServerConfigTab] = useState<HostedMcpClient>('cursor')
  const [runStatus, setRunStatus] = useState<RunStatus>('unknown')

  const promptBody = useMemo(() => buildPromptBody(payload), [payload])
  const recipeBody = useMemo(() => buildRecipeBody(payload), [payload])
  const serverSnippet = useMemo(
    () => buildHostedMcpSnippet(serverConfigTab, { url: DEFAULT_MCP_CLOUD_URL }),
    [serverConfigTab],
  )

  useEffect(() => {
    if (!open || mode !== 'run-handle' || payload.kind !== 'run-handle') return
    let cancelled = false
    const runId = payload.runId

    const fetchStatus = async () => {
      try {
        // TODO(handoff-modal): replace once /api/runs/:id status route lands
        const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { cache: 'no-store' })
        if (!response.ok) {
          if (!cancelled) setRunStatus('unknown')
          return
        }
        const data = await response.json()
        const raw = typeof data?.status === 'string' ? data.status.toLowerCase() : ''
        let next: RunStatus = 'unknown'
        if (raw === 'completed' || raw === 'success' || raw === 'succeeded') next = 'completed'
        else if (raw === 'failed' || raw === 'error') next = 'failed'
        else if (raw === 'running' || raw === 'pending' || raw === 'queued' || raw === 'in_progress') next = 'running'
        if (!cancelled) setRunStatus(next)
      } catch {
        if (!cancelled) setRunStatus('unknown')
      }
    }

    fetchStatus()
    const interval = window.setInterval(fetchStatus, 15000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [open, mode, payload])

  const handleCopyForClient = useCallback(
    async (client: ClientButton) => {
      const text = buildClipboardForClient(client.id, promptBody, recipeBody)
      try {
        await navigator.clipboard.writeText(text)
        toast({ title: `Copied to clipboard for ${client.toastLabel}` })
      } catch {
        toast({ title: `Failed to copy for ${client.toastLabel}`, variant: 'destructive' })
      }
    },
    [promptBody, recipeBody, toast],
  )

  const handleCopyRaw = useCallback(
    async (label: string, value: string) => {
      try {
        await navigator.clipboard.writeText(value)
        toast({ title: `${label} copied` })
      } catch {
        toast({ title: `Failed to copy ${label}`, variant: 'destructive' })
      }
    },
    [toast],
  )

  const handleOpenChange = (next: boolean) => {
    if (!next) onClose()
  }

  const title = payload.title || (payload.kind === 'run-handle' ? 'Hand off run' : 'Hand off workflow')
  const isRunHandle = mode === 'run-handle' && payload.kind === 'run-handle'

  const statusBadge = (() => {
    if (!isRunHandle) {
      return (
        <Badge variant="outline" className="text-xs">
          Template
        </Badge>
      )
    }
    const map: Record<RunStatus, { label: string; className: string }> = {
      running: { label: 'Running…', className: 'bg-blue-100 text-blue-800' },
      completed: { label: 'Completed', className: 'bg-green-100 text-green-800' },
      failed: { label: 'Failed', className: 'bg-red-100 text-red-800' },
      unknown: { label: 'Unknown', className: 'bg-slate-100 text-slate-700' },
    }
    const entry = map[runStatus]
    return <Badge className={cn('text-xs', entry.className)}>{entry.label}</Badge>
  })()

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-center justify-between gap-3">
            <DialogTitle>{title}</DialogTitle>
            {statusBadge}
          </div>
          <DialogDescription>
            Copy a ready-made handoff payload to your coding agent. The agent calls Brain Researcher MCP from there.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap gap-2">
          {CLIENT_BUTTONS.map((client) => (
            <Button
              key={client.id}
              size="sm"
              variant={client.id === 'manual' ? 'outline' : 'secondary'}
              onClick={() => void handleCopyForClient(client)}
            >
              <Copy className="mr-2 h-3 w-3" />
              {client.label}
            </Button>
          ))}
        </div>

        <Tabs defaultValue="prompt" className="w-full">
          <TabsList>
            <TabsTrigger value="prompt">Prompt</TabsTrigger>
            <TabsTrigger value="recipe">MCP Call</TabsTrigger>
            <TabsTrigger value="server">MCP Server Config</TabsTrigger>
          </TabsList>

          <TabsContent value="prompt">
            <div className="rounded-md border bg-slate-950 text-slate-50 p-4">
              <div className="flex items-center justify-end pb-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void handleCopyRaw('Prompt', promptBody)}
                >
                  <Copy className="mr-2 h-3 w-3" />
                  Copy prompt
                </Button>
              </div>
              <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
                {promptBody}
              </pre>
            </div>
          </TabsContent>

          <TabsContent value="recipe">
            <div className="rounded-md border bg-slate-950 text-slate-50 p-4">
              <div className="flex items-center justify-end pb-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void handleCopyRaw('MCP call', recipeBody)}
                >
                  <Copy className="mr-2 h-3 w-3" />
                  Copy MCP call
                </Button>
              </div>
              <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
                {recipeBody}
              </pre>
            </div>
          </TabsContent>

          <TabsContent value="server">
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {(['cursor', 'codex', 'claude'] as HostedMcpClient[]).map((client) => (
                  <Button
                    key={client}
                    size="sm"
                    variant={serverConfigTab === client ? 'default' : 'outline'}
                    onClick={() => setServerConfigTab(client)}
                  >
                    {client === 'cursor' ? 'Cursor' : client === 'codex' ? 'Codex' : 'Claude Code'}
                  </Button>
                ))}
              </div>
              <div className="rounded-md border bg-slate-950 text-slate-50 p-4">
                <div className="flex items-center justify-between gap-3 pb-2">
                  <div className="text-xs text-slate-400">{serverSnippet.fileName}</div>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void handleCopyRaw(serverSnippet.copyLabel, serverSnippet.snippet)}
                  >
                    <Copy className="mr-2 h-3 w-3" />
                    {serverSnippet.copyButtonLabel}
                  </Button>
                </div>
                <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
                  {serverSnippet.snippet}
                </pre>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <div className="border-t pt-3 text-xs text-muted-foreground">
          Need to connect a client first?{' '}
          <Link href="/mcp/setup" className="underline underline-offset-4 hover:text-foreground">
            Go to /mcp/setup
          </Link>
        </div>
      </DialogContent>
    </Dialog>
  )
}
