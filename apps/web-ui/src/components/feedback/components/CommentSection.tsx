'use client'

import React from 'react'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { FeedbackCategory } from '@/types/feedback'

interface CommentSectionProps {
  title: string
  description: string
  onTitleChange: (title: string) => void
  onDescriptionChange: (description: string) => void
  category: FeedbackCategory
  titleError?: string
  descriptionError?: string
  titleCharCount: number
  descriptionCharCount: number
  titleRemaining: number
  descriptionRemaining: number
  maxDescriptionLength?: number
  className?: string
}

export function CommentSection({
  title,
  description,
  onTitleChange,
  onDescriptionChange,
  category,
  titleError,
  descriptionError,
  titleCharCount,
  descriptionCharCount,
  titleRemaining,
  descriptionRemaining,
  maxDescriptionLength = 2000,
  className
}: CommentSectionProps) {
  // Dynamic placeholders based on category
  const getPlaceholders = (category: FeedbackCategory) => {
    switch (category) {
      case 'bug-report':
        return {
          title: 'Brief summary of the issue',
          description: 'Describe what you were doing, what you expected to happen, and what happened instead.'
        }
      case 'feature-request':
        return {
          title: 'Brief summary of the request',
          description: 'Describe the feature you want, why it would be useful, and how you expect it to work.'
        }
      case 'ui-ux':
        return {
          title: 'Brief summary of the UX issue',
          description: 'What part of the interface is confusing, and how could it be improved?'
        }
      case 'performance':
        return {
          title: 'Brief summary of the slowdown',
          description: 'Which page is slow, how long it takes, and what device/browser you are using.'
        }
      case 'content':
        return {
          title: 'Brief summary of the content issue',
          description: 'What content is incorrect and what should it show instead?'
        }
      case 'accessibility':
        return {
          title: 'Brief summary of the accessibility issue',
          description: 'What assistive technology are you using, and what interaction is not working?'
        }
      default:
        return {
          title: 'Brief summary of your feedback',
          description: 'Please provide more details about your feedback...'
        }
    }
  }

  const placeholders = getPlaceholders(category)

  return (
    <div className={cn('space-y-4', className)}>
      {/* Title Input */}
      <div className="space-y-2">
        <Label htmlFor="feedback-title" className="text-sm font-medium">
          Title
        </Label>
        <Input
          id="feedback-title"
          type="text"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder={placeholders.title}
          maxLength={100}
          className={cn(
            'transition-colors',
            titleError ? 'border-destructive focus:ring-destructive' : ''
          )}
          aria-describedby={titleError ? 'title-error' : 'title-help'}
        />
        <div className="flex justify-between items-center text-xs">
          <div>
            {titleError ? (
              <span id="title-error" className="text-destructive" role="alert">
                {titleError}
              </span>
            ) : (
              <span id="title-help" className="text-muted-foreground">
                A brief, descriptive title for your feedback
              </span>
            )}
          </div>
          <span className={cn(
            'text-muted-foreground',
            titleRemaining < 10 ? 'text-orange-500' : '',
            titleRemaining < 0 ? 'text-destructive' : ''
          )}>
            {titleCharCount}/100
          </span>
        </div>
      </div>

      {/* Description Textarea */}
      <div className="space-y-2">
        <Label htmlFor="feedback-description" className="text-sm font-medium">
          Description
        </Label>
        <Textarea
          id="feedback-description"
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          placeholder={placeholders.description}
          maxLength={maxDescriptionLength}
          rows={5}
          className={cn(
            'resize-none transition-colors',
            descriptionError ? 'border-destructive focus:ring-destructive' : ''
          )}
          aria-describedby={descriptionError ? 'description-error' : 'description-help'}
        />
        <div className="flex justify-between items-start text-xs">
          <div className="flex-1 pr-2">
            {descriptionError ? (
              <span id="description-error" className="text-destructive" role="alert">
                {descriptionError}
              </span>
            ) : (
              <div id="description-help" className="text-muted-foreground space-y-1">
                <p>Please provide as much detail as possible.</p>
                {category === 'bug-report' && (
                  <p className="text-xs">
                    💡 Include steps to reproduce, expected vs actual behavior
                  </p>
                )}
                {category === 'feature-request' && (
                  <p className="text-xs">
                    💡 Describe the problem this feature would solve
                  </p>
                )}
                {category === 'performance' && (
                  <p className="text-xs">
                    💡 Include device info, browser, and timing details
                  </p>
                )}
              </div>
            )}
          </div>
          <span className={cn(
            'text-muted-foreground whitespace-nowrap',
            descriptionRemaining < 100 ? 'text-orange-500' : '',
            descriptionRemaining < 0 ? 'text-destructive' : ''
          )}>
            {descriptionCharCount}/{maxDescriptionLength}
          </span>
        </div>
      </div>

      {/* Quick templates for common feedback types */}
      {category === 'bug-report' && !description && (
        <div className="p-3 bg-muted rounded-lg">
          <p className="text-xs font-medium text-muted-foreground mb-2">
            Quick template for bug reports:
          </p>
          <button
            type="button"
            onClick={() => onDescriptionChange(`**Steps to reproduce:**
1. Go to...
2. Click on...
3. Expected: ...
4. Actual: ...

**Browser:** ${navigator.userAgent.includes('Chrome') ? 'Chrome' : 'Other'}
**Device:** ${navigator.platform}
**URL:** ${window.location.href}`)}
            className="text-xs text-primary hover:text-primary/80 underline"
          >
            Use bug report template
          </button>
        </div>
      )}

      {category === 'feature-request' && !description && (
        <div className="p-3 bg-muted rounded-lg">
          <p className="text-xs font-medium text-muted-foreground mb-2">
            Quick template for feature requests:
          </p>
          <button
            type="button"
            onClick={() => onDescriptionChange(`**Problem:** What problem would this feature solve?

**Solution:** What would you like to see happen?

**Alternatives:** What workarounds do you currently use?

**Additional context:** Any other details or mockups?`)}
            className="text-xs text-primary hover:text-primary/80 underline"
          >
            Use feature request template
          </button>
        </div>
      )}
    </div>
  )
}
