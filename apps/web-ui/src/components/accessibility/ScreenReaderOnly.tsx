import * as React from "react"
import { cn } from "@/lib/utils"

export interface ScreenReaderOnlyProps extends React.HTMLAttributes<HTMLSpanElement> {
  children: React.ReactNode
}

/**
 * Component that renders content visible only to screen readers
 * Uses the sr-only class to visually hide content while keeping it accessible
 */
export function ScreenReaderOnly({ 
  children, 
  className, 
  ...props 
}: ScreenReaderOnlyProps) {
  return (
    <span 
      className={cn("sr-only", className)} 
      {...props}
    >
      {children}
    </span>
  )
}

// Also export as VisuallyHidden for semantic clarity
export const VisuallyHidden = ScreenReaderOnly