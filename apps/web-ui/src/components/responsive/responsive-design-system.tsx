'use client'

import React, { useState, useEffect, createContext, useContext } from 'react'
import { Monitor, Tablet, Smartphone, Maximize2, Grid, Layers } from 'lucide-react'

// Breakpoint definitions
const BREAKPOINTS = {
  xs: 0,
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536
} as const

type Breakpoint = keyof typeof BREAKPOINTS

// Device types
type DeviceType = 'mobile' | 'tablet' | 'desktop' | 'wide'

// Responsive Context
interface ResponsiveContextValue {
  breakpoint: Breakpoint
  deviceType: DeviceType
  screenWidth: number
  screenHeight: number
  isPortrait: boolean
  isTouchDevice: boolean
}

const ResponsiveContext = createContext<ResponsiveContextValue | null>(null)

// Custom hook for responsive design
export function useResponsive() {
  const context = useContext(ResponsiveContext)
  if (!context) {
    throw new Error('useResponsive must be used within ResponsiveProvider')
  }
  return context
}

// Responsive Provider Component
export function ResponsiveProvider({ children }: { children: React.ReactNode }) {
  const [screenWidth, setScreenWidth] = useState(0)
  const [screenHeight, setScreenHeight] = useState(0)
  const [isTouchDevice, setIsTouchDevice] = useState(false)

  useEffect(() => {
    const updateDimensions = () => {
      setScreenWidth(window.innerWidth)
      setScreenHeight(window.innerHeight)
    }

    const checkTouchDevice = () => {
      setIsTouchDevice('ontouchstart' in window || navigator.maxTouchPoints > 0)
    }

    updateDimensions()
    checkTouchDevice()

    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [])

  const getBreakpoint = (): Breakpoint => {
    if (screenWidth >= BREAKPOINTS['2xl']) return '2xl'
    if (screenWidth >= BREAKPOINTS.xl) return 'xl'
    if (screenWidth >= BREAKPOINTS.lg) return 'lg'
    if (screenWidth >= BREAKPOINTS.md) return 'md'
    if (screenWidth >= BREAKPOINTS.sm) return 'sm'
    return 'xs'
  }

  const getDeviceType = (): DeviceType => {
    if (screenWidth >= BREAKPOINTS.xl) return 'wide'
    if (screenWidth >= BREAKPOINTS.lg) return 'desktop'
    if (screenWidth >= BREAKPOINTS.md) return 'tablet'
    return 'mobile'
  }

  const value: ResponsiveContextValue = {
    breakpoint: getBreakpoint(),
    deviceType: getDeviceType(),
    screenWidth,
    screenHeight,
    isPortrait: screenHeight > screenWidth,
    isTouchDevice
  }

  return (
    <ResponsiveContext.Provider value={value}>
      {children}
    </ResponsiveContext.Provider>
  )
}

// Responsive Grid Component
interface ResponsiveGridProps {
  cols?: {
    xs?: number
    sm?: number
    md?: number
    lg?: number
    xl?: number
    '2xl'?: number
  }
  gap?: number | string
  children: React.ReactNode
  className?: string
}

export function ResponsiveGrid({
  cols = { xs: 1, sm: 2, md: 3, lg: 4, xl: 5, '2xl': 6 },
  gap = 4,
  children,
  className = ''
}: ResponsiveGridProps) {
  const { breakpoint } = useResponsive()
  
  const getColumns = () => {
    const breakpoints: Breakpoint[] = ['2xl', 'xl', 'lg', 'md', 'sm', 'xs']
    const currentIndex = breakpoints.indexOf(breakpoint)
    
    for (let i = currentIndex; i < breakpoints.length; i++) {
      const bp = breakpoints[i]
      if (cols[bp]) return cols[bp]
    }
    return 1
  }

  const gridStyle = {
    display: 'grid',
    gridTemplateColumns: `repeat(${getColumns()}, 1fr)`,
    gap: typeof gap === 'number' ? `${gap * 0.25}rem` : gap
  }

  return (
    <div className={className} style={gridStyle}>
      {children}
    </div>
  )
}

// Responsive Container Component
interface ResponsiveContainerProps {
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full'
  padding?: boolean
  children: React.ReactNode
  className?: string
}

export function ResponsiveContainer({
  maxWidth = 'xl',
  padding = true,
  children,
  className = ''
}: ResponsiveContainerProps) {
  const maxWidthClasses = {
    sm: 'max-w-screen-sm',
    md: 'max-w-screen-md',
    lg: 'max-w-screen-lg',
    xl: 'max-w-screen-xl',
    '2xl': 'max-w-screen-2xl',
    full: 'max-w-full'
  }

  return (
    <div className={`
      ${maxWidthClasses[maxWidth]} 
      mx-auto 
      ${padding ? 'px-4 sm:px-6 lg:px-8' : ''} 
      ${className}
    `}>
      {children}
    </div>
  )
}

// Responsive Show/Hide Components
export function ShowOnMobile({ children }: { children: React.ReactNode }) {
  const { deviceType } = useResponsive()
  return deviceType === 'mobile' ? <>{children}</> : null
}

export function HideOnMobile({ children }: { children: React.ReactNode }) {
  const { deviceType } = useResponsive()
  return deviceType !== 'mobile' ? <>{children}</> : null
}

export function ShowOnTablet({ children }: { children: React.ReactNode }) {
  const { deviceType } = useResponsive()
  return deviceType === 'tablet' ? <>{children}</> : null
}

export function ShowOnDesktop({ children }: { children: React.ReactNode }) {
  const { deviceType } = useResponsive()
  return deviceType === 'desktop' || deviceType === 'wide' ? <>{children}</> : null
}

// Responsive Image Component
interface ResponsiveImageProps {
  src: string
  alt: string
  sources?: {
    breakpoint: Breakpoint
    src: string
  }[]
  className?: string
  loading?: 'lazy' | 'eager'
}

export function ResponsiveImage({
  src,
  alt,
  sources = [],
  className = '',
  loading = 'lazy'
}: ResponsiveImageProps) {
  const { breakpoint } = useResponsive()
  
  const getCurrentSource = () => {
    if (!sources.length) return src
    
    const breakpoints: Breakpoint[] = ['2xl', 'xl', 'lg', 'md', 'sm', 'xs']
    const currentIndex = breakpoints.indexOf(breakpoint)
    
    for (let i = currentIndex; i < breakpoints.length; i++) {
      const source = sources.find(s => s.breakpoint === breakpoints[i])
      if (source) return source.src
    }
    
    return src
  }

  return (
    <img
      src={getCurrentSource()}
      alt={alt}
      className={className}
      loading={loading}
    />
  )
}

// Device Preview Component
interface DevicePreviewProps {
  children: React.ReactNode
  device: 'mobile' | 'tablet' | 'desktop'
  orientation?: 'portrait' | 'landscape'
  zoom?: number
}

export function DevicePreview({
  children,
  device,
  orientation = 'portrait',
  zoom = 1
}: DevicePreviewProps) {
  const deviceSizes = {
    mobile: { width: 375, height: 812 },
    tablet: { width: 768, height: 1024 },
    desktop: { width: 1920, height: 1080 }
  }

  const size = deviceSizes[device]
  const width = orientation === 'portrait' ? size.width : size.height
  const height = orientation === 'portrait' ? size.height : size.width

  return (
    <div className="bg-gray-100 dark:bg-gray-900 p-8 rounded-lg">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {device === 'mobile' && <Smartphone className="h-5 w-5" />}
          {device === 'tablet' && <Tablet className="h-5 w-5" />}
          {device === 'desktop' && <Monitor className="h-5 w-5" />}
          <span className="text-sm font-medium capitalize">{device} Preview</span>
        </div>
        <span className="text-xs text-gray-500">
          {width} × {height}px @ {(zoom * 100).toFixed(0)}%
        </span>
      </div>
      
      <div
        className="mx-auto bg-white dark:bg-gray-800 rounded-lg shadow-xl overflow-hidden"
        style={{
          width: width * zoom,
          height: height * zoom,
          transform: `scale(${zoom})`,
          transformOrigin: 'top center'
        }}
      >
        <iframe
          srcDoc={`
            <!DOCTYPE html>
            <html>
              <head>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                  body { margin: 0; padding: 0; }
                  * { box-sizing: border-box; }
                </style>
              </head>
              <body>
                <div id="root"></div>
              </body>
            </html>
          `}
          className="w-full h-full border-0"
          title={`${device} preview`}
        />
      </div>
    </div>
  )
}

// Responsive Design Tester Component
export function ResponsiveDesignTester({ url }: { url: string }) {
  const [selectedDevice, setSelectedDevice] = useState<'mobile' | 'tablet' | 'desktop'>('desktop')
  const [zoom, setZoom] = useState(0.5)
  
  const devices = [
    { type: 'mobile' as const, icon: Smartphone, label: 'Mobile' },
    { type: 'tablet' as const, icon: Tablet, label: 'Tablet' },
    { type: 'desktop' as const, icon: Monitor, label: 'Desktop' }
  ]

  return (
    <div className="h-full flex flex-col">
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {devices.map(({ type, icon: Icon, label }) => (
              <button
                key={type}
                onClick={() => setSelectedDevice(type)}
                className={`
                  flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium
                  ${selectedDevice === type
                    ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                  }
                `}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>
          
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">Zoom:</span>
              <input
                type="range"
                min="25"
                max="100"
                value={zoom * 100}
                onChange={(e) => setZoom(parseInt(e.target.value) / 100)}
                className="w-32"
              />
              <span className="text-sm font-medium">{(zoom * 100).toFixed(0)}%</span>
            </div>
          </div>
        </div>
      </div>
      
      <div className="flex-1 overflow-auto p-8 bg-gray-50 dark:bg-gray-900">
        <DevicePreview device={selectedDevice} zoom={zoom}>
          <iframe src={url} className="w-full h-full border-0" title="Preview" />
        </DevicePreview>
      </div>
    </div>
  )
}

// Layout System Component
interface ResponsiveLayoutProps {
  sidebar?: React.ReactNode
  main: React.ReactNode
  aside?: React.ReactNode
  header?: React.ReactNode
  footer?: React.ReactNode
  sidebarCollapsed?: boolean
  asideCollapsed?: boolean
}

export function ResponsiveLayout({
  sidebar,
  main,
  aside,
  header,
  footer,
  sidebarCollapsed = false,
  asideCollapsed = false
}: ResponsiveLayoutProps) {
  const { deviceType } = useResponsive()
  const isMobile = deviceType === 'mobile'

  return (
    <div className="min-h-screen flex flex-col">
      {header && (
        <header className="flex-shrink-0">
          {header}
        </header>
      )}
      
      <div className="flex-1 flex">
        {sidebar && !isMobile && (
          <aside className={`
            flex-shrink-0 transition-all duration-300
            ${sidebarCollapsed ? 'w-16' : 'w-64'}
          `}>
            {sidebar}
          </aside>
        )}
        
        <main className="flex-1 min-w-0">
          {main}
        </main>
        
        {aside && !isMobile && (
          <aside className={`
            flex-shrink-0 transition-all duration-300
            ${asideCollapsed ? 'w-0' : 'w-80'}
          `}>
            {aside}
          </aside>
        )}
      </div>
      
      {footer && (
        <footer className="flex-shrink-0">
          {footer}
        </footer>
      )}
      
      {isMobile && (sidebar || aside) && (
        <div className="fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 p-2 flex justify-around">
          {sidebar && <button className="p-2"><Layers className="h-5 w-5" /></button>}
          {aside && <button className="p-2"><Grid className="h-5 w-5" /></button>}
        </div>
      )}
    </div>
  )
}

// Export all components
const responsiveDesignExports = {
  ResponsiveProvider,
  useResponsive,
  ResponsiveGrid,
  ResponsiveContainer,
  ShowOnMobile,
  HideOnMobile,
  ShowOnTablet,
  ShowOnDesktop,
  ResponsiveImage,
  DevicePreview,
  ResponsiveDesignTester,
  ResponsiveLayout
}

export default responsiveDesignExports
