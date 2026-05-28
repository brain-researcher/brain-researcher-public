// Main feedback widget components
export { FeedbackWidget, default } from './FeedbackWidget'
export { FeedbackDialog } from './FeedbackDialog'
export { FeedbackTrigger } from './FeedbackTrigger'
export { FeedbackForm } from './FeedbackForm'

// Sub-components
export { RatingSection } from './components/RatingSection'
export { CategorySection } from './components/CategorySection'
export { CommentSection } from './components/CommentSection'
export { ScreenshotCapture } from './components/ScreenshotCapture'
export { SuccessMessage } from './components/SuccessMessage'

// Hooks
export { useFeedback } from '../../hooks/useFeedback'
export { useFeedbackForm } from '../../hooks/useFeedbackForm'
export { useScreenshot } from '../../hooks/useScreenshot'

// Context
export { FeedbackProvider, useFeedbackContext } from '../../contexts/FeedbackContext'

// Types
export * from '../../types/feedback'