"use client"

import dynamic from "next/dynamic"
import { useEffect, useState } from "react"

import { AdvancedViewBanner } from "@/components/advanced/advanced-view-banner"
import { NavigationWrapper } from "@/components/navigation/navigation-wrapper"
import { AnalysisStreamEventsPanel } from "@/components/progress/analysis-stream-events-panel"
import { Badge } from "@/components/ui/badge"
import { getJSON } from "@/lib/api"

const StepsList = dynamic(() => import("@/components/landing/StepsList"), { ssr: false })

type JobMetadata = {
  cached?: boolean
  plan_summary?: {
    plan_id?: string
    version?: number
    plan_status?: string
    step_count?: number
    por_token_set?: boolean
    plan_conf?: number
    confidence_score?: number
  }
  metadata?: {
    cache?: { hit?: boolean }
    cache_hit?: boolean
  }
}

export default function JobStepsPage({ params }: { params: { jobId: string } }) {
  const { jobId } = params
  const [jobDetails, setJobDetails] = useState<JobMetadata | null>(null)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    getJSON<{ job?: JobMetadata }>(`/api/analyses/${jobId}`, { signal: controller.signal })
      .then((data) => {
        if (!cancelled) {
          setJobDetails(data.job ?? null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setJobDetails(null)
        }
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [jobId])

  const cacheMeta = jobDetails?.metadata?.cache
  const isCached = Boolean(cacheMeta?.hit ?? jobDetails?.metadata?.cache_hit ?? jobDetails?.cached)
  const planSummary = jobDetails?.plan_summary
  const planConfidence =
    planSummary?.plan_conf ?? planSummary?.confidence_score
  const planConfidencePct =
    typeof planConfidence === 'number' ? Math.round(planConfidence * 100) : null

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-10">
          <AdvancedViewBanner canonicalHref={`/analyses/${encodeURIComponent(jobId)}`} />

          <header className="space-y-1">
            <div className="flex items-center gap-3">
              <div>
                <p className="text-sm text-muted-foreground">Pipeline Execution</p>
                <h1 className="text-2xl font-semibold tracking-tight">Job {jobId}</h1>
              </div>
              {isCached && (
                <Badge variant="secondary" className="bg-emerald-50 text-emerald-700">
                  From cache
                </Badge>
              )}
              {planConfidencePct !== null && (
                <Badge variant="outline" className="bg-slate-50 text-slate-700">
                  Plan confidence: {planConfidencePct}%
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Real-time step summaries and per-step log streaming powered by the orchestrator.
            </p>
            {planSummary && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>Plan ID: {planSummary.plan_id ?? 'N/A'}</span>
                <span>•</span>
                <span>Status: {planSummary.plan_status ?? 'N/A'}</span>
                <span>•</span>
                <span>Steps: {planSummary.step_count ?? 0}</span>
              </div>
            )}
          </header>

          <section className="rounded-lg border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-medium">Step Summaries</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              Follow each pipeline step as it runs. Click <strong>View logs</strong> to open the live tail for a step.
            </p>
            <StepsList jobId={jobId} enableStreaming />
          </section>

          <section className="rounded-lg border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-medium">Typed Event Stream</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              Debug view of typed analysis stream events (tool calls, logs, artifacts). Unknown events are shown with raw JSON.
            </p>
            <AnalysisStreamEventsPanel analysisId={jobId} />
          </section>
        </main>
      </div>
    </NavigationWrapper>
  )
}
