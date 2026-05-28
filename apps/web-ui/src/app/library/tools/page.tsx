'use client'

import useSWR from 'swr'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useDebouncedValue } from '@/hooks/use-debounce'
import { serviceEndpoints } from '@/lib/service-endpoints'

type ToolRow = {
  name: string
  display_name?: string
  description?: string
  runtime: string
  runtime_kind?: string
  domain?: string
  modality?: string[]
  path?: string
  module?: string
  container_image?: string
  entrypoint?: string
  package?: string
  category?: string
  stage?: string
  layer?: string
  cost_tier?: string
  origin?: string
  impl?: string
  tags?: string[]
  function?: string
  risk?: string
  exposure?: string
  consumes?: Record<string, string>
  produces?: Record<string, string>
  confidence?: string
  source: string
}

type Category = { key: string; name: string; description?: string; examples?: string[] }

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export default function ToolCatalogPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('q') || '')
  const debouncedQuery = useDebouncedValue(searchQuery, 250)
  const trimmedQuery = debouncedQuery.trim()
  const sessionIdRef = useRef<string | null>(null)
  const lastTrackedRef = useRef<string>('')
  const lastAutoOpenedToolRef = useRef<string>('')
  const [selectedTool, setSelectedTool] = useState<ToolRow | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const locationHint =
    selectedTool?.path ||
    selectedTool?.module ||
    selectedTool?.container_image ||
    selectedTool?.entrypoint
      ? 'Workflows → Tool Catalog · Studio → Tool Catalog'
      : 'Agent accessible (no UI location metadata yet)'

  useEffect(() => {
    if (typeof window === 'undefined') return
    const existing = localStorage.getItem('searchSessionId')
    if (existing) {
      sessionIdRef.current = existing
      return
    }
    const generated = `search_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
    localStorage.setItem('searchSessionId', generated)
    sessionIdRef.current = generated
  }, [])

  useEffect(() => {
    const q = searchParams.get('q') || ''
    if (!q) return
    if (q === searchQuery) return
    setSearchQuery(q)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  useEffect(() => {
    const queryToTrack = trimmedQuery
    if (!queryToTrack) return
    if (queryToTrack.length < 2) return
    if (queryToTrack === lastTrackedRef.current) return
    lastTrackedRef.current = queryToTrack

    const controller = new AbortController()
    const track = async () => {
      try {
        const params = new URLSearchParams({ query: queryToTrack })
        if (sessionIdRef.current) {
          params.set('session_id', sessionIdRef.current)
        }
        await fetch(serviceEndpoints.orchestrator(`/api/search/track?${params.toString()}`), {
          method: 'POST',
          signal: controller.signal,
        })
      } catch (err) {
        // Tracking should never block tool browsing.
        console.warn('Failed to track tools search query:', err)
      }
    }

    void track()

    return () => controller.abort()
  }, [trimmedQuery])

  const apiUrl = useMemo(() => {
    if (!trimmedQuery) return '/api/tools/search'
    return `/api/tools/search?q=${encodeURIComponent(trimmedQuery)}`
  }, [trimmedQuery])

  const { data, error } = useSWR<{ tools: ToolRow[]; categories?: Category[] }>(apiUrl, fetcher)

  const tools = useMemo(() => data?.tools ?? [], [data?.tools])

  useEffect(() => {
    const toolParam = (searchParams.get('tool') || '').trim()
    if (!toolParam) return
    if (!tools.length) return
    if (lastAutoOpenedToolRef.current === toolParam) return

    const normalized = toolParam.toLowerCase()
    const match =
      tools.find((tool) => tool.name === toolParam || tool.display_name === toolParam) ||
      tools.find(
        (tool) =>
          tool.name?.toLowerCase() === normalized ||
          tool.display_name?.toLowerCase() === normalized,
      ) ||
      null

    if (!match) return
    lastAutoOpenedToolRef.current = toolParam
    setSelectedTool(match)
    setDetailOpen(true)
  }, [searchParams, tools])

  if (error) return <div className="p-8 text-red-600">Failed to load tools.</div>
  if (!data) return <div className="p-8 text-muted-foreground">Loading tools…</div>

  const buildToolAskPrompt = (tool: ToolRow) => {
    const lines: string[] = []
    lines.push(`I want to use the tool "${tool.name}".`)
    lines.push('')
    lines.push('Tool metadata:')
    lines.push(`- name: ${tool.name}`)
    if (tool.description) lines.push(`- description: ${tool.description}`)
    if (tool.stage) lines.push(`- stage: ${tool.stage}`)
    if (tool.layer) lines.push(`- layer: ${tool.layer}`)
    if (tool.cost_tier) lines.push(`- cost_tier: ${tool.cost_tier}`)
    if (tool.runtime) lines.push(`- runtime: ${tool.runtime}`)
    if (tool.origin) lines.push(`- origin: ${tool.origin}`)
    if (tool.impl) lines.push(`- impl: ${tool.impl}`)
    if (tool.module) lines.push(`- module: ${tool.module}`)
    if (tool.entrypoint) lines.push(`- entrypoint: ${tool.entrypoint}`)
    if (tool.domain) lines.push(`- domain: ${tool.domain}`)
    if (tool.function) lines.push(`- function: ${tool.function}`)
    if (tool.risk) lines.push(`- risk: ${tool.risk}`)
    if (tool.tags?.length) lines.push(`- tags: ${tool.tags.join(', ')}`)
    if (tool.modality?.length) lines.push(`- modality: ${tool.modality.join(', ')}`)
    if (tool.consumes) {
      lines.push(`- consumes: ${Object.entries(tool.consumes).map(([k, v]) => `${k}:${v}`).join(', ')}`)
    }
    if (tool.produces) {
      lines.push(`- produces: ${Object.entries(tool.produces).map(([k, v]) => `${k}:${v}`).join(', ')}`)
    }
    lines.push('')
    lines.push('Please:')
    lines.push('- Explain where this fits in a typical plan (or which official workflow/template to use instead).')
    lines.push('- Provide suggested parameters and required inputs.')
    lines.push('- If it is not safe/recommended, propose an alternative.')
    return lines.join('\n')
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <Dialog
          open={detailOpen}
          onOpenChange={(open) => {
            setDetailOpen(open)
            if (!open) {
              setSelectedTool(null)
            }
          }}
        >
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{selectedTool?.display_name || selectedTool?.name || 'Tool details'}</DialogTitle>
            </DialogHeader>
            {selectedTool ? (
              <div className="space-y-4 text-sm max-h-[70vh] overflow-y-auto">
                {/* Description */}
                {selectedTool.description && (
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Description
                    </div>
                    <div className="text-sm text-foreground bg-muted/30 rounded-md p-3">
                      {selectedTool.description}
                    </div>
                  </div>
                )}

                {/* Core metadata grid */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Runtime
                    </div>
                    <div>
                      <Badge variant="outline">{selectedTool.runtime || '—'}</Badge>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Stage
                    </div>
                    <div>
                      <Badge variant="secondary">{selectedTool.stage || selectedTool.category || '—'}</Badge>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Cost Tier
                    </div>
                    <div>
                      <Badge 
                        className={
                          selectedTool.cost_tier === 'cheap' ? 'bg-green-100 text-green-800' :
                          selectedTool.cost_tier === 'moderate' ? 'bg-yellow-100 text-yellow-800' :
                          selectedTool.cost_tier === 'expensive' ? 'bg-orange-100 text-orange-800' :
                          ''
                        }
                      >
                        {selectedTool.cost_tier || '—'}
                      </Badge>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Layer
                    </div>
                    <div>{selectedTool.layer || '—'}</div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Origin
                    </div>
                    <div>{selectedTool.origin || '—'}</div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Source
                    </div>
                    <div>
                      <Badge variant={selectedTool.source === 'grandmaster' ? 'default' : 'secondary'}>
                        {selectedTool.source || '—'}
                      </Badge>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Domain
                    </div>
                    <div>{selectedTool.domain || '—'}</div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Function
                    </div>
                    <div>{selectedTool.function || '—'}</div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Risk
                    </div>
                    <div>
                      <Badge 
                        variant="outline"
                        className={
                          selectedTool.risk === 'safe' ? 'border-green-500 text-green-700' :
                          selectedTool.risk === 'moderate' ? 'border-yellow-500 text-yellow-700' :
                          selectedTool.risk === 'high' ? 'border-red-500 text-red-700' :
                          ''
                        }
                      >
                        {selectedTool.risk || '—'}
                      </Badge>
                    </div>
                  </div>
                </div>

                {/* Tags */}
                {selectedTool.tags && selectedTool.tags.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Tags
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {selectedTool.tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="text-xs">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Implementation details */}
                {(selectedTool.impl || selectedTool.entrypoint || selectedTool.module) && (
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Implementation
                    </div>
                    <div className="rounded-md border bg-muted/20 p-3 font-mono text-xs whitespace-pre-wrap">
                      {selectedTool.impl && <div>{selectedTool.impl}</div>}
                      {selectedTool.module && <div className="mt-1 text-muted-foreground">module: {selectedTool.module}</div>}
                      {selectedTool.entrypoint && <div className="text-muted-foreground">entrypoint: {selectedTool.entrypoint}</div>}
                    </div>
                  </div>
                )}

                {/* Location / entry (for container tools) */}
                {(selectedTool.path || selectedTool.container_image) && (
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Location / Container
                    </div>
                    <div className="rounded-md border bg-muted/20 p-3 font-mono text-xs">
                      {selectedTool.path || selectedTool.container_image}
                    </div>
                  </div>
                )}

                {/* Inputs / outputs */}
                {(selectedTool.consumes || selectedTool.produces) && (
                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Inputs / Outputs
                    </div>
                    <div className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
                      <div>
                        <span className="font-semibold">Consumes:</span>{' '}
                        {selectedTool.consumes
                          ? Object.entries(selectedTool.consumes)
                              .map(([k, v]) => `${k}:${v}`)
                              .join(', ')
                          : '—'}
                      </div>
                      <div className="mt-1">
                        <span className="font-semibold">Produces:</span>{' '}
                        {selectedTool.produces
                          ? Object.entries(selectedTool.produces)
                              .map(([k, v]) => `${k}:${v}`)
                              .join(', ')
                          : '—'}
                      </div>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      const prompt = buildToolAskPrompt(selectedTool)
                      router.push(`/studio?tab=plan&draft=${encodeURIComponent(prompt)}`)
                    }}
                  >
                    Ask Agent to use this
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setDetailOpen(false)}>
                    Done
                  </Button>
                </div>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>

        <main className="mx-auto max-w-6xl px-4 py-12 space-y-8">
          <AdvancedViewBanner canonicalHref="/studio" />

          <header className="space-y-2">
            <h1 className="text-3xl font-bold">Tool Catalog</h1>
            <p className="text-sm text-muted-foreground">
              Search internal tools/packages from repo configs. Prefer Studio + official templates for most workflows.
            </p>
          </header>

          <section className="rounded-lg border bg-white">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="text-lg font-semibold">All tools</h2>
              <span className="text-xs text-muted-foreground">{tools.length} tools</span>
            </div>
            <div className="px-4 py-3 border-b">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <Input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder='Search by name or function (e.g. "motion correction", "skull stripping")…'
                  aria-label="Search tools"
                />
                <Button
                  type="button"
                  variant="secondary"
                  className="sm:w-auto"
                  disabled={!searchQuery.trim()}
                  onClick={() => setSearchQuery('')}
                >
                  Clear search
                </Button>
              </div>
            </div>
            {tools.length === 0 ? (
              <div className="px-6 py-10 space-y-3">
                <div className="text-sm font-medium">No matching tools</div>
                <div className="text-sm text-muted-foreground">
                  No tools match “{searchQuery.trim() || 'your search'}”. Try a different keyword, or ask the assistant
                  to find the right tool for your goal.
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => {
                      const q = searchQuery.trim()
                      const prompt = q
                        ? [
                            'I am trying to find the right tool for my goal.',
                            `Search query: ${q}`,
                            '',
                            'Please recommend the best official workflow/template first, and then list 3-5 relevant tools with what they do and where they fit in a plan.',
                          ].join('\n')
                        : [
                            'I want to find the right tool for my goal.',
                            '',
                            'Please recommend the best official workflow/template first, and then list 3-5 relevant tools with what they do and where they fit in a plan.',
                          ].join('\n')
                      router.push(`/studio?tab=plan&draft=${encodeURIComponent(prompt)}`)
                    }}
                  >
                    Ask Agent
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => setSearchQuery('')}>
                    Clear search
                  </Button>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-muted/50 text-left">
                    <tr>
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Description</th>
                      <th className="px-4 py-3">Stage</th>
                      <th className="px-4 py-3">Cost</th>
                      <th className="px-4 py-3">Runtime</th>
                      <th className="px-4 py-3">Source</th>
                      <th className="px-4 py-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tools.map((row) => (
                      <tr key={`${row.name}-${row.source}`} className="border-t hover:bg-muted/20">
                        <td className="px-4 py-3 font-medium">
                          <button
                            type="button"
                            className="text-left hover:underline font-mono text-sm"
                            onClick={() => {
                              setSelectedTool(row)
                              setDetailOpen(true)
                            }}
                          >
                            {row.name}
                          </button>
                        </td>
                        <td className="px-4 py-3 text-muted-foreground max-w-md">
                          <div className="line-clamp-2 text-xs">
                            {row.description || row.impl || '—'}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary" className="text-xs">
                            {row.stage || row.category || '—'}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          {row.cost_tier && (
                            <Badge 
                              className={`text-xs ${
                                row.cost_tier === 'cheap' ? 'bg-green-100 text-green-800' :
                                row.cost_tier === 'moderate' ? 'bg-yellow-100 text-yellow-800' :
                                row.cost_tier === 'expensive' ? 'bg-orange-100 text-orange-800' :
                                ''
                              }`}
                            >
                              {row.cost_tier}
                            </Badge>
                          )}
                          {!row.cost_tier && <span className="text-muted-foreground">—</span>}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="outline" className="text-xs">
                            {row.runtime || '—'}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <Badge 
                            variant={row.source === 'grandmaster' ? 'default' : 'secondary'} 
                            className="text-xs"
                          >
                            {row.source}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setSelectedTool(row)
                                setDetailOpen(true)
                              }}
                            >
                              Details
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                const prompt = buildToolAskPrompt(row)
                                router.push(`/studio?tab=plan&draft=${encodeURIComponent(prompt)}`)
                              }}
                            >
                              Use
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </main>
      </div>
    </NavigationWrapper>
  )
}
