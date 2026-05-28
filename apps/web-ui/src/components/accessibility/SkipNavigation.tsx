'use client'

import * as React from "react"
import { cn } from "@/lib/utils"

export interface SkipLinkProps extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  /** Target element ID to skip to */
  targetId: string
  /** Link text */
  children: React.ReactNode
}

/**
 * Skip link component for keyboard navigation
 * Becomes visible when focused, allows users to skip to main content
 */
export function SkipLink({ 
  targetId, 
  children, 
  className, 
  ...props 
}: SkipLinkProps) {
  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    const target = document.getElementById(targetId)
    if (target) {
      target.focus()
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <a
      href={`#${targetId}`}
      onClick={handleClick}
      className={cn(
        // Hidden by default
        "absolute -top-full left-4 z-[9999]",
        // Visible when focused
        "focus:top-4",
        // Styling
        "bg-primary text-primary-foreground px-4 py-2 rounded-md",
        "text-sm font-medium transition-all duration-200",
        "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        className
      )}
      {...props}
    >
      {children}
    </a>
  )
}

/**
 * Complete skip navigation component with common skip links
 */
export function SkipNavigation() {
  return (
    <div className="sr-only focus-within:not-sr-only">
      <SkipLink targetId="main-content">
        Skip to main content
      </SkipLink>
      <SkipLink targetId="main-navigation">
        Skip to navigation
      </SkipLink>
      <SkipLink targetId="search">
        Skip to search
      </SkipLink>
    </div>
  )
}