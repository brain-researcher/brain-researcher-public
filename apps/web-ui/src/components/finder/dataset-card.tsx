'use client'

import { CheckCircle, AlertCircle, XCircle, Users, Brain, Calendar, Database, ExternalLink } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'

interface DatasetItem {
  id: string
  title: string
  source: string
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

interface DatasetCardProps {
  dataset: DatasetItem
  onSelect?: (dataset: DatasetItem) => void
  onRunDemo?: (dataset: DatasetItem) => void
}

export function DatasetCard({ dataset, onSelect, onRunDemo }: DatasetCardProps) {
  const getReadinessIcon = () => {
    switch (dataset.readiness) {
      case 'green':
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'yellow':
        return <AlertCircle className="h-5 w-5 text-yellow-500" />
      case 'red':
        return <XCircle className="h-5 w-5 text-red-500" />
    }
  }

  const getReadinessColor = () => {
    switch (dataset.readiness) {
      case 'green':
        return 'border-green-200 bg-green-50'
      case 'yellow':
        return 'border-yellow-200 bg-yellow-50'
      case 'red':
        return 'border-red-200 bg-red-50'
    }
  }

  const formatAge = () => {
    if (!dataset.ageStats) return null
    const { mean, sd, min, max } = dataset.ageStats
    if (min !== undefined && max !== undefined) {
      return `${min}-${max} years (μ=${mean.toFixed(1)}±${sd.toFixed(1)})`
    }
    return `${mean.toFixed(1)}±${sd.toFixed(1)} years`
  }

  return (
    <Card 
      className={`hover:shadow-lg transition-shadow cursor-pointer ${getReadinessColor()}`}
      onClick={() => onSelect?.(dataset)}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="h-4 w-4 text-gray-500" />
              {dataset.title || dataset.id}
            </CardTitle>
            <CardDescription className="mt-1">
              {dataset.source && (
                <Badge variant="outline" className="mr-2">
                  {dataset.source}
                </Badge>
              )}
              {dataset.id}
            </CardDescription>
          </div>
          <div className="flex items-center gap-1">
            {getReadinessIcon()}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Key Metrics */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          {dataset.n && (
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-gray-400" />
              <span>n = {dataset.n}</span>
            </div>
          )}
          
          {dataset.ageStats && (
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-gray-400" />
              <span className="truncate" title={formatAge() || ''}>
                {formatAge()}
              </span>
            </div>
          )}
        </div>

        {/* Tasks */}
        {dataset.tasks.length > 0 && (
          <div>
            <div className="text-xs font-medium text-gray-500 mb-1">Tasks</div>
            <div className="flex flex-wrap gap-1">
              {dataset.tasks.map(task => (
                <Badge key={task} variant="secondary" className="text-xs">
                  <Brain className="h-3 w-3 mr-1" />
                  {task}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Quality Flags */}
        <div className="flex gap-2">
          {dataset.flags.bids && (
            <Badge variant="outline" className="text-xs bg-green-50">
              BIDS ✓
            </Badge>
          )}
          {dataset.flags.qc_ok && (
            <Badge variant="outline" className="text-xs bg-blue-50">
              QC ✓
            </Badge>
          )}
          {dataset.mri?.TR && (
            <Badge variant="outline" className="text-xs">
              TR={dataset.mri.TR}s
            </Badge>
          )}
        </div>

        {/* Why Matched */}
        {dataset.why.length > 0 && (
          <div>
            <div className="text-xs font-medium text-gray-500 mb-1">Why matched</div>
            <div className="space-y-1">
              {dataset.why.slice(0, 2).map((reason, idx) => (
                <div key={idx} className="text-xs text-gray-600">
                  • {reason.type}: <span className="font-medium">{reason.value}</span>
                  {reason.evidence?.[0] && (
                    <span className="text-blue-600 ml-1">
                      [{reason.evidence[0].title?.split(' ')[0]} et al.]
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Readiness Issues */}
        {dataset.readiness !== 'green' && dataset.readiness_issues && dataset.readiness_issues.length > 0 && (
          <div className="text-xs text-gray-500 italic">
            ⚠ {dataset.readiness_issues[0]}
          </div>
        )}

        <Separator />

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            variant="default"
            className="flex-1"
            onClick={(e) => {
              e.stopPropagation()
              onRunDemo?.(dataset)
            }}
            disabled={dataset.readiness === 'red'}
          >
            Run Demo
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={(e) => {
              e.stopPropagation()
              onSelect?.(dataset)
            }}
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}