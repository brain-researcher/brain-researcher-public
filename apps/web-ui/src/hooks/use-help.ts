import { useState, useCallback, useEffect, useMemo } from 'react'
import { useLocalStorage } from './use-local-storage'
import { HELP_TOOLTIPS } from '@/lib/help-content'

export interface TourStep {
  target: string
  content: string
  title?: string
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'center'
  disableBeacon?: boolean
  styles?: {
    options?: {
      primaryColor?: string
      backgroundColor?: string
      textColor?: string
      overlayColor?: string
    }
  }
}

export interface Tour {
  id: string
  name: string
  description: string
  steps: TourStep[]
  category: string
  estimatedTime: number
}

export interface OnboardingProgress {
  currentStep: number
  completedSteps: string[]
  isCompleted: boolean
  startedAt?: Date
  completedAt?: Date
}

export interface HelpContent {
  id: string
  title: string
  content: string
  category: string
  tags: string[]
  type: 'article' | 'video' | 'tooltip' | 'tour' | 'faq'
  relevanceScore: number
  searchTerms: string[]
  videoUrl?: string
  url?: string
  lastUpdated: Date
  readTime?: number
}

interface HelpState {
  isHelpOpen: boolean
  currentTour: string | null
  tourRunning: boolean
  showTooltips: boolean
  onboardingProgress: OnboardingProgress
  tourCompletions: Record<string, boolean>
  helpAnalytics: {
    searchQueries: string[]
    viewedContent: string[]
    completedTours: string[]
  }
}

const defaultOnboardingProgress: OnboardingProgress = {
  currentStep: 0,
  completedSteps: [],
  isCompleted: false,
}

const defaultHelpState: HelpState = {
  isHelpOpen: false,
  currentTour: null,
  tourRunning: false,
  showTooltips: true,
  onboardingProgress: defaultOnboardingProgress,
  tourCompletions: {},
  helpAnalytics: {
    searchQueries: [],
    viewedContent: [],
    completedTours: [],
  },
}

const HELP_SEED_ENABLED = process.env.NEXT_PUBLIC_ENABLE_HELP_SEED === '1'

// Define available tours
export const TOURS: Record<string, Tour> = HELP_SEED_ENABLED ? {
  'welcome': {
    id: 'welcome',
    name: 'Welcome to Brain Researcher',
    description: 'Get started with the platform basics',
    category: 'onboarding',
    estimatedTime: 5,
    steps: [
      {
        target: 'body',
        content: 'Welcome to Brain Researcher! Let\'s take a quick tour to get you started.',
        title: 'Welcome!',
        placement: 'center',
        disableBeacon: true,
      },
      {
        target: '[data-tour="navigation"]',
        content: 'This is your main navigation. Access different features from here.',
        title: 'Navigation',
        placement: 'bottom',
      },
      {
        target: '[data-tour="search"]',
        content: 'Use the search to find datasets, analyses, and research papers.',
        title: 'Search',
        placement: 'bottom',
      },
      {
        target: '[data-tour="chat"]',
        content: 'The chat interface lets you interact with your data using natural language.',
        title: 'Chat Interface',
        placement: 'left',
      },
      {
        target: '[data-tour="help-button"]',
        content: 'Access help, tutorials, and documentation anytime from here. Press F1 for quick help!',
        title: 'Help & Support',
        placement: 'bottom',
      },
    ],
  },
  'data-analysis': {
    id: 'data-analysis',
    name: 'Data Analysis Workflow',
    description: 'Learn how to analyze neuroimaging data',
    category: 'analysis',
    estimatedTime: 8,
    steps: [
      {
        target: '[data-tour="upload-data"]',
        content: 'Start by uploading your neuroimaging data or selecting from available datasets.',
        title: 'Upload Data',
        placement: 'right',
      },
      {
        target: '[data-tour="analysis-tools"]',
        content: 'Choose from various analysis tools and methods.',
        title: 'Analysis Tools',
        placement: 'top',
      },
      {
        target: '[data-tour="pipeline"]',
        content: 'Build and customize your analysis pipeline.',
        title: 'Analysis Pipeline',
        placement: 'left',
      },
      {
        target: '[data-tour="results"]',
        content: 'View and interpret your analysis results.',
        title: 'Results',
        placement: 'top',
      },
    ],
  },
  'knowledge-graph': {
    id: 'knowledge-graph',
    name: 'Knowledge Graph Explorer',
    description: 'Explore connected research data and findings',
    category: 'exploration',
    estimatedTime: 6,
    steps: [
      {
        target: '[data-tour="kg-viewer"]',
        content: 'The knowledge graph shows connections between research findings, brain regions, and studies.',
        title: 'Graph Visualization',
        placement: 'top',
      },
      {
        target: '[data-tour="kg-search"]',
        content: 'Search for specific brain regions, studies, or concepts.',
        title: 'Graph Search',
        placement: 'bottom',
      },
      {
        target: '[data-tour="kg-filters"]',
        content: 'Filter the graph by study type, brain region, or other criteria.',
        title: 'Filters',
        placement: 'right',
      },
    ],
  },
} : {}

const buildHelpIndex = (): HelpContent[] => {
  const tooltipEntries: HelpContent[] = Object.values(HELP_TOOLTIPS).map((tooltip) => ({
    id: `tooltip-${tooltip.id}`,
    title: tooltip.title,
    content: tooltip.description,
    category: tooltip.category,
    tags: [tooltip.category],
    type: 'tooltip',
    relevanceScore: 0,
    searchTerms: [
      tooltip.title,
      tooltip.description,
      tooltip.category,
      tooltip.relatedTourId ?? '',
    ]
      .join(' ')
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean),
    videoUrl: tooltip.videoUrl,
    url: tooltip.learnMoreUrl,
    lastUpdated: new Date(),
  }))

  const tourEntries: HelpContent[] = Object.values(TOURS).map((tour) => {
    const stepText = tour.steps.map((step) => `${step.title ?? ''} ${step.content}`).join(' ')
    const searchTerms = `${tour.name} ${tour.description} ${tour.category} ${stepText}`
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)

    return {
      id: `tour-${tour.id}`,
      title: tour.name,
      content: tour.description,
      category: tour.category,
      tags: [tour.category],
      type: 'tour',
      relevanceScore: 0,
      searchTerms,
      lastUpdated: new Date(),
      readTime: tour.estimatedTime,
    }
  })

  return [...tooltipEntries, ...tourEntries]
}

export function useHelp() {
  const [helpState, setHelpState] = useLocalStorage<HelpState>('help-state', defaultHelpState)
  const [searchResults, setSearchResults] = useState<HelpContent[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const helpIndex = useMemo(() => buildHelpIndex(), [])

  // Toggle help panel
  const toggleHelp = useCallback(() => {
    setHelpState(prev => ({ ...prev, isHelpOpen: !prev.isHelpOpen }))
  }, [setHelpState])

  // Start a tour
  const startTour = useCallback((tourId: string) => {
    const tour = TOURS[tourId]
    if (!tour) return

    setHelpState(prev => ({
      ...prev,
      currentTour: tourId,
      tourRunning: true,
    }))

    // Track tour start
    trackHelpEvent('tour_started', { tourId, tourName: tour.name })
  }, [setHelpState])

  // Complete a tour
  const completeTour = useCallback((tourId: string) => {
    setHelpState(prev => ({
      ...prev,
      currentTour: null,
      tourRunning: false,
      tourCompletions: { ...prev.tourCompletions, [tourId]: true },
      helpAnalytics: {
        ...prev.helpAnalytics,
        completedTours: [...prev.helpAnalytics.completedTours, tourId],
      },
    }))

    // Track tour completion
    trackHelpEvent('tour_completed', { tourId })
  }, [setHelpState])

  // Skip/stop tour
  const stopTour = useCallback(() => {
    setHelpState(prev => ({
      ...prev,
      currentTour: null,
      tourRunning: false,
    }))
  }, [setHelpState])

  // Toggle tooltips
  const toggleTooltips = useCallback(() => {
    setHelpState(prev => ({ ...prev, showTooltips: !prev.showTooltips }))
  }, [setHelpState])

  // Update onboarding progress
  const updateOnboardingProgress = useCallback((step: number, stepId?: string) => {
    setHelpState(prev => ({
      ...prev,
      onboardingProgress: {
        ...prev.onboardingProgress,
        currentStep: step,
        completedSteps: stepId
          ? Array.from(new Set([...prev.onboardingProgress.completedSteps, stepId]))
          : prev.onboardingProgress.completedSteps,
        isCompleted: step >= 5, // Assume 5 steps in onboarding
        completedAt: step >= 5 ? new Date() : prev.onboardingProgress.completedAt,
      },
    }))
  }, [setHelpState])

  // Search help content
  const searchHelp = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }

    setIsSearching(true)
    
    // Track search query
    setHelpState(prev => ({
      ...prev,
      helpAnalytics: {
        ...prev.helpAnalytics,
        searchQueries: [...prev.helpAnalytics.searchQueries.slice(-20), query], // Keep last 20 searches
      },
    }))

    try {
      const terms = query
        .toLowerCase()
        .split(/\s+/)
        .map((term) => term.trim())
        .filter(Boolean)

      const scored = helpIndex
        .map((item) => {
          const haystack = `${item.title} ${item.content} ${item.tags.join(' ')} ${item.category}`.toLowerCase()
          let score = 0
          for (const term of terms) {
            if (item.title.toLowerCase().includes(term)) score += 3
            if (item.tags.some((tag) => tag.toLowerCase().includes(term))) score += 2
            if (haystack.includes(term)) score += 1
          }
          return { ...item, relevanceScore: score }
        })
        .filter((item) => item.relevanceScore > 0)
        .sort((a, b) => b.relevanceScore - a.relevanceScore)
        .slice(0, 20)

      setSearchResults(scored)
      trackHelpEvent('search_performed', { query, resultsCount: scored.length })
    } catch (error) {
      console.error('Help search error:', error)
      setSearchResults([])
    } finally {
      setIsSearching(false)
    }
  }, [setHelpState, helpIndex])

  // Track help content view
  const trackContentView = useCallback((contentId: string) => {
    setHelpState(prev => ({
      ...prev,
      helpAnalytics: {
        ...prev.helpAnalytics,
        viewedContent: Array.from(new Set([...prev.helpAnalytics.viewedContent, contentId])),
      },
    }))
    
    trackHelpEvent('content_viewed', { contentId })
  }, [setHelpState])

  // Reset onboarding
  const resetOnboarding = useCallback(() => {
    setHelpState(prev => ({
      ...prev,
      onboardingProgress: { ...defaultOnboardingProgress, startedAt: new Date() },
    }))
  }, [setHelpState])

  // Keyboard shortcut handling
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // F1 key or Ctrl+?
      if (event.key === 'F1' || (event.ctrlKey && event.key === '?')) {
        event.preventDefault()
        toggleHelp()
      }
      // Escape to close help
      if (event.key === 'Escape' && helpState.isHelpOpen) {
        setHelpState(prev => ({ ...prev, isHelpOpen: false }))
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [toggleHelp, helpState.isHelpOpen, setHelpState])

  return {
    // State
    isHelpOpen: helpState.isHelpOpen,
    currentTour: helpState.currentTour,
    tourRunning: helpState.tourRunning,
    showTooltips: helpState.showTooltips,
    onboardingProgress: helpState.onboardingProgress,
    tourCompletions: helpState.tourCompletions,
    helpAnalytics: helpState.helpAnalytics,
    searchResults,
    isSearching,
    helpContent: helpIndex,
    tours: TOURS,

    // Actions
    toggleHelp,
    startTour,
    completeTour,
    stopTour,
    toggleTooltips,
    updateOnboardingProgress,
    searchHelp,
    trackContentView,
    resetOnboarding,
  }
}

// Analytics helper
function trackHelpEvent(event: string, properties?: Record<string, any>) {
  // In a real implementation, this would send to analytics service
  console.log('Help analytics:', { event, properties, timestamp: new Date() })
}
