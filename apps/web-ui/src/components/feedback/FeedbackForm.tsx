'use client'

import React, { useState } from 'react'
import { Loader2, AlertCircle, CheckCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useFeedbackForm } from '@/hooks/useFeedbackForm'
import { FeedbackFormProps } from '@/types/feedback'

// Component imports
import { RatingSection } from './components/RatingSection'
import { CategorySection } from './components/CategorySection'
import { CommentSection } from './components/CommentSection'
import { ScreenshotCapture } from './components/ScreenshotCapture'
import { SuccessMessage } from './components/SuccessMessage'

export function FeedbackForm({
  onSubmit,
  onCancel,
  initialCategory,
  context,
  isSubmitting = false
}: FeedbackFormProps) {
  const [step, setStep] = useState<'form' | 'success'>('form')
  const [submissionResult, setSubmissionResult] = useState<any>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const {
    formData,
    errors,
    isValid,
    setRating,
    setEmojiRating,
    setCategory,
    setTitle,
    setDescription,
    setScreenshot,
    handleSubmit,
    resetForm,
    titleCharCount,
    descriptionCharCount,
    titleRemaining,
    descriptionRemaining,
    getFieldError
  } = useFeedbackForm({
    initialCategory,
    requireScreenshot: false,
    minDescriptionLength: 10,
    maxDescriptionLength: 2000
  })

  const onFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitError(null)

    try {
      await handleSubmit(async (data) => {
        await onSubmit(data)
        setSubmissionResult(data)
        setStep('success')
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to submit feedback'
      setSubmitError(message)
    }
  }

  const handleSubmitMore = () => {
    resetForm()
    setStep('form')
    setSubmissionResult(null)
    setSubmitError(null)
  }

  const handleClose = () => {
    if (step === 'success') {
      onCancel()
    } else {
      // Show confirmation if form has content
      const hasContent = formData.title || formData.description || formData.rating > 0
      if (hasContent) {
        if (confirm('Are you sure you want to close? Your feedback will be lost.')) {
          onCancel()
        }
      } else {
        onCancel()
      }
    }
  }

  if (step === 'success' && submissionResult) {
    return (
      <SuccessMessage
        submission={{
          ...submissionResult,
          id: `feedback-${Date.now()}`,
          status: 'submitted' as const,
          retryCount: 0,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString()
        }}
        onClose={handleClose}
        onSubmitMore={handleSubmitMore}
      />
    )
  }

  return (
    <form onSubmit={onFormSubmit} className="space-y-6">
      <ScrollArea className="h-[500px] pr-4">
        <div className="space-y-6">
          {/* Context Information */}
          {context && (
            <div className="p-3 bg-muted rounded-lg border-l-4 border-primary">
              <p className="text-sm text-muted-foreground">
                <span className="font-medium">Context:</span> {context}
              </p>
            </div>
          )}

          {/* Rating Section */}
          <RatingSection
            rating={formData.rating}
            onRatingChange={setRating}
            emojiRating={formData.emojiRating}
            onEmojiRatingChange={setEmojiRating}
            showEmojis={true}
          />

          {/* Category Selection */}
          <CategorySection
            selectedCategory={formData.category}
            onCategoryChange={setCategory}
          />

          {/* Title and Description */}
          <CommentSection
            title={formData.title}
            description={formData.description}
            onTitleChange={setTitle}
            onDescriptionChange={setDescription}
            category={formData.category}
            titleError={getFieldError('title')}
            descriptionError={getFieldError('description')}
            titleCharCount={titleCharCount}
            descriptionCharCount={descriptionCharCount}
            titleRemaining={titleRemaining}
            descriptionRemaining={descriptionRemaining}
          />

          {/* Screenshot Capture */}
          <ScreenshotCapture
            screenshot={formData.screenshot}
            onScreenshotChange={setScreenshot}
            category={formData.category}
            required={false}
          />

          {/* Error Display */}
          {submitError && (
            <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-medium text-destructive mb-1">
                    Submission Failed
                  </h4>
                  <p className="text-sm text-destructive/80">
                    {submitError}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Form Actions */}
      <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t">
        <Button
          type="button"
          variant="outline"
          onClick={handleClose}
          className="sm:w-auto"
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        
        <div className="flex-1" />
        
        <div className="flex gap-2">
          {!isValid && (
            <div className="flex items-center gap-1 text-sm text-muted-foreground mr-2">
              <AlertCircle className="w-4 h-4" />
              <span className="hidden sm:inline">Please complete all fields</span>
            </div>
          )}
          
          <Button
            type="submit"
            disabled={!isValid || isSubmitting}
            className="min-w-[120px]"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <CheckCircle className="w-4 h-4 mr-2" />
                Submit Feedback
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Form Progress Indicator */}
      <div className="flex items-center justify-center gap-1 pt-2">
        <div
          className={cn(
            'w-2 h-2 rounded-full transition-colors',
            formData.rating > 0 ? 'bg-primary' : 'bg-muted-foreground/30'
          )}
        />
        <div
          className={cn(
            'w-2 h-2 rounded-full transition-colors',
            formData.category ? 'bg-primary' : 'bg-muted-foreground/30'
          )}
        />
        <div
          className={cn(
            'w-2 h-2 rounded-full transition-colors',
            formData.title ? 'bg-primary' : 'bg-muted-foreground/30'
          )}
        />
        <div
          className={cn(
            'w-2 h-2 rounded-full transition-colors',
            formData.description && formData.description.length >= 10 
              ? 'bg-primary' 
              : 'bg-muted-foreground/30'
          )}
        />
      </div>
      
      <p className="text-xs text-center text-muted-foreground">
        Complete the form to submit your feedback
      </p>
    </form>
  )
}