'use client'

import { memo } from 'react'
import { Search } from 'lucide-react'
import { ConceptTreeNodeComponent, ConceptTreeNode } from './ConceptTreeNode'

export type ConceptSearchSuggestion = {
  label: string
  query?: string
  description?: string
}

interface ConceptSearchPanelProps {
  panelTitle?: string
  searchPlaceholder?: string
  loadingMessage?: string
  emptyMessage?: string
  searchSuggestions?: ConceptSearchSuggestion[]
  searchQuery: string
  onSearchChange: (query: string) => void
  onUseSearchInMcp?: (query: string) => void
  filteredTree: ConceptTreeNode[]
  conceptTree: ConceptTreeNode[]
  selectedConceptId: string | null
  expandedNodes: Set<string>
  loadingNodes: Set<string>
  onToggleNode: (conceptId: string) => void
  onSelectConcept: (conceptId: string, label?: string) => void
}

const ConceptSearchPanelRaw = ({
  panelTitle = 'Entities',
  searchPlaceholder = 'Search entities',
  loadingMessage = 'Loading concept tree…',
  emptyMessage = 'No concepts match your search.',
  searchSuggestions = [],
  searchQuery,
  onSearchChange,
  onUseSearchInMcp,
  filteredTree,
  conceptTree,
  selectedConceptId,
  expandedNodes,
  loadingNodes,
  onToggleNode,
  onSelectConcept
}: ConceptSearchPanelProps) => {
  const cleanSearchQuery = searchQuery.trim()
  const hasNoMatches = Boolean(cleanSearchQuery) && filteredTree.length === 0
  const statusMessage =
    conceptTree.length === 0 && !cleanSearchQuery ? loadingMessage : emptyMessage

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-3">
      <div className="text-sm font-semibold">{panelTitle}</div>
      <div className="relative">
        <Search className="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          data-tour="kg-search"
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9 pr-3 py-2 w-full border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black"
        />
      </div>
      <div className="max-h-[72vh] overflow-y-auto space-y-1">
        {filteredTree.length > 0 ? (
          filteredTree.map((root) => (
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
          ))
        ) : (
          <div className="space-y-3 text-sm text-gray-500">
            <div>{statusMessage}</div>
            {hasNoMatches && searchSuggestions.length > 0 ? (
              <div className="rounded border border-gray-200 bg-gray-50 p-3">
                <div className="text-xs font-medium text-gray-700">Try seed terms</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {searchSuggestions.map((suggestion) => (
                    <button
                      key={suggestion.label}
                      type="button"
                      className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 hover:border-gray-500"
                      title={suggestion.description}
                      onClick={() => onSearchChange(suggestion.query || suggestion.label)}
                    >
                      {suggestion.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            {hasNoMatches && cleanSearchQuery && onUseSearchInMcp ? (
              <button
                type="button"
                className="w-full rounded border border-black bg-black px-3 py-2 text-left text-xs font-medium text-white hover:bg-gray-800"
                onClick={() => onUseSearchInMcp(cleanSearchQuery)}
              >
                Use this query in MCP
              </button>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}

export const ConceptSearchPanel = memo(ConceptSearchPanelRaw)
