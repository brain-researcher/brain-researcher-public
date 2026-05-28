'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { BarChart } from '@/components/charts/BarChart'
import { LineChart } from '@/components/charts/LineChart'
import { ResearchMetrics } from '@/types/analytics'
import { Database, Wrench, TrendingUp, BookOpen, Users } from 'lucide-react'
import { format } from 'date-fns'

interface ResearchInsightsProps {
  data: ResearchMetrics
  loading?: boolean
  className?: string
}

export function ResearchInsights({ data, loading, className }: ResearchInsightsProps) {
  const formatDatasetData = () => {
    return Array.from(data.datasetsUsed.entries())
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)
      .map(([dataset, usage]) => ({
        dataset: dataset.length > 25 ? `${dataset.slice(0, 22)}...` : dataset,
        usage,
        fullName: dataset
      }))
  }

  const formatToolsData = () => {
    return Array.from(data.toolsUsed.entries())
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)
      .map(([tool, usage]) => ({
        tool,
        usage,
        percentage: Math.round((usage / Math.max(...Array.from(data.toolsUsed.values()))) * 100)
      }))
  }

  const formatWorkflowData = () => {
    return data.popularWorkflows.slice(0, 8).map(workflow => ({
      workflow: workflow.workflow.length > 20 
        ? `${workflow.workflow.slice(0, 17)}...` 
        : workflow.workflow,
      usage: workflow.usage,
      'Success Rate (%)': workflow.successRate
    }))
  }

  const formatToolTrendData = () => {
    return data.toolUsageTrends.slice(-30).map(item => {
      const formattedData: any = {
        date: format(new Date(item.date), 'MMM dd')
      }
      
      // Add top 5 tools to the chart
      const topTools = Array.from(data.toolsUsed.entries())
        .sort(([, a], [, b]) => b - a)
        .slice(0, 5)
        .map(([tool]) => tool)
      
      topTools.forEach(tool => {
        formattedData[tool] = item.toolUsage[tool] || 0
      })
      
      return formattedData
    })
  }

  const getToolColors = () => {
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']
    return Array.from(data.toolsUsed.entries())
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([tool], index) => ({
        dataKey: tool,
        name: tool,
        color: colors[index],
        strokeWidth: 2
      }))
  }

  if (loading) {
    return (
      <div className={className}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {[1, 2, 3, 4].map(i => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-20 animate-pulse bg-gray-200 rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={className}>
      {/* Key research metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Analyses Run</p>
                <p className="text-2xl font-bold">{data.analysesRun.toLocaleString()}</p>
              </div>
              <TrendingUp className="h-8 w-8 text-blue-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Datasets</p>
                <p className="text-2xl font-bold">{data.datasetStats.totalDatasets}</p>
                <p className="text-xs text-muted-foreground">
                  {data.datasetStats.totalSubjects.toLocaleString()} subjects
                </p>
              </div>
              <Database className="h-8 w-8 text-green-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Active Tools</p>
                <p className="text-2xl font-bold">{data.toolsUsed.size}</p>
              </div>
              <Wrench className="h-8 w-8 text-orange-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">H-Index</p>
                <p className="text-2xl font-bold">{data.publicationMetrics.hIndex}</p>
                <p className="text-xs text-muted-foreground">
                  {data.publicationMetrics.totalCitations} citations
                </p>
              </div>
              <BookOpen className="h-8 w-8 text-purple-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tool usage trends */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Tool Usage Trends</CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            data={formatToolTrendData()}
            lines={getToolColors()}
            xAxisKey="date"
            xAxisLabel="Date"
            yAxisLabel="Usage Count"
            showGrid={true}
            showLegend={true}
            className="h-80"
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Most used datasets */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center">
              <Database className="h-5 w-5 mr-2" />
              Popular Datasets
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart
              data={formatDatasetData()}
              bars={[
                {
                  dataKey: 'usage',
                  name: 'Usage Count',
                  color: '#10b981'
                }
              ]}
              xAxisKey="dataset"
              xAxisLabel="Dataset"
              yAxisLabel="Usage Count"
              showGrid={true}
              className="h-64"
            />
          </CardContent>
        </Card>

        {/* Tool usage breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center">
              <Wrench className="h-5 w-5 mr-2" />
              Tool Popularity
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {formatToolsData().slice(0, 8).map((tool, index) => (
                <div key={tool.tool} className="flex items-center justify-between">
                  <div className="flex items-center space-x-3 flex-1 min-w-0">
                    <span className="text-sm font-medium text-muted-foreground w-6">
                      #{index + 1}
                    </span>
                    <span className="font-medium truncate">{tool.tool}</span>
                  </div>
                  <div className="flex items-center space-x-3 ml-4">
                    <Progress value={tool.percentage} className="w-20" />
                    <span className="text-sm font-medium w-12 text-right">
                      {tool.usage}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Workflow success rates */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Popular Workflows</span>
            <Badge variant="secondary">
              {data.popularWorkflows.length} total workflows
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {data.popularWorkflows.slice(0, 6).map((workflow, index) => (
              <div key={workflow.workflow} className="p-4 rounded-lg border">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-medium text-sm truncate" title={workflow.workflow}>
                    {workflow.workflow.length > 30 
                      ? `${workflow.workflow.slice(0, 27)}...` 
                      : workflow.workflow
                    }
                  </h4>
                  <Badge 
                    variant={workflow.successRate >= 90 ? "default" : workflow.successRate >= 70 ? "secondary" : "destructive"}
                    className="ml-2"
                  >
                    {workflow.successRate.toFixed(0)}%
                  </Badge>
                </div>
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>{workflow.usage} runs</span>
                  <Progress value={workflow.successRate} className="w-20 ml-2" />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Modality breakdown */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Data Modality Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(data.datasetStats.modalityBreakdown)
              .sort(([, a], [, b]) => b - a)
              .map(([modality, count]) => (
              <div key={modality} className="text-center p-4 rounded-lg border">
                <div className="text-2xl font-bold text-blue-600">
                  {count.toLocaleString()}
                </div>
                <div className="text-sm text-muted-foreground capitalize">
                  {modality.replace('_', ' ')}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}