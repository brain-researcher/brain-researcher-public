'use client'

import React from 'react'
import { Star, Heart } from 'lucide-react'
import { cn } from '@/lib/utils'
import { EmojiRating, EMOJI_RATINGS } from '@/types/feedback'

interface RatingSectionProps {
  rating: number
  onRatingChange: (rating: number) => void
  emojiRating?: string
  onEmojiRatingChange: (emoji: EmojiRating) => void
  showEmojis?: boolean
  className?: string
}

export function RatingSection({
  rating,
  onRatingChange,
  emojiRating,
  onEmojiRatingChange,
  showEmojis = true,
  className
}: RatingSectionProps) {
  return (
    <div className={cn('space-y-4', className)}>
      {/* Star Rating */}
      <div>
        <label className="text-sm font-medium text-foreground mb-2 block">
          How would you rate your experience?
        </label>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              onClick={() => onRatingChange(star)}
              className={cn(
                'p-1 rounded-md transition-colors duration-200 hover:bg-accent',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2'
              )}
              aria-label={`Rate ${star} star${star !== 1 ? 's' : ''}`}
            >
              <Star
                className={cn(
                  'w-6 h-6 transition-colors duration-200',
                  star <= rating
                    ? 'fill-yellow-400 text-yellow-400'
                    : 'text-muted-foreground hover:text-yellow-300'
                )}
              />
            </button>
          ))}
        </div>
        {rating > 0 && (
          <p className="text-xs text-muted-foreground mt-1">
            {rating} out of 5 stars
          </p>
        )}
      </div>

      {/* Emoji Rating */}
      {showEmojis && (
        <div>
          <label className="text-sm font-medium text-foreground mb-2 block">
            How are you feeling?
          </label>
          <div className="flex gap-2">
            {Object.entries(EMOJI_RATINGS).map(([key, { emoji, label, value }]) => {
              const isSelected = emojiRating === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => onEmojiRatingChange(key as EmojiRating)}
                  className={cn(
                    'p-2 rounded-lg transition-all duration-200',
                    'border-2 hover:border-primary/50',
                    'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
                    isSelected
                      ? 'border-primary bg-primary/10 scale-110'
                      : 'border-border hover:bg-accent'
                  )}
                  title={label}
                  aria-label={label}
                >
                  <span className="text-lg" role="img" aria-label={label}>
                    {emoji}
                  </span>
                </button>
              )
            })}
          </div>
          {emojiRating && (
            <p className="text-xs text-muted-foreground mt-1">
              {EMOJI_RATINGS[emojiRating as EmojiRating]?.label}
            </p>
          )}
        </div>
      )}

      {/* Quick sentiment buttons for faster interaction */}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={() => {
            onRatingChange(1)
            onEmojiRatingChange('very-unhappy')
          }}
          className={cn(
            'flex-1 p-2 text-xs rounded-md border transition-colors',
            'hover:bg-destructive/10 hover:border-destructive/50',
            'focus:outline-none focus:ring-2 focus:ring-destructive focus:ring-offset-2',
            rating === 1 && emojiRating === 'very-unhappy'
              ? 'bg-destructive/10 border-destructive text-destructive'
              : 'border-border text-muted-foreground'
          )}
        >
          👎 Bad
        </button>
        <button
          type="button"
          onClick={() => {
            onRatingChange(3)
            onEmojiRatingChange('neutral')
          }}
          className={cn(
            'flex-1 p-2 text-xs rounded-md border transition-colors',
            'hover:bg-accent hover:border-accent',
            'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
            rating === 3 && emojiRating === 'neutral'
              ? 'bg-accent border-accent-foreground'
              : 'border-border text-muted-foreground'
          )}
        >
          😐 Okay
        </button>
        <button
          type="button"
          onClick={() => {
            onRatingChange(5)
            onEmojiRatingChange('very-happy')
          }}
          className={cn(
            'flex-1 p-2 text-xs rounded-md border transition-colors',
            'hover:bg-green-50 hover:border-green-200 dark:hover:bg-green-950',
            'focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2',
            rating === 5 && emojiRating === 'very-happy'
              ? 'bg-green-50 border-green-200 text-green-700 dark:bg-green-950 dark:border-green-800 dark:text-green-300'
              : 'border-border text-muted-foreground'
          )}
        >
          👍 Great
        </button>
      </div>
    </div>
  )
}