// @vitest-environment node
import { describe, expect, it } from 'vitest'

import {
  applyNotebookOperation,
  applyNotebookOperations,
  buildStarterNotebook,
  deriveNotebookPlanFromPrompt,
  normalizeStudioNotebookDocument,
} from '@/components/studio/notebook/studio-notebook-state'

describe('studio notebook state helpers', () => {
  it('builds a starter notebook with a stable path and starter cells', () => {
    const notebook = buildStarterNotebook('proj_demo', 'rt_demo')

    expect(notebook.project_id).toBe('proj_demo')
    expect(notebook.session_id).toBe('rt_demo')
    expect(notebook.path).toBe('projects/proj_demo/notebooks/studio/rt_demo.ipynb')
    expect(notebook.cells).toHaveLength(2)
    expect(notebook.cells[0]?.cell_type).toBe('markdown')
    expect(notebook.cells[1]?.cell_type).toBe('code')
    expect(notebook.cells[1]?.source).toContain('Placeholder cell')
    expect(notebook.cells[1]?.outputs).toEqual([])
  })

  it('applies notebook ops locally', () => {
    const notebook = buildStarterNotebook('proj_demo', 'rt_demo')
    const appended = applyNotebookOperation(notebook, {
      type: 'append',
      cell_type: 'markdown',
      source: '## Analysis note',
    })

    expect(appended.cells).toHaveLength(3)
    expect(appended.cells[2]?.source).toContain('Analysis note')

    const moved = applyNotebookOperation(appended, {
      type: 'move_cell',
      cell_id: appended.cells[2]?.id,
      target_index: 0,
    })

    expect(moved.cells[0]?.source).toContain('Analysis note')

    const updated = applyNotebookOperation(moved, {
      type: 'apply_outputs',
      cell_id: moved.cells[1]?.id,
      outputs: [
        {
          output_type: 'stream',
          name: 'stdout',
          text: 'hello\n',
        },
      ],
      execution_count: 2,
      status: 'finished',
    })

    expect(updated.cells[1]?.outputs).toHaveLength(1)
    expect(updated.cells[1]?.execution_count).toBe(2)
    expect(updated.cells[1]?.status).toBe('finished')
  })

  it('normalizes raw notebook payloads into the studio model', () => {
    const notebook = normalizeStudioNotebookDocument(
      {
        id: 'nb_raw',
        project_id: 'proj_raw',
        session_id: 'rt_raw',
        path: 'projects/proj_raw/notebooks/studio/rt_raw.ipynb',
        title: 'Raw notebook',
        kernel_name: 'python3',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
        revision: 3,
        cells: [
          {
            id: 'cell_1',
            cell_type: 'code',
            source: ['print("hello")', '\n'],
            outputs: [
              {
                output_type: 'stream',
                name: 'stdout',
                text: ['hello', '\n'],
              },
            ],
            execution_count: 1,
          },
        ],
      },
      { projectId: 'proj_fallback', sessionId: 'rt_fallback' },
    )

    expect(notebook.id).toBe('nb_raw')
    expect(notebook.cells[0]?.source).toBe('print("hello")\n')
    expect(notebook.cells[0]?.outputs[0]?.text).toEqual(['hello', '\n'])
  })

  it('derives notebook ops from a natural-language prompt', () => {
    const notebook = buildStarterNotebook('proj_demo', 'rt_demo')
    const plan = deriveNotebookPlanFromPrompt(
      '请创建一个 markdown cell 写研究目标，再加一个 python cell 打印 hello',
      notebook,
    )

    expect(plan.ops).toHaveLength(2)
    expect(plan.ops[0]?.cell_type).toBe('markdown')
    expect(plan.ops[0]?.source).toContain('Research goal')
    expect(plan.ops[1]?.cell_type).toBe('code')
    expect(plan.ops[1]?.source).toContain('print("hello")')

    const updated = applyNotebookOperations(notebook, plan.ops)
    expect(updated.cells).toHaveLength(4)
    expect(updated.cells[2]?.cell_type).toBe('markdown')
    expect(updated.cells[3]?.cell_type).toBe('code')
  })

  it('falls back to a markdown note when the prompt is underspecified', () => {
    const notebook = buildStarterNotebook('proj_demo', 'rt_demo')
    const plan = deriveNotebookPlanFromPrompt('把这个分析思路整理一下', notebook)

    expect(plan.ops).toHaveLength(1)
    expect(plan.ops[0]?.cell_type).toBe('markdown')
    expect(plan.assistantMessage).toContain('Added')
  })
})
