'use client'

import { useState, useCallback, useEffect } from 'react'
import { FeedbackFormData, FeedbackCategory, EmojiRating } from '@/types/feedback'

interface ValidationErrors {
  rating?: string
  category?: string
  title?: string
  description?: string
}

interface UseFeedbackFormOptions {
  initialCategory?: FeedbackCategory
  requireScreenshot?: boolean
  minDescriptionLength?: number
  maxDescriptionLength?: number
}

export function useFeedbackForm(options: UseFeedbackFormOptions = {}) {
  const {
    initialCategory,
    requireScreenshot = false,
    minDescriptionLength = 10,
    maxDescriptionLength = 2000
  } = options

  // Form state
  const [formData, setFormData] = useState<FeedbackFormData>({
    rating: 0,
    emojiRating: undefined,
    category: initialCategory || 'bug-report',
    title: '',
    description: '',
    screenshot: null
  })

  // Validation and UI state
  const [errors, setErrors] = useState<ValidationErrors>({})
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [isValid, setIsValid] = useState(false)

  // Update form field
  const updateField = useCallback(<K extends keyof FeedbackFormData>(
    field: K,
    value: FeedbackFormData[K]
  ) => {
    setFormData(prev => ({ ...prev, [field]: value }))
    
    // Mark field as touched
    setTouched(prev => new Set(prev.add(field)))

    // Clear field-specific error when user starts typing
    if (errors[field as keyof ValidationErrors]) {
      setErrors(prev => ({ ...prev, [field]: undefined }))
    }
  }, [errors])

  // Validation logic
  const validateField = useCallback((field: keyof FeedbackFormData, value: any): string | undefined => {
    switch (field) {
      case 'rating':
        if (typeof value !== 'number' || value < 1 || value > 5) {
          return 'Please provide a rating between 1 and 5'
        }
        break
      
      case 'category':
        if (!value || typeof value !== 'string') {
          return 'Please select a feedback category'
        }
        break
      
      case 'title':
        if (!value || typeof value !== 'string' || value.trim().length === 0) {
          return 'Please provide a title for your feedback'
        }
        if (value.trim().length > 100) {
          return 'Title must be 100 characters or less'
        }
        break
      
      case 'description':
        if (!value || typeof value !== 'string' || value.trim().length === 0) {
          return 'Please provide a description'
        }
        if (value.trim().length < minDescriptionLength) {
          return `Description must be at least ${minDescriptionLength} characters`
        }
        if (value.trim().length > maxDescriptionLength) {
          return `Description must be ${maxDescriptionLength} characters or less`
        }
        break
      
      case 'screenshot':
        if (requireScreenshot && !value) {
          return 'A screenshot is required for this type of feedback'
        }
        break
    }
    
    return undefined
  }, [minDescriptionLength, maxDescriptionLength, requireScreenshot])

  // Validate all fields
  const validateForm = useCallback((): ValidationErrors => {
    const newErrors: ValidationErrors = {}
    
    // Validate each field
    Object.keys(formData).forEach(key => {
      const field = key as keyof FeedbackFormData
      const error = validateField(field, formData[field])
      if (error) {
        newErrors[field as keyof ValidationErrors] = error
      }
    })
    
    return newErrors
  }, [formData, validateField])

  // Update validation state when form data changes
  useEffect(() => {
    const newErrors = validateForm()
    setErrors(newErrors)
    setIsValid(Object.keys(newErrors).length === 0)
  }, [formData, validateForm])

  // Handle form submission
  const handleSubmit = useCallback(async (
    submitFn: (data: FeedbackFormData) => Promise<void>
  ) => {
    // Mark all fields as touched
    const allFields = Object.keys(formData)
    setTouched(new Set(allFields))

    // Validate form
    const validationErrors = validateForm()
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      throw new Error('Please fix validation errors before submitting')
    }

    // Submit form
    await submitFn(formData)
  }, [formData, validateForm])

  // Reset form
  const resetForm = useCallback(() => {
    setFormData({
      rating: 0,
      emojiRating: undefined,
      category: initialCategory || 'bug-report',
      title: '',
      description: '',
      screenshot: null
    })
    setErrors({})
    setTouched(new Set())
  }, [initialCategory])

  // Helper methods
  const setRating = useCallback((rating: number) => {
    updateField('rating', rating)
  }, [updateField])

  const setEmojiRating = useCallback((emoji: EmojiRating) => {
    updateField('emojiRating', emoji)
  }, [updateField])

  const setCategory = useCallback((category: FeedbackCategory) => {
    updateField('category', category)
  }, [updateField])

  const setTitle = useCallback((title: string) => {
    updateField('title', title)
  }, [updateField])

  const setDescription = useCallback((description: string) => {
    updateField('description', description)
  }, [updateField])

  const setScreenshot = useCallback((screenshot: File | null) => {
    updateField('screenshot', screenshot)
  }, [updateField])

  // Character counts for UI
  const titleCharCount = formData.title.length
  const descriptionCharCount = formData.description.length
  const titleRemaining = 100 - titleCharCount
  const descriptionRemaining = maxDescriptionLength - descriptionCharCount

  return {
    // Form data
    formData,
    
    // Validation state
    errors,
    touched,
    isValid,
    
    // Field updaters
    setRating,
    setEmojiRating,
    setCategory,
    setTitle,
    setDescription,
    setScreenshot,
    updateField,
    
    // Form actions
    handleSubmit,
    resetForm,
    validateField,
    
    // Character counts
    titleCharCount,
    descriptionCharCount,
    titleRemaining,
    descriptionRemaining,
    
    // Computed properties
    hasErrors: Object.keys(errors).length > 0,
    isFieldTouched: (field: string) => touched.has(field),
    getFieldError: (field: keyof ValidationErrors) => touched.has(field) ? errors[field] : undefined
  }
}