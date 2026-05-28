'use client'

import React, { useState, useMemo } from 'react'
import {
  ChevronRight, ChevronDown, Copy, CheckCircle,
  Search, Download, Expand, Minimize2
} from 'lucide-react'

interface JsonViewerProps {
  data: any
  title?: string
  searchable?: boolean
  downloadable?: boolean
  maxDepth?: number
  className?: string
}

type JsonNodeType = 'object' | 'array' | 'string' | 'number' | 'boolean' | 'null'

interface JsonNode {
  key: string | number
  value: any
  type: JsonNodeType
  path: string[]
  level: number
}

function getJsonNodeType(value: any): JsonNodeType {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value as JsonNodeType
}

function formatValue(value: any, type: JsonNodeType): string {
  switch (type) {
    case 'string':
      return `"${value}"`
    case 'null':
      return 'null'
    case 'boolean':
      return value.toString()
    case 'number':
      return value.toString()
    default:
      return ''
  }
}

function getValueColor(type: JsonNodeType): string {
  switch (type) {
    case 'string':
      return 'text-green-600 dark:text-green-400'
    case 'number':
      return 'text-blue-600 dark:text-blue-400'
    case 'boolean':
      return 'text-purple-600 dark:text-purple-400'
    case 'null':
      return 'text-gray-500 dark:text-gray-400'
    default:
      return 'text-gray-900 dark:text-white'
  }
}

function flattenJson(obj: any, path: string[] = [], level: number = 0): JsonNode[] {
  if (obj === null || typeof obj !== 'object') {
    return [{
      key: path[path.length - 1] || '',
      value: obj,
      type: getJsonNodeType(obj),
      path,
      level
    }]
  }

  const nodes: JsonNode[] = []
  
  if (Array.isArray(obj)) {
    nodes.push({
      key: path[path.length - 1] || '',
      value: obj,
      type: 'array',
      path,
      level
    })
    
    obj.forEach((item, index) => {
      nodes.push(...flattenJson(item, [...path, String(index)], level + 1))
    })
  } else {
    nodes.push({
      key: path[path.length - 1] || '',
      value: obj,
      type: 'object',
      path,
      level
    })
    
    Object.entries(obj).forEach(([key, value]) => {
      nodes.push(...flattenJson(value, [...path, key], level + 1))
    })
  }
  
  return nodes
}

function JsonNodeComponent({ 
  node, 
  isExpanded, 
  onToggle, 
  onCopy,
  copiedPath,
  searchTerm,
  maxDepth
}: {
  node: JsonNode
  isExpanded: boolean
  onToggle: (path: string[]) => void
  onCopy: (value: any, path: string[]) => void
  copiedPath: string | null
  searchTerm: string
  maxDepth?: number
}) {
  const { key, value, type, path, level } = node
  const pathString = path.join('.')
  const isExpandable = type === 'object' || type === 'array'
  const hasChildren = isExpandable && (Array.isArray(value) ? value.length > 0 : Object.keys(value).length > 0)
  const shouldAutoCollapse = maxDepth !== undefined && level >= maxDepth
  
  // Highlight search matches
  const highlightText = (text: string) => {
    if (!searchTerm) return text
    
    const regex = new RegExp(`(${searchTerm})`, 'gi')
    const parts = text.split(regex)
    
    return (
      <>
        {parts.map((part, i) => 
          regex.test(part) ? (
            <mark key={i} className="bg-yellow-200 dark:bg-yellow-800 rounded px-1">
              {part}
            </mark>
          ) : (
            part
          )
        )}
      </>
    )
  }
  
  const getPreview = () => {
    if (type === 'object') {
      const keys = Object.keys(value)
      return keys.length === 0 ? '{}' : `{ ${keys.slice(0, 3).join(', ')}${keys.length > 3 ? '...' : ''} }`
    } else if (type === 'array') {
      return value.length === 0 ? '[]' : `[${value.length} items]`
    }
    return ''
  }
  
  return (
    <div className="group">
      <div 
        className="flex items-center gap-2 py-1 px-2 hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded transition-colors cursor-default"
        style={{ paddingLeft: `${level * 20 + 8}px` }}
      >
        {/* Expand/Collapse Button */}
        {hasChildren ? (
          <button
            onClick={() => onToggle(path)}
            className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded transition-colors"
          >
            {isExpanded && !shouldAutoCollapse ? (
              <ChevronDown className="h-4 w-4 text-gray-600 dark:text-gray-400" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-600 dark:text-gray-400" />
            )}
          </button>
        ) : (
          <div className="w-5" />
        )}
        
        {/* Key */}
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300 min-w-0 flex-shrink-0">
          {typeof key === 'number' ? `[${key}]` : highlightText(String(key))}
          {key !== '' && ': '}
        </span>
        
        {/* Value */}
        <div className="flex-1 min-w-0">
          {isExpandable ? (
            <div className="flex items-center gap-2">
              <span className={`text-sm font-mono ${getValueColor(type)}`}>
                {type === 'object' ? '{' : '['}
              </span>
              {(!isExpanded || shouldAutoCollapse) && (
                <span className="text-sm text-gray-500 dark:text-gray-400 italic">
                  {getPreview()}
                </span>
              )}
              {(!isExpanded || shouldAutoCollapse) && (
                <span className={`text-sm font-mono ${getValueColor(type)}`}>
                  {type === 'object' ? '}' : ']'}
                </span>
              )}
            </div>
          ) : (
            <span className={`text-sm font-mono break-all ${getValueColor(type)}`}>
              {highlightText(formatValue(value, type))}
            </span>
          )}
        </div>
        
        {/* Copy Button */}
        <button
          onClick={() => onCopy(value, path)}
          className="opacity-0 group-hover:opacity-100 p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded transition-all"
          title="Copy value"
        >
          {copiedPath === pathString ? (
            <CheckCircle className="h-3 w-3 text-green-500" />
          ) : (
            <Copy className="h-3 w-3 text-gray-400" />
          )}
        </button>
      </div>
    </div>
  )
}

export function JsonViewer({
  data,
  title,
  searchable = true,
  downloadable = true,
  maxDepth = 3,
  className = ''
}: JsonViewerProps) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())
  const [searchTerm, setSearchTerm] = useState('')
  const [copiedPath, setCopiedPath] = useState<string | null>(null)
  const [allExpanded, setAllExpanded] = useState(false)
  
  const nodes = useMemo(() => flattenJson(data), [data])
  
  // Filter nodes based on search term
  const filteredNodes = useMemo(() => {
    if (!searchTerm) return nodes
    
    const searchLower = searchTerm.toLowerCase()
    return nodes.filter(node => {
      const keyMatch = String(node.key).toLowerCase().includes(searchLower)
      const valueMatch = node.type !== 'object' && node.type !== 'array' && 
                        String(node.value).toLowerCase().includes(searchLower)
      const pathMatch = node.path.join('.').toLowerCase().includes(searchLower)
      
      return keyMatch || valueMatch || pathMatch
    })
  }, [nodes, searchTerm])
  
  // Build tree structure for rendering
  const treeNodes = useMemo(() => {
    const result: JsonNode[] = []
    const processed = new Set<string>()
    
    const addNodeAndParents = (node: JsonNode) => {
      const pathString = node.path.join('.')
      if (processed.has(pathString)) return
      
      // Add parent nodes first
      if (node.path.length > 0) {
        const parentPath = node.path.slice(0, -1)
        const parentNode = nodes.find(n => n.path.join('.') === parentPath.join('.'))
        if (parentNode) {
          addNodeAndParents(parentNode)
        }
      }
      
      if (!processed.has(pathString)) {
        result.push(node)
        processed.add(pathString)
      }
    }
    
    // If searching, include matching nodes and their parents
    if (searchTerm) {
      filteredNodes.forEach(addNodeAndParents)
      return result.sort((a, b) => {
        if (a.level !== b.level) return a.level - b.level
        return a.path.join('.').localeCompare(b.path.join('.'))
      })
    }
    
    return nodes
  }, [nodes, filteredNodes, searchTerm])
  
  const toggleExpanded = (path: string[]) => {
    const pathString = path.join('.')
    setExpandedPaths(prev => {
      const newSet = new Set(prev)
      if (newSet.has(pathString)) {
        newSet.delete(pathString)
      } else {
        newSet.add(pathString)
      }
      return newSet
    })
  }
  
  const expandAll = () => {
    if (allExpanded) {
      setExpandedPaths(new Set())
      setAllExpanded(false)
    } else {
      const allPaths = nodes
        .filter(node => node.type === 'object' || node.type === 'array')
        .map(node => node.path.join('.'))
      setExpandedPaths(new Set(allPaths))
      setAllExpanded(true)
    }
  }
  
  const copyValue = (value: any, path: string[]) => {
    const jsonString = JSON.stringify(value, null, 2)
    navigator.clipboard.writeText(jsonString)
    setCopiedPath(path.join('.'))
    setTimeout(() => setCopiedPath(null), 2000)
  }
  
  const downloadJson = () => {
    const jsonString = JSON.stringify(data, null, 2)
    const blob = new Blob([jsonString], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title || 'data'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }
  
  const renderNode = (node: JsonNode) => {
    const pathString = node.path.join('.')
    const isExpanded = expandedPaths.has(pathString)
    const hasChildren = (node.type === 'object' || node.type === 'array') && 
                       (Array.isArray(node.value) ? node.value.length > 0 : Object.keys(node.value).length > 0)
    
    // Skip child nodes if parent is collapsed
    const parentPath = node.path.slice(0, -1).join('.')
    const parentExpanded = parentPath === '' || expandedPaths.has(parentPath)
    const withinMaxDepth = maxDepth === undefined || node.level < maxDepth
    
    if (node.level > 0 && (!parentExpanded || !withinMaxDepth)) {
      return null
    }
    
    return (
      <JsonNodeComponent
        key={pathString}
        node={node}
        isExpanded={isExpanded}
        onToggle={toggleExpanded}
        onCopy={copyValue}
        copiedPath={copiedPath}
        searchTerm={searchTerm}
        maxDepth={maxDepth}
      />
    )
  }
  
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <div>
            {title && (
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                {title}
              </h3>
            )}
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {searchTerm ? `${filteredNodes.length} matches` : `${nodes.length} nodes`}
            </p>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={expandAll}
              className="p-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              title={allExpanded ? 'Collapse all' : 'Expand all'}
            >
              {allExpanded ? (
                <Minimize2 className="h-4 w-4" />
              ) : (
                <Expand className="h-4 w-4" />
              )}
            </button>
            
            {downloadable && (
              <button
                onClick={downloadJson}
                className="p-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                title="Download JSON"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        
        {/* Search */}
        {searchable && (
          <div className="mt-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search keys and values..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>
        )}
      </div>
      
      {/* JSON Tree */}
      <div className="p-4">
        {treeNodes.length === 0 ? (
          <div className="text-center text-gray-500 dark:text-gray-400 py-8">
            {searchTerm ? 'No matches found' : 'No data'}
          </div>
        ) : (
          <div className="font-mono text-sm bg-gray-50 dark:bg-gray-900 rounded-lg p-4 max-h-96 overflow-auto">
            {treeNodes.map(renderNode).filter(Boolean)}
          </div>
        )}
      </div>
      
      {/* Footer with stats */}
      <div className="px-4 py-2 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400">
        <div className="flex justify-between items-center">
          <span>
            Size: {JSON.stringify(data).length} characters
          </span>
          <span>
            Depth: {Math.max(...nodes.map(n => n.level)) + 1} levels
          </span>
        </div>
      </div>
    </div>
  )
}