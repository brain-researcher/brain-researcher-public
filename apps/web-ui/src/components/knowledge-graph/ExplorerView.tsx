'use client'

import { memo } from 'react'
import { Activity } from 'lucide-react'
import { ConceptTreeNodeComponent, ConceptTreeNode } from './ConceptTreeNode'

interface ExplorerViewProps {
  filteredTree: ConceptTreeNode[]
  selectedConceptId: string | null
  expandedNodes: Set<string>
  loadingNodes: Set<string>
  searchQuery: string
  onToggleNode: (conceptId: string) => void
  onSelectConcept: (conceptId: string, label?: string) => void
  onRefresh: () => void
}

const ExplorerViewRaw = ({
  filteredTree,
  selectedConceptId,
  expandedNodes,
  loadingNodes,
  searchQuery,
  onToggleNode,
  onSelectConcept,
  onRefresh
}: ExplorerViewProps) => {
  const normalizedQuery = searchQuery.trim().toLowerCase()

  return (
    <div className="p-6 space-y-3">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-sm text-gray-500">ONVOC hierarchy (depth ≤ 3)</div>
          <div className="text-lg font-semibold">Concept tree</div>
        </div>
        <button
          className="inline-flex items-center px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
          onClick={onRefresh}
        >
          <Activity className="h-4 w-4 mr-2 text-gray-600" />
          Refresh
        </button>
      </div>

      <div className="space-y-1 max-h-[60vh] overflow-y-auto">
        {filteredTree.length === 0 && (
          <div className="text-sm text-gray-500">
            {normalizedQuery ? 'No concepts match your search.' : 'Tree not loaded yet.'}
          </div>
        )}
        {filteredTree.map((root) => (
          <ConceptTreeNodeComponent
            key={root.id}
            node={root}
            depth={0}
            selectedConceptId={selectedConceptId}
            expandedNodes={expandedNodes}
            loadingNodes={loadingNodes}
            onToggle={onToggleNode}
            onSelect={onSelectConcept}
          />
        ))}
      </div>
    </div>
  )
}

export const ExplorerView = memo(ExplorerViewRaw)
