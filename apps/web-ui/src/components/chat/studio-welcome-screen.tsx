'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'

import type { WorkflowSummary } from '@/lib/api/workflows'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { routes } from '@/config/routes'
import { StudioEntryContent } from '@/components/studio/studio-entry-content'
import { StudioEntryDiscoveryPanel } from '@/components/studio/studio-entry-discovery-panel'
import { StudioEntryFrame } from '@/components/studio/studio-entry-frame'
import { StudioEntryIdeCard } from '@/components/studio/studio-entry-ide-card'

type ToolOption = {
  name: string
  display_name?: string
}

type StudioWelcomeScreenProps = {
  onSubmitPrompt: (prompt: string) => void
  onPickPipeline: (pipelineId: string) => void
  onOpenMcpModal: () => void
}

export function StudioWelcomeScreen({
  onSubmitPrompt,
  onPickPipeline,
  onOpenMcpModal,
}: StudioWelcomeScreenProps) {
  const router = useRouter()
  const [prompt, setPrompt] = useState('')
  const [hydrated, setHydrated] = useState(false)
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [tools, setTools] = useState<ToolOption[]>([])
  const [workflowLoading, setWorkflowLoading] = useState(false)
  const [toolLoading, setToolLoading] = useState(false)
  const [workflowError, setWorkflowError] = useState<string | null>(null)
  const [toolError, setToolError] = useState<string | null>(null)

  useEffect(() => setHydrated(true), [])

  useEffect(() => {
    let cancelled = false
    setWorkflowLoading(true)
    setWorkflowError(null)
    brainResearcherAPI
      .fetchWorkflowCatalog({ limit: 50 })
      .then((data) => {
        if (cancelled) return
        setWorkflows(data.workflows ?? [])
        setWorkflowLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setWorkflowError(err instanceof Error ? err.message : String(err))
        setWorkflowLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setToolLoading(true)
    setToolError(null)
    fetch('/api/tools/search', { cache: 'no-store' })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => {
        if (cancelled) return
        const list = Array.isArray(data?.tools) ? (data.tools as ToolOption[]) : []
        setTools(list)
        setToolLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setToolError(typeof err === 'string' ? err : err instanceof Error ? err.message : 'Failed to load tools')
        setToolLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const workflowOptions = useMemo(() => {
    return workflows
      .slice()
      .sort((a, b) => a.id.localeCompare(b.id))
      .slice(0, 25)
  }, [workflows])

  const toolOptions = useMemo(() => {
    return tools
      .slice()
      .sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name))
      .slice(0, 25)
  }, [tools])

  const formatWorkflowTitle = (id: string) =>
    id
      .replace(/^workflow_/, '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())

  const workflowBrowseOptions = useMemo(
    () =>
      workflowOptions.map((workflow) => ({
        value: workflow.id,
        label: formatWorkflowTitle(workflow.id),
      })),
    [workflowOptions],
  )

  const toolBrowseOptions = useMemo(
    () =>
      toolOptions.map((tool) => ({
        value: tool.name,
        label: tool.display_name || tool.name,
      })),
    [toolOptions],
  )

  return (
    <StudioEntryFrame
      data-testid="studio-welcome-screen"
      hydrated={hydrated}
    >
      <StudioEntryContent
        promptValue={prompt}
        onPromptChange={setPrompt}
        onSubmitPrompt={() => {
          const trimmed = prompt.trim()
          if (!trimmed) return
          onSubmitPrompt(trimmed)
        }}
        promptSubmitDisabled={!prompt.trim()}
        promptSubmitLabel="Continue"
        promptSecondaryActionLabel="Use an example"
        onPromptSecondaryAction={() => setPrompt('Run resting-state connectivity on HCP data')}
        promptTextareaClassName="min-h-[clamp(260px,38vh,560px)] text-base"
        onPickPipeline={onPickPipeline}
        templateTestIdPrefix="studio-welcome-template"
      >
        <StudioEntryDiscoveryPanel
          workflowOptions={workflowBrowseOptions}
          toolOptions={toolBrowseOptions}
          workflowLoading={workflowLoading}
          toolLoading={toolLoading}
          workflowError={workflowError}
          toolError={toolError}
          onSelectWorkflow={(value) => router.push(`${routes.library}/${encodeURIComponent(value)}`)}
          onSelectTool={(value) => router.push(`${routes.tools}?tool=${encodeURIComponent(value)}`)}
          onBrowseWorkflows={() => router.push(routes.library)}
          onBrowseTools={() => router.push(routes.tools)}
        />

        <StudioEntryIdeCard onConnectIde={onOpenMcpModal} />
      </StudioEntryContent>
    </StudioEntryFrame>
  )
}
