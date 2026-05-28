'use client'

import { useState, useCallback, useRef } from 'react'
import { ScreenshotOptions } from '@/types/feedback'

export function useScreenshot() {
  const [isCapturing, setIsCapturing] = useState(false)
  const [lastScreenshot, setLastScreenshot] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const captureScreenshot = useCallback(async (options: ScreenshotOptions = {}): Promise<File | null> => {
    const {
      quality = 0.8,
      includeFullPage = false,
      excludeSelectors = [],
      maskSensitiveData = true
    } = options

    setIsCapturing(true)
    setError(null)

    try {
      // Check if html-to-image is available
      const { toPng, toCanvas } = await import('html-to-image')

      // Get the element to capture
      const element = includeFullPage 
        ? document.documentElement 
        : document.body

      // Prepare options for html-to-image
      const captureOptions = {
        quality,
        pixelRatio: window.devicePixelRatio || 1,
        backgroundColor: '#ffffff',
        filter: (node: Element) => {
          // Exclude elements based on selectors
          if (excludeSelectors.some(selector => node.matches?.(selector))) {
            return false
          }

          // Mask sensitive data if enabled
          if (maskSensitiveData) {
            const sensitiveSelectors = [
              '[data-sensitive]',
              '.sensitive',
              'input[type="password"]',
              'input[type="email"]',
              '.feedback-dialog', // Don't capture the feedback dialog itself
              '.feedback-trigger'
            ]

            if (sensitiveSelectors.some(selector => node.matches?.(selector))) {
              return false
            }
          }

          return true
        },
        style: {
          // Hide feedback components during capture
          '.feedback-dialog': { display: 'none' },
          '.feedback-trigger': { display: 'none' }
        }
      }

      // Capture the screenshot
      const dataUrl = await toPng(element, captureOptions)
      
      // Convert data URL to File
      const response = await fetch(dataUrl)
      const blob = await response.blob()
      const file = new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' })

      setLastScreenshot(file)
      return file

    } catch (err) {
      console.error('Screenshot capture failed:', err)
      const errorMessage = err instanceof Error ? err.message : 'Failed to capture screenshot'
      setError(errorMessage)
      return null
    } finally {
      setIsCapturing(false)
    }
  }, [])

  const captureElement = useCallback(async (
    selector: string, 
    options: ScreenshotOptions = {}
  ): Promise<File | null> => {
    const element = document.querySelector(selector)
    if (!element) {
      setError(`Element with selector "${selector}" not found`)
      return null
    }

    setIsCapturing(true)
    setError(null)

    try {
      const { toPng } = await import('html-to-image')
      
      const dataUrl = await toPng(element as HTMLElement, {
        quality: options.quality || 0.8,
        pixelRatio: window.devicePixelRatio || 1,
        backgroundColor: '#ffffff'
      })

      const response = await fetch(dataUrl)
      const blob = await response.blob()
      const file = new File([blob], `element-screenshot-${Date.now()}.png`, { type: 'image/png' })

      setLastScreenshot(file)
      return file

    } catch (err) {
      console.error('Element screenshot capture failed:', err)
      const errorMessage = err instanceof Error ? err.message : 'Failed to capture element screenshot'
      setError(errorMessage)
      return null
    } finally {
      setIsCapturing(false)
    }
  }, [])

  const clearScreenshot = useCallback(() => {
    setLastScreenshot(null)
    setError(null)
  }, [])

  // Convert File to preview URL for display
  const getPreviewUrl = useCallback((file: File | null): string | null => {
    if (!file) return null
    return URL.createObjectURL(file)
  }, [])

  return {
    isCapturing,
    lastScreenshot,
    error,
    captureScreenshot,
    captureElement,
    clearScreenshot,
    getPreviewUrl,
    canCapture: typeof window !== 'undefined' && 'toBlob' in HTMLCanvasElement.prototype
  }
}