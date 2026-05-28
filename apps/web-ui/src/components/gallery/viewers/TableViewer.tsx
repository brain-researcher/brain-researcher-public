'use client'

import React, { useState, useMemo } from 'react'
import { 
  Download, Search, Filter, SortAsc, SortDesc, 
  ChevronLeft, ChevronRight, FileSpreadsheet,
  Copy, Eye, EyeOff
} from 'lucide-react'

interface TableViewerProps {
  item: {
    id: string
    name: string
    data: any[][] | { [key: string]: any }[]
    metadata: {
      rows?: number
      columns?: number
      format?: string
      [key: string]: any
    }
  }
  onDownload?: () => void
  className?: string
}

export function TableViewer({ item, onDownload, className = '' }: TableViewerProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const [sortColumn, setSortColumn] = useState<number | null>(null)
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [currentPage, setCurrentPage] = useState(1)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set())
  const [hiddenColumns, setHiddenColumns] = useState<Set<number>>(new Set())
  const [copiedCell, setCopiedCell] = useState<string | null>(null)

  // Convert data to consistent format
  const tableData = useMemo(() => {
    if (!item.data || !Array.isArray(item.data)) return []
    
    // If data is array of objects, convert to 2D array
    if (item.data.length > 0 && typeof item.data[0] === 'object' && !Array.isArray(item.data[0])) {
      const objects = item.data as { [key: string]: any }[]
      const headers = Object.keys(objects[0] || {})
      return [
        headers,
        ...objects.map(obj => headers.map(header => obj[header]))
      ]
    }
    
    // Already 2D array
    return item.data as any[][]
  }, [item.data])

  const headers = tableData[0] || []
  const rows = tableData.slice(1)

  // Filtering and searching
  const filteredRows = useMemo(() => {
    if (!searchTerm) return rows

    return rows.filter(row =>
      row.some((cell: any) =>
        String(cell).toLowerCase().includes(searchTerm.toLowerCase())
      )
    )
  }, [rows, searchTerm])

  // Sorting
  const sortedRows = useMemo(() => {
    if (sortColumn === null) return filteredRows

    return [...filteredRows].sort((a, b) => {
      const aVal = a[sortColumn]
      const bVal = b[sortColumn]
      
      // Handle numeric values
      const aNum = Number(aVal)
      const bNum = Number(bVal)
      
      let comparison = 0
      if (!isNaN(aNum) && !isNaN(bNum)) {
        comparison = aNum - bNum
      } else {
        comparison = String(aVal).localeCompare(String(bVal))
      }
      
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [filteredRows, sortColumn, sortDirection])

  // Pagination
  const totalPages = Math.ceil(sortedRows.length / rowsPerPage)
  const paginatedRows = sortedRows.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  )

  const handleSort = (columnIndex: number) => {
    if (sortColumn === columnIndex) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(columnIndex)
      setSortDirection('asc')
    }
  }

  const handleRowSelect = (rowIndex: number) => {
    const newSelection = new Set(selectedRows)
    if (newSelection.has(rowIndex)) {
      newSelection.delete(rowIndex)
    } else {
      newSelection.add(rowIndex)
    }
    setSelectedRows(newSelection)
  }

  const handleSelectAll = () => {
    if (selectedRows.size === paginatedRows.length) {
      setSelectedRows(new Set())
    } else {
      setSelectedRows(new Set(paginatedRows.map((_, i) => i)))
    }
  }

  const handleCopyCell = async (value: any) => {
    try {
      await navigator.clipboard.writeText(String(value))
      setCopiedCell(String(value))
      setTimeout(() => setCopiedCell(null), 2000)
    } catch (error) {
      console.error('Failed to copy:', error)
    }
  }

  const toggleColumnVisibility = (columnIndex: number) => {
    const newHidden = new Set(hiddenColumns)
    if (newHidden.has(columnIndex)) {
      newHidden.delete(columnIndex)
    } else {
      newHidden.add(columnIndex)
    }
    setHiddenColumns(newHidden)
  }

  const exportToCSV = () => {
    const csvContent = [
      headers.filter((_, i) => !hiddenColumns.has(i)).join(','),
      ...sortedRows.map(row =>
        row.filter((_, i) => !hiddenColumns.has(i))
          .map((cell: any) => `"${String(cell).replace(/"/g, '""')}"`)
          .join(',')
      )
    ].join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${item.name}_filtered.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`bg-white rounded-lg shadow-lg border border-gray-200 ${className}`}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">{item.name}</h3>
            <div className="flex items-center gap-2">
              <span className="px-2 py-1 bg-purple-100 text-purple-800 text-xs rounded-full">
                {item.metadata.format || 'Table'}
              </span>
              <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                {filteredRows.length} rows × {headers.filter((_, i) => !hiddenColumns.has(i)).length} cols
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={exportToCSV}
              className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              title="Export filtered data as CSV"
            >
              <Download className="h-4 w-4" />
            </button>
            {onDownload && (
              <button
                onClick={onDownload}
                className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                title="Download original file"
              >
                <FileSpreadsheet className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between flex-wrap gap-4">
          {/* Search and Selection */}
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search table..."
                className="pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            
            {selectedRows.size > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-600">
                  {selectedRows.size} row{selectedRows.size > 1 ? 's' : ''} selected
                </span>
                <button
                  onClick={() => setSelectedRows(new Set())}
                  className="px-3 py-1.5 bg-gray-600 text-white rounded-md hover:bg-gray-700 transition-colors text-sm"
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          {/* Pagination Controls */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-600">Rows per page:</span>
              <select
                value={rowsPerPage}
                onChange={(e) => {
                  setRowsPerPage(Number(e.target.value))
                  setCurrentPage(1)
                }}
                className="px-2 py-1 border border-gray-300 rounded text-sm"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-600">
                {Math.min((currentPage - 1) * rowsPerPage + 1, sortedRows.length)} - 
                {Math.min(currentPage * rowsPerPage, sortedRows.length)} of {sortedRows.length}
              </span>
              <button
                onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage === 1}
                className="p-1 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                disabled={currentPage === totalPages}
                className="p-1 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Column Visibility Controls */}
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="text-sm text-gray-600">Columns:</span>
          {headers.map((header, index) => (
            <button
              key={index}
              onClick={() => toggleColumnVisibility(index)}
              className={`px-2 py-1 rounded text-xs transition-colors ${
                hiddenColumns.has(index)
                  ? 'bg-gray-200 text-gray-500'
                  : 'bg-blue-100 text-blue-800'
              }`}
            >
              {hiddenColumns.has(index) ? <EyeOff className="h-3 w-3 inline mr-1" /> : <Eye className="h-3 w-3 inline mr-1" />}
              {header}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-auto max-h-96">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <input
                  type="checkbox"
                  checked={selectedRows.size === paginatedRows.length && paginatedRows.length > 0}
                  onChange={handleSelectAll}
                  className="rounded"
                />
              </th>
              {headers.map((header, index) => {
                if (hiddenColumns.has(index)) return null
                
                return (
                  <th
                    key={index}
                    className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                    onClick={() => handleSort(index)}
                  >
                    <div className="flex items-center gap-1">
                      {header}
                      {sortColumn === index && (
                        sortDirection === 'asc' ? 
                          <SortAsc className="h-3 w-3" /> : 
                          <SortDesc className="h-3 w-3" />
                      )}
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {paginatedRows.map((row, rowIndex) => (
              <tr 
                key={rowIndex} 
                className={`hover:bg-gray-50 ${selectedRows.has(rowIndex) ? 'bg-blue-50' : ''}`}
              >
                <td className="px-6 py-4 whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={selectedRows.has(rowIndex)}
                    onChange={() => handleRowSelect(rowIndex)}
                    className="rounded"
                  />
                </td>
                {row.map((cell, cellIndex) => {
                  if (hiddenColumns.has(cellIndex)) return null
                  
                  return (
                    <td 
                      key={cellIndex} 
                      className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 relative group cursor-pointer"
                      onClick={() => handleCopyCell(cell)}
                      title="Click to copy"
                    >
                      {String(cell)}
                      {copiedCell === String(cell) && (
                        <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 px-2 py-1 bg-gray-900 text-white text-xs rounded whitespace-nowrap">
                          Copied!
                        </div>
                      )}
                      <Copy className="h-3 w-3 absolute top-1/2 right-1 transform -translate-y-1/2 opacity-0 group-hover:opacity-50 transition-opacity" />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>

        {paginatedRows.length === 0 && (
          <div className="text-center py-12">
            <p className="text-gray-500">
              {searchTerm ? 'No rows match your search' : 'No data available'}
            </p>
          </div>
        )}
      </div>

      {/* Footer with statistics */}
      <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between text-sm text-gray-600">
          <div>
            Total: {rows.length} rows, {headers.length} columns
            {searchTerm && (
              <span className="ml-2">
                ({filteredRows.length} filtered)
              </span>
            )}
          </div>
          <div>
            {selectedRows.size > 0 && (
              <span>{selectedRows.size} row{selectedRows.size > 1 ? 's' : ''} selected</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}