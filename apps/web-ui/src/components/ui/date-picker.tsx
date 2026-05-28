'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import { Button } from './button'
import { CalendarIcon } from 'lucide-react'

export interface DateRange {
  from?: Date
  to?: Date
  start?: string
  end?: string
}

export interface DatePickerWithRangeProps {
  className?: string
  date?: DateRange
  dateRange?: { start: string; end: string }
  onDateChange?: (date: DateRange | undefined) => void
  onRangeChange?: (range: { start: string; end: string }) => void
}

export function DatePickerWithRange({
  className,
  date,
  dateRange,
  onDateChange,
  onRangeChange,
}: DatePickerWithRangeProps) {
  const formatDate = (d?: Date | string) => {
    if (!d) return ''
    if (typeof d === 'string') return d
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const hasDate = date?.from || dateRange?.start

  return (
    <div className={cn('grid gap-2', className)}>
      <Button
        variant="outline"
        className={cn(
          'w-full justify-start text-left font-normal',
          !hasDate && 'text-muted-foreground'
        )}
      >
        <CalendarIcon className="mr-2 h-4 w-4" />
        {dateRange ? (
          dateRange.start && dateRange.end ? (
            <>
              {dateRange.start} - {dateRange.end}
            </>
          ) : (
            <span>Pick a date range</span>
          )
        ) : date?.from ? (
          date.to ? (
            <>
              {formatDate(date.from)} - {formatDate(date.to)}
            </>
          ) : (
            formatDate(date.from)
          )
        ) : (
          <span>Pick a date range</span>
        )}
      </Button>
    </div>
  )
}
