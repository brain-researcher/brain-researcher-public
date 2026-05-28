'use client'

import React from 'react'
import { CheckCircle, XCircle, RotateCcw, FileText, Database, Image as ImageIcon } from 'lucide-react'
import { UploadingFile } from '@/hooks/use-file-upload'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface UploadProgressProps {
  uploadingFiles: UploadingFile[]
  onRetry: (uploadId: string) => void
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

export function UploadProgress({ uploadingFiles, onRetry, className }: UploadProgressProps) {
  if (uploadingFiles.length === 0) return null

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-sm font-medium">Uploading Files</p>
      <div className="space-y-2">
        {uploadingFiles.map((uploadingFile) => {
          const Icon = getFileIcon(uploadingFile.file.type)
          const isUploading = uploadingFile.status === 'uploading'
          const isCompleted = uploadingFile.status === 'completed'
          const isError = uploadingFile.status === 'error'

          return (
            <div
              key={uploadingFile.id}
              className="flex items-center space-x-3 p-3 bg-card border rounded-lg"
            >
              {/* File icon */}
              <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />

              {/* File info and progress */}
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium truncate">{uploadingFile.file.name}</p>
                  <span className="text-xs text-muted-foreground">
                    {formatFileSize(uploadingFile.file.size)}
                  </span>
                </div>

                {isUploading && (
                  <div className="space-y-1">
                    <Progress value={uploadingFile.progress} className="h-2" />
                    <p className="text-xs text-muted-foreground">
                      {uploadingFile.progress}% uploaded
                    </p>
                  </div>
                )}

                {isCompleted && (
                  <p className="text-xs text-green-600">Upload completed</p>
                )}

                {isError && (
                  <div className="space-y-1">
                    <p className="text-xs text-destructive">
                      {uploadingFile.error || 'Upload failed'}
                    </p>
                  </div>
                )}
              </div>

              {/* Status icon and actions */}
              <div className="flex items-center space-x-1 flex-shrink-0">
                {isUploading && (
                  <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                )}

                {isCompleted && (
                  <CheckCircle className="h-4 w-4 text-green-600" />
                )}

                {isError && (
                  <div className="flex items-center space-x-1">
                    <XCircle className="h-4 w-4 text-destructive" />
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onRetry(uploadingFile.id)}
                      className="h-6 w-6 p-0"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}