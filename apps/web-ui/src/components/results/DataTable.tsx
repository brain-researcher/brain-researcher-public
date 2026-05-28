'use client'

import React, { useState, useMemo } from 'react'
import { 
  ChevronUp, ChevronDown, Search, Filter, Download,
  MoreHorizontal, Eye, Copy, CheckCircle
} from 'lucide-react'

export interface TableColumn {
  key: string
  header: string
  type?: 'text' | 'number' | 'date' | 'boolean' | 'custom'
  sortable?: boolean
  filterable?: boolean
  width?: string
  render?: (value: any, row: any) => React.ReactNode
}

export interface TableData {
  [key: string]: any
}

interface DataTableProps {
  data: TableData[]
  columns: TableColumn[]
  title?: string
  searchable?: boolean
  filterable?: boolean
  pagination?: boolean
  pageSize?: number
  onRowClick?: (row: TableData) => void
  onDownload?: () => void
  className?: string
}

type SortDirection = 'asc' | 'desc' | null

interface SortState {
  column: string | null
  direction: SortDirection
}

interface FilterState {
  [key: string]: string
}

export function DataTable({
  data,
  columns,
  title,
  searchable = true,
  filterable = true,
  pagination = true,
  pageSize = 10,
  onRowClick,
  onDownload,
  className = ''
}: DataTableProps) {
  const [sortState, setSortState] = useState<SortState>({ column: null, direction: null })
  const [filters, setFilters] = useState<FilterState>({})
  const [searchTerm, setSearchTerm] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [showFilters, setShowFilters] = useState(false)
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set())
  const [copiedCell, setCopiedCell] = useState<string | null>(null)

  // Filter and sort data
  const processedData = useMemo(() => {
    let filtered = [...data]

    // Apply search
    if (searchTerm) {
      const searchLower = searchTerm.toLowerCase()
      filtered = filtered.filter(row =>
        columns.some(col => {
          const value = row[col.key]
          if (value == null) return false
          return String(value).toLowerCase().includes(searchLower)
        })
      )
    }

    // Apply column filters
    Object.entries(filters).forEach(([key, value]) => {
      if (value) {
        const filterLower = value.toLowerCase()
        filtered = filtered.filter(row => {
          const cellValue = row[key]
          if (cellValue == null) return false
          return String(cellValue).toLowerCase().includes(filterLower)
        })
      }
    })

    // Apply sorting
    if (sortState.column && sortState.direction) {
      filtered.sort((a, b) => {
        const aVal = a[sortState.column!]
        const bVal = b[sortState.column!]
        
        // Handle null/undefined values
        if (aVal == null && bVal == null) return 0
        if (aVal == null) return 1
        if (bVal == null) return -1
        
        // Get column type for proper sorting
        const column = columns.find(col => col.key === sortState.column)
        const type = column?.type || 'text'
        
        let comparison = 0
        
        switch (type) {
          case 'number':
            comparison = Number(aVal) - Number(bVal)
            break
          case 'date':
            comparison = new Date(aVal).getTime() - new Date(bVal).getTime()
            break
          case 'boolean':
            comparison = (aVal ? 1 : 0) - (bVal ? 1 : 0)
            break
          default:
            comparison = String(aVal).localeCompare(String(bVal))
        }
        
        return sortState.direction === 'asc' ? comparison : -comparison
      })
    }

    return filtered
  }, [data, columns, searchTerm, filters, sortState])

  // Pagination
  const totalPages = Math.ceil(processedData.length / pageSize)
  const startIndex = (currentPage - 1) * pageSize
  const endIndex = startIndex + pageSize
  const paginatedData = pagination ? processedData.slice(startIndex, endIndex) : processedData

  const handleSort = (column: TableColumn) => {
    if (!column.sortable) return
    
    setSortState(prev => {
      if (prev.column === column.key) {
        // Cycle through: asc -> desc -> null
        const newDirection = prev.direction === 'asc' ? 'desc' : 
                           prev.direction === 'desc' ? null : 'asc'
        return { column: newDirection ? column.key : null, direction: newDirection }
      } else {
        return { column: column.key, direction: 'asc' }
      }
    })
  }

  const handleFilterChange = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }))
    setCurrentPage(1) // Reset to first page when filtering
  }

  const clearFilters = () => {
    setFilters({})
    setSearchTerm('')
    setCurrentPage(1)
  }

  const handleRowSelect = (index: number) => {
    setSelectedRows(prev => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }

  const selectAllRows = () => {
    if (selectedRows.size === paginatedData.length) {
      setSelectedRows(new Set())
    } else {
      setSelectedRows(new Set(Array.from({ length: paginatedData.length }, (_, i) => i)))
    }
  }

  const copyCell = (value: any) => {
    const textValue = String(value)
    navigator.clipboard.writeText(textValue)
    setCopiedCell(textValue)
    setTimeout(() => setCopiedCell(null), 2000)
  }

  const exportData = () => {
    // Convert to CSV
    const headers = columns.map(col => col.header).join(',')
    const rows = processedData.map(row => 
      columns.map(col => {
        const value = row[col.key]
        // Escape commas and quotes in CSV
        if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
          return `"${value.replace(/"/g, '""')}"`
        }
        return value
      }).join(',')
    )
    
    const csv = [headers, ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title || 'data'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const renderCellValue = (column: TableColumn, value: any, row: TableData) => {
    if (column.render) {
      return column.render(value, row)
    }
    
    if (value == null) {
      return <span className="text-gray-400 italic">null</span>
    }
    
    switch (column.type) {
      case 'boolean':
        return (
          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
            value ? 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400' : 
            'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400'
          }`}>
            {value ? 'Yes' : 'No'}
          </span>
        )
      case 'number':
        return <span className="font-mono">{Number(value).toLocaleString()}</span>
      case 'date':
        return <span className="font-mono">{new Date(value).toLocaleDateString()}</span>
      default:
        return String(value)
    }
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
              {processedData.length} of {data.length} rows
              {selectedRows.size > 0 && ` • ${selectedRows.size} selected`}
            </p>
          </div>
          
          <div className="flex items-center gap-2">
            {filterable && (
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`p-2 rounded-lg border transition-colors ${
                  showFilters 
                    ? 'bg-blue-50 border-blue-200 text-blue-600 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-400'
                    : 'border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'
                }`}
                title="Toggle filters"
              >
                <Filter className="h-4 w-4" />
              </button>
            )}
            
            {onDownload ? (
              <button
                onClick={onDownload}
                className="p-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </button>
            ) : (
              <button
                onClick={exportData}
                className="p-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                title="Export as CSV"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        
        {/* Search Bar */}
        {searchable && (
          <div className="mt-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search all columns..."
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>
        )}
        
        {/* Column Filters */}
        {showFilters && filterable && (
          <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {columns.filter(col => col.filterable !== false).map(column => (
                <div key={column.key}>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {column.header}
                  </label>
                  <input
                    type="text"
                    placeholder={`Filter ${column.header.toLowerCase()}...`}
                    value={filters[column.key] || ''}
                    onChange={(e) => handleFilterChange(column.key, e.target.value)}
                    className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:ring-1 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              ))}
            </div>
            
            <div className="flex justify-end mt-4">
              <button
                onClick={clearFilters}
                className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
              >
                Clear all filters
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-700/50">
            <tr>
              <th className="w-12 px-4 py-3 text-left">
                <input
                  type="checkbox"
                  checked={selectedRows.size === paginatedData.length && paginatedData.length > 0}
                  onChange={selectAllRows}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
              </th>
              {columns.map(column => (
                <th
                  key={column.key}
                  className={`px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider ${
                    column.sortable !== false ? 'cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600' : ''
                  }`}
                  style={{ width: column.width }}
                  onClick={() => handleSort(column)}
                >
                  <div className="flex items-center gap-2">
                    {column.header}
                    {column.sortable !== false && (
                      <div className="flex flex-col">
                        <ChevronUp 
                          className={`h-3 w-3 ${sortState.column === column.key && sortState.direction === 'asc' 
                            ? 'text-blue-600 dark:text-blue-400' : 'text-gray-300 dark:text-gray-600'}`} 
                        />
                        <ChevronDown 
                          className={`h-3 w-3 -mt-1 ${sortState.column === column.key && sortState.direction === 'desc' 
                            ? 'text-blue-600 dark:text-blue-400' : 'text-gray-300 dark:text-gray-600'}`} 
                        />
                      </div>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {paginatedData.length === 0 ? (
              <tr>
                <td 
                  colSpan={columns.length + 1} 
                  className="px-4 py-8 text-center text-gray-500 dark:text-gray-400"
                >
                  No data found
                </td>
              </tr>
            ) : (
              paginatedData.map((row, index) => (
                <tr
                  key={startIndex + index}
                  className={`hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
                    onRowClick ? 'cursor-pointer' : ''
                  } ${selectedRows.has(index) ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                  onClick={() => onRowClick?.(row)}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedRows.has(index)}
                      onChange={(e) => {
                        e.stopPropagation()
                        handleRowSelect(index)
                      }}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </td>
                  {columns.map(column => (
                    <td key={column.key} className="px-4 py-3 text-sm text-gray-900 dark:text-white group relative">
                      <div className="flex items-center justify-between">
                        <div className="truncate">
                          {renderCellValue(column, row[column.key], row)}
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            copyCell(row[column.key])
                          }}
                          className="opacity-0 group-hover:opacity-100 ml-2 p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded transition-opacity"
                          title="Copy cell value"
                        >
                          {copiedCell === String(row[column.key]) ? (
                            <CheckCircle className="h-3 w-3 text-green-500" />
                          ) : (
                            <Copy className="h-3 w-3 text-gray-400" />
                          )}
                        </button>
                      </div>
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pagination && totalPages > 1 && (
        <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-700 dark:text-gray-300">
              Showing {startIndex + 1} to {Math.min(endIndex, processedData.length)} of {processedData.length} results
            </div>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCurrentPage(1)}
                disabled={currentPage === 1}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                First
              </button>
              
              <button
                onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                disabled={currentPage === 1}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Previous
              </button>
              
              <span className="text-sm text-gray-700 dark:text-gray-300 mx-4">
                Page {currentPage} of {totalPages}
              </span>
              
              <button
                onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                disabled={currentPage === totalPages}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Next
              </button>
              
              <button
                onClick={() => setCurrentPage(totalPages)}
                disabled={currentPage === totalPages}
                className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Last
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}