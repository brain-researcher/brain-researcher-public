import {
  DEFAULT_CODING_STREAM_PLACEHOLDER,
  extractCodingStreamText,
  getNextCodingStreamContent,
} from '../coding-stream'

describe('coding-stream', () => {
  it('appends token chunks and replaces the placeholder', () => {
    const firstChunk = getNextCodingStreamContent({
      event: 'token',
      data: { content: 'Diagnosis: ' },
      previousContent: DEFAULT_CODING_STREAM_PLACEHOLDER,
    })
    const secondChunk = getNextCodingStreamContent({
      event: 'token',
      data: { content: 'missing confounds.tsv' },
      previousContent: firstChunk,
    })

    expect(firstChunk).toBe('Diagnosis: ')
    expect(secondChunk).toBe('Diagnosis: missing confounds.tsv')
  })

  it('preserves streamed content on terminal done events without text', () => {
    const nextContent = getNextCodingStreamContent({
      event: 'done',
      data: { thread_id: 'thread-1', total_length: 128 },
      previousContent: 'Diagnosis: missing confounds.tsv',
    })

    expect(nextContent).toBe('Diagnosis: missing confounds.tsv')
  })

  it('does not stringify terminal metadata into visible content', () => {
    expect(
      extractCodingStreamText({
        thread_id: 'thread-1',
        total_length: 128,
      }),
    ).toBeNull()
  })

  it('uses explicit message content when result events carry a full answer', () => {
    const nextContent = getNextCodingStreamContent({
      event: 'result',
      data: { answer: 'Apply the confounds-aware subject subset and retry.' },
      previousContent: DEFAULT_CODING_STREAM_PLACEHOLDER,
    })

    expect(nextContent).toBe('Apply the confounds-aware subject subset and retry.')
  })
})
