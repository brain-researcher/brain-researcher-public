export interface FeedbackFormData {
  rating: number
  emojiRating?: string
  category: FeedbackCategory
  title: string
  description: string
  screenshot?: File | null
  userAgent?: string
  url?: string
  userId?: string
  sessionId?: string
  timestamp?: string
}

export interface FeedbackSubmission extends FeedbackFormData {
  id: string
  status: 'pending' | 'submitted' | 'error'
  screenshotUrl?: string
  retryCount: number
  createdAt: string
  updatedAt: string
}

export type FeedbackCategory = 
  | 'bug-report'
  | 'feature-request'
  | 'ui-ux'
  | 'performance'
  | 'content'
  | 'accessibility'
  | 'other'

export type EmojiRating = 
  | 'very-unhappy'
  | 'unhappy'
  | 'neutral' 
  | 'happy'
  | 'very-happy'

export interface FeedbackTriggerProps {
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
  size?: 'sm' | 'md' | 'lg'
  variant?: 'floating' | 'inline' | 'minimal'
  disabled?: boolean
  customIcon?: React.ReactNode
}

export interface FeedbackDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  initialCategory?: FeedbackCategory
  context?: string
  onSubmit?: (data: FeedbackFormData) => Promise<void>
}

export interface FeedbackFormProps {
  onSubmit: (data: FeedbackFormData) => Promise<void>
  onCancel: () => void
  initialCategory?: FeedbackCategory
  context?: string
  isSubmitting?: boolean
}

export interface ScreenshotOptions {
  quality?: number
  includeFullPage?: boolean
  excludeSelectors?: string[]
  maskSensitiveData?: boolean
}

export interface FeedbackContext {
  isOpen: boolean
  setIsOpen: (open: boolean) => void
  submitFeedback: (data: FeedbackFormData) => Promise<void>
  isSubmitting: boolean
  lastSubmission?: FeedbackSubmission
  error?: string | null
}

export interface UseFeedbackOptions {
  autoCapture?: boolean
  enableScreenshots?: boolean
  maxRetries?: number
  submitTimeout?: number
}

export interface FeedbackAPIResponse {
  success: boolean
  id?: string
  message?: string
  error?: string
}

export interface ScreenshotUploadResponse {
  success: boolean
  url?: string
  error?: string
}

export const FEEDBACK_CATEGORIES: Record<FeedbackCategory, {
  label: string
  description: string
  icon: string
}> = {
  'bug-report': {
    label: 'Bug Report',
    description: 'Something is not working as expected',
    icon: '🐛'
  },
  'feature-request': {
    label: 'Feature Request',
    description: 'Suggest a new feature or enhancement',
    icon: '💡'
  },
  'ui-ux': {
    label: 'UI/UX',
    description: 'Issues with design or user experience',
    icon: '🎨'
  },
  'performance': {
    label: 'Performance',
    description: 'App feels slow or unresponsive',
    icon: '⚡'
  },
  'content': {
    label: 'Content',
    description: 'Issues with data or content accuracy',
    icon: '📝'
  },
  'accessibility': {
    label: 'Accessibility',
    description: 'Difficulty using with assistive technologies',
    icon: '♿'
  },
  'other': {
    label: 'Other',
    description: 'Something else',
    icon: '💬'
  }
}

export const EMOJI_RATINGS: Record<EmojiRating, {
  emoji: string
  label: string
  value: number
}> = {
  'very-unhappy': {
    emoji: '😭',
    label: 'Very Unhappy',
    value: 1
  },
  'unhappy': {
    emoji: '😞',
    label: 'Unhappy',
    value: 2
  },
  'neutral': {
    emoji: '😐',
    label: 'Neutral',
    value: 3
  },
  'happy': {
    emoji: '😊',
    label: 'Happy',
    value: 4
  },
  'very-happy': {
    emoji: '😍',
    label: 'Very Happy',
    value: 5
  }
}