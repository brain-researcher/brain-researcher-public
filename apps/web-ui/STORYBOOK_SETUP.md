# Storybook Documentation Setup

This document provides setup instructions and usage guidelines for the Brain Researcher UI Storybook documentation system.

## Quick Start

### Prerequisites
- Node.js 18+ 
- npm or yarn package manager
- Brain Researcher UI project setup

### Installation
Dependencies are already included in package.json. Install them with:

```bash
npm install
# or
yarn install
```

### Running Storybook

```bash
# Development mode
npm run storybook
# or
yarn storybook

# Build for production
npm run build-storybook
# or  
yarn build-storybook
```

The development server will start on `http://localhost:6006`

## Project Structure

```
apps/web-ui/
├── .storybook/                 # Storybook configuration
│   ├── main.ts                # Main configuration
│   └── preview.tsx            # Global decorators and parameters
├── src/
│   ├── stories/               # Story files and documentation
│   │   ├── Introduction.mdx   # Welcome page
│   │   ├── DesignTokens.mdx   # Design system documentation
│   │   ├── components/        # Component stories
│   │   │   ├── Button.stories.tsx
│   │   │   ├── ResultDisplay.stories.tsx
│   │   │   ├── KnowledgeGraph.stories.tsx
│   │   │   ├── KPICard.stories.tsx
│   │   │   ├── Chat.stories.tsx
│   │   │   └── Dashboard.stories.tsx
│   │   └── guidelines/        # Usage documentation
│   │       ├── BestPractices.mdx
│   │       └── Accessibility.mdx
│   └── components/            # Actual React components
└── package.json               # Dependencies and scripts
```

## Key Features

### 1. Component Documentation
- **Interactive Examples**: All component variants with live controls
- **Props Documentation**: Auto-generated from TypeScript interfaces  
- **Usage Examples**: Real-world scenarios for scientific contexts
- **Accessibility Testing**: Built-in a11y addon for compliance checking

### 2. Design System Documentation
- **Design Tokens**: Colors, typography, spacing scales
- **Scientific Context**: Brain imaging color schemes, statistical displays
- **Theme Support**: Light/dark mode with proper contrast ratios
- **Responsive Design**: Mobile-first approach with breakpoint documentation

### 3. Developer Experience
- **Hot Reload**: Instant updates during development
- **TypeScript Support**: Full type safety and IntelliSense
- **MDX Documentation**: Rich markdown with embedded components
- **Export Functionality**: Generate static documentation site

## Available Addons

### Essential Addons
- **@storybook/addon-docs**: Auto-generated documentation
- **@storybook/addon-controls**: Interactive prop controls
- **@storybook/addon-actions**: Event logging and debugging
- **@storybook/addon-viewport**: Responsive design testing

### Accessibility & Quality
- **@storybook/addon-a11y**: Accessibility compliance checking
- **@storybook/addon-interactions**: User interaction testing

## Component Story Structure

Each story file follows this pattern:

```typescript
import type { Meta, StoryObj } from '@storybook/react';
import { ComponentName } from '@/components/path/ComponentName';

const meta = {
  title: 'Components/ComponentName',
  component: ComponentName,
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component: 'Component description here...'
      }
    }
  },
  tags: ['autodocs'],
  argTypes: {
    // Prop documentation
  }
} satisfies Meta<typeof ComponentName>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    // Default props
  }
};

export const Variant: Story = {
  args: {
    // Variant props
  },
  parameters: {
    docs: {
      description: {
        story: 'Story description...'
      }
    }
  }
};
```

## Scientific Component Examples

### Brain Imaging Results
```typescript
// ResultDisplay.stories.tsx shows:
- fMRI statistical maps
- ROI analysis tables  
- JSON configuration files
- Analysis reports
```

### Knowledge Graphs
```typescript
// KnowledgeGraph.stories.tsx demonstrates:
- Brain region relationships
- Author collaboration networks
- Study interconnections
- Large network performance
```

### Analytics Dashboards
```typescript
// Dashboard.stories.tsx includes:
- Research KPI monitoring
- System performance metrics
- Collaborative workflows
- Customizable layouts
```

## Accessibility Documentation

### Testing Features
- **Automatic Scanning**: axe-core integration for WCAG compliance
- **Keyboard Navigation**: Tab order and shortcut testing
- **Screen Reader Support**: ARIA attributes and semantic markup
- **Color Contrast**: Automatic contrast ratio validation

### Implementation Guidelines
- All components include accessibility examples
- Scientific data visualization accessibility patterns
- Mobile touch target compliance
- Reduced motion support

## Customization

### Theme Configuration
Storybook inherits the project's theme system:

```typescript
// .storybook/preview.tsx
globalTypes: {
  theme: {
    description: 'Global theme for components',
    defaultValue: 'light',
    toolbar: {
      title: 'Theme',
      items: [
        { value: 'light', title: 'Light' },
        { value: 'dark', title: 'Dark' }
      ]
    }
  }
}
```

### Viewport Settings
Pre-configured breakpoints for scientific applications:

```typescript
viewport: {
  viewports: {
    mobile: { styles: { width: '375px', height: '667px' } },
    tablet: { styles: { width: '768px', height: '1024px' } },
    desktop: { styles: { width: '1024px', height: '768px' } },
    wide: { styles: { width: '1440px', height: '900px' } }
  }
}
```

## Development Workflow

### Adding New Components

1. **Create Component**: Build your React component with TypeScript
2. **Write Stories**: Create comprehensive stories showing all variants
3. **Document Usage**: Include scientific context and best practices  
4. **Test Accessibility**: Verify WCAG compliance with built-in tools
5. **Update Guidelines**: Add patterns to best practices documentation

### Story Best Practices

```typescript
// Include multiple variants
export const AllVariants: Story = {
  render: () => (
    <div className="flex gap-4">
      <Component variant="primary" />
      <Component variant="secondary" />
      <Component variant="destructive" />
    </div>
  )
};

// Scientific context
export const ResearchExample: Story = {
  args: {
    data: mockFMRIData
  },
  parameters: {
    docs: {
      description: {
        story: 'Real-world example showing fMRI activation analysis...'
      }
    }
  }
};

// Accessibility demonstration
export const AccessibilityFeatures: Story = {
  render: () => (
    <div>
      <Component aria-label="Descriptive label" />
      <div id="help-text">Helpful context</div>
    </div>
  )
};
```

## Production Deployment

### Build Process
```bash
# Generate static Storybook site
npm run build-storybook

# Output directory: storybook-static/
# Deploy to any static hosting service
```

### Integration Options
- **GitHub Pages**: Automated deployment via GitHub Actions
- **Netlify**: Drag and drop deployment or git integration  
- **Vercel**: Zero-configuration deployment
- **Internal Hosting**: Self-hosted documentation portal

## Maintenance

### Regular Tasks
- **Component Updates**: Keep stories synchronized with component changes
- **Accessibility Audits**: Run a11y tests on new components
- **Documentation Review**: Ensure scientific context remains accurate
- **Dependency Updates**: Keep Storybook and addons current

### Monitoring
- Check build status in CI/CD pipeline
- Monitor accessibility compliance scores
- Review user feedback on component usage
- Track documentation page views and engagement

## Troubleshooting

### Common Issues

**Storybook won't start:**
```bash
# Clear cache and reinstall
rm -rf node_modules .next
npm install
npm run storybook
```

**CSS not loading:**
- Verify CSS imports in `.storybook/preview.tsx`
- Check Tailwind CSS configuration
- Ensure path aliases are configured correctly

**TypeScript errors:**
- Check component exports and imports
- Verify story type definitions
- Update `@storybook/nextjs` if using Next.js features

**Accessibility violations:**
- Review component ARIA attributes
- Check color contrast ratios
- Verify keyboard navigation support
- Test with actual screen readers

### Getting Help

- **Storybook Documentation**: https://storybook.js.org/docs
- **Accessibility Guidelines**: See `stories/guidelines/Accessibility.mdx`
- **Component Examples**: Browse existing stories for patterns
- **Team Support**: Contact the development team for component-specific questions
