import { describe, expect, it } from 'vitest'

import {
  HYPOTHESIS_DIRECTION_PATTERNS,
  buildGroundedDirectionCandidates,
  buildGroundedDirectionCandidatesWithTrace,
  buildDirectionCandidates,
  buildResearchPreview,
  buildWorkflowPlan,
  evaluateWorkflowPlan,
  normalizeCanvas,
  patchWorkflowPlan,
} from '@/lib/hypothesis-workflow'

describe('hypothesis workflow helpers', () => {
  const canvas = normalizeCanvas({
    term: 'Working memory',
    goal: 'mechanism_explanation',
    modality: 'fmri_task',
    population: 'Healthy adults',
    primary_outcome: 'BOLD contrast change',
    constraints: 'Allow public datasets',
    research_question: 'When does working memory increase fronto-parietal activation?',
  })

  it('builds fixed candidate set', () => {
    const candidates = buildDirectionCandidates(canvas, 5)
    expect(candidates).toHaveLength(5)
    expect(candidates[0].hypothesis.toLowerCase()).toContain('working memory')
  })

  it('exposes stable pattern catalog for methodology templates', () => {
    expect(HYPOTHESIS_DIRECTION_PATTERNS).toHaveLength(11)
    const ids = new Set(HYPOTHESIS_DIRECTION_PATTERNS.map((item) => item.id))
    expect(ids).toContain('bridge_disconnected_claims')
    expect(ids).toContain('collapse_methodological_bottleneck')
    expect(ids).toContain('resolve_contradiction_loop')
    expect(ids).toContain('circular_validation_leak')
    expect(ids).toContain('population_generalization_failure')
    expect(ids).toContain('measurement_invariance_gap')
    expect(ids).toContain('effect_size_inflation_risk')
    expect(ids).toContain('hrf_assumption_mismatch')
    expect(ids).toContain('parcellation_dependence')
    expect(ids).toContain('motion_confound_underreporting')
    expect(ids).toContain('minimum_discriminating_test')
  })

  it('marks candidates draft when no external evidence is available', () => {
    const candidates = buildGroundedDirectionCandidates(canvas, { evidence: [] }, 3)
    expect(candidates).toHaveLength(3)
    expect(candidates.every((item) => item.grounding_status === 'draft_unverified')).toBe(true)
    expect(candidates.every((item) => (item.evidence_anchors || []).length === 0)).toBe(true)
    expect(candidates.every((item) => item.share_allowed === false)).toBe(true)
  })

  it('excludes synthetic summary evidence from grounding and overlap', () => {
    const candidates = buildGroundedDirectionCandidates(
      canvas,
      {
        evidence: [
          {
            id: 'paper:synthetic-1',
            label: '# Comprehensive Analysis of Working Memory Findings',
            summary:
              '## Executive Summary\n* **Key Points**: Recent research synthesis highlights broad trends without extractable study-level claims.',
            kind: 'paper',
            url: 'https://example.org/synthesis',
            quality_tier: 'primary',
            traceability_score: 0.95,
            source_channel: 'deep_research_live',
            synthetic_summary: true,
          },
        ],
        kgCompare: {
          prior_art_match: ['Mapped concept exists'],
          novelty_gap: ['Bridge remains under-tested'],
          feasibility_constraints: ['Requires explicit confound controls'],
        },
        overlapThreshold: 0.05,
      },
      2,
    )

    expect(candidates).toHaveLength(2)
    expect(candidates.every((item) => item.grounding_status === 'draft_unverified')).toBe(true)
    expect(candidates.every((item) => (item.evidence_anchors || []).length === 0)).toBe(true)
  })

  it('attaches evidence anchors when evidence exists', () => {
    const candidates = buildGroundedDirectionCandidates(
      canvas,
      {
        evidence: [
          {
            id: 'paper:1',
            label: 'Working memory meta-analysis in fronto-parietal networks',
            kind: 'paper',
            url: 'https://doi.org/10.1038/s41593-024-00001-1',
            quality_tier: 'primary',
            traceability_score: 0.95,
            source_channel: 'deep_research_live',
          },
          {
            id: 'dataset:1',
            label: 'Working memory open benchmark cohort',
            kind: 'dataset',
            url: 'https://openneuro.org/datasets/ds000030',
            quality_tier: 'primary',
            traceability_score: 0.9,
            source_channel: 'graph',
          },
        ],
        kgCompare: {
          prior_art_match: ['Mapped concepts: decoding, prediction'],
          novelty_gap: ['Cross-paradigm bridge remains under-tested'],
          feasibility_constraints: ['Requires harmonized outcomes'],
        },
        overlapThreshold: 0.05,
      },
      2,
    )
    expect(candidates.length).toBeGreaterThanOrEqual(1)
    expect(candidates.length).toBeLessThanOrEqual(2)
    expect(candidates.some((item) => item.grounding_status === 'grounded')).toBe(true)
    expect(candidates.some((item) => (item.evidence_anchors || []).length > 0)).toBe(true)
    expect(candidates.some((item) => item.share_allowed === true)).toBe(true)
  })

  it('does not mark candidates grounded when KG is sparse and only low-traceability anchors exist', () => {
    const candidates = buildGroundedDirectionCandidates(
      canvas,
      {
        evidence: [
          {
            id: 'paper:low-1',
            label: 'Working memory blog summary',
            kind: 'paper',
            quality_tier: 'tertiary',
            traceability_score: 0.35,
            source_channel: 'deep_research_live',
          },
        ],
        kgCompare: {
          prior_art_match: [],
          novelty_gap: [],
          feasibility_constraints: [],
        },
      },
      3,
    )

    expect(candidates.length).toBeGreaterThanOrEqual(1)
    expect(candidates.length).toBeLessThanOrEqual(3)
    expect(candidates.every((item) => item.grounding_status !== 'grounded')).toBe(true)
  })

  it('forces draft status when evidence is marked degenerate', () => {
    const candidates = buildGroundedDirectionCandidates(
      canvas,
      {
        evidence: [
          {
            id: 'paper:deg-1',
            label: 'Nested cross-validation improves cross-site fMRI decoding robustness',
            kind: 'paper',
            url: 'https://doi.org/10.1016/j.neuroimage.2025.120001',
            quality_tier: 'primary',
            traceability_score: 0.95,
            source_channel: 'deep_research_live',
          },
        ],
        kgCompare: {
          prior_art_match: ['Mapped concepts: decoding'],
          novelty_gap: ['Cross-paradigm bridge remains under-tested'],
          feasibility_constraints: ['Requires harmonized outcomes'],
        },
        overlapThreshold: 0.05,
        degenerateEvidence: {
          degenerate: true,
          mode: 'soft_keep_top1',
          reason: 'Detected repeated synthesized titles.',
        },
      },
      2,
    )

    expect(candidates.length).toBeGreaterThan(0)
    expect(candidates.every((item) => item.grounding_status !== 'grounded')).toBe(true)
    expect(
      candidates.some((item) =>
        (item.fallback_reasons || []).some((reason) => reason.includes('Detected repeated synthesized titles')),
      ),
    ).toBe(true)
  })

  it('defaults to template-priority generation and injects evidence as cue text', () => {
    const previousMode = process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
    delete process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
    try {
      const result = buildGroundedDirectionCandidatesWithTrace(
        canvas,
        {
          evidence: [
            {
              id: 'paper:t1',
              label: '# Advances in fMRI Decoding and Predictive Modeling',
              summary:
                'Key points: Nested validation improves cross-site generalization and lowers inflated decoding gains.',
              kind: 'paper',
              url: 'https://arxiv.org/abs/2510.16196',
              quality_tier: 'primary',
              traceability_score: 0.91,
              source_channel: 'deep_research_live',
            },
          ],
          overlapThreshold: 0.05,
        },
        2,
      )

      expect(result.mode).toBe('template_diversified')
      expect(result.facts).toHaveLength(0)
      expect(result.candidates.length).toBeGreaterThan(0)
      expect(result.candidates[0]?.hypothesis.toLowerCase()).toContain('working memory')
      expect(result.candidates[0]?.hypothesis).toContain('Evidence cue:')
      expect(result.candidates[0]?.hypothesis.trim().startsWith('#')).toBe(false)
    } finally {
      if (previousMode === undefined) {
        delete process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
      } else {
        process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE = previousMode
      }
    }
  })

  it('uses evidence-first generation and does not force-fill candidates', () => {
    const previousMode = process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
    process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE = 'evidence_first'
    try {
      const candidates = buildGroundedDirectionCandidates(
        canvas,
        {
          evidence: [
            {
              id: 'paper:a1',
              label: 'Nested CV reduces inflated fMRI decoding accuracy in cross-site tests',
              summary:
                'Across multi-site datasets, strict nested validation lowers apparent gains and improves generalization estimates.',
              kind: 'paper',
              url: 'https://doi.org/10.1016/j.neuroimage.2025.120001',
              quality_tier: 'primary',
              traceability_score: 0.93,
              source_channel: 'deep_research_live',
            },
            {
              id: 'paper:a2',
              label: 'Atlas choice changes connectome biomarker stability',
              summary:
                'Parcellation decisions drive substantial variance in reported network biomarkers across cohorts.',
              kind: 'paper',
              url: 'https://doi.org/10.1016/j.neuroimage.2025.120002',
              quality_tier: 'primary',
              traceability_score: 0.9,
              source_channel: 'deep_research_live',
            },
          ],
          overlapThreshold: 0.1,
          kgCompare: {
            prior_art_match: [],
            novelty_gap: [],
            feasibility_constraints: [],
          },
        },
        6,
      )

      expect(candidates.length).toBeLessThan(6)
      expect(candidates.length).toBeGreaterThanOrEqual(2)
      expect(candidates.some((item) => (item.semantic_alignment || 0) > 0.1)).toBe(true)
      expect(
        candidates.some(
          (item) =>
            item.hypothesis.toLowerCase().includes('nested') ||
            item.hypothesis.toLowerCase().includes('parcellation'),
        ),
      ).toBe(true)
    } finally {
      if (previousMode === undefined) {
        delete process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
      } else {
        process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE = previousMode
      }
    }
  })

  it('enforces template diversity by anchor dimensions and pattern reuse control', () => {
    const prevMode = process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
    const prevReuse = process.env.HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE
    const prevDiversity = process.env.HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED
    process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE = 'template_only'
    process.env.HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE = '1'
    process.env.HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED = '1'

    try {
      const result = buildGroundedDirectionCandidatesWithTrace(
        canvas,
        {
          evidence: [
            {
              id: 'ev-1',
              label: 'Nested validation catches leakage in decoding pipelines',
              summary:
                'Strict fold-level separation reduces inflated effects and improves robustness.',
              kind: 'paper',
              source_channel: 'deep_research_live',
              quality_tier: 'primary',
              traceability_score: 0.9,
            },
            {
              id: 'ev-2',
              label: 'Population cohorts show uneven generalization',
              summary:
                'Clinical and developmental cohorts diverge from healthy-adult benchmarks.',
              kind: 'paper',
              source_channel: 'deep_research_live',
              quality_tier: 'secondary',
              traceability_score: 0.75,
            },
            {
              id: 'ev-3',
              label: 'Parcellation and atlas choices alter biomarker stability',
              summary:
                'Connectome effects shift by atlas and region definition choices.',
              kind: 'paper',
              source_channel: 'deep_research_live',
              quality_tier: 'secondary',
              traceability_score: 0.72,
            },
          ],
          kgCompare: {
            prior_art_match: ['Protocol definitions vary across studies'],
            novelty_gap: ['Measurement invariance is under-tested'],
            feasibility_constraints: ['Motion confounds remain under-controlled'],
          },
          kgConcepts: ['hrf timing', 'effect size inflation', 'confound control'],
          overlapThreshold: 0.1,
        },
        6,
      )

      expect(result.mode).toBe('template_diversified')
      expect(result.diagnostics.anchor_pool_size).toBeGreaterThan(0)
      expect(result.diagnostics.unique_anchor_dims).toBeGreaterThan(2)
      expect(result.diagnostics.pattern_reuse_count).toBeLessThanOrEqual(1)
      expect(result.candidates.every((item) => Boolean(item.anchor_dim))).toBe(true)
    } finally {
      if (prevMode === undefined) delete process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE
      else process.env.HYPOTHESIS_CANDIDATE_GENERATION_MODE = prevMode
      if (prevReuse === undefined) delete process.env.HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE
      else process.env.HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE = prevReuse
      if (prevDiversity === undefined) delete process.env.HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED
      else process.env.HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED = prevDiversity
    }
  })

  it('marks non-fixable when required data is unavailable', () => {
    const candidate = buildDirectionCandidates(canvas, 1)[0]
    const preview = buildResearchPreview(canvas, candidate)
    const strictCanvas = {
      ...canvas,
      constraints: 'Use internal-only cohort',
    }
    const plan = buildWorkflowPlan({ canvas: strictCanvas, candidate, preview })

    const validation = evaluateWorkflowPlan({
      canvas: strictCanvas,
      plan,
      context: {
        dataset_id: null,
      },
    })

    expect(validation.triage.status).toBe('non_fixable')
    expect(validation.triage.reason_codes).toContain('DATA_UNAVAILABLE')
    expect(validation.blocked_report?.required_inputs.length).toBeGreaterThan(0)
  })

  it('patches only fixable failures', () => {
    const candidate = buildDirectionCandidates(canvas, 1)[0]
    const preview = buildResearchPreview(canvas, candidate)
    const minimalPlan = {
      ...buildWorkflowPlan({ canvas, candidate, preview }),
      mvp_steps: ['Run test'],
      full_steps: [],
    }

    const validation = evaluateWorkflowPlan({
      canvas,
      plan: minimalPlan,
      context: {
        dataset_id: 'ds_mock',
      },
    })

    expect(validation.triage.status).toBe('fixable')

    const patch = patchWorkflowPlan({
      plan: minimalPlan,
      validation,
    })

    expect(patch.changed_steps.length).toBeGreaterThan(0)
    expect(patch.patched_plan.id).toContain('patch1')
  })
})
