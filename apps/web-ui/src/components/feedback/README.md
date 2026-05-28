# Feedback Widget System

A comprehensive feedback collection system for the Brain Researcher platform, built with Next.js, TypeScript, Tailwind CSS, and shadcn/ui components.

## Features

- **Floating Action Button**: Customizable position and appearance
- **Multi-step Form**: Guided feedback collection with validation
- **Screenshot Capture**: Automatic page screenshots with html-to-image
- **Category System**: Organized feedback types (bug reports, features, UI/UX, etc.)
- **Rating System**: Star ratings and emoji sentiment
- **Real-time Validation**: Form validation with helpful error messages
- **Success States**: Confirmation messages and submission tracking
- **Context Awareness**: Automatic URL, user agent, and metadata collection
- **Accessibility**: Full keyboard navigation and ARIA support
- **Responsive Design**: Mobile-friendly layouts
- **Dark Mode Support**: Seamless theme integration

## Quick Start

### Basic Usage

The feedback widget is already integrated into the main layout and will appear as a floating button in the bottom-right corner:

```tsx
// Already included in layout.tsx - no setup needed!
<FeedbackWidget />
```

### Custom Implementations

```tsx
import { FeedbackWidget, useFeedback } from '@/components/feedback'

// Inline feedback button
<FeedbackWidget variant="inline" showTrigger={false} customTrigger={
  <Button variant="outline">Send Feedback</Button>
} />

// Different position
<FeedbackWidget position="bottom-left" size="lg" />

// With callbacks and context
<FeedbackWidget
  context="User viewing dataset analysis page"
  onFeedbackSubmitted={(id) => analytics.track('feedback_submitted', { id })}
  onFeedbackOpened={() => analytics.track('feedback_opened')}
/>

// Programmatic usage
function MyComponent() {
  const { openFeedback, reportBug, requestFeature } = useFeedback()

  return (
    <div>
      <Button onClick={() => reportBug('Chart not rendering properly')}>
        Report Chart Bug
      </Button>
      <Button onClick={() => requestFeature('Need CSV export')}>
        Request Feature
      </Button>
    </div>
  )
}
```

## Component Architecture

### Core Components

- **`FeedbackWidget`**: Main component that includes trigger and dialog
- **`FeedbackTrigger`**: Floating action button with quick actions
- **`FeedbackDialog`**: Modal container for the feedback form
- **`FeedbackForm`**: Multi-step form with validation

### Form Sections

- **`RatingSection`**: Star ratings and emoji sentiment
- **`CategorySection`**: Feedback category selection
- **`CommentSection`**: Title and description inputs with templates
- **`ScreenshotCapture`**: Screenshot capture and upload
- **`SuccessMessage`**: Submission confirmation and next steps

### Hooks

- **`useFeedback`**: Main feedback logic and state management
- **`useFeedbackForm`**: Form state, validation, and submission
- **`useScreenshot`**: Screenshot capture functionality

### Context

- **`FeedbackProvider`**: Global feedback state management

## API Endpoints

### POST /api/feedback

Submit feedback data:

```typescript
{
  title: string
  description: string
  category: FeedbackCategory
  rating: number
  emojiRating?: EmojiRating
  screenshot?: File
  // Automatic fields
  userAgent: string
  url: string
  timestamp: string
}
```

Response:
```typescript
{
  success: boolean
  id?: string
  message?: string
  error?: string
}
```

### POST /api/feedback/screenshot

Upload screenshot files:

```typescript
FormData {
  screenshot: File
  feedbackId?: string
}
```

Response:
```typescript
{
  success: boolean
  url?: string
  error?: string
}
```

## Configuration

### Environment Variables

```env
# Feedback submission uses the same-origin Next.js routes:
#   POST /api/feedback
#   POST /api/feedback/screenshot
# Those routes proxy to the Orchestrator feedback widget endpoints, so no
# separate FEEDBACK_API_URL override is required.

# Optional: Webhook notifications
FEEDBACK_WEBHOOK_URL=https://your-webhook-url.com/feedback

# Optional: Slack notifications for urgent feedback
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Optional: Cloud storage for screenshots
CLOUD_STORAGE_PROVIDER=s3
CLOUD_STORAGE_BUCKET=feedback-screenshots
CLOUD_STORAGE_REGION=us-east-1
CLOUD_STORAGE_ACCESS_KEY_ID=your-access-key
CLOUD_STORAGE_SECRET_ACCESS_KEY=your-secret-key
```

### Customization

```tsx
// Custom styling
<FeedbackWidget 
  position="top-right"
  size="sm"
  variant="minimal"
  customIcon={<MessageCircle />}
/>

// Custom categories
const customCategories = {
  'data-issue': {
    label: 'Data Problem',
    description: 'Issues with neuroimaging data',
    icon: '🧠'
  }
}

// Custom validation rules
<FeedbackForm
  minDescriptionLength={20}
  maxDescriptionLength={1000}
  requireScreenshot={true}
/>
```

## Feedback Categories

| Category | Description | Recommended For |
|----------|-------------|-----------------|
| `bug-report` | Something is broken | Errors, crashes, unexpected behavior |
| `feature-request` | New functionality | Enhancement ideas, missing features |
| `ui-ux` | Design issues | Layout problems, confusing interfaces |
| `performance` | Speed/responsiveness | Slow loading, lag, timeouts |
| `content` | Data accuracy | Incorrect information, missing data |
| `accessibility` | A11y concerns | Screen reader issues, keyboard navigation |
| `other` | General feedback | Anything else |

## Best Practices

### For Developers

1. **Context Matters**: Always provide context when programmatically opening feedback
2. **Category Hints**: Pre-select appropriate categories when possible
3. **Error Boundaries**: Wrap feedback components in error boundaries
4. **Analytics**: Track feedback interactions for product insights

```tsx
// Good: Contextual feedback
<Button onClick={() => reportBug(`Chart rendering failed on dataset ${datasetId}`)}>
  Report Issue
</Button>

// Better: With full context
<Button onClick={() => openFeedback('bug-report', {
  context: `User attempted to render ${chartType} chart for dataset ${datasetId}`,
  metadata: { datasetId, chartType, filters: activeFilters }
})}>
  Report Issue
</Button>
```

### For Users

1. **Be Specific**: Include steps to reproduce bugs
2. **Add Screenshots**: Visual context helps tremendously
3. **Provide Context**: Mention what you were trying to accomplish
4. **Check Existing**: Look for similar feedback before submitting

## Troubleshooting

### Common Issues

**Screenshot capture not working:**
- Ensure `html-to-image` is installed
- Check browser permissions for clipboard access
- Verify HTTPS context for security features

**Form validation errors:**
- Check minimum field requirements (title, description, rating)
- Verify character limits (title: 100, description: 2000)
- Ensure category selection is valid

**API submission failures:**
- Check network connectivity
- Verify API endpoint configuration
- Review browser console for detailed errors

### Debug Mode

Enable debug logging:

```tsx
<FeedbackProvider debug={true}>
  <App />
</FeedbackProvider>
```

## Accessibility

The feedback widget follows WCAG 2.1 AA guidelines:

- **Keyboard Navigation**: Full keyboard support with logical tab order
- **Screen Readers**: Comprehensive ARIA labels and descriptions
- **Color Contrast**: Meets 4.5:1 contrast ratios
- **Focus Management**: Clear focus indicators and proper focus trap
- **Semantic HTML**: Proper heading hierarchy and form structure

## Performance

- **Lazy Loading**: Components load only when needed
- **Image Optimization**: Screenshot compression and resizing
- **Bundle Size**: Tree-shakeable exports minimize impact
- **Caching**: API responses cached where appropriate

## Security

- **Input Sanitization**: All user input sanitized
- **File Validation**: Screenshot uploads validated by type and size
- **Rate Limiting**: API endpoints include rate limiting
- **CSRF Protection**: Next.js built-in CSRF protection

## Contributing

When adding new features:

1. Update TypeScript types in `/types/feedback.ts`
2. Add comprehensive tests for new components
3. Update this documentation
4. Follow existing code patterns and styling
5. Ensure accessibility compliance

## License

This feedback system is part of the Brain Researcher platform and follows the same license terms.
