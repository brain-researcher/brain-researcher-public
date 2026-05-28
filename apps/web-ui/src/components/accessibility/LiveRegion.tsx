'use client'

import * as React from "react"
import { cn } from "@/lib/utils"

export interface LiveRegionProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Content to announce to screen readers */
  children: React.ReactNode
  /** Politeness level for announcements */
  politeness?: 'polite' | 'assertive' | 'off'
  /** Whether to announce the entire region or just changes */
  atomic?: boolean
  /** Whether this region is relevant for updates */
  relevant?: 'additions' | 'removals' | 'text' | 'all'
  /** Visually hide the live region */
  visuallyHidden?: boolean
}

/**
 * Live region for announcing dynamic content changes to screen readers
 * Follows WCAG 2.1 guidelines for live regions
 */
export function LiveRegion({
  children,
  politeness = 'polite',
  atomic = true,
  relevant = 'all',
  visuallyHidden = true,
  className,
  ...props
}: LiveRegionProps) {
  return (
    <div
      role="status"
      aria-live={politeness}
      aria-atomic={atomic}
      aria-relevant={relevant}
      className={cn(
        visuallyHidden && "sr-only",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

/**
 * Specialized live region for status messages
 */
export function StatusRegion({ children, ...props }: Omit<LiveRegionProps, 'politeness'>) {
  return (
    <LiveRegion politeness="polite" {...props}>
      {children}
    </LiveRegion>
  )
}

/**
 * Specialized live region for alerts and urgent messages
 */
export function AlertRegion({ children, ...props }: Omit<LiveRegionProps, 'politeness'>) {
  return (
    <LiveRegion politeness="assertive" {...props}>
      {children}
    </LiveRegion>
  )
}