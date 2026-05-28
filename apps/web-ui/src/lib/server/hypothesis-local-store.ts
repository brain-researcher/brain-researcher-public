import type { HypothesisChatMessage } from '@/types/hypothesis'
import {
  loadHypothesisStoreRecord,
  persistHypothesisStoreRecord,
} from '@/lib/server/hypothesis-persistence'

type LocalOpenQuestion = {
  id: string
  title: string
  description: string
  status: 'open' | 'in_progress' | 'resolved'
  priority: 'high' | 'medium' | 'low'
  leverage_hint?: string | null
}

type LocalHypothesisCandidate = {
  id: string
  title: string
  statement: string
  status: 'open' | 'provisional' | 'selected' | 'rejected' | 'verified'
  tags: string[]
  open_question_id?: string | null
  rationale?: string | null
  score: {
    total_score: number
    novelty: number
    coherence: number
    leverage: number
    feasibility: number
    risk: number
  }
  traces: Array<{
    agent: 'explorer' | 'critic' | 'verifier' | 'ranker'
    status: 'ok' | 'warning' | 'error' | 'pending'
    summary: string
    details: string[]
    updated_at: string
  }>
  mde: {
    id: string
    objective: string
    minimal_test: string
    falsifier: string
    expected_signals: string[]
    confounds: string[]
    cost_estimate: string
    status: 'draft' | 'ready' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  } | null
  evidence: Array<{
    id: string
    label: string
    kind: 'paper' | 'dataset' | 'experiment' | 'note' | 'other'
    summary?: string | null
    url?: string | null
  }>
  created_at: string
  updated_at: string
}

type LocalHypothesisSession = {
  session_id: string
  context: {
    session_id: string
    dataset_id: string | null
    concept_id: string | null
    task_id: string | null
    thread_id: string | null
  }
  open_questions: LocalOpenQuestion[]
  candidates: LocalHypothesisCandidate[]
  selected_hypothesis_id: string | null
  leaderboard_url: string | null
  messages: HypothesisChatMessage[]
  updated_at: string
}

type LocalBatchRun = {
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  queued_count: number
  started_at: string
  updated_at: string
  leaderboard_url: string | null
  session_id: string
}

type LocalStore = {
  sessions: Map<string, LocalHypothesisSession>
  runs: Map<string, LocalBatchRun>
}

declare global {
  // eslint-disable-next-line no-var
  var __brHypothesisLocalStore: LocalStore | undefined
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function asNullableString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed || null
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function asFiniteNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

function asIsoOrNow(value: unknown): string {
  return asNullableString(value) || nowIso()
}

function normalizeTraceStatus(value: unknown): LocalHypothesisCandidate['traces'][number]['status'] {
  if (value === 'ok' || value === 'warning' || value === 'error' || value === 'pending') {
    return value
  }
  return 'pending'
}

function normalizeTraceAgent(value: unknown): LocalHypothesisCandidate['traces'][number]['agent'] {
  if (value === 'explorer' || value === 'critic' || value === 'verifier' || value === 'ranker') {
    return value
  }
  return 'explorer'
}

function normalizeCandidateStatus(value: unknown): LocalHypothesisCandidate['status'] {
  if (
    value === 'open' ||
    value === 'provisional' ||
    value === 'selected' ||
    value === 'rejected' ||
    value === 'verified'
  ) {
    return value
  }
  return 'provisional'
}

function normalizeOpenQuestionStatus(value: unknown): LocalOpenQuestion['status'] {
  if (value === 'open' || value === 'in_progress' || value === 'resolved') return value
  return 'open'
}

function normalizeOpenQuestionPriority(value: unknown): LocalOpenQuestion['priority'] {
  if (value === 'high' || value === 'medium' || value === 'low') return value
  return 'medium'
}

function normalizeMdeStatus(value: unknown): NonNullable<LocalHypothesisCandidate['mde']>['status'] {
  if (
    value === 'draft' ||
    value === 'ready' ||
    value === 'queued' ||
    value === 'running' ||
    value === 'completed' ||
    value === 'failed' ||
    value === 'cancelled'
  ) {
    return value
  }
  return 'draft'
}

function normalizeRemoteEvidence(raw: unknown): LocalHypothesisCandidate['evidence'][number] | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  const id =
    asNullableString(source.id) ||
    asNullableString(source.evidence_id) ||
    asNullableString(source.evidenceId) ||
    makeId('evidence')
  const label =
    asNullableString(source.label) || asNullableString(source.title) || 'Untitled evidence'
  const kind = source.kind
  const normalizedKind: LocalHypothesisCandidate['evidence'][number]['kind'] =
    kind === 'paper' || kind === 'dataset' || kind === 'experiment' || kind === 'note'
      ? kind
      : 'other'
  return {
    id,
    label,
    kind: normalizedKind,
    summary: asNullableString(source.summary),
    url: asNullableString(source.url),
  }
}

function normalizeRemoteMde(raw: unknown): LocalHypothesisCandidate['mde'] {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  return {
    id: asNullableString(source.id) || asNullableString(source.mde_id) || makeId('mde'),
    objective:
      asNullableString(source.objective) ||
      asNullableString(source.question) ||
      'Define discriminating objective.',
    minimal_test:
      asNullableString(source.minimal_test) ||
      asNullableString(source.minimalTest) ||
      asNullableString(source.test) ||
      'Design minimum discriminating test.',
    falsifier:
      asNullableString(source.falsifier) ||
      'Specify what result would falsify this hypothesis.',
    expected_signals: asStringArray(source.expected_signals ?? source.expectedSignals),
    confounds: asStringArray(source.confounds),
    cost_estimate: asNullableString(source.cost_estimate ?? source.costEstimate),
    status: normalizeMdeStatus(source.status),
  }
}

function normalizeRemoteCandidate(raw: unknown, index: number): LocalHypothesisCandidate | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  const timestamp = nowIso()
  const scoreRaw =
    source.score && typeof source.score === 'object'
      ? (source.score as Record<string, unknown>)
      : {}
  const tracesRaw = Array.isArray(source.traces)
    ? source.traces
    : Array.isArray(source.agent_traces)
      ? source.agent_traces
      : []
  const evidenceRaw = Array.isArray(source.evidence) ? source.evidence : []

  return {
    id:
      asNullableString(source.id) ||
      asNullableString(source.hypothesis_id) ||
      asNullableString(source.hypothesisId) ||
      makeId('hyp'),
    title:
      asNullableString(source.title) ||
      asNullableString(source.name) ||
      `Direction ${index + 1}`,
    statement:
      asNullableString(source.statement) ||
      asNullableString(source.hypothesis) ||
      asNullableString(source.summary) ||
      'No statement provided.',
    status: normalizeCandidateStatus(source.status),
    tags: asStringArray(source.tags),
    open_question_id: asNullableString(source.open_question_id ?? source.openQuestionId),
    rationale: asNullableString(source.rationale),
    score: {
      total_score: asFiniteNumber(scoreRaw.total_score ?? scoreRaw.totalScore),
      novelty: asFiniteNumber(scoreRaw.novelty),
      coherence: asFiniteNumber(scoreRaw.coherence),
      leverage: asFiniteNumber(scoreRaw.leverage),
      feasibility: asFiniteNumber(scoreRaw.feasibility),
      risk: asFiniteNumber(scoreRaw.risk),
    },
    traces: tracesRaw
      .map((traceRaw) => {
        if (!traceRaw || typeof traceRaw !== 'object') return null
        const trace = traceRaw as Record<string, unknown>
        return {
          agent: normalizeTraceAgent(trace.agent),
          status: normalizeTraceStatus(trace.status),
          summary:
            asNullableString(trace.summary) || 'Trace details unavailable from remote snapshot.',
          details: asStringArray(trace.details),
          updated_at: asIsoOrNow(trace.updated_at ?? trace.updatedAt),
        } satisfies LocalHypothesisCandidate['traces'][number]
      })
      .filter((trace): trace is LocalHypothesisCandidate['traces'][number] => Boolean(trace)),
    mde: normalizeRemoteMde(source.mde),
    evidence: evidenceRaw
      .map((item) => normalizeRemoteEvidence(item))
      .filter((item): item is LocalHypothesisCandidate['evidence'][number] => Boolean(item)),
    created_at: asIsoOrNow(source.created_at ?? source.createdAt),
    updated_at: asIsoOrNow(source.updated_at ?? source.updatedAt ?? timestamp),
  }
}

function normalizeRemoteOpenQuestion(raw: unknown, index: number): LocalOpenQuestion | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  return {
    id:
      asNullableString(source.id) ||
      asNullableString(source.question_id) ||
      asNullableString(source.questionId) ||
      `oq-${index + 1}`,
    title:
      asNullableString(source.title) || asNullableString(source.question) || `Question ${index + 1}`,
    description: asNullableString(source.description) || '',
    status: normalizeOpenQuestionStatus(source.status),
    priority: normalizeOpenQuestionPriority(source.priority),
    leverage_hint: asNullableString(source.leverage_hint ?? source.leverageHint),
  }
}

function mergeById<T extends Record<string, unknown>>(existing: T[], incoming: T[]): T[] {
  const merged = new Map<string, T>()
  for (const item of existing) {
    const id = asNullableString(item.id)
    if (!id) continue
    merged.set(id, item)
  }
  for (const item of incoming) {
    const id = asNullableString(item.id)
    if (!id) continue
    merged.set(id, item)
  }
  return Array.from(merged.values())
}

function mergeMessages(
  existing: HypothesisChatMessage[],
  incoming: HypothesisChatMessage[],
): HypothesisChatMessage[] {
  if (!incoming.length) return existing
  const merged = new Map<string, HypothesisChatMessage>()

  const put = (message: HypothesisChatMessage) => {
    const key = asNullableString(message.id) || `${message.role}:${message.timestamp}:${message.content}`
    merged.set(key, message)
  }

  existing.forEach(put)
  incoming.forEach(put)

  return Array.from(merged.values()).sort((left, right) => {
    const lt = Date.parse(left.timestamp)
    const rt = Date.parse(right.timestamp)
    return (Number.isFinite(lt) ? lt : 0) - (Number.isFinite(rt) ? rt : 0)
  })
}

function normalizeMessageRole(value: unknown): HypothesisChatMessage['role'] {
  if (value === 'assistant') return 'assistant'
  if (value === 'system') return 'system'
  return 'user'
}

function normalizeMessage(raw: unknown): HypothesisChatMessage | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  const content = typeof source.content === 'string' ? source.content.trim() : ''
  if (!content) return null

  const id =
    (typeof source.id === 'string' && source.id.trim()) ||
    makeId('msg')
  const timestamp =
    (typeof source.timestamp === 'string' && source.timestamp.trim()) ||
    nowIso()

  return {
    id,
    role: normalizeMessageRole(source.role),
    content,
    timestamp,
  }
}

function normalizePersistedSession(
  raw: LocalHypothesisSession,
  fallbackSessionId: string,
): LocalHypothesisSession {
  const sessionId = asNullableString(raw?.session_id) || fallbackSessionId
  const contextSource = (raw?.context || {}) as Record<string, unknown>
  const openQuestions = Array.isArray(raw?.open_questions) ? raw.open_questions : defaultOpenQuestions()
  const candidates = Array.isArray(raw?.candidates) ? raw.candidates : []
  const messagesRaw = Array.isArray((raw as any)?.messages) ? (raw as any).messages : []
  const messages = messagesRaw
    .map((item) => normalizeMessage(item))
    .filter((item): item is HypothesisChatMessage => Boolean(item))

  return {
    session_id: sessionId,
    context: {
      session_id: asNullableString(contextSource.session_id) || sessionId,
      dataset_id: asNullableString(contextSource.dataset_id),
      concept_id: asNullableString(contextSource.concept_id),
      task_id: asNullableString(contextSource.task_id),
      thread_id: asNullableString(contextSource.thread_id),
    },
    open_questions: openQuestions,
    candidates,
    selected_hypothesis_id: asNullableString((raw as any)?.selected_hypothesis_id),
    leaderboard_url: asNullableString((raw as any)?.leaderboard_url),
    messages,
    updated_at: asNullableString((raw as any)?.updated_at) || nowIso(),
  }
}

function normalizePersistedRun(raw: LocalBatchRun, fallbackRunId: string): LocalBatchRun {
  return {
    run_id: asNullableString((raw as any)?.run_id) || fallbackRunId,
    status:
      (typeof (raw as any)?.status === 'string' &&
      ['queued', 'running', 'completed', 'failed', 'cancelled'].includes((raw as any).status)
        ? (raw as any).status
        : 'queued') as LocalBatchRun['status'],
    queued_count: Number.isFinite((raw as any)?.queued_count)
      ? Math.max(0, Math.trunc((raw as any).queued_count))
      : 0,
    started_at: asNullableString((raw as any)?.started_at) || nowIso(),
    updated_at: asNullableString((raw as any)?.updated_at) || nowIso(),
    leaderboard_url: asNullableString((raw as any)?.leaderboard_url),
    session_id: asNullableString((raw as any)?.session_id) || '',
  }
}

function getStore(): LocalStore {
  if (!globalThis.__brHypothesisLocalStore) {
    globalThis.__brHypothesisLocalStore = {
      sessions: new Map<string, LocalHypothesisSession>(),
      runs: new Map<string, LocalBatchRun>(),
    }
  }
  return globalThis.__brHypothesisLocalStore
}

function persistSession(session: LocalHypothesisSession): void {
  persistHypothesisStoreRecord('local_session', session.session_id, session)
}

function persistRun(run: LocalBatchRun): void {
  persistHypothesisStoreRecord('local_run', run.run_id, run)
}

async function hydrateSessionFromPersistence(sessionId: string): Promise<LocalHypothesisSession | null> {
  const normalizedSessionId = (sessionId || '').trim()
  if (!normalizedSessionId) return null

  const store = getStore()
  const existing = store.sessions.get(normalizedSessionId)
  if (existing) return existing

  const persisted = await loadHypothesisStoreRecord<LocalHypothesisSession>(
    'local_session',
    normalizedSessionId,
  )
  if (!persisted) return null

  const session = normalizePersistedSession(persisted, normalizedSessionId)
  store.sessions.set(normalizedSessionId, session)
  return session
}

async function hydrateRunFromPersistence(runId: string): Promise<LocalBatchRun | null> {
  const normalizedRunId = (runId || '').trim()
  if (!normalizedRunId) return null

  const store = getStore()
  const existing = store.runs.get(normalizedRunId)
  if (existing) return existing

  const persisted = await loadHypothesisStoreRecord<LocalBatchRun>('local_run', normalizedRunId)
  if (!persisted) return null

  const run = normalizePersistedRun(persisted, normalizedRunId)
  store.runs.set(normalizedRunId, run)
  return run
}

function defaultOpenQuestions(): LocalOpenQuestion[] {
  return [
    {
      id: 'oq-bridge',
      title: 'Bridge disconnected evidence clusters',
      description:
        'Find a hypothesis that connects claims across currently disconnected concept/method regions.',
      status: 'open',
      priority: 'high',
      leverage_hint: 'Bridge edge with highest expected information gain',
    },
    {
      id: 'oq-bottleneck',
      title: 'Collapse methodological bottleneck',
      description:
        'Propose a route that reduces path cost caused by a single dominant analysis bottleneck.',
      status: 'open',
      priority: 'medium',
      leverage_hint: 'Target preprocessing or model assumptions that constrain most results',
    },
    {
      id: 'oq-contradiction',
      title: 'Resolve contradiction loop',
      description:
        'Construct a conditionally valid explanation for contradictory findings in existing studies.',
      status: 'open',
      priority: 'medium',
      leverage_hint: 'Look for subgroup- or task-conditioned consistency',
    },
  ]
}

function buildCandidate(index: number, openQuestionId?: string | null): LocalHypothesisCandidate {
  const timestamp = nowIso()
  const scoreBase = Math.max(0.5, 0.85 - index * 0.06)
  const novelty = Number((scoreBase + 0.05).toFixed(2))
  const coherence = Number((scoreBase - 0.02).toFixed(2))
  const leverage = Number((scoreBase + 0.01).toFixed(2))
  const feasibility = Number((scoreBase - 0.04).toFixed(2))
  const risk = Number((0.25 + index * 0.08).toFixed(2))
  const total = Number(
    ((novelty + coherence + leverage + feasibility - risk) / 4).toFixed(2),
  )

  return {
    id: makeId('hyp'),
    title: `Direction ${index + 1}`,
    statement:
      'Low-probability but structurally coherent hypothesis with an explicit minimal discriminating test.',
    status: 'provisional',
    tags: ['novelty', 'coherence', 'mde'],
    open_question_id: openQuestionId || null,
    rationale: 'Generated from local fallback when remote hypothesis service is unavailable.',
    score: {
      total_score: total,
      novelty,
      coherence,
      leverage,
      feasibility,
      risk,
    },
    traces: [
      {
        agent: 'explorer',
        status: 'ok',
        summary: 'Generated candidate from current question context.',
        details: ['Bridge/bottleneck/contradiction heuristics applied'],
        updated_at: timestamp,
      },
      {
        agent: 'verifier',
        status: 'warning',
        summary: 'Awaiting external evidence verification.',
        details: ['No upstream hypothesis backend available in this environment'],
        updated_at: timestamp,
      },
    ],
    mde: {
      id: makeId('mde'),
      objective: 'Discriminate this candidate against one competing explanation.',
      minimal_test: 'Run a low-cost proxy analysis on available dataset summary.',
      falsifier: 'Reject if predicted direction is not observed after confound control.',
      expected_signals: ['Direction-consistent effect estimate', 'Reduced contradiction with prior claims'],
      confounds: ['site effect', 'measurement noise', 'population imbalance'],
      cost_estimate: 'low',
      status: 'draft',
    },
    evidence: [],
    created_at: timestamp,
    updated_at: timestamp,
  }
}

export function getOrCreateLocalHypothesisSession(args: {
  sessionId?: string | null
  datasetId?: string | null
  conceptId?: string | null
  taskId?: string | null
  threadId?: string | null
}): LocalHypothesisSession {
  const store = getStore()
  const sessionId = args.sessionId || makeId('session')
  const existing = store.sessions.get(sessionId)
  if (existing) return existing

  const session: LocalHypothesisSession = {
    session_id: sessionId,
    context: {
      session_id: sessionId,
      dataset_id: asNullableString(args.datasetId),
      concept_id: asNullableString(args.conceptId),
      task_id: asNullableString(args.taskId),
      thread_id: asNullableString(args.threadId),
    },
    open_questions: defaultOpenQuestions(),
    candidates: [],
    selected_hypothesis_id: null,
    leaderboard_url: null,
    messages: [],
    updated_at: nowIso(),
  }

  store.sessions.set(sessionId, session)
  persistSession(session)
  return session
}

export async function getOrCreateLocalHypothesisSessionPersisted(args: {
  sessionId?: string | null
  datasetId?: string | null
  conceptId?: string | null
  taskId?: string | null
  threadId?: string | null
}): Promise<LocalHypothesisSession> {
  const requestedId = asNullableString(args.sessionId)
  if (requestedId) {
    const hydrated = await hydrateSessionFromPersistence(requestedId)
    if (hydrated) return hydrated
  }
  return getOrCreateLocalHypothesisSession(args)
}

export async function getLocalHypothesisSessionPersisted(
  sessionId: string | null | undefined,
): Promise<LocalHypothesisSession | null> {
  const normalized = asNullableString(sessionId)
  if (!normalized) return null
  return hydrateSessionFromPersistence(normalized)
}

export async function upsertLocalHypothesisSessionFromRemote(args: {
  sessionId?: string | null
  session?: unknown
  openQuestions?: unknown
  candidates?: unknown
  messages?: unknown
  selectedHypothesisId?: unknown
  leaderboardUrl?: unknown
}): Promise<LocalHypothesisSession | null> {
  const sessionSource =
    args.session && typeof args.session === 'object'
      ? (args.session as Record<string, unknown>)
      : null

  const sessionId =
    asNullableString(args.sessionId) ||
    asNullableString(sessionSource?.session_id) ||
    asNullableString(sessionSource?.sessionId)

  if (!sessionId) return null

  const existing =
    (await getLocalHypothesisSessionPersisted(sessionId)) ||
    getOrCreateLocalHypothesisSession({ sessionId })

  const remoteContext =
    sessionSource?.context && typeof sessionSource.context === 'object'
      ? (sessionSource.context as Record<string, unknown>)
      : {}
  const openQuestionsRaw =
    args.openQuestions ??
    sessionSource?.open_questions ??
    sessionSource?.openQuestions ??
    null
  const candidatesRaw =
    args.candidates ??
    sessionSource?.candidates ??
    sessionSource?.hypotheses ??
    null
  const messagesRaw = args.messages ?? sessionSource?.messages ?? null

  const incomingOpenQuestions = Array.isArray(openQuestionsRaw)
    ? openQuestionsRaw
        .map((item, index) => normalizeRemoteOpenQuestion(item, index))
        .filter((item): item is LocalOpenQuestion => Boolean(item))
    : []
  const incomingCandidates = Array.isArray(candidatesRaw)
    ? candidatesRaw
        .map((item, index) => normalizeRemoteCandidate(item, index))
        .filter((item): item is LocalHypothesisCandidate => Boolean(item))
    : []
  const incomingMessages = Array.isArray(messagesRaw)
    ? messagesRaw
        .map((item) => normalizeMessage(item))
        .filter((item): item is HypothesisChatMessage => Boolean(item))
    : []

  const merged: LocalHypothesisSession = {
    ...existing,
    session_id: sessionId,
    context: {
      session_id: sessionId,
      dataset_id:
        asNullableString(remoteContext.dataset_id ?? remoteContext.datasetId) ??
        existing.context.dataset_id,
      concept_id:
        asNullableString(remoteContext.concept_id ?? remoteContext.conceptId) ??
        existing.context.concept_id,
      task_id:
        asNullableString(remoteContext.task_id ?? remoteContext.taskId) ?? existing.context.task_id,
      thread_id:
        asNullableString(remoteContext.thread_id ?? remoteContext.threadId) ??
        existing.context.thread_id,
    },
    open_questions: incomingOpenQuestions.length
      ? mergeById(existing.open_questions, incomingOpenQuestions)
      : existing.open_questions,
    candidates: incomingCandidates.length
      ? mergeById(existing.candidates, incomingCandidates)
      : existing.candidates,
    messages: mergeMessages(existing.messages, incomingMessages),
    selected_hypothesis_id:
      asNullableString(args.selectedHypothesisId) ||
      asNullableString(sessionSource?.selected_hypothesis_id) ||
      asNullableString(sessionSource?.selectedHypothesisId) ||
      existing.selected_hypothesis_id,
    leaderboard_url:
      asNullableString(args.leaderboardUrl) ||
      asNullableString(sessionSource?.leaderboard_url) ||
      asNullableString(sessionSource?.leaderboardUrl) ||
      existing.leaderboard_url,
    updated_at: asIsoOrNow(sessionSource?.updated_at ?? sessionSource?.updatedAt),
  }

  getStore().sessions.set(merged.session_id, merged)
  persistSession(merged)
  return merged
}

export function appendLocalHypothesisMessage(args: {
  sessionId: string
  role: HypothesisChatMessage['role']
  content: string
  timestamp?: string | null
}): HypothesisChatMessage | null {
  const session = getOrCreateLocalHypothesisSession({ sessionId: args.sessionId })
  const content = args.content.trim()
  if (!content) return null

  const message: HypothesisChatMessage = {
    id: makeId('msg'),
    role: normalizeMessageRole(args.role),
    content,
    timestamp: asNullableString(args.timestamp) || nowIso(),
  }

  session.messages = [...session.messages, message]
  session.updated_at = nowIso()
  getStore().sessions.set(session.session_id, session)
  persistSession(session)
  return message
}

export function exploreLocalHypothesisSession(args: {
  sessionId: string
  openQuestionId?: string | null
  nCandidates?: number | null
}) {
  const store = getStore()
  const session = getOrCreateLocalHypothesisSession({ sessionId: args.sessionId })
  const count = Math.max(1, Math.min(16, Math.trunc(args.nCandidates || 10)))
  const questionId = asNullableString(args.openQuestionId)

  const generated = Array.from({ length: count }).map((_, index) =>
    buildCandidate(index, questionId),
  )
  session.candidates = [...session.candidates, ...generated]
  session.selected_hypothesis_id = generated[0]?.id || session.selected_hypothesis_id
  session.updated_at = nowIso()
  store.sessions.set(session.session_id, session)
  persistSession(session)

  return {
    session,
    open_questions: session.open_questions,
    candidates: generated,
    message: `Generated ${generated.length} provisional hypotheses in local fallback mode.`,
  }
}

export function chatLocalHypothesisSession(args: {
  sessionId: string
  message: string
  selectedHypothesisId?: string | null
}) {
  const store = getStore()
  const session = getOrCreateLocalHypothesisSession({ sessionId: args.sessionId })
  const normalized = args.message.trim().toLowerCase()

  appendLocalHypothesisMessage({
    sessionId: session.session_id,
    role: 'user',
    content: args.message,
  })

  if (normalized.includes('explore')) {
    const explored = exploreLocalHypothesisSession({
      sessionId: session.session_id,
      openQuestionId: null,
      nCandidates: 3,
    })
    const reply =
      'Local fallback: generated 3 new hypotheses because remote hypothesis service is unavailable.'
    appendLocalHypothesisMessage({
      sessionId: session.session_id,
      role: 'assistant',
      content: reply,
    })
    return {
      ...explored,
      reply,
    }
  }

  const selectedId = asNullableString(args.selectedHypothesisId) || session.selected_hypothesis_id
  const selected = selectedId
    ? session.candidates.find((candidate) => candidate.id === selectedId) || null
    : null
  const reply = selected
    ? `Local fallback answer for "${selected.title}": focus on its MDE falsifier before running full batch.`
    : `Local fallback answer: session has ${session.candidates.length} hypotheses. Run Deep Research to generate more.`

  appendLocalHypothesisMessage({
    sessionId: session.session_id,
    role: 'assistant',
    content: reply,
  })

  session.updated_at = nowIso()
  store.sessions.set(session.session_id, session)
  persistSession(session)

  return {
    session,
    reply,
    candidates: [],
    open_questions: session.open_questions,
  }
}

export function runBatchLocalHypothesisSession(args: {
  sessionId: string
  hypothesisIds: string[]
}) {
  const store = getStore()
  const session = getOrCreateLocalHypothesisSession({ sessionId: args.sessionId })
  const run: LocalBatchRun = {
    run_id: makeId('run'),
    status: 'completed',
    queued_count: args.hypothesisIds.length,
    started_at: nowIso(),
    updated_at: nowIso(),
    leaderboard_url: null,
    session_id: session.session_id,
  }

  session.updated_at = nowIso()
  store.sessions.set(session.session_id, session)
  store.runs.set(run.run_id, run)
  persistSession(session)
  persistRun(run)

  return { run, session }
}

export function getLocalHypothesisRun(runId: string): LocalBatchRun | null {
  return getStore().runs.get(runId) || null
}

export async function getLocalHypothesisRunPersisted(runId: string): Promise<LocalBatchRun | null> {
  const normalizedRunId = (runId || '').trim()
  if (!normalizedRunId) return null

  const fromMemory = getStore().runs.get(normalizedRunId)
  if (fromMemory) return fromMemory
  return hydrateRunFromPersistence(normalizedRunId)
}

export function __resetHypothesisLocalMemoryStoreForTests(): void {
  globalThis.__brHypothesisLocalStore = {
    sessions: new Map<string, LocalHypothesisSession>(),
    runs: new Map<string, LocalBatchRun>(),
  }
}
