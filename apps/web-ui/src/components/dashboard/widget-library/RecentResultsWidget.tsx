'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { 
  Download,
  FileText,
  Image,
  BarChart3,
  Brain,
  Clock,
  RefreshCw
} from 'lucide-react'
import { RecentResultsData, WidgetComponentProps } from '@/types/dashboard'

interface RecentResultsWidgetProps extends WidgetComponentProps {
  data?: RecentResultsData
}

export const RecentResultsWidget: React.FC<RecentResultsWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  className = ''
}) => {
  const getFileIcon = (type: string) => {
    switch (type) {
      case 'brain_map':
        return <Brain className="h-5 w-5 text-purple-500" />
      case 'chart':
        return <BarChart3 className="h-5 w-5 text-blue-500" />
      case 'report':
        return <FileText className="h-5 w-5 text-green-500" />
      case 'table':
        return <FileText className="h-5 w-5 text-orange-500" />
      default:
        return <FileText className="h-5 w-5 text-gray-500" />
    }
  }

  const formatTimeAgo = (date: Date) => {
    const now = new Date()
    const diffInMs = now.getTime() - date.getTime()
    const diffInMins = Math.floor(diffInMs / (1000 * 60))
    
    if (diffInMins < 1) return 'Just now'
    if (diffInMins < 60) return `${diffInMins} min ago`
    
    const diffInHours = Math.floor(diffInMins / 60)
    if (diffInHours < 24) return `${diffInHours} hour${diffInHours > 1 ? 's' : ''} ago`
    
    const diffInDays = Math.floor(diffInHours / 24)
    return `${diffInDays} day${diffInDays > 1 ? 's' : ''} ago`
  }

  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Recent Results
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gray-200 rounded"></div>
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-gray-200 rounded w-3/4"></div>
                  <div className="h-3 bg-gray-200 rounded w-1/2"></div>
                </div>
              </div>
            ))}
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
            <Download className="h-5 w-5" />
            Recent Results
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <FileText className="h-8 w-8 mb-2" />
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
            <Download className="h-5 w-5" />
            Recent Results
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <FileText className="h-8 w-8 mb-2 opacity-50" />
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
            <Download className="h-5 w-5" />
            Recent Results
          </CardTitle>
          {onRefresh && (
            <Button variant="ghost" size="sm" onClick={onRefresh}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {data.results.map((result) => (
            <div
              key={result.id}
              className="flex items-center gap-3 p-2 rounded-lg border bg-card/50 hover:bg-card transition-colors group"
            >
              {/* File Icon */}
              <div className="flex-shrink-0">
                {result.thumbnail_url ? (
                  <div className="w-10 h-10 rounded border overflow-hidden bg-gray-100">
                    <img 
                      src={result.thumbnail_url} 
                      alt={result.title}
                      className="w-full h-full object-cover"
                      onError={(e) => {
                        e.currentTarget.style.display = 'none'
                        e.currentTarget.nextElementSibling?.classList.remove('hidden')
                      }}
                    />
                    <div className="hidden w-full h-full flex items-center justify-center">
                      {getFileIcon(result.type)}
                    </div>
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded border flex items-center justify-center bg-gray-50">
                    {getFileIcon(result.type)}
                  </div>
                )}
              </div>

              {/* File Info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate group-hover:text-primary">
                  {result.title}
                </p>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{result.size}</span>
                  <span>•</span>
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {formatTimeAgo(result.created_at)}
                  </div>
                </div>
              </div>

              {/* Download Button */}
              <div className="flex-shrink-0">
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => {
                    // Create download link
                    const link = document.createElement('a')
                    link.href = result.download_url
                    link.download = result.title
                    link.click()
                  }}
                >
                  <Download className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {/* Quick Actions */}
        <div className="pt-2 border-t">
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm">
              Browse All
            </Button>
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4 mr-1" />
              Download All
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
