import type {
  StudioNotebookCell,
  StudioNotebookCellStatus,
  StudioNotebookCellType,
  StudioNotebookDocument,
  StudioNotebookOperation,
  StudioNotebookOutput,
} from '@/lib/api/studio-notebook'

export type DerivedNotebookPlan = {
  ops: StudioNotebookOperation[]
  assistantMessage: string
}

function nowIso() {
  return new Date().toISOString()
}

function randomId(prefix: string) {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}_${crypto.randomUUID().replace(/-/g, '')}`
  }
  return `${prefix}_${Math.random().toString(36).slice(2, 12)}`
}

function toText(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join('')
  }
  if (value == null) {
    return ''
  }
  return String(value)
}

function normalizeStatus(value: unknown): StudioNotebookCellStatus {
  if (
    value === 'idle' ||
    value === 'running' ||
    value === 'finished' ||
    value === 'error'
  ) {
    return value
  }
  if (value === 'succeeded') {
    return 'finished'
  }
  if (value === 'failed' || value === 'canceled') {
    return 'error'
  }
  return 'idle'
}

function normalizeCellType(value: unknown): StudioNotebookCellType {
  return value === 'markdown' ? 'markdown' : 'code'
}

function normalizeOutputs(value: unknown): StudioNotebookOutput[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => {
    const record = item && typeof item === 'object' ? (item as Record<string, unknown>) : {}
    return {
      output_type:
        record.output_type === 'display_data' ||
        record.output_type === 'execute_result' ||
        record.output_type === 'error'
          ? record.output_type
          : 'stream',
      name: record.name === 'stderr' ? 'stderr' : 'stdout',
      text: record.text as string | string[] | undefined,
      data:
        record.data && typeof record.data === 'object' && !Array.isArray(record.data)
          ? (record.data as Record<string, unknown>)
          : undefined,
      metadata:
        record.metadata && typeof record.metadata === 'object' && !Array.isArray(record.metadata)
          ? (record.metadata as Record<string, unknown>)
          : undefined,
      ename: typeof record.ename === 'string' ? record.ename : undefined,
      evalue: typeof record.evalue === 'string' ? record.evalue : undefined,
      traceback: Array.isArray(record.traceback)
        ? record.traceback.map((line) => String(line))
        : undefined,
    }
  })
}

export function createNotebookCell(
  cell_type: StudioNotebookCellType,
  source: string,
  partial?: Partial<StudioNotebookCell>,
): StudioNotebookCell {
  return {
    id: partial?.id ?? randomId('cell'),
    cell_type,
    source,
    metadata: partial?.metadata ?? {},
    outputs: partial?.outputs ?? [],
    execution_count: partial?.execution_count ?? null,
    status: partial?.status ?? 'idle',
    ...partial,
  }
}

export function buildStarterNotebook(
  projectId: string,
  sessionId: string | null,
): StudioNotebookDocument {
  const createdAt = nowIso()
  const notebookId = sessionId ? `nb_${sessionId}` : randomId('nb')
  const path = sessionId
    ? `projects/${projectId}/notebooks/studio/${sessionId}.ipynb`
    : `projects/${projectId}/notebooks/studio/draft.ipynb`
  return {
    id: notebookId,
    project_id: projectId,
    session_id: sessionId,
    path,
    title: 'Studio notebook',
    kernel_name: 'python3',
    format: 'ipynb',
    metadata: {
      source: 'brain_researcher.studio',
      surface: 'assistant_first',
    },
    created_at: createdAt,
    updated_at: createdAt,
    last_saved_at: null,
    revision: 1,
    cells: [
      createNotebookCell(
        'markdown',
        '# Notebook draft\n\nAsk the assistant to generate the first cells, or start editing this notebook directly.',
        {
        id: 'cell_welcome',
        metadata: { role: 'welcome' },
      },
      ),
      createNotebookCell(
        'code',
        "# Placeholder cell\n# Ask the assistant for a concrete notebook scaffold,\n# for example: 'Generate a notebook to visualize T1 images.'",
        {
          id: 'cell_start',
          outputs: [],
          execution_count: null,
          status: 'idle',
          metadata: { role: 'placeholder' },
        },
      ),
    ],
  }
}

function cloneNotebook(notebook: StudioNotebookDocument): StudioNotebookDocument {
  return {
    ...notebook,
    metadata: { ...notebook.metadata },
    cells: notebook.cells.map((cell) => ({
      ...cell,
      metadata: { ...cell.metadata },
      outputs: cell.outputs.map((output) => ({ ...output })),
    })),
  }
}

function findCellIndex(
  notebook: StudioNotebookDocument,
  cellId: string | undefined,
): number {
  if (!cellId) {
    return -1
  }
  return notebook.cells.findIndex((cell) => cell.id === cellId)
}

function coerceCell(
  cell: StudioNotebookCell | Partial<StudioNotebookCell>,
  fallbackType: StudioNotebookCellType = 'code',
): StudioNotebookCell {
  return createNotebookCell(normalizeCellType(cell.cell_type ?? fallbackType), toText(cell.source), {
    ...cell,
    cell_type: normalizeCellType(cell.cell_type ?? fallbackType),
    source: toText(cell.source),
    metadata:
      cell.metadata && typeof cell.metadata === 'object' && !Array.isArray(cell.metadata)
        ? (cell.metadata as Record<string, unknown>)
        : {},
    outputs: normalizeOutputs((cell as StudioNotebookCell).outputs),
    execution_count:
      typeof (cell as StudioNotebookCell).execution_count === 'number'
        ? (cell as StudioNotebookCell).execution_count
        : null,
    status: normalizeStatus((cell as StudioNotebookCell).status),
  })
}

export function normalizeStudioNotebookDocument(
  value: unknown,
  fallback: { projectId: string; sessionId: string | null },
): StudioNotebookDocument {
  const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const cellsValue = Array.isArray(record.cells) ? record.cells : []
  const cells = cellsValue.map((cell, index) => {
    const cellRecord = cell && typeof cell === 'object' ? (cell as Record<string, unknown>) : {}
    const id = typeof cellRecord.id === 'string' && cellRecord.id.trim()
      ? cellRecord.id
      : randomId(`cell_${index}`)
    return coerceCell(
      {
        id,
        cell_type: normalizeCellType(cellRecord.cell_type),
        source: toText(cellRecord.source),
        metadata:
          cellRecord.metadata && typeof cellRecord.metadata === 'object' && !Array.isArray(cellRecord.metadata)
            ? (cellRecord.metadata as Record<string, unknown>)
            : {},
        outputs: normalizeOutputs(cellRecord.outputs),
        execution_count:
          typeof cellRecord.execution_count === 'number' ? cellRecord.execution_count : null,
        status: normalizeStatus(cellRecord.status),
      },
      'code',
    )
  })

  const createdAt = typeof record.created_at === 'string' ? record.created_at : nowIso()
  const updatedAt = typeof record.updated_at === 'string' ? record.updated_at : createdAt
  const lastSavedAt =
    typeof record.last_saved_at === 'string'
      ? record.last_saved_at
      : typeof record.last_saved_at === 'boolean'
        ? null
        : null
  const rawPath =
    typeof record.path === 'string' && record.path.trim() ? record.path.trim() : null
  const canonicalStudioPath = fallback.sessionId
    ? `projects/${fallback.projectId}/notebooks/studio/${fallback.sessionId}.ipynb`
    : `projects/${fallback.projectId}/notebooks/studio/draft.ipynb`
  const studioRoot = `projects/${fallback.projectId}/notebooks/studio/`
  const normalizedPath =
    rawPath &&
    !(
      fallback.sessionId &&
      (rawPath.endsWith('/draft.ipynb') ||
        (rawPath.startsWith(studioRoot) &&
          !rawPath.endsWith(`/${fallback.sessionId}.ipynb`)))
    )
      ? rawPath
      : canonicalStudioPath

  return {
    id:
      typeof record.id === 'string' && record.id.trim()
        ? record.id
        : fallback.sessionId
          ? `nb_${fallback.sessionId}`
          : randomId('nb'),
    project_id:
      typeof record.project_id === 'string' && record.project_id.trim()
        ? record.project_id
        : fallback.projectId,
    session_id:
      typeof record.session_id === 'string' ? record.session_id : fallback.sessionId,
    path: normalizedPath,
    title:
      typeof record.title === 'string' && record.title.trim()
        ? record.title
        : 'Studio notebook',
    kernel_name:
      typeof record.kernel_name === 'string' && record.kernel_name.trim()
        ? record.kernel_name
        : 'python3',
    format: 'ipynb',
    metadata:
      record.metadata && typeof record.metadata === 'object' && !Array.isArray(record.metadata)
        ? (record.metadata as Record<string, unknown>)
        : {},
    created_at: createdAt,
    updated_at: updatedAt,
    last_saved_at: lastSavedAt,
    revision: typeof record.revision === 'number' ? record.revision : 1,
    cells:
      cells.length > 0
        ? cells
        : buildStarterNotebook(fallback.projectId, fallback.sessionId).cells,
  }
}

function insertCell(
  notebook: StudioNotebookDocument,
  cell: StudioNotebookCell,
  afterCellId?: string | null,
): StudioNotebookDocument {
  const next = cloneNotebook(notebook)
  const index = findCellIndex(next, afterCellId ?? undefined)
  if (index < 0) {
    next.cells.push(cell)
  } else {
    next.cells.splice(index + 1, 0, cell)
  }
  next.revision += 1
  next.updated_at = nowIso()
  return next
}

export function applyNotebookOperations(
  notebook: StudioNotebookDocument,
  operations: StudioNotebookOperation[],
): StudioNotebookDocument {
  return operations.reduce(
    (current, operation) => applyNotebookOperation(current, operation),
    notebook,
  )
}

function trimPrompt(prefixes: Array<string | RegExp>, prompt: string): string {
  let value = prompt.trim()
  for (const prefix of prefixes) {
    value = value.replace(prefix, '').trim()
  }
  return value
}

function inferMarkdownSource(prompt: string): string {
  const trimmed = trimPrompt(
    [
      /^请/i,
      /^please/i,
      /^帮我/i,
      /^创建一个/i,
      /^加一个/i,
      /^添加一个/i,
      /^新增一个/i,
      /^write a/i,
      /^add a/i,
      /^create a/i,
      /markdown cell/gi,
      /markdown/gi,
      /单元格/gi,
      /cell/gi,
    ],
    prompt,
  )

  if (/研究目标|research goal|objective|aim/i.test(prompt)) {
    return `## Research goal\n\n${trimmed || 'Describe the research goal for this notebook.'}`
  }

  if (/假设|hypothesis/i.test(prompt)) {
    return `## Hypothesis\n\n${trimmed || 'State the working hypothesis for this analysis.'}`
  }

  if (/总结|summary|note|说明/i.test(prompt)) {
    return `## Note\n\n${trimmed || 'Summarize the next analysis step.'}`
  }

  return `## Assistant note\n\n${trimmed || prompt.trim()}`
}

function inferCodeSource(prompt: string): string {
  const quotedPrint =
    prompt.match(/print\s+["']([^"']+)["']/i)?.[1] ??
    prompt.match(/打印\s*([a-zA-Z0-9_ .-]+)/i)?.[1]?.trim()

  if (quotedPrint) {
    return `print(${JSON.stringify(quotedPrint)})`
  }

  if (/print\s+hello|打印\s*hello/i.test(prompt)) {
    return 'print("hello")'
  }

  if (/plot|绘图|画图/i.test(prompt)) {
    return [
      'import matplotlib.pyplot as plt',
      '',
      'fig, ax = plt.subplots()',
      'ax.plot([0, 1, 2], [0, 1, 4])',
      "ax.set_title('Assistant draft plot')",
      'plt.show()',
    ].join('\n')
  }

  if (/load|read|csv|读取|加载/i.test(prompt)) {
    return [
      'from pathlib import Path',
      'import pandas as pd',
      '',
      "data_path = Path('data.csv')",
      'df = pd.read_csv(data_path)',
      'df.head()',
    ].join('\n')
  }

  return [
    '# Assistant draft',
    `request = ${JSON.stringify(prompt.trim())}`,
    "print('Drafted from request:')",
    'print(request)',
  ].join('\n')
}

export function deriveNotebookPlanFromPrompt(
  prompt: string,
  notebook: StudioNotebookDocument,
): DerivedNotebookPlan {
  const normalizedPrompt = prompt.trim()
  if (!normalizedPrompt) {
    return {
      ops: [],
      assistantMessage: 'Add a request and I will draft cells into the notebook.',
    }
  }

  const ops: StudioNotebookOperation[] = []
  const lastCellId = notebook.cells.at(-1)?.id ?? null
  const wantsMarkdown =
    /markdown|说明|总结|笔记|研究目标|research goal|objective|hypothesis|note/i.test(
      normalizedPrompt,
    )
  const wantsCode =
    /python|code|代码|print|运行|execute|plot|绘图|加载|读取|analysis/i.test(
      normalizedPrompt,
    )

  if (wantsMarkdown) {
    ops.push({
      type: 'append',
      cell_type: 'markdown',
      source: inferMarkdownSource(normalizedPrompt),
      after_cell_id: lastCellId,
      metadata: {
        source: 'assistant_prompt',
      },
    })
  }

  if (wantsCode) {
    ops.push({
      type: 'append',
      cell_type: 'code',
      source: inferCodeSource(normalizedPrompt),
      after_cell_id: null,
      metadata: {
        source: 'assistant_prompt',
      },
    })
  }

  if (!ops.length) {
    ops.push({
      type: 'append',
      cell_type: 'markdown',
      source: inferMarkdownSource(normalizedPrompt),
      after_cell_id: lastCellId,
      metadata: {
        source: 'assistant_prompt',
      },
    })
  }

  const summary = ops
    .map((op) => (op.cell_type === 'markdown' ? '1 markdown cell' : '1 code cell'))
    .join(' and ')

  return {
    ops,
    assistantMessage: `Added ${summary} to the notebook. Review on the right, then edit or run the drafted cells.`,
  }
}

export function applyNotebookOperation(
  notebook: StudioNotebookDocument,
  operation: StudioNotebookOperation,
): StudioNotebookDocument {
  const next = cloneNotebook(notebook)
  const cellIndex = findCellIndex(next, operation.cell_id)

  switch (operation.type) {
    case 'append': {
      return insertCell(
        next,
        createNotebookCell(operation.cell_type ?? 'code', operation.source ?? '', {
          metadata: operation.metadata ?? {},
        }),
        operation.after_cell_id ?? null,
      )
    }
    case 'edit':
    case 'ai_edit':
    case 'replace_cell': {
      if (cellIndex < 0) {
        return next
      }
      const cell = next.cells[cellIndex]
      next.cells[cellIndex] = {
        ...cell,
        source: operation.source ?? cell.source,
        metadata: {
          ...cell.metadata,
          ...(operation.metadata ?? {}),
          ...(operation.reason ? { ai_reason: operation.reason } : {}),
        },
        cell_type: operation.cell_type ?? cell.cell_type,
        status: 'idle',
      }
      next.revision += 1
      next.updated_at = nowIso()
      return next
    }
    case 'edit_and_move': {
      if (cellIndex < 0) {
        return next
      }
      const existing = next.cells[cellIndex]
      const updated = createNotebookCell(operation.cell_type ?? existing.cell_type, operation.source ?? existing.source, {
        metadata: {
          ...existing.metadata,
          ...(operation.metadata ?? {}),
          ...(operation.reason ? { ai_reason: operation.reason } : {}),
          moved_from_cell_id: existing.id,
        },
      })
      next.cells.splice(cellIndex, 1)
      return insertCell(next, updated, operation.after_cell_id ?? null)
    }
    case 'delete_cell': {
      if (cellIndex < 0) {
        return next
      }
      next.cells.splice(cellIndex, 1)
      next.revision += 1
      next.updated_at = nowIso()
      return next
    }
    case 'move_cell': {
      if (cellIndex < 0) {
        return next
      }
      const [cell] = next.cells.splice(cellIndex, 1)
      const targetIndex = Math.max(
        0,
        Math.min(
          typeof operation.target_index === 'number' ? operation.target_index : next.cells.length,
          next.cells.length,
        ),
      )
      next.cells.splice(targetIndex, 0, cell)
      next.revision += 1
      next.updated_at = nowIso()
      return next
    }
    case 'apply_outputs': {
      if (cellIndex < 0) {
        return next
      }
      const cell = next.cells[cellIndex]
      next.cells[cellIndex] = {
        ...cell,
        outputs: operation.outputs ?? [],
        execution_count:
          typeof operation.execution_count === 'number'
            ? operation.execution_count
            : cell.execution_count,
        status: operation.status ?? 'finished',
      }
      next.revision += 1
      next.updated_at = nowIso()
      return next
    }
    default:
      return next
  }
}

export function markNotebookSaved(
  notebook: StudioNotebookDocument,
  savedAt = nowIso(),
): StudioNotebookDocument {
  return {
    ...cloneNotebook(notebook),
    last_saved_at: savedAt,
    updated_at: savedAt,
  }
}
