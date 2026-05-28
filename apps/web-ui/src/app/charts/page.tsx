'use client'

import Link from 'next/link'
import Image from 'next/image'
import { useMemo, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useSession } from 'next-auth/react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  parseCsvPreview,
  splitDemoChartArtifacts,
  type CsvPreview,
  type DemoBundleArtifactItem,
} from '@/lib/charts/demo-chart-artifacts'

type DemoIndexEntry = {
  slug: string
  title: string
  description?: string
  is_template?: boolean
  bundle_available?: boolean
  bundle_artifact_count?: number
}

type DemoIndexResponse = {
  demos: DemoIndexEntry[]
}

type DemoBundleResponse = {
  slug: string
  available: boolean
  artifact_count: number
  generated_at?: string | null
  source_run_ids?: string[]
  items: DemoBundleArtifactItem[]
}

function artifactKey(artifact: DemoBundleArtifactItem): string {
  return String(artifact.id || artifact.path || '').trim()
}

function artifactLabel(artifact: DemoBundleArtifactItem): string {
  const title = String(artifact.title || '').trim()
  if (title) return title
  const name = String(artifact.name || '').trim()
  if (name) return name
  const cleanPath = String(artifact.path || '').replace(/\\/g, '/')
  return cleanPath.split('/').filter(Boolean).pop() || cleanPath || 'artifact'
}

export default function ChartsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { status: sessionStatus } = useSession()

  const [demos, setDemos] = useState<DemoIndexEntry[]>([])
  const [demosLoading, setDemosLoading] = useState(true)
  const [demosError, setDemosError] = useState<string | null>(null)

  const [bundle, setBundle] = useState<DemoBundleResponse | null>(null)
  const [bundleLoading, setBundleLoading] = useState(false)
  const [bundleError, setBundleError] = useState<string | null>(null)

  const [csvPreviews, setCsvPreviews] = useState<Record<string, CsvPreview | null>>({})
  const [csvPreviewLoading, setCsvPreviewLoading] = useState<Record<string, boolean>>({})

  const selectedSlug = searchParams.get('demo')?.trim() || ''
  const selectedDemo = useMemo(
    () => demos.find((demo) => demo.slug === selectedSlug) || null,
    [demos, selectedSlug],
  )
  const selectedDemoMissing = Boolean(selectedSlug) && demos.length > 0 && !selectedDemo
  const isAuthenticated = sessionStatus === 'authenticated'
  const authLoading = sessionStatus === 'loading'

  useEffect(() => {
    let active = true

    const loadDemos = async () => {
      try {
        setDemosLoading(true)
        setDemosError(null)
        const res = await fetch('/api/demo/index', { cache: 'no-store' })
        if (!res.ok) {
          throw new Error(`Failed to load demos (${res.status})`)
        }
        const payload = (await res.json()) as DemoIndexResponse
        if (!active) return
        setDemos(Array.isArray(payload.demos) ? payload.demos : [])
      } catch (err) {
        if (!active) return
        const detail = err instanceof Error ? err.message : 'Failed to load demos.'
        setDemosError(detail)
        setDemos([])
      } finally {
        if (active) setDemosLoading(false)
      }
    }

    loadDemos()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (demosLoading || selectedSlug) {
      return
    }
    if (!searchParams.has('demo') && demos.length > 0) {
      const defaultDemo = demos.find((item) => item.bundle_available !== false) || demos[0]
      if (!defaultDemo?.slug) return
      const params = new URLSearchParams(searchParams.toString())
      params.set('demo', defaultDemo.slug)
      const suffix = params.toString()
      router.replace(suffix ? `/charts?${suffix}` : '/charts', { scroll: false })
    }
  }, [demos, demosLoading, selectedSlug, searchParams, router])

  useEffect(() => {
    let active = true

    const loadBundle = async () => {
      if (!selectedDemo || !isAuthenticated) {
        setBundle(null)
        setBundleError(null)
        setBundleLoading(false)
        setCsvPreviews({})
        setCsvPreviewLoading({})
        return
      }

      try {
        setBundleLoading(true)
        setBundleError(null)
        setCsvPreviews({})
        setCsvPreviewLoading({})

        const res = await fetch(`/api/demo/bundles/${encodeURIComponent(selectedDemo.slug)}`, {
          cache: 'no-store',
        })
        if (!res.ok) {
          throw new Error(`Failed to load bundle (${res.status})`)
        }
        const payload = (await res.json()) as DemoBundleResponse
        if (!active) return
        setBundle(payload)
      } catch (err) {
        if (!active) return
        const detail = err instanceof Error ? err.message : 'Failed to load bundle.'
        setBundle(null)
        setBundleError(detail)
      } finally {
        if (active) setBundleLoading(false)
      }
    }

    loadBundle()
    return () => {
      active = false
    }
  }, [selectedDemo, isAuthenticated])

  const chartArtifacts = useMemo(() => {
    return splitDemoChartArtifacts(bundle?.items || [])
  }, [bundle])

  useEffect(() => {
    let active = true
    const csvArtifacts = chartArtifacts.csvs.slice(0, 4)

    if (!isAuthenticated || !selectedDemo || !bundle?.available || csvArtifacts.length === 0) {
      setCsvPreviews({})
      setCsvPreviewLoading({})
      return
    }

    const loadCsvPreviews = async () => {
      const loadingMap = Object.fromEntries(
        csvArtifacts.map((artifact) => [artifactKey(artifact), true]),
      )
      if (active) setCsvPreviewLoading(loadingMap)

      const results = await Promise.all(
        csvArtifacts.map(async (artifact) => {
          const key = artifactKey(artifact)
          try {
            const res = await fetch(artifact.download_url, { cache: 'no-store' })
            if (!res.ok) return [key, null] as const
            const text = await res.text()
            return [key, parseCsvPreview(text, 10, 8)] as const
          } catch {
            return [key, null] as const
          }
        }),
      )

      if (!active) return
      const previewMap: Record<string, CsvPreview | null> = {}
      for (const [key, preview] of results) {
        previewMap[key] = preview
      }
      setCsvPreviews(previewMap)
      setCsvPreviewLoading(Object.fromEntries(csvArtifacts.map((artifact) => [artifactKey(artifact), false])))
    }

    loadCsvPreviews()
    return () => {
      active = false
    }
  }, [chartArtifacts.csvs, isAuthenticated, selectedDemo, bundle])

  const loginCallback =
    selectedSlug.length > 0 ? `/charts?demo=${encodeURIComponent(selectedSlug)}` : '/charts'

  const onSelectDemo = (value: string) => {
    const params = new URLSearchParams(searchParams.toString())
    if (value) params.set('demo', value)
    else params.delete('demo')
    const suffix = params.toString()
    router.replace(suffix ? `/charts?${suffix}` : '/charts', { scroll: false })
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto space-y-6 p-6">
          <div>
            <h1 className="text-3xl font-bold">Statistical Charts</h1>
            <p className="mt-2 text-gray-600">
              Browse demo-ready chart artifacts. Select a demo first, then sign in to load chart
              content.
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Choose A Demo</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-gray-600">
              {demosLoading ? (
                <div>Loading demos...</div>
              ) : null}
              {demosError ? (
                <Alert>
                  <AlertDescription>{demosError}</AlertDescription>
                </Alert>
              ) : null}
              <label className="flex flex-col gap-2">
                <span className="text-sm font-medium text-gray-700">Demo</span>
                <select
                  className="h-10 rounded-md border border-input bg-white px-3 text-sm"
                  value={selectedSlug}
                  onChange={(event) => onSelectDemo(event.target.value)}
                >
                  <option value="">Select a demo...</option>
                  {demos.map((demo) => (
                    <option key={demo.slug} value={demo.slug}>
                      {demo.title}
                    </option>
                  ))}
                </select>
              </label>

              {selectedDemo ? (
                <div className="rounded-md border bg-white p-3">
                  <div className="text-sm font-medium text-gray-900">{selectedDemo.title}</div>
                  <div className="mt-1 text-sm text-gray-600">
                    {selectedDemo.description || 'No description available.'}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Bundle artifacts:{' '}
                    {typeof selectedDemo.bundle_artifact_count === 'number'
                      ? selectedDemo.bundle_artifact_count
                      : 'n/a'}
                  </div>
                </div>
              ) : null}

              {!selectedSlug ? (
                <Alert>
                  <AlertDescription>
                    Select a demo to load chart previews for this page.
                  </AlertDescription>
                </Alert>
              ) : null}

              {selectedDemoMissing ? (
                <Alert>
                  <AlertDescription>
                    Demo &quot;{selectedSlug}&quot; was not found. Pick a valid demo from the list.
                  </AlertDescription>
                </Alert>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <Button asChild>
                  <Link href="/demos">Browse all demos</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/studio">Start a run</Link>
                </Button>
              </div>
            </CardContent>
          </Card>

          {selectedDemo && !selectedDemoMissing ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Chart Artifacts</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-gray-600">
                {authLoading ? (
                  <div>Checking sign-in status...</div>
                ) : null}

                {!authLoading && !isAuthenticated ? (
                  <Alert>
                    <AlertDescription>
                      Sign in to view all artifact content on the charts page.
                    </AlertDescription>
                  </Alert>
                ) : null}

                {!authLoading && !isAuthenticated ? (
                  <div className="flex flex-wrap gap-3">
                    <Button asChild>
                      <Link href={`/auth/login?callbackUrl=${encodeURIComponent(loginCallback)}`}>
                        Sign in to view charts
                      </Link>
                    </Button>
                    <Button asChild variant="outline">
                      <Link href="/auth/signup">Create account</Link>
                    </Button>
                  </div>
                ) : null}

                {isAuthenticated && bundleLoading ? <div>Loading chart artifacts...</div> : null}
                {isAuthenticated && bundleError ? (
                  <Alert>
                    <AlertDescription>{bundleError}</AlertDescription>
                  </Alert>
                ) : null}

                {isAuthenticated && !bundleLoading && !bundleError && !bundle?.available ? (
                  <Alert>
                    <AlertDescription>
                      This demo does not have a run bundle yet. Try another demo.
                    </AlertDescription>
                  </Alert>
                ) : null}

                {isAuthenticated &&
                bundle?.available &&
                chartArtifacts.images.length === 0 &&
                chartArtifacts.csvs.length === 0 ? (
                  <Alert>
                    <AlertDescription>
                      This bundle has no image/CSV chart artifacts yet.
                    </AlertDescription>
                  </Alert>
                ) : null}

                {isAuthenticated && bundle?.available && chartArtifacts.images.length > 0 ? (
                  <div className="space-y-3">
                    <div className="text-sm font-medium text-gray-900">
                      Image Charts ({chartArtifacts.images.length})
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      {chartArtifacts.images.map((artifact) => (
                        <Card key={artifactKey(artifact)}>
                          <CardHeader className="pb-2">
                            <CardTitle className="text-sm">{artifactLabel(artifact)}</CardTitle>
                          </CardHeader>
                          <CardContent className="space-y-3">
                            <Image
                              src={artifact.download_url}
                              alt={artifactLabel(artifact)}
                              width={1200}
                              height={800}
                              unoptimized
                              className="max-h-80 w-full rounded border object-contain bg-white"
                            />
                            <Button asChild variant="outline" size="sm">
                              <Link href={artifact.download_url} target="_blank" rel="noreferrer">
                                Open file
                              </Link>
                            </Button>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </div>
                ) : null}

                {isAuthenticated && bundle?.available && chartArtifacts.csvs.length > 0 ? (
                  <div className="space-y-3">
                    <div className="text-sm font-medium text-gray-900">
                      CSV Previews ({Math.min(chartArtifacts.csvs.length, 4)} shown)
                    </div>
                    {chartArtifacts.csvs.slice(0, 4).map((artifact) => {
                      const key = artifactKey(artifact)
                      const preview = csvPreviews[key]
                      const previewLoading = csvPreviewLoading[key]
                      return (
                        <Card key={key}>
                          <CardHeader className="pb-2">
                            <CardTitle className="text-sm">{artifactLabel(artifact)}</CardTitle>
                          </CardHeader>
                          <CardContent className="space-y-3">
                            {previewLoading ? <div>Loading preview...</div> : null}
                            {!previewLoading && !preview ? (
                              <div className="text-sm text-gray-500">
                                Preview unavailable for this CSV.
                              </div>
                            ) : null}
                            {!previewLoading && preview ? (
                              <div className="overflow-auto rounded border bg-white">
                                <table className="min-w-full text-xs">
                                  <thead className="bg-gray-100 text-gray-700">
                                    <tr>
                                      {preview.header.map((cell, idx) => (
                                        <th key={`${key}-h-${idx}`} className="px-2 py-1 text-left">
                                          {cell || `Column ${idx + 1}`}
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {preview.rows.map((row, rowIdx) => (
                                      <tr key={`${key}-r-${rowIdx}`} className="border-t">
                                        {row.map((cell, colIdx) => (
                                          <td
                                            key={`${key}-r-${rowIdx}-c-${colIdx}`}
                                            className="px-2 py-1 align-top"
                                          >
                                            {cell}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : null}
                            {preview?.truncated ? (
                              <div className="text-xs text-gray-500">
                                Preview truncated. Open the file for full content.
                              </div>
                            ) : null}
                            <Button asChild variant="outline" size="sm">
                              <Link href={artifact.download_url} target="_blank" rel="noreferrer">
                                Open file
                              </Link>
                            </Button>
                          </CardContent>
                        </Card>
                      )
                    })}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </NavigationWrapper>
  )
}
