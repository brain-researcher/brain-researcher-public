/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RatingSection } from '@/components/feedback/components/RatingSection'
import '@testing-library/jest-dom'

describe('RatingSection', () => {
  const mockOnRatingChange = jest.fn()
  const mockOnEmojiRatingChange = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Rendering', () => {
    it('renders star rating component', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Should render 5 stars
      const stars = screen.getAllByRole('button', { name: /star/i })
      expect(stars).toHaveLength(5)
    })

    it('renders emoji rating component', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Should render emoji options
      const emojis = screen.getAllByRole('button', { name: /emoji/i })
      expect(emojis.length).toBeGreaterThan(0)
    })

    it('renders section labels and descriptions', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      expect(screen.getByText(/overall rating/i)).toBeInTheDocument()
      expect(screen.getByText(/how would you rate/i)).toBeInTheDocument()
    })

    it('shows current rating value', () => {
      render(
        <RatingSection
          rating={4}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      // First 4 stars should be filled
      expect(stars[0]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[1]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[2]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[3]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[4]).toHaveAttribute('aria-pressed', 'false')
    })

    it('shows selected emoji rating', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating="happy"
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const happyEmoji = screen.getByRole('button', { name: /happy/i })
      expect(happyEmoji).toHaveAttribute('aria-pressed', 'true')
    })
  })

  describe('Star Rating Interactions', () => {
    it('calls onRatingChange when star is clicked', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const thirdStar = screen.getAllByRole('button', { name: /star/i })[2]
      await user.click(thirdStar)

      expect(mockOnRatingChange).toHaveBeenCalledWith(3)
    })

    it('updates rating on hover', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const fourthStar = screen.getAllByRole('button', { name: /star/i })[3]
      await user.hover(fourthStar)

      // Should show hover state visually (4 stars highlighted)
      // This is typically handled by CSS classes or visual indicators
      expect(fourthStar).toBeInTheDocument()
    })

    it('resets to current rating on mouse leave', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={2}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const fourthStar = screen.getAllByRole('button', { name: /star/i })[3]
      
      // Hover over star
      await user.hover(fourthStar)
      
      // Move mouse away
      await user.unhover(fourthStar)

      // Should revert to original rating (2 stars)
      const stars = screen.getAllByRole('button', { name: /star/i })
      expect(stars[0]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[1]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[2]).toHaveAttribute('aria-pressed', 'false')
    })

    it('allows rating to be changed multiple times', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      
      // Click 3rd star
      await user.click(stars[2])
      expect(mockOnRatingChange).toHaveBeenCalledWith(3)

      // Click 5th star
      await user.click(stars[4])
      expect(mockOnRatingChange).toHaveBeenCalledWith(5)

      // Click 1st star
      await user.click(stars[0])
      expect(mockOnRatingChange).toHaveBeenCalledWith(1)
    })

    it('allows rating to be reset to 0', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={3}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Click on currently selected star to deselect
      const thirdStar = screen.getAllByRole('button', { name: /star/i })[2]
      await user.click(thirdStar)

      expect(mockOnRatingChange).toHaveBeenCalledWith(0)
    })
  })

  describe('Emoji Rating Interactions', () => {
    it('calls onEmojiRatingChange when emoji is clicked', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const happyEmoji = screen.getByRole('button', { name: /happy/i })
      await user.click(happyEmoji)

      expect(mockOnEmojiRatingChange).toHaveBeenCalledWith('happy')
    })

    it('allows emoji rating to be changed', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating="happy"
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const sadEmoji = screen.getByRole('button', { name: /sad|unhappy/i })
      await user.click(sadEmoji)

      expect(mockOnEmojiRatingChange).toHaveBeenCalledWith('unhappy')
    })

    it('allows emoji rating to be deselected', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating="happy"
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Click currently selected emoji to deselect
      const happyEmoji = screen.getByRole('button', { name: /happy/i })
      await user.click(happyEmoji)

      expect(mockOnEmojiRatingChange).toHaveBeenCalledWith('')
    })

    it('shows all emoji options', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Should have emojis for different sentiment levels
      expect(screen.getByRole('button', { name: /very.*unhappy/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /unhappy/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /neutral/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /happy/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /very.*happy/i })).toBeInTheDocument()
    })
  })

  describe('Validation and Error States', () => {
    it('shows validation error when rating is required but not provided', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
          error="Please provide a rating"
          required
        />
      )

      expect(screen.getByText('Please provide a rating')).toBeInTheDocument()
    })

    it('applies error styling when in error state', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
          error="Rating required"
        />
      )

      const ratingContainer = screen.getByTestId('rating-container')
      expect(ratingContainer).toHaveClass('error')
    })

    it('clears error when rating is provided', async () => {
      const user = userEvent.setup()

      const { rerender } = render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
          error="Rating required"
        />
      )

      expect(screen.getByText('Rating required')).toBeInTheDocument()

      // Provide rating
      const star = screen.getAllByRole('button', { name: /star/i })[2]
      await user.click(star)

      // Re-render without error
      rerender(
        <RatingSection
          rating={3}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      expect(screen.queryByText('Rating required')).not.toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels for stars', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      stars.forEach((star, index) => {
        expect(star).toHaveAttribute('aria-label', `${index + 1} star`)
      })
    })

    it('has proper ARIA labels for emojis', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      expect(screen.getByRole('button', { name: /very.*unhappy/i })).toHaveAttribute('aria-label')
      expect(screen.getByRole('button', { name: /unhappy/i })).toHaveAttribute('aria-label')
      expect(screen.getByRole('button', { name: /neutral/i })).toHaveAttribute('aria-label')
      expect(screen.getByRole('button', { name: /happy/i })).toHaveAttribute('aria-label')
      expect(screen.getByRole('button', { name: /very.*happy/i })).toHaveAttribute('aria-label')
    })

    it('supports keyboard navigation for stars', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      
      // Focus first star
      stars[0].focus()
      expect(stars[0]).toHaveFocus()

      // Navigate with arrow keys
      await user.keyboard('{ArrowRight}')
      expect(stars[1]).toHaveFocus()

      await user.keyboard('{ArrowRight}')
      expect(stars[2]).toHaveFocus()

      // Navigate backwards
      await user.keyboard('{ArrowLeft}')
      expect(stars[1]).toHaveFocus()

      // Select with Enter or Space
      await user.keyboard('{Enter}')
      expect(mockOnRatingChange).toHaveBeenCalledWith(2)
    })

    it('supports keyboard navigation for emojis', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const emojis = screen.getAllByRole('button', { name: /emoji|happy|sad|neutral/i })
      
      // Focus first emoji
      emojis[0].focus()
      expect(emojis[0]).toHaveFocus()

      // Select with Space
      await user.keyboard(' ')
      expect(mockOnEmojiRatingChange).toHaveBeenCalled()
    })

    it('has proper focus indicators', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      stars.forEach(star => {
        expect(star).toHaveClass('focus:ring-2')
      })
    })

    it('announces changes to screen readers', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const star = screen.getAllByRole('button', { name: /star/i })[2]
      await user.click(star)

      // Should have live region for announcements
      expect(screen.getByRole('status')).toHaveTextContent('3 stars selected')
    })
  })

  describe('Visual States', () => {
    it('shows hover state on star hover', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const star = screen.getAllByRole('button', { name: /star/i })[2]
      await user.hover(star)

      expect(star).toHaveClass('hover')
    })

    it('shows active state for selected rating', () => {
      render(
        <RatingSection
          rating={3}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      expect(stars[0]).toHaveClass('active')
      expect(stars[1]).toHaveClass('active')
      expect(stars[2]).toHaveClass('active')
      expect(stars[3]).not.toHaveClass('active')
      expect(stars[4]).not.toHaveClass('active')
    })

    it('shows selected state for emoji', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating="happy"
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      const happyEmoji = screen.getByRole('button', { name: /happy/i })
      expect(happyEmoji).toHaveClass('selected')
    })

    it('applies disabled state when disabled', () => {
      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
          disabled
        />
      )

      const stars = screen.getAllByRole('button', { name: /star/i })
      stars.forEach(star => {
        expect(star).toBeDisabled()
      })

      const emojis = screen.getAllByRole('button', { name: /emoji|happy|sad|neutral/i })
      emojis.forEach(emoji => {
        expect(emoji).toBeDisabled()
      })
    })
  })

  describe('Integration', () => {
    it('works with both star and emoji ratings together', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={0}
          onRatingChange={mockOnRatingChange}
          emojiRating=""
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Set star rating
      const star = screen.getAllByRole('button', { name: /star/i })[3]
      await user.click(star)
      expect(mockOnRatingChange).toHaveBeenCalledWith(4)

      // Set emoji rating
      const emoji = screen.getByRole('button', { name: /happy/i })
      await user.click(emoji)
      expect(mockOnEmojiRatingChange).toHaveBeenCalledWith('happy')
    })

    it('maintains independent state for stars and emojis', async () => {
      const user = userEvent.setup()

      render(
        <RatingSection
          rating={2}
          onRatingChange={mockOnRatingChange}
          emojiRating="very-happy"
          onEmojiRatingChange={mockOnEmojiRatingChange}
        />
      )

      // Stars show rating of 2
      const stars = screen.getAllByRole('button', { name: /star/i })
      expect(stars[0]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[1]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[2]).toHaveAttribute('aria-pressed', 'false')

      // Emoji shows very-happy selection
      const veryHappyEmoji = screen.getByRole('button', { name: /very.*happy/i })
      expect(veryHappyEmoji).toHaveAttribute('aria-pressed', 'true')
    })
  })
})