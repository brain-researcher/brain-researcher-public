'use client'

import React, { useState, useEffect, createContext, useContext, useCallback } from 'react'
import { 
  FlaskConical, TrendingUp, Users, BarChart3, 
  Play, Pause, RefreshCw, Settings, Check, X,
  AlertCircle, Target, Zap, Eye
} from 'lucide-react'

// Experiment types
interface Experiment {
  id: string
  name: string
  description: string
  status: 'draft' | 'running' | 'paused' | 'completed'
  variants: Variant[]
  metrics: Metric[]
  traffic: number // percentage of traffic
  startDate?: Date
  endDate?: Date
  winner?: string
  config: ExperimentConfig
}

interface Variant {
  id: string
  name: string
  description?: string
  weight: number // traffic weight
  changes: Record<string, any>
  metrics?: VariantMetrics
}

interface Metric {
  id: string
  name: string
  type: 'conversion' | 'engagement' | 'revenue' | 'custom'
  goal: 'maximize' | 'minimize'
  unit?: string
}

interface VariantMetrics {
  impressions: number
  conversions: number
  conversionRate: number
  confidence?: number
  uplift?: number
}

interface ExperimentConfig {
  minSampleSize: number
  confidenceLevel: number
  testType: 'ab' | 'multivariate' | 'sequential'
  allocation: 'random' | 'weighted' | 'deterministic'
}

// A/B Testing Context
interface ABTestingContextValue {
  experiments: Experiment[]
  activeExperiment?: Experiment
  userVariant?: Variant
  trackEvent: (eventName: string, properties?: Record<string, any>) => void
  getVariant: (experimentId: string) => Variant | null
  isFeatureEnabled: (featureName: string) => boolean
}

const ABTestingContext = createContext<ABTestingContextValue | null>(null)

export function useABTesting() {
  const context = useContext(ABTestingContext)
  if (!context) {
    throw new Error('useABTesting must be used within ABTestingProvider')
  }
  return context
}

// A/B Testing Provider
export function ABTestingProvider({ 
  children,
  userId,
  apiUrl = '/api/experiments'
}: { 
  children: React.ReactNode
  userId?: string
  apiUrl?: string
}) {
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [userVariants, setUserVariants] = useState<Map<string, Variant>>(new Map())

  useEffect(() => {
    // Fetch experiments and user assignments
    fetchExperiments()
  }, [userId])

  const fetchExperiments = async () => {
    try {
      const response = await fetch(`${apiUrl}/active`)
      const data = await response.json()
      setExperiments(data)
      
      // Get user variant assignments
      if (userId) {
        const assignmentsResponse = await fetch(`${apiUrl}/assignments/${userId}`)
        const assignments = await assignmentsResponse.json()
        const variantsMap = new Map<string, Variant>()
        assignments.forEach((a: any) => {
          variantsMap.set(a.experimentId, a.variant)
        })
        setUserVariants(variantsMap)
      }
    } catch (error) {
      console.error('Failed to fetch experiments:', error)
    }
  }

  const trackEvent = useCallback((eventName: string, properties?: Record<string, any>) => {
    // Send event to analytics
    const event = {
      name: eventName,
      properties,
      userId,
      timestamp: new Date().toISOString(),
      variants: Array.from(userVariants.entries()).map(([expId, variant]) => ({
        experimentId: expId,
        variantId: variant.id
      }))
    }
    
    // In production, send to analytics service
    console.log('Track event:', event)
  }, [userId, userVariants])

  const getVariant = useCallback((experimentId: string) => {
    return userVariants.get(experimentId) || null
  }, [userVariants])

  const isFeatureEnabled = useCallback((featureName: string) => {
    // Check if feature is enabled for user's variant
    for (const [_, variant] of Array.from(userVariants.entries())) {
      if (variant.changes[featureName] === true) {
        return true
      }
    }
    return false
  }, [userVariants])

  const value: ABTestingContextValue = {
    experiments,
    activeExperiment: experiments.find(e => e.status === 'running'),
    userVariant: userVariants.values().next().value,
    trackEvent,
    getVariant,
    isFeatureEnabled
  }

  return (
    <ABTestingContext.Provider value={value}>
      {children}
    </ABTestingContext.Provider>
  )
}

// Experiment Dashboard Component
export function ExperimentDashboard() {
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedExperiment, setSelectedExperiment] = useState<Experiment | null>(null)

  useEffect(() => {
    let cancelled = false
    const loadExperiments = async () => {
      setLoading(true)
      setError(null)
      const endpoints = ['/api/experiments', '/api/experiments/active']
      try {
        let payload: any = null
        for (const endpoint of endpoints) {
          const response = await fetch(endpoint, { cache: 'no-store' })
          if (!response.ok) continue
          payload = await response.json()
          break
        }

        const list = Array.isArray(payload)
          ? payload
          : Array.isArray(payload?.experiments)
            ? payload.experiments
            : Array.isArray(payload?.items)
              ? payload.items
              : payload
                ? [payload]
                : []

        if (!cancelled) {
          setExperiments(list)
          setSelectedExperiment(list[0] ?? null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load experiments')
          setExperiments([])
          setSelectedExperiment(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadExperiments()
    return () => {
      cancelled = true
    }
  }, [])

  const getStatusColor = (status: Experiment['status']) => {
    switch (status) {
      case 'running': return 'text-green-600 bg-green-100'
      case 'paused': return 'text-yellow-600 bg-yellow-100'
      case 'completed': return 'text-blue-600 bg-blue-100'
      case 'draft': return 'text-gray-600 bg-gray-100'
    }
  }

  const getStatusIcon = (status: Experiment['status']) => {
    switch (status) {
      case 'running': return <Play className="h-4 w-4" />
      case 'paused': return <Pause className="h-4 w-4" />
      case 'completed': return <Check className="h-4 w-4" />
      case 'draft': return <Settings className="h-4 w-4" />
    }
  }


  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            A/B Testing Dashboard
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Manage and monitor your experiments
          </p>
        </div>
        <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2">
          <FlaskConical className="h-5 w-5" />
          New Experiment
        </button>
      </div>

      {/* Experiments Grid */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {loading && (
          <div className="col-span-full text-center py-12 text-gray-500">
            <BarChart3 className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg font-medium">Loading experiments…</p>
          </div>
        )}
        {!loading && experiments.length === 0 && (
          <div className="col-span-full text-center py-12 text-gray-500">
            <BarChart3 className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg font-medium">No experiments found</p>
            <p className="text-sm">{error ?? 'Connect the experiments service to see data here.'}</p>
          </div>
        )}
        {!loading && experiments.map((experiment) => (
          <div
            key={experiment.id}
            className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 cursor-pointer hover:shadow-xl transition-shadow"
            onClick={() => setSelectedExperiment(experiment)}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {experiment.name}
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {experiment.description}
                </p>
              </div>
              <span className={`px-2 py-1 rounded-full text-xs font-medium flex items-center gap-1 ${getStatusColor(experiment.status)}`}>
                {getStatusIcon(experiment.status)}
                {experiment.status}
              </span>
            </div>

            {/* Metrics */}
            <div className="space-y-3">
              {experiment.variants.map((variant) => (
                <div key={variant.id} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-700 dark:text-gray-300">{variant.name}</span>
                    <span className="font-medium">
                      {variant.metrics?.conversionRate != null
                        ? `${variant.metrics.conversionRate.toFixed(1)}%`
                        : '—'}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full"
                      style={{ width: `${variant.metrics?.conversionRate || 0}%` }}
                    />
                  </div>
                  {variant.metrics?.uplift !== undefined && variant.metrics.uplift !== 0 && (
                    <div className="flex items-center gap-1 text-xs">
                      <TrendingUp className={`h-3 w-3 ${variant.metrics.uplift > 0 ? 'text-green-500' : 'text-red-500'}`} />
                      <span className={variant.metrics.uplift > 0 ? 'text-green-600' : 'text-red-600'}>
                        {variant.metrics.uplift > 0 ? '+' : ''}{variant.metrics.uplift}% uplift
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between text-sm">
              <div className="flex items-center gap-1 text-gray-500">
                <Users className="h-4 w-4" />
                <span>{experiment.traffic}% traffic</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    // Toggle experiment status
                  }}
                  className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                >
                  {experiment.status === 'running' ? 
                    <Pause className="h-4 w-4" /> : 
                    <Play className="h-4 w-4" />
                  }
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    // Refresh data
                  }}
                  className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Experiment Detail Modal */}
      {selectedExperiment && (
        <ExperimentDetail
          experiment={selectedExperiment}
          onClose={() => setSelectedExperiment(null)}
        />
      )}
    </div>
  )
}

// Experiment Detail Component
function ExperimentDetail({ 
  experiment, 
  onClose 
}: { 
  experiment: Experiment
  onClose: () => void
}) {
  const controlVariant =
    experiment.variants.find((variant) => variant.id === 'control') ||
    experiment.variants.find((variant) => variant.name.toLowerCase().includes('control')) ||
    experiment.variants[0]
  const bestVariant = experiment.variants.reduce((best, candidate) => {
    const bestRate = best.metrics?.conversionRate ?? -Infinity
    const candidateRate = candidate.metrics?.conversionRate ?? -Infinity
    return candidateRate > bestRate ? candidate : best
  }, experiment.variants[0])
  const totalImpressions = experiment.variants.reduce((sum, variant) => sum + (variant.metrics?.impressions || 0), 0)
  const uplift =
    controlVariant?.metrics?.conversionRate != null && bestVariant?.metrics?.conversionRate != null
      ? ((bestVariant.metrics.conversionRate - controlVariant.metrics.conversionRate) / controlVariant.metrics.conversionRate) * 100
      : null
  const confidence = bestVariant?.metrics?.confidence ?? experiment.config.confidenceLevel

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-auto">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">
              {experiment.name}
            </h2>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Variants Performance */}
          <div>
            <h3 className="text-lg font-semibold mb-4">Variants Performance</h3>
            <div className="space-y-4">
              {experiment.variants.map((variant) => (
                <div key={variant.id} className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-medium">{variant.name}</span>
                    {variant.metrics?.confidence && (
                      <span className="text-sm text-gray-500">
                        {variant.metrics.confidence}% confidence
                      </span>
                    )}
                  </div>
                  
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <p className="text-sm text-gray-500">Impressions</p>
                      <p className="text-xl font-bold">
                        {variant.metrics?.impressions != null ? variant.metrics.impressions.toLocaleString() : '—'}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">Conversions</p>
                      <p className="text-xl font-bold">
                        {variant.metrics?.conversions != null ? variant.metrics.conversions.toLocaleString() : '—'}
                      </p>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500">Conversion Rate</p>
                      <p className="text-xl font-bold">
                        {variant.metrics?.conversionRate != null ? `${variant.metrics.conversionRate.toFixed(2)}%` : '—'}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Statistical Significance */}
          <div>
            <h3 className="text-lg font-semibold mb-4">Statistical Analysis</h3>
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5" />
                <div>
                  <p className="text-sm text-blue-900 dark:text-blue-100">
                    {uplift != null && bestVariant && controlVariant
                      ? `Current estimate: ${bestVariant.name} shows ${uplift.toFixed(1)}% uplift versus ${controlVariant.name}.`
                      : 'Statistical uplift is not available yet.'}
                  </p>
                  <p className="text-xs text-blue-700 dark:text-blue-300 mt-2">
                    Minimum sample size: {experiment.config.minSampleSize.toLocaleString()} | 
                    Current sample: {totalImpressions ? totalImpressions.toLocaleString() : '—'}
                  </p>
                  <p className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                    Confidence level: {confidence ? `${confidence}%` : '—'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// Feature Flag Component
export function FeatureFlag({ 
  name, 
  children, 
  fallback = null 
}: { 
  name: string
  children: React.ReactNode
  fallback?: React.ReactNode
}) {
  const { isFeatureEnabled } = useABTesting()
  
  return isFeatureEnabled(name) ? <>{children}</> : <>{fallback}</>
}

// Experiment Preview Component
export function ExperimentPreview({ experimentId }: { experimentId: string }) {
  const { getVariant } = useABTesting()
  const variant = getVariant(experimentId)
  
  if (!variant) return null
  
  return (
    <div className="fixed bottom-4 right-4 bg-white dark:bg-gray-800 rounded-lg shadow-lg p-4 max-w-sm">
      <div className="flex items-center gap-2 mb-2">
        <FlaskConical className="h-5 w-5 text-blue-500" />
        <span className="font-medium text-sm">Experiment Active</span>
      </div>
      <p className="text-xs text-gray-600 dark:text-gray-400">
        You're seeing: <span className="font-medium">{variant.name}</span>
      </p>
    </div>
  )
}

// Export all components
const abTestingExports = {
  ABTestingProvider,
  useABTesting,
  ExperimentDashboard,
  FeatureFlag,
  ExperimentPreview
}

export default abTestingExports
