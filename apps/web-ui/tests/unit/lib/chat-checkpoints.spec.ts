import { describe, expect, it } from 'vitest'

import {
  buildCheckpointMessagePatch,
  extractCheckpointIdFromBoundary,
  normalizeCheckpointMetadata,
  withResumeCheckpointInContext,
} from '@/lib/chat-checkpoints'

describe('chat checkpoint helpers', () => {
  it('normalizes legacy boundary payloads to a canonical checkpoint id', () => {
    expect(
      extractCheckpointIdFromBoundary({
        metadata: { last_checkpoint_id: 'ck-legacy-1' },
      }),
    ).toBe('ck-legacy-1')
  })

  it('writes only metadata.checkpoint_id in normalized metadata', () => {
    expect(
      normalizeCheckpointMetadata({
        last_checkpoint_id: 'ck-legacy-2',
        provider: 'test',
      }),
    ).toEqual({
      checkpoint_id: 'ck-legacy-2',
      provider: 'test',
    })
  })

  it('builds a canonical message patch for UI state', () => {
    expect(
      buildCheckpointMessagePatch({
        payload: { metadata: { checkpoint_id: 'ck-3' } },
        metadata: { type: 'clarification' },
      }),
    ).toEqual({
      lastCheckpointId: 'ck-3',
      metadata: {
        checkpoint_id: 'ck-3',
        type: 'clarification',
      },
    })
  })

  it('injects resume checkpoint ids only into canonical ctx.resume_checkpoint_id', () => {
    expect(withResumeCheckpointInContext({ preview: true }, 'ck-4')).toEqual({
      preview: true,
      resume_checkpoint_id: 'ck-4',
    })
  })

  it('strips legacy ctx checkpoint keys while preserving the canonical value', () => {
    expect(
      withResumeCheckpointInContext(
        {
          preview: true,
          resumeCheckpointId: 'ck-legacy-ui',
          checkpoint_id: 'ck-legacy-root',
          checkpointId: 'ck-legacy-camel',
        },
        null,
      ),
    ).toEqual({
      preview: true,
      resume_checkpoint_id: 'ck-legacy-ui',
    })
  })
})
