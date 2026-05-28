'use client'

import { memo } from 'react'
import { Network, Layers, Database, Search, Filter, Settings } from 'lucide-react'

export type ViewMode = 'graph' | 'explorer' | 'query'

interface GraphViewTabsProps {
  selectedView: ViewMode
  onViewChange: (view: ViewMode) => void
  searchQuery: string
  onSearchChange: (query: string) => void
  showExplorerTab?: boolean
  showQueryBuilderTab?: boolean
  onFilterClick?: () => void
  onSettingsClick?: () => void
}

const GraphViewTabsRaw = ({
  selectedView,
  onViewChange,
  searchQuery,
  onSearchChange,
  showExplorerTab = true,
  showQueryBuilderTab = true,
  onFilterClick,
  onSettingsClick
}: GraphViewTabsProps) => {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between gap-4">
      <div className="flex items-center gap-2">
        <button
          onClick={() => onViewChange('graph')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            selectedView === 'graph' ? 'bg-black text-white' : 'text-gray-700 hover:bg-gray-100'
          }`}
        >
          <Network className="h-4 w-4 inline mr-1" />
          Graph
        </button>
        {showExplorerTab ? (
          <button
            onClick={() => onViewChange('explorer')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              selectedView === 'explorer' ? 'bg-black text-white' : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Layers className="h-4 w-4 inline mr-1" />
            Explorer
          </button>
        ) : null}
        {showQueryBuilderTab ? (
          <button
            onClick={() => onViewChange('query')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              selectedView === 'query' ? 'bg-black text-white' : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Database className="h-4 w-4 inline mr-1" />
            Query Builder
          </button>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <div className="relative">
          <Search className="h-4 w-4 text-gray-400 absolute left-3 top-1/2 transform -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search nodes..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9 pr-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black w-64"
          />
        </div>
        {onFilterClick && (
          <button
            className="p-1.5 border border-gray-300 rounded-lg hover:bg-gray-50"
            aria-label="Filters"
            onClick={onFilterClick}
          >
            <Filter className="h-4 w-4 text-gray-600" />
          </button>
        )}
        {onSettingsClick && (
          <button
            className="p-1.5 border border-gray-300 rounded-lg hover:bg-gray-50"
            aria-label="Settings"
            onClick={onSettingsClick}
          >
            <Settings className="h-4 w-4 text-gray-600" />
          </button>
        )}
      </div>
    </div>
  )
}

export const GraphViewTabs = memo(GraphViewTabsRaw)
