'use client'

import React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FeedbackCategory, FEEDBACK_CATEGORIES } from '@/types/feedback'

interface CategorySectionProps {
  selectedCategory: FeedbackCategory
  onCategoryChange: (category: FeedbackCategory) => void
  className?: string
}

export function CategorySection({
  selectedCategory,
  onCategoryChange,
  className
}: CategorySectionProps) {
  return (
    <div className={cn('space-y-3', className)}>
      <label className="text-sm font-medium text-foreground block">
        What type of feedback is this?
      </label>
      
      <div className="grid grid-cols-1 gap-2">
        {Object.entries(FEEDBACK_CATEGORIES).map(([key, { label, description, icon }]) => {
          const isSelected = selectedCategory === key
          return (
            <button
              key={key}
              type="button"
              onClick={() => onCategoryChange(key as FeedbackCategory)}
              className={cn(
                'flex items-start gap-3 p-3 text-left rounded-lg border-2 transition-all duration-200',
                'hover:border-primary/50 hover:bg-accent/50',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
                isSelected
                  ? 'border-primary bg-primary/10'
                  : 'border-border'
              )}
            >
              <div className="flex-shrink-0 w-8 h-8 rounded-md bg-background border flex items-center justify-center text-sm">
                {icon}
              </div>
              
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium text-foreground">
                    {label}
                  </h4>
                  {isSelected && (
                    <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {description}
                </p>
              </div>
            </button>
          )
        })}
      </div>

      {/* Quick category suggestions based on common patterns */}
      <div className="border-t pt-3 mt-4">
        <p className="text-xs text-muted-foreground mb-2">Quick select:</p>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => onCategoryChange('bug-report')}
            className={cn(
              'px-2 py-1 text-xs rounded-md border transition-colors',
              'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-primary',
              selectedCategory === 'bug-report'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground'
            )}
          >
            🐛 Something's broken
          </button>
          <button
            type="button"
            onClick={() => onCategoryChange('feature-request')}
            className={cn(
              'px-2 py-1 text-xs rounded-md border transition-colors',
              'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-primary',
              selectedCategory === 'feature-request'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground'
            )}
          >
            💡 I have an idea
          </button>
          <button
            type="button"
            onClick={() => onCategoryChange('ui-ux')}
            className={cn(
              'px-2 py-1 text-xs rounded-md border transition-colors',
              'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-primary',
              selectedCategory === 'ui-ux'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground'
            )}
          >
            🎨 Design issue
          </button>
          <button
            type="button"
            onClick={() => onCategoryChange('performance')}
            className={cn(
              'px-2 py-1 text-xs rounded-md border transition-colors',
              'hover:bg-accent focus:outline-none focus:ring-1 focus:ring-primary',
              selectedCategory === 'performance'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground'
            )}
          >
            ⚡ Too slow
          </button>
        </div>
      </div>
    </div>
  )
}