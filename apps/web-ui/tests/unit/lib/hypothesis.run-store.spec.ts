import { describe, expect, it } from 'vitest'

import { updateIntentSummary } from '@/lib/server/hypothesis-run-store'

const CJK_RE = /[\u4e00-\u9fff]/

function countNumberedQuestions(message: string): number {
  return (message.match(/^\d\)/gm) || []).length
}

describe('hypothesis run store clarifying message', () => {
  it('builds a dynamic 4-question decoding questionnaire', () => {
    const result = updateIntentSummary({
      sessionId: 'spec-decoding-v2',
      message: 'what is the recent research in brain decoding',
      hasDataset: false,
    })

    expect(result.summary.intent_ready).toBe(false)
    expect(result.assistantMessage).toContain('4 quick decisions')
    expect(result.assistantMessage).toContain('cross-subject generalization')
    expect(result.assistantMessage).toContain('Reply in one line: objective=..., modality=..., population=..., priority=...')
    expect(result.assistantMessage).toContain('Optional shortcut: reply 1/2/3')
    expect(countNumberedQuestions(result.assistantMessage)).toBe(4)
  })

  it('adapts questionnaire language to intervention/causal lane', () => {
    const result = updateIntentSummary({
      sessionId: 'spec-intervention-v2',
      message: 'does TMS improve working memory performance?',
      hasDataset: false,
    })

    expect(result.summary.intent_ready).toBe(false)
    expect(result.assistantMessage).toContain('sham-controlled causal estimate')
    expect(result.assistantMessage).toContain('sham leakage control')
    expect(countNumberedQuestions(result.assistantMessage)).toBe(4)
  })

  it('keeps output in English even for non-English input', () => {
    const result = updateIntentSummary({
      sessionId: 'spec-language-v2',
      message: '最近脑解码研究是什么',
      hasDataset: false,
    })

    expect(result.assistantMessage).not.toMatch(CJK_RE)
  })

  it('returns an English intent-locked message after defaults are accepted', () => {
    updateIntentSummary({
      sessionId: 'spec-ready-v2',
      message: 'what is the recent research in brain decoding',
      hasDataset: false,
    })

    const result = updateIntentSummary({
      sessionId: 'spec-ready-v2',
      message: 'use default',
      hasDataset: false,
    })

    expect(result.summary.intent_ready).toBe(true)
    expect(result.assistantMessage).toContain('Intent locked:')
    expect(result.assistantMessage).toContain('Starting deep research + KG comparison now.')
    expect(result.assistantMessage).not.toMatch(CJK_RE)
  })

  it('extracts task term and strips trailing evidence-path noise', () => {
    const result = updateIntentSummary({
      sessionId: 'spec-term-clean-v1',
      message: 'what are robust fMRI findings for approach avoidance task and their evidence paths?',
      hasDataset: false,
    })

    expect(result.summary.term).toBe('approach avoidance task')
  })

  it('extracts status query term for brain decoding domain prompts', () => {
    const result = updateIntentSummary({
      sessionId: 'spec-term-decoding-v1',
      message: "what's the current status in fmri-based brain decoding?",
      hasDataset: false,
    })

    expect(result.summary.term).toBe('fmri-based brain decoding')
  })
})
