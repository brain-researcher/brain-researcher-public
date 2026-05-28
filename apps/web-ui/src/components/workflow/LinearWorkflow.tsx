'use client'

import { useState, useEffect } from 'react'
import {
  Play,
  Pause,
  StopCircle,
  CheckCircle,
  XCircle,
  Clock,
  Plus,
  ChevronRight,
  Settings,
  FileText,
  GitBranch,
  Zap,
  Target,
  Activity,
  Brain,
  Database,
  BarChart3,
  Upload,
  Download,
  RefreshCw,
  AlertCircle,
  Info,
  Code,
  Terminal,
  ChevronDown
} from 'lucide-react'
import Link from 'next/link'

interface Pipeline {
  id: string
  name: string
  description: string
  status: 'idle' | 'running' | 'completed' | 'failed' | 'queued'
  progress: number
  runtime: string
  steps: number
  currentStep: number
  created: string
  owner: string
}

interface PipelineStep {
  id: string
  name: string
  type: 'preprocess' | 'analysis' | 'visualization' | 'export'
  status: 'pending' | 'running' | 'completed' | 'failed'
  duration?: string
  output?: string
}

export function LinearWorkflow() {
  const [loading, setLoading] = useState(true)
  const [selectedPipeline, setSelectedPipeline] = useState<Pipeline | null>(null)
  const [activeView, setActiveView] = useState<'pipelines' | 'builder' | 'templates'>('pipelines')
  
  const [pipelines] = useState<Pipeline[]>([
    {
      id: 'p1',
      name: 'fMRI GLM Analysis',
      description: 'Standard GLM analysis pipeline for task-based fMRI',
      status: 'running',
      progress: 65,
      runtime: '12:34',
      steps: 8,
      currentStep: 5,
      created: '2 hours ago',
      owner: 'You'
    },
    {
      id: 'p2',
      name: 'Resting State Preprocessing',
      description: 'fMRIPrep preprocessing for resting-state data',
      status: 'completed',
      progress: 100,
      runtime: '45:12',
      steps: 12,
      currentStep: 12,
      created: '1 day ago',
      owner: 'You'
    },
    {
      id: 'p3',
      name: 'DTI Tractography',
      description: 'White matter tractography analysis',
      status: 'queued',
      progress: 0,
      runtime: '00:00',
      steps: 6,
      currentStep: 0,
      created: '5 minutes ago',
      owner: 'Sarah Chen'
    },
    {
      id: 'p4',
      name: 'Group ICA Analysis',
      description: 'Independent component analysis for group study',
      status: 'failed',
      progress: 35,
      runtime: '08:21',
      steps: 10,
      currentStep: 4,
      created: '3 days ago',
      owner: 'You'
    }
  ])

  const [pipelineSteps] = useState<PipelineStep[]>([
    { id: 's1', name: 'Data Import', type: 'preprocess', status: 'completed', duration: '2:15' },
    { id: 's2', name: 'Motion Correction', type: 'preprocess', status: 'completed', duration: '5:32' },
    { id: 's3', name: 'Slice Timing', type: 'preprocess', status: 'completed', duration: '1:45' },
    { id: 's4', name: 'Normalization', type: 'preprocess', status: 'completed', duration: '3:12' },
    { id: 's5', name: 'GLM Estimation', type: 'analysis', status: 'running' },
    { id: 's6', name: 'Contrast Maps', type: 'analysis', status: 'pending' },
    { id: 's7', name: 'Statistical Maps', type: 'visualization', status: 'pending' },
    { id: 's8', name: 'Report Generation', type: 'export', status: 'pending' }
  ])

  useEffect(() => {
    setTimeout(() => {
      setLoading(false)
      setSelectedPipeline(pipelines[0])
    }, 1000)
  }, [pipelines])

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'bg-blue-100 text-blue-700 border-blue-200'
      case 'completed': return 'bg-green-100 text-green-700 border-green-200'
      case 'failed': return 'bg-red-100 text-red-700 border-red-200'
      case 'queued': return 'bg-yellow-100 text-yellow-700 border-yellow-200'
      default: return 'bg-gray-100 text-gray-700 border-gray-200'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running': return <RefreshCw className="h-4 w-4 animate-spin" />
      case 'completed': return <CheckCircle className="h-4 w-4" />
      case 'failed': return <XCircle className="h-4 w-4" />
      case 'queued': return <Clock className="h-4 w-4" />
      default: return <Clock className="h-4 w-4" />
    }
  }

  const getStepIcon = (type: string) => {
    switch (type) {
      case 'preprocess': return <Settings className="h-4 w-4" />
      case 'analysis': return <Brain className="h-4 w-4" />
      case 'visualization': return <BarChart3 className="h-4 w-4" />
      case 'export': return <Download className="h-4 w-4" />
      default: return <Activity className="h-4 w-4" />
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-pulse text-gray-500">Loading workflows...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Workflow Manager</h1>
            <p className="text-gray-600 mt-1">Design and run neuroimaging analysis pipelines</p>
          </div>
          <button className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-2">
            <Plus className="h-4 w-4" />
            New Pipeline
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">1</div>
                <div className="text-sm text-gray-600">Running</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Clock className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">1</div>
                <div className="text-sm text-gray-600">Queued</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <CheckCircle className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">1</div>
                <div className="text-sm text-gray-600">Completed</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Zap className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">87%</div>
                <div className="text-sm text-gray-600">Success Rate</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* View Tabs */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveView('pipelines')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              activeView === 'pipelines' 
                ? 'bg-black text-white' 
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Activity className="h-4 w-4 inline mr-1" />
            Active Pipelines
          </button>
          <button
            onClick={() => setActiveView('builder')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              activeView === 'builder' 
                ? 'bg-black text-white' 
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <GitBranch className="h-4 w-4 inline mr-1" />
            Pipeline Builder
          </button>
          <button
            onClick={() => setActiveView('templates')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              activeView === 'templates' 
                ? 'bg-black text-white' 
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <FileText className="h-4 w-4 inline mr-1" />
            Templates
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-3 gap-6">
        {/* Pipeline List */}
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Pipelines</h2>
          {pipelines.map((pipeline) => (
            <div
              key={pipeline.id}
              onClick={() => setSelectedPipeline(pipeline)}
              className={`bg-white rounded-lg border p-4 cursor-pointer transition-all ${
                selectedPipeline?.id === pipeline.id 
                  ? 'border-black shadow-md' 
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex-1">
                  <h3 className="font-medium text-gray-900">{pipeline.name}</h3>
                  <p className="text-sm text-gray-500 mt-0.5">{pipeline.description}</p>
                </div>
                {getStatusIcon(pipeline.status)}
              </div>
              
              <div className="flex items-center justify-between mb-2">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${getStatusColor(pipeline.status)}`}>
                  {pipeline.status}
                </span>
                <span className="text-xs text-gray-500">{pipeline.runtime}</span>
              </div>

              {pipeline.status === 'running' && (
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
                    <span>Step {pipeline.currentStep}/{pipeline.steps}</span>
                    <span>{pipeline.progress}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-1.5">
                    <div 
                      className="bg-blue-600 h-1.5 rounded-full transition-all"
                      style={{ width: `${pipeline.progress}%` }}
                    />
                  </div>
                </div>
              )}

              <div className="text-xs text-gray-500 mt-2">
                Created {pipeline.created} • {pipeline.owner}
              </div>
            </div>
          ))}
        </div>

        {/* Pipeline Details */}
        <div className="col-span-2 bg-white rounded-lg border border-gray-200">
          {selectedPipeline ? (
            <div>
              {/* Pipeline Header */}
              <div className="p-6 border-b border-gray-200">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-xl font-semibold text-gray-900">{selectedPipeline.name}</h2>
                    <p className="text-gray-600 mt-1">{selectedPipeline.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {selectedPipeline.status === 'running' ? (
                      <button className="p-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                        <Pause className="h-4 w-4 text-gray-600" />
                      </button>
                    ) : (
                      <button className="p-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                        <Play className="h-4 w-4 text-gray-600" />
                      </button>
                    )}
                    <button className="p-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                      <StopCircle className="h-4 w-4 text-gray-600" />
                    </button>
                    <button className="p-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                      <Settings className="h-4 w-4 text-gray-600" />
                    </button>
                  </div>
                </div>

                {/* Pipeline Info */}
                <div className="grid grid-cols-4 gap-4 text-sm">
                  <div>
                    <div className="text-gray-500">Status</div>
                    <div className="font-medium flex items-center gap-1 mt-1">
                      {getStatusIcon(selectedPipeline.status)}
                      <span className="capitalize">{selectedPipeline.status}</span>
                    </div>
                  </div>
                  <div>
                    <div className="text-gray-500">Runtime</div>
                    <div className="font-medium mt-1">{selectedPipeline.runtime}</div>
                  </div>
                  <div>
                    <div className="text-gray-500">Progress</div>
                    <div className="font-medium mt-1">{selectedPipeline.progress}%</div>
                  </div>
                  <div>
                    <div className="text-gray-500">Steps</div>
                    <div className="font-medium mt-1">{selectedPipeline.currentStep}/{selectedPipeline.steps}</div>
                  </div>
                </div>
              </div>

              {/* Pipeline Steps */}
              <div className="p-6">
                <h3 className="font-semibold text-gray-900 mb-4">Pipeline Steps</h3>
                <div className="space-y-3">
                  {pipelineSteps.map((step, index) => (
                    <div key={step.id} className="flex items-center gap-4">
                      {/* Step Number */}
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                        step.status === 'completed' ? 'bg-green-100 text-green-700' :
                        step.status === 'running' ? 'bg-blue-100 text-blue-700' :
                        step.status === 'failed' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-500'
                      }`}>
                        {index + 1}
                      </div>

                      {/* Step Content */}
                      <div className="flex-1 bg-gray-50 rounded-lg p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {getStepIcon(step.type)}
                            <span className="font-medium text-gray-900">{step.name}</span>
                            {step.status === 'running' && (
                              <RefreshCw className="h-3 w-3 animate-spin text-blue-600" />
                            )}
                          </div>
                          {step.duration && (
                            <span className="text-xs text-gray-500">{step.duration}</span>
                          )}
                        </div>
                        {step.output && (
                          <div className="text-xs text-gray-600 mt-1 font-mono">{step.output}</div>
                        )}
                      </div>

                      {/* Status Icon */}
                      <div>
                        {step.status === 'completed' && <CheckCircle className="h-5 w-5 text-green-600" />}
                        {step.status === 'running' && <RefreshCw className="h-5 w-5 text-blue-600 animate-spin" />}
                        {step.status === 'failed' && <XCircle className="h-5 w-5 text-red-600" />}
                        {step.status === 'pending' && <Clock className="h-5 w-5 text-gray-400" />}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Pipeline Logs */}
                <div className="mt-6">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-gray-900">Execution Logs</h3>
                    <button className="text-sm text-gray-600 hover:text-gray-900">
                      <Terminal className="h-4 w-4 inline mr-1" />
                      View Full Logs
                    </button>
                  </div>
                  <div className="bg-gray-900 text-gray-100 rounded-lg p-4 font-mono text-xs h-32 overflow-y-auto">
                    <div>[2024-01-15 14:23:45] Pipeline started</div>
                    <div>[2024-01-15 14:23:46] Loading dataset: sub-01_task-motor_bold.nii.gz</div>
                    <div>[2024-01-15 14:25:01] Motion correction completed</div>
                    <div>[2024-01-15 14:26:33] Slice timing correction completed</div>
                    <div>[2024-01-15 14:28:15] Normalization to MNI space completed</div>
                    <div className="text-blue-400">[2024-01-15 14:31:27] Running GLM estimation...</div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-96 text-gray-500">
              Select a pipeline to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}