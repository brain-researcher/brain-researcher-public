"use client"

import { useEffect, useState } from "react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { NavigationWrapper } from "@/components/navigation/navigation-wrapper"
import { AdvancedViewBanner } from "@/components/advanced/advanced-view-banner"

type ServiceStatus = {
  name: string
  status: string
  latency_ms?: number | null
  detail?: string
}

type Neo4jStats = {
  status?: string
  backend?: string
  node_count?: number
  relationship_count?: number
  node_labels?: string[]
  relationship_types?: string[]
  error?: string
}

type HealthPayload = {
  status: string
  services: ServiceStatus[]
  queue?: Record<string, any>
  neo4j?: Neo4jStats
  env?: string
  build_git_sha?: string | null
  duration_ms?: number
  timestamp?: number
}

const statusTone = (status?: string) => {
  switch (status) {
    case "ok":
    case "healthy":
      return "bg-emerald-100 text-emerald-800"
    case "degraded":
      return "bg-amber-100 text-amber-800"
    case "down":
    case "error":
      return "bg-rose-100 text-rose-800"
    default:
      return "bg-slate-100 text-slate-700"
  }
}

const formatMs = (ms?: number | null) =>
  typeof ms === "number" ? `${ms.toFixed(0)} ms` : "–"

const formatCount = (value?: number | null) =>
  typeof value === "number" ? value.toLocaleString() : "–"

export default function StatusPage() {
  const [data, setData] = useState<HealthPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch("/api/health/full", { cache: "no-store" })
        if (!res.ok) throw new Error(`status ${res.status}`)
        const json = (await res.json()) as HealthPayload
        if (!cancelled) setData(json)
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "failed to load")
      }
    }
    load()
    const id = setInterval(load, 15000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const overall = data?.status || "unknown"

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <AdvancedViewBanner canonicalHref="/settings" />
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">System Status</h1>
              <p className="text-sm text-muted-foreground">
                Live health snapshot from Agent aggregation.
              </p>
            </div>
            <Badge className={statusTone(overall)}>{overall}</Badge>
          </div>

          {error && (
            <Card>
              <CardContent className="py-4 text-sm text-rose-700">
                Failed to load health: {error}
              </CardContent>
            </Card>
          )}

          {data && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Services</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {data.services?.length ? (
                    data.services.map((svc) => (
                      <div
                        key={svc.name}
                        className="flex items-center justify-between rounded-md border p-3 bg-white"
                      >
                        <div className="flex items-center gap-3">
                          <Badge className={statusTone(svc.status)}>{svc.status}</Badge>
                          <div className="font-medium">{svc.name}</div>
                        </div>
                        <div className="text-sm text-muted-foreground flex items-center gap-3">
                          <span>{formatMs(svc.latency_ms)}</span>
                          {svc.detail && <span className="text-amber-700">{svc.detail}</span>}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Job Queue</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {data.queue ? (
                    <>
                      <div className="flex gap-3">
                        <span className="font-medium">queued:</span>
                        <span>{data.queue.queued ?? data.queue.queue_depth ?? "–"}</span>
                      </div>
                      <div className="flex gap-3">
                        <span className="font-medium">oldest_pending_age_sec:</span>
                        <span>{data.queue.oldest_pending_age_sec ?? "–"}</span>
                      </div>
                      <div className="flex gap-3">
                        <span className="font-medium">active_workers:</span>
                        <span>{data.queue.active_workers ?? "–"}</span>
                      </div>
                    </>
                  ) : (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  )}
                </CardContent>
              </Card>

              {data.neo4j && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between">
                      <span>Neo4j Database</span>
                      {data.neo4j.status && (
                        <Badge className={statusTone(data.neo4j.status)}>
                          {data.neo4j.status}
                        </Badge>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex gap-3">
                      <span className="font-medium">backend:</span>
                      <span>{data.neo4j.backend ?? "–"}</span>
                    </div>
                    <div className="flex gap-3">
                      <span className="font-medium">node_count:</span>
                      <span>{formatCount(data.neo4j.node_count)}</span>
                    </div>
                    <div className="flex gap-3">
                      <span className="font-medium">relationship_count:</span>
                      <span>{formatCount(data.neo4j.relationship_count)}</span>
                    </div>
                    {data.neo4j.node_labels && data.neo4j.node_labels.length > 0 && (
                      <div className="flex gap-3">
                        <span className="font-medium">labels:</span>
                        <span className="text-muted-foreground">
                          {data.neo4j.node_labels.slice(0, 5).join(", ")}
                          {data.neo4j.node_labels.length > 5 && ` (+${data.neo4j.node_labels.length - 5} more)`}
                        </span>
                      </div>
                    )}
                    {data.neo4j.error && (
                      <div className="text-rose-600 text-xs mt-2">
                        Error: {data.neo4j.error}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle>Metadata</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-4 text-sm">
                  <div className="flex gap-2">
                    <span className="font-medium">env:</span>
                    <span>{data.env || "dev"}</span>
                  </div>
                  <Separator orientation="vertical" className="h-4" />
                  <div className="flex gap-2">
                    <span className="font-medium">git:</span>
                    <span>{data.build_git_sha || "n/a"}</span>
                  </div>
                  <Separator orientation="vertical" className="h-4" />
                  <div className="flex gap-2">
                    <span className="font-medium">generated:</span>
                    <span>
                      {data.timestamp
                        ? new Date(data.timestamp * 1000).toLocaleString()
                        : "–"}
                    </span>
                  </div>
                  <Separator orientation="vertical" className="h-4" />
                  <div className="flex gap-2">
                    <span className="font-medium">compute:</span>
                    <span>{data.duration_ms ? `${data.duration_ms} ms` : "–"}</span>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </NavigationWrapper>
  )
}
