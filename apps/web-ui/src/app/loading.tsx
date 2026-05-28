'use client'

import React from 'react'

export default function Loading() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      {/* Top progress bar */}
      <div
        aria-hidden
        className="fixed left-0 top-0 h-0.5 w-full overflow-hidden z-50"
      >
        <div className="h-full w-1/3 animate-[progress_1.2s_ease-in-out_infinite] bg-blue-500" />
      </div>

      {/* Centered spinner and message */}
      <div className="flex min-h-screen items-center justify-center">
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-3 text-gray-700 dark:text-gray-200"
        >
          <svg
            className="h-5 w-5 animate-spin text-blue-500"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
            />
          </svg>
          <span className="text-sm">Loading…</span>
        </div>
      </div>

      {/* Keyframes for top bar animation (scoped via arbitrary keyframe name) */}
      <style jsx global>{`
        @keyframes progress {
          0% { transform: translateX(-100%); }
          50% { transform: translateX(100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>
    </div>
  )
}

