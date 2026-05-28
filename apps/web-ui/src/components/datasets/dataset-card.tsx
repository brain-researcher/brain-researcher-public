'use client'

import { useState, memo } from 'react'
import { Calendar, Database, Users, Zap, Play, Info, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dataset } from '@/types/dataset'
import { formatBytes } from '@/lib/utils'

interface DatasetCardProps {
  dataset: Dataset
  onRunDemo: (dataset: Dataset) => void
  onViewDetails: (dataset: Dataset) => void
}

function DatasetCardComponent({ dataset, onRunDemo, onViewDetails }: DatasetCardProps) {
  const [imageError, setImageError] = useState(false)

  const getSourceColor = (source: string) => {
    switch (source) {
      case 'OpenNeuro': return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
      case 'HCP': return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
      case 'ABCD': return 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
      case 'Built-in Sample': return 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
    }
  }

  return (
    <Card className="group hover:shadow-lg transition-all duration-300 border-2 hover:border-primary/20">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between mb-2">
          <div>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-1 rounded-full text-xs font-medium ${getSourceColor(dataset.source)}`}>
                {dataset.source}
              </span>
              {dataset.onvoc?.labels?.length ? (
                <Badge variant="outline" className="flex items-center gap-1 text-[10px] font-medium">
                  <Sparkles className="h-3 w-3 text-amber-500" />
                  {dataset.onvoc.labels[0]}
                  {dataset.onvoc.labels.length > 1 ? ` (+${dataset.onvoc.labels.length - 1})` : ''}
                </Badge>
              ) : null}
            </div>
            {dataset.category && dataset.category.toLowerCase() !== dataset.source.toLowerCase() && (
              <Badge variant="outline" className="mt-2 text-[10px] font-medium">
                {dataset.category}
              </Badge>
            )}
          </div>
          
          {dataset.thumbnail && !imageError && (
            <div className="w-16 h-12 rounded overflow-hidden bg-muted">
              <img
                src={dataset.thumbnail}
                alt={dataset.name}
                className="w-full h-full object-cover"
                onError={() => setImageError(true)}
              />
            </div>
          )}
        </div>

        <CardTitle className="text-lg group-hover:text-primary transition-colors">
          {dataset.name}
        </CardTitle>
        
        <CardDescription className="text-sm line-clamp-2">
          {dataset.description}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Key metrics */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" />
            <span>{dataset.nSubjects.toLocaleString()} subjects</span>
          </div>
          
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <span>{dataset.size}</span>
          </div>

          {dataset.tr && (
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-muted-foreground" />
              <span>TR: {dataset.tr}s</span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            <span>{dataset.lastUpdated.toLocaleDateString()}</span>
          </div>
        </div>

        {/* Modalities */}
        <div className="flex flex-wrap gap-1">
          {dataset.modality.map((mod) => (
            <span
              key={mod}
              className="px-2 py-1 bg-secondary text-secondary-foreground rounded text-xs font-medium"
            >
              {mod}
            </span>
          ))}
        </div>

        {/* Tasks */}
        {dataset.tasks && dataset.tasks.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">Tasks:</div>
            <div className="flex flex-wrap gap-1">
              {dataset.tasks.slice(0, 3).map((task) => (
                <span
                  key={task}
                  className="px-2 py-1 bg-muted text-muted-foreground rounded text-xs"
                >
                  {task}
                </span>
              ))}
              {dataset.tasks.length > 3 && (
                <span className="px-2 py-1 bg-muted text-muted-foreground rounded text-xs">
                  +{dataset.tasks.length - 3} more
                </span>
              )}
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-2">
          <Button
            onClick={() => onRunDemo(dataset)}
            className="flex-1"
            size="sm"
          >
            <Play className="h-3 w-3 mr-1" />
            Run Demo
          </Button>
          
          <Button
            onClick={() => onViewDetails(dataset)}
            variant="outline"
            size="sm"
          >
            <Info className="h-3 w-3" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// Memoized export for better performance
export const DatasetCard = memo(DatasetCardComponent, (prevProps, nextProps) => {
  return prevProps.dataset.id === nextProps.dataset.id &&
         prevProps.dataset.lastUpdated?.getTime() === nextProps.dataset.lastUpdated?.getTime()
})
