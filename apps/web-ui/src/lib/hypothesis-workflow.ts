import type {
  BlockedReport,
  CandidateGroundingStatus,
  ClarifyQuestion,
  DirectionCandidate,
  EvidenceQualityTier,
  EvidenceAnchor,
  HypothesisCanvas,
  HypothesisEvidenceItem,
  PlanPatchResult,
  ResearchGoal,
  ResearchModality,
  ResearchPreview,
  ValidationFailureCode,
  ValidationReport,
  ValidationTriage,
  ValidationTriageStatus,
  WorkflowPlan,
} from '@/types/hypothesis'

export type WorkflowContextInput = {
  dataset_id?: string | null
  concept_id?: string | null
  task_id?: string | null
}

export type ClarifyAnswers = Record<string, string>

const GOAL_OPTIONS: Array<{ id: ResearchGoal; label: string }> = [
  { id: 'mechanism_explanation', label: 'Mechanism explanation' },
  { id: 'predictive_modeling', label: 'Predictive model' },
  { id: 'intervention_effect', label: 'Intervention effect' },
  { id: 'replication_dispute', label: 'Replication dispute' },
]

const MODALITY_OPTIONS: Array<{ id: ResearchModality; label: string }> = [
  { id: 'fmri_task', label: 'fMRI task' },
  { id: 'fmri_rest', label: 'fMRI rest' },
  { id: 'eeg', label: 'EEG' },
  { id: 'behavioral', label: 'Behavioral only' },
  { id: 'multimodal', label: 'Multimodal' },
]

const POPULATION_OPTIONS = [
  { id: 'healthy_adults', label: 'Healthy adults' },
  { id: 'clinical_cohort', label: 'Clinical cohort' },
  { id: 'developmental', label: 'Developmental cohort' },
]

const OUTPUT_OPTIONS = [
  { id: 'three_options', label: '3 alternatives to compare' },
  { id: 'single_best', label: 'Single strongest hypothesis' },
  { id: 'direct_plan', label: 'Directly to executable plan' },
]

const goalLabel = (goal: ResearchGoal): string =>
  GOAL_OPTIONS.find((option) => option.id === goal)?.label || 'Research goal'

const modalityLabel = (modality: ResearchModality): string =>
  MODALITY_OPTIONS.find((option) => option.id === modality)?.label || 'Modality'

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

function sentence(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
}

function inferModality(term: string): ResearchModality {
  const lower = term.toLowerCase()
  if (lower.includes('rest')) return 'fmri_rest'
  if (lower.includes('eeg')) return 'eeg'
  if (lower.includes('behavior')) return 'behavioral'
  if (lower.includes('multi')) return 'multimodal'
  return 'fmri_task'
}

function inferGoal(term: string): ResearchGoal {
  const lower = term.toLowerCase()
  if (lower.includes('replicat') || lower.includes('controvers')) return 'replication_dispute'
  if (lower.includes('interven') || lower.includes('stim')) return 'intervention_effect'
  if (lower.includes('predict') || lower.includes('classif')) return 'predictive_modeling'
  return 'mechanism_explanation'
}

function buildResearchQuestion(args: {
  term: string
  goal: ResearchGoal
  modality: ResearchModality
  population: string
}): string {
  const population = args.population.replace(/_/g, ' ')
  switch (args.goal) {
    case 'predictive_modeling':
      return `Which modeling and validation conditions make ${args.term} decoding robust in ${modalityLabel(args.modality)} for ${population}?`
    case 'intervention_effect':
      return `Under which intervention conditions does ${args.term} causally shift ${population} outcomes in ${modalityLabel(args.modality)}?`
    case 'replication_dispute':
      return `What design choices explain why ${args.term} findings replicate in some ${population} cohorts but fail in others?`
    case 'mechanism_explanation':
    default:
      return `Which mechanistic pathway best explains how ${args.term} changes measurable outcomes in ${modalityLabel(args.modality)} for ${population}?`
  }
}

export function buildClarifyQuestions(term: string): ClarifyQuestion[] {
  const normalizedTerm = sentence(term) || 'this topic'

  return [
    {
      id: 'goal',
      prompt: `What do you want to explain about ${normalizedTerm}?`,
      options: GOAL_OPTIONS.map((option) => ({ id: option.id, label: option.label })),
    },
    {
      id: 'modality',
      prompt: 'Which data modality should be primary?',
      options: MODALITY_OPTIONS.map((option) => ({ id: option.id, label: option.label })),
    },
    {
      id: 'population',
      prompt: 'Which population is your primary target?',
      options: POPULATION_OPTIONS,
    },
    {
      id: 'output_mode',
      prompt: 'What do you want from this round?',
      options: OUTPUT_OPTIONS,
    },
  ]
}

export function buildSuggestedCanvas(args: {
  term: string
  answers?: ClarifyAnswers
  context?: WorkflowContextInput
}): HypothesisCanvas {
  const term = sentence(args.term) || 'Unspecified topic'
  const answers = args.answers || {}

  const goal =
    (answers.goal as ResearchGoal) ||
    inferGoal(term)

  const modality =
    (answers.modality as ResearchModality) ||
    inferModality(term)

  const population =
    (answers.population || '').trim() ||
    'healthy_adults'

  const datasetHint = (args.context?.dataset_id || '').trim()
  const defaultConstraint = datasetHint
    ? `Prefer analyses compatible with dataset ${datasetHint}.`
    : 'Prefer publicly available datasets with transparent preprocessing metadata.'

  return {
    term,
    goal,
    modality,
    population,
    primary_outcome: `${term} effect on task-relevant neural signal`,
    constraints: defaultConstraint,
    research_question: buildResearchQuestion({
      term,
      goal,
      modality,
      population,
    }),
  }
}

export function normalizeCanvas(raw: Partial<HypothesisCanvas>, fallbackTerm?: string): HypothesisCanvas {
  const term = sentence(raw.term || fallbackTerm || 'Unspecified topic')
  const goal = (raw.goal as ResearchGoal) || inferGoal(term)
  const modality = (raw.modality as ResearchModality) || inferModality(term)

  return {
    term,
    goal,
    modality,
    population: sentence(raw.population || 'healthy_adults'),
    primary_outcome: sentence(raw.primary_outcome || `${term} related outcome`),
    constraints: sentence(raw.constraints || 'No extra constraints provided.'),
    research_question: sentence(raw.research_question || `How is ${term} linked to measurable outcomes?`),
  }
}

type KgNoveltyTasteContext = {
  structural_leverage?: string[]
  contradiction_motifs?: string[]
  ood_hypotheses?: string[]
  topology_shifts?: string[]
} | null

type KgCompareEvidenceContext = {
  prior_art_match?: string[]
  novelty_gap?: string[]
  feasibility_constraints?: string[]
  novelty_taste?: KgNoveltyTasteContext
  warnings?: string[]
} | null

export type CandidateEvidenceContext = {
  evidence?: HypothesisEvidenceItem[]
  kgCompare?: KgCompareEvidenceContext
  kgConcepts?: string[]
  deepResearchSummary?: string | null
  overlapThreshold?: number | null
  degenerateEvidence?: {
    degenerate: boolean
    reason?: string | null
    mode?: 'soft_keep_top1' | 'none'
  } | null
}

export type EvidenceFact = {
  id: string
  evidence_id: string
  text: string
  tokens: string[]
  source_channel: NonNullable<HypothesisEvidenceItem['source_channel']>
  quality_tier: EvidenceQualityTier
  traceability_score: number
  relevance: number
}

export type EvidenceFactCluster = {
  id: string
  fact_ids: string[]
  evidence_ids: string[]
  key_terms: string[]
  score: number
}

export type CandidateAnchorSource = 'kg' | 'evidence' | 'kg_compare' | 'hybrid'

export type CandidateGenerationMode =
  | 'evidence_first'
  | 'template_fallback'
  | 'template_diversified'

export type CandidateGenerationDiagnostics = {
  anchor_pool_size: number
  unique_anchor_dims: number
  pattern_reuse_count: number
  diversity_resample_count: number
  diversity_exhausted_slots: number
  qualifying_evidence_count: number
  distinct_qualifying_docs: number
}

export type GroundedDirectionCandidateBuildResult = {
  candidates: DirectionCandidate[]
  mode: CandidateGenerationMode
  facts: EvidenceFact[]
  clusters: EvidenceFactCluster[]
  diagnostics: CandidateGenerationDiagnostics
}

type CandidatePattern = {
  id: string
  title: string
  hypothesis: (canvas: HypothesisCanvas) => string
  independent_variable: (canvas: HypothesisCanvas) => string
  dependent_variable: (canvas: HypothesisCanvas) => string
  expected_signal: (canvas: HypothesisCanvas) => string
  likely_data_source: (canvas: HypothesisCanvas) => string
  novelty_gap: (canvas: HypothesisCanvas) => string
  risk_note: (canvas: HypothesisCanvas) => string
  taste_axis: string
  anchor_reason: string
}

export const HYPOTHESIS_DIRECTION_PATTERNS: ReadonlyArray<CandidatePattern> = [
  {
    id: 'bridge_disconnected_claims',
    title: 'Bridge disconnected claims',
    hypothesis: (canvas) =>
      `${canvas.term} effects differ across paradigms because existing studies mix incompatible task contexts.`,
    independent_variable: () => 'Task context / paradigm family',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Direction of effect flips when context-specific confounds are controlled.',
    likely_data_source: () => 'Public task-based benchmark cohorts with matched contrast definitions',
    novelty_gap: () => 'Connects previously separate task clusters under one conditional mechanism.',
    risk_note: () => 'Needs careful task harmonization to avoid pseudo-heterogeneity.',
    taste_axis: 'bridge_disconnected_regions',
    anchor_reason: 'Cross-paradigm evidence supports a context-conditional claim.',
  },
  {
    id: 'collapse_methodological_bottleneck',
    title: 'Collapse methodological bottleneck',
    hypothesis: (canvas) =>
      `Current ${canvas.term} findings are bottlenecked by one dominant preprocessing choice. Alternative pipelines could reveal stable effects.`,
    independent_variable: () => 'Preprocessing / modeling pipeline family',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Effect remains only in a subset of robust preprocessing choices.',
    likely_data_source: () => 'Datasets with reusable derivatives and reproducible processing logs',
    novelty_gap: () => 'Targets path-cost bottleneck in existing evidence graph.',
    risk_note: () => 'Can fail if pipeline metadata are incomplete.',
    taste_axis: 'collapse_path_bottleneck',
    anchor_reason: 'Method metadata indicates one dominant pipeline path.',
  },
  {
    id: 'resolve_contradiction_loop',
    title: 'Resolve contradiction loop',
    hypothesis: (canvas) =>
      `Conflicting ${canvas.term} claims are both conditionally correct when stratified by ${canvas.population}.`,
    independent_variable: () => 'Population stratification / subgroup assignment',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Opposing effects become coherent after subgroup-aware analysis.',
    likely_data_source: () => 'Cohorts with demographic and behavioral covariates',
    novelty_gap: () => 'Turns contradiction edge into conditional validity edge.',
    risk_note: () => 'Statistical power may be insufficient after stratification.',
    taste_axis: 'resolve_contradictions',
    anchor_reason: 'Prior-art conflict can be tested as conditional validity.',
  },
  {
    id: 'circular_validation_leak',
    title: 'Detect circular validation leak',
    hypothesis: (canvas) =>
      `${canvas.term} decoding gains are inflated when the same feature selection path is reused for validation.`,
    independent_variable: () => 'Feature-selection leakage versus strict separation',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Performance drops under strict nested validation but remains above chance.',
    likely_data_source: () => 'Studies with fold-level split definitions and full evaluation logs',
    novelty_gap: () => 'Tests whether reported gains are methodological leakage artifacts.',
    risk_note: () => 'Requires explicit split metadata that are often missing.',
    taste_axis: 'guard_against_spurious_gain',
    anchor_reason: 'Evaluation protocol details indicate possible leakage risk.',
  },
  {
    id: 'population_generalization_failure',
    title: 'Probe population generalization boundary',
    hypothesis: (canvas) =>
      `${canvas.term} effects learned in healthy adults fail to generalize uniformly across clinical or developmental cohorts.`,
    independent_variable: () => 'Population cohort type',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Model fit and effect direction vary systematically across cohorts.',
    likely_data_source: () => 'Multi-cohort datasets with harmonized covariates',
    novelty_gap: () => 'Identifies where external validity fails instead of averaging it away.',
    risk_note: () => 'Cross-cohort protocol mismatch can dominate observed differences.',
    taste_axis: 'external_validity_boundary',
    anchor_reason: 'Evidence includes multiple cohort profiles suitable for boundary testing.',
  },
  {
    id: 'measurement_invariance_gap',
    title: 'Audit measurement invariance',
    hypothesis: (canvas) =>
      `Studies labeled as ${canvas.term} are not measuring an invariant construct across tasks and acquisition settings.`,
    independent_variable: () => 'Task/acquisition definition variants',
    dependent_variable: () => 'Construct-level comparability score',
    expected_signal: () => 'Cross-study effect comparability drops after strict measurement matching.',
    likely_data_source: () => 'Task ontologies + studies with explicit protocol metadata',
    novelty_gap: () => 'Separates true contradiction from non-comparable measurement regimes.',
    risk_note: () => 'Requires richer metadata normalization across sources.',
    taste_axis: 'construct_invariance_audit',
    anchor_reason: 'Task mapping evidence indicates definition drift across studies.',
  },
  {
    id: 'effect_size_inflation_risk',
    title: 'Quantify effect-size inflation',
    hypothesis: (canvas) =>
      `${canvas.term} reported effects are inflated in small-sample studies and shrink in higher-powered cohorts.`,
    independent_variable: () => 'Sample size / power regime',
    dependent_variable: () => 'Effect size stability',
    expected_signal: () => 'Effect magnitude decays toward a stable estimate with increasing sample size.',
    likely_data_source: () => 'Meta-analytic evidence with study-level sample sizes',
    novelty_gap: () => 'Converts broad uncertainty into a power-aware effect model.',
    risk_note: () => 'Publication bias may still distort aggregate estimates.',
    taste_axis: 'power_aware_recalibration',
    anchor_reason: 'Evidence provides sample-size heterogeneity for shrinkage checks.',
  },
  {
    id: 'hrf_assumption_mismatch',
    title: 'Test HRF assumption mismatch',
    hypothesis: (canvas) =>
      `${canvas.term} conclusions depend on an HRF model assumption that does not hold across regions or cohorts.`,
    independent_variable: () => 'HRF model family / temporal basis',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Key effects attenuate or shift under alternative HRF assumptions.',
    likely_data_source: () => 'Task fMRI datasets with event timing and model specification access',
    novelty_gap: () => 'Makes latent model-assumption risk directly testable.',
    risk_note: () => 'Temporal model overfitting can mask true neural effects.',
    taste_axis: 'model_assumption_stress_test',
    anchor_reason: 'fMRI modeling evidence suggests sensitivity to HRF assumptions.',
  },
  {
    id: 'parcellation_dependence',
    title: 'Measure parcellation dependence',
    hypothesis: (canvas) =>
      `${canvas.term} network-level claims are unstable across atlas/parcellation choices.`,
    independent_variable: () => 'Atlas/parcellation family',
    dependent_variable: () => 'Network-level effect consistency',
    expected_signal: () => 'Core claims remain only for a subset of parcellation schemes.',
    likely_data_source: () => 'Pipelines with reproducible atlas switch support',
    novelty_gap: () => 'Adds an explicit robustness axis that many studies omit.',
    risk_note: () => 'Atlas choice may interact with smoothing and preprocessing settings.',
    taste_axis: 'representation_stability_check',
    anchor_reason: 'Graph evidence links results to multiple parcellation conventions.',
  },
  {
    id: 'motion_confound_underreporting',
    title: 'Stress-test motion confound controls',
    hypothesis: (canvas) =>
      `${canvas.term} effects are partially explained by under-controlled motion artifacts in one subgroup.`,
    independent_variable: () => 'Motion confound control strategy',
    dependent_variable: (canvas) => canvas.primary_outcome,
    expected_signal: () => 'Effect weakens after stricter motion exclusion and nuisance regression.',
    likely_data_source: () => 'Datasets exposing framewise displacement and QC metrics',
    novelty_gap: () => 'Turns hidden QC variability into an explicit falsification branch.',
    risk_note: () => 'Aggressive filtering may reduce usable sample size.',
    taste_axis: 'confound_sensitivity',
    anchor_reason: 'QC metadata indicates potential confound pressure on estimates.',
  },
  {
    id: 'minimum_discriminating_test',
    title: 'Minimum discriminating test first',
    hypothesis: (canvas) =>
      `A lightweight discriminating test can falsify weak ${canvas.term} explanations before expensive full analyses.`,
    independent_variable: () => 'Cheap proxy task / ablation condition',
    dependent_variable: () => 'Binary support vs falsification signal',
    expected_signal: () => 'One low-cost test removes at least one major competing claim.',
    likely_data_source: () => 'Small open datasets or precomputed summaries',
    novelty_gap: () => 'Optimizes information gain per unit compute budget.',
    risk_note: () => 'Proxy may under-represent final task complexity.',
    taste_axis: 'cheap_falsification_first',
    anchor_reason: 'Current evidence is sufficient to stage an early falsification gate.',
  },
  {
    id: 'structural_leverage_bridge',
    title: 'Target structural leverage bridges',
    hypothesis: (canvas) =>
      `A small set of under-connected ${canvas.term} nodes likely bridge currently disconnected claims and can yield higher information gain than adding more same-family analyses.`,
    independent_variable: () => 'Bridge candidate selection from structural leverage ranking',
    dependent_variable: () => 'Cross-cluster evidence connectivity and explanatory compression',
    expected_signal: () => 'Adding one bridge hypothesis reduces contradiction paths and improves cross-source coherence.',
    likely_data_source: () => 'Knowledge-graph neighborhood traversal plus matched task-fMRI contrasts',
    novelty_gap: () => 'Prioritizes high-leverage missing edges instead of broad low-yield searches.',
    risk_note: () => 'Bridge candidates can be unstable if ontology alignment is noisy.',
    taste_axis: 'bridge_disconnected_regions',
    anchor_reason: 'Structural leverage scan identifies candidate bridge nodes for targeted tests.',
  },
  {
    id: 'contradiction_motif_disambiguation',
    title: 'Disambiguate contradiction motifs',
    hypothesis: (canvas) =>
      `Conflicting ${canvas.term} findings are generated by repeatable contradiction motifs (task definition, cohort mix, or model choice) rather than random literature noise.`,
    independent_variable: () => 'Contradiction motif class',
    dependent_variable: () => 'Direction consistency after motif-aware stratification',
    expected_signal: () => 'Once motif class is controlled, support/refute polarity becomes more coherent.',
    likely_data_source: () => 'Publication-level claim polarity traces with task/cohort metadata',
    novelty_gap: () => 'Upgrades contradiction handling from anecdotal dispute to repeatable motif testing.',
    risk_note: () => 'Motif extraction can underperform when provenance metadata are sparse.',
    taste_axis: 'resolve_contradictions',
    anchor_reason: 'Contradiction motifs indicate where discriminating tests are most informative.',
  },
  {
    id: 'controlled_ood_hypothesis',
    title: 'Controlled OOD hypothesis search',
    hypothesis: (canvas) =>
      `Low-probability but structurally coherent ${canvas.term} hypotheses can outperform common in-distribution guesses when constrained by feasibility and mechanism consistency.`,
    independent_variable: () => 'Hypothesis search regime (in-distribution vs controlled OOD)',
    dependent_variable: () => 'Discriminability gain per unit evaluation cost',
    expected_signal: () => 'Controlled OOD proposals yield higher falsification efficiency than baseline templates.',
    likely_data_source: () => 'KG-guided OOD sampling plus low-cost validation datasets',
    novelty_gap: () => 'Converts novelty from random ideation into constrained graph search.',
    risk_note: () => 'OOD proposals may be harder to communicate without explicit mechanism traces.',
    taste_axis: 'controlled_ood_search',
    anchor_reason: 'OOD sampler proposes structurally coherent hypotheses outside routine search paths.',
  },
  {
    id: 'topology_shift_guardrail',
    title: 'Guard against topology shifts',
    hypothesis: (canvas) =>
      `When evidence topology shifts, previously stable ${canvas.term} conclusions can become brittle unless edge-weight updates are explicitly audited.`,
    independent_variable: () => 'Topology-shift-aware versus shift-agnostic interpretation',
    dependent_variable: () => 'Conclusion stability under edge-weight perturbation',
    expected_signal: () => 'Shift-aware auditing flags fragile claims before full pipeline escalation.',
    likely_data_source: () => 'Graph topology shift proposals with downstream robustness checks',
    novelty_gap: () => 'Adds change-detection guardrails to prevent stale reasoning on dynamic evidence graphs.',
    risk_note: () => 'Topology updates can over-penalize sparse areas if priors are not calibrated.',
    taste_axis: 'topology_shift_detection',
    anchor_reason: 'Topology-shift proposals identify where claim stability is most likely to flip.',
  },
]

function normalizeConfidence(value: number): number {
  return Math.max(0, Math.min(0.99, Number(value.toFixed(2))))
}

const DEFAULT_OVERLAP_THRESHOLD = 0.15
const DEFAULT_TEMPLATE_SIMILARITY_THRESHOLD = 0.75
const DEFAULT_TEMPLATE_MAX_RESAMPLE_PER_SLOT = 3
const DEFAULT_TEMPLATE_MAX_PATTERN_REUSE = 1
const TOKEN_STOPWORDS = new Set([
  'a',
  'an',
  'and',
  'are',
  'as',
  'at',
  'be',
  'because',
  'by',
  'for',
  'from',
  'how',
  'in',
  'is',
  'it',
  'of',
  'on',
  'or',
  'that',
  'the',
  'their',
  'this',
  'to',
  'under',
  'when',
  'which',
  'with',
])

const FACT_STOPWORDS = new Set([
  ...Array.from(TOKEN_STOPWORDS),
  'analysis',
  'approach',
  'based',
  'brain',
  'cohort',
  'decode',
  'decoding',
  'effect',
  'effects',
  'evidence',
  'findings',
  'fmri',
  'group',
  'model',
  'models',
  'paper',
  'papers',
  'participants',
  'results',
  'sample',
  'signal',
  'study',
  'studies',
  'task',
  'tasks',
])

function normalizeUnit(value: number): number {
  return Math.max(0, Math.min(1, Number(value.toFixed(2))))
}

function parseOverlapThreshold(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0.05, Math.min(0.95, value))
  }
  return DEFAULT_OVERLAP_THRESHOLD
}

function parseBoundedInt(value: unknown, fallback: number, min: number, max: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(min, Math.min(max, Math.trunc(value)))
  }
  return fallback
}

function parseBoundedFloat(value: unknown, fallback: number, min: number, max: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(min, Math.min(max, value))
  }
  return fallback
}

function buildCandidateMinimalTestText(args: {
  hypothesis: string
  independentVariable: string
  dependentVariable: string
  likelyDataSource: string
}): string {
  const iv = sentence(args.independentVariable || 'key predictor')
  const dv = sentence(args.dependentVariable || 'primary outcome')
  const ds = sentence(args.likelyDataSource || 'available benchmark data')
  return `Run a cheapest discriminating contrast in ${ds}: perturb ${iv} while holding other analysis choices fixed, then estimate directional change in ${dv}.`
}

function buildCandidateFalsifierHintText(args: {
  dependentVariable: string
  expectedSignal: string
}): string {
  const dv = sentence(args.dependentVariable || 'primary outcome')
  const signal = sentence(args.expectedSignal || 'predicted directional effect')
  return `Reject if ${dv} fails to show the predicted directional pattern (${signal}) after confound control and one competing hypothesis check.`
}

function tokenizeForOverlap(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(
      (token) =>
        token.length >= 3 && !TOKEN_STOPWORDS.has(token) && !/^\d+$/.test(token),
    )
}

function resolveQualityTier(item: HypothesisEvidenceItem): EvidenceQualityTier {
  if (
    item.quality_tier === 'primary' ||
    item.quality_tier === 'secondary' ||
    item.quality_tier === 'tertiary'
  ) {
    return item.quality_tier
  }
  if (item.traceability_score !== null && item.traceability_score !== undefined) {
    if (item.traceability_score >= 0.8) return 'primary'
    if (item.traceability_score >= 0.55) return 'secondary'
  }
  if (item.kind === 'dataset' && item.url) return 'primary'
  if (item.url && item.source_host) return 'secondary'
  return 'tertiary'
}

function resolveTraceabilityScore(item: HypothesisEvidenceItem, tier: EvidenceQualityTier): number {
  if (typeof item.traceability_score === 'number' && Number.isFinite(item.traceability_score)) {
    return normalizeUnit(item.traceability_score)
  }
  if (tier === 'primary') return 0.9
  if (tier === 'secondary') return 0.7
  return 0.45
}

function qualityWeight(tier: EvidenceQualityTier): number {
  if (tier === 'primary') return 1
  if (tier === 'secondary') return 0.7
  return 0.4
}

function semanticOverlapScore(claim: string, evidence: HypothesisEvidenceItem): number {
  const claimTokens = new Set(tokenizeForOverlap(claim))
  if (!claimTokens.size) return 0
  const evidenceText = [evidence.label, evidence.summary || '', evidence.source_host || '']
    .filter(Boolean)
    .join(' ')
  const evidenceTokens = new Set(tokenizeForOverlap(evidenceText))
  if (!evidenceTokens.size) return 0
  let overlap = 0
  claimTokens.forEach((token) => {
    if (evidenceTokens.has(token)) overlap += 1
  })
  const precision = overlap / evidenceTokens.size
  const recall = overlap / claimTokens.size
  if (precision <= 0 || recall <= 0) return 0
  return normalizeUnit((2 * precision * recall) / (precision + recall))
}

function termTokenSet(canvas: HypothesisCanvas): Set<string> {
  return new Set(
    [
      ...tokenizeForOverlap(canvas.term),
      ...tokenizeForOverlap(canvas.primary_outcome),
      ...tokenizeForOverlap(canvas.research_question),
    ],
  )
}

function splitFactSegments(value: string): string[] {
  return value
    .split(/[\n\r.;!?]+/)
    .map((segment) => segment.trim())
    .filter((segment) => segment.length >= 28)
}

function normalizeTokenSet(tokens: string[]): Set<string> {
  return new Set(tokens.filter((token) => !FACT_STOPWORDS.has(token)))
}

function jaccard(left: Set<string>, right: Set<string>): number {
  if (!left.size || !right.size) return 0
  let overlap = 0
  left.forEach((token) => {
    if (right.has(token)) overlap += 1
  })
  if (!overlap) return 0
  const union = left.size + right.size - overlap
  return union > 0 ? overlap / union : 0
}

function candidateTextSimilarity(left: string, right: string): number {
  const leftTokens = new Set(tokenizeForOverlap(left))
  const rightTokens = new Set(tokenizeForOverlap(right))
  return jaccard(leftTokens, rightTokens)
}

function sharedTokenCount(left: Set<string>, right: Set<string>): number {
  let overlap = 0
  left.forEach((token) => {
    if (right.has(token)) overlap += 1
  })
  return overlap
}

function extractEvidenceFacts(
  canvas: HypothesisCanvas,
  evidenceItems: HypothesisEvidenceItem[],
): EvidenceFact[] {
  const topicTokens = termTokenSet(canvas)
  const seen = new Set<string>()
  const facts: EvidenceFact[] = []

  for (const item of evidenceItems) {
    if (!item.id) continue
    if (item.synthetic_summary) continue
    const sourceChannel = item.source_channel || 'other'
    if (sourceChannel === 'workflow_fallback' || sourceChannel === 'deep_research_pending') continue
    const tier = resolveQualityTier(item)
    const traceability = resolveTraceabilityScore(item, tier)
    const snippets = [
      ...(item.summary ? splitFactSegments(item.summary) : []),
      ...(item.label ? splitFactSegments(item.label) : []),
    ]
    const segments = snippets.length ? snippets : [item.label].filter(Boolean)

    for (const segment of segments) {
      const normalizedSegment = segment.trim()
      if (!normalizedSegment) continue
      const dedupeKey = `${item.id}::${normalizedSegment.toLowerCase()}`
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)

      const tokens = tokenizeForOverlap(normalizedSegment)
      const tokenSet = normalizeTokenSet(tokens)
      if (tokenSet.size < 3) continue
      const topicality = jaccard(tokenSet, topicTokens)
      const relevance = normalizeUnit(
        topicality * 0.65 + qualityWeight(tier) * 0.2 + traceability * 0.15,
      )
      facts.push({
        id: `fact-${facts.length + 1}`,
        evidence_id: item.id,
        text: sentence(normalizedSegment),
        tokens: Array.from(tokenSet).slice(0, 14),
        source_channel: sourceChannel,
        quality_tier: tier,
        traceability_score: traceability,
        relevance,
      })
    }
  }

  return facts
    .sort((left, right) => {
      if (right.relevance !== left.relevance) return right.relevance - left.relevance
      return right.traceability_score - left.traceability_score
    })
    .slice(0, 28)
}

function clusterEvidenceFacts(facts: EvidenceFact[]): EvidenceFactCluster[] {
  type MutableCluster = {
    id: string
    factIds: string[]
    evidenceIds: Set<string>
    tokenSet: Set<string>
    tokenCounts: Map<string, number>
    scoreAcc: number
  }

  const clusters: MutableCluster[] = []
  for (const fact of facts) {
    const factTokens = new Set(fact.tokens)
    let bestCluster: MutableCluster | null = null
    let bestScore = 0

    for (const cluster of clusters) {
      const similarity = jaccard(factTokens, cluster.tokenSet)
      const overlap = sharedTokenCount(factTokens, cluster.tokenSet)
      const matchScore = similarity + overlap * 0.04
      if (matchScore > bestScore) {
        bestScore = matchScore
        bestCluster = cluster
      }
    }

    const shouldAttach = bestCluster && (bestScore >= 0.22 || sharedTokenCount(factTokens, bestCluster.tokenSet) >= 2)
    if (shouldAttach && bestCluster) {
      bestCluster.factIds.push(fact.id)
      bestCluster.evidenceIds.add(fact.evidence_id)
      factTokens.forEach((token) => {
        bestCluster.tokenSet.add(token)
        bestCluster.tokenCounts.set(token, (bestCluster.tokenCounts.get(token) || 0) + 1)
      })
      bestCluster.scoreAcc += fact.relevance
      continue
    }

    const tokenCounts = new Map<string, number>()
    factTokens.forEach((token) => {
      tokenCounts.set(token, 1)
    })
    clusters.push({
      id: `cluster-${clusters.length + 1}`,
      factIds: [fact.id],
      evidenceIds: new Set([fact.evidence_id]),
      tokenSet: factTokens,
      tokenCounts,
      scoreAcc: fact.relevance,
    })
  }

  return clusters
    .map((cluster) => {
      const keyTerms = Array.from(cluster.tokenCounts.entries())
        .sort((left, right) => {
          if (right[1] !== left[1]) return right[1] - left[1]
          return left[0].localeCompare(right[0])
        })
        .map(([token]) => token)
        .slice(0, 5)
      const baseScore = cluster.scoreAcc / Math.max(1, cluster.factIds.length)
      const sizeBoost = Math.min(0.15, cluster.factIds.length * 0.03)
      return {
        id: cluster.id,
        fact_ids: cluster.factIds,
        evidence_ids: Array.from(cluster.evidenceIds),
        key_terms: keyTerms,
        score: normalizeUnit(baseScore + sizeBoost),
      } satisfies EvidenceFactCluster
    })
    .sort((left, right) => right.score - left.score)
}

function buildEvidenceAnchors(args: {
  evidenceItems: HypothesisEvidenceItem[]
  pattern: CandidatePattern
  claim: string
  overlapThreshold: number
}): {
  anchors: EvidenceAnchor[]
  semanticAlignment: number
  qualityCounts: { primary: number; secondary: number; tertiary: number }
} {
  const scored = args.evidenceItems
    .map((item) => {
      const tier = resolveQualityTier(item)
      const overlapScore = semanticOverlapScore(args.claim, item)
      const traceabilityScore = resolveTraceabilityScore(item, tier)
      return {
        item,
        tier,
        overlapScore,
        traceabilityScore,
        anchorScore: normalizeUnit(
          overlapScore * 0.65 + qualityWeight(tier) * 0.2 + traceabilityScore * 0.15,
        ),
      }
    })
    .filter((entry) => entry.overlapScore >= args.overlapThreshold)
    .sort((left, right) => {
      if (right.anchorScore !== left.anchorScore) return right.anchorScore - left.anchorScore
      if (right.overlapScore !== left.overlapScore) return right.overlapScore - left.overlapScore
      return right.traceabilityScore - left.traceabilityScore
    })

  const top = scored.slice(0, 3)
  const qualityCounts = { primary: 0, secondary: 0, tertiary: 0 }
  for (const entry of top) {
    qualityCounts[entry.tier] += 1
  }

  return {
    anchors: top.map(
      (entry): EvidenceAnchor => ({
        evidence_id: entry.item.id,
        label: entry.item.label,
        kind: entry.item.kind,
        reason: args.pattern.anchor_reason,
        source_channel: entry.item.source_channel || 'other',
        confidence: entry.item.confidence ?? null,
        overlap_score: entry.overlapScore,
        quality_tier: entry.tier,
        traceability_score: entry.traceabilityScore,
      }),
    ),
    semanticAlignment: top.length
      ? normalizeUnit(
          top.reduce((sum, entry) => sum + entry.overlapScore, 0) / top.length,
        )
      : 0,
    qualityCounts,
  }
}

function chooseGroundingStatus(args: {
  anchors: EvidenceAnchor[]
  hasKgSignal: boolean
  degenerateEvidence?: boolean
}): CandidateGroundingStatus {
  if (!args.anchors.length) return 'draft_unverified'
  const qualifyingAnchors = args.anchors.filter(
    (anchor) =>
      anchor.quality_tier === 'primary' || anchor.quality_tier === 'secondary',
  )
  const distinctQualifyingDocs = new Set(
    qualifyingAnchors.map((anchor) => anchor.evidence_id).filter(Boolean),
  ).size
  if (distinctQualifyingDocs >= 2) return 'grounded'
  if (args.degenerateEvidence && distinctQualifyingDocs < 2) {
    if (distinctQualifyingDocs >= 1 || args.hasKgSignal) return 'weak_grounded'
    return 'draft_unverified'
  }
  if (distinctQualifyingDocs >= 1 || args.hasKgSignal) return 'weak_grounded'
  return 'draft_unverified'
}

function scoreCandidate(args: {
  anchors: EvidenceAnchor[]
  hasKgSignal: boolean
  patternIndex: number
  groundingStatus: CandidateGroundingStatus
  semanticAlignment: number
}): number {
  const anchorCount = args.anchors.length
  const anchorBoost = Math.min(0.3, anchorCount * 0.1)
  const kgBoost = args.hasKgSignal ? 0.07 : 0
  const alignmentBoost = Math.min(0.22, args.semanticAlignment * 0.24)
  const groundingBoost =
    args.groundingStatus === 'grounded'
      ? 0.14
      : args.groundingStatus === 'weak_grounded'
        ? 0.07
        : 0
  const rankBias = Math.max(0, 0.05 - args.patternIndex * 0.003)
  return normalizeConfidence(0.34 + anchorBoost + kgBoost + alignmentBoost + groundingBoost + rankBias)
}

export function buildGroundedDirectionCandidates(
  canvas: HypothesisCanvas,
  context: CandidateEvidenceContext = {},
  count = 5,
): DirectionCandidate[] {
  return buildGroundedDirectionCandidatesWithTrace(canvas, context, count).candidates
}

function scorePatternForCluster(pattern: CandidatePattern, cluster: EvidenceFactCluster): number {
  const tokenSet = new Set(cluster.key_terms.map((token) => token.toLowerCase()))
  const overlap = (keywords: string[]): number =>
    keywords.reduce((acc, token) => (tokenSet.has(token) ? acc + 1 : acc), 0)

  const weightedOverlap = (keywords: string[], weight: number): number =>
    overlap(keywords) * weight

  const patternKeywords: Record<string, { primary: string[]; secondary: string[] }> = {
    bridge_disconnected_claims: {
      primary: ['paradigm', 'context', 'task'],
      secondary: ['mixed', 'incompatible', 'heterogeneity'],
    },
    collapse_methodological_bottleneck: {
      primary: ['pipeline', 'preprocessing', 'modeling'],
      secondary: ['dominant', 'choice', 'variant'],
    },
    resolve_contradiction_loop: {
      primary: ['conflict', 'contradiction', 'heterogeneity'],
      secondary: ['stratified', 'subgroup', 'cohort'],
    },
    circular_validation_leak: {
      primary: ['nested', 'validation', 'leakage'],
      secondary: ['split', 'fold', 'inflated'],
    },
    population_generalization_failure: {
      primary: ['generalization', 'population', 'cohort'],
      secondary: ['clinical', 'developmental', 'site'],
    },
    measurement_invariance_gap: {
      primary: ['invariance', 'construct', 'comparability'],
      secondary: ['definition', 'protocol', 'acquisition'],
    },
    effect_size_inflation_risk: {
      primary: ['sample', 'power', 'effect'],
      secondary: ['inflated', 'shrinkage', 'meta'],
    },
    hrf_assumption_mismatch: {
      primary: ['hrf', 'hemodynamic', 'timing'],
      secondary: ['basis', 'temporal', 'event'],
    },
    parcellation_dependence: {
      primary: ['atlas', 'parcellation', 'connectome'],
      secondary: ['network', 'region', 'biomarker'],
    },
    motion_confound_underreporting: {
      primary: ['motion', 'confound', 'fd'],
      secondary: ['artifact', 'regression', 'nuisance'],
    },
    minimum_discriminating_test: {
      primary: ['minimal', 'discriminating', 'falsify'],
      secondary: ['cheap', 'proxy', 'ablation'],
    },
    structural_leverage_bridge: {
      primary: ['structural', 'leverage', 'bridge'],
      secondary: ['bottleneck', 'topology', 'path'],
    },
    contradiction_motif_disambiguation: {
      primary: ['contradiction', 'conflicting', 'motif'],
      secondary: ['supports', 'refutes', 'polarity'],
    },
    controlled_ood_hypothesis: {
      primary: ['ood', 'distribution', 'frontier'],
      secondary: ['low', 'probability', 'coherent'],
    },
    topology_shift_guardrail: {
      primary: ['topology', 'shift', 'drift'],
      secondary: ['stability', 'edge', 'reweight'],
    },
  }

  const kw = patternKeywords[pattern.id] || { primary: [], secondary: [] }
  const strictPatterns = new Set([
    'hrf_assumption_mismatch',
    'parcellation_dependence',
    'motion_confound_underreporting',
    'circular_validation_leak',
  ])

  const primaryHits = overlap(kw.primary)
  const secondaryHits = overlap(kw.secondary)
  if (strictPatterns.has(pattern.id) && primaryHits === 0) return 0

  let score = weightedOverlap(kw.primary, 1.4) + weightedOverlap(kw.secondary, 0.65)
  if (pattern.id === 'resolve_contradiction_loop') {
    score += overlap(['conflicting', 'opposing']) * 0.6
  }
  if (pattern.id === 'population_generalization_failure') {
    score += overlap(['cross', 'site', 'transportability']) * 0.5
  }
  if (pattern.id === 'collapse_methodological_bottleneck') {
    score += overlap(['reproducibility', 'robustness']) * 0.45
  }
  if (pattern.id === 'structural_leverage_bridge') {
    score += overlap(['disconnected', 'bridge', 'leverage']) * 0.55
  }
  if (pattern.id === 'contradiction_motif_disambiguation') {
    score += overlap(['supports', 'refutes', 'motif']) * 0.5
  }
  if (pattern.id === 'controlled_ood_hypothesis') {
    score += overlap(['frontier', 'novelty', 'exploration']) * 0.45
  }
  if (pattern.id === 'topology_shift_guardrail') {
    score += overlap(['drift', 'shift', 'stability']) * 0.5
  }
  return score
}

function choosePatternForCluster(
  cluster: EvidenceFactCluster,
  usedPatternIds: Set<string>,
  clusterIndex: number,
): CandidatePattern {
  const scored = HYPOTHESIS_DIRECTION_PATTERNS.map((pattern, index) => ({
    pattern,
    index,
    score: scorePatternForCluster(pattern, cluster),
    used: usedPatternIds.has(pattern.id),
  })).sort((left, right) => {
    if (right.score !== left.score) return right.score - left.score
    return left.index - right.index
  })

  const bestUnused = scored.find((item) => !item.used && item.score > 0)
  if (bestUnused) return bestUnused.pattern

  const defaultByIndex = HYPOTHESIS_DIRECTION_PATTERNS[clusterIndex % HYPOTHESIS_DIRECTION_PATTERNS.length]
  if (!usedPatternIds.has(defaultByIndex.id)) return defaultByIndex

  const anyUnused = HYPOTHESIS_DIRECTION_PATTERNS.find((item) => !usedPatternIds.has(item.id))
  return anyUnused || HYPOTHESIS_DIRECTION_PATTERNS[0]
}

function normalizeEvidenceCue(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string') return null
  const compact = raw
    .replace(/[#*_`>]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!compact) return null

  const firstSegment =
    compact
      .split(/[.!?;]+/)
      .map((part) => part.trim())
      .find((part) => part.length >= 18) || compact
  const cleaned = firstSegment
    .replace(/^key points?\s*[:\-]\s*/i, '')
    .replace(/^summary\s*[:\-]\s*/i, '')
    .trim()
  if (!cleaned) return null
  const bounded = cleaned.length > 140 ? `${cleaned.slice(0, 137).trim()}...` : cleaned
  return bounded.replace(/[.]+$/, '')
}

function injectEvidenceCue(templateClaim: string, cueRaw: string | null | undefined): string {
  const base = sentence(templateClaim)
  const cue = normalizeEvidenceCue(cueRaw)
  if (!cue) return base
  if (base.toLowerCase().includes(cue.toLowerCase())) return base
  return `${base} Evidence cue: ${cue}.`
}

type TemplateAnchorDimension = {
  id: string
  label: string
  source: CandidateAnchorSource
  evidenceIds: string[]
  cue: string | null
  tokens: string[]
  score: number
}

const ANCHOR_DIMENSION_RULES: Array<{
  id: string
  label: string
  keywords: string[]
}> = [
  { id: 'validation_leakage', label: 'Validation leakage', keywords: ['nested', 'validation', 'leakage', 'split', 'fold'] },
  { id: 'population_boundary', label: 'Population boundary', keywords: ['population', 'cohort', 'clinical', 'developmental', 'generalization'] },
  { id: 'measurement_invariance', label: 'Measurement invariance', keywords: ['invariance', 'construct', 'definition', 'protocol', 'comparability'] },
  { id: 'effect_size_inflation', label: 'Effect-size inflation', keywords: ['effect', 'sample', 'power', 'inflated', 'shrinkage'] },
  { id: 'confound_control', label: 'Confound control', keywords: ['confound', 'motion', 'artifact', 'regression', 'nuisance'] },
  { id: 'task_context_heterogeneity', label: 'Task context heterogeneity', keywords: ['task', 'context', 'paradigm', 'heterogeneity', 'incompatible'] },
  { id: 'modeling_pipeline_dependency', label: 'Modeling pipeline dependency', keywords: ['pipeline', 'preprocessing', 'modeling', 'workflow'] },
  { id: 'structural_leverage_bridge', label: 'Structural leverage bridge', keywords: ['structural', 'leverage', 'bridge', 'bottleneck', 'topology'] },
  { id: 'contradiction_motif', label: 'Contradiction motif', keywords: ['contradiction', 'conflicting', 'motif', 'supports', 'refutes'] },
  { id: 'controlled_ood_search', label: 'Controlled OOD search', keywords: ['ood', 'distribution', 'frontier', 'low', 'probability'] },
  { id: 'topology_shift', label: 'Topology shift', keywords: ['topology', 'shift', 'drift', 'reweight', 'stability'] },
  { id: 'hrf_model_assumption', label: 'HRF model assumption', keywords: ['hrf', 'hemodynamic', 'temporal', 'basis', 'timing'] },
  { id: 'parcellation_dependence', label: 'Parcellation dependence', keywords: ['parcellation', 'atlas', 'connectome', 'network'] },
  { id: 'minimal_discriminating_test', label: 'Minimal discriminating test', keywords: ['minimal', 'discriminating', 'falsify', 'ablation', 'proxy'] },
]

function resolveAnchorSource(
  current: CandidateAnchorSource | null,
  next: CandidateAnchorSource,
): CandidateAnchorSource {
  if (!current) return next
  if (current === next) return current
  return 'hybrid'
}

function collectAnchorDimensions(args: {
  canvas: HypothesisCanvas
  context: CandidateEvidenceContext
  evidenceItems: HypothesisEvidenceItem[]
}): TemplateAnchorDimension[] {
  type MutableDimension = {
    id: string
    label: string
    source: CandidateAnchorSource | null
    evidenceIds: Set<string>
    cue: string | null
    tokens: Set<string>
    score: number
  }
  const dims = new Map<string, MutableDimension>()

  const ensureDim = (ruleId: string, ruleLabel: string): MutableDimension => {
    const existing = dims.get(ruleId)
    if (existing) return existing
    const next: MutableDimension = {
      id: ruleId,
      label: ruleLabel,
      source: null,
      evidenceIds: new Set<string>(),
      cue: null,
      tokens: new Set<string>(),
      score: 0,
    }
    dims.set(ruleId, next)
    return next
  }

  const scoreTextForRules = (
    text: string,
    source: CandidateAnchorSource,
    evidenceId?: string,
  ): void => {
    const tokenSet = new Set(tokenizeForOverlap(text))
    if (!tokenSet.size) return
    for (const rule of ANCHOR_DIMENSION_RULES) {
      const matched = rule.keywords.filter((kw) => tokenSet.has(kw))
      if (!matched.length) continue
      const dim = ensureDim(rule.id, rule.label)
      dim.source = resolveAnchorSource(dim.source, source)
      dim.score += matched.length
      if (evidenceId) dim.evidenceIds.add(evidenceId)
      if (!dim.cue) dim.cue = normalizeEvidenceCue(text)
      matched.forEach((kw) => dim.tokens.add(kw))
    }
  }

  for (const item of args.evidenceItems) {
    const evidenceText = [item.label, item.summary || '', item.source_host || '']
      .filter(Boolean)
      .join(' ')
    scoreTextForRules(evidenceText, 'evidence', item.id)
  }

  const kgCompareText = [
    ...(args.context.kgCompare?.prior_art_match || []),
    ...(args.context.kgCompare?.novelty_gap || []),
    ...(args.context.kgCompare?.feasibility_constraints || []),
    ...(args.context.kgCompare?.novelty_taste?.structural_leverage || []),
    ...(args.context.kgCompare?.novelty_taste?.contradiction_motifs || []),
    ...(args.context.kgCompare?.novelty_taste?.ood_hypotheses || []),
    ...(args.context.kgCompare?.novelty_taste?.topology_shifts || []),
  ]
  kgCompareText.forEach((line) => scoreTextForRules(line, 'kg_compare'))

  ;(args.context.kgConcepts || []).forEach((concept) => scoreTextForRules(concept, 'kg'))

  const result = Array.from(dims.values())
    .map((dim) => ({
      id: dim.id,
      label: dim.label,
      source: dim.source || 'hybrid',
      evidenceIds: Array.from(dim.evidenceIds),
      cue: dim.cue,
      tokens: Array.from(dim.tokens),
      score: Number(dim.score.toFixed(2)),
    }))
    .sort((left, right) => right.score - left.score)

  if (result.length) return result
  return [
    {
      id: 'general_hypothesis_gap',
      label: 'General hypothesis gap',
      source: 'hybrid',
      evidenceIds: [],
      cue: normalizeEvidenceCue(args.context.deepResearchSummary || null),
      tokens: tokenizeForOverlap(args.canvas.term).slice(0, 4),
      score: 0.1,
    },
  ]
}

function buildFallbackReasons(args: {
  anchors: EvidenceAnchor[]
  overlapThreshold: number
  hasKgSignal: boolean
  degenerateReason: string | null
  groundingStatus: CandidateGroundingStatus
}): string[] {
  const reasons: string[] = []
  if (!args.anchors.length) {
    reasons.push(
      `No evidence passed semantic alignment threshold (${args.overlapThreshold.toFixed(2)}).`,
    )
  }
  if (!args.hasKgSignal) reasons.push('KG compare signal is sparse for this query.')
  if (args.groundingStatus !== 'grounded' && args.degenerateReason) {
    reasons.push(args.degenerateReason)
  }
  return reasons
}

function computeCandidateDiagnostics(
  candidates: DirectionCandidate[],
  anchorPoolSize: number,
  diversityResampleCount: number,
  diversityExhaustedSlots: number,
): CandidateGenerationDiagnostics {
  const patternUse = new Map<string, number>()
  const anchorDims = new Set<string>()
  const qualifyingAnchors: EvidenceAnchor[] = []

  for (const candidate of candidates) {
    if (candidate.pattern_id) {
      patternUse.set(candidate.pattern_id, (patternUse.get(candidate.pattern_id) || 0) + 1)
    }
    if (candidate.anchor_dim) anchorDims.add(candidate.anchor_dim)
    for (const anchor of candidate.evidence_anchors || []) {
      if (anchor.quality_tier === 'primary' || anchor.quality_tier === 'secondary') {
        qualifyingAnchors.push(anchor)
      }
    }
  }

  const patternReuseCount = Array.from(patternUse.values()).reduce(
    (acc, value) => acc + Math.max(0, value - 1),
    0,
  )
  const distinctQualifyingDocs = new Set(
    qualifyingAnchors.map((anchor) => anchor.evidence_id).filter(Boolean),
  ).size

  return {
    anchor_pool_size: anchorPoolSize,
    unique_anchor_dims: anchorDims.size,
    pattern_reuse_count: patternReuseCount,
    diversity_resample_count: diversityResampleCount,
    diversity_exhausted_slots: diversityExhaustedSlots,
    qualifying_evidence_count: qualifyingAnchors.length,
    distinct_qualifying_docs: distinctQualifyingDocs,
  }
}

function buildTemplateCandidates(args: {
  canvas: HypothesisCanvas
  context: CandidateEvidenceContext
  count: number
  overlapThreshold: number
  evidenceItems: HypothesisEvidenceItem[]
  hasKgSignal: boolean
}): {
  candidates: DirectionCandidate[]
  mode: CandidateGenerationMode
  diagnostics: CandidateGenerationDiagnostics
} {
  const { canvas, count, overlapThreshold, evidenceItems, hasKgSignal } = args
  const degenerateEvidence = Boolean(args.context.degenerateEvidence?.degenerate)
  const degenerateReason = args.context.degenerateEvidence?.reason || null
  const evidenceById = new Map(evidenceItems.map((item) => [item.id, item]))
  const diversityEnabled = process.env.HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED !== '0'
  const similarityThreshold = parseBoundedFloat(
    Number(process.env.HYPOTHESIS_TEMPLATE_SIMILARITY_THRESHOLD),
    DEFAULT_TEMPLATE_SIMILARITY_THRESHOLD,
    0.45,
    0.95,
  )
  const maxResamplePerSlot = parseBoundedInt(
    Number(process.env.HYPOTHESIS_TEMPLATE_MAX_RESAMPLE_PER_SLOT),
    DEFAULT_TEMPLATE_MAX_RESAMPLE_PER_SLOT,
    0,
    6,
  )
  const maxPatternReuse = parseBoundedInt(
    Number(process.env.HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE),
    DEFAULT_TEMPLATE_MAX_PATTERN_REUSE,
    1,
    4,
  )
  const anchorDims = collectAnchorDimensions({
    canvas,
    context: args.context,
    evidenceItems,
  })
  const targetCount = Math.max(1, count)
  const usedPatternCounts = new Map<string, number>()
  const candidates: DirectionCandidate[] = []
  let diversityResampleCount = 0
  let diversityExhaustedSlots = 0

  const choosePatternForAnchor = (
    anchor: TemplateAnchorDimension,
    excludedPatternIds: Set<string>,
  ): CandidatePattern => {
    const pseudoCluster: EvidenceFactCluster = {
      id: anchor.id,
      fact_ids: [],
      evidence_ids: anchor.evidenceIds,
      key_terms: anchor.tokens,
      score: anchor.score,
    }
    const scored = HYPOTHESIS_DIRECTION_PATTERNS.map((pattern, idx) => {
      const useCount = usedPatternCounts.get(pattern.id) || 0
      return {
        pattern,
        idx,
        useCount,
        score: scorePatternForCluster(pattern, pseudoCluster),
      }
    })
      .filter((entry) => !excludedPatternIds.has(entry.pattern.id))
      .sort((left, right) => {
        if (left.useCount !== right.useCount) return left.useCount - right.useCount
        if (right.score !== left.score) return right.score - left.score
        return left.idx - right.idx
      })

    const underReuse = scored.find((entry) => entry.useCount < maxPatternReuse)
    if (underReuse) return underReuse.pattern
    return scored[0]?.pattern || HYPOTHESIS_DIRECTION_PATTERNS[0]
  }

  const buildCandidateForPattern = (
    pattern: CandidatePattern,
    anchor: TemplateAnchorDimension,
    index: number,
    retryCount: number,
  ): DirectionCandidate => {
    const baseHypothesis = pattern.hypothesis(canvas)
    const anchorCueFromEvidence = (() => {
      if (anchor.evidenceIds.length) {
        const evidence = evidenceById.get(anchor.evidenceIds[0])
        return evidence?.summary || evidence?.label || null
      }
      return anchor.cue
    })()
    const hypothesis = injectEvidenceCue(baseHypothesis, anchorCueFromEvidence)
    const anchorDecision = buildEvidenceAnchors({
      evidenceItems,
      pattern,
      claim: hypothesis,
      overlapThreshold,
    })
    const groundingStatus = chooseGroundingStatus({
      anchors: anchorDecision.anchors,
      hasKgSignal,
      degenerateEvidence,
    })
    const confidence = scoreCandidate({
      anchors: anchorDecision.anchors,
      hasKgSignal,
      patternIndex: index,
      groundingStatus,
      semanticAlignment: anchorDecision.semanticAlignment,
    })
    const independentVariable = pattern.independent_variable(canvas)
    const dependentVariable = pattern.dependent_variable(canvas)
    const expectedSignal = pattern.expected_signal(canvas)
    const likelyDataSource = pattern.likely_data_source(canvas)
    return {
      id: `dir-${slug(canvas.term)}-${pattern.id}-${index + 1}`,
      title: pattern.title,
      hypothesis,
      independent_variable: independentVariable,
      dependent_variable: dependentVariable,
      expected_signal: expectedSignal,
      likely_data_source: likelyDataSource,
      novelty_gap: pattern.novelty_gap(canvas),
      risk_note: pattern.risk_note(canvas),
      minimal_discriminating_test: buildCandidateMinimalTestText({
        hypothesis,
        independentVariable,
        dependentVariable,
        likelyDataSource,
      }),
      falsifier_hint: buildCandidateFalsifierHintText({
        dependentVariable,
        expectedSignal,
      }),
      taste_axis: pattern.taste_axis,
      pattern_id: pattern.id,
      pattern_label: pattern.title,
      claim: hypothesis,
      evidence_anchors: anchorDecision.anchors,
      grounding_status: groundingStatus,
      confidence,
      semantic_alignment: anchorDecision.semanticAlignment,
      anchor_quality: anchorDecision.qualityCounts,
      anchor_dim: anchor.label,
      anchor_source: anchor.source,
      anchor_evidence_ids: anchor.evidenceIds,
      diversity_retry_count: retryCount,
      fallback_reasons: buildFallbackReasons({
        anchors: anchorDecision.anchors,
        overlapThreshold,
        hasKgSignal,
        degenerateReason,
        groundingStatus,
      }),
      share_allowed: groundingStatus === 'grounded',
    } satisfies DirectionCandidate
  }

  for (let slot = 0; slot < targetCount; slot += 1) {
    const anchor = anchorDims[slot % anchorDims.length]
    const excludedPatternIds = new Set<string>()
    let selected: DirectionCandidate | null = null
    let retries = 0
    let exhausted = false

    while (retries <= maxResamplePerSlot) {
      const pattern = choosePatternForAnchor(anchor, excludedPatternIds)
      const candidate = buildCandidateForPattern(pattern, anchor, slot, retries)
      const tooSimilar = diversityEnabled
        ? candidates.some(
            (existing) =>
              candidateTextSimilarity(existing.hypothesis, candidate.hypothesis) >
              similarityThreshold,
          )
        : false
      if (!tooSimilar) {
        selected = candidate
        break
      }
      excludedPatternIds.add(pattern.id)
      selected = candidate
      retries += 1
      diversityResampleCount += 1
    }

    if (!selected) continue
    if (retries > maxResamplePerSlot) {
      exhausted = true
    }
    if (exhausted) diversityExhaustedSlots += 1

    const patternId = selected.pattern_id || ''
    usedPatternCounts.set(patternId, (usedPatternCounts.get(patternId) || 0) + 1)
    candidates.push(selected)
  }

  const sorted = candidates.sort((left, right) => {
    const rank = (status: CandidateGroundingStatus | undefined): number => {
      if (status === 'grounded') return 2
      if (status === 'weak_grounded') return 1
      return 0
    }
    const leftGrounded = rank(left.grounding_status)
    const rightGrounded = rank(right.grounding_status)
    if (leftGrounded !== rightGrounded) return rightGrounded - leftGrounded
    return (right.confidence || 0) - (left.confidence || 0)
  })

  const mode: CandidateGenerationMode =
    diversityEnabled && anchorDims.length > 0 ? 'template_diversified' : 'template_fallback'
  const selected = sorted.slice(0, targetCount)
  return {
    candidates: selected,
    mode,
    diagnostics: computeCandidateDiagnostics(
      selected,
      anchorDims.length,
      diversityResampleCount,
      diversityExhaustedSlots,
    ),
  }
}

export function buildGroundedDirectionCandidatesWithTrace(
  canvas: HypothesisCanvas,
  context: CandidateEvidenceContext = {},
  count = 5,
): GroundedDirectionCandidateBuildResult {
  const envOverlapThreshold = Number(process.env.HYPOTHESIS_CLAIM_EVIDENCE_OVERLAP_THRESHOLD)
  const overlapThreshold = parseOverlapThreshold(
    context.overlapThreshold ??
      (Number.isFinite(envOverlapThreshold)
        ? envOverlapThreshold
        : DEFAULT_OVERLAP_THRESHOLD),
  )
  const evidenceItems = (context.evidence || []).filter((item) => {
    const label = (item.label || '').trim()
    return Boolean(label) && !item.synthetic_summary
  })

  const hasKgSignal = Boolean(
    (context.kgCompare?.prior_art_match?.length || 0) +
      (context.kgCompare?.novelty_gap?.length || 0) +
      (context.kgCompare?.feasibility_constraints?.length || 0),
  )
  const configuredMode = (process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE || 'template_only')
    .trim()
    .toLowerCase()
  const evidenceFirstEnabled = configuredMode === 'evidence_first'

  const facts = evidenceFirstEnabled ? extractEvidenceFacts(canvas, evidenceItems) : []
  const clusters = evidenceFirstEnabled ? clusterEvidenceFacts(facts) : []
  const effectiveCount = Math.max(1, count)

  if (!facts.length || !clusters.length) {
    const templateResult = buildTemplateCandidates({
      canvas,
      context,
      count: effectiveCount,
      overlapThreshold,
      evidenceItems,
      hasKgSignal,
    })
    return {
      candidates: templateResult.candidates,
      mode: templateResult.mode,
      facts,
      clusters,
      diagnostics: templateResult.diagnostics,
    }
  }

  const factsById = new Map(facts.map((fact) => [fact.id, fact]))
  const evidenceById = new Map(evidenceItems.map((item) => [item.id, item]))
  const usedPatternIds = new Set<string>()
  const selectedClusters = clusters.slice(0, Math.min(effectiveCount, clusters.length))

  const candidates = selectedClusters.map((cluster, clusterIndex) => {
    const pattern = choosePatternForCluster(cluster, usedPatternIds, clusterIndex)
    usedPatternIds.add(pattern.id)
    const clusterFacts = cluster.fact_ids
      .map((factId) => factsById.get(factId))
      .filter((fact): fact is EvidenceFact => Boolean(fact))
    const strongestFact = (() => {
      if (!clusterFacts.length) return null
      const preferPaper = clusterFacts.find((fact) => {
        const evidence = evidenceById.get(fact.evidence_id)
        return evidence?.kind === 'paper'
      })
      return preferPaper || clusterFacts[0]
    })()
    const hypothesis = injectEvidenceCue(pattern.hypothesis(canvas), strongestFact?.text || null)
    const title = pattern.title

    const anchorReason = 'Evidence-derived claim (fact cluster trace).'
    const anchorEntries = cluster.evidence_ids
      .map((evidenceId) => evidenceById.get(evidenceId))
      .filter((item): item is HypothesisEvidenceItem => Boolean(item))
      .map((item) => {
        const tier = resolveQualityTier(item)
        const overlapScore = semanticOverlapScore(hypothesis, item)
        const traceabilityScore = resolveTraceabilityScore(item, tier)
        return {
          item,
          tier,
          overlapScore,
          traceabilityScore,
          score: normalizeUnit(
            overlapScore * 0.7 + qualityWeight(tier) * 0.2 + traceabilityScore * 0.1,
          ),
        }
      })
      .sort((left, right) => {
        if (right.score !== left.score) return right.score - left.score
        return right.traceabilityScore - left.traceabilityScore
      })
      .slice(0, 3)

    const anchors: EvidenceAnchor[] = anchorEntries.map((entry) => ({
      evidence_id: entry.item.id,
      label: entry.item.label,
      kind: entry.item.kind,
      reason: anchorReason,
      source_channel: entry.item.source_channel || 'other',
      confidence: entry.item.confidence ?? null,
      overlap_score: entry.overlapScore,
      quality_tier: entry.tier,
      traceability_score: entry.traceabilityScore,
    }))

    const qualityCounts = { primary: 0, secondary: 0, tertiary: 0 }
    anchors.forEach((anchor) => {
      const tier =
        anchor.quality_tier === 'primary' || anchor.quality_tier === 'secondary'
          ? anchor.quality_tier
          : 'tertiary'
      qualityCounts[tier] += 1
    })

    const semanticAlignment = anchors.length
      ? normalizeUnit(
          anchors.reduce((sum, anchor) => sum + (anchor.overlap_score || 0), 0) / anchors.length,
        )
      : 0
    const groundingStatus = chooseGroundingStatus({
      anchors,
      hasKgSignal,
      degenerateEvidence: Boolean(context.degenerateEvidence?.degenerate),
    })
    const confidence = scoreCandidate({
      anchors,
      hasKgSignal,
      patternIndex: clusterIndex,
      groundingStatus,
      semanticAlignment,
    })
    const fallbackReasons = buildFallbackReasons({
      anchors,
      overlapThreshold,
      hasKgSignal,
      degenerateReason: context.degenerateEvidence?.reason || null,
      groundingStatus,
    })
    const independentVariable = pattern.independent_variable(canvas)
    const dependentVariable = pattern.dependent_variable(canvas)
    const expectedSignal = pattern.expected_signal(canvas)
    const likelyDataSource = pattern.likely_data_source(canvas)

    return {
      id: `dir-${slug(canvas.term)}-${pattern.id}-${clusterIndex + 1}`,
      title,
      hypothesis,
      independent_variable: independentVariable,
      dependent_variable: dependentVariable,
      expected_signal: expectedSignal,
      likely_data_source: likelyDataSource,
      novelty_gap: pattern.novelty_gap(canvas),
      risk_note: pattern.risk_note(canvas),
      minimal_discriminating_test: buildCandidateMinimalTestText({
        hypothesis,
        independentVariable,
        dependentVariable,
        likelyDataSource,
      }),
      falsifier_hint: buildCandidateFalsifierHintText({
        dependentVariable,
        expectedSignal,
      }),
      taste_axis: pattern.taste_axis,
      pattern_id: pattern.id,
      pattern_label: pattern.title,
      claim: hypothesis,
      evidence_anchors: anchors,
      grounding_status: groundingStatus,
      confidence,
      semantic_alignment: semanticAlignment,
      anchor_quality: qualityCounts,
      anchor_dim: cluster.key_terms.slice(0, 3).join(', ') || 'evidence cluster',
      anchor_source: 'evidence',
      anchor_evidence_ids: cluster.evidence_ids,
      diversity_retry_count: 0,
      fallback_reasons: fallbackReasons,
      share_allowed: groundingStatus === 'grounded',
    } satisfies DirectionCandidate
  })

  const sorted = candidates.sort((left, right) => {
    const rank = (status: CandidateGroundingStatus | undefined): number => {
      if (status === 'grounded') return 2
      if (status === 'weak_grounded') return 1
      return 0
    }
    const leftRank = rank(left.grounding_status)
    const rightRank = rank(right.grounding_status)
    if (leftRank !== rightRank) return rightRank - leftRank
    return (right.confidence || 0) - (left.confidence || 0)
  })

  const deduped: DirectionCandidate[] = []
  const seenClaims = new Set<string>()
  for (const candidate of sorted) {
    const key = (candidate.hypothesis || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .replace(/\s+/g, ' ')
    if (!key || seenClaims.has(key)) continue
    seenClaims.add(key)
    deduped.push(candidate)
  }

  return {
    candidates: deduped,
    mode: 'evidence_first',
    facts: facts.slice(0, 20),
    clusters: selectedClusters,
    diagnostics: computeCandidateDiagnostics(deduped, 0, 0, 0),
  }
}

export function buildDirectionCandidates(canvas: HypothesisCanvas, count = 5): DirectionCandidate[] {
  return buildGroundedDirectionCandidates(canvas, {}, count)
}

export function buildResearchPreview(
  canvas: HypothesisCanvas,
  candidate: DirectionCandidate,
): ResearchPreview {
  const baseMinutesByModality: Record<ResearchModality, number> = {
    fmri_task: 35,
    fmri_rest: 30,
    eeg: 24,
    behavioral: 18,
    multimodal: 52,
  }

  const baseCreditsByGoal: Record<ResearchGoal, number> = {
    mechanism_explanation: 18,
    predictive_modeling: 24,
    intervention_effect: 30,
    replication_dispute: 20,
  }

  const estimated_minutes = baseMinutesByModality[canvas.modality]
  const estimated_credits = baseCreditsByGoal[canvas.goal]
  const risk_level = estimated_minutes >= 45 || estimated_credits >= 28 ? 'high' : estimated_minutes >= 28 ? 'medium' : 'low'

  return {
    coverage_scope: [
      `Goal: ${goalLabel(canvas.goal)}`,
      `Modality: ${modalityLabel(canvas.modality)}`,
      `Population focus: ${canvas.population}`,
      `Candidate lens: ${candidate.title}`,
    ],
    estimated_minutes,
    estimated_credits,
    risk_level,
    known_gaps: [
      'Causal direction may remain under-identified without intervention data.',
      'Dataset harmonization assumptions should be validated before final claims.',
    ],
  }
}

export function buildWorkflowPlan(args: {
  canvas: HypothesisCanvas
  candidate: DirectionCandidate
  preview?: ResearchPreview | null
}): WorkflowPlan {
  const { canvas, candidate, preview } = args
  const suffix = slug(`${canvas.term}-${candidate.id}`)

  return {
    id: `plan-${suffix}`,
    mvp_steps: [
      `Define one falsifiable contrast for: ${candidate.hypothesis}`,
      candidate.minimal_discriminating_test ||
        `Run minimal test on ${candidate.likely_data_source}.`,
      'Compute effect direction + uncertainty intervals.',
      'Compare against at least one competing explanation.',
    ],
    full_steps: [
      'Expand to multiverse sensitivity checks across preprocessing/model variants.',
      'Add subgroup-stratified analyses with confound controls.',
      'Run robustness checks against task or site heterogeneity.',
      'Package reproducibility bundle (versions, seeds, config, run logs).',
    ],
    falsifier:
      candidate.falsifier_hint ||
      `If ${candidate.dependent_variable} does not change in the predicted direction after controlling major confounds, reject this direction.`,
    success_criteria: [
      'Primary effect sign and confidence interval are consistent across at least two analysis variants.',
      'At least one competing hypothesis is empirically disfavored by the minimum discriminating test.',
      preview
        ? `Execution remains within preview budget (<= ${preview.estimated_minutes} min, <= ${preview.estimated_credits} credits).`
        : 'Execution remains within approved budget envelope.',
    ],
    assumptions: [
      `Population definition (${canvas.population}) is observable in selected datasets.`,
      `Primary outcome (${canvas.primary_outcome}) can be operationalized with available derivatives.`,
    ],
  }
}

function triage(status: ValidationTriageStatus, reason_codes: ValidationFailureCode[], user_actions: string[]): ValidationTriage {
  return {
    status,
    reason_codes,
    user_actions,
  }
}

function blockedReport(why_not: string, alternatives: string[], required_inputs: string[]): BlockedReport {
  return {
    why_not,
    alternatives,
    required_inputs,
  }
}

export function evaluateWorkflowPlan(args: {
  plan: WorkflowPlan
  canvas: HypothesisCanvas
  context?: WorkflowContextInput
}): ValidationReport {
  const { plan, canvas, context } = args

  const checks: ValidationReport['checks'] = [
    {
      id: 'data_existence',
      label: 'Data existence check',
      status: 'pass',
      detail: 'Dataset context is available or constraints allow public fallback datasets.',
    },
    {
      id: 'hypothesis_specificity',
      label: 'Hypothesis specificity check',
      status: 'pass',
      detail: 'Research question includes target outcome and a falsifier.',
    },
    {
      id: 'method_viability',
      label: 'Method viability check',
      status: 'pass',
      detail: 'MVP has executable steps and explicit discriminating test.',
    },
    {
      id: 'confound_coverage',
      label: 'Confound coverage check',
      status: 'pass',
      detail: 'Plan includes at least one explicit confound control step.',
    },
  ]

  const reasonCodes: ValidationFailureCode[] = []
  const userActions: string[] = []

  const hasDataset = Boolean((context?.dataset_id || '').trim())
  if (!hasDataset && !canvas.constraints.toLowerCase().includes('public')) {
    checks[0].status = 'fail'
    checks[0].detail = 'No dataset_id provided and constraints do not allow public fallback data.'
    reasonCodes.push('DATA_UNAVAILABLE')
    userActions.push('Provide dataset_id or relax constraints to allow public datasets.')
  }

  if (canvas.research_question.trim().length < 18 || !plan.falsifier.trim()) {
    checks[1].status = 'fail'
    checks[1].detail = 'Research question/falsifier is too underspecified for decisive validation.'
    reasonCodes.push('HYPOTHESIS_UNDERSPECIFIED')
    userActions.push('Refine research question and falsifier with measurable outcome definitions.')
  }

  if (plan.mvp_steps.length < 3) {
    checks[2].status = 'fail'
    checks[2].detail = 'MVP steps are insufficient for an executable discriminating test.'
    reasonCodes.push('METHOD_INCOMPATIBLE')
    userActions.push('Add explicit data extraction, model fit, and falsification steps.')
  }

  const hasConfoundControl = [...plan.mvp_steps, ...plan.full_steps].some((step) => {
    const normalized = step.toLowerCase()
    return (
      normalized.includes('confound') ||
      normalized.includes('covariate') ||
      normalized.includes('motion') ||
      normalized.includes('site effect') ||
      normalized.includes('negative control')
    )
  })

  if (!hasConfoundControl) {
    checks[3].status = 'warn'
    checks[3].detail = 'No explicit confound control step detected.'
    if (!reasonCodes.includes('CONFOUND_UNCONTROLLED')) {
      reasonCodes.push('CONFOUND_UNCONTROLLED')
      userActions.push('Add one confound-control step before execution.')
    }
  }

  const hasNonFixable = reasonCodes.some((code) => code === 'DATA_UNAVAILABLE' || code === 'HYPOTHESIS_UNDERSPECIFIED')
  const hasFixable = reasonCodes.some((code) => code === 'METHOD_INCOMPATIBLE' || code === 'CONFOUND_UNCONTROLLED')

  if (hasNonFixable) {
    return {
      status: 'fail',
      triage: triage('non_fixable', reasonCodes, userActions),
      checks,
      blocked_report: blockedReport(
        'Current path is not executable because key inputs or hypothesis definitions are missing.',
        [
          'Switch to a dataset-backed direction with explicit public fallback constraints.',
          'Narrow the hypothesis to one measurable endpoint before re-planning.',
        ],
        [
          'dataset_id (or explicit public dataset fallback)',
          'one measurable primary outcome and falsifier threshold',
        ],
      ),
    }
  }

  if (hasFixable) {
    const overallStatus: ValidationReport['status'] =
      checks.some((check) => check.status === 'fail') ? 'fail' : 'warn'
    return {
      status: overallStatus,
      triage: triage('fixable', reasonCodes, userActions),
      checks,
      blocked_report: null,
    }
  }

  return {
    status: 'pass',
    triage: triage('unknown', [], []),
    checks,
    blocked_report: null,
  }
}

export function patchWorkflowPlan(args: {
  plan: WorkflowPlan
  validation: ValidationReport
}): PlanPatchResult {
  const { plan, validation } = args

  if (validation.triage.status !== 'fixable') {
    throw new Error('Plan patch only supports fixable triage results.')
  }

  const nextPlan: WorkflowPlan = {
    ...plan,
    id: `${plan.id}-patch1`,
    mvp_steps: [...plan.mvp_steps],
    full_steps: [...plan.full_steps],
    assumptions: [...plan.assumptions],
  }

  const changed_steps: string[] = []

  if (nextPlan.mvp_steps.length < 3) {
    nextPlan.mvp_steps.push('Add explicit model-fit and effect-size reporting step.')
    changed_steps.push('mvp_steps:+model_fit_reporting')
  }

  const hasConfoundControl = [...nextPlan.mvp_steps, ...nextPlan.full_steps].some((step) =>
    /confound|covariate|motion|negative control|site effect/i.test(step),
  )
  if (!hasConfoundControl) {
    nextPlan.mvp_steps.push('Add confound control block (motion, site, demographic covariates).')
    changed_steps.push('mvp_steps:+confound_control')
  }

  if (!nextPlan.assumptions.some((item) => /dataset/i.test(item))) {
    nextPlan.assumptions.push('Dataset compatibility has been re-checked for required variables.')
    changed_steps.push('assumptions:+dataset_compatibility')
  }

  return {
    summary: 'Applied one constrained auto-patch to method viability/confound coverage before re-validation.',
    changed_steps,
    patched_plan: nextPlan,
  }
}
