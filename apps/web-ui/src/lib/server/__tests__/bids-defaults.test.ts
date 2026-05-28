import { describe, expect, it } from 'vitest'

import {
  inferBidsRunHintsFromPath,
  inferBoldImgPathFromBidsDir,
  resolveDefaultBidsRunHints,
} from '@/lib/server/bids-defaults'

describe('BIDS launch defaults', () => {
  it('uses ds000114 catalog task/session instead of a nonexistent rest fallback', () => {
    const dataset = {
      id: 'ds:openneuro:ds000114',
      source_repo_id: 'ds000114',
      tasks: [
        'covert_verb_generation',
        'finger_foot_lips',
        'line_bisection',
      ],
      sessions_count: 2,
    }

    const hints = resolveDefaultBidsRunHints(dataset)
    expect(hints).toEqual({
      subject_id: '01',
      session_id: 'test',
      task_id: 'covertverbgeneration',
    })
    expect(inferBoldImgPathFromBidsDir('/app/data/openneuro/ds000114', hints)).toBe(
      '/app/data/openneuro/ds000114/sub-01/ses-test/func/sub-01_ses-test_task-covertverbgeneration_bold.nii.gz',
    )
  })

  it('normalizes resting-state catalog labels to task-rest', () => {
    const hints = resolveDefaultBidsRunHints({
      id: 'ds:manual:abide',
      tasks: ['resting-state'],
    })

    expect(hints.task_id).toBe('rest')
  })

  it('infers subject/session/task hints from an explicit BIDS bold path', () => {
    const path =
      '/tmp/bids/sub-02/ses-retest/func/sub-02_ses-retest_task-fingerfootlips_bold.nii.gz'

    expect(inferBidsRunHintsFromPath(path)).toEqual({
      subject_id: '02',
      session_id: 'retest',
      task_id: 'fingerfootlips',
    })
    expect(
      resolveDefaultBidsRunHints(
        {
          id: 'ds:openneuro:ds000114',
          source_repo_id: 'ds000114',
          tasks: ['covert_verb_generation'],
        },
        {
          bold_img: path,
        },
      ),
    ).toEqual({
      subject_id: '02',
      session_id: 'retest',
      task_id: 'fingerfootlips',
    })
  })
})
