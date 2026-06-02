'use client'

import { useRouter } from 'next/navigation'

import { LinearKnowledgeGraph } from '@/components/knowledge-graph/LinearKnowledgeGraph'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'

export default function KnowledgeGraphExplorePage() {
  const router = useRouter()

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">Knowledge Graph</h1>
              <p className="text-sm text-muted-foreground">
                Explore ONVOC, Cognitive Atlas, Neurosynth, NeuroVault concepts.
              </p>
            </div>

            <Button
              variant="outline"
              onClick={() => {
                const prompt =
                  'Use the internal BR-KG (Neo4j) first. Run a subgraph search around relevant concepts and include top nodes/edges in the answer. Avoid external web unless necessary.'
                router.push(`/en/studio?prompt=${encodeURIComponent(prompt)}`)
              }}
            >
              Ask assistant
            </Button>
          </div>

          <LinearKnowledgeGraph />
        </div>
      </div>
    </NavigationWrapper>
  )
}
