'use client'

import React, { useState, useMemo } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Activity,
  Cpu,
  HardDrive,
  Zap,
  Network,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle,
  Clock,
  Gauge,
  BarChart3,
  LineChart,
  PieChart,
  Download,
  Settings,
  RefreshCw
} from 'lucide-react'

import { PipelineNodeData } from './PipelineNode'

interface ResourceData {
  cpu: number
  memory: number
  gpu?: number
  networkIO?: number
  timestamp: Date
}

interface NodeResourceUsage {
  nodeId: string
  nodeName: string
  current: ResourceData
  average: ResourceData
  peak: ResourceData
  history: ResourceData[]
  alerts: Array<{
    type: 'warning' | 'critical'
    metric: string
    value: number
    threshold: number
    timestamp: Date
  }>
}

interface ResourceMonitorProps {
  pipelineId: string
  nodes: Record<string, PipelineNodeData>
  className?: string
  refreshInterval?: number
  showHistory?: boolean
  alertThresholds?: {
    cpu: { warning: number; critical: number }
    memory: { warning: number; critical: number }
    gpu: { warning: number; critical: number }
  }
}

const defaultThresholds = {
  cpu: { warning: 80, critical: 95 },
  memory: { warning: 85, critical: 95 },
  gpu: { warning: 85, critical: 95 }
}

export function ResourceMonitor({
  pipelineId,
  nodes,
  className = '',
  refreshInterval = 5000,
  showHistory = true,
  alertThresholds = defaultThresholds
}: ResourceMonitorProps) {
  const [selectedMetric, setSelectedMetric] = useState<'cpu' | 'memory' | 'gpu' | 'networkIO'>('cpu')
  const [viewMode, setViewMode] = useState<'overview' | 'detailed' | 'alerts'>('overview')
  const [autoRefresh, setAutoRefresh] = useState(true)

  const resourceUsage = useMemo((): NodeResourceUsage[] => {
    return Object.entries(nodes).map(([nodeId, nodeData]) => {
      const current = nodeData.resources || {}
      
      const currentData: ResourceData = {
        cpu: current.cpu || 0,
        memory: current.memory || 0,
        gpu: current.gpu,
        networkIO: current.networkIO,
        timestamp: new Date()
      }

      const history: ResourceData[] = showHistory ? [currentData] : []
      const averageData: ResourceData = currentData
      const peakData: ResourceData = currentData

      // Generate alerts
      const alerts: NodeResourceUsage['alerts'] = []
      if (currentData.cpu > alertThresholds.cpu.critical) {
        alerts.push({
          type: 'critical',
          metric: 'CPU',
          value: currentData.cpu,
          threshold: alertThresholds.cpu.critical,
          timestamp: new Date()
        })
      } else if (currentData.cpu > alertThresholds.cpu.warning) {
        alerts.push({
          type: 'warning',
          metric: 'CPU',
          value: currentData.cpu,
          threshold: alertThresholds.cpu.warning,
          timestamp: new Date()
        })
      }

      if (currentData.memory > alertThresholds.memory.critical) {
        alerts.push({
          type: 'critical',
          metric: 'Memory',
          value: currentData.memory,
          threshold: alertThresholds.memory.critical,
          timestamp: new Date()
        })
      } else if (currentData.memory > alertThresholds.memory.warning) {
        alerts.push({
          type: 'warning',
          metric: 'Memory',
          value: currentData.memory,
          threshold: alertThresholds.memory.warning,
          timestamp: new Date()
        })
      }

      return {
        nodeId,
        nodeName: nodeData.label,
        current: currentData,
        average: averageData,
        peak: peakData,
        history,
        alerts
      }
    }).filter(usage => 
      usage.current.cpu > 0 || 
      usage.current.memory > 0 || 
      usage.current.gpu !== undefined || 
      usage.current.networkIO !== undefined
    )
  }, [nodes, alertThresholds, showHistory])

  const systemStats = useMemo(() => {
    if (resourceUsage.length === 0) return null

    const totalCpu = resourceUsage.reduce((sum, node) => sum + node.current.cpu, 0) / resourceUsage.length
    const totalMemory = resourceUsage.reduce((sum, node) => sum + node.current.memory, 0) / resourceUsage.length
    const totalGpu = resourceUsage
      .filter(node => node.current.gpu !== undefined)
      .reduce((sum, node) => sum + (node.current.gpu || 0), 0) / 
      resourceUsage.filter(node => node.current.gpu !== undefined).length || 0

    const activeAlerts = resourceUsage.flatMap(node => node.alerts)
    const criticalAlerts = activeAlerts.filter(alert => alert.type === 'critical')
    const warningAlerts = activeAlerts.filter(alert => alert.type === 'warning')

    return {
      cpu: { current: totalCpu, status: totalCpu > 90 ? 'critical' : totalCpu > 70 ? 'warning' : 'normal' },
      memory: { current: totalMemory, status: totalMemory > 90 ? 'critical' : totalMemory > 80 ? 'warning' : 'normal' },
      gpu: { current: totalGpu, status: totalGpu > 90 ? 'critical' : totalGpu > 80 ? 'warning' : 'normal' },
      alerts: { critical: criticalAlerts.length, warning: warningAlerts.length },
      activeNodes: resourceUsage.filter(node => node.current.cpu > 1 || node.current.memory > 1).length
    }
  }, [resourceUsage])

  const getResourceIcon = (metric: string, status: string) => {
    const iconMap = {
      cpu: Cpu,
      memory: HardDrive,
      gpu: Zap,
      networkIO: Network
    }
    const Icon = iconMap[metric as keyof typeof iconMap] || Activity

    const colorMap = {
      normal: 'text-green-500',
      warning: 'text-yellow-500',
      critical: 'text-red-500'
    }
    
    return <Icon className={`h-4 w-4 ${colorMap[status as keyof typeof colorMap]}`} />
  }

  const getStatusBadge = (value: number, thresholds: { warning: number; critical: number }) => {
    if (value >= thresholds.critical) {
      return <Badge variant="destructive" className="text-xs">Critical</Badge>
    } else if (value >= thresholds.warning) {
      return <Badge variant="secondary" className="text-xs">Warning</Badge>
    }
    return <Badge variant="default" className="text-xs">Normal</Badge>
  }

  const formatBytes = (bytes: number) => {
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = bytes
    let unitIndex = 0

    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024
      unitIndex++
    }

    return `${value.toFixed(1)} ${units[unitIndex]}`
  }

  if (resourceUsage.length === 0) {
    return (
      <Card className={`p-6 ${className}`}>
        <div className="text-center text-muted-foreground">
          <Activity className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p>No resource data available</p>
          <p className="text-sm">Resource monitoring will appear when nodes are executing.</p>
        </div>
      </Card>
    )
  }

  return (
    <Card className={className}>
      <div className="p-4 border-b">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Resource Monitor
          </h3>
          <div className="flex items-center gap-2">
            <Button
              onClick={() => setAutoRefresh(!autoRefresh)}
              variant={autoRefresh ? "default" : "outline"}
              size="sm"
            >
              <RefreshCw className={`h-4 w-4 ${autoRefresh ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        {/* System Overview */}
        {systemStats && (
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {getResourceIcon('cpu', systemStats.cpu.status)}
                  <span className="text-sm font-medium">CPU</span>
                </div>
                {getStatusBadge(systemStats.cpu.current, alertThresholds.cpu)}
              </div>
              <Progress value={systemStats.cpu.current} className="h-2" />
              <div className="text-xs text-muted-foreground mt-1">
                {Math.round(systemStats.cpu.current)}% average
              </div>
            </div>

            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {getResourceIcon('memory', systemStats.memory.status)}
                  <span className="text-sm font-medium">Memory</span>
                </div>
                {getStatusBadge(systemStats.memory.current, alertThresholds.memory)}
              </div>
              <Progress value={systemStats.memory.current} className="h-2" />
              <div className="text-xs text-muted-foreground mt-1">
                {Math.round(systemStats.memory.current)}% average
              </div>
            </div>

            {systemStats.gpu.current > 0 && (
              <div className="p-3 bg-muted/50 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {getResourceIcon('gpu', systemStats.gpu.status)}
                    <span className="text-sm font-medium">GPU</span>
                  </div>
                  {getStatusBadge(systemStats.gpu.current, alertThresholds.gpu)}
                </div>
                <Progress value={systemStats.gpu.current} className="h-2" />
                <div className="text-xs text-muted-foreground mt-1">
                  {Math.round(systemStats.gpu.current)}% average
                </div>
              </div>
            )}

            <div className="p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Gauge className="h-4 w-4 text-blue-500" />
                  <span className="text-sm font-medium">Active</span>
                </div>
              </div>
              <div className="text-lg font-semibold">{systemStats.activeNodes}</div>
              <div className="text-xs text-muted-foreground">
                {systemStats.activeNodes} / {Object.keys(nodes).length} nodes
              </div>
            </div>
          </div>
        )}

        {/* Alerts Summary */}
        {systemStats?.alerts && (systemStats.alerts.critical > 0 || systemStats.alerts.warning > 0) && (
          <div className="p-3 bg-yellow-50 dark:bg-yellow-950/20 border border-yellow-200 dark:border-yellow-800 rounded-lg mb-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="h-4 w-4 text-yellow-600" />
              <span className="font-medium text-yellow-800 dark:text-yellow-200">Resource Alerts</span>
            </div>
            <div className="flex gap-4 text-sm">
              {systemStats.alerts.critical > 0 && (
                <span className="text-red-600 dark:text-red-400">
                  {systemStats.alerts.critical} critical
                </span>
              )}
              {systemStats.alerts.warning > 0 && (
                <span className="text-yellow-600 dark:text-yellow-400">
                  {systemStats.alerts.warning} warnings
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as typeof viewMode)} className="h-full flex flex-col">
        <TabsList className="mx-4 mt-2 grid w-full grid-cols-3">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="detailed">Details</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="flex-1 overflow-hidden">
          <ScrollArea className="h-80">
            <div className="p-4 space-y-4">
              {resourceUsage.map((nodeUsage) => (
                <Card key={nodeUsage.nodeId} className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="font-medium text-sm">{nodeUsage.nodeName}</h4>
                    <Badge variant="outline" className="text-xs">
                      {nodes[nodeUsage.nodeId]?.status || 'unknown'}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1">
                          <Cpu className="h-3 w-3 text-blue-500" />
                          <span className="text-xs">CPU</span>
                        </div>
                        <span className="text-xs font-mono">
                          {Math.round(nodeUsage.current.cpu)}%
                        </span>
                      </div>
                      <Progress value={nodeUsage.current.cpu} className="h-1.5" />
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1">
                          <HardDrive className="h-3 w-3 text-green-500" />
                          <span className="text-xs">Memory</span>
                        </div>
                        <span className="text-xs font-mono">
                          {Math.round(nodeUsage.current.memory)}%
                        </span>
                      </div>
                      <Progress value={nodeUsage.current.memory} className="h-1.5" />
                    </div>

                    {nodeUsage.current.gpu !== undefined && (
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-1">
                            <Zap className="h-3 w-3 text-yellow-500" />
                            <span className="text-xs">GPU</span>
                          </div>
                          <span className="text-xs font-mono">
                            {Math.round(nodeUsage.current.gpu)}%
                          </span>
                        </div>
                        <Progress value={nodeUsage.current.gpu} className="h-1.5" />
                      </div>
                    )}

                    {nodeUsage.current.networkIO !== undefined && (
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-1">
                            <Network className="h-3 w-3 text-purple-500" />
                            <span className="text-xs">Network</span>
                          </div>
                          <span className="text-xs font-mono">
                            {Math.round(nodeUsage.current.networkIO)}%
                          </span>
                        </div>
                        <Progress value={nodeUsage.current.networkIO} className="h-1.5" />
                      </div>
                    )}
                  </div>

                  {/* Trend indicators */}
                  <div className="flex items-center justify-between mt-3 pt-2 border-t border-muted/50">
                    <div className="flex gap-3 text-xs text-muted-foreground">
                      <span>Avg: {Math.round(nodeUsage.average.cpu)}%</span>
                      <span>Peak: {Math.round(nodeUsage.peak.cpu)}%</span>
                    </div>
                    {nodeUsage.alerts.length > 0 && (
                      <Badge variant="destructive" className="text-xs">
                        {nodeUsage.alerts.length} alerts
                      </Badge>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="detailed" className="flex-1 overflow-hidden">
          <div className="p-4 space-y-4">
            <Select value={selectedMetric} onValueChange={(value: any) => setSelectedMetric(value)}>
              <SelectTrigger>
                <SelectValue placeholder="Select metric" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cpu">CPU Usage</SelectItem>
                <SelectItem value="memory">Memory Usage</SelectItem>
                <SelectItem value="gpu">GPU Usage</SelectItem>
                <SelectItem value="networkIO">Network I/O</SelectItem>
              </SelectContent>
            </Select>

            <ScrollArea className="h-64">
              <div className="space-y-3">
                {resourceUsage.map((nodeUsage) => {
                  const metricValue = nodeUsage.current[selectedMetric]
                  const avgValue = nodeUsage.average[selectedMetric]
                  const peakValue = nodeUsage.peak[selectedMetric]

                  if (metricValue === undefined) return null

                  const trend = avgValue ? (metricValue - avgValue) / avgValue : 0
                  const TrendIcon = trend > 0.1 ? TrendingUp : trend < -0.1 ? TrendingDown : Minus

                  return (
                    <Card key={nodeUsage.nodeId} className="p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="font-medium text-sm">{nodeUsage.nodeName}</h4>
                        <div className="flex items-center gap-2">
                          <TrendIcon className={`h-4 w-4 ${
                            trend > 0.1 ? 'text-red-500' : 
                            trend < -0.1 ? 'text-green-500' : 
                            'text-gray-400'
                          }`} />
                          <span className="text-xs font-mono">
                            {Math.round(metricValue)}%
                          </span>
                        </div>
                      </div>

                      <Progress value={metricValue} className="mb-3" />

                      <div className="grid grid-cols-3 gap-3 text-xs">
                        <div className="text-center">
                          <div className="font-medium">{Math.round(metricValue)}%</div>
                          <div className="text-muted-foreground">Current</div>
                        </div>
                        <div className="text-center">
                          <div className="font-medium">{avgValue ? Math.round(avgValue) : '--'}%</div>
                          <div className="text-muted-foreground">Average</div>
                        </div>
                        <div className="text-center">
                          <div className="font-medium">{peakValue ? Math.round(peakValue) : '--'}%</div>
                          <div className="text-muted-foreground">Peak</div>
                        </div>
                      </div>
                    </Card>
                  )
                })}
              </div>
            </ScrollArea>
          </div>
        </TabsContent>

        <TabsContent value="alerts" className="flex-1 overflow-hidden">
          <ScrollArea className="h-80">
            <div className="p-4">
              {resourceUsage.flatMap(node => 
                node.alerts.map(alert => ({...alert, nodeName: node.nodeName, nodeId: node.nodeId}))
              ).length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  <CheckCircle className="h-8 w-8 mx-auto mb-2 text-green-500" />
                  <p>No active alerts</p>
                  <p className="text-sm">All resources are within normal thresholds.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {resourceUsage.flatMap(node => 
                    node.alerts.map(alert => ({...alert, nodeName: node.nodeName, nodeId: node.nodeId}))
                  )
                  .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
                  .map((alert, index) => (
                    <Card key={`${alert.nodeId}-${alert.metric}-${index}`} 
                          className={`p-4 ${alert.type === 'critical' ? 'border-red-500' : 'border-yellow-500'}`}>
                      <div className="flex items-start justify-between">
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <AlertTriangle className={`h-4 w-4 ${
                              alert.type === 'critical' ? 'text-red-500' : 'text-yellow-500'
                            }`} />
                            <Badge variant={alert.type === 'critical' ? 'destructive' : 'secondary'} className="text-xs">
                              {alert.type}
                            </Badge>
                            <span className="text-sm font-medium">{alert.nodeName}</span>
                          </div>
                          <div className="text-sm">
                            {alert.metric} usage at {Math.round(alert.value)}% 
                            (threshold: {alert.threshold}%)
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {alert.timestamp.toLocaleTimeString()}
                          </div>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  )
}

export default ResourceMonitor
