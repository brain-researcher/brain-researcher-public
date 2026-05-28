'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { Message, ExecutionBlock, FileAttachment } from '@/types/chat'
import { apiClient, submitRun, cancelJob, getJob, createWebSocket } from '@/lib/api'
import {
  buildCheckpointMessagePatch,
  withResumeCheckpointInContext,
} from '@/lib/chat-checkpoints'
import {
  DEFAULT_CODING_STREAM_PLACEHOLDER,
  getNextCodingStreamContent,
} from '@/lib/coding-stream'
import { buildAuthLoginHref } from '@/lib/auth/login-redirect'
import { serviceEndpoints } from '@/lib/service-endpoints'
import { useToast } from '@/hooks/use-toast'
import { extractErrorCode, planForError } from '@/lib/errors'
import { buildRepairMessageMetadata } from '@/lib/chat-repair'

type ChatMode = 'simple' | 'analysis'

type SubmitOptions = {
  pipeline?: string
  datasetId?: string
  datasetVersion?: string
  datasetResourceSummary?: {
    selectedVersion: string | null
    readinessStatus: string | null
    bucketCheckState: string | null
    versionCheckMode: string | null
    resolvedVersion: string | null
    subjectsCount: number | null
    totalMatchedFiles: number | null
    s3Uri: string | null
    openneuroUrl: string | null
    sourceRepoUrl: string | null
  }
  parameters?: Record<string, any>
  mode?: ChatMode
  systemPrompt?: string
  scenarioId?: string
  resumeCheckpointId?: string | null
  codingMode?: boolean
  /** Optional tool payload for /api/chat (e.g., {mode: 'coding'}) */
  tools?: Record<string, any>
  /** Optional ctx payload for /api/chat (repo_root, file_paths, preview, etc.) */
  ctx?: Record<string, any>
  /** Convenience: repo root for coding agent */
  repoRoot?: string
  /** Convenience: file paths for coding agent */
  filePaths?: string[]
  /** Force code agent even without repo_root */
  forceCodeAgent?: boolean
  /** Request explain-only (LLM) path */
  explainOnly?: boolean
  /** Optional fixed thread id (for tests) */
  threadId?: string
}

// Connection state for SSE streaming
export type ConnectionState = 'idle' | 'connected' | 'reconnecting' | 'failed'

function normalizeThreadId(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized.length > 0 ? normalized : undefined
}

function extractThreadIdFromPayload(payload: any): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined

  return (
    normalizeThreadId(payload?.thread_id) ||
    normalizeThreadId(payload?.threadId) ||
    normalizeThreadId(payload?.session_id) ||
    normalizeThreadId(payload?.sessionId) ||
    normalizeThreadId(payload?.message?.thread_id) ||
    normalizeThreadId(payload?.message?.threadId) ||
    normalizeThreadId(payload?.message?.session_id) ||
    normalizeThreadId(payload?.message?.sessionId) ||
    normalizeThreadId(payload?.metadata?.thread_id) ||
    normalizeThreadId(payload?.metadata?.threadId) ||
    normalizeThreadId(payload?.ctx?.thread_id) ||
    normalizeThreadId(payload?.ctx?.threadId) ||
    normalizeThreadId(payload?.runCard?.thread_id) ||
    normalizeThreadId(payload?.runCard?.threadId) ||
    normalizeThreadId(payload?.runCard?.metadata?.thread_id) ||
    normalizeThreadId(payload?.runCard?.metadata?.threadId)
  )
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const messagesRef = useRef<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [codingMode, setCodingMode] = useState(true)
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle')
  const [threadId, setThreadId] = useState<string | undefined>(undefined)
  const threadIdRef = useRef<string | undefined>(undefined)
  const isSubmittingRef = useRef(false)
  const { toast } = useToast()

  const setActiveThreadId = useCallback((nextThreadId: unknown): string | undefined => {
    const normalized = normalizeThreadId(nextThreadId)
    if (!normalized) return undefined
    if (threadIdRef.current === normalized) return normalized
    threadIdRef.current = normalized
    setThreadId(normalized)
    return normalized
  }, [])

  const parseApiError = useCallback(async (res: Response) => {
    const status = res.status
    let body: any = null
    try {
      body = await res.clone().json()
    } catch {
      // ignore
    }
    const code = extractErrorCode(body)
    const detail = typeof body === 'string' ? body : body?.detail || body?.error || res.statusText
    return { status, code, detail }
  }, [])

  const addMessage = useCallback((message: Omit<Message, 'id' | 'timestamp'>) => {
    // Use crypto.randomUUID for client-generated messages (SSR-safe since this is 'use client')
    // Server-provided messages should have server-generated stable IDs
    const newMessage: Message = {
      ...message,
      id: `pending_${crypto.randomUUID()}`,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, newMessage])
    return newMessage.id
  }, [])

  const updateMessage = useCallback((messageId: string, updates: Partial<Message>) => {
    setMessages(prev => prev.map(msg => 
      msg.id === messageId ? { ...msg, ...updates } : msg
    ))
  }, [])

  const pollJobStatus = useCallback(async (jobId: string, messageId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const jobResult = await getJob(jobId)
        
        updateMessage(messageId, {
          executionBlock: jobResult
        })
        
        if (jobResult.status === 'completed') {
          updateMessage(messageId, {
            content: 'Analysis completed! Here are your results:'
          })
          clearInterval(pollInterval)
        } else if (jobResult.status === 'failed') {
          updateMessage(messageId, {
            content: 'Sorry, there was an error processing your request.'
          })
          clearInterval(pollInterval)
          
          toast({
            title: "Execution Failed",
            description: "There was an error running your analysis. Please try again.",
            variant: "destructive"
          })
        }
      } catch (error) {
        console.error('Polling error:', error)
        clearInterval(pollInterval)
      }
    }, 2000) // Poll every 2 seconds
    
    // Clean up after 5 minutes
    setTimeout(() => clearInterval(pollInterval), 5 * 60 * 1000)
  }, [updateMessage, toast])

  const submitPrompt = useCallback(async (prompt: string, attachments?: FileAttachment[], options?: SubmitOptions) => {
    if (!prompt.trim()) return

    if (isSubmittingRef.current) {
      return
    }

    isSubmittingRef.current = true
    setIsLoading(true)
    
    // Add user message
    const userMessageId = addMessage({
      type: 'user',
      content: prompt,
      attachments: attachments || [],
      resumeCheckpointId: options?.resumeCheckpointId || undefined,
    })

    try {
      const promptWithSystem = options?.systemPrompt
        ? `System instruction:\n${options.systemPrompt}\n\nUser request:\n${prompt}`
        : prompt

      // Determine mode: simple uses /api/chat, analysis uses /run
      const mode = options?.mode || 'analysis'
      const effectiveCodingMode = options?.codingMode ?? codingMode
      const defaultRepoRoot = process.env.NEXT_PUBLIC_REPO_ROOT || undefined

      const buildChatPayload = (overrides?: Record<string, any>) => {
        const params = options?.parameters

        // Base payload follows new /api/chat contract (messages array), but keeps legacy fields for compatibility
        const resolvedThreadId =
          normalizeThreadId(overrides?.thread_id) ||
          normalizeThreadId(overrides?.threadId) ||
          normalizeThreadId(options?.threadId) ||
          normalizeThreadId(options?.ctx?.thread_id) ||
          threadIdRef.current ||
          crypto.randomUUID()
        setActiveThreadId(resolvedThreadId)
        const payload: any = {
          messages: [
            {
              role: 'user',
              content: promptWithSystem,
            },
          ],
          message: promptWithSystem, // legacy
          scenario_id: options?.scenarioId,
          codingMode: effectiveCodingMode,
          thread_id: resolvedThreadId,
          session_id: resolvedThreadId,
        }
        if (options?.datasetId) payload.dataset_id = options.datasetId
        if (options?.datasetVersion) payload.dataset_version = options.datasetVersion
        if (options?.pipeline) payload.pipeline_id = options.pipeline

        // Tools
        if (options?.tools) {
          payload.tools = options.tools
        } else if (effectiveCodingMode) {
          payload.tools = { mode: 'coding' }
        }

        // Ctx
        let ctx: Record<string, any> = options?.ctx ? { ...options.ctx } : {}
        if (options?.repoRoot || defaultRepoRoot) {
          ctx.repo_root = ctx.repo_root || options?.repoRoot || defaultRepoRoot
        }
        if (options?.filePaths?.length) {
          ctx.file_paths = ctx.file_paths || options.filePaths
        }
        if (options?.forceCodeAgent) {
          ctx.force_code_agent = true
        }
        if (options?.explainOnly) {
          ctx.explain_only = true
        }
        const planContext: Record<string, any> = {}
        if (options?.datasetId) planContext.dataset_id = options.datasetId
        if (options?.datasetVersion) planContext.dataset_version = options.datasetVersion
        if (options?.pipeline) planContext.pipeline_id = options.pipeline
        if (options?.datasetResourceSummary) {
          planContext.dataset_resource_summary = options.datasetResourceSummary
        }
        if (params && Object.keys(params).length > 0) {
          planContext.parameters = params
        }
        if (Object.keys(planContext).length > 0) {
          ctx.plan_context = {
            ...(ctx.plan_context && typeof ctx.plan_context === 'object' ? ctx.plan_context : {}),
            ...planContext,
          }
        }
        if (effectiveCodingMode) {
          // Sensible safe defaults for coding
          ctx.apply = ctx.apply ?? false
          ctx.dry_run = ctx.dry_run ?? true
          ctx.preview = ctx.preview ?? true
        }
        const nextCtx = withResumeCheckpointInContext(ctx, options?.resumeCheckpointId)
        if (nextCtx && Object.keys(nextCtx).length > 0) {
          payload.ctx = nextCtx
        }

        if (params && Object.keys(params).length > 0) {
          payload.parameters = params
          payload.inputs = { ...(payload.inputs || {}), ...params }
          const existingMeta = (payload.metadata as Record<string, any> | undefined) || {}
          payload.metadata = { ...existingMeta, parameters: params }
        }

        return { ...payload, ...(overrides || {}) }
      }

      const buildRepairMetadata = (ctx?: Record<string, any>) =>
        buildRepairMessageMetadata(ctx?.repair_context)

      // Streaming helper for coding mode
      const streamCodingChat = async (payload: any) => {
        const repairMetadata = buildRepairMetadata(payload?.ctx)
        const assistantId = addMessage({
          type: 'assistant',
          content: DEFAULT_CODING_STREAM_PLACEHOLDER,
          metadata: {
            status: 'running',
            mode: 'coding',
            ...(repairMetadata || {}),
          },
        })

        let queueFullRetried = false
        let forbiddenRetried = false
        let sseRestarted = false
        let streamedContent = ''

        const runStream = async (attemptPayload: any, attempt: number): Promise<void> => {
          // Track reconnection attempts
          if (attempt > 0) {
            setConnectionState('reconnecting')
          }
          setActiveThreadId(extractThreadIdFromPayload(attemptPayload))

          const res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(attemptPayload),
          })

          if (res.status === 401) {
            setConnectionState('failed')
            toast({
              title: 'Session expired',
              description: 'Please sign in again.',
              variant: 'destructive',
            })
            if (typeof window !== 'undefined') {
              const currentPath = window.location.pathname + window.location.search
              window.location.href = buildAuthLoginHref(currentPath)
            }
            return
          }
          if (res.status === 403 && !forbiddenRetried) {
            forbiddenRetried = true
            const newThreadPayload = buildChatPayload({ thread_id: crypto.randomUUID() })
            await runStream(newThreadPayload, attempt + 1)
            return
          }
          if ((res.status === 429 || res.status >= 500) && attempt === 0) {
            setConnectionState('reconnecting')
            updateMessage(assistantId, {
              content: 'Backend is busy. Switching to a fallback model and retrying…',
              metadata: { fallback_model: true },
            })
            await new Promise((r) => setTimeout(r, 1500))
            await runStream(attemptPayload, attempt + 1)
            return
          }

          if (!res.ok || !res.body) {
            setConnectionState('failed')
            updateMessage(assistantId, {
              content: 'Coding agent failed to start.',
              error: `HTTP ${res.status}`,
            })
            return
          }

          // Connected successfully
          setConnectionState('connected')

          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          const flushEvent = (raw: string) => {
            const lines = raw.split('\n').filter(Boolean)
            let event = 'message'
            const dataLines: string[] = []
            for (const line of lines) {
              if (line.startsWith('event:')) {
                event = line.slice(6).trim()
              } else if (line.startsWith('data:')) {
                dataLines.push(line.slice(5).trim())
              }
            }
            if (!dataLines.length) return
            const dataStr = dataLines.join('\n')
            let data: any = dataStr
            try { data = JSON.parse(dataStr) } catch { /* keep raw string */ }
            setActiveThreadId(extractThreadIdFromPayload(data) || extractThreadIdFromPayload(attemptPayload))

            // Simple handling by event type
            const current = messagesRef.current?.find(m => m.id === assistantId)
            const currentMeta = current?.metadata || {}
            const currentContent = streamedContent || current?.content || ''
            const events = Array.isArray(currentMeta.coding_events) ? currentMeta.coding_events.slice() : []

            const pushEvent = (etype: string, payload: any) => {
              events.push({
                type: etype,
                data: payload,
                timestamp: new Date().toISOString(),
              })
              updateMessage(assistantId, { metadata: { ...currentMeta, coding_events: events } })
            }

            if (event === 'plan' || event === 'patch' || event === 'test') {
              pushEvent(event, data)
              return
            }
            if (event === 'metadata') {
              const nextPatch = buildCheckpointMessagePatch({
                payload: data,
                metadata: {
                  ...currentMeta,
                  ...(data && typeof data === 'object' ? data : {}),
                  type: 'coding_tool',
                  coding_events: events,
                },
                fallbackCheckpointId: current?.lastCheckpointId,
              })
              updateMessage(assistantId, {
                ...nextPatch,
              })
              return
            }
            if (event === 'token' || event === 'result' || event === 'message') {
              const nextContent = getNextCodingStreamContent({
                event,
                data,
                previousContent: currentContent,
                placeholder: DEFAULT_CODING_STREAM_PLACEHOLDER,
              })
              if (nextContent) {
                streamedContent = nextContent
              }
              const nextPatch = buildCheckpointMessagePatch({
                payload: data,
                metadata: {
                  ...currentMeta,
                  ...(data?.metadata || {}),
                  type: 'coding_tool',
                  coding_events: events,
                },
                fallbackCheckpointId: current?.lastCheckpointId,
              })
              updateMessage(assistantId, {
                content: nextContent || currentContent || 'Coding task completed.',
                ...nextPatch,
              })
              if (event === 'result') {
                pushEvent(event, data)
              }
              return
            }
            if (event === 'done' || event === 'stream_end') {
              const nextContent = getNextCodingStreamContent({
                event,
                data,
                previousContent: currentContent,
                placeholder: DEFAULT_CODING_STREAM_PLACEHOLDER,
              })
              const nextPatch = buildCheckpointMessagePatch({
                payload: data,
                metadata: {
                  ...currentMeta,
                  ...(data?.metadata || {}),
                  type: 'coding_tool',
                  coding_events: events,
                },
                fallbackCheckpointId: current?.lastCheckpointId,
              })
              if (nextContent) {
                streamedContent = nextContent
                updateMessage(assistantId, {
                  content: nextContent,
                  ...nextPatch,
                })
              } else {
                updateMessage(assistantId, {
                  ...nextPatch,
                })
              }
              pushEvent(event, data)
              return
            }
            if (event === 'error') {
              const errMsg = typeof data === 'string' ? data : data?.error || 'Unknown error'
              pushEvent('error', data)
              if (errMsg === 'coding_event_queue_full' && !queueFullRetried) {
                queueFullRetried = true
                throw new Error('queue_full')
              }
              updateMessage(assistantId, {
                content: 'Coding agent error.',
                error: errMsg,
                metadata: {
                  ...currentMeta,
                  coding_events: events,
                },
              })
              return
            }
          }

          // Stream read loop
          const processStream = async () => {
            while (true) {
              const { done, value } = await reader.read()
              if (done) break
              buffer += decoder.decode(value, { stream: true })
              let idx: number
              while ((idx = buffer.indexOf('\n\n')) !== -1) {
                const chunk = buffer.slice(0, idx)
                buffer = buffer.slice(idx + 2)
                if (chunk.trim()) flushEvent(chunk)
              }
            }
            if (buffer.trim()) flushEvent(buffer)
          }

          try {
            await processStream()
            setConnectionState('idle')  // Stream completed successfully
          } catch (err) {
            if (err instanceof Error && err.message === 'queue_full') {
              // Retry with trimmed file list
              setConnectionState('reconnecting')
              const newCtx = { ...(attemptPayload.ctx || {}) }
              if (Array.isArray(newCtx.file_paths)) {
                newCtx.file_paths = newCtx.file_paths.slice(0, 5)
              }
              const retryPayload = { ...attemptPayload, ctx: newCtx }
              await runStream(retryPayload, attempt + 1)
              return
            }
            if (!sseRestarted && attempt === 0) {
              sseRestarted = true
              setConnectionState('reconnecting')
              await new Promise((r) => setTimeout(r, 1500))
              await runStream(attemptPayload, attempt + 1)
              return
            }
            setConnectionState('failed')
            updateMessage(assistantId, {
              content: 'Coding stream interrupted.',
              error: err instanceof Error ? err.message : 'Unknown error',
              metadata: {
                ...(messagesRef.current?.find(m => m.id === assistantId)?.metadata || {}),
              },
            })
          }
        }

        await runStream(payload, 0)
        setConnectionState('idle')  // Reset after stream completes
      }
      
      if (mode === 'simple') {
        // Simple mode: for coding use streaming path, otherwise normal chat
        const payload = buildChatPayload()
        if (effectiveCodingMode) {
          await streamCodingChat(payload)
        } else {
          const sendSimple = async (attemptPayload: any, attempt: number) => {
            try {
              setActiveThreadId(extractThreadIdFromPayload(attemptPayload))
              const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(attemptPayload)
              })

              if (response.status === 401) {
                toast({
                  title: 'Session expired',
                  description: 'Please sign in again.',
                  variant: 'destructive',
                })
                if (typeof window !== 'undefined') {
                  const currentPath = window.location.pathname + window.location.search
                  window.location.href = buildAuthLoginHref(currentPath)
                }
                return
              }
              if (response.status === 403 && attempt === 0) {
                const newPayload = buildChatPayload({ thread_id: crypto.randomUUID() })
                await sendSimple(newPayload, attempt + 1)
                return
              }
              if (!response.ok) {
                const parsed = await parseApiError(response)
                const plan = planForError(parsed.code)
                if ((response.status === 429 || response.status >= 500) && attempt === 0) {
                  await new Promise((r) => setTimeout(r, 800))
                  await sendSimple(attemptPayload, attempt + 1)
                  return
                }
                addMessage({
                  type: 'assistant',
                  content: 'Sorry, I encountered an error. Please try again.',
                  error: parsed.detail || `HTTP ${response.status}`,
                  metadata: { error_code: parsed.code, render: plan.kind },
                })
                return
              }

              const data = await response.json()
              setActiveThreadId(extractThreadIdFromPayload(data) || extractThreadIdFromPayload(attemptPayload))
              const baseContent = data.message?.content || data.content || data.text || 'No response'

              const toolCalls = data.tool_calls
                || data.runCard?.provenance?.tool_calls
                || data.runCard?.execution?.tool_calls
                || []

              // Surface first tool result/error inline so the user sees outcomes without opening run details
              let toolSuffix = ''
              if (Array.isArray(toolCalls) && toolCalls.length) {
                const first = toolCalls[0]
                const toolName = first.name || first.tool || 'tool'
                const isMultihop =
                  typeof toolName === 'string' && toolName.toLowerCase().includes('kg_multihop_qa')
                if (first.result) {
                  if (isMultihop) {
                    toolSuffix = '\n\nkg_multihop_qa result is available in the tool result card below.'
                  } else {
                    const serialized = JSON.stringify(first.result, null, 2)
                    toolSuffix = `\n\n${toolName} result:\n${serialized.slice(0, 1200)}`
                  }
                } else if (first.error) {
                  const errorCategory = first.error_category || first.errorCategory
                  const categoryLine = errorCategory ? `\nError category: ${errorCategory}` : ''
                  toolSuffix = `\n\n${toolName} error: ${first.error}${categoryLine}`
                }
              }

              const checkpointPatch = buildCheckpointMessagePatch({
                payload: data,
                metadata: {
                  ...(data?.metadata && typeof data.metadata === 'object' ? data.metadata : {}),
                  ...(toolCalls.length ? { tool_calls: toolCalls } : {}),
                  ...(buildRepairMetadata(attemptPayload?.ctx) || {}),
                },
              })
              addMessage({
                type: 'assistant',
                content: baseContent + toolSuffix,
                runCard: data.runCard,
                ...checkpointPatch,
              })
            } catch (error) {
              // If simple mode fails, show error
              addMessage({
                type: 'assistant',
                content: 'Sorry, I encountered an error. Please try again.',
                error: error instanceof Error ? error.message : 'Unknown error'
              })
            }
          }

          await sendSimple(buildChatPayload(), 0)
        }
      } else {
        // Analysis mode: job-based endpoint with progress tracking
        let response: { job_id: string }

        try {
          const mergedParameters = {
            ...(options?.parameters || {}),
            ...(options?.scenarioId ? { scenario_id: options.scenarioId } : {})
          }
          // Use real orchestrator API with copilot flag for chat pipeline
          response = await submitRun(promptWithSystem, {
            pipeline: options?.pipeline || 'chat',
            datasetId: options?.datasetId,
            parameters: Object.keys(mergedParameters).length ? mergedParameters : undefined,
            copilot: true,
            attachments: attachments || [],
            scenarioId: options?.scenarioId,
            checkpointId: options?.resumeCheckpointId || undefined,
          })
        } catch (runError) {
          // Fallback to simple chat if /run fails
          console.warn('Job endpoint failed, falling back to simple chat:', runError)
          
          try {
            const fallbackPayload = buildChatPayload()
            const fallbackResponse = await fetch('/api/chat', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(fallbackPayload)
            })
            
            if (!fallbackResponse.ok) throw new Error(`HTTP ${fallbackResponse.status}`)
            
            const data = await fallbackResponse.json()
            setActiveThreadId(extractThreadIdFromPayload(data) || extractThreadIdFromPayload(fallbackPayload))
            const content = data.message?.content || data.content || 'No response'
            const checkpointPatch = buildCheckpointMessagePatch({
              payload: data,
              metadata: data?.metadata,
            })
            
            addMessage({
              type: 'assistant',
              content: content,
              runCard: data.runCard,
              ...checkpointPatch,
            })
            return // Exit after successful fallback
          } catch (fallbackError) {
            throw fallbackError // Re-throw if fallback also fails
          }
        }
        
        // Add assistant message with execution block
        const assistantMessageId = addMessage({
          type: 'assistant',
          content: `I'll run that analysis for you. Processing: "${prompt}"`,
          executionBlock: {
            id: response.job_id,
            status: 'running',
            steps: [],
            artifacts: []
          }
        })

        ;(async () => {
          try {
            const quickPayload = buildChatPayload()
            const quickResponse = await fetch('/api/chat', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(quickPayload),
            })

            if (!quickResponse.ok) {
              return
            }

            const data = await quickResponse.json().catch(() => undefined)
            setActiveThreadId(extractThreadIdFromPayload(data) || extractThreadIdFromPayload(quickPayload))
            const quickContent = data?.message?.content || data?.content || data?.text

            if (typeof quickContent === 'string' && quickContent.trim().length > 0) {
              const toolCalls = data?.tool_calls
                || data?.runCard?.provenance?.tool_calls
                || data?.runCard?.execution?.tool_calls
                || []

              let toolSuffix = ''
              if (Array.isArray(toolCalls) && toolCalls.length) {
                const first = toolCalls[0]
                const toolName = first.name || first.tool || 'tool'
                const isMultihop =
                  typeof toolName === 'string' && toolName.toLowerCase().includes('kg_multihop_qa')
                if (first.result) {
                  if (isMultihop) {
                    toolSuffix = '\n\nkg_multihop_qa result is available in the tool result card below.'
                  } else {
                    const serialized = JSON.stringify(first.result, null, 2)
                    toolSuffix = `\n\n${toolName} result:\n${serialized.slice(0, 1200)}`
                  }
                } else if (first.error) {
                  const errorCategory = first.error_category || first.errorCategory
                  const categoryLine = errorCategory ? `\nError category: ${errorCategory}` : ''
                  toolSuffix = `\n\n${toolName} error: ${first.error}${categoryLine}`
                }
              }
              const currentMessage = messagesRef.current?.find(m => m.id === assistantMessageId)
              const checkpointPatch = buildCheckpointMessagePatch({
                payload: data,
                metadata: {
                  ...((currentMessage?.metadata as Record<string, any>) || {}),
                  ...((data?.metadata && typeof data.metadata === 'object') ? data.metadata : {}),
                },
                fallbackCheckpointId: currentMessage?.lastCheckpointId,
              })
              updateMessage(assistantMessageId, {
                content: quickContent + toolSuffix,
                ...checkpointPatch,
              })
            }
          } catch (error) {
            console.warn('Quick chat response failed', error)
          }
        })()

        // Use WebSocket for real-time updates
        try {
          const ws = createWebSocket(response.job_id)
          
          ws.onmessage = (event) => {
            const data = JSON.parse(event.data)
            
            if (data.type === 'update') {
              updateMessage(assistantMessageId, {
                executionBlock: {
                  id: response.job_id,
                  status: data.status,
                  steps: data.steps || [],
                  artifacts: data.artifacts || [],
                  progress: data.progress
                }
              })
            } else if (data.type === 'complete') {
              updateMessage(assistantMessageId, {
                content: 'Analysis completed! Here are your results:',
                executionBlock: data.result
              })
              ws.close()
            } else if (data.type === 'error') {
              updateMessage(assistantMessageId, {
                content: 'Sorry, there was an error processing your request.',
                executionBlock: {
                  id: response.job_id,
                  status: 'failed',
                  steps: data.steps || [],
                  artifacts: [],
                  error: data.error
                }
              })
              ws.close()
              
              toast({
                title: "Execution Failed",
                description: data.error || "There was an error running your analysis.",
                variant: "destructive"
              })
            }
          }
          
          ws.onerror = (error) => {
            console.error('WebSocket error:', error)
            // Fall back to polling if WebSocket fails
            pollJobStatus(response.job_id, assistantMessageId)
          }
          
          ws.onclose = () => {
            console.log('WebSocket connection closed')
          }
        } catch (wsError) {
          // Fall back to polling if WebSocket creation fails
          console.warn('WebSocket not available, falling back to polling')
          pollJobStatus(response.job_id, assistantMessageId)
        }
      }

    } catch (error) {
      console.error('Submit error:', error)
      toast({
        title: "Submission Failed",
        description: error instanceof Error ? error.message : "Failed to submit your request. Please try again.",
        variant: "destructive"
      })
    } finally {
      isSubmittingRef.current = false
      setIsLoading(false)
    }
  }, [addMessage, updateMessage, toast, pollJobStatus, codingMode, parseApiError, setActiveThreadId])

  // Polling fallback for when WebSocket is not available
  const cancelExecution = useCallback(async (jobId: string) => {
    try {
      await cancelJob(jobId)
      
      // Update message to show cancelled status
      setMessages(prev => prev.map(msg => {
        if (msg.executionBlock?.id === jobId) {
          return {
            ...msg,
            executionBlock: {
              ...msg.executionBlock,
              status: 'cancelled'
            }
          }
        }
        return msg
      }))
      
      toast({
        title: "Execution Cancelled",
        description: "The analysis has been cancelled."
      })
    } catch (error) {
      toast({
        title: "Cancellation Failed",
        description: "Failed to cancel the execution.",
        variant: "destructive"
      })
    }
  }, [toast])

  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])

  const replaceMessages = useCallback((nextMessages: Message[]) => {
    setMessages(Array.isArray(nextMessages) ? nextMessages : [])
  }, [])

  // keep mutable ref for streaming updates
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  // Reset connection state helper (useful for UI retry button)
  const resetConnectionState = useCallback(() => {
    setConnectionState('idle')
  }, [])

  return {
    messages,
    isLoading,
    submitPrompt,
    cancelExecution,
    clearMessages,
    replaceMessages,
    addMessage,
    updateMessage,
    pollJobStatus,
    codingMode,
    setCodingMode,
    threadId,
    connectionState,
    resetConnectionState,
  }
}
