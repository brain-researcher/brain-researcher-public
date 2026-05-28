import { planForError } from '../errors'

describe('planForError', () => {
  it('maps validation to inline retry', () => {
    const plan = planForError('E-INPUT-VALIDATION')
    expect(plan.kind).toBe('inline')
    expect(plan.fallbackAction).toBe('retry')
  })

  it('maps auth to fullscreen login', () => {
    const plan = planForError('E-AUTH')
    expect(plan.kind).toBe('fullscreen')
    expect(plan.fallbackAction).toBe('login')
  })

  it('maps kg offline to toast model-fallback', () => {
    const plan = planForError('E-KG-OFFLINE')
    expect(plan.kind).toBe('toast')
    expect(plan.fallbackAction).toBe('model-fallback')
  })

  it('defaults to toast when unknown', () => {
    const plan = planForError('E-NOT-A-REAL-CODE')
    expect(plan.kind).toBe('toast')
  })
})
