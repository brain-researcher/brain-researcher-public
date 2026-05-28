import * as React from "react"
import { cn } from "@/lib/utils"

interface Badge90sProps extends React.HTMLAttributes<HTMLDivElement> {}

export function Badge90s({ className, ...props }: Badge90sProps) {
  return (
    <div 
      className={cn(
        "inline-flex items-center justify-center px-3 py-1.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 border border-green-200 dark:border-green-800 rounded-full",
        className
      )}
      {...props}
    >
      <svg 
        className="w-3 h-3 mr-1" 
        viewBox="0 0 12 12" 
        fill="none" 
        xmlns="http://www.w3.org/2000/svg"
      >
        <path 
          d="M6 1L7.5 4.5L11 4.5L8.25 7L9.75 10.5L6 8.5L2.25 10.5L3.75 7L1 4.5L4.5 4.5L6 1Z" 
          fill="currentColor"
        />
      </svg>
      ≤90s
    </div>
  )
}