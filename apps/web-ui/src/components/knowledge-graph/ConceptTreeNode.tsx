'use client'

import { memo } from 'react'
import { ChevronRight, ChevronDown, Loader2 } from 'lucide-react'

export type ConceptTreeNode = {
  id: string
  label: string
  depth: number
  collapsedCount?: number
  children?: ConceptTreeNode[]
  hasChildren?: boolean
  selectable?: boolean
}

interface ConceptTreeNodeProps {
  node: ConceptTreeNode
  depth: number
  selectedConceptId: string | null
  expandedNodes: Set<string>
  loadingNodes: Set<string>
  onToggle: (conceptId: string) => void
  onSelect: (conceptId: string, label?: string) => void
}

const ConceptTreeNodeComponentRaw = ({
  node,
  depth,
  selectedConceptId,
  expandedNodes,
  loadingNodes,
  onToggle,
  onSelect
}: ConceptTreeNodeProps) => {
  const isSelected = selectedConceptId === node.id
  const isExpanded = expandedNodes.has(node.id)
  const isLoading = loadingNodes.has(node.id)
  const hasChildren = node.hasChildren || (node.children && node.children.length > 0)
  const isSelectable = node.selectable !== false
  const isUnmappedFamily = node.id === 'family:tf_unmapped'

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        {/* Expand/collapse chevron for nodes with children */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onToggle(node.id)
            }}
            className="flex-shrink-0 p-1 hover:bg-gray-100 rounded"
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 text-gray-400 animate-spin" />
            ) : isExpanded ? (
              <ChevronDown className="h-4 w-4 text-gray-600" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-600" />
            )}
          </button>
        ) : (
          // Spacer for alignment when no expand icon
          <div className="w-6" />
        )}

        {/* Concept button */}
        <button
          onClick={() => {
            if (isSelectable) onSelect(node.id, node.label)
          }}
          disabled={!isSelectable}
          className={`flex-1 text-left px-3 py-2 rounded border ${
            isSelected
              ? 'border-black bg-gray-100 font-semibold'
              : isUnmappedFamily
                ? 'border-amber-200 bg-amber-50 text-gray-700 hover:border-amber-300'
              : isSelectable
                ? 'border-gray-200 hover:border-gray-300'
                : 'border-gray-200 bg-gray-50 text-gray-600 cursor-default'
          }`}
          style={{ paddingLeft: 12 + depth * 12 }}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">L{node.depth}</span>
            <span className={`text-sm ${isUnmappedFamily ? 'text-gray-700' : 'text-gray-900'}`}>
              {node.label}
            </span>
            {node.collapsedCount && node.collapsedCount > 1 ? (
              <span className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                {node.collapsedCount}
              </span>
            ) : null}
          </div>
        </button>
      </div>

      {/* Render children only if expanded */}
      {isExpanded && node.children && node.children.length > 0 && (
        <div className="space-y-1 ml-6">
          {node.children.map((child) => (
            <ConceptTreeNodeComponent
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedConceptId={selectedConceptId}
              expandedNodes={expandedNodes}
              loadingNodes={loadingNodes}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export const ConceptTreeNodeComponent = memo(ConceptTreeNodeComponentRaw)
