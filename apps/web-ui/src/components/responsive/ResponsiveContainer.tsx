'use client'

import React from 'react'
import { cn } from '@/lib/utils'
import { MOBILE_FIRST_BREAKPOINTS } from './ResponsiveGrid'

type ContainerSize = 'mobile' | 'tablet' | 'desktop' | 'wide' | 'full' | 'none'

interface ResponsiveContainerProps {
  children: React.ReactNode
  maxWidth?: ContainerSize
  className?: string
  fluid?: boolean
  paddingX?: boolean | 'sm' | 'md' | 'lg'
  paddingY?: boolean | 'sm' | 'md' | 'lg'
  centerContent?: boolean
  as?: keyof JSX.IntrinsicElements
  id?: string
  role?: string
  'aria-label'?: string
  'data-testid'?: string
}

/**
 * Responsive container with mobile-first fluid layouts
 * Provides consistent spacing and max-widths across breakpoints
 */
export function ResponsiveContainer({
  children,
  maxWidth = 'desktop',
  className,
  fluid = false,
  paddingX = 'md',
  paddingY = false,
  centerContent = true,
  as: Component = 'div',
  id,
  role,
  'aria-label': ariaLabel,
  'data-testid': testId = 'responsive-container'
}: ResponsiveContainerProps) {
  
  // Get max-width classes based on container size
  const getMaxWidthClasses = () => {
    if (fluid || maxWidth === 'full') return 'w-full'
    if (maxWidth === 'none') return ''
    
    const maxWidthMap = {
      mobile: 'max-w-sm',     // ~384px
      tablet: 'max-w-2xl',   // ~672px  
      desktop: 'max-w-6xl',  // ~1152px
      wide: 'max-w-7xl'      // ~1280px
    }
    
    return maxWidthMap[maxWidth] || maxWidthMap.desktop
  }

  // Get horizontal padding classes
  const getPaddingXClasses = () => {
    if (!paddingX) return ''
    if (paddingX === true) paddingX = 'md'
    
    const paddingMap = {
      sm: 'px-4 sm:px-6',
      md: 'px-4 sm:px-6 lg:px-8',
      lg: 'px-6 sm:px-8 lg:px-12'
    }
    
    return paddingMap[paddingX] || paddingMap.md
  }

  // Get vertical padding classes  
  const getPaddingYClasses = () => {
    if (!paddingY) return ''
    if (paddingY === true) paddingY = 'md'
    
    const paddingMap = {
      sm: 'py-4 sm:py-6',
      md: 'py-6 sm:py-8 lg:py-12',
      lg: 'py-8 sm:py-12 lg:py-16'
    }
    
    return paddingMap[paddingY] || paddingMap.md
  }

  const containerClasses = cn(
    'responsive-container',
    getMaxWidthClasses(),
    centerContent && 'mx-auto',
    getPaddingXClasses(),
    getPaddingYClasses(),
    className
  )

  return (
    <Component
      id={id}
      role={role}
      aria-label={ariaLabel}
      data-testid={testId}
      className={containerClasses}
    >
      {children}
    </Component>
  )
}

/**
 * Section container with semantic structure
 */
export function ResponsiveSection({
  children,
  maxWidth = 'desktop',
  paddingY = 'lg',
  className,
  ...props
}: Omit<ResponsiveContainerProps, 'as'> & {
  'aria-labelledby'?: string
}) {
  return (
    <ResponsiveContainer
      as="section"
      maxWidth={maxWidth}
      paddingY={paddingY}
      className={className}
      {...props}
    >
      {children}
    </ResponsiveContainer>
  )
}

/**
 * Article container with reading-optimized width
 */
export function ResponsiveArticle({
  children,
  className,
  ...props
}: Omit<ResponsiveContainerProps, 'as' | 'maxWidth'>) {
  return (
    <ResponsiveContainer
      as="article"
      maxWidth="tablet" // Optimal reading width
      className={cn('prose prose-gray dark:prose-invert max-w-none', className)}
      {...props}
    >
      {children}
    </ResponsiveContainer>
  )
}

/**
 * Header container with full-width background support
 */
export function ResponsiveHeader({
  children,
  background = true,
  sticky = false,
  className,
  ...props
}: Omit<ResponsiveContainerProps, 'as'> & {
  background?: boolean
  sticky?: boolean
}) {
  return (
    <header
      className={cn(
        background && 'bg-white dark:bg-gray-900 shadow-sm border-b border-gray-200 dark:border-gray-800',
        sticky && 'sticky top-0 z-40',
        'w-full'
      )}
    >
      <ResponsiveContainer
        paddingY="sm" 
        className={className}
        {...props}
      >
        {children}
      </ResponsiveContainer>
    </header>
  )
}

/**
 * Footer container with full-width background
 */
export function ResponsiveFooter({
  children,
  className,
  ...props
}: Omit<ResponsiveContainerProps, 'as'>) {
  return (
    <footer className="bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800">
      <ResponsiveContainer
        paddingY="lg"
        className={className}
        {...props}
      >
        {children}
      </ResponsiveContainer>
    </footer>
  )
}

/**
 * Card container with responsive padding and styling
 */
export function ResponsiveCard({
  children,
  variant = 'default',
  interactive = false,
  className,
  onClick,
  ...props
}: Omit<ResponsiveContainerProps, 'maxWidth' | 'centerContent'> & {
  variant?: 'default' | 'outlined' | 'elevated' | 'ghost'
  interactive?: boolean
  onClick?: () => void
}) {
  const getVariantClasses = () => {
    const variants = {
      default: 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg',
      outlined: 'border-2 border-gray-300 dark:border-gray-600 rounded-lg bg-transparent',
      elevated: 'bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-100 dark:border-gray-700',
      ghost: 'bg-transparent'
    }
    return variants[variant]
  }

  const cardClasses = cn(
    'responsive-card',
    getVariantClasses(),
    interactive && [
      'cursor-pointer transition-all duration-200',
      'hover:shadow-md hover:scale-[1.02]',
      'active:scale-[0.98]',
      'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'
    ],
    className
  )

  const Component = onClick || interactive ? 'button' : 'div'

  return (
    <Component
      className={cardClasses}
      onClick={onClick}
      {...(Component === 'button' && { type: 'button' })}
    >
      <ResponsiveContainer
        maxWidth="none"
        centerContent={false}
        paddingX="md"
        paddingY="md"
        {...props}
      >
        {children}
      </ResponsiveContainer>
    </Component>
  )
}

/**
 * Grid container that combines responsive container with grid layout
 */
export function ResponsiveGridContainer({
  children,
  cols = { mobile: 1, tablet: 2, desktop: 3, wide: 4 },
  gap = 24,
  className,
  ...containerProps
}: ResponsiveContainerProps & {
  cols?: {
    mobile?: number
    tablet?: number
    desktop?: number
    wide?: number
  }
  gap?: number
}) {
  return (
    <ResponsiveContainer {...containerProps}>
      <div
        className={cn(
          'responsive-grid-container grid',
          // Mobile-first grid columns
          `grid-cols-${cols.mobile || 1}`,
          cols.tablet && `md:grid-cols-${cols.tablet}`,
          cols.desktop && `lg:grid-cols-${cols.desktop}`,
          cols.wide && `xl:grid-cols-${cols.wide}`,
          className
        )}
        style={{ gap: `${gap}px` }}
      >
        {children}
      </div>
    </ResponsiveContainer>
  )
}

/**
 * Flexbox container with responsive direction changes
 */
export function ResponsiveFlexContainer({
  children,
  direction = { mobile: 'col', desktop: 'row' },
  align = 'stretch',
  justify = 'start',
  gap = 16,
  wrap = true,
  className,
  ...containerProps
}: ResponsiveContainerProps & {
  direction?: {
    mobile?: 'row' | 'col' | 'row-reverse' | 'col-reverse'
    tablet?: 'row' | 'col' | 'row-reverse' | 'col-reverse'  
    desktop?: 'row' | 'col' | 'row-reverse' | 'col-reverse'
    wide?: 'row' | 'col' | 'row-reverse' | 'col-reverse'
  }
  align?: 'start' | 'center' | 'end' | 'stretch' | 'baseline'
  justify?: 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly'
  gap?: number
  wrap?: boolean
}) {
  const getFlexClasses = () => {
    const directionClasses = [
      direction.mobile && `flex-${direction.mobile}`,
      direction.tablet && `md:flex-${direction.tablet}`,
      direction.desktop && `lg:flex-${direction.desktop}`,
      direction.wide && `xl:flex-${direction.wide}`
    ].filter(Boolean).join(' ')

    const alignClass = `items-${align === 'start' ? 'start' : 
                               align === 'end' ? 'end' : 
                               align === 'baseline' ? 'baseline' :
                               align === 'stretch' ? 'stretch' : 'center'}`

    const justifyClass = `justify-${justify === 'start' ? 'start' :
                                   justify === 'end' ? 'end' :
                                   justify === 'between' ? 'between' :
                                   justify === 'around' ? 'around' :
                                   justify === 'evenly' ? 'evenly' : 'center'}`

    return cn(
      'flex',
      directionClasses,
      alignClass,
      justifyClass,
      wrap && 'flex-wrap'
    )
  }

  return (
    <ResponsiveContainer {...containerProps}>
      <div
        className={cn(getFlexClasses(), className)}
        style={{ gap: `${gap}px` }}
      >
        {children}
      </div>
    </ResponsiveContainer>
  )
}

/**
 * Sidebar layout with responsive behavior
 */
export function ResponsiveSidebarLayout({
  children,
  sidebar,
  sidebarWidth = '320px',
  collapsible = true,
  defaultCollapsed = false,
  className
}: {
  children: React.ReactNode
  sidebar: React.ReactNode
  sidebarWidth?: string
  collapsible?: boolean
  defaultCollapsed?: boolean
  className?: string
}) {
  const [isCollapsed, setIsCollapsed] = React.useState(defaultCollapsed)

  return (
    <div className={cn('responsive-sidebar-layout flex min-h-screen', className)}>
      {/* Sidebar */}
      <aside
        className={cn(
          'sidebar transition-all duration-300 ease-in-out',
          'bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700',
          'flex-shrink-0',
          // Mobile: full overlay, Desktop: fixed width
          'fixed inset-y-0 left-0 z-40 md:relative md:z-auto',
          isCollapsed ? 'w-0 md:w-16 overflow-hidden' : `w-80 md:w-[${sidebarWidth}]`
        )}
        style={{
          width: isCollapsed ? (window.innerWidth >= 768 ? '64px' : '0') : sidebarWidth
        }}
      >
        {/* Collapse Toggle */}
        {collapsible && (
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="absolute top-4 right-2 w-8 h-8 bg-white dark:bg-gray-800 rounded-full shadow-md flex items-center justify-center z-10"
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg
              className={cn('w-4 h-4 transition-transform', isCollapsed && 'rotate-180')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}
        
        <div className={cn('sidebar-content h-full', isCollapsed && 'md:px-2')}>
          {sidebar}
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 min-w-0 bg-white dark:bg-gray-800">
        <ResponsiveContainer
          maxWidth="none"
          centerContent={false}
          paddingX="md"
          paddingY="md"
        >
          {children}
        </ResponsiveContainer>
      </main>

      {/* Mobile Overlay */}
      {!isCollapsed && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-30 md:hidden"
          onClick={() => setIsCollapsed(true)}
          aria-hidden="true"
        />
      )}
    </div>
  )
}

export default ResponsiveContainer