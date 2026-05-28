'use client'

import React, { useState, useRef } from 'react'
import { Camera, X, Upload, Download, Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useScreenshot } from '@/hooks/useScreenshot'
import { FeedbackCategory } from '@/types/feedback'

interface ScreenshotCaptureProps {
  screenshot: File | null
  onScreenshotChange: (screenshot: File | null) => void
  category: FeedbackCategory
  className?: string
  required?: boolean
}

export function ScreenshotCapture({
  screenshot,
  onScreenshotChange,
  category,
  className,
  required = false
}: ScreenshotCaptureProps) {
  const [showPreview, setShowPreview] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  const {
    isCapturing,
    captureScreenshot,
    getPreviewUrl,
    error,
    canCapture
  } = useScreenshot()

  const previewUrl = screenshot ? getPreviewUrl(screenshot) : null

  const handleCapture = async () => {
    try {
      const capturedFile = await captureScreenshot({
        quality: 0.8,
        includeFullPage: false,
        maskSensitiveData: true,
        excludeSelectors: ['.feedback-dialog', '.feedback-trigger']
      })
      
      if (capturedFile) {
        onScreenshotChange(capturedFile)
      }
    } catch (err) {
      console.error('Screenshot capture failed:', err)
    }
  }

  const handleFileSelect = (file: File) => {
    if (file && file.type.startsWith('image/')) {
      onScreenshotChange(file)
    }
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleFileSelect(file)
    }
  }

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDragIn = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(true)
  }

  const handleDragOut = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    
    const files = Array.from(e.dataTransfer.files)
    const imageFile = files.find(file => file.type.startsWith('image/'))
    
    if (imageFile) {
      handleFileSelect(imageFile)
    }
  }

  const downloadScreenshot = () => {
    if (screenshot && previewUrl) {
      const link = document.createElement('a')
      link.href = previewUrl
      link.download = screenshot.name
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
  }

  const isHelpful = ['bug-report', 'ui-ux', 'performance'].includes(category)

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-foreground">
          Screenshot {required && <span className="text-destructive">*</span>}
        </label>
        {isHelpful && (
          <span className="text-xs text-muted-foreground bg-muted px-2 py-1 rounded">
            Recommended for {category.replace('-', ' ')}
          </span>
        )}
      </div>

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-md">
          <p className="text-sm text-destructive">
            Screenshot error: {error}
          </p>
        </div>
      )}

      {!screenshot ? (
        <div
          className={cn(
            'border-2 border-dashed rounded-lg p-6 text-center transition-colors',
            dragActive
              ? 'border-primary bg-primary/10'
              : 'border-muted-foreground/25 hover:border-muted-foreground/50'
          )}
          onDragEnter={handleDragIn}
          onDragLeave={handleDragOut}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <div className="space-y-3">
            <div className="w-12 h-12 mx-auto bg-muted rounded-full flex items-center justify-center">
              <Camera className="w-6 h-6 text-muted-foreground" />
            </div>
            
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">
                Add a screenshot
              </p>
              <p className="text-xs text-muted-foreground">
                Help us understand the issue better with a visual
              </p>
            </div>

            <div className="flex flex-col sm:flex-row gap-2 items-center justify-center">
              {canCapture && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleCapture}
                  disabled={isCapturing}
                  className="min-w-[120px]"
                >
                  <Camera className="w-4 h-4 mr-2" />
                  {isCapturing ? 'Capturing...' : 'Capture Page'}
                </Button>
              )}

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                className="min-w-[120px]"
              >
                <Upload className="w-4 h-4 mr-2" />
                Upload Image
              </Button>
            </div>

            <p className="text-xs text-muted-foreground">
              Drop an image file here, or click to browse
            </p>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileInputChange}
            className="hidden"
            aria-label="Upload screenshot"
          />
        </div>
      ) : (
        <div className="space-y-3">
          {/* Screenshot Preview */}
          <div className="relative border rounded-lg overflow-hidden bg-muted">
            <div className="flex items-center justify-between p-2 bg-background border-b">
              <div className="flex items-center gap-2 text-sm">
                <Camera className="w-4 h-4 text-muted-foreground" />
                <span className="font-medium truncate max-w-[200px]">
                  {screenshot.name}
                </span>
                <span className="text-muted-foreground text-xs">
                  ({(screenshot.size / 1024).toFixed(1)}KB)
                </span>
              </div>
              
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowPreview(!showPreview)}
                  title={showPreview ? 'Hide preview' : 'Show preview'}
                >
                  {showPreview ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </Button>
                
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={downloadScreenshot}
                  title="Download screenshot"
                >
                  <Download className="w-4 h-4" />
                </Button>
                
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onScreenshotChange(null)}
                  title="Remove screenshot"
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
            </div>

            {showPreview && previewUrl && (
              <div className="p-2">
                <img
                  src={previewUrl}
                  alt="Screenshot preview"
                  className="w-full h-auto max-h-64 object-contain rounded border"
                />
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            {canCapture && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleCapture}
                disabled={isCapturing}
              >
                <Camera className="w-4 h-4 mr-2" />
                {isCapturing ? 'Capturing...' : 'Retake'}
              </Button>
            )}

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="w-4 h-4 mr-2" />
              Replace
            </Button>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileInputChange}
            className="hidden"
            aria-label="Replace screenshot"
          />
        </div>
      )}

      {/* Help text */}
      <div className="text-xs text-muted-foreground space-y-1">
        <p>
          Screenshots help us understand and fix issues faster.
        </p>
        {category === 'bug-report' && (
          <p>💡 Try to show the error or unexpected behavior clearly</p>
        )}
        {category === 'ui-ux' && (
          <p>💡 Highlight the UI element or design issue</p>
        )}
        {category === 'performance' && (
          <p>💡 Include browser dev tools or performance indicators if possible</p>
        )}
      </div>
    </div>
  )
}