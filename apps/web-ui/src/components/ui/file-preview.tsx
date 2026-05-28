'use client'

import React from 'react'
import { FileText, Database, Image as ImageIcon, Download, X } from 'lucide-react'
import { FileAttachment } from '@/types/chat'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface FilePreviewProps {
  attachments: FileAttachment[]
  onRemove: (fileId: string) => void
  showRemove?: boolean
  className?: string
}

const getFileIcon = (type: string) => {
  if (type.includes('csv')) return Database
  if (type.includes('json')) return FileText
  if (type.includes('pdf')) return FileText
  if (type.includes('gzip') || type.includes('octet-stream')) return ImageIcon
  return FileText
}

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const getFileTypeLabel = (type: string) => {
  if (type.includes('gzip')) return 'NIFTI (Compressed)'
  if (type.includes('octet-stream')) return 'NIFTI'
  if (type.includes('csv')) return 'CSV Data'
  if (type.includes('json')) return 'JSON Data'
  if (type.includes('pdf')) return 'PDF Document'
  if (type.includes('text/plain')) return 'Text File'
  return 'File'
}

export function FilePreview({ 
  attachments, 
  onRemove, 
  showRemove = true, 
  className 
}: FilePreviewProps) {
  if (attachments.length === 0) return null

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-sm font-medium">Attached Files ({attachments.length})</p>
      <div className="grid gap-2">
        {attachments.map((attachment) => {
          const Icon = getFileIcon(attachment.type)
          
          return (
            <div
              key={attachment.id}
              className="flex items-center space-x-3 p-3 bg-muted/50 border rounded-lg hover:bg-muted/70 transition-colors"
            >
              {/* File icon */}
              <Icon className="h-5 w-5 text-muted-foreground flex-shrink-0" />

              {/* File info */}
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium truncate" title={attachment.name}>
                    {attachment.name}
                  </p>
                  <span className="text-xs text-muted-foreground ml-2">
                    {formatFileSize(attachment.size)}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {getFileTypeLabel(attachment.type)}
                </p>
              </div>

              {/* Actions */}
              <div className="flex items-center space-x-1 flex-shrink-0">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    // Open file in new tab
                    window.open(attachment.url, '_blank')
                  }}
                  className="h-7 w-7 p-0"
                  title="View file"
                >
                  <Download className="h-3 w-3" />
                </Button>
                
                {showRemove && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onRemove(attachment.id)}
                    className="h-7 w-7 p-0 hover:bg-destructive/10 hover:text-destructive"
                    title="Remove file"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}