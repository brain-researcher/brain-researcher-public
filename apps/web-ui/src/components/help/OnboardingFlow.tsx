'use client'

import React, { useEffect, useState } from 'react'
import { CheckCircle, Circle, ArrowRight, Sparkles, Target, Zap, Book, X } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import { Progress } from '../ui/progress'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../ui/dialog'
import { useHelp } from '../../hooks/use-help'

interface OnboardingStep {
  id: string
  title: string
  description: string
  icon: React.ReactNode
  action: string
  tourId?: string
  completionCriteria: string
  estimatedTime: number
}

const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to Brain Researcher',
    description: 'Take a quick tour to learn the basics of the platform and discover what you can accomplish.',
    icon: <Sparkles className="h-5 w-5" />,
    action: 'Take Welcome Tour',
    tourId: 'welcome',
    completionCriteria: 'Complete the welcome tour',
    estimatedTime: 5,
  },
  {
    id: 'explore-data',
    title: 'Explore Datasets',
    description: 'Browse the dataset catalog to understand the types of neuroimaging data available.',
    icon: <Target className="h-5 w-5" />,
    action: 'Browse Datasets',
    completionCriteria: 'View at least 3 datasets',
    estimatedTime: 8,
  },
  {
    id: 'first-analysis',
    title: 'Run Your First Analysis',
    description: 'Try a simple analysis using a dataset from the catalog to see the platform in action.',
    icon: <Zap className="h-5 w-5" />,
    action: 'Start Analysis Tour',
    tourId: 'data-analysis',
    completionCriteria: 'Complete an analysis workflow',
    estimatedTime: 12,
  },
  {
    id: 'knowledge-graph',
    title: 'Discover the Knowledge Graph',
    description: 'Explore how research findings connect and build upon each other.',
    icon: <Book className="h-5 w-5" />,
    action: 'Explore Knowledge Graph',
    tourId: 'knowledge-graph',
    completionCriteria: 'Interact with the knowledge graph',
    estimatedTime: 6,
  },
  {
    id: 'customize-workspace',
    title: 'Customize Your Workspace',
    description: 'Set up your preferences and customize the interface to match your workflow.',
    icon: <CheckCircle className="h-5 w-5" />,
    action: 'Customize Settings',
    completionCriteria: 'Update at least 2 settings',
    estimatedTime: 4,
  },
]

interface OnboardingStepCardProps {
  step: OnboardingStep
  stepNumber: number
  isCompleted: boolean
  isCurrent: boolean
  onStart: (stepId: string) => void
}

function OnboardingStepCard({
  step,
  stepNumber,
  isCompleted,
  isCurrent,
  onStart
}: OnboardingStepCardProps) {
  return (
    <Card className={`transition-all duration-200 ${isCurrent ? 'ring-2 ring-blue-500 border-blue-200' :
        isCompleted ? 'border-green-200 bg-green-50/30' :
          'border-muted'
      }`}>
      <CardContent className="p-4">
        <div className="flex items-start gap-4">
          <div className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center ${isCompleted ? 'bg-green-100 text-green-600' :
              isCurrent ? 'bg-blue-100 text-blue-600' :
                'bg-muted text-muted-foreground'
            }`}>
            {isCompleted ? (
              <CheckCircle className="h-5 w-5" />
            ) : (
              <div className="flex items-center justify-center">
                {step.icon}
              </div>
            )}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h3 className="font-medium">{step.title}</h3>
              <Badge variant="outline" className="text-xs">
                Step {stepNumber}
              </Badge>
              <Badge variant="outline" className="text-xs">
                {step.estimatedTime} min
              </Badge>
            </div>

            <p className="text-sm text-muted-foreground mb-3">
              {step.description}
            </p>

            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {step.completionCriteria}
              </span>

              {isCompleted ? (
                <Badge variant="default" className="bg-green-100 text-green-700">
                  ✓ Completed
                </Badge>
              ) : (
                <Button
                  size="sm"
                  variant={isCurrent ? "default" : "outline"}
                  onClick={() => onStart(step.id)}
                  className="flex items-center gap-1"
                >
                  {step.action}
                  <ArrowRight className="h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

interface OnboardingProgressProps {
  currentStep: number
  totalSteps: number
  completedSteps: string[]
}

function OnboardingProgress({ currentStep, totalSteps, completedSteps }: OnboardingProgressProps) {
  const progressPercentage = (completedSteps.length / totalSteps) * 100

  return (
    <Card className="mb-6">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">Your Onboarding Progress</CardTitle>
            <CardDescription>
              Complete these steps to get the most out of Brain Researcher
            </CardDescription>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-blue-600">
              {completedSteps.length}/{totalSteps}
            </div>
            <div className="text-xs text-muted-foreground">
              steps completed
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span>Overall Progress</span>
            <span>{Math.round(progressPercentage)}%</span>
          </div>
          <Progress value={progressPercentage} className="h-2" />
        </div>

        {progressPercentage === 100 && (
          <div className="mt-4 p-3 bg-green-100 border border-green-200 rounded-lg">
            <div className="flex items-center gap-2 text-green-700">
              <CheckCircle className="h-4 w-4" />
              <span className="font-medium">Congratulations!</span>
            </div>
            <p className="text-sm text-green-600 mt-1">
              You've completed the onboarding process. You're ready to start your neuroimaging research!
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function OnboardingFlow() {
  const {
    onboardingProgress,
    updateOnboardingProgress,
    startTour,
    resetOnboarding,
  } = useHelp()

  const [showOnboarding, setShowOnboarding] = useState(false)
  const [dismissedPermanently, setDismissedPermanently] = useState(false)

  // Show onboarding dialog for new users
  useEffect(() => {
    if (typeof window !== 'undefined' && window.location.pathname === '/studio') {
      return
    }
    const hasSeenOnboarding = localStorage.getItem('onboarding-dismissed')
    const isNewUser = !onboardingProgress.isCompleted && onboardingProgress.currentStep === 0

    if (!hasSeenOnboarding && isNewUser && !dismissedPermanently) {
      const timer = setTimeout(() => {
        setShowOnboarding(true)
      }, 2000) // Show after 2 seconds

      return () => clearTimeout(timer)
    }
  }, [onboardingProgress, dismissedPermanently])

  const handleStepAction = (stepId: string) => {
    const step = ONBOARDING_STEPS.find(s => s.id === stepId)
    if (!step) return

    // Mark step as started
    const stepIndex = ONBOARDING_STEPS.findIndex(s => s.id === stepId)
    updateOnboardingProgress(Math.max(stepIndex, onboardingProgress.currentStep), stepId)

    if (step.tourId) {
      // Start the associated tour
      startTour(step.tourId)
    } else {
      // Handle other actions
      switch (stepId) {
        case 'explore-data':
          // Navigate to datasets page
          window.location.href = '/datasets'
          break
        case 'customize-workspace':
          // Navigate to settings
          window.location.href = '/settings'
          break
      }
    }

    // Close onboarding dialog
    setShowOnboarding(false)
  }

  const handleDismiss = (permanent = false) => {
    setShowOnboarding(false)
    if (permanent) {
      localStorage.setItem('onboarding-dismissed', 'true')
      setDismissedPermanently(true)
    }
  }

  const getCurrentStepIndex = () => {
    return Math.min(onboardingProgress.currentStep, ONBOARDING_STEPS.length - 1)
  }

  const getStepStatus = (stepId: string, index: number) => {
    const isCompleted = onboardingProgress.completedSteps.includes(stepId)
    const isCurrent = index === getCurrentStepIndex() && !onboardingProgress.isCompleted
    return { isCompleted, isCurrent }
  }

  // Don't render if permanently dismissed
  if (dismissedPermanently) return null

  return (
    <>
      {/* Welcome Dialog for New Users */}
      <Dialog open={showOnboarding} onOpenChange={(open) => {
        if (!open) {
          handleDismiss(false)  // Don't dismiss permanently when using close button
        }
      }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader className="sr-only">
            <DialogTitle>Welcome to Brain Researcher</DialogTitle>
            <DialogDescription>Guided onboarding introduction and next steps.</DialogDescription>
          </DialogHeader>
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full">
              <Sparkles className="h-8 w-8 text-blue-600" />
            </div>

            <div>
              <h2 className="text-2xl font-bold mb-2">Welcome to Brain Researcher!</h2>
              <p className="text-muted-foreground">
                We're excited to have you here. Let's take a few minutes to get you started
                with a personalized onboarding experience.
              </p>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <h3 className="font-medium text-blue-900 mb-2">What you'll learn:</h3>
              <ul className="text-sm text-blue-700 space-y-1 text-left">
                <li>• Platform navigation and core features</li>
                <li>• How to explore and analyze neuroimaging data</li>
                <li>• Using the knowledge graph for research insights</li>
                <li>• Customizing your workspace</li>
              </ul>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                onClick={() => handleDismiss(true)}
                className="flex-1"
              >
                Skip for now
              </Button>
              <Button
                onClick={() => handleStepAction('welcome')}
                className="flex-1"
              >
                Start Onboarding
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>

            <p className="text-xs text-muted-foreground">
              You can always access help and tours from the help button (F1)
            </p>
          </div>
        </DialogContent>
      </Dialog>

      {/* Onboarding Progress for Existing Users */}
      {!onboardingProgress.isCompleted && onboardingProgress.currentStep > 0 && (
        <div className="fixed bottom-4 right-4 w-80 z-50">
          <Card className="shadow-lg border-2 border-blue-200">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">Continue Onboarding</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDismiss()}
                  className="h-6 w-6 p-0"
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </CardHeader>

            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span>Progress</span>
                <span>
                  {onboardingProgress.completedSteps.length}/{ONBOARDING_STEPS.length}
                </span>
              </div>

              <Progress
                value={(onboardingProgress.completedSteps.length / ONBOARDING_STEPS.length) * 100}
                className="h-1"
              />

              <div className="text-xs text-muted-foreground">
                Next: {ONBOARDING_STEPS[getCurrentStepIndex()]?.title}
              </div>

              <Button
                size="sm"
                onClick={() => handleStepAction(ONBOARDING_STEPS[getCurrentStepIndex()]?.id)}
                className="w-full"
              >
                Continue
                <ArrowRight className="ml-2 h-3 w-3" />
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  )
}

// Onboarding steps component for the help system
export function OnboardingSteps() {
  const { onboardingProgress, resetOnboarding } = useHelp()

  const handleStepAction = (stepId: string) => {
    const step = ONBOARDING_STEPS.find(s => s.id === stepId)
    if (!step) return

    if (step.tourId) {
      window.location.hash = `tour-${step.tourId}`
    } else {
      // Handle other navigation
      switch (stepId) {
        case 'explore-data':
          window.location.href = '/datasets'
          break
        case 'customize-workspace':
          window.location.href = '/settings'
          break
      }
    }
  }

  return (
    <div className="space-y-6">
      <OnboardingProgress
        currentStep={onboardingProgress.currentStep}
        totalSteps={ONBOARDING_STEPS.length}
        completedSteps={onboardingProgress.completedSteps}
      />

      <div className="space-y-4">
        {ONBOARDING_STEPS.map((step, index) => {
          const { isCompleted, isCurrent } = getStepStatus(step.id, index)

          return (
            <OnboardingStepCard
              key={step.id}
              step={step}
              stepNumber={index + 1}
              isCompleted={isCompleted}
              isCurrent={isCurrent}
              onStart={handleStepAction}
            />
          )
        })}
      </div>

      {onboardingProgress.currentStep > 0 && (
        <div className="text-center pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={resetOnboarding}
          >
            Restart Onboarding
          </Button>
        </div>
      )}
    </div>
  )

  function getStepStatus(stepId: string, index: number) {
    const isCompleted = onboardingProgress.completedSteps.includes(stepId)
    const isCurrent = index === Math.min(onboardingProgress.currentStep, ONBOARDING_STEPS.length - 1) && !onboardingProgress.isCompleted
    return { isCompleted, isCurrent }
  }
}
