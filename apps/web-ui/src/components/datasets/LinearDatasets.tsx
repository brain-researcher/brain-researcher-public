'use client'

import { useState, useEffect } from 'react'
import { 
  Database, 
  Upload, 
  Search, 
  Filter, 
  Download, 
  ChevronRight,
  Calendar,
  HardDrive,
  Users,
  Brain,
  Activity,
  FileText,
  MoreVertical,
  Plus,
  FolderOpen,
  Clock,
  Check,
  AlertCircle
} from 'lucide-react'
import Link from 'next/link'
import { getDatasets } from '@/lib/datasets'
import { Badge } from '@/components/ui/badge'

interface Dataset {
  id: string
  name: string
  description: string
  type: 'fMRI' | 'sMRI' | 'DTI' | 'PET' | 'MEG' | 'EEG'
  size: string
  subjects: number
  sessions: number
  modality: string[]
  status: 'available' | 'processing' | 'archived'
  lastModified: string
  owner: string
  shared: boolean
  category?: string
}

export function LinearDatasets() {
  const [loading, setLoading] = useState(true)
  const [selectedFilter, setSelectedFilter] = useState<'all' | 'my-datasets' | 'shared' | 'public'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [datasets, setDatasets] = useState<Dataset[]>([])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const { datasets: apiDatasets } = await getDatasets({ limit: 20, offset: 0 })

        const mapModality = (mods: string[] | undefined): string[] => {
          if (!mods || mods.length === 0) return []
          return mods.map((m) => (m === 'dMRI' ? 'DTI' : m))
        }

        const pickType = (mods: string[] | undefined): Dataset['type'] => {
          const m = (mods && mods[0]) || 'fMRI'
          switch (m) {
            case 'sMRI':
              return 'sMRI'
            case 'EEG':
              return 'EEG'
            case 'MEG':
              return 'MEG'
            case 'DTI':
            case 'dMRI':
              return 'DTI'
            case 'PET':
              return 'PET'
            default:
              return 'fMRI'
          }
        }

        const toDisplayDate = (d: Date | string | undefined) => {
          try {
            const date = d instanceof Date ? d : d ? new Date(d) : undefined
            return date ? date.toLocaleDateString() : '—'
          } catch {
            return '—'
          }
        }

        const mapped: Dataset[] = apiDatasets.map((d: any) => ({
          id: d.id,
          name: d.name,
          description: d.description,
          type: pickType(mapModality(d.modality)),
          size: d.size || '—',
          subjects: d.nSubjects || 0,
          sessions: d.nSessions || 1,
          modality: mapModality(d.modality),
          status: 'available',
          lastModified: toDisplayDate(d.lastUpdated),
          owner: d.source && d.source !== 'Built-in Sample' ? d.source : 'You',
          shared: d.source && d.source !== 'Built-in Sample',
          category: d.category,
        }))

        if (!cancelled) setDatasets(mapped)
      } catch (err) {
        if (!cancelled) setDatasets([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'available':
        return 'bg-green-100 text-green-700 border-green-200'
      case 'processing':
        return 'bg-yellow-100 text-yellow-700 border-yellow-200'
      case 'archived':
        return 'bg-gray-100 text-gray-700 border-gray-200'
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200'
    }
  }

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'fMRI':
        return <Brain className="h-4 w-4 text-purple-500" />
      case 'sMRI':
        return <Brain className="h-4 w-4 text-blue-500" />
      case 'DTI':
        return <Activity className="h-4 w-4 text-green-500" />
      case 'MEG':
      case 'EEG':
        return <Activity className="h-4 w-4 text-orange-500" />
      default:
        return <FileText className="h-4 w-4 text-gray-500" />
    }
  }

  const filteredDatasets = datasets.filter(dataset => {
    if (selectedFilter === 'my-datasets' && dataset.owner !== 'You') return false
    if (selectedFilter === 'shared' && !dataset.shared) return false
    if (selectedFilter === 'public' && dataset.owner === 'You') return false
    
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return dataset.name.toLowerCase().includes(query) || 
             dataset.description.toLowerCase().includes(query) ||
             dataset.type.toLowerCase().includes(query)
    }
    
    return true
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="animate-pulse text-gray-500">Loading datasets...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Datasets</h1>
            <p className="text-gray-600 mt-1">Manage and explore neuroimaging datasets</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/datasets/explorer"
              className="px-4 py-2 border border-gray-300 text-gray-800 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Advanced Explorer
            </Link>
            <button className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-2">
              <Plus className="h-4 w-4" />
              New Dataset
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Database className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">{datasets.length}</div>
                <div className="text-sm text-gray-600">Total Datasets</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <HardDrive className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">137.5 GB</div>
                <div className="text-sm text-gray-600">Total Storage</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">229</div>
                <div className="text-sm text-gray-600">Total Subjects</div>
              </div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 text-gray-400" />
              <div>
                <div className="text-2xl font-semibold">1 Active</div>
                <div className="text-sm text-gray-600">Processing</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedFilter('all')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedFilter === 'all' 
                  ? 'bg-black text-white' 
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              All Datasets
            </button>
            <button
              onClick={() => setSelectedFilter('my-datasets')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedFilter === 'my-datasets' 
                  ? 'bg-black text-white' 
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              My Datasets
            </button>
            <button
              onClick={() => setSelectedFilter('shared')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedFilter === 'shared' 
                  ? 'bg-black text-white' 
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              Shared with Me
            </button>
            <button
              onClick={() => setSelectedFilter('public')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedFilter === 'public' 
                  ? 'bg-black text-white' 
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              Public
            </button>
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="h-4 w-4 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search datasets..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 pr-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black focus:border-transparent"
              />
            </div>
            <button className="p-1.5 border border-gray-300 rounded-lg hover:bg-gray-50">
              <Filter className="h-4 w-4 text-gray-600" />
            </button>
          </div>
        </div>
      </div>

      {/* Dataset List */}
      <div className="space-y-3">
        {filteredDatasets.map((dataset) => (
          <div key={dataset.id} className="bg-white rounded-lg border border-gray-200 p-4 hover:border-gray-300 transition-colors">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4 flex-1">
                {/* Icon */}
                <div className="mt-1">
                  {getTypeIcon(dataset.type)}
                </div>

                {/* Main Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-gray-900">{dataset.name}</h3>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${getStatusColor(dataset.status)}`}>
                      {dataset.status}
                    </span>
                    {dataset.shared && (
                      <Users className="h-3 w-3 text-gray-400" />
                    )}
                  </div>
                  {dataset.category && (
                    <Badge variant="outline" className="mb-2 text-[10px]">
                      {dataset.category}
                    </Badge>
                  )}
                  <p className="text-sm text-gray-600 mb-2">{dataset.description}</p>
                  
                  {/* Metadata */}
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <div className="flex items-center gap-1">
                      <Users className="h-3 w-3" />
                      {dataset.subjects} subjects
                    </div>
                    <div className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {dataset.sessions} session{dataset.sessions > 1 ? 's' : ''}
                    </div>
                    <div className="flex items-center gap-1">
                      <HardDrive className="h-3 w-3" />
                      {dataset.size}
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {dataset.lastModified}
                    </div>
                    <div>
                      Owner: {dataset.owner}
                    </div>
                  </div>

                  {/* Modality Tags */}
                  <div className="flex items-center gap-1 mt-2">
                    {dataset.modality.map((mod) => (
                      <span key={mod} className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs">
                        {mod}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                <button className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
                  <Download className="h-4 w-4 text-gray-600" />
                </button>
                <button className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
                  <FolderOpen className="h-4 w-4 text-gray-600" />
                </button>
                <button className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
                  <MoreVertical className="h-4 w-4 text-gray-600" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Empty State */}
      {filteredDatasets.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-12">
          <div className="text-center">
            <Database className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No datasets found</h3>
            <p className="text-gray-600 mb-4">
              {searchQuery 
                ? `No datasets match "${searchQuery}"`
                : 'Get started by uploading your first dataset'}
            </p>
            {!searchQuery && (
              <button className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors">
                <Upload className="h-4 w-4 inline mr-2" />
                Upload Dataset
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
