'use client'

import { useState, useEffect } from 'react'
import { 
  Brain, Calendar, Users, Database, FileText, 
  ExternalLink, Download, Copy, CheckCircle, Loader2 
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MiniGraph } from './mini-graph'

interface DatasetItem {
  id: string
  title: string
  source: string
  category?: string
  n?: number
  ageStats?: {
    mean: number
    sd: number
    min?: number
    max?: number
  }
  tasks: string[]
  mri?: {
    TR: number
    voxel?: number[]
  }
  flags: {
    bids: boolean
    qc_ok: boolean
  }
  why: Array<{
    type: string
    value: string
    evidence?: Array<{
      doi?: string
      title?: string
    }>
  }>
  readiness: 'green' | 'yellow' | 'red'
  readiness_issues?: string[]
}

interface DatasetDetailsProps {
  dataset: DatasetItem
  onRunDemo?: (dataset: DatasetItem) => void
}

interface ExplanationData {
  summary: string
  topCitations: Array<{
    doi?: string
    title?: string
  }>
  miniGraph: {
    nodes: Array<{
      id: string
      type: string
      label: string
    }>
    edges: Array<{
      src: string
      dst: string
      rel: string
      weight: number
    }>
    positions?: Array<{
      id: string
      x: number
      y: number
    }>
  }
  details?: {
    tasks: string[]
    constructs: string[]
    publications: number
  }
}

export function DatasetDetails({ dataset, onRunDemo }: DatasetDetailsProps) {
  const [explanation, setExplanation] = useState<ExplanationData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const fetchExplanation = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const response = await fetch(
          `/api/finder/explain/${encodeURIComponent(dataset.id)}`,
          { cache: 'no-store' },
        )
        if (!response.ok) {
          const detail = await response.text().catch(() => '')
          setExplanation(null)
          setError(detail || `HTTP ${response.status}`)
          return
        }
        const data = await response.json().catch(() => null)
        setExplanation(data as ExplanationData | null)
      } catch (error) {
        console.error('Failed to fetch explanation:', error)
        setExplanation(null)
        setError(error instanceof Error ? error.message : 'Failed to load dataset explanation')
      } finally {
        setIsLoading(false)
      }
    }

    fetchExplanation()
  }, [dataset])

  const copyToClipboard = () => {
    const text = `Dataset: ${dataset.id}\nTitle: ${dataset.title}\nSource: ${dataset.source}\nN: ${dataset.n}\nTasks: ${dataset.tasks.join(', ')}`
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const exportData = () => {
    const data = {
      dataset,
      explanation,
      timestamp: new Date().toISOString()
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${dataset.id}_details.json`
    a.click()
  }

  return (
    <ScrollArea className="h-[calc(100vh-100px)] mt-4">
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Database className="h-5 w-5" />
            {dataset.title}
          </h3>
          <p className="text-sm text-gray-500 mt-1">{dataset.id}</p>
          {dataset.category && (
            <Badge variant="outline" className="mt-2 w-fit text-xs">
              {dataset.category}
            </Badge>
          )}
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-2 gap-4">
          {dataset.n && (
            <div className="flex items-center gap-2 p-3 bg-gray-50 rounded">
              <Users className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-sm text-gray-500">Sample Size</div>
                <div className="font-semibold">{dataset.n}</div>
              </div>
            </div>
          )}
          
          {dataset.ageStats && (
            <div className="flex items-center gap-2 p-3 bg-gray-50 rounded">
              <Calendar className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-sm text-gray-500">Age Range</div>
                <div className="font-semibold">
                  {dataset.ageStats.min}-{dataset.ageStats.max} years
                </div>
              </div>
            </div>
          )}
        </div>

        <Separator />

        {/* Tabs */}
        <Tabs defaultValue="summary" className="w-full">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="graph">Graph</TabsTrigger>
          </TabsList>

          <TabsContent value="summary" className="mt-4 space-y-4">
            {/* Summary */}
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : error ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                Explanation unavailable: {error}
              </div>
            ) : explanation ? (
              <>
                <div>
                  <h4 className="font-medium mb-2">Description</h4>
                  <p className="text-sm text-gray-600">{explanation.summary}</p>
                </div>

                {/* Tasks & Constructs */}
                {explanation.details && (
                  <>
                    <div>
                      <h4 className="font-medium mb-2">Tasks</h4>
                      <div className="flex flex-wrap gap-2">
                        {explanation.details.tasks.map(task => (
                          <Badge key={task} variant="secondary">
                            <Brain className="h-3 w-3 mr-1" />
                            {task}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    <div>
                      <h4 className="font-medium mb-2">Cognitive Constructs</h4>
                      <div className="flex flex-wrap gap-2">
                        {explanation.details.constructs.map(construct => (
                          <Badge key={construct} variant="outline">
                            {construct.replace(/_/g, ' ')}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </>
            ) : (
              <div className="text-sm text-muted-foreground">No data yet.</div>
            )}

            {/* Quality Indicators */}
            <div>
              <h4 className="font-medium mb-2">Quality Indicators</h4>
              <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <CheckCircle className={`h-4 w-4 ${dataset.flags.bids ? 'text-green-500' : 'text-gray-300'}`} />
                      <span className="text-sm">BIDS Compliant</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <CheckCircle className={`h-4 w-4 ${dataset.flags.qc_ok ? 'text-green-500' : 'text-gray-300'}`} />
                      <span className="text-sm">Quality Control Passed</span>
                    </div>
                {dataset.mri && (
                  <div className="flex items-center gap-2">
                    <CheckCircle className="h-4 w-4 text-blue-500" />
                    <span className="text-sm">TR = {dataset.mri.TR}s</span>
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="evidence" className="mt-4 space-y-4">
            {/* Why Matched */}
            <div>
              <h4 className="font-medium mb-2">Why This Dataset Matched</h4>
              <div className="space-y-2">
                {dataset.why.map((reason, idx) => (
                  <div key={idx} className="p-3 bg-blue-50 rounded">
                    <div className="font-medium text-sm">
                      {reason.type}: {reason.value}
                    </div>
                    {reason.evidence && reason.evidence.length > 0 && (
                      <div className="mt-1 text-xs text-gray-600">
                        Evidence: {reason.evidence[0].title}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Citations */}
            {explanation?.topCitations && explanation.topCitations.length > 0 && (
              <div>
                <h4 className="font-medium mb-2">Related Publications</h4>
                <div className="space-y-2">
                  {explanation.topCitations.map((citation, idx) => (
                    <div key={idx} className="p-3 border rounded hover:bg-gray-50">
                      <div className="text-sm">{citation.title}</div>
                      {citation.doi && (
                        <a
                          href={`https://doi.org/${citation.doi}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-blue-600 hover:underline flex items-center gap-1 mt-1"
                        >
                          DOI: {citation.doi}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="graph" className="mt-4">
            {explanation?.miniGraph && (
              <MiniGraph
                nodes={explanation.miniGraph.nodes}
                edges={explanation.miniGraph.edges}
                positions={explanation.miniGraph.positions}
              />
            )}
          </TabsContent>
        </Tabs>

        <Separator />

        {/* Actions */}
        <div className="flex gap-2">
          <Button
            className="flex-1"
            onClick={() => onRunDemo?.(dataset)}
            disabled={dataset.readiness === 'red'}
          >
            Run GLM Demo
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={copyToClipboard}
          >
            {copied ? <CheckCircle className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={exportData}
          >
            <Download className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </ScrollArea>
  )
}
