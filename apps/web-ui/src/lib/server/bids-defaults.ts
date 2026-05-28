import { join } from 'node:path'

export type DatasetBidsHintSource = {
  id?: string
  source_repo_id?: string
  tasks?: string[]
  sessions_count?: number
}

export type BidsRunHints = {
  subject_id: string
  session_id?: string
  task_id: string
}

const DATASET_DEFAULT_RUN_HINTS: Record<string, Partial<BidsRunHints>> = {
  ds000114: {
    subject_id: '01',
    session_id: 'test',
  },
}

function sanitizePathToken(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '')
}

function trimTrailingPathSeparators(value: string): string {
  return value.replace(/[\\/]+$/g, '')
}

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function datasetToken(dataset?: DatasetBidsHintSource | null): string {
  const sourceRepoId = normalizeId(dataset?.source_repo_id)
  if (sourceRepoId) return sourceRepoId
  const rawId = normalizeId(dataset?.id)
  const openNeuroMatch = rawId.match(/^ds:openneuro:(.+)$/i)
  return openNeuroMatch?.[1] || rawId
}

export function normalizeBidsEntityHint(value: unknown, prefix: string): string {
  const trimmed = normalizeId(value)
  if (!trimmed) return ''
  const normalized = trimmed.replace(new RegExp(`^${prefix}-`, 'i'), '')
  return sanitizePathToken(normalized)
}

export function normalizeBidsTaskHint(value: unknown): string {
  const trimmed = normalizeId(value)
  if (!trimmed) return ''
  const normalized = trimmed.replace(/^task-/i, '')
  const task = normalized.toLowerCase().replace(/[^a-z0-9]+/g, '')
  if (['rest', 'resting', 'restingstate', 'reststate'].includes(task)) return 'rest'
  return task
}

function catalogTaskHints(dataset?: DatasetBidsHintSource | null): string[] {
  const tasks = Array.isArray(dataset?.tasks) ? dataset?.tasks : []
  const out: string[] = []
  const seen = new Set<string>()
  for (const task of tasks) {
    const normalized = normalizeBidsTaskHint(task)
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    out.push(normalized)
  }
  return out
}

function inferBidsEntityFromPath(value: string, prefix: string): string {
  const match = value.match(new RegExp(`(?:^|[\\\\/_])${prefix}-([A-Za-z0-9.-]+)(?=[\\\\/_]|$)`, 'i'))
  return match ? normalizeBidsEntityHint(match[1], prefix) : ''
}

export function inferBidsRunHintsFromPath(value: unknown): Partial<BidsRunHints> {
  const path = normalizeId(value)
  if (!path) return {}
  const subjectId = inferBidsEntityFromPath(path, 'sub')
  const sessionId = inferBidsEntityFromPath(path, 'ses')
  const taskMatch = path.match(/(?:^|[\\/_])task-([A-Za-z0-9.-]+)(?=[\\/_]|$)/i)
  const taskId = taskMatch ? normalizeBidsTaskHint(taskMatch[1]) : ''
  return {
    ...(subjectId ? { subject_id: subjectId } : {}),
    ...(sessionId ? { session_id: sessionId } : {}),
    ...(taskId ? { task_id: taskId } : {}),
  }
}

export function resolveDefaultBidsRunHints(
  dataset: DatasetBidsHintSource | null | undefined,
  args: Record<string, unknown> = {},
): BidsRunHints {
  const token = datasetToken(dataset)
  const datasetDefaults = DATASET_DEFAULT_RUN_HINTS[token] ?? {}
  const pathHints = inferBidsRunHintsFromPath(args.img ?? args.bold_img)
  const explicitTask =
    normalizeBidsTaskHint(args.task_id ?? args.task ?? args.task_name) ||
    normalizeBidsTaskHint(pathHints.task_id)
  const taskHints = catalogTaskHints(dataset)
  const taskId =
    explicitTask ||
    normalizeBidsTaskHint(datasetDefaults.task_id) ||
    (taskHints.includes('rest') ? 'rest' : taskHints[0]) ||
    'rest'

  const subjectId =
    normalizeBidsEntityHint(args.subject_id ?? args.subject, 'sub') ||
    normalizeBidsEntityHint(pathHints.subject_id, 'sub') ||
    normalizeBidsEntityHint(datasetDefaults.subject_id, 'sub') ||
    '01'
  const sessionId =
    normalizeBidsEntityHint(args.session_id ?? args.session, 'ses') ||
    normalizeBidsEntityHint(pathHints.session_id, 'ses') ||
    normalizeBidsEntityHint(datasetDefaults.session_id, 'ses') ||
    undefined

  return { subject_id: subjectId, session_id: sessionId, task_id: taskId }
}

export function inferBoldImgPathFromBidsDir(
  bidsDir: string,
  hints: BidsRunHints,
): string {
  const normalizedBidsDir = trimTrailingPathSeparators(bidsDir.trim())
  const subjectId = normalizeBidsEntityHint(hints.subject_id, 'sub') || '01'
  const sessionId = normalizeBidsEntityHint(hints.session_id, 'ses')
  const taskId = normalizeBidsTaskHint(hints.task_id) || 'rest'
  const subjectLabel = `sub-${subjectId}`
  const sessionLabel = sessionId ? `ses-${sessionId}` : ''
  const filename = sessionLabel
    ? `${subjectLabel}_${sessionLabel}_task-${taskId}_bold.nii.gz`
    : `${subjectLabel}_task-${taskId}_bold.nii.gz`

  if (!normalizedBidsDir) return filename
  const parts = [normalizedBidsDir, subjectLabel]
  if (sessionLabel) parts.push(sessionLabel)
  parts.push('func', filename)
  return join(...parts)
}

export function inferSessionIdFromPath(value: string): string | null {
  return inferBidsRunHintsFromPath(value).session_id || null
}
