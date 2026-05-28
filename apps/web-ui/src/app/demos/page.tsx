import Link from 'next/link'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Badge } from '@/components/ui/badge'
import {
  bundleArtifacts,
  loadDemoRunBundle,
} from '@/lib/server/demo-bundles'
import { loadDemoIndex } from '@/lib/server/demo-index'
import type { DemoIndexEntry } from '@/lib/server/demo-index'

type DemoCatalogEntry = DemoIndexEntry & {
  bundle_available: boolean
  bundle_artifact_count: number
  report_title?: string | null
  report_href?: string | null
}

function demoTier(demo: DemoIndexEntry): number {
  const slug = demo.slug.toLowerCase()
  const tags = (demo.tags || []).map((tag) => tag.toLowerCase())

  if (slug.startsWith('case1-') || tags.includes('case1')) return 1
  if (slug.startsWith('case2-') || tags.includes('case2')) return 2
  if (slug.startsWith('case3-') || tags.includes('case3')) return 3
  if (slug.startsWith('case4-') || tags.includes('case4')) return 4
  if (slug.startsWith('bounded-self-evolving-') || tags.includes('bounded-self-evolving')) {
    return 5
  }
  if (slug.startsWith('uc1-') || tags.includes('uc1')) return 6
  if (slug.startsWith('uc2-') || tags.includes('uc2')) return 7
  if (slug.startsWith('uc3-') || tags.includes('uc3')) return 8
  if (
    demo.demo_type === 'exploration' ||
    slug.includes('exploration') ||
    tags.includes('exploration')
  ) {
    return 9
  }
  return 10
}

function loadCatalogEntries(): DemoCatalogEntry[] {
  const index = loadDemoIndex()
  const demos = Array.isArray(index.demos) ? index.demos : []

  return demos
    .map((demo) => {
      const bundle = loadDemoRunBundle(demo.slug)
      const artifacts = bundleArtifacts(bundle)
      const reportArtifact =
        artifacts.find((artifact) =>
          artifact.roles?.includes('reference_summary_source') &&
          (artifact.mime_type || '').toLowerCase().includes('pdf'),
        ) ??
        artifacts.find((artifact) =>
          (artifact.mime_type || '').toLowerCase().includes('pdf') ||
          artifact.path.toLowerCase().endsWith('.pdf'),
        )
      return {
        ...demo,
        bundle_available: Boolean(bundle),
        bundle_artifact_count:
          typeof bundle?.artifact_count === 'number'
            ? bundle.artifact_count
            : artifacts.length,
        report_title: reportArtifact?.title || demo.report_title || null,
        report_href: reportArtifact
          ? `/api/demo/bundles/${encodeURIComponent(demo.slug)}/artifact?path=${encodeURIComponent(
              reportArtifact.id || reportArtifact.path,
            )}`
          : null,
      }
    })
    .sort((a, b) => {
      const tierDiff = demoTier(a) - demoTier(b)
      if (tierDiff !== 0) return tierDiff
      return a.slug.localeCompare(b.slug)
    })
}

function formatEvidenceMode(value: DemoIndexEntry['evidence_mode']): string {
  if (value === 'real') return 'Real evidence'
  if (value === 'hybrid') return 'Hybrid evidence'
  if (value === 'template') return 'Template'
  return 'Evidence bundle'
}

function formatDemoType(value: string | undefined): string {
  if (!value) return 'Replay'
  return value
    .split(/[_-]+/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export default function DemosPage() {
  const demos = loadCatalogEntries()

  return (
    <NavigationWrapper>
      <main className="min-h-screen bg-background">
        <section className="border-b bg-muted/30">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 py-10">
            <div className="text-sm font-medium uppercase text-muted-foreground">
              Demo catalog
            </div>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-normal text-foreground">
              Demos and use cases
            </h1>
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
              Public use-case reports with replay evidence, artifact packages, and MCP handoff
              context. These are the release-facing examples people can inspect before running
              their own workflow.
            </p>
            <div className="flex flex-wrap gap-2 pt-2">
              <Link
                href="/mcp/setup"
                className="inline-flex h-9 items-center rounded-md border bg-background px-4 text-sm font-medium hover:bg-muted"
              >
                MCP setup
              </Link>
              <Link
                href="/library"
                className="inline-flex h-9 items-center rounded-md border bg-background px-4 text-sm font-medium hover:bg-muted"
              >
                Workflow library
              </Link>
            </div>
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-6 py-8">
          {demos.length === 0 ? (
            <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
              No demos are currently published.
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {demos.map((demo) => (
                <article
                  key={demo.slug}
                  className="flex min-h-64 flex-col justify-between rounded-lg border bg-card p-5 shadow-sm"
                >
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">Use case</Badge>
                      <Badge variant="outline">{formatEvidenceMode(demo.evidence_mode)}</Badge>
                      <Badge variant="secondary">{formatDemoType(demo.demo_type)}</Badge>
                      {demo.stage_tags?.slice(0, 2).map((tag) => (
                        <Badge key={tag} variant="outline">
                          {tag}
                        </Badge>
                      ))}
                      {demo.bundle_available ? (
                        <Badge variant="outline">
                          {demo.bundle_artifact_count} artifact
                          {demo.bundle_artifact_count === 1 ? '' : 's'}
                        </Badge>
                      ) : null}
                    </div>

                    <div className="space-y-2">
                      <h2 className="text-xl font-semibold tracking-normal text-foreground">
                        {demo.title}
                      </h2>
                      {demo.description ? (
                        <p className="text-sm leading-6 text-muted-foreground">
                          {demo.description}
                        </p>
                      ) : null}
                      {demo.report_title ? (
                        <p className="text-xs leading-5 text-muted-foreground">
                          Report: {demo.report_title}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                    <div className="truncate text-xs text-muted-foreground">{demo.slug}</div>
                    <div className="flex flex-wrap justify-end gap-2">
                      {demo.report_href ? (
                        <Link
                          href={demo.report_href}
                          className="inline-flex h-9 shrink-0 items-center rounded-md border bg-background px-4 text-sm font-medium hover:bg-muted"
                        >
                          Open report PDF
                        </Link>
                      ) : null}
                      <Link
                        href={`/demos/${encodeURIComponent(demo.slug)}`}
                        className="inline-flex h-9 shrink-0 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                      >
                        Open use case
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </NavigationWrapper>
  )
}

export const dynamic = 'force-dynamic'
