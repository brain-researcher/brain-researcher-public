'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

interface ExampleChipsProps {
  onSelectExample: (example: string) => void
}

type TrendingItem = { query?: string }

export function ExampleChips({ onSelectExample }: ExampleChipsProps) {
  const [examples, setExamples] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const loadTrending = async () => {
      setLoading(true)
      try {
        const response = await fetch('/api/search/trending?timeframe=30d&limit=10', {
          cache: 'no-store',
        })
        if (!response.ok) {
          throw new Error(`trending ${response.status}`)
        }
        const payload = (await response.json()) as { trending?: TrendingItem[] }
        const items = Array.isArray(payload.trending) ? payload.trending : []
        const unique = Array.from(
          new Set(items.map((item) => item.query?.trim()).filter(Boolean) as string[])
        )
        if (!cancelled) {
          setExamples(unique.slice(0, 10))
        }
      } catch {
        if (!cancelled) setExamples([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadTrending()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center mb-8 text-xs text-muted-foreground">
        Loading search suggestions…
      </div>
    )
  }

  if (examples.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap justify-center gap-3 mb-8">
      {examples.map((example) => (
        <Button
          key={example}
          variant="secondary"
          size="sm"
          onClick={() => onSelectExample(example)}
          className="h-7 px-3 text-sm border border-border/50 hover:bg-primary/10 hover:border-primary/20 transition-all duration-200"
        >
          {example}
        </Button>
      ))}
    </div>
  )
}
