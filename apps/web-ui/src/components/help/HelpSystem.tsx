'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { HelpCircle, Book, Search, Lightbulb, ChevronRight, Clock, CheckCircle, ExternalLink, BookOpen } from 'lucide-react'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { Badge } from '../ui/badge'
import { ScrollArea } from '../ui/scroll-area'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { useHelp } from '../../hooks/use-help'
import { InteractiveTour } from './InteractiveTour'
import { ContextualHelp } from './ContextualHelp'
import { OnboardingFlow } from './OnboardingFlow'
import { HelpSearch } from './HelpSearch'

interface HelpSystemProps {
  showHelpButton?: boolean
  className?: string
}

export function HelpSystem({ showHelpButton = true, className }: HelpSystemProps) {
  const {
    isHelpOpen,
    toggleHelp,
    startTour,
    tours,
    tourCompletions,
    onboardingProgress,
    showTooltips,
    toggleTooltips,
    faqs,
    guides,
  } = useHelp()

  const [activeTab, setActiveTab] = useState('overview')
  const showOnboardingModal =
    (process.env.NEXT_PUBLIC_ENABLE_ONBOARDING_MODAL || '').trim().toLowerCase() === 'true'

  const handleStartTour = (tourId: string) => {
    toggleHelp() // Close help dialog
    setTimeout(() => startTour(tourId), 100) // Small delay for smooth transition
  }

  const handleReportBug = () => {
    window.open('https://github.com/zjc062/brain_researcher/issues/new?template=bug_report.md', '_blank')
  }

  const handleRequestFeature = () => {
    window.open('https://github.com/zjc062/brain_researcher/issues/new?template=feature_request.md', '_blank')
  }

  const handleContactSupport = () => {
    window.location.href = 'mailto:support@brain-researcher.ai'
  }

  const getToursByCategory = () => {

    const categories: Record<string, typeof tours[keyof typeof tours][]> = {}
    Object.values(tours).forEach(tour => {
      if (!categories[tour.category]) {
        categories[tour.category] = []
      }
      categories[tour.category].push(tour)
    })
    return categories
  }

  const tourCategories = getToursByCategory()
  const completedToursCount = Object.keys(tourCompletions).filter(id => tourCompletions[id]).length
  const totalToursCount = Object.keys(tours).length

  return (
    <>
      {/* Help Button */}
      {showHelpButton && (
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleHelp}
          className={`relative ${className}`}
          data-tour="help-button"
          aria-label="Open help system (F1)"
          title="Get help (F1)"
        >
          <HelpCircle className="h-4 w-4" />
          {!onboardingProgress.isCompleted && (
            <div className="absolute -top-1 -right-1 w-3 h-3 bg-gray-900 dark:bg-gray-100 rounded-full animate-pulse" />
          )}
        </Button>
      )}

      {/* Help Dialog */}
      <Dialog open={isHelpOpen} onOpenChange={toggleHelp}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HelpCircle className="h-5 w-5 text-gray-700 dark:text-gray-300" />
              Help & Support
            </DialogTitle>
            <DialogDescription>
              Browse tours, guides, and quick answers to get unblocked fast.
            </DialogDescription>
          </DialogHeader>

          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">
            <TabsList className="grid w-full grid-cols-5">
              <TabsTrigger value="overview" className="flex items-center gap-1">
                <Lightbulb className="h-4 w-4" />
                <span className="hidden sm:inline">Overview</span>
              </TabsTrigger>
              <TabsTrigger value="tours" className="flex items-center gap-1">
                <Book className="h-4 w-4" />
                <span className="hidden sm:inline">Tours</span>
              </TabsTrigger>
              <TabsTrigger value="videos" className="flex items-center gap-1">
                <Book className="h-4 w-4" />
                <span className="hidden sm:inline">Guides</span>
              </TabsTrigger>
              <TabsTrigger value="search" className="flex items-center gap-1">
                <Search className="h-4 w-4" />
                <span className="hidden sm:inline">Search</span>
              </TabsTrigger>
              <TabsTrigger value="settings" className="flex items-center gap-1">
                <span className="hidden sm:inline">Settings</span>
              </TabsTrigger>
            </TabsList>

            {/* Overview Tab */}
            <TabsContent value="overview" className="flex-1 mt-4">
              <ScrollArea className="h-[500px]">
                <div className="space-y-6">
                  {/* Quick answers */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Quick answers</CardTitle>
                      <CardDescription>
                        Common questions about Studio, MCP, runs, and grounding.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2">
                      {faqs.slice(0, 6).map((faq) => (
                        <details
                          key={faq.id}
                          className="group rounded-lg border px-3 py-2"
                        >
                          <summary className="cursor-pointer list-none text-sm font-medium marker:hidden [&::-webkit-details-marker]:hidden flex items-center justify-between gap-2">
                            <span>{faq.question}</span>
                            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
                          </summary>
                          <p className="mt-2 text-sm text-muted-foreground">{faq.answer}</p>
                        </details>
                      ))}
                      <div className="pt-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="w-full justify-start"
                          onClick={() => setActiveTab('search')}
                        >
                          <Search className="mr-2 h-4 w-4" />
                          Search all answers
                        </Button>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Quick Start */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Quick Start</CardTitle>
                      <CardDescription>
                        New to Brain Researcher? Start here!
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {!onboardingProgress.isCompleted ? (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <span>Onboarding Progress</span>
                            <span className="text-sm text-muted-foreground">
                              {onboardingProgress.currentStep}/5 steps
                            </span>
                          </div>
                          <div className="w-full bg-muted rounded-full h-2">
                            <div
                              className="bg-gray-900 dark:bg-gray-100 h-2 rounded-full transition-all duration-300"
                              style={{ width: `${(onboardingProgress.currentStep / 5) * 100}%` }}
                            />
                          </div>
                          <Button
                            onClick={() => handleStartTour('welcome')}
                            className="w-full"
                          >
                            Continue Onboarding
                            <ChevronRight className="ml-2 h-4 w-4" />
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 text-green-600">
                          <CheckCircle className="h-5 w-5" />
                          <span>Onboarding completed!</span>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Tour Progress */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Tour Progress</CardTitle>
                      <CardDescription>
                        Track your learning progress with interactive tours
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-center justify-between mb-3">
                        <span>Completed Tours</span>
                        <Badge variant="secondary">
                          {completedToursCount}/{totalToursCount}
                        </Badge>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2 mb-4">
                        <div
                          className="bg-green-500 h-2 rounded-full transition-all duration-300"
                          style={{ width: `${(completedToursCount / totalToursCount) * 100}%` }}
                        />
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => setActiveTab('tours')}
                        className="w-full"
                      >
                        View All Tours
                        <ChevronRight className="ml-2 h-4 w-4" />
                      </Button>
                    </CardContent>
                  </Card>

                  {/* Keyboard Shortcuts */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Keyboard Shortcuts</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span>Open Help</span>
                          <Badge variant="outline">F1</Badge>
                        </div>
                        <div className="flex justify-between">
                          <span>Search</span>
                          <Badge variant="outline">Ctrl + K</Badge>
                        </div>
                        <div className="flex justify-between">
                          <span>Close Dialog</span>
                          <Badge variant="outline">Esc</Badge>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Tours Tab */}
            <TabsContent value="tours" className="flex-1 mt-4">
              <ScrollArea className="h-[500px]">
                <div className="space-y-6">
                  {Object.entries(tourCategories).map(([category, categoryTours]) => (
                    <div key={category}>
                      <h3 className="text-lg font-semibold mb-3 capitalize">{category}</h3>
                      <div className="grid gap-3">
                        {categoryTours.map(tour => (
                          <Card key={tour.id} className="cursor-pointer hover:shadow-md transition-shadow">
                            <CardContent className="p-4">
                              <div className="flex items-start justify-between">
                                <div className="flex-1">
                                  <div className="flex items-center gap-2 mb-1">
                                    <h4 className="font-medium">{tour.name}</h4>
                                    {tourCompletions[tour.id] && (
                                      <CheckCircle className="h-4 w-4 text-green-500" />
                                    )}
                                  </div>
                                  <p className="text-sm text-muted-foreground mb-2">{tour.description}</p>
                                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                    <Clock className="h-3 w-3" />
                                    <span>{tour.estimatedTime} min</span>
                                    <Badge variant="outline" className="ml-auto">
                                      {tour.steps.length} steps
                                    </Badge>
                                  </div>
                                </div>
                                <Button
                                  size="sm"
                                  onClick={() => handleStartTour(tour.id)}
                                  variant={tourCompletions[tour.id] ? "outline" : "default"}
                                >
                                  {tourCompletions[tour.id] ? "Restart" : "Start"}
                                </Button>
                              </div>
                            </CardContent>
                          </Card>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Guides Tab */}
            <TabsContent value="videos" className="flex-1 mt-4">
              <ScrollArea className="h-[500px]">
                <div className="space-y-3">
                  {guides.map((guide) => {
                    const isInternal = guide.href.startsWith('/')
                    return (
                      <Card key={guide.href}>
                        <CardContent className="flex items-start justify-between gap-4 p-4">
                          <div className="flex-1 space-y-1">
                            <div className="font-medium">{guide.title}</div>
                            <p className="text-sm text-muted-foreground">{guide.description}</p>
                          </div>
                          <Button asChild size="sm" variant="outline" className="shrink-0">
                            {isInternal ? (
                              <Link href={guide.href} onClick={toggleHelp}>
                                <BookOpen className="mr-2 h-3.5 w-3.5" />
                                Open
                              </Link>
                            ) : (
                              <a href={guide.href} target="_blank" rel="noreferrer">
                                <ExternalLink className="mr-2 h-3.5 w-3.5" />
                                Open
                              </a>
                            )}
                          </Button>
                        </CardContent>
                      </Card>
                    )
                  })}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Search Tab */}
            <TabsContent value="search" className="flex-1 mt-4">
              <HelpSearch />
            </TabsContent>

            {/* Settings Tab */}
            <TabsContent value="settings" className="flex-1 mt-4">
              <ScrollArea className="h-[500px]">
                <div className="space-y-6">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Help Preferences</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium">Contextual Tooltips</div>
                          <div className="text-sm text-muted-foreground">
                            Show helpful tooltips when hovering over interface elements
                          </div>
                        </div>
                        <Button
                          variant={showTooltips ? "default" : "outline"}
                          size="sm"
                          onClick={toggleTooltips}
                        >
                          {showTooltips ? "Enabled" : "Disabled"}
                        </Button>
                      </div>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Support</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <Button variant="outline" className="w-full justify-start" onClick={handleContactSupport}>
                        Contact Support
                      </Button>
                      <Button variant="outline" className="w-full justify-start" onClick={handleReportBug}>
                        Report a Bug
                      </Button>
                      <Button variant="outline" className="w-full justify-start" onClick={handleRequestFeature}>
                        Request Feature
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              </ScrollArea>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>

      {/* Interactive Components */}
      <InteractiveTour />
      <ContextualHelp />
      {showOnboardingModal ? <OnboardingFlow /> : null}
    </>
  )
}
