'use client'

import React, { useCallback, useState } from 'react'
import { Upload, FileText, Database, Image as ImageIcon, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FileUploadZoneProps {
  onFilesSelected: (files: File[]) => void
  disabled?: boolean
  maxFiles?: number
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

export function FileUploadZone({ 
  onFilesSelected, 
  disabled = false, 
  maxFiles = 10,
  className 
}: FileUploadZoneProps) {
  const [dragActive, setDragActive] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true)
    } else if (e.type === "dragleave") {
      setDragActive(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    if (disabled) return

    const files = Array.from(e.dataTransfer.files).slice(0, maxFiles)
    if (files.length > 0) {
      setSelectedFiles(files)
      onFilesSelected(files)
    }
  }, [disabled, maxFiles, onFilesSelected])

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (disabled) return

    const files = Array.from(e.target.files || []).slice(0, maxFiles)
    if (files.length > 0) {
      setSelectedFiles(files)
      onFilesSelected(files)
    }
  }, [disabled, maxFiles, onFilesSelected])

  const removeFile = useCallback((index: number) => {
    const newFiles = selectedFiles.filter((_, i) => i !== index)
    setSelectedFiles(newFiles)
    onFilesSelected(newFiles)
  }, [selectedFiles, onFilesSelected])

  return (
    <div className={cn("space-y-3", className)}>
      {/* Drop Zone */}
      <div
        className={cn(
          "relative border-2 border-dashed border-muted-foreground/25 rounded-lg p-6",
          "transition-colors duration-200 cursor-pointer",
          "hover:border-muted-foreground/50 hover:bg-muted/50",
          dragActive && "border-primary bg-primary/5",
          disabled && "cursor-not-allowed opacity-50"
        )}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => {
          if (!disabled) {
            document.getElementById('file-upload-input')?.click()
          }
        }}
      >
        <input
          id="file-upload-input"
          type="file"
          multiple
          accept=".nii,.nii.gz,.csv,.json,.pdf,.txt"
          onChange={handleFileInput}
          disabled={disabled}
          className="hidden"
        />

        <div className="flex flex-col items-center justify-center space-y-2 text-center">
          <Upload className={cn(
            "h-10 w-10 text-muted-foreground",
            dragActive && "text-primary"
          )} />
          <div className="space-y-1">
            <p className="text-sm font-medium">
              {dragActive ? "Drop files here" : "Upload files"}
            </p>
            <p className="text-xs text-muted-foreground">
              Drag & drop or click to browse
            </p>
          </div>
        </div>

        <div className="mt-3 text-xs text-muted-foreground text-center">
          Supported: NIFTI (.nii, .nii.gz), CSV, JSON, PDF, TXT
          <br />
          Max size: 100MB for NIFTI, 10MB for others
        </div>
      </div>

      {/* Selected Files */}
      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Selected Files ({selectedFiles.length})</p>
          <div className="space-y-1">
            {selectedFiles.map((file, index) => {
              const Icon = getFileIcon(file.type)
              return (
                <div
                  key={`${file.name}-${index}`}
                  className="flex items-center justify-between p-2 bg-muted rounded-md"
                >
                  <div className="flex items-center space-x-2 min-w-0 flex-1">
                    <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatFileSize(file.size)}
                      </p>
                    </div>
                  </div>
                  {!disabled && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFile(index)
                      }}
                      className="p-1 hover:bg-destructive/10 hover:text-destructive rounded-sm transition-colors"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}