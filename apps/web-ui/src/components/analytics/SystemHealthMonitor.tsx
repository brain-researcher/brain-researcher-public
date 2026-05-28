'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { LineChart } from '@/components/charts/LineChart'
import { SystemMetrics } from '@/types/analytics'
import { 
  Cpu, 
  HardDrive, 
  MemoryStick, 
  Zap, 
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Play
} from 'lucide-react'
import { format } from 'date-fns'

interface SystemHealthMonitorProps {
  data: SystemMetrics
  loading?: boolean
  className?: string
}

export function SystemHealthMonitor({ data, loading, className }: SystemHealthMonitorProps) {
  const formatResourceHistoryData = () => {
    if (!data?.resourceHistory || !Array.isArray(data.resourceHistory)) return []
    return data.resourceHistory.slice(-48).map(item => ({
      timestamp: format(new Date(item.timestamp), 'HH:mm'),
      'CPU %': item.cpu,
      'Memory %': item.memory,
      'GPU %': item.gpu,
      'Storage %': item.storage,
      fullTimestamp: item.timestamp
    }))
  }

  const getHealthStatus = (usage: number) => {
    if (usage < 70) return { color: 'text-green-600', bg: 'bg-green-100', icon: CheckCircle, label: 'Healthy' }
    if (usage < 85) return { color: 'text-yellow-600', bg: 'bg-yellow-100', icon: AlertTriangle, label: 'Warning' }
    return { color: 'text-red-600', bg: 'bg-red-100', icon: AlertTriangle, label: 'Critical' }
  }

  const formatQueueData = () => {
    if (!data?.jobQueue || !Array.isArray(data.jobQueue) || data.jobQueue.length === 0) return []
    
    const statusCounts = data.jobQueue.reduce((acc, job) => {
      acc[job.status] = (acc[job.status] || 0) + 1
      return acc
    }, {} as Record<string, number>)

    return Object.entries(statusCounts).map(([status, count]) => ({
      status: status.charAt(0).toUpperCase() + status.slice(1),
      count,
      percentage: Math.round((count / data.jobQueue.length) * 100)
    }))
  }

  const getJobStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed': return 'text-green-600 bg-green-50'
      case 'running': return 'text-blue-600 bg-blue-50'
      case 'queued': return 'text-yellow-600 bg-yellow-50'
      case 'failed': return 'text-red-600 bg-red-50'
      default: return 'text-gray-600 bg-gray-50'
    }
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

  const cpuStatus = getHealthStatus(data?.cpuUsage || 0)
  const memoryStatus = getHealthStatus(data?.memoryUsage || 0)
  const gpuStatus = getHealthStatus(data?.gpuUsage || 0)
  const storageStatus = getHealthStatus(data?.storageUsage || 0)

  return (
    <div className={className}>
      {/* Resource usage cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <Cpu className="h-5 w-5 text-blue-600" />
                <span className="font-medium">CPU Usage</span>
              </div>
              <Badge variant="secondary" className={cpuStatus.color}>
                {cpuStatus.label}
              </Badge>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-2xl font-bold">{(data?.cpuUsage || 0).toFixed(1)}%</span>
                <cpuStatus.icon className={`h-6 w-6 ${cpuStatus.color}`} />
              </div>
              <Progress
                value={data?.cpuUsage || 0}
                className="h-2"
                aria-label="CPU usage"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <MemoryStick className="h-5 w-5 text-green-600" />
                <span className="font-medium">Memory</span>
              </div>
              <Badge variant="secondary" className={memoryStatus.color}>
                {memoryStatus.label}
              </Badge>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-2xl font-bold">{(data?.memoryUsage || 0).toFixed(1)}%</span>
                <memoryStatus.icon className={`h-6 w-6 ${memoryStatus.color}`} />
              </div>
              <Progress
                value={data?.memoryUsage || 0}
                className="h-2"
                aria-label="Memory usage"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <Zap className="h-5 w-5 text-purple-600" />
                <span className="font-medium">GPU Usage</span>
              </div>
              <Badge variant="secondary" className={gpuStatus.color}>
                {gpuStatus.label}
              </Badge>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-2xl font-bold">{(data?.gpuUsage || 0).toFixed(1)}%</span>
                <gpuStatus.icon className={`h-6 w-6 ${gpuStatus.color}`} />
              </div>
              <Progress
                value={data?.gpuUsage || 0}
                className="h-2"
                aria-label="GPU usage"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <HardDrive className="h-5 w-5 text-orange-600" />
                <span className="font-medium">Storage</span>
              </div>
              <Badge variant="secondary" className={storageStatus.color}>
                {storageStatus.label}
              </Badge>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-2xl font-bold">{(data?.storageUsage || 0).toFixed(1)}%</span>
                <storageStatus.icon className={`h-6 w-6 ${storageStatus.color}`} />
              </div>
              <Progress
                value={data?.storageUsage || 0}
                className="h-2"
                aria-label="Storage usage"
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Resource usage trends */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center">
            <Activity className="h-5 w-5 mr-2" />
            Resource Usage History (Last 48 Hours)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            data={formatResourceHistoryData()}
            lines={[
              {
                dataKey: 'CPU %',
                name: 'CPU Usage',
                color: '#3b82f6',
                strokeWidth: 2
              },
              {
                dataKey: 'Memory %',
                name: 'Memory Usage',
                color: '#10b981',
                strokeWidth: 2
              },
              {
                dataKey: 'GPU %',
                name: 'GPU Usage',
                color: '#8b5cf6',
                strokeWidth: 2
              },
              {
                dataKey: 'Storage %',
                name: 'Storage Usage',
                color: '#f59e0b',
                strokeWidth: 2
              }
            ]}
            xAxisKey="timestamp"
            xAxisLabel="Time"
            yAxisLabel="Usage (%)"
            domain={[0, 100]}
            showGrid={true}
            showLegend={true}
            showBrush={true}
            className="h-80"
            referenceLines={[
              { y: 70, label: 'Warning', stroke: '#f59e0b', strokeDasharray: '3 3' },
              { y: 85, label: 'Critical', stroke: '#ef4444', strokeDasharray: '3 3' }
            ]}
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Job queue status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center">
                <Play className="h-5 w-5 mr-2" />
                Job Queue Status
              </span>
              <Badge variant="outline">
                {data?.queueLength || 0} in queue
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="text-center p-4 rounded-lg border">
                <div className="text-2xl font-bold text-blue-600">
                  {data?.activeJobs || 0}
                </div>
                <div className="text-sm text-muted-foreground">Active Jobs</div>
              </div>
              <div className="text-center p-4 rounded-lg border">
                <div className="text-2xl font-bold text-green-600">
                  {data?.completedJobs || 0}
                </div>
                <div className="text-sm text-muted-foreground">Completed</div>
              </div>
            </div>

            <div className="space-y-3">
              {formatQueueData().map((item) => (
                <div key={item.status} className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Badge 
                      variant="secondary" 
                      className={getJobStatusColor(item.status)}
                    >
                      {item.status}
                    </Badge>
                  </div>
                  <div className="flex items-center space-x-3">
                    <Progress
                      value={item.percentage}
                      className="w-20"
                      aria-label={`Percentage of ${item.status} jobs`}
                    />
                    <span className="text-sm font-medium w-8 text-right">
                      {item.count}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Recent jobs */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center">
              <Clock className="h-5 w-5 mr-2" />
              Recent Job Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 max-h-80 overflow-y-auto">
              {(data?.jobQueue || [])
                .sort((a, b) => {
                  const aTime = a.startTime ? new Date(a.startTime).getTime() : 0
                  const bTime = b.startTime ? new Date(b.startTime).getTime() : 0
                  return bTime - aTime
                })
                .slice(0, 10)
                .map((job) => (
                <div key={job.id} className="flex items-center justify-between p-3 rounded-lg border">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="font-medium text-sm truncate">
                        {job.type}
                      </span>
                      <Badge 
                        variant="secondary"
                        className={getJobStatusColor(job.status)}
                      >
                        {job.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {job.user} • {job.id.slice(-8)}
                    </div>
                  </div>
                  <div className="text-right ml-4">
                    {job.duration && (
                      <div className="text-sm font-medium">
                        {job.duration > 3600 
                          ? `${Math.floor(job.duration / 3600)}h ${Math.floor((job.duration % 3600) / 60)}m`
                          : `${Math.floor(job.duration / 60)}m`
                        }
                      </div>
                    )}
                    {job.startTime && (
                      <div className="text-xs text-muted-foreground">
                        {format(new Date(job.startTime), 'MMM dd HH:mm')}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
