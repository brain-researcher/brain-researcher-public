'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { X, ArrowRight, ArrowLeft, SkipForward } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import { useHelp, TourStep } from '../../hooks/use-help'
import { createPortal } from 'react-dom'

interface TourTooltipProps {
  step: TourStep
  currentStepIndex: number
  totalSteps: number
  onNext: () => void
  onPrev: () => void
  onSkip: () => void
  onComplete: () => void
  tourName: string
}

function TourTooltip({
  step,
  currentStepIndex,
  totalSteps,
  onNext,
  onPrev,
  onComplete,
  onSkip,
  tourName,
}: TourTooltipProps) {
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const [isVisible, setIsVisible] = useState(false)

  const calculatePosition = useCallback(() => {
    if (step.target === 'body') {
      // Center of screen for welcome steps
      setPosition({
        top: window.innerHeight / 2 - 150,
        left: window.innerWidth / 2 - 200,
      })
      setIsVisible(true)
      return
    }

    const element = document.querySelector(step.target)
    if (!element) {
      console.warn(`Tour step target not found: ${step.target}`)
      setIsVisible(false)
      return
    }

    const rect = element.getBoundingClientRect()
    const tooltipWidth = 400
    const tooltipHeight = 200
    const padding = 20

    let top = rect.bottom + padding
    let left = rect.left

    // Adjust for placement preference
    switch (step.placement) {
      case 'top':
        top = rect.top - tooltipHeight - padding
        break
      case 'bottom':
        top = rect.bottom + padding
        break
      case 'left':
        top = rect.top
        left = rect.left - tooltipWidth - padding
        break
      case 'right':
        top = rect.top
        left = rect.right + padding
        break
      case 'center':
        top = window.innerHeight / 2 - tooltipHeight / 2
        left = window.innerWidth / 2 - tooltipWidth / 2
        break
    }

    // Ensure tooltip stays within viewport
    if (left + tooltipWidth > window.innerWidth) {
      left = window.innerWidth - tooltipWidth - padding
    }
    if (left < padding) {
      left = padding
    }
    if (top + tooltipHeight > window.innerHeight) {
      top = window.innerHeight - tooltipHeight - padding
    }
    if (top < padding) {
      top = padding
    }

    setPosition({ top, left })
    setIsVisible(true)

    // Scroll element into view if needed
    element.scrollIntoView({ 
      behavior: 'smooth', 
      block: 'center',
      inline: 'center'
    })

    // Add highlight effect
    element.classList.add('tour-highlight')
    return () => element.classList.remove('tour-highlight')
  }, [step.target, step.placement])

  useEffect(() => {
    calculatePosition()
    const handleResize = () => calculatePosition()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [calculatePosition])

  const isLastStep = currentStepIndex === totalSteps - 1
  const isFirstStep = currentStepIndex === 0

  if (!isVisible) return null

  return createPortal(
    <>
      {/* Overlay */}
      <div 
        className="fixed inset-0 bg-black/50 z-[9998]"
        style={{ pointerEvents: step.target === 'body' ? 'auto' : 'none' }}
      />
      
      {/* Spotlight effect for specific elements */}
      {step.target !== 'body' && (
        <style jsx>{`
          .tour-highlight {
            position: relative !important;
            z-index: 9999 !important;
            box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.5), 
                        0 0 0 9999px rgba(0, 0, 0, 0.5) !important;
          }
        `}</style>
      )}

      {/* Tooltip */}
      <Card 
        className="fixed z-[9999] w-[400px] shadow-2xl border-2 border-blue-200"
        style={{
          top: position.top,
          left: position.left,
        }}
      >
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="text-lg">{step.title || tourName}</CardTitle>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="outline">
                  Step {currentStepIndex + 1} of {totalSteps}
                </Badge>
                <div className="text-xs text-muted-foreground">
                  {tourName}
                </div>
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={onSkip}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        
        <CardContent className="space-y-4">
          <p className="text-sm leading-relaxed">{step.content}</p>
          
          {/* Progress indicator */}
          <div className="w-full bg-muted rounded-full h-1">
            <div 
              className="bg-blue-500 h-1 rounded-full transition-all duration-300"
              style={{ width: `${((currentStepIndex + 1) / totalSteps) * 100}%` }}
            />
          </div>
          
          {/* Navigation buttons */}
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {!isFirstStep && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onPrev}
                  className="flex items-center gap-1"
                >
                  <ArrowLeft className="h-3 w-3" />
                  Previous
                </Button>
              )}
            </div>
            
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={onSkip}
                className="flex items-center gap-1"
              >
                <SkipForward className="h-3 w-3" />
                Skip Tour
              </Button>
              
              <Button
                size="sm"
                onClick={isLastStep ? onComplete : onNext}
                className="flex items-center gap-1"
              >
                {isLastStep ? 'Complete' : 'Next'}
                {!isLastStep && <ArrowRight className="h-3 w-3" />}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </>,
    document.body
  )
}

export function InteractiveTour() {
  const { currentTour, tourRunning, tours, completeTour, stopTour } = useHelp()
  const [currentStepIndex, setCurrentStepIndex] = useState(0)

  const tour = currentTour ? tours[currentTour] : null
  const currentStep = tour?.steps[currentStepIndex]

  // Reset step index when tour changes
  useEffect(() => {
    if (currentTour) {
      setCurrentStepIndex(0)
    }
  }, [currentTour])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Remove any highlight classes when component unmounts
      document.querySelectorAll('.tour-highlight').forEach(el => {
        el.classList.remove('tour-highlight')
      })
    }
  }, [])

  const handleNext = () => {
    if (!tour) return
    
    if (currentStepIndex < tour.steps.length - 1) {
      setCurrentStepIndex(prev => prev + 1)
    } else {
      handleComplete()
    }
  }

  const handlePrev = () => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex(prev => prev - 1)
    }
  }

  const handleComplete = () => {
    if (currentTour) {
      completeTour(currentTour)
    }
    cleanup()
  }

  const handleSkip = () => {
    stopTour()
    cleanup()
  }

  const cleanup = () => {
    // Remove highlight classes
    document.querySelectorAll('.tour-highlight').forEach(el => {
      el.classList.remove('tour-highlight')
    })
    setCurrentStepIndex(0)
  }

  // Handle keyboard navigation
  useEffect(() => {
    if (!tourRunning) return

    const handleKeyDown = (event: KeyboardEvent) => {
      switch (event.key) {
        case 'Escape':
          handleSkip()
          break
        case 'ArrowRight':
        case 'Enter':
          event.preventDefault()
          handleNext()
          break
        case 'ArrowLeft':
          event.preventDefault()
          handlePrev()
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [tourRunning, currentStepIndex, tour])

  if (!tourRunning || !tour || !currentStep) {
    return null
  }

  return (
    <TourTooltip
      step={currentStep}
      currentStepIndex={currentStepIndex}
      totalSteps={tour.steps.length}
      onNext={handleNext}
      onPrev={handlePrev}
      onComplete={handleComplete}
      onSkip={handleSkip}
      tourName={tour.name}
    />
  )
}