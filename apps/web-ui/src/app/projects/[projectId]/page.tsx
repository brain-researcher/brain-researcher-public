'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  buildCodingAgentHandoffHrefFromAnalysis,
  buildStudioPlanHrefFromAnalysis,
} from '@/lib/analysis-links'
import type { AnalysesListResponse, AnalysisStatus, AnalysisSummary } from '@/types/analysis'

function toEpochMillis(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e11 ? value : value * 1000
  }
  if (typeof value === 'string' && value.trim()) {
    const ms = Date.parse(value)
    return Number.isFinite(ms) ? ms : null
  }
  return null
}

function formatTimestamp(value: unknown): string {
  const ms = toEpochMillis(value)
  if (!ms) return '-'
  return new Date(ms).toLocaleString()
}

function statusColor(status: AnalysisStatus): string {
  switch (status) {
    case 'queued':
    case 'pending':
      return 'bg-gray-100 text-gray-800'
    case 'running':
    case 'retrying':
    case 'cancelling':
      return 'bg-blue-100 text-blue-800'
    case 'completed':
      return 'bg-green-100 text-green-800'
    case 'failed':
    case 'timeout':
      return 'bg-red-100 text-red-800'
    case 'cancelled':
      return 'bg-yellow-100 text-yellow-800'
    default:
      return 'bg-gray-100 text-gray-600'
  }
}

export default function ProjectDetailPage({ params }: { params: { projectId: string } }) {
  const projectId = params?.projectId ? String(params.projectId) : 'default'

  const [items, setItems] = useState<AnalysisSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const query = new URLSearchParams({ limit: '20' })
        query.set('project_id', projectId || 'default')
        const res = await fetch(`/api/analyses?${query.toString()}`, {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load runs (${res.status})`)
        }
        const data = (await res.json()) as AnalysesListResponse
        setItems(Array.isArray(data.items) ? data.items : [])
      } catch (err: any) {
        if (err?.name !== 'AbortError') {
          setError(err instanceof Error ? err.message : String(err))
          setItems([])
        }
      } finally {
        setLoading(false)
      }
    }

    void load()
    return () => controller.abort()
  }, [projectId])

  const projectLabel = useMemo(() => {
    if (!projectId || projectId === 'default') return 'Default project'
    return `Project ${projectId}`
  }, [projectId])

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">{projectLabel}</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Review recent runs, evidence, and next-step handoffs for this project.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild>
                <Link href={`/studio?project=${encodeURIComponent(projectId || 'default')}`}>
                  Review plan in Studio
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/analyses">All Runs</Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/datasets">Datasets</Link>
              </Button>
            </div>
          </div>

          <Card>
            <CardContent className="p-6 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">Recent runs</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Review evidence, status, and full-run handoffs for this project.
                  </div>
                </div>
                <Button asChild size="sm" variant="outline">
                  <Link href="/analyses">View all runs</Link>
                </Button>
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-10">
                  <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                </div>
              ) : error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                  {error}
                </div>
              ) : items.length === 0 ? (
                <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
                  No runs yet. Start in <Link className="text-primary underline" href="/studio">Studio</Link> to draft and validate a plan.
                </div>
              ) : (
                <div className="space-y-3">
                  {items.map((analysis) => {
                    const studioPlanHref = buildStudioPlanHrefFromAnalysis(analysis)
                    const codingAgentHref = buildCodingAgentHandoffHrefFromAnalysis(analysis)

                    return (
                      <div
                        key={analysis.analysis_id}
                        className="rounded-lg border bg-card p-4 shadow-sm transition-shadow hover:shadow-md"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <Link
                                href={`/analyses/${encodeURIComponent(analysis.analysis_id)}`}
                                className="font-medium text-primary hover:underline"
                              >
                                {analysis.title || `Run ${analysis.analysis_id.slice(0, 8)}`}
                              </Link>
                              <Badge className={statusColor(analysis.status)}>{analysis.status}</Badge>
                            </div>
                            <div className="mt-1 flex flex-wrap gap-x-4 text-sm text-muted-foreground">
                              {analysis.dataset?.name ? (
                                <span>Dataset: {analysis.dataset.name}</span>
                              ) : analysis.dataset?.dataset_id ? (
                                <span>Dataset: {analysis.dataset.dataset_id}</span>
                              ) : null}
                              {analysis.template?.template_id ? (
                                <span>Workflow: {analysis.template.template_id}</span>
                              ) : null}
                              <span>Created: {formatTimestamp(analysis.created_at)}</span>
                            </div>
                          </div>
                          <div className="flex flex-shrink-0 items-center gap-2">
                            <Button variant="outline" size="sm" asChild>
                              <Link href={`/analyses/${encodeURIComponent(analysis.analysis_id)}`}>
                                Review evidence
                              </Link>
                            </Button>
                            {studioPlanHref ? (
                              <Button variant="outline" size="sm" asChild>
                                <Link href={studioPlanHref}>Review plan in Studio</Link>
                              </Button>
                            ) : null}
                            {codingAgentHref ? (
                              <Button size="sm" asChild>
                                <Link href={codingAgentHref}>Run via MCP in Codex/Cursor</Link>
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </NavigationWrapper>
  )
}
