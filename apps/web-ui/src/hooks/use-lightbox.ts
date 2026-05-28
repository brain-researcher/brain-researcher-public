'use client'

import { useState, useCallback, useEffect, useRef } from 'react'

interface UseLightboxOptions {
  enableNavigation?: boolean
  enableKeyboardShortcuts?: boolean
  autoPlay?: boolean
  autoPlayInterval?: number
}

export function useLightbox(options: UseLightboxOptions = {}) {
  const { 
    enableNavigation = true, 
    enableKeyboardShortcuts = true,
    autoPlay = false,
    autoPlayInterval = 5000
  } = options

  const [isOpen, setIsOpen] = useState(false)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [items, setItems] = useState<any[]>([])
  const [isAutoPlaying, setIsAutoPlaying] = useState(false)
  const controlsRef = useRef({
    close: () => {},
    previous: () => {},
    next: () => {},
    toggleAutoPlay: () => {},
    goToFirst: () => {},
    goToLast: () => {}
  })

  // Auto play functionality
  useEffect(() => {
    let interval: NodeJS.Timeout
    
    if (isOpen && autoPlay && isAutoPlaying && items.length > 1) {
      interval = setInterval(() => {
        setCurrentIndex(prev => (prev + 1) % items.length)
      }, autoPlayInterval)
    }
    
    return () => {
      if (interval) {
        clearInterval(interval)
      }
    }
  }, [isOpen, autoPlay, isAutoPlaying, items.length, autoPlayInterval])

  // Keyboard shortcuts
  useEffect(() => {
    if (!isOpen || !enableKeyboardShortcuts) return

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape':
          controlsRef.current.close()
          break
        case 'ArrowLeft':
          if (enableNavigation) {
            controlsRef.current.previous()
          }
          break
        case 'ArrowRight':
          if (enableNavigation) {
            controlsRef.current.next()
          }
          break
        case ' ':
          e.preventDefault()
          if (autoPlay) {
            controlsRef.current.toggleAutoPlay()
          }
          break
        case 'Home':
          controlsRef.current.goToFirst()
          break
        case 'End':
          controlsRef.current.goToLast()
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, enableKeyboardShortcuts, enableNavigation, autoPlay])

  const open = useCallback((itemsArray: any[], initialIndex = 0) => {
    setItems(itemsArray)
    setCurrentIndex(Math.max(0, Math.min(initialIndex, itemsArray.length - 1)))
    setIsOpen(true)
    
    if (autoPlay) {
      setIsAutoPlaying(true)
    }
  }, [autoPlay])

  const close = useCallback(() => {
    setIsOpen(false)
    setIsAutoPlaying(false)
    // Reset after animation completes
    setTimeout(() => {
      setCurrentIndex(0)
      setItems([])
    }, 300)
  }, [])

  const next = useCallback(() => {
    if (!enableNavigation || items.length <= 1) return
    setCurrentIndex(prev => (prev + 1) % items.length)
  }, [enableNavigation, items.length])

  const previous = useCallback(() => {
    if (!enableNavigation || items.length <= 1) return
    setCurrentIndex(prev => (prev - 1 + items.length) % items.length)
  }, [enableNavigation, items.length])

  const goTo = useCallback((index: number) => {
    if (index >= 0 && index < items.length) {
      setCurrentIndex(index)
    }
  }, [items.length])

  const goToFirst = useCallback(() => {
    setCurrentIndex(0)
  }, [])

  const goToLast = useCallback(() => {
    setCurrentIndex(items.length - 1)
  }, [items.length])

  const toggleAutoPlay = useCallback(() => {
    setIsAutoPlaying(prev => !prev)
  }, [])

  const hasNext = useCallback(() => {
    return currentIndex < items.length - 1
  }, [currentIndex, items.length])

  const hasPrevious = useCallback(() => {
    return currentIndex > 0
  }, [currentIndex])

  const getCurrentItem = useCallback(() => {
    return items[currentIndex] || null
  }, [items, currentIndex])

  const getProgress = useCallback(() => {
    if (items.length === 0) return 0
    return ((currentIndex + 1) / items.length) * 100
  }, [currentIndex, items.length])

  useEffect(() => {
    controlsRef.current = {
      close,
      previous,
      next,
      toggleAutoPlay,
      goToFirst,
      goToLast
    }
  }, [close, previous, next, toggleAutoPlay, goToFirst, goToLast])

  return {
    isOpen,
    currentIndex,
    items,
    isAutoPlaying,
    open,
    close,
    next,
    previous,
    goTo,
    goToFirst,
    goToLast,
    toggleAutoPlay,
    hasNext,
    hasPrevious,
    getCurrentItem,
    getProgress
  }
}
