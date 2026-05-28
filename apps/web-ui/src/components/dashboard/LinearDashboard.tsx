'use client'

import Link from 'next/link'
import { useState, useEffect, useMemo } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import {
  Activity,
  Brain,
  Database,
  FileText,
  FolderOpen,
  GitBranch,
  HardDrive,
  Layers,
  Network,
  Package,
  Server,
  TrendingUp,
  Users,
  Zap,
  ArrowUpRight,
} from 'lucide-react'
import { ResourceUsageWidget } from '@/components/dashboard/widget-library/ResourceUsageWidget'
import { Badge } from '@/components/ui/badge'
import { useDashboardData } from '@/hooks/useDashboardData'
import { routes } from '@/config/routes'
import { LineChart } from '@/components/charts/LineChart'
import { formatDistanceToNow } from 'date-fns'

interface Stat {
  label: string
  value: string | number
  change?: string
  trend?: 'up' | 'down' | 'neutral'
  icon: React.ReactNode
}

interface ActivityEntry {
  id: string
  type: 'analysis' | 'dataset' | 'pipeline' | 'collaboration'
  title: string
  description: string
  timestamp: string
  user?: string
  status?: 'completed' | 'running' | 'failed'
}

type HealthServiceStatus = {
  name: string
  status: string
  latency_ms?: number | null
  detail?: string
}

type HealthPayload = {
  status: string
  services: HealthServiceStatus[]
  duration_ms?: number
}

type TrendingItem = {
  query: string
  count?: number
  growth_rate?: number
  category?: string
  last_searched?: string
}

type RealtimeSnapshot = {
  timestamp?: string
  cpuUsage?: number
  memoryUsage?: number
  responseTime?: number
  requestsPerSecond?: number
  errorRate?: number
  activeUsers?: number
}

export function LinearDashboard() {
  const [isMounted, setIsMounted] = useState(false)
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const {
    data: dashboardData,
    loading: dashboardLoading,
    error: dashboardError,
    connected: dashboardConnected,
  } = useDashboardData()
  const [mcpUserFilter, setMcpUserFilter] = useState<'all' | 'used' | 'unused'>('all')
  const [health, setHealth] = useState<HealthPayload | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [trending, setTrending] = useState<TrendingItem[]>([])
  const [realtime, setRealtime] = useState<RealtimeSnapshot | null>(null)

  // Determine which view is active based on query parameter or current path
  const getActiveView = () => {
    const viewParam = searchParams.get('view')
    if (viewParam === 'analytics') return 'analytics'
    if (viewParam === 'resources') return 'resources'
    if (pathname?.includes('/analytics')) return 'analytics'
    if (pathname?.includes('/resources')) return 'resources'
    return 'overview'
  }

  const [activeView, setActiveView] = useState<'overview' | 'analytics' | 'resources'>(getActiveView())

  useEffect(() => {
    // Update active view when URL changes
    setActiveView(getActiveView())
  }, [searchParams, pathname])

  useEffect(() => {
    setIsMounted(true)
  }, [])

  useEffect(() => {
    let cancelled = false

    const fetchHealth = async () => {
      try {
        const response = await fetch('/api/health/full', { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`health ${response.status}`)
        }
        const json = (await response.json()) as HealthPayload
        if (!cancelled) {
          setHealth(json)
          setHealthError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setHealth(null)
          setHealthError(err instanceof Error ? err.message : 'Failed to load health')
        }
      }
    }

    void fetchHealth()
    const id = setInterval(fetchHealth, 15_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const fetchTrending = async () => {
      try {
        const response = await fetch('/api/search/trending?timeframe=24h&limit=5', {
          cache: 'no-store',
        })
        if (!response.ok) {
          throw new Error(`trending ${response.status}`)
        }
        const json = (await response.json()) as { trending?: TrendingItem[] }
        const items = Array.isArray(json.trending) ? json.trending : []
        if (!cancelled) {
          setTrending(items.filter((item) => item?.query).slice(0, 5))
        }
      } catch {
        if (!cancelled) {
          setTrending([])
        }
      }
    }

    void fetchTrending()
    const id = setInterval(fetchTrending, 30_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const fetchRealtime = async () => {
      try {
        const response = await fetch('/api/analytics/realtime', { cache: 'no-store' })
        if (!response.ok) {
          throw new Error(`realtime ${response.status}`)
        }
        const json = (await response.json()) as RealtimeSnapshot
        if (!cancelled) {
          setRealtime(json)
        }
      } catch {
        if (!cancelled) {
          setRealtime(null)
        }
      }
    }

    void fetchRealtime()
    const id = setInterval(fetchRealtime, 15_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const queueSnapshot = dashboardData?.jobMetrics?.queue
  const throughputPerMinute =
    typeof dashboardData?.jobMetrics?.throughputPerMinute === 'number'
      ? dashboardData.jobMetrics.throughputPerMinute
      : null
  const activeWorkers =
    typeof dashboardData?.jobMetrics?.activeWorkers === 'number'
      ? dashboardData.jobMetrics.activeWorkers
      : null
  const oldestQueuedSeconds =
    typeof dashboardData?.jobMetrics?.oldestPendingSeconds === 'number'
      ? dashboardData.jobMetrics.oldestPendingSeconds
      : null
  const successRate = useMemo(() => {
    const completed = queueSnapshot?.completed ?? 0
    const failed = queueSnapshot?.failed ?? 0
    const total = completed + failed
    if (total <= 0) return null
    return (completed / total) * 100
  }, [queueSnapshot?.completed, queueSnapshot?.failed])

  const resourceUsageData = useMemo(() => {
    if (!dashboardData && !realtime) return undefined

    const cluster = (dashboardData?.resourceMetrics?.cluster || {}) as Record<string, any>
    const clusterCpu =
      typeof cluster.cpuUsage === 'number'
        ? cluster.cpuUsage
        : typeof cluster.cpu_usage === 'number'
          ? cluster.cpu_usage
          : null
    const clusterMemory =
      typeof cluster.memoryUsage === 'number'
        ? cluster.memoryUsage
        : typeof cluster.memory_usage === 'number'
          ? cluster.memory_usage
          : null

    const gpuSamples = dashboardData?.resourceMetrics?.gpuSamples || []
    const latestGpu = gpuSamples[gpuSamples.length - 1]
    const gpuUsage = latestGpu
      ? [latestGpu.gpu1, latestGpu.gpu2, latestGpu.gpu3, latestGpu.gpu4].filter((v) =>
          Number.isFinite(v),
        )
      : []

    const primaryStorage = dashboardData?.storageMetrics?.primary
    const storageTotal =
      typeof primaryStorage?.total === 'number' ? primaryStorage.total : Number.NaN
    const storageUsed =
      typeof primaryStorage?.used === 'number' ? primaryStorage.used : Number.NaN
    const storagePct =
      Number.isFinite(storageTotal) && storageTotal > 0 && Number.isFinite(storageUsed)
        ? (storageUsed / storageTotal) * 100
        : Number.NaN

    const cpuUsage =
      clusterCpu != null
        ? clusterCpu
        : typeof realtime?.cpuUsage === 'number'
          ? realtime.cpuUsage
          : Number.NaN
    const memoryUsage =
      clusterMemory != null
        ? clusterMemory
        : typeof realtime?.memoryUsage === 'number'
          ? realtime.memoryUsage
          : Number.NaN
    const cpuCores =
      typeof navigator !== 'undefined' && typeof navigator.hardwareConcurrency === 'number'
        ? navigator.hardwareConcurrency
        : 0

    return {
      cpu: { usage: cpuUsage, cores: cpuCores, frequency: Number.NaN },
      memory: { used: Number.NaN, total: Number.NaN, percentage: memoryUsage },
      gpu: {
        count: gpuUsage.length,
        usage: gpuUsage as number[],
        memory_used: new Array(gpuUsage.length).fill(Number.NaN) as number[],
        memory_total: new Array(gpuUsage.length).fill(Number.NaN) as number[],
      },
      storage: {
        used: storageUsed,
        total: storageTotal,
        percentage: storagePct,
      },
    }
  }, [dashboardData, realtime])

  const stats: Stat[] = useMemo(() => {
    const items: Stat[] = []

    if (dashboardData?.jobMetrics?.queue) {
      const { running, queued, completed, failed } = dashboardData.jobMetrics.queue
      if (typeof running === 'number') {
        items.push({
          label: 'Active Jobs',
          value: running.toLocaleString(),
          change: `Queued: ${(queued ?? 0).toLocaleString()}`,
          trend: 'neutral',
          icon: <Activity className="h-4 w-4 text-blue-600" />,
        })
      }
      if (typeof completed === 'number') {
        const failedCount = typeof failed === 'number' ? failed : 0
        const total = completed + failedCount
        const successRate = total > 0 ? (completed / total) * 100 : 100
        items.push({
          label: 'Jobs Completed',
          value: completed.toLocaleString(),
          change: `${successRate.toFixed(1)}% success`,
          trend: successRate >= 95 ? 'up' : successRate < 80 ? 'down' : 'neutral',
          icon: <GitBranch className="h-4 w-4 text-purple-600" />,
        })
      }
    }

    if (throughputPerMinute != null) {
      items.push({
        label: 'Throughput',
        value: `${(throughputPerMinute * 60).toFixed(0)} jobs/hr`,
        change: 'From recent completions',
        trend: throughputPerMinute > 0 ? 'up' : 'neutral',
        icon: <TrendingUp className="h-4 w-4 text-blue-500" />,
      })
    }

    if (activeWorkers != null) {
      items.push({
        label: 'Active Workers',
        value: activeWorkers.toLocaleString(),
        change: dashboardData?.jobMetrics?.queueSource
          ? `Source: ${dashboardData.jobMetrics.queueSource}`
          : 'Queue backend',
        trend: activeWorkers > 0 ? 'up' : 'neutral',
        icon: <Users className="h-4 w-4 text-green-600" />,
      })
    }

    if (health?.duration_ms != null) {
      items.push({
        label: 'Health Latency',
        value: `${health.duration_ms.toFixed(0)} ms`,
        change: health.status === 'ok' ? 'All services OK' : `Status: ${health.status}`,
        trend: health.status === 'ok' ? 'up' : 'down',
        icon: <Zap className="h-4 w-4 text-orange-500" />,
      })
    }

    if (dashboardData?.storageMetrics?.primary) {
      const used = dashboardData.storageMetrics.primary.used ?? 0
      const total = dashboardData.storageMetrics.primary.total ?? 0
      const percent = total > 0 ? (used / total) * 100 : 0
      items.push({
        label: 'Primary Storage',
        value: `${used.toLocaleString()} GB`,
        change: total > 0 ? `${percent.toFixed(0)}% of ${total.toLocaleString()} GB` : 'No capacity data',
        trend: percent > 85 ? 'down' : 'neutral',
        icon: <HardDrive className="h-4 w-4 text-teal-600" />,
      })
    }

    return items.slice(0, 6)
  }, [dashboardData, throughputPerMinute, activeWorkers, health?.duration_ms, health?.status, dashboardData?.jobMetrics?.queueSource])

  const recentActivity: ActivityEntry[] = useMemo(() => {
    if (!dashboardData?.activity?.length) {
      return []
    }

    return dashboardData.activity.slice(0, 6).map((event) => {
      const eventType = event.type
      const mappedType: ActivityEntry['type'] =
        eventType === 'upload'
          ? 'dataset'
          : eventType === 'submit'
            ? 'pipeline'
            : eventType === 'error'
              ? 'pipeline'
              : 'analysis'

      const status: ActivityEntry['status'] =
        eventType === 'error' ? 'failed' : eventType === 'start' ? 'running' : 'completed'

      const timestampLabel = event.timestamp
        ? formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })
        : 'Just now'

      const description =
        eventType === 'upload'
          ? 'Dataset upload'
          : eventType === 'error'
            ? 'Error encountered'
            : eventType === 'submit'
              ? 'Job submitted'
              : eventType === 'complete'
                ? 'Workflow completed'
                : 'Analysis event'

      return {
        id: event.id || `${eventType}-${event.timestamp ?? Date.now()}`,
        type: mappedType,
        title: event.action,
        description,
        timestamp: timestampLabel,
        user: event.user,
        status,
      }
    })
  }, [dashboardData])

  const gpuTrendData = useMemo(() => {
    const samples = dashboardData?.resourceMetrics?.gpuSamples ?? []
    if (!samples.length) return []

    return samples.slice(-24).map((sample) => {
      const values = [sample.gpu1, sample.gpu2, sample.gpu3, sample.gpu4].filter((v) =>
        Number.isFinite(v)
      )
      const avg = values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : 0
      const timestamp = new Date(sample.timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      })
      return { timestamp, avgGpu: avg }
    })
  }, [dashboardData?.resourceMetrics?.gpuSamples])

  const quickActions = useMemo(
    () => [
      { label: 'New Analysis', icon: <Brain className="h-4 w-4" />, href: routes.pipelineBuilder },
      { label: 'Upload Dataset', icon: <FolderOpen className="h-4 w-4" />, href: routes.datasets },
      { label: 'Browse Results', icon: <FileText className="h-4 w-4" />, href: routes.finder },
      { label: 'View Pipelines', icon: <Layers className="h-4 w-4" />, href: routes.pipeline },
    ],
    []
  )

  const isLoading = !isMounted || dashboardLoading
  const combinedError = dashboardError || healthError
  const apiHealthy = !dashboardError && !healthError && health?.status === 'ok'
  const clusterSnapshot = (dashboardData?.resourceMetrics?.cluster || {}) as Record<string, any>
  const clusterCpuUsage =
    typeof clusterSnapshot.cpuUsage === 'number'
      ? clusterSnapshot.cpuUsage
      : typeof clusterSnapshot.cpu_usage === 'number'
        ? clusterSnapshot.cpu_usage
        : null
  const clusterUsage =
    clusterCpuUsage == null || Number.isNaN(clusterCpuUsage) ? null : clusterCpuUsage
  const clusterStatusColor =
    clusterUsage !== null && clusterUsage > 85
      ? 'bg-red-500'
      : clusterUsage !== null && clusterUsage > 60
        ? 'bg-yellow-500'
        : 'bg-green-500'
  const clusterStatusLabel =
    clusterUsage !== null ? `${clusterUsage.toFixed(0)}% cpu` : 'No data'
  const dashboardRealtime = dashboardConnected
  const mcpAdoption = dashboardData?.mcpAdoption ?? null
  const kgServiceStatus = health?.services?.find((svc) => svc.name === 'kg' || svc.name === 'neurokg')?.status
  const kgTone =
    kgServiceStatus === 'ok'
      ? 'bg-green-500'
      : kgServiceStatus === 'degraded'
        ? 'bg-yellow-500'
        : kgServiceStatus === 'down'
          ? 'bg-red-500'
          : 'bg-gray-300'
  const kgLabel = kgServiceStatus ? kgServiceStatus : 'Unknown'
  const filteredMcpUsers = useMemo(() => {
    if (!mcpAdoption?.users?.length) {
      return []
    }
    return mcpAdoption.users.filter((user) => {
      if (mcpUserFilter === 'used') {
        return user.usedMcp
      }
      if (mcpUserFilter === 'unused') {
        return !user.usedMcp
      }
      return true
    })
  }, [mcpAdoption?.users, mcpUserFilter])

  const formatRelativeTimestamp = (value?: string | null) => {
    if (!value) return 'Never'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return 'Never'
    return formatDistanceToNow(parsed, { addSuffix: true })
  }

  const formatAbsoluteTimestamp = (value?: string | null) => {
    if (!value) return '—'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return '—'
    return parsed.toLocaleString()
  }

  // Don't render loading state on server to avoid hydration mismatch
  if (isLoading) {
    return (
      <div suppressHydrationWarning className="min-h-[600px] flex items-center justify-center">
        <div className="text-center">
          <div className="inline-flex items-center gap-2">
            <div className="h-4 w-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
            <span className="text-gray-600">Loading dashboard...</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Monitor your neuroimaging workspace</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex border border-gray-200 rounded-lg p-0.5">
            <button
              onClick={() => {
                // Show overview view
                router.push('/dashboard')
              }}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                activeView === 'overview'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Overview
            </button>
            <button
              onClick={() => {
                // Show analytics view
                router.push('/dashboard?view=analytics')
              }}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                activeView === 'analytics'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Analytics
            </button>
            <button
              onClick={() => {
                // Show resources view
                router.push('/dashboard?view=resources')
              }}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                activeView === 'resources'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Resources
            </button>
          </div>
        </div>
      </div>

      {combinedError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-200">
          {combinedError}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {stats.length > 0 ? (
          stats.map((stat) => (
            <div key={stat.label} className="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center justify-between mb-2">
                <div className="p-1.5 bg-gray-50 rounded-lg">
                  {stat.icon}
                </div>
                {stat.trend && (
                  <div
                    className={`text-xs font-medium ${
                      stat.trend === 'up'
                        ? 'text-green-600'
                        : stat.trend === 'down'
                          ? 'text-red-600'
                          : 'text-gray-500'
                    }`}
                  >
                    {stat.trend === 'up' && '↑'}
                    {stat.trend === 'down' && '↓'}
                  </div>
                )}
              </div>
              <div className="text-2xl font-semibold text-gray-900">{stat.value}</div>
              <div className="text-xs text-gray-500 mt-1">{stat.label}</div>
              {stat.change && (
                <div className="text-xs text-gray-400 mt-2">{stat.change}</div>
              )}
            </div>
          ))
        ) : (
          <div className="col-span-full bg-white border border-gray-200 rounded-xl p-6 text-center text-sm text-gray-500">
            No metrics available yet. Check back after your first analysis run.
          </div>
        )}
      </div>

      {/* Main Content Area */}
      {activeView === 'overview' && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Activity */}
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl">
            <div className="p-4 border-b border-gray-100">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">Recent Activity</h2>
                <Link href={routes.pipeline} className="text-sm text-blue-600 hover:text-blue-700 font-medium">
                  View all →
                </Link>
              </div>
            </div>
          <div className="divide-y divide-gray-100">
            {recentActivity.length > 0 ? recentActivity.map(item => (
              <div key={item.id} className="p-4 hover:bg-gray-50 transition-colors">
                <div className="flex items-start gap-3">
                  <div className={`p-2 rounded-lg ${
                    item.type === 'analysis' ? 'bg-blue-50' :
                    item.type === 'dataset' ? 'bg-green-50' :
                    item.type === 'pipeline' ? 'bg-purple-50' :
                    'bg-orange-50'
                  }`}>
                    {item.type === 'analysis' && <Brain className="h-4 w-4 text-blue-600" />}
                    {item.type === 'dataset' && <Database className="h-4 w-4 text-green-600" />}
                    {item.type === 'pipeline' && <GitBranch className="h-4 w-4 text-purple-600" />}
                    {item.type === 'collaboration' && <Users className="h-4 w-4 text-orange-600" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-medium text-gray-900">{item.title}</p>
                        <p className="text-sm text-gray-500 mt-0.5">{item.description}</p>
                        <div className="flex items-center gap-3 mt-2">
                          <span className="text-xs text-gray-400">{item.timestamp}</span>
                          {item.user && (
                            <>
                              <span className="text-xs text-gray-300">•</span>
                              <span className="text-xs text-gray-500">{item.user}</span>
                            </>
                          )}
                          {item.status && (
                            <>
                              <span className="text-xs text-gray-300">•</span>
                              <span className={`text-xs font-medium ${
                                item.status === 'completed' ? 'text-green-600' :
                                item.status === 'running' ? 'text-blue-600' :
                                'text-red-600'
                              }`}>
                                {item.status}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <button className="p-1 hover:bg-gray-100 rounded-lg transition-colors">
                        <ArrowUpRight className="h-3 w-3 text-gray-400" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )) : (
              <div className="p-6 text-center text-sm text-gray-500">
                No recent activity yet. Run an analysis or launch a dataset ingestion to see updates.
              </div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="space-y-6">
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h2 className="font-semibold text-gray-900 mb-3">Quick Actions</h2>
            <div className="space-y-2">
              {quickActions.map((action) => (
                <Link
                  key={action.label}
                  href={action.href}
                  className="flex items-center gap-3 p-3 hover:bg-gray-50 rounded-lg transition-colors group"
                >
                  <div className="p-2 bg-gray-100 rounded-lg group-hover:bg-gray-200 transition-colors">
                    {action.icon}
                  </div>
                  <span className="font-medium text-gray-700 group-hover:text-gray-900">
                    {action.label}
                  </span>
                  <ArrowUpRight className="h-3 w-3 text-gray-400 ml-auto opacity-0 group-hover:opacity-100 transition-opacity" />
                </Link>
              ))}
            </div>
          </div>

          {/* System Status */}
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h2 className="font-semibold text-gray-900 mb-3">System Status</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-gray-400" />
                  <span className="text-sm text-gray-600">API Server</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className={`h-2 w-2 rounded-full ${apiHealthy ? 'bg-green-500' : 'bg-yellow-500'}`} />
                  <span className={`text-xs font-medium ${apiHealthy ? 'text-green-600' : 'text-yellow-600'}`}>
                    {apiHealthy ? 'Healthy' : 'Degraded'}
                  </span>
                </div>
              </div>
	              <div className="flex items-center justify-between">
	                <div className="flex items-center gap-2">
	                  <Package className="h-4 w-4 text-gray-400" />
	                  <span className="text-sm text-gray-600">Knowledge Graph</span>
	                </div>
	                <div className="flex items-center gap-1">
	                  <div className={`h-2 w-2 rounded-full ${kgTone}`} />
	                  <span className="text-xs font-medium text-gray-600">{kgLabel}</span>
	                </div>
	              </div>
	              <div className="flex items-center justify-between">
	                <div className="flex items-center gap-2">
	                  <Package className="h-4 w-4 text-gray-400" />
	                  <span className="text-sm text-gray-600">Dashboard Realtime</span>
	                </div>
	                <div className="flex items-center gap-1">
	                  <div className={`h-2 w-2 rounded-full ${dashboardRealtime ? 'bg-green-500' : 'bg-yellow-500'}`} />
	                  <span className={`text-xs font-medium ${dashboardRealtime ? 'text-green-600' : 'text-yellow-600'}`}>
	                    {dashboardRealtime ? 'Streaming' : 'Polling'}
	                  </span>
	                </div>
	              </div>
	              <div className="flex items-center justify-between">
	                <div className="flex items-center gap-2">
	                  <Network className="h-4 w-4 text-gray-400" />
	                  <span className="text-sm text-gray-600">Compute Cluster</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className={`h-2 w-2 rounded-full ${clusterStatusColor}`} />
                  <span className="text-xs text-gray-600 font-medium">{clusterStatusLabel}</span>
                </div>
              </div>
	              {queueSnapshot?.queued != null && (
	                <div className="flex items-center justify-between">
	                  <div className="flex items-center gap-2">
	                    <Layers className="h-4 w-4 text-gray-400" />
	                    <span className="text-sm text-gray-600">Queue Depth</span>
	                  </div>
	                  <span className="text-xs text-gray-600 font-medium">
	                    {queueSnapshot.queued.toLocaleString()} jobs
	                  </span>
	                </div>
	              )}
            </div>
          </div>
        </div>
      </div>

      )}

      {activeView === 'overview' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="xl:col-span-2">
            {gpuTrendData.length > 0 ? (
              <LineChart
                height={320}
                title="GPU Utilization (avg)"
                description="Recent GPU utilization samples (nvidia-smi)"
                data={gpuTrendData}
                lines={[
                  { dataKey: 'avgGpu', name: 'Avg GPU %', color: 'rgb(147, 51, 234)' },
                ]}
                xAxisKey="timestamp"
                yAxisLabel="%"
                showBrush={false}
                domain={[0, 100]}
                exportFileName="dashboard-gpu-utilization"
              />
            ) : (
              <div className="flex h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-white px-6 text-sm text-gray-500">
                GPU telemetry is not available yet.
              </div>
            )}
          </div>
          <div>
            {trending.length > 0 ? (
              <div className="h-[320px] rounded-xl border border-gray-200 bg-white p-6">
                <h3 className="text-lg font-semibold mb-1">Trending searches</h3>
                <p className="text-sm text-muted-foreground mb-4">From /api/search/track (last 24h window)</p>
                <div className="space-y-3">
                  {trending.map((item) => (
                    <div key={item.query} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-gray-900">{item.query}</div>
                        <div className="text-xs text-muted-foreground">
                          {item.category ? item.category : 'general'}
                        </div>
                      </div>
                      <div className="text-sm font-semibold text-gray-700">
                        {typeof item.count === 'number' ? item.count.toLocaleString() : '–'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-white px-6 text-sm text-gray-500">
                Trending searches will appear after searches are tracked.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Analytics View */}
      {activeView === 'analytics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="text-sm text-gray-500">Success Rate</div>
              <div className="text-2xl font-bold text-gray-900">
                {successRate == null ? '–' : `${successRate.toFixed(1)}%`}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                From completed vs failed jobs
              </div>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="text-sm text-gray-500">Jobs/min</div>
              <div className="text-2xl font-bold text-gray-900">
                {throughputPerMinute == null ? '–' : throughputPerMinute.toFixed(1)}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Rolling 5-minute window
              </div>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="text-sm text-gray-500">Active Workers</div>
              <div className="text-2xl font-bold text-gray-900">
                {activeWorkers == null ? '–' : activeWorkers.toLocaleString()}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Job store reported
              </div>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="text-sm text-gray-500">Oldest Queued</div>
              <div className="text-2xl font-bold text-gray-900">
                {oldestQueuedSeconds == null ? '–' : `${Math.floor(oldestQueuedSeconds)}s`}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Queue age signal
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white border border-gray-200 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-1">Services</h3>
              <p className="text-sm text-muted-foreground mb-4">From /api/health/full</p>
              {health?.services?.length ? (
                <div className="space-y-3">
                  {health.services.map((svc) => (
                    <div key={svc.name} className="flex items-center justify-between rounded-lg border px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-gray-900">{svc.name}</div>
                        {svc.detail ? (
                          <div className="text-xs text-muted-foreground truncate">{svc.detail}</div>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground">
                          {typeof svc.latency_ms === 'number' ? `${svc.latency_ms.toFixed(0)} ms` : '–'}
                        </span>
                        <span className="text-xs font-semibold text-gray-700">{svc.status}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  No data yet.
                </div>
              )}
            </div>

            <div className="bg-white border border-gray-200 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-1">Trending searches</h3>
              <p className="text-sm text-muted-foreground mb-4">From /api/search/trending (24h)</p>
              {trending.length ? (
                <div className="space-y-3">
                  {trending.map((item) => (
                    <div key={item.query} className="flex items-center justify-between rounded-lg border px-3 py-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-gray-900">{item.query}</div>
                        <div className="text-xs text-muted-foreground">
                          {item.category ? item.category : 'general'}
                        </div>
                      </div>
                      <div className="text-sm font-semibold text-gray-700">
                        {typeof item.count === 'number' ? item.count.toLocaleString() : '–'}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  No data yet. Searches start populating after UI events call /api/search/track.
                </div>
              )}
            </div>
          </div>

          {mcpAdoption && (
            <>
              <div className="rounded-xl border border-gray-200 bg-white p-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">MCP Adoption</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Admin-only adoption view derived from Redis-backed signup and MCP token records.
                      Exact all-time MCP request counts are not persisted yet.
                    </p>
                  </div>
                  <Badge variant="outline" className="border-blue-200 bg-blue-50 text-blue-700">
                    Updated {formatRelativeTimestamp(mcpAdoption.generatedAt)}
                  </Badge>
                </div>

                <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="text-sm text-gray-500">Signed-up users</div>
                    <div className="mt-2 text-2xl font-semibold text-gray-900">
                      {mcpAdoption.summary.totalUsers.toLocaleString()}
                    </div>
                  </div>
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                    <div className="text-sm text-emerald-700">Used MCP</div>
                    <div className="mt-2 text-2xl font-semibold text-emerald-900">
                      {mcpAdoption.summary.usedUsers.toLocaleString()}
                    </div>
                    <div className="mt-1 text-xs text-emerald-700">
                      {mcpAdoption.summary.adoptionRatePct.toFixed(1)}% adoption
                    </div>
                  </div>
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <div className="text-sm text-amber-700">Have not used MCP</div>
                    <div className="mt-2 text-2xl font-semibold text-amber-900">
                      {mcpAdoption.summary.unusedUsers.toLocaleString()}
                    </div>
                  </div>
                  <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4">
                    <div className="text-sm text-indigo-700">Token never used</div>
                    <div className="mt-2 text-2xl font-semibold text-indigo-900">
                      {mcpAdoption.summary.tokenNeverUsedUsers.toLocaleString()}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="text-sm text-slate-700">No token</div>
                    <div className="mt-2 text-2xl font-semibold text-slate-900">
                      {mcpAdoption.summary.noTokenUsers.toLocaleString()}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-white p-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">User Breakdown</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Filter users by adoption state. `last_used_at` is the stable historical usage signal;
                      exact cumulative request counts need a new durable counter in the MCP auth path.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {([
                      ['all', 'All'],
                      ['used', 'Used'],
                      ['unused', 'Unused'],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        onClick={() => setMcpUserFilter(value)}
                        className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                          mcpUserFilter === value
                            ? 'bg-gray-900 text-white'
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="mt-6 overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                        <th className="px-3 py-3 font-medium">User</th>
                        <th className="px-3 py-3 font-medium">Status</th>
                        <th className="px-3 py-3 font-medium">Tokens</th>
                        <th className="px-3 py-3 font-medium">Last used</th>
                        <th className="px-3 py-3 font-medium">Joined</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {filteredMcpUsers.length > 0 ? (
                        filteredMcpUsers.map((user) => {
                          const statusTone =
                            user.mcpStatus === 'used'
                              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                              : user.mcpStatus === 'token_never_used'
                                ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                                : 'border-slate-200 bg-slate-50 text-slate-700'
                          const statusLabel =
                            user.mcpStatus === 'used'
                              ? 'Used'
                              : user.mcpStatus === 'token_never_used'
                                ? 'Token never used'
                                : 'No token'
                          return (
                            <tr key={user.userId} className="align-top">
                              <td className="px-3 py-4">
                                <div className="font-medium text-gray-900">{user.username}</div>
                                <div className="text-gray-500">{user.email}</div>
                                {user.fullName ? (
                                  <div className="mt-1 text-xs text-gray-400">{user.fullName}</div>
                                ) : null}
                              </td>
                              <td className="px-3 py-4">
                                <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone}`}>
                                  {statusLabel}
                                </span>
                                <div className="mt-2 text-xs text-gray-500">
                                  {user.hasActiveToken ? 'Active token present' : 'No active token'}
                                </div>
                              </td>
                              <td className="px-3 py-4">
                                <div className="font-medium text-gray-900">{user.tokenCount}</div>
                                <div className="text-xs text-gray-500">
                                  {user.hasAnyToken ? 'issued' : 'none'}
                                </div>
                              </td>
                              <td className="px-3 py-4">
                                <div className="font-medium text-gray-900">
                                  {formatRelativeTimestamp(user.lastUsedAt)}
                                </div>
                                <div className="text-xs text-gray-500">
                                  {formatAbsoluteTimestamp(user.lastUsedAt)}
                                </div>
                              </td>
                              <td className="px-3 py-4">
                                <div className="font-medium text-gray-900">
                                  {formatRelativeTimestamp(user.createdAt)}
                                </div>
                                <div className="text-xs text-gray-500">
                                  {formatAbsoluteTimestamp(user.createdAt)}
                                </div>
                              </td>
                            </tr>
                          )
                        })
                      ) : (
                        <tr>
                          <td colSpan={5} className="px-3 py-8 text-center text-sm text-gray-500">
                            No users match this filter.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Resources View */}
      {activeView === 'resources' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Resource Usage Widget */}
            <ResourceUsageWidget
              widget={{
                id: '1',
                type: 'resource_usage' as any,
                title: 'Resource Usage',
                config: {},
                position: { x: 0, y: 0, w: 6, h: 8 },
                visible: true,
                created_at: new Date(),
                updated_at: new Date()
              }}
              data={resourceUsageData}
              loading={!resourceUsageData && dashboardLoading}
            />

            <div className="bg-white border border-gray-200 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-1">Queue Snapshot</h3>
              <p className="text-sm text-muted-foreground mb-4">From /api/dashboard/metrics</p>
              {queueSnapshot ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-600">Running</span>
                    <span className="text-sm font-semibold text-gray-900">{queueSnapshot.running.toLocaleString()}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-600">Queued</span>
                    <span className="text-sm font-semibold text-gray-900">{queueSnapshot.queued.toLocaleString()}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-600">Completed</span>
                    <span className="text-sm font-semibold text-gray-900">{queueSnapshot.completed.toLocaleString()}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-600">Failed</span>
                    <span className="text-sm font-semibold text-gray-900">{queueSnapshot.failed.toLocaleString()}</span>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No data yet.</div>
              )}
            </div>
          </div>

          {/* Storage Details */}
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h3 className="text-lg font-semibold mb-4">Storage Breakdown</h3>
            <div className="space-y-4">
              {dashboardData ? (
                (['primary', 'archive', 'scratch'] as const).map((tier) => {
                  const snapshot = dashboardData.storageMetrics[tier]
                  const used = snapshot?.used ?? 0
                  const total = snapshot?.total ?? 0
                  const pct = total > 0 ? (used / total) * 100 : 0
                  const color =
                    tier === 'primary' ? 'bg-blue-500' : tier === 'archive' ? 'bg-purple-500' : 'bg-green-500'
                  return (
                    <div key={tier}>
                      <div className="flex justify-between mb-1">
                        <span className="text-sm text-gray-600">{tier}</span>
                        <span className="text-sm font-medium">
                          {used.toLocaleString()} GB / {total.toLocaleString()} GB
                        </span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div className={`${color} h-2 rounded-full`} style={{ width: `${pct}%` }}></div>
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="text-sm text-muted-foreground">No data yet.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Performance Metrics - shown in overview only */}
      {activeView === 'overview' && (
        <>
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">Performance Metrics</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <TrendingUp className="h-4 w-4 text-blue-600" />
                  <span className="text-sm text-gray-600">Throughput</span>
                </div>
                <div className="text-xl font-semibold text-gray-900">
                  {throughputPerMinute == null ? '–' : `${(throughputPerMinute * 60).toFixed(0)} jobs/hr`}
                </div>
                <div className="text-xs text-muted-foreground mt-1">From recent completions</div>
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Activity className="h-4 w-4 text-purple-600" />
                  <span className="text-sm text-gray-600">Queue Age</span>
                </div>
                <div className="text-xl font-semibold text-gray-900">
                  {oldestQueuedSeconds == null ? '–' : `${Math.floor(oldestQueuedSeconds)}s`}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Oldest queued job</div>
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Zap className="h-4 w-4 text-orange-600" />
                  <span className="text-sm text-gray-600">Success Rate</span>
                </div>
                <div className="text-xl font-semibold text-gray-900">
                  {successRate == null ? '–' : `${successRate.toFixed(1)}%`}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Completed vs failed</div>
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <HardDrive className="h-4 w-4 text-green-600" />
                  <span className="text-sm text-gray-600">Storage Used</span>
                </div>
                <div className="text-xl font-semibold text-gray-900">
                  {dashboardData?.storageMetrics?.primary?.used == null
                    ? '–'
                    : `${dashboardData.storageMetrics.primary.used.toLocaleString()} GB`}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Primary tier</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
