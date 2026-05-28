'use client'

import React from 'react'
import { X, MessageSquare } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { FeedbackDialogProps } from '@/types/feedback'
import { FeedbackForm } from './FeedbackForm'
import { cn } from '@/lib/utils'

export function FeedbackDialog({
  open,
  onOpenChange,
  initialCategory,
  context,
  onSubmit
}: FeedbackDialogProps) {
  const handleSubmit = async (data: any) => {
    if (onSubmit) {
      await onSubmit(data)
    }
    // Don't close dialog here - let the form handle success state
  }

  const handleClose = () => {
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          'max-w-2xl max-h-[90vh] overflow-hidden',
          'feedback-dialog' // For screenshot exclusion
        )}
        // Prevent closing on outside click when form has content
        onInteractOutside={(e) => {
          // Could add logic here to check if form has content and prevent closing
          e.preventDefault()
        }}
      >
        <DialogHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-primary/10 rounded-full flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-lg font-semibold">
                Share Your Feedback
              </DialogTitle>
              <DialogDescription className="text-sm text-muted-foreground mt-0.5">
                Help us improve your experience
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <FeedbackForm
          onSubmit={handleSubmit}
          onCancel={handleClose}
          initialCategory={initialCategory}
          context={context}
        />
      </DialogContent>
    </Dialog>
  )
}
