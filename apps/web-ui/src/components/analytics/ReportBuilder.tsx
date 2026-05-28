'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { 
  Plus, 
  Trash2, 
  Save, 
  Eye,
  BarChart3,
  LineChart as LineChartIcon,
  PieChart,
  Activity,
  Users,
  Database
} from 'lucide-react'
import { ChartConfig, CustomReport, AnalyticsFilter } from '@/types/analytics'

interface ReportBuilderProps {
  onSave: (report: Omit<CustomReport, 'id' | 'createdAt' | 'updatedAt'>) => Promise<void>
  filter: AnalyticsFilter
  className?: string
  initialReport?: CustomReport
}

interface ChartTemplate {
  type: ChartConfig['type']
  name: string
  icon: React.ReactNode
  description: string
  requiredData: string[]
  defaultOptions: Record<string, any>
}

const CHART_TEMPLATES: ChartTemplate[] = [
  {
    type: 'line',
    name: 'Line Chart',
    icon: <LineChartIcon className="h-5 w-5" />,
    description: 'Show trends over time',
    requiredData: ['timestamp', 'value'],
    defaultOptions: {
      xAxis: 'timestamp',
      yAxis: 'value',
      showGrid: true,
      showLegend: true
    }
  },
  {
    type: 'bar',
    name: 'Bar Chart',
    icon: <BarChart3 className="h-5 w-5" />,
    description: 'Compare values across categories',
    requiredData: ['category', 'value'],
    defaultOptions: {
      xAxis: 'category',
      yAxis: 'value',
      showGrid: true,
      orientation: 'vertical'
    }
  },
  {
    type: 'pie',
    name: 'Pie Chart',
    icon: <PieChart className="h-5 w-5" />,
    description: 'Show proportions of a whole',
    requiredData: ['category', 'value'],
    defaultOptions: {
      labelKey: 'category',
      valueKey: 'value',
      showLabels: true
    }
  },
  {
    type: 'gauge',
    name: 'Gauge',
    icon: <Activity className="h-5 w-5" />,
    description: 'Display single metric with target',
    requiredData: ['value'],
    defaultOptions: {
      min: 0,
      max: 100,
      target: 80,
      unit: '%'
    }
  }
]

const METRIC_CATEGORIES = [
  {
    name: 'Usage Metrics',
    icon: <Users className="h-4 w-4" />,
    metrics: [
      'totalUsers',
      'activeUsers',
      'newUsers',
      'sessionsPerUser',
      'avgSessionDuration',
      'pageViewsPerSession',
      'bounceRate'
    ]
  },
  {
    name: 'Performance Metrics',
    icon: <Activity className="h-4 w-4" />,
    metrics: [
      'avgResponseTime',
      'p95ResponseTime',
      'successRate',
      'errorRate',
      'throughput',
      'uptime'
    ]
  },
  {
    name: 'Research Metrics',
    icon: <Database className="h-4 w-4" />,
    metrics: [
      'analysesRun',
      'datasetsUsed',
      'toolsUsed',
      'popularWorkflows',
      'totalCitations',
      'hIndex'
    ]
  }
]

export function ReportBuilder({ onSave, filter, className, initialReport }: ReportBuilderProps) {
  const NO_SCHEDULE = '__no_schedule__'
  const [report, setReport] = useState<Omit<CustomReport, 'id' | 'createdAt' | 'updatedAt'>>({
    name: initialReport?.name || '',
    description: initialReport?.description || '',
    charts: initialReport?.charts || [],
    filters: initialReport?.filters || filter,
    schedule: initialReport?.schedule
  })

  const [selectedChartIndex, setSelectedChartIndex] = useState<number | null>(null)
  const [showPreview, setShowPreview] = useState(false)

  const addChart = (template: ChartTemplate) => {
    const newChart: ChartConfig = {
      type: template.type,
      data: [],
      options: template.defaultOptions,
      title: `${template.name} - ${report.charts.length + 1}`,
      description: template.description
    }

    setReport(prev => ({
      ...prev,
      charts: [...prev.charts, newChart]
    }))

    setSelectedChartIndex(report.charts.length)
  }

  const updateChart = (index: number, updates: Partial<ChartConfig>) => {
    setReport(prev => ({
      ...prev,
      charts: prev.charts.map((chart, i) => 
        i === index ? { ...chart, ...updates } : chart
      )
    }))
  }

  const removeChart = (index: number) => {
    setReport(prev => ({
      ...prev,
      charts: prev.charts.filter((_, i) => i !== index)
    }))

    if (selectedChartIndex === index) {
      setSelectedChartIndex(null)
    } else if (selectedChartIndex !== null && selectedChartIndex > index) {
      setSelectedChartIndex(selectedChartIndex - 1)
    }
  }

  const handleSave = async () => {
    if (!report.name.trim()) {
      alert('Please enter a report name')
      return
    }

    try {
      await onSave(report)
      // Reset form or show success message
    } catch (error) {
      console.error('Failed to save report:', error)
      alert('Failed to save report. Please try again.')
    }
  }

  const selectedChart = selectedChartIndex !== null ? report.charts[selectedChartIndex] : null

  return (
    <div className={className}>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Report Configuration */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Report Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="reportName">Report Name</Label>
              <Input
                id="reportName"
                value={report.name}
                onChange={(e) => setReport(prev => ({ ...prev, name: e.target.value }))}
                placeholder="My Analytics Report"
              />
            </div>

            <div>
              <Label htmlFor="reportDescription">Description</Label>
              <Textarea
                id="reportDescription"
                value={report.description}
                onChange={(e) => setReport(prev => ({ ...prev, description: e.target.value }))}
                placeholder="Brief description of this report..."
                rows={3}
              />
            </div>

            <div>
              <Label>Schedule (Optional)</Label>
              <Select
                value={report.schedule?.frequency || NO_SCHEDULE}
                onValueChange={(value) => 
                  setReport(prev => ({
                    ...prev,
                    schedule: value === NO_SCHEDULE ? undefined : {
                      frequency: value as any, 
                      recipients: [],
                      time: '09:00'
                    }
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="No scheduling" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_SCHEDULE}>No scheduling</SelectItem>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex space-x-2">
              <Button onClick={handleSave} className="flex-1">
                <Save className="h-4 w-4 mr-2" />
                Save Report
              </Button>
              <Button 
                variant="outline" 
                onClick={() => setShowPreview(!showPreview)}
              >
                <Eye className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Chart Templates */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Add Charts</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {CHART_TEMPLATES.map((template) => (
                <div
                  key={template.type}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer"
                  onClick={() => addChart(template)}
                >
                  <div className="flex items-center space-x-3">
                    {template.icon}
                    <div>
                      <h4 className="font-medium text-sm">{template.name}</h4>
                      <p className="text-xs text-muted-foreground">
                        {template.description}
                      </p>
                    </div>
                  </div>
                  <Button size="sm" variant="ghost">
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Chart Configuration */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>
              Chart Configuration
              {selectedChart && (
                <Badge variant="secondary" className="ml-2">
                  {selectedChart.type}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {selectedChart ? (
              <div className="space-y-4">
                <div>
                  <Label>Chart Title</Label>
                  <Input
                    value={selectedChart.title || ''}
                    onChange={(e) => updateChart(selectedChartIndex!, { 
                      title: e.target.value 
                    })}
                    placeholder="Chart title"
                  />
                </div>

                <div>
                  <Label>Description</Label>
                  <Textarea
                    value={selectedChart.description || ''}
                    onChange={(e) => updateChart(selectedChartIndex!, { 
                      description: e.target.value 
                    })}
                    placeholder="Chart description"
                    rows={2}
                  />
                </div>

                {/* Chart-specific options */}
                {selectedChart.type === 'line' && (
                  <>
                    <div>
                      <Label>X-Axis Field</Label>
                      <Select
                        value={selectedChart.options?.xAxis || ''}
                        onValueChange={(value) => updateChart(selectedChartIndex!, {
                          options: { ...selectedChart.options, xAxis: value }
                        })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select field" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="timestamp">Timestamp</SelectItem>
                          <SelectItem value="date">Date</SelectItem>
                          <SelectItem value="hour">Hour</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <Label>Y-Axis Field</Label>
                      <Select
                        value={selectedChart.options?.yAxis || ''}
                        onValueChange={(value) => updateChart(selectedChartIndex!, {
                          options: { ...selectedChart.options, yAxis: value }
                        })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select metric" />
                        </SelectTrigger>
                        <SelectContent>
                          {METRIC_CATEGORIES.map(category => (
                            <div key={category.name}>
                              <div className="px-2 py-1 text-xs font-medium text-muted-foreground">
                                {category.name}
                              </div>
                              {category.metrics.map(metric => (
                                <SelectItem key={metric} value={metric}>
                                  {metric.replace(/([A-Z])/g, ' $1').toLowerCase()}
                                </SelectItem>
                              ))}
                            </div>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </>
                )}

                <div className="flex items-center space-x-2">
                  <Checkbox
                    checked={selectedChart.options?.showGrid !== false}
                    onCheckedChange={(checked) => updateChart(selectedChartIndex!, {
                      options: { ...selectedChart.options, showGrid: checked }
                    })}
                  />
                  <Label>Show Grid</Label>
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    checked={selectedChart.options?.showLegend !== false}
                    onCheckedChange={(checked) => updateChart(selectedChartIndex!, {
                      options: { ...selectedChart.options, showLegend: checked }
                    })}
                  />
                  <Label>Show Legend</Label>
                </div>

                <Button 
                  variant="destructive" 
                  size="sm"
                  onClick={() => removeChart(selectedChartIndex!)}
                  className="w-full"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Remove Chart
                </Button>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <BarChart3 className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Select a chart to configure</p>
                <p className="text-sm">Add charts from the templates on the left</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Chart List */}
      {report.charts.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Report Charts ({report.charts.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {report.charts.map((chart, index) => (
                <div
                  key={index}
                  className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                    selectedChartIndex === index 
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20' 
                      : 'hover:bg-gray-50 dark:hover:bg-gray-800'
                  }`}
                  onClick={() => setSelectedChartIndex(index)}
                >
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-medium text-sm">{chart.title}</h4>
                    <Badge variant="outline" className="text-xs">
                      {chart.type}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {chart.description || 'No description'}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
