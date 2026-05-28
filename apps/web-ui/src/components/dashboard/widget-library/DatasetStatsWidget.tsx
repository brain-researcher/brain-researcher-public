'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { 
  Database,
  Users,
  Calendar,
  TrendingUp,
  RefreshCw
} from 'lucide-react'
import { DatasetStatsData, WidgetComponentProps } from '@/types/dashboard'
import { Badge } from '@/components/ui/badge'

interface DatasetStatsWidgetProps extends WidgetComponentProps {
  data?: DatasetStatsData
}

export const DatasetStatsWidget: React.FC<DatasetStatsWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  className = ''
}) => {
  const formatTimeAgo = (date: Date) => {
    const now = new Date()
    const diffInMs = now.getTime() - date.getTime()
    const diffInDays = Math.floor(diffInMs / (1000 * 60 * 60 * 24))
    
    if (diffInDays === 0) return 'Today'
    if (diffInDays === 1) return 'Yesterday'
    return `${diffInDays} days ago`
  }

  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Dataset Statistics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-4">
            <div className="grid grid-cols-2 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-16 bg-gray-200 rounded"></div>
              ))}
            </div>
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-8 bg-gray-200 rounded"></div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Dataset Statistics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Database className="h-8 w-8 mb-2" />
            <p className="text-sm text-center">{error}</p>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
                Retry
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Dataset Statistics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Database className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm text-center">No data yet.</p>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
                Retry
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  const maxModalityCount = Math.max(...Object.values(data.modalities ?? {}), 1)

  return (
    <Card className={`h-full ${className}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-5 w-5" />
            Dataset Statistics
          </CardTitle>
          {onRefresh && (
            <Button variant="ghost" size="sm" onClick={onRefresh}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary Stats */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-blue-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-blue-600">{data.total_datasets}</p>
                <p className="text-xs text-blue-600">Datasets</p>
              </div>
              <Database className="h-6 w-6 text-blue-500" />
            </div>
          </div>
          <div className="bg-green-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-green-600">{data.total_subjects.toLocaleString()}</p>
                <p className="text-xs text-green-600">Subjects</p>
              </div>
              <Users className="h-6 w-6 text-green-500" />
            </div>
          </div>
        </div>

        <div className="bg-purple-50 rounded-lg p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xl font-bold text-purple-600">{data.total_sessions.toLocaleString()}</p>
              <p className="text-xs text-purple-600">Total Sessions</p>
            </div>
            <Calendar className="h-5 w-5 text-purple-500" />
          </div>
        </div>

        {/* Modalities */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Modalities</h4>
          <div className="space-y-1">
            {Object.entries(data.modalities).map(([modality, count]) => (
              <div key={modality} className="flex items-center justify-between">
                <span className="text-sm">{modality}</span>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-gray-200 rounded-full">
                    <div 
                      className="h-1.5 bg-blue-500 rounded-full transition-all duration-300"
                      style={{ width: `${(count / maxModalityCount) * 100}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium text-muted-foreground w-6 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Categories */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Categories</h4>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.categories).map(([category, count]) => (
              <Badge key={category} variant="outline" className="text-xs font-normal">
                {category}
                <span className="ml-1 text-muted-foreground">({count})</span>
              </Badge>
            ))}
          </div>
        </div>

        {/* Recent Uploads */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Recent Uploads</h4>
          <div className="space-y-1 max-h-24 overflow-y-auto">
            {data.recent_uploads.map((upload) => (
              <div
                key={upload.id}
                className="flex items-center justify-between p-2 rounded border bg-card/50"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{upload.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {upload.subjects} subjects • {upload.modality}
                  </p>
                </div>
                <div className="text-xs text-muted-foreground">
                  {formatTimeAgo(upload.uploaded_at)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="pt-2 border-t">
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm">
              Browse All
            </Button>
            <Button variant="outline" size="sm">
              <TrendingUp className="h-4 w-4 mr-1" />
              Analytics
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
