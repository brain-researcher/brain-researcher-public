'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  BookOpen,
  TrendingUp,
  Award,
  ExternalLink,
  RefreshCw
} from 'lucide-react'
import { CitationMetricsData, WidgetComponentProps } from '@/types/dashboard'

interface CitationMetricsWidgetProps extends WidgetComponentProps {
  data?: CitationMetricsData
}

export const CitationMetricsWidget: React.FC<CitationMetricsWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  className = ''
}) => {
  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5" />
            Citation Metrics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-4">
            <div className="grid grid-cols-2 gap-3">
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
            <BookOpen className="h-5 w-5" />
            Citation Metrics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <BookOpen className="h-8 w-8 mb-2" />
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
            <BookOpen className="h-5 w-5" />
            Citation Metrics
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <BookOpen className="h-8 w-8 mb-2 opacity-50" />
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
            <BookOpen className="h-5 w-5" />
            Citation Metrics
          </CardTitle>
          {onRefresh && (
            <Button variant="ghost" size="sm" onClick={onRefresh}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Key Metrics */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-blue-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-blue-600">{data.total_citations}</p>
                <p className="text-xs text-blue-600">Total Citations</p>
              </div>
              <TrendingUp className="h-6 w-6 text-blue-500" />
            </div>
          </div>
          <div className="bg-amber-50 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold text-amber-600">{data.h_index}</p>
                <p className="text-xs text-amber-600">h-index</p>
              </div>
              <Award className="h-6 w-6 text-amber-500" />
            </div>
          </div>
        </div>

        {/* Recent Publications */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Recent Publications</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {data.recent_publications.map((pub, index) => (
              <div
                key={index}
                className="p-2 rounded border bg-card/50 hover:bg-card transition-colors group"
              >
                <div className="space-y-1">
                  <p className="text-sm font-medium line-clamp-2 group-hover:text-primary">
                    {pub.title}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {pub.authors.join(', ')} • {pub.journal} ({pub.year})
                  </p>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="text-xs">
                        {pub.citations} citations
                      </Badge>
                      {pub.doi && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => window.open(`https://doi.org/${pub.doi}`, '_blank')}
                        >
                          <ExternalLink className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Trending Topics */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Trending Research Topics</h4>
          <div className="flex flex-wrap gap-1">
            {data.trending_topics.map((topic, index) => (
              <Badge 
                key={index} 
                variant="outline" 
                className="text-xs hover:bg-primary/10 cursor-pointer"
              >
                {topic}
              </Badge>
            ))}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="pt-2 border-t">
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm">
              View Profile
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
