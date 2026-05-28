'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
import { 
  Cpu,
  HardDrive,
  MemoryStick,
  Zap,
  Activity,
  RefreshCw
} from 'lucide-react'
import { ResourceUsageData, WidgetComponentProps } from '@/types/dashboard'

interface ResourceUsageWidgetProps extends WidgetComponentProps {
  data?: ResourceUsageData
}

export const ResourceUsageWidget: React.FC<ResourceUsageWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  className = ''
}) => {
  const formatBytes = (bytes: number, decimals = 1) => {
    if (!Number.isFinite(bytes) || bytes < 0) return '–'
    if (bytes === 0) return '0 B'
    const k = 1024
    const dm = decimals < 0 ? 0 : decimals
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes * k) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
  }

  const getUsageColor = (percentage: number) => {
    if (!Number.isFinite(percentage)) return 'bg-slate-200'
    if (percentage < 50) return 'bg-green-500'
    if (percentage < 80) return 'bg-yellow-500'
    return 'bg-red-500'
  }

  const getUsageTextColor = (percentage: number) => {
    if (!Number.isFinite(percentage)) return 'text-muted-foreground'
    if (percentage < 50) return 'text-green-600'
    if (percentage < 80) return 'text-yellow-600'
    return 'text-red-600'
  }

  const clampPercent = (value: number) =>
    Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0

  const formatPercent = (value: number) =>
    Number.isFinite(value) ? `${value.toFixed(1)}%` : '–'

  const formatGB = (gb: number) => formatBytes(gb * 1024 * 1024 * 1024)

  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Resource Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="space-y-2">
                <div className="flex justify-between">
                  <div className="h-4 bg-gray-200 rounded w-1/4"></div>
                  <div className="h-4 bg-gray-200 rounded w-1/6"></div>
                </div>
                <div className="h-2 bg-gray-200 rounded"></div>
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
            <Activity className="h-5 w-5" />
            Resource Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Activity className="h-8 w-8 mb-2" />
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
            <Activity className="h-5 w-5" />
            Resource Usage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Activity className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm text-center">No data yet.</p>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
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
            <Activity className="h-5 w-5" />
            Resource Usage
          </CardTitle>
          {onRefresh && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onRefresh}
              aria-label="Refresh resource usage"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* CPU Usage */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-blue-500" />
              <span className="text-sm font-medium">CPU</span>
            </div>
            <div className="text-right">
              <span className={`text-sm font-semibold ${getUsageTextColor(data.cpu.usage)}`}>
                {formatPercent(data.cpu.usage)}
              </span>
              <p className="text-xs text-muted-foreground">
                {data.cpu.cores > 0 ? (
                  <>
                    {data.cpu.cores} cores
                    {data.cpu.frequency > 0 ? ` @ ${data.cpu.frequency} GHz` : ''}
                  </>
                ) : (
                  '–'
                )}
              </p>
            </div>
          </div>
          <div className="relative">
            <Progress
              value={clampPercent(data.cpu.usage)}
              className="h-2"
              aria-label="CPU usage"
            />
            <div 
              className={`absolute top-0 left-0 h-2 rounded-full transition-all duration-500 ${getUsageColor(data.cpu.usage)}`}
              style={{ width: `${clampPercent(data.cpu.usage)}%` }}
            />
          </div>
        </div>

        {/* Memory Usage */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MemoryStick className="h-4 w-4 text-green-500" />
              <span className="text-sm font-medium">Memory</span>
            </div>
            <div className="text-right">
              <span className={`text-sm font-semibold ${getUsageTextColor(data.memory.percentage)}`}>
                {formatPercent(data.memory.percentage)}
              </span>
              <p className="text-xs text-muted-foreground">
                {Number.isFinite(data.memory.total) &&
                data.memory.total > 0 &&
                Number.isFinite(data.memory.used)
                  ? `${formatGB(data.memory.used)} / ${formatGB(data.memory.total)}`
                  : '–'}
              </p>
            </div>
          </div>
          <div className="relative">
            <Progress
              value={clampPercent(data.memory.percentage)}
              className="h-2"
              aria-label="Memory usage"
            />
            <div 
              className={`absolute top-0 left-0 h-2 rounded-full transition-all duration-500 ${getUsageColor(data.memory.percentage)}`}
              style={{ width: `${clampPercent(data.memory.percentage)}%` }}
            />
          </div>
        </div>

        {/* GPU Usage */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-purple-500" />
            <span className="text-sm font-medium">GPU ({data.gpu.count} devices)</span>
          </div>
          <div className="space-y-1">
            {data.gpu.usage.map((usage, index) => (
              <div key={index} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-8">#{index + 1}</span>
                <div className="flex-1 space-y-1">
                  <div className="relative">
                    <Progress
                      value={clampPercent(usage)}
                      className="h-1.5"
                      aria-label={`GPU ${index + 1} usage`}
                    />
                    <div 
                      className={`absolute top-0 left-0 h-1.5 rounded-full transition-all duration-500 ${getUsageColor(usage)}`}
                      style={{ width: `${clampPercent(usage)}%` }}
                    />
                  </div>
                </div>
                <div className="text-right min-w-0">
                  <span className={`text-xs font-medium ${getUsageTextColor(usage)}`}>
                    {formatPercent(usage)}
                  </span>
                  <p className="text-xs text-muted-foreground">
                    {Number.isFinite(data.gpu.memory_used[index]) &&
                    Number.isFinite(data.gpu.memory_total[index]) &&
                    (data.gpu.memory_total[index] ?? 0) > 0
                      ? `${data.gpu.memory_used[index].toFixed(1)}/${data.gpu.memory_total[index].toFixed(1)}GB`
                      : '–'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Storage Usage */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-orange-500" />
              <span className="text-sm font-medium">Storage</span>
            </div>
            <div className="text-right">
              <span className={`text-sm font-semibold ${getUsageTextColor(data.storage.percentage)}`}>
                {formatPercent(data.storage.percentage)}
              </span>
              <p className="text-xs text-muted-foreground">
                {Number.isFinite(data.storage.total) &&
                data.storage.total > 0 &&
                Number.isFinite(data.storage.used)
                  ? `${formatGB(data.storage.used)} / ${formatGB(data.storage.total)}`
                  : '–'}
              </p>
            </div>
          </div>
          <div className="relative">
            <Progress
              value={clampPercent(data.storage.percentage)}
              className="h-2"
              aria-label="Storage usage"
            />
            <div 
              className={`absolute top-0 left-0 h-2 rounded-full transition-all duration-500 ${getUsageColor(data.storage.percentage)}`}
              style={{ width: `${clampPercent(data.storage.percentage)}%` }}
            />
          </div>
        </div>

        {/* Quick Stats */}
        <div className="pt-2 border-t">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="text-center">
              <p className="font-semibold text-blue-600">
                {data.cpu.cores > 0 ? data.cpu.cores : '–'}
              </p>
              <p className="text-muted-foreground">CPU Cores</p>
            </div>
            <div className="text-center">
              <p className="font-semibold text-purple-600">{data.gpu.count}</p>
              <p className="text-muted-foreground">GPUs</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
