function asRecord(value: unknown): Record<string, any> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, any>)
    : undefined
}

export function normalizeCheckpointId(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized.length > 0 ? normalized : undefined
}

/**
 * Boundary-only compatibility shim for checkpoint payloads.
 * Internal UI state should use `lastCheckpointId` plus canonical
 * `metadata.checkpoint_id`.
 */
export function extractCheckpointIdFromBoundary(payload: unknown): string | undefined {
  const root = asRecord(payload)
  if (!root) return undefined

  const metadata = asRecord(root.metadata)
  const messageMetadata = asRecord(asRecord(root.message)?.metadata)

  return (
    normalizeCheckpointId(metadata?.checkpoint_id) ||
    normalizeCheckpointId(metadata?.last_checkpoint_id) ||
    normalizeCheckpointId(root.resume_checkpoint_id) ||
    normalizeCheckpointId(root.resumeCheckpointId) ||
    normalizeCheckpointId(root.checkpoint_id) ||
    normalizeCheckpointId(root.last_checkpoint_id) ||
    normalizeCheckpointId(root.checkpointId) ||
    normalizeCheckpointId(root.lastCheckpointId) ||
    normalizeCheckpointId(messageMetadata?.checkpoint_id) ||
    normalizeCheckpointId(messageMetadata?.last_checkpoint_id)
  )
}

export function normalizeCheckpointMetadata(
  metadata: unknown,
  checkpointId?: string,
): Record<string, any> | undefined {
  const normalized = { ...(asRecord(metadata) || {}) }
  const canonical =
    checkpointId ||
    normalizeCheckpointId(normalized.checkpoint_id) ||
    normalizeCheckpointId(normalized.last_checkpoint_id) ||
    normalizeCheckpointId(normalized.checkpointId) ||
    normalizeCheckpointId(normalized.lastCheckpointId)

  delete normalized.last_checkpoint_id
  delete normalized.lastCheckpointId
  delete normalized.checkpointId

  if (canonical) {
    normalized.checkpoint_id = canonical
  }

  return Object.keys(normalized).length ? normalized : undefined
}

export function buildCheckpointMessagePatch(options: {
  payload?: unknown
  metadata?: unknown
  fallbackCheckpointId?: string
}): { metadata?: Record<string, any>; lastCheckpointId?: string } {
  const checkpointId =
    extractCheckpointIdFromBoundary(options.payload) ||
    normalizeCheckpointId(options.fallbackCheckpointId)
  const metadata = normalizeCheckpointMetadata(options.metadata, checkpointId)

  return {
    ...(metadata ? { metadata } : {}),
    ...(checkpointId ? { lastCheckpointId: checkpointId } : {}),
  }
}

export function withResumeCheckpointInContext(
  ctx: Record<string, any> | undefined,
  resumeCheckpointId: string | null | undefined,
): Record<string, any> | undefined {
  const nextCtx = { ...(ctx || {}) }
  const normalized =
    normalizeCheckpointId(resumeCheckpointId) ||
    normalizeCheckpointId(nextCtx.resume_checkpoint_id) ||
    extractCheckpointIdFromBoundary(nextCtx)

  delete nextCtx.resumeCheckpointId
  delete nextCtx.checkpoint_id
  delete nextCtx.checkpointId

  if (normalized) {
    nextCtx.resume_checkpoint_id = normalized
  } else {
    delete nextCtx.resume_checkpoint_id
  }
  return Object.keys(nextCtx).length ? nextCtx : undefined
}
