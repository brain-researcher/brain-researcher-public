'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { HelpCircle, X, ExternalLink } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import { useHelp } from '../../hooks/use-help'
import { createPortal } from 'react-dom'
import { HELP_TOOLTIPS, type HelpTooltip } from '@/lib/help-content'

type TooltipContent = HelpTooltip

interface ContextualTooltipProps {
  content: TooltipContent
  targetElement: Element
  onClose: () => void
  onStartTour?: (tourId: string) => void
}

function ContextualTooltip({ content, targetElement, onClose, onStartTour }: ContextualTooltipProps) {
  const [position, setPosition] = useState({ top: 0, left: 0 })

  useEffect(() => {
    const updatePosition = () => {
      const rect = targetElement.getBoundingClientRect()
      const tooltipWidth = 320
      const tooltipHeight = 200
      const padding = 12

      let top = rect.bottom + padding
      let left = rect.left

      // Adjust if tooltip would go off screen
      if (left + tooltipWidth > window.innerWidth) {
        left = window.innerWidth - tooltipWidth - padding
      }
      if (left < padding) {
        left = padding
      }
      if (top + tooltipHeight > window.innerHeight) {
        top = rect.top - tooltipHeight - padding
      }

      setPosition({ top, left })
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    return () => window.removeEventListener('resize', updatePosition)
  }, [targetElement])

  const getCategoryColor = (category: TooltipContent['category']) => {
    switch (category) {
      case 'feature': return 'bg-blue-100 text-blue-800'
      case 'concept': return 'bg-purple-100 text-purple-800'
      case 'shortcut': return 'bg-green-100 text-green-800'
      case 'workflow': return 'bg-orange-100 text-orange-800'
      default: return 'bg-gray-100 text-gray-800'
    }
  }

  return createPortal(
    <Card
      className="fixed z-[9999] w-80 shadow-lg border-2 border-blue-100"
      style={{
        top: position.top,
        left: position.left,
      }}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <CardTitle className="text-sm font-medium">{content.title}</CardTitle>
              <Badge variant="secondary" className={getCategoryColor(content.category)}>
                {content.category}
              </Badge>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      </CardHeader>
      
      <CardContent className="pt-0 space-y-3">
        <CardDescription className="text-xs leading-relaxed">
          {content.description}
        </CardDescription>
        
        <div className="flex flex-wrap gap-2">
          {content.relatedTourId && onStartTour && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                onStartTour(content.relatedTourId!)
                onClose()
              }}
              className="text-xs"
            >
              Take Tour
            </Button>
          )}
          
          {content.learnMoreUrl && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => window.open(content.learnMoreUrl, '_blank')}
              className="text-xs"
            >
              <ExternalLink className="h-3 w-3 mr-1" />
              Learn More
            </Button>
          )}
          
          {content.videoUrl && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => window.open(content.videoUrl, '_blank')}
              className="text-xs"
            >
              Watch Video
            </Button>
          )}
        </div>
      </CardContent>
    </Card>,
    document.body
  )
}

export function ContextualHelp() {
  const { showTooltips, startTour } = useHelp()
  const [activeTooltip, setActiveTooltip] = useState<{ content: TooltipContent; element: Element } | null>(null)
  const [hoverTimeout, setHoverTimeout] = useState<NodeJS.Timeout | null>(null)

  const showTooltip = useCallback((helpId: string, element: Element) => {
    if (!showTooltips) return
    
    const content = HELP_TOOLTIPS[helpId]
    if (content) {
      setActiveTooltip({ content, element })
    }
  }, [showTooltips])

  const hideTooltip = useCallback(() => {
    setActiveTooltip(null)
    if (hoverTimeout) {
      clearTimeout(hoverTimeout)
      setHoverTimeout(null)
    }
  }, [hoverTimeout])

  // Set up global event listeners
  useEffect(() => {
    if (!showTooltips) return

    const handleMouseEnter = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      const helpElement = target.closest('[data-help]')

      if (helpElement) {
        const helpId = helpElement.getAttribute('data-help')
        if (helpId && HELP_TOOLTIPS[helpId]) {
          // Clear any existing timeout
          if (hoverTimeout) {
            clearTimeout(hoverTimeout)
          }
          
          // Set a delay before showing tooltip
          const timeout = setTimeout(() => {
            showTooltip(helpId, helpElement)
          }, 800) // 800ms delay
          
          setHoverTimeout(timeout)
        }
      }
    }

    const handleMouseLeave = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      const helpElement = target.closest('[data-help]')

      if (helpElement) {
        // Clear timeout if mouse leaves before tooltip shows
        if (hoverTimeout) {
          clearTimeout(hoverTimeout)
          setHoverTimeout(null)
        }
        
        // Hide tooltip after a short delay
        setTimeout(() => {
          const tooltipElement = document.querySelector('[data-contextual-tooltip]')
          if (!tooltipElement?.matches(':hover')) {
            hideTooltip()
          }
        }, 200)
      }
    }

    const handleClick = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      const tooltipElement = target.closest('[data-contextual-tooltip]')
      if (!tooltipElement) {
        hideTooltip()
      }
    }

    // Add help icons to elements with data-help attribute
    const addHelpIcons = () => {
      document.querySelectorAll('[data-help]:not([data-help-icon-added])').forEach(element => {
        const helpId = element.getAttribute('data-help')
        if (!helpId || !HELP_TOOLTIPS[helpId]) return

        // Don't add icon if element already has one
        if (element.querySelector('.help-icon')) return

        // Create help icon
        const helpIcon = document.createElement('span')
        helpIcon.className = 'help-icon inline-flex items-center justify-center w-4 h-4 ml-1 text-muted-foreground opacity-60 hover:opacity-100 cursor-help'
        helpIcon.innerHTML = '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>'
        
        // Position based on element type
        if (element.tagName === 'BUTTON' || element.tagName === 'A') {
          element.appendChild(helpIcon)
        } else {
          const htmlElement = element as HTMLElement
          htmlElement.style.position = 'relative'
          helpIcon.style.position = 'absolute'
          helpIcon.style.top = '2px'
          helpIcon.style.right = '2px'
          htmlElement.appendChild(helpIcon)
        }

        element.setAttribute('data-help-icon-added', 'true')
      })
    }

    // Initial setup
    addHelpIcons()

    // Listen for DOM changes to add help icons to new elements
    const observer = new MutationObserver(() => {
      addHelpIcons()
    })

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    })

    document.addEventListener('mouseenter', handleMouseEnter, true)
    document.addEventListener('mouseleave', handleMouseLeave, true)
    document.addEventListener('click', handleClick, true)

    return () => {
      observer.disconnect()
      document.removeEventListener('mouseenter', handleMouseEnter, true)
      document.removeEventListener('mouseleave', handleMouseLeave, true)
      document.removeEventListener('click', handleClick, true)
      if (hoverTimeout) {
        clearTimeout(hoverTimeout)
      }
    }
  }, [showTooltips, hoverTimeout, showTooltip, hideTooltip])

  if (!activeTooltip) return null

  return (
    <div data-contextual-tooltip>
      <ContextualTooltip
        content={activeTooltip.content}
        targetElement={activeTooltip.element}
        onClose={hideTooltip}
        onStartTour={startTour}
      />
    </div>
  )
}

// Utility component for adding help attributes to any element
interface HelpTriggerProps {
  helpId: string
  children: React.ReactNode
  className?: string
}

export function HelpTrigger({ helpId, children, className = '' }: HelpTriggerProps) {
  return (
    <div data-help={helpId} className={className}>
      {children}
    </div>
  )
}

// Export help content for use in other components
export { HELP_TOOLTIPS }
