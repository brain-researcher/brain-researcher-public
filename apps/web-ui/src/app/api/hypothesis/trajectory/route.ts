import { NextRequest, NextResponse } from 'next/server'

import {
  type HotLoadTrajectoryExportRow,
  extractHotLoadTrajectoryRow,
  summarizeHotLoadTrajectoryRows,
} from '@/lib/server/hypothesis-hot-load-trajectory'
import {
  getRunSnapshotPersisted,
  getRunSnapshotsForSessionPersisted,
} from '@/lib/server/hypothesis-run-store'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function asPositiveInt(value: string | null, fallback: number): number {
  const parsed = value ? Number(value) : NaN
  if (Number.isFinite(parsed) && parsed > 0) return Math.trunc(parsed)
  return fallback
}

function asBooleanFlag(value: string | null): boolean {
  if (!value) return false
  const normalized = value.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

function asOptionalBoolean(value: string | null): boolean | null {
  if (!value) return null
  const normalized = value.trim().toLowerCase()
  if (normalized === '1' || normalized === 'true' || normalized === 'yes') return true
  if (normalized === '0' || normalized === 'false' || normalized === 'no') return false
  return null
}

function filterRows(
  rows: HotLoadTrajectoryExportRow[],
  filters: {
    deepResearchStatus: string | null
    verificationSource: string | null
    mcpFallbackUsed: boolean | null
    queryContains: string | null
  },
): HotLoadTrajectoryExportRow[] {
  const queryNeedle = (filters.queryContains || '').trim().toLowerCase()
  return rows.filter((row) => {
    if (filters.deepResearchStatus && row.deep_research_status !== filters.deepResearchStatus) {
      return false
    }
    if (filters.verificationSource && row.verification_source !== filters.verificationSource) {
      return false
    }
    if (
      filters.mcpFallbackUsed !== null &&
      row.mcp_fallback_used !== filters.mcpFallbackUsed
    ) {
      return false
    }
    if (
      queryNeedle &&
      !row.query.toLowerCase().includes(queryNeedle) &&
      !row.query_normalized.toLowerCase().includes(queryNeedle)
    ) {
      return false
    }
    return true
  })
}

export async function GET(req: NextRequest) {
  const sessionId =
    req.nextUrl.searchParams.get('sessionId') ||
    req.nextUrl.searchParams.get('session_id') ||
    ''
  const runId = req.nextUrl.searchParams.get('runId') || req.nextUrl.searchParams.get('run_id') || ''
  const limit = asPositiveInt(req.nextUrl.searchParams.get('limit'), 30)
  const jsonl = asBooleanFlag(req.nextUrl.searchParams.get('jsonl'))
  const download = asBooleanFlag(req.nextUrl.searchParams.get('download'))
  const deepResearchStatus =
    req.nextUrl.searchParams.get('deepResearchStatus') ||
    req.nextUrl.searchParams.get('deep_research_status')
  const verificationSource =
    req.nextUrl.searchParams.get('verificationSource') ||
    req.nextUrl.searchParams.get('verification_source')
  const mcpFallbackUsed = asOptionalBoolean(
    req.nextUrl.searchParams.get('mcpFallbackUsed') ||
      req.nextUrl.searchParams.get('mcp_fallback_used'),
  )
  const queryContains =
    req.nextUrl.searchParams.get('queryContains') ||
    req.nextUrl.searchParams.get('query_contains') ||
    req.nextUrl.searchParams.get('q')

  if (!sessionId.trim() && !runId.trim()) {
    return NextResponse.json(
      {
        error: 'missing_target',
        message: 'sessionId or runId is required.',
      },
      { status: 400 },
    )
  }

  const snapshots = runId.trim()
    ? [await getRunSnapshotPersisted(runId.trim())].filter(Boolean)
    : await getRunSnapshotsForSessionPersisted({
        sessionId: sessionId.trim(),
        limit,
      })

  const extractedRows = snapshots
    .map((snapshot) => (snapshot ? extractHotLoadTrajectoryRow(snapshot) : null))
    .filter((row): row is NonNullable<typeof row> => Boolean(row))
  const rows = filterRows(extractedRows, {
    deepResearchStatus: deepResearchStatus?.trim() || null,
    verificationSource: verificationSource?.trim() || null,
    mcpFallbackUsed,
    queryContains: queryContains?.trim() || null,
  })

  if (jsonl) {
    const body = rows.map((row) => JSON.stringify(row)).join('\n')
    const filename = runId.trim()
      ? `hot-load-trajectory-${runId.trim()}.jsonl`
      : `hot-load-trajectory-${sessionId.trim() || 'session'}.jsonl`
    return new Response(body ? `${body}\n` : '', {
      status: 200,
      headers: {
        'content-type': 'application/x-ndjson; charset=utf-8',
        ...(download
          ? {
              'content-disposition': `attachment; filename="${filename}"`,
            }
          : {}),
      },
    })
  }

  return NextResponse.json({
    ok: true,
    target: runId.trim()
      ? {
          run_id: runId.trim(),
        }
      : {
          session_id: sessionId.trim(),
          limit,
        },
    filters: {
      deep_research_status: deepResearchStatus?.trim() || null,
      verification_source: verificationSource?.trim() || null,
      mcp_fallback_used: mcpFallbackUsed,
      query_contains: queryContains?.trim() || null,
    },
    summary: summarizeHotLoadTrajectoryRows(rows),
    rows,
  })
}
