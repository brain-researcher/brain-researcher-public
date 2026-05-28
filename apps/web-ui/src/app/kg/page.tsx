'use client'

import { AdvancedViewBanner } from '@/components/advanced/advanced-view-banner'
import { KGExplorerLayout } from '@/components/knowledge-graph/KGExplorerLayout'
import {
  LinearKnowledgeGraph,
  type ExplorerLens,
} from '@/components/knowledge-graph/LinearKnowledgeGraph'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSearchParams } from 'next/navigation'
import { useState } from 'react'

export default function KnowledgeGraphPage() {
  const searchParams = useSearchParams()
  const defaultLens = (() => {
    const rawLens = (
      searchParams.get('lens') ||
      searchParams.get('tab') ||
      ''
    )
      .trim()
      .toLowerCase()
    if (rawLens === 'task') return 'task'
    if (rawLens === 'disease') return 'disease'
    if (rawLens === 'population') return 'task'
    if (rawLens === 'onvoc') return 'onvoc'
    return 'task'
  })()
  const lensTabs: Array<{ value: ExplorerLens; label: string }> = [
    { value: 'task', label: 'Task' },
    { value: 'disease', label: 'Disease' },
    { value: 'onvoc', label: 'ONVOC' },
  ]
  const [activeLens, setActiveLens] = useState<ExplorerLens>(defaultLens)

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <AdvancedViewBanner canonicalHref="/studio" />
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Knowledge Graph</h1>
            <p className="text-sm text-muted-foreground">
              Explore graph-backed evidence across task, disease, and ONVOC views before you commit to a run.
            </p>
          </div>

          <KGExplorerLayout>
            <Tabs
              value={activeLens}
              onValueChange={(value) => setActiveLens(value as ExplorerLens)}
              className="space-y-4"
            >
              <TabsList className="w-full justify-start">
                {lensTabs.map((tab) => (
                  <TabsTrigger key={tab.value} value={tab.value}>
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              <TabsContent value={activeLens} className="mt-0">
                <LinearKnowledgeGraph key={activeLens} lens={activeLens} />
              </TabsContent>
            </Tabs>
          </KGExplorerLayout>
        </div>
      </div>
    </NavigationWrapper>
  )
}
