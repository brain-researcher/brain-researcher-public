'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type ProjectStatusCounts = {
  running: number
  completed: number
  failed: number
  other: number
}

type ProjectSummary = {
  project_id: string
  name?: string
  description?: string | null
  is_archived?: boolean
  run_count: number
  latest_run_id: string | null
  latest_status: string
  latest_created_at: number | null
  status_counts: ProjectStatusCounts
}

type ProjectsListResponse = {
  items: ProjectSummary[]
  count: number
  sampled_runs: number
  upstream_total_runs: number | null
  truncated: boolean
}

function formatTimestamp(value: number | null): string {
  if (!value || !Number.isFinite(value)) return '-'
  return new Date(value * 1000).toLocaleString()
}

function prettyProjectName(project: ProjectSummary): string {
  if (typeof project.name === 'string' && project.name.trim()) return project.name.trim()
  if (project.project_id === 'default') return 'Default project'
  return `Project ${project.project_id}`
}

export default function ProjectsPage() {
  const [items, setItems] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [truncated, setTruncated] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await fetch('/api/projects', {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load projects (${res.status})`)
        }
        const data = (await res.json()) as ProjectsListResponse
        setItems(Array.isArray(data.items) ? data.items : [])
        setTruncated(Boolean(data.truncated))
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'AbortError') {
          setError(err instanceof Error ? err.message : String(err))
          setItems([])
        }
      } finally {
        setLoading(false)
      }
    }

    void load()
    return () => controller.abort()
  }, [])

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Projects</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Projects group plans, runs, evidence, and handoffs for a focused line of work.
            </p>
          </div>

          {loading ? (
            <Card>
              <CardContent className="p-8">
                <div className="flex items-center justify-center">
                  <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                </div>
              </CardContent>
            </Card>
          ) : error ? (
            <Card>
              <CardContent className="p-6">
                <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                  {error}
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {items.map((project) => (
                <Card key={project.project_id}>
                  <CardContent className="p-6 space-y-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="text-base font-semibold text-gray-900">
                          {prettyProjectName(project)}
                        </div>
                        <div className="text-sm text-muted-foreground">
                          ID: {project.project_id} · Runs: {project.run_count} · Latest activity:{' '}
                          {formatTimestamp(project.latest_created_at)}
                        </div>
                        {typeof project.description === 'string' && project.description.trim() ? (
                          <div className="mt-1 text-sm text-muted-foreground">{project.description}</div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="secondary">Running {project.status_counts.running}</Badge>
                        <Badge variant="secondary">Completed {project.status_counts.completed}</Badge>
                        <Badge variant="secondary">Failed {project.status_counts.failed}</Badge>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <Button asChild>
                        <Link href={`/studio?project=${encodeURIComponent(project.project_id)}`}>
                          Review plan in Studio
                        </Link>
                      </Button>
                      <Button asChild variant="secondary">
                        <Link href={`/projects/${encodeURIComponent(project.project_id)}`}>
                          Review project
                        </Link>
                      </Button>
                      <Button asChild variant="outline">
                        <Link href={`/analyses?project_id=${encodeURIComponent(project.project_id)}`}>
                          View runs
                        </Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
              {truncated ? (
                <Card>
                  <CardContent className="p-4 text-sm text-muted-foreground">
                    Project summaries are sampled from recent runs. Open a project to review the latest evidence and next-step handoff.
                  </CardContent>
                </Card>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </NavigationWrapper>
  )
}
