'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { 
  Download, 
  FileText, 
  Image, 
  Table, 
  Mail,
  Calendar,
  Settings
} from 'lucide-react'
import { AnalyticsFilter } from '@/types/analytics'

interface ExportMenuProps {
  onExport: (format: 'csv' | 'pdf' | 'json' | 'png', options?: ExportOptions) => Promise<void>
  filter: AnalyticsFilter
  className?: string
}

interface ExportOptions {
  includeCharts?: boolean
  includeTables?: boolean
  includeMetadata?: boolean
  dateRange?: boolean
  format?: string
  fileName?: string
  email?: {
    recipients: string[]
    subject: string
    message: string
  }
  schedule?: {
    frequency: 'daily' | 'weekly' | 'monthly'
    dayOfWeek?: number
    dayOfMonth?: number
    time: string
  }
}

export function ExportMenu({ onExport, filter, className }: ExportMenuProps) {
  const [exportLoading, setExportLoading] = useState<string | null>(null)
  const [showAdvancedDialog, setShowAdvancedDialog] = useState(false)
  const [exportOptions, setExportOptions] = useState<ExportOptions>({
    includeCharts: true,
    includeTables: true,
    includeMetadata: true,
    dateRange: true,
    fileName: `analytics-report-${new Date().toISOString().split('T')[0]}`
  })

  const handleSimpleExport = async (format: 'csv' | 'pdf' | 'json' | 'png') => {
    setExportLoading(format)
    try {
      await onExport(format)
    } finally {
      setExportLoading(null)
    }
  }

  const handleAdvancedExport = async (format: 'csv' | 'pdf' | 'json' | 'png') => {
    setExportLoading(format)
    try {
      await onExport(format, exportOptions)
      setShowAdvancedDialog(false)
    } finally {
      setExportLoading(null)
    }
  }

  const updateExportOptions = (key: keyof ExportOptions, value: any) => {
    setExportOptions(prev => ({ ...prev, [key]: value }))
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button 
            variant="outline" 
            size="sm" 
            className={className}
            disabled={!!exportLoading}
          >
            <Download className="h-4 w-4 mr-2" />
            {exportLoading ? `Exporting ${exportLoading.toUpperCase()}...` : 'Export'}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel>Quick Export</DropdownMenuLabel>
          <DropdownMenuItem 
            onClick={() => handleSimpleExport('csv')}
            disabled={exportLoading === 'csv'}
          >
            <Table className="h-4 w-4 mr-2" />
            Export as CSV
          </DropdownMenuItem>
          <DropdownMenuItem 
            onClick={() => handleSimpleExport('pdf')}
            disabled={exportLoading === 'pdf'}
          >
            <FileText className="h-4 w-4 mr-2" />
            Export as PDF
          </DropdownMenuItem>
          <DropdownMenuItem 
            onClick={() => handleSimpleExport('png')}
            disabled={exportLoading === 'png'}
          >
            <Image className="h-4 w-4 mr-2" />
            Export Charts as PNG
          </DropdownMenuItem>
          <DropdownMenuItem 
            onClick={() => handleSimpleExport('json')}
            disabled={exportLoading === 'json'}
          >
            <FileText className="h-4 w-4 mr-2" />
            Export Raw Data (JSON)
          </DropdownMenuItem>
          
          <DropdownMenuSeparator />
          
          <DropdownMenuLabel>Advanced Options</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => setShowAdvancedDialog(true)}>
            <Settings className="h-4 w-4 mr-2" />
            Custom Export...
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Advanced Export Dialog */}
      <Dialog open={showAdvancedDialog} onOpenChange={setShowAdvancedDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Custom Export Options</DialogTitle>
            <DialogDescription>
              Customize your analytics export with advanced options
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6">
            {/* File Options */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium">File Options</h4>
              
              <div className="space-y-2">
                <Label htmlFor="fileName">File Name</Label>
                <Input
                  id="fileName"
                  value={exportOptions.fileName}
                  onChange={(e) => updateExportOptions('fileName', e.target.value)}
                  placeholder="analytics-report"
                />
              </div>

              <div className="space-y-3">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="includeCharts"
                    checked={exportOptions.includeCharts}
                    onCheckedChange={(checked) => updateExportOptions('includeCharts', checked)}
                  />
                  <Label htmlFor="includeCharts">Include Charts</Label>
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="includeTables"
                    checked={exportOptions.includeTables}
                    onCheckedChange={(checked) => updateExportOptions('includeTables', checked)}
                  />
                  <Label htmlFor="includeTables">Include Data Tables</Label>
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="includeMetadata"
                    checked={exportOptions.includeMetadata}
                    onCheckedChange={(checked) => updateExportOptions('includeMetadata', checked)}
                  />
                  <Label htmlFor="includeMetadata">Include Metadata & Filters</Label>
                </div>
              </div>
            </div>

            {/* Email Options */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium">Email Delivery (Optional)</h4>
              
              <div className="space-y-2">
                <Label htmlFor="recipients">Recipients</Label>
                <Input
                  id="recipients"
                  placeholder="Add recipient emails (comma-separated)"
                  value={exportOptions.email?.recipients.join(', ') || ''}
                  onChange={(e) => updateExportOptions('email', {
                    ...exportOptions.email,
                    recipients: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                  })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="subject">Email Subject</Label>
                <Input
                  id="subject"
                  placeholder="Analytics Report"
                  value={exportOptions.email?.subject || ''}
                  onChange={(e) => updateExportOptions('email', {
                    ...exportOptions.email,
                    subject: e.target.value
                  })}
                />
              </div>
            </div>

            {/* Scheduling Options */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium">Scheduling (Optional)</h4>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="frequency">Frequency</Label>
                  <Select 
                    value={exportOptions.schedule?.frequency || ''}
                    onValueChange={(value: 'daily' | 'weekly' | 'monthly') => 
                      updateExportOptions('schedule', {
                        ...exportOptions.schedule,
                        frequency: value
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select frequency" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="daily">Daily</SelectItem>
                      <SelectItem value="weekly">Weekly</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="time">Time</Label>
                  <Input
                    id="time"
                    type="time"
                    value={exportOptions.schedule?.time || '09:00'}
                    onChange={(e) => updateExportOptions('schedule', {
                      ...exportOptions.schedule,
                      time: e.target.value
                    })}
                  />
                </div>
              </div>

              {exportOptions.schedule?.frequency === 'weekly' && (
                <div className="space-y-2">
                  <Label htmlFor="dayOfWeek">Day of Week</Label>
                  <Select 
                    value={exportOptions.schedule?.dayOfWeek?.toString() || ''}
                    onValueChange={(value) => 
                      updateExportOptions('schedule', {
                        ...exportOptions.schedule,
                        dayOfWeek: parseInt(value)
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select day" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">Monday</SelectItem>
                      <SelectItem value="2">Tuesday</SelectItem>
                      <SelectItem value="3">Wednesday</SelectItem>
                      <SelectItem value="4">Thursday</SelectItem>
                      <SelectItem value="5">Friday</SelectItem>
                      <SelectItem value="6">Saturday</SelectItem>
                      <SelectItem value="0">Sunday</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}

              {exportOptions.schedule?.frequency === 'monthly' && (
                <div className="space-y-2">
                  <Label htmlFor="dayOfMonth">Day of Month</Label>
                  <Input
                    id="dayOfMonth"
                    type="number"
                    min="1"
                    max="31"
                    value={exportOptions.schedule?.dayOfMonth || 1}
                    onChange={(e) => updateExportOptions('schedule', {
                      ...exportOptions.schedule,
                      dayOfMonth: parseInt(e.target.value)
                    })}
                  />
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button 
              variant="outline" 
              onClick={() => setShowAdvancedDialog(false)}
              disabled={!!exportLoading}
            >
              Cancel
            </Button>
            
            <div className="flex space-x-2">
              <Button
                onClick={() => handleAdvancedExport('csv')}
                disabled={exportLoading === 'csv'}
              >
                <Table className="h-4 w-4 mr-2" />
                Export CSV
              </Button>
              
              <Button
                onClick={() => handleAdvancedExport('pdf')}
                disabled={exportLoading === 'pdf'}
              >
                <FileText className="h-4 w-4 mr-2" />
                Export PDF
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
