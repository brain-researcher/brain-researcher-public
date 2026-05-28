import type {
  HypothesisArtifactEnvelope,
  HypothesisIntentSummary,
  HypothesisRunEvent,
  HypothesisRunSnapshot,
  HypothesisRunState,
  ResearchGoal,
  ResearchModality,
} from '@/types/hypothesis'
import {
  loadHypothesisStoreRecord,
  persistHypothesisStoreRecord,
} from '@/lib/server/hypothesis-persistence'

type SessionIntentMemory = {
  turns: number
  summary: HypothesisIntentSummary
}

type StoredRun = {
  run_id: string
  session_id: string
  state: HypothesisRunState
  intent_summary: HypothesisIntentSummary
  started_at: string
  updated_at: string
  done: boolean
  error_message: string | null
  events: HypothesisRunEvent[]
  artifacts: Map<string, HypothesisArtifactEnvelope>
  seq: number
}

type SessionRunIndex = {
  session_id: string
  run_ids: string[]
  updated_at: string
}

type HypothesisRunStore = {
  runs: Map<string, StoredRun>
  sessionRuns: Map<string, SessionRunIndex>
  sessionIntents: Map<string, SessionIntentMemory>
}

declare global {
  // eslint-disable-next-line no-var
  var __brHypothesisRunStore: HypothesisRunStore | undefined
}

const DEFAULT_INTENT_SUMMARY: HypothesisIntentSummary = {
  term: null,
  goal: null,
  modality: null,
  population: null,
  output_mode: null,
  intent_ready: false,
  missing_fields: ['term', 'goal_or_output_mode', 'dataset_or_modality_or_population'],
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeRunId(): string {
  return `hrun-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function cloneIntentSummary(summary: HypothesisIntentSummary): HypothesisIntentSummary {
  return {
    term: summary.term,
    goal: summary.goal || null,
    modality: summary.modality || null,
    population: summary.population || null,
    output_mode: summary.output_mode || null,
    intent_ready: Boolean(summary.intent_ready),
    missing_fields: [...summary.missing_fields],
  }
}

function normalizeMessage(message: string): string {
  return message
    .replace(/[“”"']/g, ' ')
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function sanitizeCapturedTerm(value: string): string {
  return value
    .replace(/[?.!,;:]+$/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripTermSuffixNoise(value: string): string {
  return value
    .replace(/\s+(?:and|with)\s+(?:their|its|the)?\s*evidence paths?$/i, '')
    .replace(/\s+(?:and|with)\s+(?:their|its|the)?\s*evidence$/i, '')
    .replace(/\s+(?:and|with)\s+(?:their|its|the)?\s*citations?$/i, '')
    .replace(/\s+(?:and|with)\s+(?:their|its|the)?\s*references?$/i, '')
    .replace(/\s+(?:and|with)\s+supporting papers?$/i, '')
    .trim()
}

function normalizeTermCandidate(value: string): string | null {
  const cleaned = stripTermSuffixNoise(sanitizeCapturedTerm(value))
  if (!cleaned) return null
  const words = cleaned.split(' ').filter(Boolean)
  if (words.length === 0) return null
  if (words.length > 12) {
    return words.slice(0, 12).join(' ')
  }
  return cleaned
}

function extractTerm(message: string): string | null {
  const normalized = normalizeMessage(message)
  if (!normalized) return null

  const patterns = [
    /(?:findings?|status|evidence|research)\s+(?:for|on|in|about)\s+([a-z][a-z0-9 -]{2,120})/i,
    /for ([a-z][a-z0-9 -]{2,120})/i,
    /recent research in ([a-z][a-z0-9 -]{2,80})/i,
    /research in ([a-z][a-z0-9 -]{2,80})/i,
    /research on ([a-z][a-z0-9 -]{2,80})/i,
    /about ([a-z][a-z0-9 -]{2,80})/i,
    /on ([a-z][a-z0-9 -]{2,80})/i,
    /in ([a-z][a-z0-9 -]{2,80})/i,
  ]

  for (const pattern of patterns) {
    const matched = normalized.match(pattern)
    if (matched?.[1]) {
      const candidate = normalizeTermCandidate(matched[1])
      if (candidate && candidate.split(' ').length <= 12) return candidate
    }
  }

  const tokens = normalized.split(' ')
  if (tokens.length <= 6) return normalizeTermCandidate(normalized)
  return null
}

function detectGoal(message: string): ResearchGoal | null {
  const text = message.toLowerCase()
  if (/replicat|contradict|controvers|dispute|generaliz|robust|inconsisten/.test(text)) {
    return 'replication_dispute'
  }
  if (/interven|stimulat|tms|drug|causal/.test(text)) return 'intervention_effect'
  if (/predict|classif|forecast|model|decod/.test(text)) return 'predictive_modeling'
  if (/mechanis|explain|why|pathway/.test(text)) return 'mechanism_explanation'
  return null
}

function detectModality(message: string): ResearchModality | null {
  const text = message.toLowerCase()
  if (/multimodal|multi-modal|multi modal/.test(text)) return 'multimodal'
  if (/fmri.*rest|rest.*fmri|resting/.test(text)) return 'fmri_rest'
  if (/fmri|bold/.test(text)) return 'fmri_task'
  if (/\beeg\b/.test(text)) return 'eeg'
  if (/behavior|questionnaire|survey/.test(text)) return 'behavioral'
  return null
}

function detectPopulation(message: string): string | null {
  const text = message.toLowerCase()
  if (/patient|clinical|disease|disorder/.test(text)) return 'clinical cohort'
  if (/child|adolescent|development/.test(text)) return 'developmental cohort'
  if (/healthy|control/.test(text)) return 'healthy adults'
  return null
}

function detectOutputMode(
  message: string,
): HypothesisIntentSummary['output_mode'] | null {
  const text = message.toLowerCase()
  if (/3|three|options|alternatives/.test(text)) return 'three_options'
  if (/single|best|one hypothesis/.test(text)) return 'single_best'
  if (/direct|plan|execute/.test(text)) return 'direct_plan'
  return null
}

function wantsDefault(message: string): boolean {
  const text = message.toLowerCase().trim()
  if (!text) return false
  return /\b(use default|default|go ahead|proceed)\b/.test(text) || /默认|直接开始|继续/.test(text)
}

function inferDefaultGoal(term: string | null): ResearchGoal {
  const text = (term || '').toLowerCase()
  if (/decod|classif|predict|model/.test(text)) return 'predictive_modeling'
  if (/interven|stimulat|causal|drug/.test(text)) return 'intervention_effect'
  if (/replicat|contradict|controvers/.test(text)) return 'replication_dispute'
  return 'mechanism_explanation'
}

function inferDefaultModality(term: string | null): ResearchModality {
  const text = (term || '').toLowerCase()
  if (/\beeg\b/.test(text)) return 'eeg'
  if (/rest|resting/.test(text)) return 'fmri_rest'
  if (/multimodal|multi-modal|multi modal/.test(text)) return 'multimodal'
  return 'fmri_task'
}

function inferDefaultPopulation(term: string | null): string {
  const text = (term || '').toLowerCase()
  if (/patient|clinical|disease|disorder/.test(text)) return 'clinical cohort'
  return 'healthy adults'
}

function buildMissingFields(summary: HypothesisIntentSummary, hasDataset: boolean): string[] {
  const missing: string[] = []
  if (!summary.term) missing.push('term')
  if (!summary.goal && !summary.output_mode) missing.push('goal_or_output_mode')
  if (!hasDataset && !summary.modality && !summary.population) {
    missing.push('dataset_or_modality_or_population')
  }
  return missing
}

type DirectionOptionId = '1' | '2' | '3'
type DirectionPreset = {
  id: DirectionOptionId
  label: string
  goal: ResearchGoal
  modality: ResearchModality
  population: string
}
type ResearchLane =
  | 'decoding_predictive'
  | 'mechanism_explanatory'
  | 'intervention_causal'
  | 'replication_generalization'
  | 'clinical_translation'

type DynamicQuestion = {
  title: string
  question: string
  recommended: string
  rationale: string
}

function laneFromGoal(goal: ResearchGoal | null | undefined): ResearchLane | null {
  if (goal === 'predictive_modeling') return 'decoding_predictive'
  if (goal === 'mechanism_explanation') return 'mechanism_explanatory'
  if (goal === 'intervention_effect') return 'intervention_causal'
  if (goal === 'replication_dispute') return 'replication_generalization'
  return null
}

function classifyResearchLane(message: string, term: string | null): ResearchLane {
  const text = `${message} ${(term || '').toLowerCase()}`.toLowerCase()

  if (/patient|clinical|cohort|disease|disorder|diagnos|prognos|treatment response/.test(text)) {
    return 'clinical_translation'
  }
  if (/interven|stimulat|tms|drug|causal|sham|dose/.test(text)) {
    return 'intervention_causal'
  }
  if (/replicat|contradict|controvers|dispute|generaliz|robust|inconsisten/.test(text)) {
    return 'replication_generalization'
  }
  if (/mechanis|explain|why|pathway|circuit/.test(text)) {
    return 'mechanism_explanatory'
  }
  if (/decod|predict|classif|forecast|model|brain decoding/.test(text)) {
    return 'decoding_predictive'
  }
  return 'decoding_predictive'
}

function humanizeGoal(goal: ResearchGoal | null | undefined): string {
  if (goal === 'mechanism_explanation') return 'mechanism explanation'
  if (goal === 'predictive_modeling') return 'predictive modeling'
  if (goal === 'intervention_effect') return 'intervention effect'
  if (goal === 'replication_dispute') return 'replication/generalization'
  return 'unspecified'
}

function humanizeModality(modality: ResearchModality | null | undefined): string {
  if (modality === 'fmri_task') return 'fMRI task'
  if (modality === 'fmri_rest') return 'fMRI rest'
  if (modality === 'eeg') return 'EEG'
  if (modality === 'behavioral') return 'behavioral'
  if (modality === 'multimodal') return 'multimodal'
  return 'unspecified'
}

function safeTermLabel(term: string | null): string {
  if (!term || /[\u4e00-\u9fff]/.test(term)) return 'this topic'
  return term
}

function buildDirectionPresets(term: string | null, lane: ResearchLane): DirectionPreset[] {
  const topic = safeTermLabel(term)

  if (lane === 'intervention_causal') {
    return [
      {
        id: '1',
        label: `${topic}: sham-controlled TMS causal effect baseline`,
        goal: 'intervention_effect',
        modality: 'fmri_task',
        population: 'healthy adults',
      },
      {
        id: '2',
        label: `${topic}: dose-response intervention test`,
        goal: 'intervention_effect',
        modality: 'multimodal',
        population: 'healthy adults',
      },
      {
        id: '3',
        label: `${topic}: clinical responder-stratified causal check`,
        goal: 'replication_dispute',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
    ]
  }

  if (lane === 'replication_generalization') {
    return [
      {
        id: '1',
        label: `${topic}: direct replication under matched protocol`,
        goal: 'replication_dispute',
        modality: 'fmri_task',
        population: 'healthy adults',
      },
      {
        id: '2',
        label: `${topic}: cross-dataset generalization stress test`,
        goal: 'replication_dispute',
        modality: 'multimodal',
        population: 'healthy adults',
      },
      {
        id: '3',
        label: `${topic}: contradiction-resolution via subgroup stratification`,
        goal: 'replication_dispute',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
    ]
  }

  if (lane === 'mechanism_explanatory') {
    return [
      {
        id: '1',
        label: `${topic}: task-evoked mechanism hypothesis`,
        goal: 'mechanism_explanation',
        modality: 'fmri_task',
        population: 'healthy adults',
      },
      {
        id: '2',
        label: `${topic}: resting-state circuit mechanism check`,
        goal: 'mechanism_explanation',
        modality: 'fmri_rest',
        population: 'healthy adults',
      },
      {
        id: '3',
        label: `${topic}: multimodal mechanism transfer in clinical cohort`,
        goal: 'mechanism_explanation',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
    ]
  }

  if (lane === 'clinical_translation') {
    return [
      {
        id: '1',
        label: `${topic}: clinical biomarker discrimination baseline`,
        goal: 'predictive_modeling',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
      {
        id: '2',
        label: `${topic}: treatment-response prediction baseline`,
        goal: 'predictive_modeling',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
      {
        id: '3',
        label: `${topic}: mechanism-grounded subgroup interpretation`,
        goal: 'mechanism_explanation',
        modality: 'multimodal',
        population: 'clinical cohort',
      },
    ]
  }

  return [
    {
      id: '1',
      label: `${topic}: cross-subject fMRI decoding baseline`,
      goal: 'predictive_modeling',
      modality: 'fmri_task',
      population: 'healthy adults',
    },
    {
      id: '2',
      label: `${topic}: EEG temporal decoding transfer`,
      goal: 'predictive_modeling',
      modality: 'eeg',
      population: 'healthy adults',
    },
    {
      id: '3',
      label: `${topic}: multimodal/clinical robustness check`,
      goal: 'replication_dispute',
      modality: 'multimodal',
      population: 'clinical cohort',
    },
  ]
}

function detectDirectionChoice(message: string): DirectionOptionId | null {
  const text = message.toLowerCase().trim()
  if (!text) return null
  if (/^[123]$/.test(text)) return text as DirectionOptionId

  const english = text.match(/\b(option|direction|lane|pick|choose)\s*([123])\b/)
  if (english?.[2]) return english[2] as DirectionOptionId

  const chinese = text.match(/(?:方向|选|選|方案)\s*([123])/)
  if (chinese?.[1]) return chinese[1] as DirectionOptionId

  return null
}

function buildDynamicQuestions(
  summary: HypothesisIntentSummary,
  lane: ResearchLane,
): DynamicQuestion[] {
  const topic = safeTermLabel(summary.term)
  const recommendedGoal = humanizeGoal(summary.goal || inferDefaultGoal(summary.term))
  const recommendedModality = humanizeModality(summary.modality || inferDefaultModality(summary.term))
  const recommendedPopulation = summary.population || inferDefaultPopulation(summary.term)

  if (lane === 'intervention_causal') {
    return [
      {
        title: 'Objective framing',
        question: `For ${topic}, do you want a sham-controlled causal estimate, dose-response characterization, or subgroup treatment heterogeneity?`,
        recommended: 'sham-controlled causal estimate first',
        rationale: 'A clean causal baseline prevents over-interpreting correlational gains.',
      },
      {
        title: 'Data and modality',
        question: 'Will we anchor on fMRI task, multimodal intervention readouts, or EEG + behavioral response curves?',
        recommended: `${recommendedModality}`,
        rationale: 'Modality choice sets both effect observability and implementation cost.',
      },
      {
        title: 'Population boundary',
        question: 'Should we start with healthy adults, clinical cohort, or both with stratified analysis?',
        recommended: `${recommendedPopulation}`,
        rationale: 'Population scope determines confound burden and minimum sample requirements.',
      },
      {
        title: 'Evaluation priority',
        question: 'Which failure mode should we optimize against first: sham leakage, confound imbalance, or weak responder signal?',
        recommended: 'sham leakage control',
        rationale: 'Intervention claims fail most often on inadequate control design.',
      },
    ]
  }

  if (lane === 'replication_generalization') {
    return [
      {
        title: 'Objective framing',
        question: `For ${topic}, is the main goal direct replication, contradiction resolution, or cross-dataset generalization?`,
        recommended: 'contradiction resolution with explicit boundary conditions',
        rationale: 'Boundary conditions convert disagreement into testable structure.',
      },
      {
        title: 'Data and modality',
        question: 'Should we match the original modality exactly, or stress-test transfer across modalities/cohorts?',
        recommended: `${recommendedModality}`,
        rationale: 'Modality alignment decides whether we test reproducibility or transportability.',
      },
      {
        title: 'Population boundary',
        question: 'Do you want one homogeneous cohort first, or immediate subgroup-stratified comparisons?',
        recommended: `${recommendedPopulation}`,
        rationale: 'Subgroup effects are a common reason for conflicting findings.',
      },
      {
        title: 'Evaluation priority',
        question: 'Prioritize protocol harmonization, sample-size power, or out-of-distribution robustness?',
        recommended: 'protocol harmonization',
        rationale: 'Replication collapses without comparable protocol assumptions.',
      },
    ]
  }

  if (lane === 'mechanism_explanatory') {
    return [
      {
        title: 'Objective framing',
        question: `For ${topic}, do you want a mechanistic account, a mediation-style proxy, or a descriptive association map?`,
        recommended: `${recommendedGoal}`,
        rationale: 'Mechanistic scope determines what counts as explanatory evidence.',
      },
      {
        title: 'Data and modality',
        question: 'Should we prioritize task-evoked fMRI, resting-state circuitry, or multimodal triangulation?',
        recommended: `${recommendedModality}`,
        rationale: 'Mechanism claims need modality-specific observables, not generic correlations.',
      },
      {
        title: 'Population boundary',
        question: 'Focus on healthy adults first or include clinical variability from the start?',
        recommended: `${recommendedPopulation}`,
        rationale: 'Population heterogeneity can mask or fabricate mechanism patterns.',
      },
      {
        title: 'Evaluation priority',
        question: 'What matters most first: confound control, mechanistic specificity, or reproducibility across tasks?',
        recommended: 'mechanistic specificity',
        rationale: 'Without specificity, mechanism claims degrade into pattern matching.',
      },
    ]
  }

  if (lane === 'clinical_translation') {
    return [
      {
        title: 'Objective framing',
        question: `For ${topic}, are we targeting diagnostic discrimination, prognosis, or treatment-response prediction?`,
        recommended: 'diagnostic discrimination with external validation',
        rationale: 'A constrained clinical endpoint keeps the first pass testable.',
      },
      {
        title: 'Data and modality',
        question: 'Should we use clinically available modality only, or allow multimodal features for stronger signal?',
        recommended: `${recommendedModality}`,
        rationale: 'Clinical deployability trades off with raw predictive signal.',
      },
      {
        title: 'Population boundary',
        question: 'Which cohort is primary: one diagnosis, transdiagnostic sample, or matched control + patient?',
        recommended: `${recommendedPopulation}`,
        rationale: 'Cohort definition controls label quality and transport risk.',
      },
      {
        title: 'Evaluation priority',
        question: 'Prioritize external validation, calibration/fairness, or clinical utility thresholding?',
        recommended: 'external validation',
        rationale: 'Most clinical models fail on site transfer rather than in-sample metrics.',
      },
    ]
  }

  return [
    {
      title: 'Objective framing',
      question: `For ${topic}, are you optimizing cross-subject generalization, in-dataset accuracy, or deployment calibration?`,
      recommended: 'cross-subject generalization',
      rationale: 'Generalization-first framing avoids leaderboard-only claims.',
    },
    {
      title: 'Data and modality',
      question: 'Should we anchor on fMRI task decoding, fMRI rest, EEG temporal decoding, or multimodal fusion?',
      recommended: `${recommendedModality}`,
      rationale: 'Modality selection defines what evidence can be compared apples-to-apples.',
    },
    {
      title: 'Population boundary',
      question: 'Do you want healthy adults first, or immediate clinical/subgroup coverage?',
      recommended: `${recommendedPopulation}`,
      rationale: 'Population scope controls variance and contradiction risk.',
    },
    {
      title: 'Evaluation priority',
      question: 'Which risk should we minimize first: leakage, cross-cohort robustness, or calibration drift?',
      recommended: 'leakage control',
      rationale: 'Leakage is the fastest way to produce misleading decoding claims.',
    },
  ]
}

function buildClarifyingQuestion(
  summary: HypothesisIntentSummary,
  lane: ResearchLane,
): string {
  const termLabel = safeTermLabel(summary.term)
  const questions = buildDynamicQuestions(summary, lane)
  const presets = buildDirectionPresets(summary.term, lane)
  const questionBlocks = questions
    .map((item, index) => {
      return `${index + 1}) ${item.title}: ${item.question}\nRecommended: ${item.recommended}\nWhy this matters: ${item.rationale}`
    })
    .join('\n\n')
  const shortcut = `Optional shortcut: reply 1/2/3 for preset lanes: ${presets.map((item) => `${item.id}) ${item.label}`).join('; ')}`
  return [
    `Let me tighten the scope for term=${termLabel} with 4 quick decisions:`,
    '',
    questionBlocks,
    '',
    'Reply in one line: objective=..., modality=..., population=..., priority=...',
    shortcut,
  ].join('\n')
}

function buildIntentReadyMessage(summary: HypothesisIntentSummary): string {
  const goal = humanizeGoal(summary.goal)
  const modality = humanizeModality(summary.modality)
  const population = summary.population || 'unspecified'
  const termLabel = safeTermLabel(summary.term)
  return `Intent locked: term=${termLabel}, goal=${goal}, modality=${modality}, population=${population}. Starting deep research + KG comparison now.`
}

function getStore(): HypothesisRunStore {
  if (!globalThis.__brHypothesisRunStore) {
    globalThis.__brHypothesisRunStore = {
      runs: new Map<string, StoredRun>(),
      sessionRuns: new Map<string, SessionRunIndex>(),
      sessionIntents: new Map<string, SessionIntentMemory>(),
    }
  }
  return globalThis.__brHypothesisRunStore
}

type PersistedRunRecord = {
  run_id: string
  session_id: string
  state: HypothesisRunState
  intent_summary: HypothesisIntentSummary
  started_at: string
  updated_at: string
  done: boolean
  error_message: string | null
  events: HypothesisRunEvent[]
  artifacts: HypothesisArtifactEnvelope[]
  seq: number
}

type PersistedSessionRunIndex = {
  session_id: string
  run_ids: string[]
  updated_at: string
}

function toPersistedRun(run: StoredRun): PersistedRunRecord {
  return {
    run_id: run.run_id,
    session_id: run.session_id,
    state: run.state,
    intent_summary: cloneIntentSummary(run.intent_summary),
    started_at: run.started_at,
    updated_at: run.updated_at,
    done: run.done,
    error_message: run.error_message,
    events: [...run.events],
    artifacts: Array.from(run.artifacts.values()),
    seq: run.seq,
  }
}

function fromPersistedRun(raw: PersistedRunRecord): StoredRun {
  return {
    run_id: raw.run_id,
    session_id: raw.session_id,
    state: raw.state,
    intent_summary: cloneIntentSummary(raw.intent_summary),
    started_at: raw.started_at,
    updated_at: raw.updated_at,
    done: Boolean(raw.done),
    error_message: raw.error_message || null,
    events: Array.isArray(raw.events) ? raw.events : [],
    artifacts: new Map(
      (Array.isArray(raw.artifacts) ? raw.artifacts : []).map((artifact) => [artifact.id, artifact]),
    ),
    seq: Number.isFinite(raw.seq) ? Math.max(0, Math.trunc(raw.seq)) : 0,
  }
}

function normalizeSessionRunIndex(
  raw: PersistedSessionRunIndex | SessionRunIndex,
  fallbackSessionId: string,
): SessionRunIndex {
  const sessionId =
    (typeof (raw as any)?.session_id === 'string' && (raw as any).session_id.trim()) ||
    fallbackSessionId
  const runIds: string[] = Array.isArray((raw as any)?.run_ids)
    ? (raw as any).run_ids
        .filter((item: unknown): item is string => typeof item === 'string')
        .map((item: string) => item.trim())
        .filter(Boolean)
    : []
  const deduped: string[] = Array.from(new Set<string>(runIds)).slice(-500)
  return {
    session_id: sessionId,
    run_ids: deduped,
    updated_at:
      (typeof (raw as any)?.updated_at === 'string' && (raw as any).updated_at.trim()) || nowIso(),
  }
}

function persistIntentMemory(sessionId: string, memory: SessionIntentMemory): void {
  persistHypothesisStoreRecord('run_store_intent', sessionId, memory)
}

function persistRunRecord(run: StoredRun): void {
  persistHypothesisStoreRecord('run_store_run', run.run_id, toPersistedRun(run))
}

function persistSessionRunIndex(index: SessionRunIndex): void {
  persistHypothesisStoreRecord('run_store_session_runs', index.session_id, index)
}

function indexRunForSession(run: StoredRun, persist = true): void {
  const sessionId = run.session_id.trim()
  if (!sessionId) return

  const store = getStore()
  const existing = store.sessionRuns.get(sessionId)
  const previous = existing?.run_ids || []
  const nextRunIds = Array.from(new Set([...previous, run.run_id])).slice(-500)
  const nextIndex: SessionRunIndex = {
    session_id: sessionId,
    run_ids: nextRunIds,
    updated_at: nowIso(),
  }
  store.sessionRuns.set(sessionId, nextIndex)
  if (persist) persistSessionRunIndex(nextIndex)
}

async function hydrateIntentMemory(sessionId: string): Promise<SessionIntentMemory | null> {
  const normalizedSessionId = sessionId.trim()
  if (!normalizedSessionId) return null

  const store = getStore()
  const existing = store.sessionIntents.get(normalizedSessionId)
  if (existing) return existing

  const persisted = await loadHypothesisStoreRecord<SessionIntentMemory>(
    'run_store_intent',
    normalizedSessionId,
  )
  if (!persisted || typeof persisted !== 'object') return null

  const hydrated: SessionIntentMemory = {
    turns:
      Number.isFinite((persisted as any).turns) && (persisted as any).turns >= 0
        ? Math.trunc((persisted as any).turns)
        : 0,
    summary: cloneIntentSummary(
      ((persisted as any).summary as HypothesisIntentSummary) || DEFAULT_INTENT_SUMMARY,
    ),
  }
  store.sessionIntents.set(normalizedSessionId, hydrated)
  return hydrated
}

async function hydrateRunRecord(runId: string): Promise<StoredRun | null> {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return null

  const store = getStore()
  const existing = store.runs.get(normalizedRunId)
  if (existing) return existing

  const persisted = await loadHypothesisStoreRecord<PersistedRunRecord>(
    'run_store_run',
    normalizedRunId,
  )
  if (!persisted || typeof persisted !== 'object') return null

  const run = fromPersistedRun(persisted)
  store.runs.set(run.run_id, run)
  indexRunForSession(run)
  return run
}

async function hydrateSessionRunIndex(sessionId: string): Promise<SessionRunIndex | null> {
  const normalizedSessionId = sessionId.trim()
  if (!normalizedSessionId) return null

  const store = getStore()
  const existing = store.sessionRuns.get(normalizedSessionId)
  if (existing) return existing

  const persisted = await loadHypothesisStoreRecord<PersistedSessionRunIndex>(
    'run_store_session_runs',
    normalizedSessionId,
  )
  if (!persisted || typeof persisted !== 'object') return null

  const index = normalizeSessionRunIndex(persisted, normalizedSessionId)
  store.sessionRuns.set(normalizedSessionId, index)
  return index
}

export function updateIntentSummary(args: {
  sessionId: string
  message: string
  hasDataset: boolean
}): {
  summary: HypothesisIntentSummary
  assistantMessage: string
} {
  const store = getStore()
  const existing = store.sessionIntents.get(args.sessionId)
  const previous = existing ? cloneIntentSummary(existing.summary) : cloneIntentSummary(DEFAULT_INTENT_SUMMARY)
  const message = normalizeMessage(args.message)

  const term = previous.term || extractTerm(message)
  const lane = laneFromGoal(previous.goal) || classifyResearchLane(message, term)
  const directionChoice = detectDirectionChoice(message)
  const directionPresets = buildDirectionPresets(term, lane)
  const selectedDirection = directionChoice
    ? directionPresets.find((item) => item.id === directionChoice) || null
    : null

  const goal = detectGoal(message) || selectedDirection?.goal || previous.goal
  const modality = detectModality(message) || selectedDirection?.modality || previous.modality
  const population = detectPopulation(message) || selectedDirection?.population || previous.population
  const outputMode = previous.output_mode || detectOutputMode(message)
  const acceptDefault = wantsDefault(message)

  const resolvedGoal = acceptDefault ? goal || inferDefaultGoal(term) : goal
  const resolvedModality = acceptDefault ? modality || inferDefaultModality(term) : modality
  const resolvedPopulation = acceptDefault ? population || inferDefaultPopulation(term) : population

  const next: HypothesisIntentSummary = {
    term,
    goal: resolvedGoal,
    modality: resolvedModality,
    population: resolvedPopulation,
    output_mode: outputMode,
    intent_ready: false,
    missing_fields: [],
  }

  next.missing_fields = buildMissingFields(next, args.hasDataset)
  next.intent_ready = next.missing_fields.length === 0

  store.sessionIntents.set(args.sessionId, {
    turns: (existing?.turns || 0) + 1,
    summary: cloneIntentSummary(next),
  })
  persistIntentMemory(args.sessionId, {
    turns: (existing?.turns || 0) + 1,
    summary: cloneIntentSummary(next),
  })

  const assistantMessage = next.intent_ready
    ? buildIntentReadyMessage(next)
    : buildClarifyingQuestion(next, lane)

  return {
    summary: next,
    assistantMessage,
  }
}

export function createRun(args: {
  sessionId: string
  state: HypothesisRunState
  intentSummary: HypothesisIntentSummary
}): StoredRun {
  const store = getStore()
  const run: StoredRun = {
    run_id: makeRunId(),
    session_id: args.sessionId,
    state: args.state,
    intent_summary: cloneIntentSummary(args.intentSummary),
    started_at: nowIso(),
    updated_at: nowIso(),
    done: false,
    error_message: null,
    events: [],
    artifacts: new Map<string, HypothesisArtifactEnvelope>(),
    seq: 0,
  }
  store.runs.set(run.run_id, run)
  indexRunForSession(run)
  persistRunRecord(run)
  return run
}

function appendRunEvent<T extends HypothesisRunEvent['type']>(
  run: StoredRun,
  type: T,
  payload: Extract<HypothesisRunEvent, { type: T }>['payload'],
): Extract<HypothesisRunEvent, { type: T }> {
  run.seq += 1
  run.updated_at = nowIso()
  const event = {
    type,
    run_id: run.run_id,
    seq: run.seq,
    ts: run.updated_at,
    payload,
  } as Extract<HypothesisRunEvent, { type: T }>
  run.events.push(event)
  persistRunRecord(run)
  return event
}

export function emitRunState(runId: string, state: HypothesisRunState, message?: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  run.state = state
  appendRunEvent(run, 'run_state', { state, message })
}

export function emitAssistantMessage(runId: string, content: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  appendRunEvent(run, 'assistant_message', { content })
}

export function emitStage(
  runId: string,
  stageName: string,
  message: string,
  progress?: number,
): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  appendRunEvent(run, 'stage', {
    stage_name: stageName,
    message,
    progress,
  })
}

export function emitMetric(runId: string, name: string, value: number, unit?: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  appendRunEvent(run, 'metric', { name, value, unit })
}

export function upsertArtifact(
  runId: string,
  artifact: Omit<HypothesisArtifactEnvelope, 'updated_at'> & { updated_at?: string },
): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  const next: HypothesisArtifactEnvelope = {
    ...artifact,
    updated_at: artifact.updated_at || nowIso(),
  }
  run.artifacts.set(next.id, next)
  appendRunEvent(run, 'artifact_upsert', { artifact: next })
}

export function markRunFailed(runId: string, message: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  run.state = 'failed'
  run.error_message = message
  run.done = true
  appendRunEvent(run, 'error', { message })
  appendRunEvent(run, 'done', {
    summary: 'Run failed before producing complete artifacts.',
    final_state: 'failed',
  })
}

export function markRunCompleted(runId: string, summary: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  run.state = 'completed'
  run.done = true
  appendRunEvent(run, 'done', {
    summary,
    final_state: 'completed',
  })
}

export function markRunClarifying(runId: string, summary: string): void {
  const run = getStore().runs.get(runId)
  if (!run) return
  run.state = 'clarifying'
  run.done = true
  appendRunEvent(run, 'done', {
    summary,
    final_state: 'clarifying',
  })
}

export function getRunSnapshot(runId: string): HypothesisRunSnapshot | null {
  const run = getStore().runs.get(runId)
  if (!run) return null
  return {
    run_id: run.run_id,
    session_id: run.session_id,
    state: run.state,
    intent_summary: cloneIntentSummary(run.intent_summary),
    started_at: run.started_at,
    updated_at: run.updated_at,
    done: run.done,
    error_message: run.error_message,
    artifacts: Array.from(run.artifacts.values()),
  }
}

export function getRunEventsSince(runId: string, seq: number): HypothesisRunEvent[] {
  const run = getStore().runs.get(runId)
  if (!run) return []
  return run.events.filter((event) => event.seq > seq)
}

export function getStoredRunState(runId: string): {
  state: HypothesisRunState
  done: boolean
  run_id: string
} | null {
  const run = getStore().runs.get(runId)
  if (!run) return null
  return {
    state: run.state,
    done: run.done,
    run_id: run.run_id,
  }
}

export async function updateIntentSummaryPersisted(args: {
  sessionId: string
  message: string
  hasDataset: boolean
}): Promise<{
  summary: HypothesisIntentSummary
  assistantMessage: string
}> {
  await hydrateIntentMemory(args.sessionId)
  return updateIntentSummary(args)
}

export async function getRunSnapshotPersisted(
  runId: string,
): Promise<HypothesisRunSnapshot | null> {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return null
  const fromMemory = getRunSnapshot(normalizedRunId)
  if (fromMemory) return fromMemory

  const hydrated = await hydrateRunRecord(normalizedRunId)
  if (!hydrated) return null
  return getRunSnapshot(hydrated.run_id)
}

export async function getRunEventsSincePersisted(
  runId: string,
  seq: number,
): Promise<HypothesisRunEvent[]> {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return []
  const fromMemory = getRunEventsSince(normalizedRunId, seq)
  if (fromMemory.length) return fromMemory

  const hydrated = await hydrateRunRecord(normalizedRunId)
  if (!hydrated) return []
  return getRunEventsSince(hydrated.run_id, seq)
}

export async function getStoredRunStatePersisted(runId: string): Promise<{
  state: HypothesisRunState
  done: boolean
  run_id: string
} | null> {
  const normalizedRunId = runId.trim()
  if (!normalizedRunId) return null
  const fromMemory = getStoredRunState(normalizedRunId)
  if (fromMemory) return fromMemory

  const hydrated = await hydrateRunRecord(normalizedRunId)
  if (!hydrated) return null
  return getStoredRunState(hydrated.run_id)
}

export async function getRunSnapshotsForSessionPersisted(args: {
  sessionId: string
  limit?: number
}): Promise<HypothesisRunSnapshot[]> {
  const sessionId = args.sessionId.trim()
  if (!sessionId) return []

  const limit = Number.isFinite(args.limit) ? Math.max(1, Math.trunc(args.limit as number)) : 20
  const store = getStore()

  await hydrateSessionRunIndex(sessionId)

  const knownRunIds = new Set<string>()
  const indexed = store.sessionRuns.get(sessionId)?.run_ids || []
  for (const runId of indexed) knownRunIds.add(runId)

  // Backfill in-memory runs that may exist before index migration.
  Array.from(store.runs.values()).forEach((run) => {
    if (run.session_id === sessionId) {
      knownRunIds.add(run.run_id)
      indexRunForSession(run)
    }
  })

  const snapshots: HypothesisRunSnapshot[] = []
  for (const runId of Array.from(knownRunIds)) {
    const snapshot = await getRunSnapshotPersisted(runId)
    if (!snapshot || snapshot.session_id !== sessionId) continue
    snapshots.push(snapshot)
  }

  snapshots.sort((left, right) => {
    const l = Date.parse(left.updated_at || left.started_at || '')
    const r = Date.parse(right.updated_at || right.started_at || '')
    return (Number.isFinite(r) ? r : 0) - (Number.isFinite(l) ? l : 0)
  })

  return snapshots.slice(0, limit)
}

export function __resetHypothesisRunStoreForTests(): void {
  globalThis.__brHypothesisRunStore = {
    runs: new Map<string, StoredRun>(),
    sessionRuns: new Map<string, SessionRunIndex>(),
    sessionIntents: new Map<string, SessionIntentMemory>(),
  }
}
