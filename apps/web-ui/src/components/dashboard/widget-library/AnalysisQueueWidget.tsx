'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
import { 
  Play, 
  Pause, 
  Clock, 
  CheckCircle, 
  XCircle,
  Users,
  BarChart3
} from 'lucide-react'
import { AnalysisQueueData, WidgetComponentProps } from '@/types/dashboard'

interface AnalysisQueueWidgetProps extends WidgetComponentProps {
  data?: AnalysisQueueData
}

export const AnalysisQueueWidget: React.FC<AnalysisQueueWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  className = ''
}) => {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return <Play className="h-4 w-4 text-blue-500" />
      case 'queued':
        return <Clock className="h-4 w-4 text-orange-500" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <Pause className="h-4 w-4 text-gray-500" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-blue-100 text-blue-800 hover:bg-blue-200'
      case 'queued':
        return 'bg-orange-100 text-orange-800 hover:bg-orange-200'
      case 'completed':
        return 'bg-green-100 text-green-800 hover:bg-green-200'
      case 'failed':
        return 'bg-red-100 text-red-800 hover:bg-red-200'
      default:
        return 'bg-gray-100 text-gray-800 hover:bg-gray-200'
    }
  }

  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Analysis Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div className="h-16 bg-gray-200 rounded"></div>
              <div className="h-16 bg-gray-200 rounded"></div>
            </div>
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-12 bg-gray-200 rounded"></div>
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
            <BarChart3 className="h-5 w-5" />
            Analysis Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <XCircle className="h-8 w-8 mb-2" />
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
            <BarChart3 className="h-5 w-5" />
            Analysis Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <BarChart3 className="h-8 w-8 mb-2 opacity-50" />
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

  return (
    <Card className={`h-full ${className}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-5 w-5" />
            Analysis Queue
          </CardTitle>
          {onRefresh && (
            <Button variant="ghost" size="sm" onClick={onRefresh}>
              <Clock className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Summary Stats */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-blue-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-blue-600">{data.running}</p>
                <p className="text-xs text-blue-600">Running</p>
              </div>
              <Play className="h-6 w-6 text-blue-500" />
            </div>
          </div>
          <div className="bg-orange-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-orange-600">{data.queued}</p>
                <p className="text-xs text-orange-600">Queued</p>
              </div>
              <Clock className="h-6 w-6 text-orange-500" />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="bg-green-50 rounded-lg p-2">
            <p className="text-lg font-semibold text-green-600">{data.completed_today}</p>
            <p className="text-xs text-green-600">Completed Today</p>
          </div>
          <div className="bg-red-50 rounded-lg p-2">
            <p className="text-lg font-semibold text-red-600">{data.failed}</p>
            <p className="text-xs text-red-600">Failed</p>
          </div>
        </div>

        {/* Recent Jobs */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Recent Jobs</h4>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {data.recent_jobs.slice(0, 5).map((job) => (
              <div
                key={job.id}
                className="flex items-center justify-between p-2 rounded-lg border bg-card/50 hover:bg-card transition-colors"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {getStatusIcon(job.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{job.title}</p>
                    <p className="text-xs text-muted-foreground">
                      <Users className="h-3 w-3 inline mr-1" />
                      {job.user}
                    </p>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge variant="secondary" className={`text-xs ${getStatusColor(job.status)}`}>
                    {job.status}
                  </Badge>
                  {job.progress && (
                    <div className="flex items-center gap-1">
                      <div className="w-12 h-1 bg-gray-200 rounded-full">
                        <div 
                          className="h-1 bg-blue-500 rounded-full transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground">{job.progress}%</span>
                    </div>
                  )}
                  {job.eta && (
                    <span className="text-xs text-muted-foreground">{job.eta} left</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="pt-2 border-t">
          <Button variant="outline" size="sm" className="w-full">
            View All Jobs
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
