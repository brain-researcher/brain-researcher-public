'use client'

import * as React from "react"
import { cn } from "@/lib/utils"

export type CalendarProps = React.HTMLAttributes<HTMLDivElement>

export function Calendar({
  className,
  ...props
}: CalendarProps) {
  return (
    <div
      className={cn("p-3", className)}
      {...props}
    >
      <div className="text-sm text-muted-foreground">Calendar view is not available yet.</div>
    </div>
  )
}
