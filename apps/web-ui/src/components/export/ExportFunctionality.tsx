'use client'

import React, { useState, useRef } from 'react'
import { 
  Download, FileText, Image, FileJson, Table, 
  Archive, Check, X, Loader2, ChevronDown,
  FileImage, FilePlus, Settings, Share2
} from 'lucide-react'
import { toPng, toJpeg, toSvg } from 'html-to-image'
import { jsPDF } from 'jspdf'
import { saveAs } from 'file-saver'
import JSZip from 'jszip'
import { useToast } from '@/hooks/use-toast'

interface ExportOptions {
  format: 'pdf' | 'png' | 'svg' | 'jpeg' | 'csv' | 'json' | 'zip'
  quality?: number
  scale?: number
  includeMetadata?: boolean
  includeTimestamp?: boolean
  paperSize?: 'a4' | 'letter' | 'a3'
  orientation?: 'portrait' | 'landscape'
  margin?: number
}

interface ExportableData {
  title?: string
  content?: any
  element?: HTMLElement | null
  data?: any[]
  metadata?: Record<string, any>
}

interface ExportPreset {
  id: string
  name: string
  icon: React.ReactNode
  format: ExportOptions['format']
  options: Partial<ExportOptions>
  description?: string
}

export function ExportFunctionality({
  data,
  element,
  title = 'Export',
  onExport,
  className
}: {
  data?: ExportableData
  element?: React.RefObject<HTMLElement>
  title?: string
  onExport?: (format: string) => void
  className?: string
}) {
  const { toast } = useToast()
  const [isExporting, setIsExporting] = useState(false)
  const [showOptions, setShowOptions] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<ExportOptions['format']>('pdf')
  const [exportOptions, setExportOptions] = useState<ExportOptions>({
    format: 'pdf',
    quality: 0.95,
    scale: 2,
    includeMetadata: true,
    includeTimestamp: true,
    paperSize: 'a4',
    orientation: 'portrait',
    margin: 10
  })
  
  const exportPresets: ExportPreset[] = [
    {
      id: 'report-pdf',
      name: 'Full Report (PDF)',
      icon: <FileText className="w-4 h-4" />,
      format: 'pdf',
      options: {
        paperSize: 'a4',
        orientation: 'portrait',
        includeMetadata: true
      },
      description: 'Complete analysis report with all visualizations'
    },
    {
      id: 'high-res-png',
      name: 'High Resolution Image',
      icon: <Image className="w-4 h-4" />,
      format: 'png',
      options: {
        quality: 1,
        scale: 3
      },
      description: 'Publication-quality PNG image'
    },
    {
      id: 'vector-svg',
      name: 'Vector Graphics',
      icon: <FileImage className="w-4 h-4" />,
      format: 'svg',
      options: {},
      description: 'Scalable vector format for editing'
    },
    {
      id: 'data-csv',
      name: 'Data Table (CSV)',
      icon: <Table className="w-4 h-4" />,
      format: 'csv',
      options: {
        includeMetadata: false
      },
      description: 'Spreadsheet-compatible data export'
    },
    {
      id: 'raw-json',
      name: 'Raw Data (JSON)',
      icon: <FileJson className="w-4 h-4" />,
      format: 'json',
      options: {
        includeMetadata: true
      },
      description: 'Complete data with metadata'
    },
    {
      id: 'archive-zip',
      name: 'Archive Bundle',
      icon: <Archive className="w-4 h-4" />,
      format: 'zip',
      options: {
        includeMetadata: true,
        includeTimestamp: true
      },
      description: 'All formats in a single archive'
    }
  ]

  // Export to PDF
  const exportToPDF = async (targetElement: HTMLElement, options: ExportOptions) => {
    try {
      const canvas = await toPng(targetElement, {
        quality: options.quality,
        pixelRatio: options.scale
      })
      
      const pdf = new jsPDF({
        orientation: options.orientation,
        unit: 'mm',
        format: options.paperSize
      })
      
      const imgProps = pdf.getImageProperties(canvas)
      const pdfWidth = pdf.internal.pageSize.getWidth()
      const pdfHeight = pdf.internal.pageSize.getHeight()
      const margin = options.margin || 10
      
      const widthRatio = (pdfWidth - 2 * margin) / imgProps.width
      const heightRatio = (pdfHeight - 2 * margin) / imgProps.height
      const ratio = Math.min(widthRatio, heightRatio)
      
      const imgWidth = imgProps.width * ratio
      const imgHeight = imgProps.height * ratio
      
      const x = (pdfWidth - imgWidth) / 2
      const y = margin
      
      // Add title
      if (title) {
        pdf.setFontSize(16)
        pdf.text(title, pdfWidth / 2, margin / 2, { align: 'center' })
      }
      
      // Add image
      pdf.addImage(canvas, 'PNG', x, y, imgWidth, imgHeight)
      
      // Add metadata
      if (options.includeMetadata && data?.metadata) {
        pdf.addPage()
        pdf.setFontSize(12)
        pdf.text('Metadata', margin, margin)
        
        let yPos = margin + 10
        Object.entries(data.metadata).forEach(([key, value]) => {
          pdf.setFontSize(10)
          pdf.text(`${key}: ${JSON.stringify(value)}`, margin, yPos)
          yPos += 5
        })
      }
      
      // Add timestamp
      if (options.includeTimestamp) {
        const timestamp = new Date().toLocaleString()
        pdf.setFontSize(8)
        pdf.text(timestamp, margin, pdfHeight - 5)
      }
      
      pdf.save(`${title.replace(/\s+/g, '_')}.pdf`)
    } catch (error) {
      console.error('PDF export error:', error)
      throw error
    }
  }

  // Export to Image (PNG/SVG/JPEG)
  const exportToImage = async (targetElement: HTMLElement, options: ExportOptions) => {
    try {
      let dataUrl: string
      
      switch (options.format) {
        case 'png':
          dataUrl = await toPng(targetElement, {
            quality: options.quality,
            pixelRatio: options.scale
          })
          break
        case 'jpeg':
          dataUrl = await toJpeg(targetElement, {
            quality: options.quality,
            pixelRatio: options.scale
          })
          break
        case 'svg':
          dataUrl = await toSvg(targetElement)
          break
        default:
          throw new Error('Unsupported image format')
      }
      
      // Convert data URL to blob
      const response = await fetch(dataUrl)
      const blob = await response.blob()
      
      // Save file
      saveAs(blob, `${title.replace(/\s+/g, '_')}.${options.format}`)
    } catch (error) {
      console.error('Image export error:', error)
      throw error
    }
  }

  // Export to CSV
  const exportToCSV = (data: any[], options: ExportOptions) => {
    try {
      if (!data || data.length === 0) {
        throw new Error('No data to export')
      }
      
      // Get headers from first object
      const headers = Object.keys(data[0])
      
      // Build CSV content
      let csvContent = headers.join(',') + '\n'
      
      data.forEach(row => {
        const values = headers.map(header => {
          const value = row[header]
          // Escape quotes and wrap in quotes if contains comma
          if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
            return `"${value.replace(/"/g, '""')}"`
          }
          return value ?? ''
        })
        csvContent += values.join(',') + '\n'
      })
      
      // Add metadata as comments if requested
      if (options.includeMetadata && data) {
        csvContent = `# Exported: ${new Date().toISOString()}\n` + 
                    `# Title: ${title}\n` + 
                    csvContent
      }
      
      // Create blob and save
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
      saveAs(blob, `${title.replace(/\s+/g, '_')}.csv`)
    } catch (error) {
      console.error('CSV export error:', error)
      throw error
    }
  }

  // Export to JSON
  const exportToJSON = (data: any, options: ExportOptions) => {
    try {
      const exportData: any = {
        title,
        exportDate: new Date().toISOString(),
        data
      }
      
      if (options.includeMetadata && data?.metadata) {
        exportData.metadata = data.metadata
      }
      
      const jsonStr = JSON.stringify(exportData, null, 2)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      saveAs(blob, `${title.replace(/\s+/g, '_')}.json`)
    } catch (error) {
      console.error('JSON export error:', error)
      throw error
    }
  }

  // Export to ZIP (all formats)
  const exportToZIP = async (targetElement: HTMLElement, data: any, options: ExportOptions) => {
    try {
      const zip = new JSZip()
      const folder = zip.folder(title.replace(/\s+/g, '_'))
      
      if (!folder) throw new Error('Failed to create ZIP folder')
      
      // Add PDF
      try {
        const pdfCanvas = await toPng(targetElement, { quality: 1, pixelRatio: 2 })
        const pdfBlob = await (await fetch(pdfCanvas)).blob()
        folder.file('report.pdf', pdfBlob)
      } catch (e) {
        console.warn('Failed to add PDF to archive', e)
      }
      
      // Add PNG
      try {
        const pngCanvas = await toPng(targetElement, { quality: 1, pixelRatio: 3 })
        const pngBlob = await (await fetch(pngCanvas)).blob()
        folder.file('visualization.png', pngBlob)
      } catch (e) {
        console.warn('Failed to add PNG to archive', e)
      }
      
      // Add SVG
      try {
        const svgData = await toSvg(targetElement)
        const svgBlob = await (await fetch(svgData)).blob()
        folder.file('visualization.svg', svgBlob)
      } catch (e) {
        console.warn('Failed to add SVG to archive', e)
      }
      
      // Add JSON
      if (data) {
        const jsonData = {
          title,
          exportDate: new Date().toISOString(),
          data,
          metadata: data?.metadata
        }
        folder.file('data.json', JSON.stringify(jsonData, null, 2))
      }
      
      // Add CSV if data is array
      if (Array.isArray(data?.data)) {
        const headers = Object.keys(data.data[0])
        let csvContent = headers.join(',') + '\n'
        data.data.forEach((row: any) => {
          csvContent += headers.map(h => row[h] ?? '').join(',') + '\n'
        })
        folder.file('data.csv', csvContent)
      }
      
      // Add README
      const readme = `# ${title}

Exported: ${new Date().toLocaleString()}

## Contents
- report.pdf: Full PDF report
- visualization.png: High-resolution image
- visualization.svg: Vector graphics
- data.json: Raw data with metadata
- data.csv: Tabular data (if applicable)

## Metadata
${JSON.stringify(data?.metadata || {}, null, 2)}
`
      folder.file('README.md', readme)
      
      // Generate and save ZIP
      const content = await zip.generateAsync({ type: 'blob' })
      saveAs(content, `${title.replace(/\s+/g, '_')}_bundle.zip`)
    } catch (error) {
      console.error('ZIP export error:', error)
      throw error
    }
  }

  // Main export handler
  const handleExport = async (format?: ExportOptions['format']) => {
    setIsExporting(true)
    const exportFormat = format || exportOptions.format
    
    try {
      const targetElement = element?.current || document.getElementById('export-target')
      
      if (!targetElement && ['pdf', 'png', 'svg', 'jpeg', 'zip'].includes(exportFormat)) {
        throw new Error('No element to export')
      }
      
      switch (exportFormat) {
        case 'pdf':
          if (targetElement) {
            await exportToPDF(targetElement, exportOptions)
          }
          break
          
        case 'png':
        case 'svg':
        case 'jpeg':
          if (targetElement) {
            await exportToImage(targetElement, { ...exportOptions, format: exportFormat })
          }
          break
          
        case 'csv':
          if (data?.data && Array.isArray(data.data)) {
            exportToCSV(data.data, exportOptions)
          } else {
            throw new Error('No data available for CSV export')
          }
          break
          
        case 'json':
          if (data) {
            exportToJSON(data, exportOptions)
          } else {
            throw new Error('No data available for JSON export')
          }
          break
          
        case 'zip':
          if (targetElement) {
            await exportToZIP(targetElement, data, exportOptions)
          }
          break
          
        default:
          throw new Error(`Unsupported format: ${exportFormat}`)
      }
      
      toast({
        title: 'Export Successful',
        description: `Exported as ${exportFormat.toUpperCase()}`
      })
      
      if (onExport) {
        onExport(exportFormat)
      }
    } catch (error: any) {
      console.error('Export error:', error)
      toast({
        title: 'Export Failed',
        description: error.message || 'An error occurred during export',
        variant: 'destructive'
      })
    } finally {
      setIsExporting(false)
      setShowOptions(false)
    }
  }

  // Quick export buttons
  const QuickExportButtons = () => (
    <div className="flex space-x-2">
      <button
        onClick={() => handleExport('pdf')}
        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
        title="Export as PDF"
      >
        <FileText className="w-4 h-4" />
      </button>
      <button
        onClick={() => handleExport('png')}
        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
        title="Export as PNG"
      >
        <Image className="w-4 h-4" />
      </button>
      <button
        onClick={() => handleExport('csv')}
        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
        title="Export as CSV"
        disabled={!data?.data || !Array.isArray(data.data)}
      >
        <Table className="w-4 h-4" />
      </button>
      <button
        onClick={() => handleExport('json')}
        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
        title="Export as JSON"
        disabled={!data}
      >
        <FileJson className="w-4 h-4" />
      </button>
    </div>
  )

  return (
    <div className={`relative ${className || ''}`}>
      <div className="flex items-center space-x-2">
        {/* Main Export Button */}
        <button
          onClick={() => setShowOptions(!showOptions)}
          disabled={isExporting}
          className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center space-x-2"
        >
          {isExporting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          <span>Export</span>
          <ChevronDown className={`w-4 h-4 transition-transform ${showOptions ? 'rotate-180' : ''}`} />
        </button>
        
        {/* Quick Export Buttons */}
        <QuickExportButtons />
      </div>

      {/* Export Options Dropdown */}
      {showOptions && (
        <div className="absolute top-full mt-2 left-0 w-96 bg-white dark:bg-gray-900 rounded-xl shadow-xl border p-4 z-50">
          <h3 className="font-semibold mb-3">Export Options</h3>
          
          {/* Format Presets */}
          <div className="space-y-2 mb-4">
            {exportPresets.map(preset => (
              <button
                key={preset.id}
                onClick={() => {
                  setExportOptions({ ...exportOptions, ...preset.options, format: preset.format })
                  handleExport(preset.format)
                }}
                className="w-full flex items-center space-x-3 p-3 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg text-left"
              >
                {preset.icon}
                <div className="flex-1">
                  <div className="font-medium">{preset.name}</div>
                  <div className="text-sm text-gray-500">{preset.description}</div>
                </div>
                <ChevronDown className="w-4 h-4 -rotate-90" />
              </button>
            ))}
          </div>
          
          {/* Advanced Options */}
          <details className="border-t pt-3">
            <summary className="cursor-pointer font-medium text-sm flex items-center space-x-2">
              <Settings className="w-4 h-4" />
              <span>Advanced Options</span>
            </summary>
            
            <div className="mt-3 space-y-3">
              {/* Quality Slider */}
              <div>
                <label className="text-sm font-medium">Quality: {Math.round((exportOptions.quality || 0.95) * 100)}%</label>
                <input
                  type="range"
                  min="0.5"
                  max="1"
                  step="0.05"
                  value={exportOptions.quality}
                  onChange={(e) => setExportOptions({ ...exportOptions, quality: parseFloat(e.target.value) })}
                  className="w-full"
                />
              </div>
              
              {/* Scale */}
              <div>
                <label className="text-sm font-medium">Scale: {exportOptions.scale}x</label>
                <input
                  type="range"
                  min="1"
                  max="4"
                  step="0.5"
                  value={exportOptions.scale}
                  onChange={(e) => setExportOptions({ ...exportOptions, scale: parseFloat(e.target.value) })}
                  className="w-full"
                />
              </div>
              
              {/* Checkboxes */}
              <div className="space-y-2">
                <label className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    checked={exportOptions.includeMetadata}
                    onChange={(e) => setExportOptions({ ...exportOptions, includeMetadata: e.target.checked })}
                    className="rounded"
                  />
                  <span className="text-sm">Include Metadata</span>
                </label>
                <label className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    checked={exportOptions.includeTimestamp}
                    onChange={(e) => setExportOptions({ ...exportOptions, includeTimestamp: e.target.checked })}
                    className="rounded"
                  />
                  <span className="text-sm">Include Timestamp</span>
                </label>
              </div>
              
              {/* Paper Options for PDF */}
              {selectedFormat === 'pdf' && (
                <>
                  <div>
                    <label className="text-sm font-medium block mb-1">Paper Size</label>
                    <select
                      value={exportOptions.paperSize}
                      onChange={(e) => setExportOptions({ ...exportOptions, paperSize: e.target.value as any })}
                      className="w-full px-3 py-2 border rounded-lg"
                    >
                      <option value="a4">A4</option>
                      <option value="letter">Letter</option>
                      <option value="a3">A3</option>
                    </select>
                  </div>
                  
                  <div>
                    <label className="text-sm font-medium block mb-1">Orientation</label>
                    <select
                      value={exportOptions.orientation}
                      onChange={(e) => setExportOptions({ ...exportOptions, orientation: e.target.value as any })}
                      className="w-full px-3 py-2 border rounded-lg"
                    >
                      <option value="portrait">Portrait</option>
                      <option value="landscape">Landscape</option>
                    </select>
                  </div>
                </>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

export default ExportFunctionality