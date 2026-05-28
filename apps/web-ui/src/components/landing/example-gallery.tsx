'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Database, ExternalLink, Loader2 } from 'lucide-react'
import type { DatasetCardResponse } from '@/types/datasets-search'

interface ExampleGalleryProps {
  locale?: string
}

export function ExampleGallery({}: ExampleGalleryProps) {
  const [datasets, setDatasets] = useState<DatasetCardResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const loadDatasets = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch('/api/catalog/datasets/search?limit=6&offset=0', { cache: 'no-store' })
        if (!response.ok) throw new Error(`Failed to load datasets (${response.status})`)
        const data = await response.json()
        if (!cancelled) setDatasets(data.datasets ?? [])
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load datasets')
          setDatasets([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadDatasets()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="container mx-auto px-4 py-16">
      <div className="text-center mb-12">
        <h2 className="text-3xl font-bold mb-4">Dataset highlights</h2>
        <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
          Explore datasets already indexed in the Brain Researcher catalog.
        </p>
        {error && (
          <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800 text-sm">
            {error}
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          Loading datasets…
        </div>
      ) : datasets.length === 0 ? (
        <div className="text-center text-sm text-muted-foreground">
          No datasets available yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8">
          {datasets.map((dataset) => (
            <Card
              key={dataset.id}
              className="group hover:shadow-xl transition-all duration-300 border-2 hover:border-primary/20 overflow-hidden"
            >
              <div className="bg-gradient-to-br from-gray-50 to-white px-4 py-3 border-b">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-sm">
                  <Database className="h-4 w-4 text-primary" />
                  {dataset.source_repo}
                </div>
              </div>

              <CardHeader>
                <CardTitle className="text-lg">{dataset.name}</CardTitle>
                <CardDescription className="text-sm">
                  {(dataset.description ?? '').slice(0, 140) || 'No description available.'}
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {(dataset.modalities ?? []).slice(0, 4).map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded-full"
                    >
                      {tag}
                    </span>
                  ))}
                  {dataset.subjects_count != null && (
                    <span className="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded-full">
                      N={dataset.subjects_count}
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-2">
                  <Button asChild variant="outline" className="w-full">
                    <Link href={`/datasets?q=${encodeURIComponent(dataset.name)}`}>
                      <ExternalLink className="h-4 w-4 mr-2" />
                      View in catalog
                    </Link>
                  </Button>
                  {dataset.primary_url ? (
                    <Button asChild variant="ghost" className="w-full">
                      <a href={dataset.primary_url} target="_blank" rel="noreferrer">
                        Open source
                      </a>
                    </Button>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}
