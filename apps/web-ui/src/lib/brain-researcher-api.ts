/**
 * Brain Researcher API Integration
 * Connects to BR-KG, Agent, and NICLIP services
 */

import { Message } from '@/types/chat'
import { Dataset } from '@/types/dataset'
import {
  ExecutePipelinePayload,
  PipelineExecutionResponse
} from '@/types/pipeline'
import type {
  NotificationItem,
  NotificationListResponse,
  UserProfile
} from '@/types/user'
import { getSupabaseClient, isSupabaseEnabled } from '@/lib/supabase/client'
import {
  KGTool,
  KGToolFamily,
  KGPipelinesResponse,
  KGToolsResponse,
  AgentPlanResponse,
  PlanRequest
} from '@/types/kg-responses'
import type {
  WorkflowTemplateCreateResponse,
  WorkflowTemplateDetail,
  WorkflowTemplateListItem
} from '@/types/workflow-templates'
import type {
  WorkflowSummary,
  WorkflowDetail,
  WorkflowCatalogResponse,
  WorkflowFilters
} from '@/lib/api/workflows'
import {
  resolveKgApiUrl,
  resolveKgRootUrl,
  serviceEndpoints,
} from '@/lib/service-endpoints'

const AGENT_API = serviceEndpoints.agentBase
const NICLIP_API = process.env.NEXT_PUBLIC_NICLIP_API || ''
const ORCHESTRATOR_API = serviceEndpoints.orchestratorBase
const USE_API_PROXY = serviceEndpoints.useProxy

const NOTIFICATIONS_ENDPOINT_STATE_KEY = 'br_notifications_endpoint_state_v1'
const NOTIFICATIONS_ENDPOINT_STATE_TS_KEY = 'br_notifications_endpoint_state_ts_v1'
const NOTIFICATIONS_ENDPOINT_STATE_TTL_MS = 1000 * 60 * 60 * 12
type NotificationsEndpointStatus = 'unknown' | 'supported' | 'unsupported'
type ChatOptions = {
  copilot?: boolean
}

const COPILOT_CHAT_SYSTEM_PROMPT =
  'You are Brain Researcher Copilot. Provide concise, user-facing assistance only. Do not reveal internal reasoning, hidden deliberation, tool-selection rationale, or planning traces. Never use phrases like "the user said" or "I should".'

// Obtain an access token in both browser (client) and server (SSR/route handler) contexts.
export async function getAccessTokenAnyContext(): Promise<string | null> {
  // Client-side: pull from NextAuth session
  if (typeof window !== 'undefined') {
    try {
      const { getSession } = await import('next-auth/react')
      const session = await getSession()
      if (session?.accessToken) {
        return session.accessToken
      }
    } catch (err) {
      console.warn('Could not read client session token:', err)
    }

    if (isSupabaseEnabled()) {
      try {
        const supabase = getSupabaseClient()
        const { data } = await supabase?.auth.getSession()
        return data?.session?.access_token ?? null
      } catch (err) {
        console.warn('Could not read Supabase session token:', err)
      }
    }
    return null
  }

  // Server-side token attachment is handled in Next.js route handlers; keep this
  // helper client-safe to avoid bundling server-only auth modules into client code.
  return null
}

export class BrainResearcherAPI {
  private notificationsEndpointStatus: NotificationsEndpointStatus = 'unknown'
  private notificationsUnsupportedWarningShown = false

  constructor() {
    this.notificationsEndpointStatus = this.readNotificationsEndpointStatus()
  }

  private readNotificationsEndpointStatus(): NotificationsEndpointStatus {
    if (typeof window === 'undefined') return 'unknown'
    try {
      const value = window.sessionStorage.getItem(NOTIFICATIONS_ENDPOINT_STATE_KEY)
      if (value === 'supported' || value === 'unsupported') return value
    } catch {
      // Ignore storage read failures.
    }
    try {
      const value = window.localStorage.getItem(NOTIFICATIONS_ENDPOINT_STATE_KEY)
      const tsRaw = window.localStorage.getItem(NOTIFICATIONS_ENDPOINT_STATE_TS_KEY)
      const ts = Number(tsRaw)
      const isFresh =
        Number.isFinite(ts) && Date.now() - ts <= NOTIFICATIONS_ENDPOINT_STATE_TTL_MS
      if ((value === 'supported' || value === 'unsupported') && isFresh) {
        return value
      }
      if (value || tsRaw) {
        window.localStorage.removeItem(NOTIFICATIONS_ENDPOINT_STATE_KEY)
        window.localStorage.removeItem(NOTIFICATIONS_ENDPOINT_STATE_TS_KEY)
      }
    } catch {
      // Ignore storage read failures.
    }
    return 'unknown'
  }

  private persistNotificationsEndpointStatus(state: NotificationsEndpointStatus): void {
    this.notificationsEndpointStatus = state
    if (typeof window === 'undefined') return
    try {
      if (state === 'unknown') {
        window.sessionStorage.removeItem(NOTIFICATIONS_ENDPOINT_STATE_KEY)
        window.localStorage.removeItem(NOTIFICATIONS_ENDPOINT_STATE_KEY)
        window.localStorage.removeItem(NOTIFICATIONS_ENDPOINT_STATE_TS_KEY)
      } else {
        window.sessionStorage.setItem(NOTIFICATIONS_ENDPOINT_STATE_KEY, state)
        window.localStorage.setItem(NOTIFICATIONS_ENDPOINT_STATE_KEY, state)
        window.localStorage.setItem(
          NOTIFICATIONS_ENDPOINT_STATE_TS_KEY,
          String(Date.now()),
        )
      }
    } catch {
      // Ignore storage write failures.
    }
  }

  private async safePostJson(url: string, payload: Record<string, unknown>): Promise<Response> {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
  }

  private async safePostJsonWithAuth(url: string, payload: Record<string, unknown>): Promise<Response> {
    const token = await getAccessTokenAnyContext()
    if (!token) {
      return this.safePostJson(url, payload)
    }

    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      credentials: 'include',
      body: JSON.stringify(payload),
    })
  }

  private async fetchJsonWithFallback(paths: string[], payload: Record<string, unknown>): Promise<Response> {
    let lastError: unknown = null

    for (const url of paths) {
      try {
        const response = await (url.startsWith('/')
          ? this.safePostJson(url, payload)
          : this.safePostJsonWithAuth(url, payload)
        )
        if (response.status !== 404 && response.status !== 405) {
          return response
        }
      } catch (error) {
        lastError = error
      }
    }

    if (lastError instanceof Error) {
      throw lastError
    }

    throw new Error('No backend endpoint available')
  }

  private async extractMessageFromResponse(response: Response): Promise<string> {
    try {
      const data = await response.json()
      return (
        data?.message?.content ||
        data?.text ||
        data?.output ||
        ''
      )
    } catch {
      return ''
    }
  }

  private markNotificationsEndpointUnsupported(statusCode?: number): void {
    if (this.notificationsEndpointStatus !== 'unsupported') {
      this.persistNotificationsEndpointStatus('unsupported')
    }
    if (!this.notificationsUnsupportedWarningShown) {
      const statusSuffix = typeof statusCode === 'number' ? ` (HTTP ${statusCode})` : ''
      console.warn(
        `[notifications] Endpoint unavailable${statusSuffix}; disabling notification fetches for this browser session.`,
      )
      this.notificationsUnsupportedWarningShown = true
    }
  }

  private markNotificationsEndpointSupported(): void {
    this.notificationsUnsupportedWarningShown = false
    this.persistNotificationsEndpointStatus('supported')
  }

  private buildEmptyNotifications(
    endpointStatus: NotificationsEndpointStatus = this.notificationsEndpointStatus,
  ): NotificationListResponse {
    return {
      notifications: [],
      unreadCount: 0,
      totalCount: 0,
      hasMore: false,
      cursor: null,
      endpointSupported: endpointStatus !== 'unsupported',
      endpointStatus,
    }
  }

  getNotificationsEndpointStatus(): NotificationsEndpointStatus {
    return this.notificationsEndpointStatus
  }

  // Enhanced request helper with automatic auth headers
  private async authenticatedFetch(url: string, options: RequestInit = {}): Promise<Response> {
    // Get current token for authorization
    const headers = new Headers(options.headers)
    const token = await getAccessTokenAnyContext()
    if (token) {
      headers.set('Authorization', `Bearer ${token}`)
    }

    return fetch(url, {
      ...options,
      headers,
      credentials: 'include' // Always include cookies for authenticated requests
    })
  }

  async getUserProfile(): Promise<UserProfile> {
    try {
      const response = await this.authenticatedFetch(`${ORCHESTRATOR_API}/api/user/profile`)
      if (response.ok) {
        const data = await response.json()
        return {
          id: data.id ?? 'unknown',
          username: data.username ?? 'unknown',
          fullName: data.full_name ?? data.fullName ?? null,
          avatarUrl: data.avatar_url ?? data.avatarUrl ?? null,
          role: data.role ?? null,
          unreadNotifications: data.unread_notifications ?? data.unreadNotifications ?? 0,
          lastActivity: data.last_activity ?? data.lastActivity ?? null
        }
      }
    } catch (err) {
      console.warn('Failed to load user profile:', err)
    }

    return {
      id: 'unknown',
      username: 'unknown',
      fullName: null,
      avatarUrl: null,
      role: null,
      unreadNotifications: 0,
      lastActivity: null
    }
  }

  async getUserNotifications(limit: number = 5): Promise<NotificationListResponse> {
    if (this.notificationsEndpointStatus === 'unsupported') {
      return this.buildEmptyNotifications('unsupported')
    }

    try {
      const response = await this.authenticatedFetch(
        `${ORCHESTRATOR_API}/api/user/notifications?limit=${encodeURIComponent(limit)}`
      )
      if (response.ok) {
        this.markNotificationsEndpointSupported()
        const data = await response.json()
        const notifications: NotificationItem[] = (data.notifications ?? []).map(
          (notification: any) => ({
            id: notification.id,
            type: notification.type,
            priority: notification.priority ?? 'normal',
            title: notification.title,
            message: notification.message,
            read: Boolean(notification.read),
            createdAt: notification.created_at ?? notification.createdAt ?? new Date().toISOString(),
            readAt: notification.read_at ?? notification.readAt ?? null,
            expiresAt: notification.expires_at ?? notification.expiresAt ?? null,
            actionUrl: notification.action_url ?? notification.actionUrl ?? null,
            actionText: notification.action_text ?? notification.actionText ?? null,
            data: notification.data ?? {}
          })
        )

        return {
          notifications,
          unreadCount: data.unread_count ?? data.unreadCount ?? 0,
          totalCount: data.total_count ?? data.totalCount ?? notifications.length,
          hasMore: data.has_more ?? data.hasMore ?? false,
          cursor: data.cursor ?? null,
          endpointSupported: true,
          endpointStatus: 'supported',
        }
      }

      if (
        response.status === 404 ||
        response.status === 405 ||
        response.status === 410 ||
        response.status === 501
      ) {
        this.markNotificationsEndpointUnsupported(response.status)
        return this.buildEmptyNotifications('unsupported')
      }
    } catch (err) {
      console.warn('Failed to load notifications:', err)
    }

    return this.buildEmptyNotifications()
  }

  async markNotificationsRead(notificationIds: string[]): Promise<void> {
    if (!notificationIds || notificationIds.length === 0) return
    if (this.notificationsEndpointStatus === 'unsupported') return
    try {
      const response = await this.authenticatedFetch(
        `${ORCHESTRATOR_API}/api/user/notifications/mark-read`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notification_ids: notificationIds })
        }
      )
      if (
        response.status === 404 ||
        response.status === 405 ||
        response.status === 410 ||
        response.status === 501
      ) {
        this.markNotificationsEndpointUnsupported(response.status)
        return
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
    } catch (err) {
      console.warn('Failed to mark notifications read:', err)
    }
  }

  // Workflow Templates (Orchestrator)
  async listWorkflowTemplates(params?: {
    category?: string
    status?: string
    tags?: string[]
    limit?: number
    offset?: number
  }): Promise<WorkflowTemplateListItem[]> {
    const query = new URLSearchParams()
    if (params?.category) query.set('category', params.category)
    if (params?.status) query.set('status', params.status)
    if (params?.tags?.length) {
      params.tags.forEach(tag => query.append('tags', tag))
    }
    if (typeof params?.limit === 'number') query.set('limit', String(params.limit))
    if (typeof params?.offset === 'number') query.set('offset', String(params.offset))

    const url = `${ORCHESTRATOR_API}/api/templates${query.toString() ? `?${query}` : ''}`
    const response = await this.authenticatedFetch(url)
    if (!response.ok) {
      throw new Error(`Failed to fetch templates: ${response.status} ${response.statusText}`)
    }
    return response.json()
  }

  async getWorkflowTemplate(templateId: string): Promise<WorkflowTemplateDetail> {
    const url = `${ORCHESTRATOR_API}/api/templates/${encodeURIComponent(templateId)}`
    const response = await this.authenticatedFetch(url)
    if (!response.ok) {
      throw new Error(`Failed to fetch template: ${response.status} ${response.statusText}`)
    }
    return response.json()
  }

  async createWorkflowTemplate(
    templateData: Record<string, unknown>,
    saveToFile: boolean = true
  ): Promise<WorkflowTemplateCreateResponse> {
    const response = await this.authenticatedFetch(`${ORCHESTRATOR_API}/api/templates/custom`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_data: templateData, save_to_file: saveToFile })
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload?.detail?.errors?.join?.(', ') || payload?.detail || response.statusText)
    }
    return response.json()
  }

  // Workflow Catalog API (dynamically loaded from workflow_catalog.yaml)
  async fetchWorkflowCatalog(filters?: WorkflowFilters): Promise<WorkflowCatalogResponse> {
    const params = new URLSearchParams()
    if (filters?.stage) params.set('stage', filters.stage)
    if (filters?.cost_tier) params.set('cost_tier', filters.cost_tier)
    if (filters?.modality) params.set('modality', filters.modality)
    if (filters?.limit) params.set('limit', String(filters.limit))
    if (filters?.offset) params.set('offset', String(filters.offset))

    const queryStr = params.toString()
    // Use Next.js API proxy route to ensure auth cookies are forwarded
    const url = `/api/workflows${queryStr ? `?${queryStr}` : ''}`

    const response = await this.authenticatedFetch(url)
    if (!response.ok) {
      throw new Error(`Failed to fetch workflows: ${response.status} ${response.statusText}`)
    }
    return response.json()
  }

  async fetchWorkflowById(workflowId: string): Promise<WorkflowDetail> {
    // Use Next.js API proxy route to ensure auth cookies are forwarded
    const url = `/api/workflows/${encodeURIComponent(workflowId)}`
    const response = await this.authenticatedFetch(url)
    if (!response.ok) {
      throw new Error(`Failed to fetch workflow ${workflowId}: ${response.status} ${response.statusText}`)
    }
    return response.json()
  }

  async fetchWorkflowStages(): Promise<string[]> {
    // Use Next.js API proxy route to ensure auth cookies are forwarded
    const url = `/api/workflows/stages/list`
    const response = await this.authenticatedFetch(url)
    if (!response.ok) {
      throw new Error(`Failed to fetch workflow stages: ${response.status} ${response.statusText}`)
    }
    const data = await response.json()
    return data.stages
  }

  // BR-KG Knowledge Graph API
  async searchKnowledgeGraph(query: string, options?: {
    type?: string
    depth?: number
    limit?: number
  }) {
    const params = new URLSearchParams({
      q: query,
      type: options?.type || 'All',
      depth: String(options?.depth || 2),
      limit: String(options?.limit || 100)
    })
    
    const response = await fetch(resolveKgApiUrl('search_and_expand', params))
    if (!response.ok) throw new Error('Failed to search knowledge graph')
    return response.json()
  }

  async getGraphStats() {
    const response = await fetch(resolveKgApiUrl('statistics'))
    if (!response.ok) throw new Error('Failed to get graph stats')
    return response.json()
  }

  async expandNode(nodeId: string, nodeType?: string, depth: number = 1) {
    const params = new URLSearchParams({
      label: nodeType || 'Node',
      name: nodeId,
      depth: String(depth)
    })
    
    const response = await fetch(resolveKgRootUrl('subgraph', params))
    if (!response.ok) throw new Error('Failed to expand node')
    return response.json()
  }

  async searchNodes(query: string, options?: {
    nodeTypes?: string[]
    limit?: number
    signal?: AbortSignal
  }) {
    const searchParams = new URLSearchParams({
      query,
      limit: String(options?.limit || 50)
    })
    
    if (options?.nodeTypes?.length) {
      searchParams.append('types', options.nodeTypes.join(','))
    }
    
    const response = await fetch(resolveKgApiUrl('search', searchParams), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: options?.signal,
      body: JSON.stringify({ 
        query,
        types: options?.nodeTypes || [],
        limit: options?.limit || 50
      })
    })
    if (!response.ok) throw new Error('Failed to search nodes')
    const data = await response.json()
    if (Array.isArray(data)) {
      return data
    }
    return data.results || []
  }

  async queryGraphQL(query: string, variables?: Record<string, any>) {
    const response = await fetch(resolveKgRootUrl('graphql'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, variables })
    })
    if (!response.ok) throw new Error('GraphQL query failed')
    return response.json()
  }

  // Knowledge Graph - Pipeline Catalog Integration
  async fetchKGPipelines(): Promise<KGPipelinesResponse> {
    const response = await fetch('/api/kg/pipelines')
    if (!response.ok) {
      throw new Error('Failed to fetch KG pipelines')
    }
    return response.json()
  }

  async fetchKGTools(
    intent: string,
    pipeline?: string,
    perFamily: number = 5,
    options?: {
      exposures?: string[]
      domain?: string
      func?: string
      risk?: string
    }
  ): Promise<KGToolsResponse> {
    const params = new URLSearchParams({ intent })
    if (pipeline) params.append('pipeline', pipeline)
    if (perFamily) params.append('per_family', String(perFamily))

    if (options?.exposures && options.exposures.length > 0) {
      options.exposures.forEach(e => params.append('exposure', e))
    }
    if (options?.domain) params.append('domain', options.domain)
    if (options?.func) params.append('function', options.func)
    if (options?.risk) params.append('risk', options.risk)

    const response = await fetch(`/api/kg/tools?${params}`)
    if (!response.ok) {
      throw new Error('Failed to fetch KG tools')
    }
    const raw = await response.json()

    // The agent debug endpoint returns families + examples, not a flat tools list.
    // Normalize to our KGTool shape for the UI.
    const tools: KGTool[] = []
    const grouped_by_family: Record<string, KGTool[]> = {}

    if (Array.isArray(raw.families)) {
      raw.families.forEach((fam: any) => {
        const famId = fam.family || fam.id
        const examples = fam.examples || []
        examples.forEach((ex: any) => {
          const tool: KGTool = {
            id: ex.id,
            name: ex.name || ex.id || ex.entrypoint || 'unknown tool',
            family: famId,
            is_promoted: !!ex.is_promoted,
            runtime_estimate_seconds: ex.runtime_estimate_seconds,
            kg_tool_count: fam.kg_tool_count,
            description: ex.description,
            version: ex.version,
            metadata: ex.metadata || {},
          }
          tools.push(tool)
          if (!grouped_by_family[famId]) grouped_by_family[famId] = []
          grouped_by_family[famId].push(tool)
        })
      })
    }

    return {
      tools,
      grouped_by_family,
      total_count: tools.length,
      operation: raw.intent,
      pipeline: raw.pipeline,
    }
  }

  async requestPlan(payload: PlanRequest): Promise<AgentPlanResponse> {
    const params = new URLSearchParams()
    if (payload.debug_selection) {
      params.append('debug_selection', 'true')
    }

    const url = `/api/plan${params.toString() ? '?' + params.toString() : ''}`
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      let errorMessage = 'Failed to request plan'
      try {
        const errorData = await response.json()
        errorMessage = errorData.error || errorData.detail || errorMessage
      } catch (e) {
        // Use default error message
      }
      throw new Error(errorMessage)
    }

    return response.json()
  }

  // Agent LLM Service (via Orchestrator)
  async createThread(): Promise<{ thread_id: string }> {
    const response = await fetch(`${ORCHESTRATOR_API}/threads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    })
    if (!response.ok) throw new Error('Failed to create thread')
    return response.json()
  }

  async sendMessage(threadId: string, message: string, onChunk?: (chunk: any) => void, resumeCheckpointId?: string | null) {
    const response = await fetch(`${ORCHESTRATOR_API}/threads/${threadId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ content: message, resume_checkpoint_id: resumeCheckpointId || undefined })
    })

    if (!response.ok) throw new Error('Failed to send message')

    // Handle streaming response
    if (onChunk && response.body) {
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        const chunk = decoder.decode(value)
        const lines = chunk.split('\\n')
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onChunk(data)
            } catch (e) {
              // Skip invalid JSON
            }
          }
        }
      }
    }
  }

  async getThreadHistory(threadId: string): Promise<Message[]> {
    const response = await fetch(`${ORCHESTRATOR_API}/threads/${threadId}/messages`, {
      credentials: 'include'
    })
    if (!response.ok) throw new Error('Failed to get thread history')
    const data = await response.json()
    return data.messages || []
  }

  // Dataset Integration (OpenNeuro via BR-KG)
  async getDatasets(options?: {
    limit?: number
    offset?: number
    search?: string
  }): Promise<Dataset[]> {
    const params = new URLSearchParams({
      limit: String(options?.limit || 50),
      offset: String(options?.offset || 0),
      ...(options?.search && { search: options.search })
    })
    
    const response = await fetch(resolveKgApiUrl('openneuro/datasets', params))
    if (!response.ok) throw new Error('Failed to fetch datasets')
    
    const data = await response.json()
    
    // Transform to match Dataset type
    return (data.datasets || []).map((ds: any) => ({
      id: ds.id,
      name: ds.title || ds.name,
      description: ds.description || '',
      subjects: ds.participant_count || 0,
      modalities: ds.modalities || [],
      tasks: ds.tasks || [],
      publicationCount: ds.publications?.length || 0,
      lastUpdated: ds.updated_at || new Date().toISOString(),
      source: 'OpenNeuro',
      metadata: ds
    }))
  }

  async getDatasetDetails(datasetId: string) {
    const response = await fetch(
      resolveKgApiUrl(`openneuro/datasets/${encodeURIComponent(datasetId)}`),
    )
    if (!response.ok) throw new Error('Failed to fetch dataset details')
    return response.json()
  }

  // NICLIP Integration
  async mapTextToBrain(text: string) {
    if (!NICLIP_API) {
      throw new Error('NICLIP is not configured')
    }
    const response = await fetch(`${NICLIP_API}/api/predict`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    })
    if (!response.ok) throw new Error('Failed to map text to brain')
    return response.json()
  }

  async findSimilarConcepts(concept: string, limit: number = 10) {
    if (!NICLIP_API) {
      throw new Error('NICLIP is not configured')
    }
    const response = await fetch(`${NICLIP_API}/api/similar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concept, limit })
    })
    if (!response.ok) throw new Error('Failed to find similar concepts')
    return response.json()
  }

  // Analysis Tools (via Orchestrator)
  async runAnalysis(tool: string, parameters: Record<string, any>) {
    // Try orchestrator first
    try {
      const response = await fetch(`${ORCHESTRATOR_API}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          prompt: `Run ${tool} analysis`,
          parameters,
          pipeline: tool
        })
      })
      if (response.ok) {
        return response.json()
      }
    } catch (e) {
      console.warn('Orchestrator unavailable, using direct agent API')
    }
    
    const response = await fetch(`${AGENT_API}/api/tools/${tool}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parameters })
    })
    if (!response.ok) throw new Error(`Failed to run ${tool} analysis`)
    return response.json()
  }

  async executePipeline(payload: ExecutePipelinePayload): Promise<PipelineExecutionResponse> {
    const response = await this.authenticatedFetch(`${ORCHESTRATOR_API}/pipeline/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      let message = 'Failed to execute pipeline'
      try {
        const error = await response.json()
        message = error?.detail || message
      } catch (error) {
        // Ignore JSON parse errors, fall back to default message
      }
      throw new Error(message)
    }

    return response.json()
  }

  // Literature Search (via BR-KG)
  async searchLiterature(query: string, options?: {
    limit?: number
    yearFrom?: number
    yearTo?: number
  }) {
    const params = new URLSearchParams({
      q: query,
      limit: String(options?.limit || 20),
      ...(options?.yearFrom && { year_from: String(options.yearFrom) }),
      ...(options?.yearTo && { year_to: String(options.yearTo) })
    })
    
    const response = await fetch(resolveKgApiUrl('literature/search', params))
    if (!response.ok) throw new Error('Failed to search literature')
    return response.json()
  }

  // Copilot endpoints are orchestrator-owned; do not fall back to Agent.
  async copilotSuggest(
    query: string,
    metadata?: Record<string, any>,
    k: number = 5,
    options?: {
      exposures?: string[]
      domain?: string
      func?: string
      risk?: string
    }
  ) {
    const payload = {
      query,
      metadata: metadata || {},
      k,
      exposures: options?.exposures,
      domain: options?.domain,
      function: options?.func,
      risk: options?.risk,
    }

    const endpoints = new Set<string>([
      ...(typeof window !== 'undefined' && USE_API_PROXY ? ['/copilot/suggest'] : []),
      `${ORCHESTRATOR_API}/copilot/suggest`,
    ])

    const response = await this.fetchJsonWithFallback(Array.from(endpoints), payload)
    if (response.ok) {
      return response.json()
    }

    throw new Error(`Failed to get copilot suggestions: ${response.status}`)
  }

  async chat(message: string, options?: ChatOptions) {
    const payload: Record<string, unknown> = { message }
    if (options?.copilot) {
      payload.copilot = true
      payload.metadata = {
        copilot: true,
        ui_surface: 'studio_copilot',
      }
      payload.messages = [
        { role: 'system', content: COPILOT_CHAT_SYSTEM_PROMPT },
        { role: 'user', content: message },
      ]
    }

    const proxyEndpoints = ['/api/chat', `${ORCHESTRATOR_API}/api/chat`]
    const response = await this.fetchJsonWithFallback(proxyEndpoints, payload)

    if (!response.ok) {
      const fallbackMessage = await this.extractMessageFromResponse(response)
      if (response.status === 401 || response.status === 403) {
        return fallbackMessage || 'No response (authorization required).'
      }
      if (response.status >= 500) {
        throw new Error(fallbackMessage || `Chat service error: ${response.status}`)
      }

      throw new Error(fallbackMessage || `Failed to get chat response: ${response.status}`)
    }

    const content = await this.extractMessageFromResponse(response)
    if (!content) {
      throw new Error('No chat content in response')
    }

    return String(content)
  }

  async copilotAutocomplete(tool: string, params?: Record<string, any>, metadata?: Record<string, any>) {
    const payload = { tool, params: params || {}, metadata: metadata || {} }
    const endpoints = [
      ...(typeof window !== 'undefined' && USE_API_PROXY ? ['/copilot/autocomplete'] : []),
      `${ORCHESTRATOR_API}/copilot/autocomplete`,
    ]
    const response = await this.fetchJsonWithFallback(endpoints, payload)
    if (!response.ok) throw new Error(`Failed to autocomplete params: ${response.status}`)
    return response.json()
  }

  async copilotLearn(tool: string, params?: Record<string, any>) {
    const payload = { tool, params: params || {} }
    const endpoints = [
      ...(typeof window !== 'undefined' && USE_API_PROXY ? ['/copilot/learn'] : []),
      `${ORCHESTRATOR_API}/copilot/learn`,
    ]
    const response = await this.fetchJsonWithFallback(endpoints, payload)
    if (!response.ok) throw new Error(`Failed to record learning: ${response.status}`)
    return response.json()
  }

  // File Upload Methods (UI-003)
  async uploadFile(file: File, onProgress?: (progress: number) => void): Promise<any> {
    const formData = new FormData()
    formData.append('file', file)
    
    const xhr = new XMLHttpRequest()
    // Ensure cookies (if any) are sent along with uploads
    xhr.withCredentials = true
    
    return new Promise((resolve, reject) => {
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable && onProgress) {
          const progress = Math.round((event.loaded / event.total) * 100)
          onProgress(progress)
        }
      })
      
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch (e) {
            reject(new Error('Invalid response from server'))
          }
        } else {
          try {
            const error = JSON.parse(xhr.responseText)
            reject(new Error(error.detail || `Upload failed with status ${xhr.status}`))
          } catch (e) {
            reject(new Error(`Upload failed with status ${xhr.status}`))
          }
        }
      })
      
      xhr.addEventListener('error', () => {
        reject(new Error('Upload failed'))
      })
      
      xhr.open('POST', `${ORCHESTRATOR_API}/upload`)

      // Add auth headers from NextAuth session if available
      // Note: We open the XHR first, then set headers
      if (typeof window !== 'undefined') {
        getAccessTokenAnyContext()
          .then((token) => {
            if (token) {
              xhr.setRequestHeader('Authorization', `Bearer ${token}`)
            }
            xhr.send(formData)
          })
          .catch(() => {
            xhr.send(formData)
          })
      } else {
        xhr.send(formData)
      }
    })
  }
  
  async deleteFile(fileId: string) {
    const response = await this.authenticatedFetch(`${ORCHESTRATOR_API}/uploads/${fileId}`, {
      method: 'DELETE'
    })
    if (!response.ok) throw new Error('Failed to delete file')
    return response.json()
  }
  
  async getFileInfo(fileId: string) {
    const response = await this.authenticatedFetch(`${ORCHESTRATOR_API}/uploads/info/${fileId}`)
    if (!response.ok) throw new Error('Failed to get file info')
    return response.json()
  }
  
  getFileUrl(fileId: string, filename: string) {
    return `${ORCHESTRATOR_API}/uploads/${fileId}/${filename}`
  }
}

export const brainResearcherAPI = new BrainResearcherAPI()
