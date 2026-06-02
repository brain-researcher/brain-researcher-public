'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'

type BundleItem = {
  id?: string
  name: string
  path: string
  download_url: string
  mime_type?: string
  title?: string | null
  roles?: string[]
}

type ReplayPayload = {
  demo: {
    slug: string
    title: string
  }
  analysis: {
    analysis_id: string
    status: string
    title?: string
  }
  bundle: {
    available: boolean
    items: BundleItem[]
  }
}

type Props = {
  demoId: string
}

function isPdfArtifact(item: BundleItem): boolean {
  const mime = (item.mime_type || '').toLowerCase()
  return mime.includes('pdf') || item.path.toLowerCase().endsWith('.pdf')
}

function withDownloadParam(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}download=1`
}

export function DemoReplayWorkbench({ demoId }: Props) {
  const [payload, setPayload] = useState<ReplayPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const res = await fetch(`/api/demo/replay/${encodeURIComponent(demoId)}`, {
          method: 'GET',
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!res.ok) {
          const body = await res
            .clone()
            .json()
            .catch(() => ({}))
          throw new Error(body?.detail || `Failed to load demo report (${res.status})`)
        }
        const data = (await res.json()) as ReplayPayload
        setPayload(data)
      } catch (err: any) {
        if (err.name === 'AbortError') return
        setError(err.message || 'Failed to load demo report.')
      } finally {
        setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [demoId])

  const primaryReportArtifact = useMemo(() => {
    if (!payload) return null
    const pdfArtifacts = payload.bundle.items.filter(isPdfArtifact)
    return (
      pdfArtifacts.find((item) => item.roles?.includes('reference_summary_source')) ||
      pdfArtifacts[0] ||
      null
    )
  }, [payload])

  if (loading) {
    return (
      <NavigationWrapper>
        <div className="flex min-h-screen items-center justify-center bg-gray-50">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </NavigationWrapper>
    )
  }

  if (error || !payload) {
    return (
      <NavigationWrapper>
        <div className="min-h-screen bg-gray-50">
          <div className="mx-auto max-w-5xl px-4 py-8">
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
              {error || 'Demo report not found.'}
            </div>
          </div>
        </div>
      </NavigationWrapper>
    )
  }

  const pageTitle = primaryReportArtifact?.title || payload.analysis.title || payload.demo.title

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-7xl space-y-4 px-4 py-8 sm:px-6 lg:px-8">
          <Link href="/demos" className="text-sm text-muted-foreground hover:text-primary">
            Back to Demos
          </Link>

          {primaryReportArtifact ? (
            <section className="rounded-lg border bg-card p-4 space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h1 className="text-2xl font-semibold tracking-tight">{pageTitle}</h1>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {primaryReportArtifact.name}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" asChild>
                    <a href={primaryReportArtifact.download_url} target="_blank" rel="noreferrer">
                      Open PDF
                    </a>
                  </Button>
                  <Button size="sm" variant="secondary" asChild>
                    <a href={withDownloadParam(primaryReportArtifact.download_url)}>Download</a>
                  </Button>
                </div>
              </div>
              <iframe
                title="Demo report PDF"
                src={primaryReportArtifact.download_url}
                className="h-[78vh] min-h-[620px] w-full rounded border bg-white"
              />
            </section>
          ) : (
            <section className="rounded-lg border bg-card p-4">
              <h1 className="text-2xl font-semibold tracking-tight">
                {payload.analysis.title || payload.demo.title}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                No PDF report is available for this demo.
              </p>
            </section>
          )}
        </div>
      </div>
    </NavigationWrapper>
  )
}
