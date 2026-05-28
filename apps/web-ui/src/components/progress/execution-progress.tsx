'use client'

import React, { useState, useEffect } from 'react'
import { 
  Activity, Clock, Cpu, CheckCircle, 
  XCircle, AlertTriangle, Loader2, 
  ChevronDown, ChevronUp, Info
} from 'lucide-react'

interface ExecutionStep {
  id: string
  name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  progress: number
  startTime?: Date
  endTime?: Date
  logs?: string[]
  metrics?: {
    cpuUsage?: number
    memoryUsage?: number
    diskIO?: number
  }
  subSteps?: ExecutionStep[]
}

interface ExecutionProgressProps {
  jobId: string
  steps: ExecutionStep[]
  currentStep?: string
  overallProgress: number
  estimatedTime?: number
  showDetails?: boolean
  onStepClick?: (stepId: string) => void
}

export function ExecutionProgress({
  jobId,
  steps,
  currentStep,
  overallProgress,
  estimatedTime,
  showDetails = true,
  onStepClick
}: ExecutionProgressProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  const [elapsedTime, setElapsedTime] = useState(0)

  // Update elapsed time
  useEffect(() => {
    const interval = setInterval(() => {
      const runningStep = steps.find(s => s.status === 'running')
      if (runningStep && runningStep.startTime) {
        const elapsed = Date.now() - runningStep.startTime.getTime()
        setElapsedTime(Math.floor(elapsed / 1000))
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [steps])

  const toggleStepExpansion = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }

  const handleStepClick = (stepId: string) => {
    setSelectedStep(stepId)
    onStepClick?.(stepId)
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
      case 'failed':
        return 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
      case 'running':
        return 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
      case 'skipped':
        return 'text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-900/20'
      default:
        return 'text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5" />
      case 'failed':
        return <XCircle className="h-5 w-5" />
      case 'running':
        return <Loader2 className="h-5 w-5 animate-spin" />
      case 'skipped':
        return <AlertTriangle className="h-5 w-5" />
      default:
        return <Clock className="h-5 w-5" />
    }
  }

  const formatDuration = (start?: Date, end?: Date) => {
    if (!start) return '-'
    const endTime = end || new Date()
    const duration = Math.floor((endTime.getTime() - start.getTime()) / 1000)
    const minutes = Math.floor(duration / 60)
    const seconds = duration % 60
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const renderStep = (step: ExecutionStep, depth = 0) => {
    const isExpanded = expandedSteps.has(step.id)
    const isSelected = selectedStep === step.id
    const hasSubSteps = step.subSteps && step.subSteps.length > 0

    return (
      <div key={step.id} className={depth > 0 ? 'ml-8' : ''}>
        <div
          className={`border rounded-lg p-4 mb-2 cursor-pointer transition-all ${
            isSelected 
              ? 'border-blue-500 shadow-md' 
              : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
          } ${getStatusColor(step.status)}`}
          onClick={() => handleStepClick(step.id)}
        >
          <div className="flex items-start gap-3">
            <div className="mt-0.5">
              {getStatusIcon(step.status)}
            </div>
            
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-gray-900 dark:text-white">
                  {step.name}
                </h4>
                <div className="flex items-center gap-2">
                  {step.status === 'running' && (
                    <span className="text-sm text-blue-600 dark:text-blue-400">
                      {step.progress}%
                    </span>
                  )}
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    {formatDuration(step.startTime, step.endTime)}
                  </span>
                  {hasSubSteps && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleStepExpansion(step.id)
                      }}
                      className="p-1 hover:bg-gray-200 dark:hover:bg-gray-700 rounded"
                    >
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </button>
                  )}
                </div>
              </div>
              
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                {step.description}
              </p>
              
              {step.status === 'running' && (
                <div className="mt-3">
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${step.progress}%` }}
                    />
                  </div>
                </div>
              )}
              
              {showDetails && step.metrics && (
                <div className="mt-3 flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                  {step.metrics.cpuUsage !== undefined && (
                    <span>CPU: {step.metrics.cpuUsage}%</span>
                  )}
                  {step.metrics.memoryUsage !== undefined && (
                    <span>Memory: {step.metrics.memoryUsage}%</span>
                  )}
                  {step.metrics.diskIO !== undefined && (
                    <span>Disk I/O: {step.metrics.diskIO} MB/s</span>
                  )}
                </div>
              )}
              
              {step.logs && step.logs.length > 0 && isSelected && (
                <div className="mt-3 p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono max-h-32 overflow-y-auto">
                  {step.logs.map((log, i) => (
                    <div key={i}>{log}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
        
        {isExpanded && hasSubSteps && (
          <div className="mt-2">
            {step.subSteps!.map(subStep => renderStep(subStep, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Activity className="h-6 w-6 text-blue-500" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Execution Progress
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Job ID: {jobId}
            </p>
          </div>
        </div>
        
        <div className="text-right">
          <div className="text-2xl font-bold text-gray-900 dark:text-white">
            {overallProgress}%
          </div>
          {estimatedTime && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              ETA: {Math.ceil(estimatedTime / 60)} min
            </p>
          )}
        </div>
      </div>

      {/* Overall Progress Bar */}
      <div className="mb-6">
        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3">
          <div
            className="bg-gradient-to-r from-blue-500 to-purple-500 h-3 rounded-full transition-all duration-500"
            style={{ width: `${overallProgress}%` }}
          />
        </div>
        <div className="flex items-center justify-between mt-2 text-sm text-gray-500 dark:text-gray-400">
          <span>{steps.filter(s => s.status === 'completed').length} / {steps.length} steps completed</span>
          <span>Elapsed: {Math.floor(elapsedTime / 60)}:{(elapsedTime % 60).toString().padStart(2, '0')}</span>
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-2">
        {steps.map(step => renderStep(step))}
      </div>

      {/* Info Box */}
      {currentStep && (
        <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                Currently executing: {steps.find(s => s.id === currentStep)?.name}
              </p>
              <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                {steps.find(s => s.id === currentStep)?.description}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}