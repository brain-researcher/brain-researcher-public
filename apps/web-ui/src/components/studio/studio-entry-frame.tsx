'use client'

import type { ComponentProps, ReactNode } from 'react'

type StudioEntryFrameProps = {
  children: ReactNode
  hydrated?: boolean
  outerClassName?: string
  innerClassName?: string
} & Omit<ComponentProps<'div'>, 'children' | 'className'>

export function StudioEntryFrame({
  children,
  hydrated,
  outerClassName = 'flex-1 overflow-y-auto p-6',
  innerClassName = 'mx-auto max-w-xl space-y-6',
  ...pageProps
}: StudioEntryFrameProps) {
  return (
    <div
      {...pageProps}
      className={outerClassName}
      data-hydrated={typeof hydrated === 'boolean' ? (hydrated ? '1' : '0') : undefined}
    >
      <div className={innerClassName}>{children}</div>
    </div>
  )
}
