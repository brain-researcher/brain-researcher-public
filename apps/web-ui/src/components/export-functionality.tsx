'use client'

import React, { useState, useCallback } from 'react'
import { 
  Download, FileText, Image, Table, Code, 
  Check, X, Loader2, Share2, Copy, Mail
} from 'lucide-react'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'

interface ExportOptions {
  format: 'pdf' | 'png' | 'svg' | 'csv' | 'json' | 'xlsx'
  quality?: 'low' | 'medium' | 'high'
  includeMetadata?: boolean
  includeTimestamp?: boolean
  compress?: boolean
}

interface ExportData {
  title?: string
  description?: string
  data: any
  metadata?: Record<string, any>
  elementRef?: React.RefObject<HTMLElement>
}

interface ExportProgress {
  status: 'idle' | 'preparing' | 'processing' | 'complete' | 'error'
  progress: number
  message?: string
}

interface ExportFunctionalityProps {
  data: ExportData
  onExport?: (format: string, blob: Blob) => void
  onShare?: (method: string, data: any) => void
  enabledFormats?: ExportOptions['format'][]
  defaultOptions?: Partial<ExportOptions>
}

const formatIcons = {
  pdf: FileText,
  png: Image,
  svg: Image,
  csv: Table,
  json: Code,
  xlsx: Table
}

const formatDescriptions = {
  pdf: 'Portable Document Format - Best for sharing and printing',
  png: 'PNG Image - High quality raster image',
  svg: 'SVG Vector - Scalable vector graphics',
  csv: 'CSV Table - Comma-separated values for spreadsheets',
  json: 'JSON Data - Structured data format',
  xlsx: 'Excel Spreadsheet - Microsoft Excel format'
}

export function ExportFunctionality({
  data,
  onExport,
  onShare,
  enabledFormats = ['pdf', 'png', 'csv', 'json'],
  defaultOptions = {}
}: ExportFunctionalityProps) {
  const [showModal, setShowModal] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<ExportOptions['format']>('pdf')
  const [options, setOptions] = useState<ExportOptions>({
    format: 'pdf',
    quality: 'high',
    includeMetadata: true,
    includeTimestamp: true,
    compress: false,
    ...defaultOptions
  })
  const [progress, setProgress] = useState<ExportProgress>({
    status: 'idle',
    progress: 0
  })
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  // Export to PDF
  const exportToPDF = useCallback(async () => {
    if (!data.elementRef?.current) {
      throw new Error('No element to export')
    }

    setProgress({ status: 'preparing', progress: 10, message: 'Preparing PDF...' })

    const canvas = await html2canvas(data.elementRef.current, {
      scale: options.quality === 'high' ? 3 : options.quality === 'medium' ? 2 : 1,
      logging: false
    })

    setProgress({ status: 'processing', progress: 50, message: 'Generating PDF...' })

    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF({
      orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
      unit: 'px',
      format: [canvas.width, canvas.height]
    })

    pdf.addImage(imgData, 'PNG', 0, 0, canvas.width, canvas.height)

    // Add metadata
    if (options.includeMetadata && data.metadata) {
      pdf.setProperties({
        title: data.title || 'Export',
        subject: data.description || '',
        creator: 'Brain Researcher',
        keywords: Object.keys(data.metadata).join(', ')
      })
    }

    // Add timestamp
    if (options.includeTimestamp) {
      pdf.setFontSize(10)
      pdf.text(`Generated: ${new Date().toLocaleString()}`, 10, canvas.height - 10)
    }

    setProgress({ status: 'processing', progress: 90, message: 'Finalizing...' })

    const blob = pdf.output('blob')
    return blob
  }, [data, options])

  // Export to PNG
  const exportToPNG = useCallback(async () => {
    if (!data.elementRef?.current) {
      throw new Error('No element to export')
    }

    setProgress({ status: 'preparing', progress: 10, message: 'Capturing image...' })

    const canvas = await html2canvas(data.elementRef.current, {
      scale: options.quality === 'high' ? 3 : options.quality === 'medium' ? 2 : 1,
      logging: false
    })

    setProgress({ status: 'processing', progress: 50, message: 'Processing image...' })

    return new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (blob) {
            resolve(blob)
          } else {
            reject(new Error('Failed to create image'))
          }
        },
        'image/png',
        options.quality === 'high' ? 1 : options.quality === 'medium' ? 0.8 : 0.6
      )
    })
  }, [data, options])

  // Export to SVG
  const exportToSVG = useCallback(async () => {
    if (!data.elementRef?.current) {
      throw new Error('No element to export')
    }

    setProgress({ status: 'processing', progress: 50, message: 'Generating SVG...' })

    // Clone the element and convert to SVG
    const clone = data.elementRef.current.cloneNode(true) as HTMLElement
    const svgString = `
      <svg xmlns="http://www.w3.org/2000/svg" width="${clone.offsetWidth}" height="${clone.offsetHeight}">
        <foreignObject width="100%" height="100%">
          <div xmlns="http://www.w3.org/1999/xhtml">
            ${clone.outerHTML}
          </div>
        </foreignObject>
      </svg>
    `

    const blob = new Blob([svgString], { type: 'image/svg+xml' })
    return blob
  }, [data])

  // Export to CSV
  const exportToCSV = useCallback(async () => {
    setProgress({ status: 'processing', progress: 50, message: 'Generating CSV...' })

    let csvContent = ''

    // Convert data to CSV format
    if (Array.isArray(data.data)) {
      // If data is an array of objects
      const headers = Object.keys(data.data[0] || {})
      csvContent = headers.join(',') + '\n'
      
      data.data.forEach(row => {
        const values = headers.map(header => {
          const value = row[header]
          // Escape commas and quotes
          if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
            return `"${value.replace(/"/g, '""')}"`
          }
          return value
        })
        csvContent += values.join(',') + '\n'
      })
    } else {
      // Convert object to CSV
      csvContent = 'Key,Value\n'
      Object.entries(data.data).forEach(([key, value]) => {
        csvContent += `"${key}","${value}"\n`
      })
    }

    // Add metadata as comments
    if (options.includeMetadata && data.metadata) {
      csvContent = `# ${data.title || 'Export'}\n# ${data.description || ''}\n# Generated: ${new Date().toISOString()}\n\n${csvContent}`
    }

    const blob = new Blob([csvContent], { type: 'text/csv' })
    return blob
  }, [data, options])

  // Export to JSON
  const exportToJSON = useCallback(async () => {
    setProgress({ status: 'processing', progress: 50, message: 'Generating JSON...' })

    const exportData: any = {
      data: data.data
    }

    if (options.includeMetadata) {
      exportData.metadata = {
        ...data.metadata,
        title: data.title,
        description: data.description,
        exportDate: new Date().toISOString()
      }
    }

    const jsonString = JSON.stringify(exportData, null, 2)
    const blob = new Blob([jsonString], { type: 'application/json' })
    return blob
  }, [data, options])

  // Main export handler
  const handleExport = useCallback(async () => {
    setProgress({ status: 'preparing', progress: 0 })

    try {
      let blob: Blob

      switch (selectedFormat) {
        case 'pdf':
          blob = await exportToPDF()
          break
        case 'png':
          blob = await exportToPNG()
          break
        case 'svg':
          blob = await exportToSVG()
          break
        case 'csv':
          blob = await exportToCSV()
          break
        case 'json':
          blob = await exportToJSON()
          break
        default:
          throw new Error(`Unsupported format: ${selectedFormat}`)
      }

      setProgress({ status: 'complete', progress: 100, message: 'Export complete!' })

      // Download the file
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${data.title || 'export'}_${new Date().getTime()}.${selectedFormat}`
      link.click()
      URL.revokeObjectURL(url)

      // Call callback
      onExport?.(selectedFormat, blob)

      // Close modal after delay
      setTimeout(() => {
        setShowModal(false)
        setProgress({ status: 'idle', progress: 0 })
      }, 1500)
    } catch (error) {
      console.error('Export failed:', error)
      setProgress({ 
        status: 'error', 
        progress: 0, 
        message: error instanceof Error ? error.message : 'Export failed' 
      })
    }
  }, [selectedFormat, data, onExport, exportToPDF, exportToPNG, exportToSVG, exportToCSV, exportToJSON])

  // Generate share link
  const generateShareLink = useCallback(async () => {
    // Mock share link generation
    const shareData = {
      title: data.title,
      data: data.data,
      timestamp: new Date().toISOString()
    }
    
    const encoded = btoa(JSON.stringify(shareData))
    const url = `${window.location.origin}/shared/${encoded.substring(0, 10)}`
    setShareUrl(url)
    
    return url
  }, [data])

  // Copy to clipboard
  const copyToClipboard = useCallback(async (text: string) => {
    await navigator.clipboard.writeText(text)
  }, [])

  return (
    <>
      {/* Export Button */}
      <button
        onClick={() => setShowModal(true)}
        className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 flex items-center gap-2"
      >
        <Download className="h-4 w-4" />
        Export
      </button>

      {/* Export Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-2xl">
            {/* Header */}
            <div className="p-6 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold">Export Data</h2>
                <button
                  onClick={() => setShowModal(false)}
                  className="p-1 hover:bg-gray-100 rounded"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              {data.title && (
                <p className="text-gray-600 mt-1">{data.title}</p>
              )}
            </div>

            {/* Content */}
            <div className="p-6">
              {/* Format Selection */}
              <div className="mb-6">
                <h3 className="font-medium mb-3">Select Format</h3>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {enabledFormats.map(format => {
                    const Icon = formatIcons[format]
                    return (
                      <button
                        key={format}
                        onClick={() => setSelectedFormat(format)}
                        className={`p-3 rounded-lg border-2 transition-all ${
                          selectedFormat === format
                            ? 'border-blue-500 bg-blue-50'
                            : 'border-gray-200 hover:border-gray-300'
                        }`}
                      >
                        <Icon className="h-6 w-6 mx-auto mb-1" />
                        <div className="text-sm font-medium uppercase">{format}</div>
                      </button>
                    )
                  })}
                </div>
                <p className="text-sm text-gray-600 mt-2">
                  {formatDescriptions[selectedFormat]}
                </p>
              </div>

              {/* Options */}
              <div className="mb-6 space-y-3">
                <h3 className="font-medium mb-3">Options</h3>
                
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={options.includeMetadata}
                    onChange={(e) => setOptions({ ...options, includeMetadata: e.target.checked })}
                    className="rounded text-blue-600"
                  />
                  <span>Include metadata</span>
                </label>

                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={options.includeTimestamp}
                    onChange={(e) => setOptions({ ...options, includeTimestamp: e.target.checked })}
                    className="rounded text-blue-600"
                  />
                  <span>Add timestamp</span>
                </label>

                {(selectedFormat === 'pdf' || selectedFormat === 'png') && (
                  <div>
                    <label className="block text-sm font-medium mb-1">Quality</label>
                    <select
                      value={options.quality}
                      onChange={(e) => setOptions({ ...options, quality: e.target.value as any })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md"
                    >
                      <option value="low">Low (Faster, smaller file)</option>
                      <option value="medium">Medium</option>
                      <option value="high">High (Slower, larger file)</option>
                    </select>
                  </div>
                )}
              </div>

              {/* Progress */}
              {progress.status !== 'idle' && (
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-gray-600">{progress.message}</span>
                    <span className="text-sm font-medium">{progress.progress}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full transition-all ${
                        progress.status === 'error' ? 'bg-red-500' :
                        progress.status === 'complete' ? 'bg-green-500' :
                        'bg-blue-500'
                      }`}
                      style={{ width: `${progress.progress}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Share Options */}
              <div className="border-t pt-4">
                <h3 className="font-medium mb-3">Share</h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={generateShareLink}
                    className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-md flex items-center gap-2"
                  >
                    <Share2 className="h-4 w-4" />
                    Generate Link
                  </button>
                  {shareUrl && (
                    <>
                      <input
                        type="text"
                        value={shareUrl}
                        readOnly
                        className="flex-1 px-3 py-1.5 border border-gray-300 rounded-md text-sm"
                      />
                      <button
                        onClick={() => copyToClipboard(shareUrl)}
                        className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-md"
                        title="Copy to clipboard"
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-gray-200 bg-gray-50">
              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-md"
                >
                  Cancel
                </button>
                <button
                  onClick={handleExport}
                  disabled={progress.status === 'preparing' || progress.status === 'processing'}
                  className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2"
                >
                  {progress.status === 'preparing' || progress.status === 'processing' ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Exporting...
                    </>
                  ) : progress.status === 'complete' ? (
                    <>
                      <Check className="h-4 w-4" />
                      Complete!
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4" />
                      Export {selectedFormat.toUpperCase()}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}