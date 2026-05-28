'use client'

import React from 'react'
import { CheckCircle, ExternalLink, MessageSquare, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { FeedbackSubmission } from '@/types/feedback'

interface SuccessMessageProps {
  submission: FeedbackSubmission
  onClose: () => void
  onSubmitMore?: () => void
  className?: string
}

export function SuccessMessage({
  submission,
  onClose,
  onSubmitMore,
  className
}: SuccessMessageProps) {
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const getSuccessMessage = (category: string) => {
    switch (category) {
      case 'bug-report':
        return {
          title: 'Bug report submitted successfully!',
          message: 'Thank you for reporting this issue. Our team will investigate and work on a fix.',
          emoji: '🐛'
        }
      case 'feature-request':
        return {
          title: 'Feature request submitted!',
          message: 'Thanks for the great idea! We\'ll consider it for future updates.',
          emoji: '💡'
        }
      case 'ui-ux':
        return {
          title: 'UI/UX feedback received!',
          message: 'Your input helps us improve the user experience. Thank you!',
          emoji: '🎨'
        }
      case 'performance':
        return {
          title: 'Performance issue reported!',
          message: 'We\'ll look into this performance concern and optimize accordingly.',
          emoji: '⚡'
        }
      case 'content':
        return {
          title: 'Content feedback submitted!',
          message: 'Thanks for helping us maintain accurate and useful content.',
          emoji: '📝'
        }
      case 'accessibility':
        return {
          title: 'Accessibility feedback received!',
          message: 'Thank you for helping us make our platform more accessible to everyone.',
          emoji: '♿'
        }
      default:
        return {
          title: 'Feedback submitted successfully!',
          message: 'Thank you for your feedback. We appreciate your input!',
          emoji: '💬'
        }
    }
  }

  const success = getSuccessMessage(submission.category)

  return (
    <div className={cn('text-center space-y-6', className)}>
      {/* Success Icon and Animation */}
      <div className="flex flex-col items-center space-y-3">
        <div className="relative">
          <div className="w-16 h-16 bg-green-100 dark:bg-green-900 rounded-full flex items-center justify-center">
            <CheckCircle className="w-8 h-8 text-green-600 dark:text-green-400" />
          </div>
          <div className="absolute -top-1 -right-1 text-2xl">
            {success.emoji}
          </div>
        </div>
        
        <div className="space-y-2">
          <h3 className="text-lg font-semibold text-foreground">
            {success.title}
          </h3>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            {success.message}
          </p>
        </div>
      </div>

      {/* Submission Details */}
      <div className="bg-muted rounded-lg p-4 text-left space-y-3">
        <h4 className="text-sm font-medium text-foreground flex items-center gap-2">
          <MessageSquare className="w-4 h-4" />
          Submission Details
        </h4>
        
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="flex justify-between">
            <span>Feedback ID:</span>
            <code className="bg-background px-1 rounded text-foreground">
              {submission.id.slice(-8)}
            </code>
          </div>
          
          <div className="flex justify-between">
            <span>Category:</span>
            <span className="text-foreground capitalize">
              {submission.category.replace('-', ' ')}
            </span>
          </div>
          
          <div className="flex justify-between">
            <span>Submitted:</span>
            <span className="text-foreground">
              {formatDate(submission.createdAt)}
            </span>
          </div>
          
          {submission.screenshot && (
            <div className="flex justify-between">
              <span>Screenshot:</span>
              <span className="text-green-600 dark:text-green-400">Included</span>
            </div>
          )}
        </div>

        {submission.title && (
          <div className="border-t pt-2">
            <p className="text-xs text-muted-foreground mb-1">Title:</p>
            <p className="text-sm text-foreground font-medium">
              {submission.title}
            </p>
          </div>
        )}
      </div>

      {/* Next Steps */}
      <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <h4 className="text-sm font-medium text-blue-900 dark:text-blue-100 mb-2">
          What happens next?
        </h4>
        <ul className="text-xs text-blue-700 dark:text-blue-300 space-y-1 text-left">
          <li>• Our team will review your feedback within 24-48 hours</li>
          <li>• For bugs, we'll prioritize based on severity and impact</li>
          <li>• For feature requests, we'll evaluate and add to our roadmap</li>
          <li>• You may receive follow-up questions if needed</li>
        </ul>
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 pt-2">
        <Button
          onClick={onClose}
          className="flex-1"
        >
          Close
        </Button>
        
        {onSubmitMore && (
          <Button
            variant="outline"
            onClick={onSubmitMore}
            className="flex-1"
          >
            Submit More Feedback
          </Button>
        )}
        
        <Button
          variant="outline"
          onClick={() => {
            // Copy feedback ID to clipboard
            navigator.clipboard.writeText(submission.id)
          }}
          className="sm:w-auto"
          title="Copy feedback ID to clipboard"
        >
          Copy ID
        </Button>
      </div>

      {/* Additional Resources */}
      <div className="border-t pt-4 space-y-2">
        <p className="text-xs text-muted-foreground">
          Need immediate help? Check out our resources:
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-8"
            onClick={() => window.open('/docs', '_blank')}
          >
            <ExternalLink className="w-3 h-3 mr-1" />
            Documentation
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-8"
            onClick={() => window.open('/help', '_blank')}
          >
            <ExternalLink className="w-3 h-3 mr-1" />
            Help Center
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-8"
            onClick={() => window.open('/status', '_blank')}
          >
            <ExternalLink className="w-3 h-3 mr-1" />
            System Status
          </Button>
        </div>
      </div>
    </div>
  )
}