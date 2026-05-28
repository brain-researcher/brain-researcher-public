# Help System Documentation

The Brain Researcher Help System provides comprehensive guidance and support for users through interactive tours, contextual help, video tutorials, and searchable documentation.

## Components Overview

### 1. HelpSystem (Main Component)
- **File**: `HelpSystem.tsx`
- **Purpose**: Main coordinator for the entire help system
- **Features**:
  - Tabbed interface with Overview, Tours, Videos, Search, and Settings
  - Tour progress tracking
  - Onboarding status display
  - Help preferences management
  - Keyboard shortcuts display

### 2. InteractiveTour
- **File**: `InteractiveTour.tsx`
- **Purpose**: Provides step-by-step guided tours
- **Features**:
  - Custom tour implementation (no external dependencies)
  - Element highlighting with spotlight effect
  - Navigation controls (next, previous, skip)
  - Keyboard navigation support
  - Progress tracking
  - Automatic element scrolling

### 3. ContextualHelp
- **File**: `ContextualHelp.tsx`
- **Purpose**: Tooltip-based contextual help system
- **Features**:
  - Automatic help icon injection
  - Hover-triggered tooltips with delay
  - Category-based styling
  - Related tour integration
  - Viewport-aware positioning

### 4. VideoGuide
- **File**: `VideoGuide.tsx`
- **Purpose**: Embedded video tutorials interface
- **Features**:
  - Video library with categories and difficulty levels
  - Search and filtering
  - YouTube/Vimeo embedding
  - Related tour integration
  - Bookmark functionality
  - Rating and view tracking

### 5. OnboardingFlow
- **File**: `OnboardingFlow.tsx`
- **Purpose**: New user onboarding experience
- **Features**:
  - Progressive step completion
  - Progress tracking and persistence
  - Welcome dialog for new users
  - Floating progress indicator
  - Integration with tours and navigation

### 6. HelpSearch
- **File**: `HelpSearch.tsx`
- **Purpose**: Searchable documentation interface
- **Features**:
  - Full-text search across help content
  - Type and category filtering
  - Popular searches suggestions
  - Result highlighting
  - Analytics tracking

## Hooks

### useHelp
- **File**: `../../hooks/use-help.ts`
- **Purpose**: Central state management for help system
- **Features**:
  - Tour management (start, stop, complete)
  - Onboarding progress tracking
  - Local storage persistence
  - Keyboard shortcuts handling
  - Search functionality
  - Analytics tracking

## Usage Examples

### Basic Help System Integration
```jsx
import { HelpSystem } from '@/components/help'

export function MyComponent() {
  return (
    <div>
      {/* Your component content */}
      <HelpSystem showHelpButton={true} />
    </div>
  )
}
```

### Adding Contextual Help
```jsx
import { HelpTrigger } from '@/components/help'

export function NavigationBar() {
  return (
    <nav data-tour="navigation" data-help="navigation">
      <HelpTrigger helpId="navigation">
        <button>Menu</button>
      </HelpTrigger>
    </nav>
  )
}
```

### Using Help Hooks
```jsx
import { useHelp } from '@/components/help'

export function MyFeature() {
  const { startTour, isHelpOpen, toggleHelp } = useHelp()
  
  return (
    <div>
      <button onClick={() => startTour('welcome')}>
        Start Tutorial
      </button>
    </div>
  )
}
```

## Tour Configuration

Tours are defined in the `use-help.ts` hook as the `TOURS` object:

```typescript
export const TOURS: Record<string, Tour> = {
  'welcome': {
    id: 'welcome',
    name: 'Welcome to Brain Researcher',
    description: 'Get started with the platform basics',
    category: 'onboarding',
    estimatedTime: 5,
    steps: [
      {
        target: 'body',
        content: 'Welcome message...',
        title: 'Welcome!',
        placement: 'center',
        disableBeacon: true,
      },
      // More steps...
    ],
  },
  // More tours...
}
```

### Tour Step Properties
- `target`: CSS selector for the element to highlight
- `content`: Step description text
- `title`: Optional step title
- `placement`: Tooltip position ('top', 'bottom', 'left', 'right', 'center')
- `disableBeacon`: Whether to disable the pulsing beacon

## Contextual Help Content

Help tooltips are defined in `ContextualHelp.tsx` as the `HELP_TOOLTIPS` object:

```typescript
const HELP_TOOLTIPS: Record<string, TooltipContent> = {
  'navigation': {
    id: 'navigation',
    title: 'Main Navigation',
    description: 'Access all main features...',
    category: 'feature',
    learnMoreUrl: '/docs/navigation',
    relatedTourId: 'welcome',
  },
  // More tooltips...
}
```

## Data Attributes

### Tour Integration
- `data-tour="element-id"`: Marks an element as a tour target
- `data-help="tooltip-id"`: Marks an element for contextual help

Example:
```jsx
<button 
  data-tour="search" 
  data-help="search"
  className="search-button"
>
  Search
</button>
```

## Keyboard Shortcuts

The help system responds to several keyboard shortcuts:

- **F1**: Open/close help dialog
- **Ctrl + ?**: Alternative help shortcut
- **Escape**: Close help dialog or stop tour
- **Arrow Keys**: Navigate tour steps (when tour is active)
- **Enter**: Next tour step

## Styling and Theming

### CSS Classes
- `.tour-highlight`: Applied to highlighted tour elements
- `.help-icon`: Injected help icons
- `.contextual-tooltip`: Tooltip containers
- `.help-dialog`: Main help dialog
- `.onboarding-progress`: Progress bars

### Custom Properties
The help system respects system preferences:
- Dark mode support
- High contrast mode
- Reduced motion
- Screen reader compatibility

## Analytics and Tracking

The help system tracks user interactions for improvement:

```typescript
interface HelpAnalytics {
  searchQueries: string[]
  viewedContent: string[]
  completedTours: string[]
}
```

## Accessibility Features

- **Keyboard Navigation**: Full keyboard support
- **ARIA Labels**: Proper labeling for screen readers  
- **Focus Management**: Logical focus flow during tours
- **Color Contrast**: High contrast mode support
- **Screen Reader**: Compatible with assistive technologies

## Performance Considerations

- **Lazy Loading**: Components load on demand
- **Memoization**: React.memo for performance optimization
- **Local Storage**: Efficient state persistence
- **Bundle Size**: Minimal external dependencies

## Mobile Responsiveness

- **Responsive Dialogs**: Adapt to screen size
- **Touch-Friendly**: Large touch targets
- **Mobile Navigation**: Optimized mobile experience
- **Gesture Support**: Touch gestures for tour navigation

## Configuration Options

### Environment Variables
- `HELP_ANALYTICS_ENABLED`: Enable/disable analytics tracking
- `HELP_VIDEO_PROVIDER`: Video provider (youtube/vimeo)
- `HELP_SEARCH_ENDPOINT`: Custom search API endpoint

### Local Storage Keys
- `help-state`: Main help system state
- `onboarding-dismissed`: Onboarding dismissal flag
- `tour-completions`: Completed tours tracking

## Testing

### Unit Tests
Located in `/tests/unit/test_help_system.py`:
- Component rendering tests
- State management tests
- User interaction tests
- Accessibility tests

### E2E Tests
- Tour completion flows
- Help search functionality
- Cross-browser compatibility
- Mobile device testing

## Troubleshooting

### Common Issues

1. **Tour elements not highlighting**
   - Check CSS selector accuracy
   - Ensure elements exist when tour starts
   - Verify z-index conflicts

2. **Tooltips not appearing**
   - Confirm `data-help` attribute is set
   - Check tooltip content is defined
   - Verify hover delays are appropriate

3. **Tours not progressing**
   - Check for JavaScript errors
   - Verify tour step configuration
   - Ensure proper event handling

### Debug Mode
Enable debug logging:
```javascript
localStorage.setItem('help-debug', 'true')
```

## Contributing

### Adding New Tours
1. Define tour in `TOURS` object
2. Add data-tour attributes to target elements
3. Test tour flow thoroughly
4. Update documentation

### Adding New Help Content
1. Add content to appropriate component
2. Update search indexing if needed
3. Add analytics tracking
4. Test across devices

### Adding New Features
1. Follow existing component patterns
2. Add comprehensive tests
3. Update documentation
4. Consider accessibility impact

## Future Enhancements

- [ ] Multi-language support
- [ ] Video transcript integration
- [ ] Advanced analytics dashboard
- [ ] User-generated help content
- [ ] AI-powered help suggestions
- [ ] Collaborative tour creation
- [ ] Integration with external documentation
- [ ] Voice-guided tours
- [ ] Augmented reality help overlays
- [ ] Personalized learning paths

## API Reference

### HelpSystem Props
```typescript
interface HelpSystemProps {
  showHelpButton?: boolean
  className?: string
}
```

### useHelp Return Value
```typescript
interface UseHelpReturn {
  // State
  isHelpOpen: boolean
  currentTour: string | null
  tourRunning: boolean
  showTooltips: boolean
  onboardingProgress: OnboardingProgress
  
  // Actions
  toggleHelp: () => void
  startTour: (tourId: string) => void
  completeTour: (tourId: string) => void
  stopTour: () => void
  toggleTooltips: () => void
  searchHelp: (query: string) => void
  
  // Data
  tours: Record<string, Tour>
  searchResults: HelpContent[]
}
```

---

For more detailed information, refer to the individual component files and their inline documentation.