'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CalendarIcon, Clock } from 'lucide-react'
import { format, addDays, startOfDay, endOfDay } from 'date-fns'
import { TimeRange } from '@/types/analytics'
import { cn } from '@/lib/utils'

interface TimeRangeSelectorProps {
  value: TimeRange
  onChange: (timeRange: TimeRange) => void
  presets?: TimeRange[]
  className?: string
}

const DEFAULT_PRESETS: TimeRange[] = [
  {
    label: 'Last 24 hours',
    value: '24h',
    start: new Date(Date.now() - 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 7 days',
    value: '7d',
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 30 days',
    value: '30d',
    start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 90 days',
    value: '90d',
    start: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000),
    end: new Date()
  }
]

export function TimeRangeSelector({ 
  value, 
  onChange, 
  presets = DEFAULT_PRESETS,
  className 
}: TimeRangeSelectorProps) {
  const [customRange, setCustomRange] = useState<{
    from: Date | undefined
    to: Date | undefined
  }>({
    from: undefined,
    to: undefined
  })
  const [isCustomPopoverOpen, setIsCustomPopoverOpen] = useState(false)

  const handlePresetSelect = (preset: string) => {
    const selectedPreset = presets.find(p => p.value === preset)
    if (selectedPreset) {
      onChange(selectedPreset)
    }
  }

  const handleCustomDateSelect = (range: { from: Date | undefined, to: Date | undefined }) => {
    setCustomRange(range)
    
    if (range.from && range.to) {
      const customTimeRange: TimeRange = {
        label: `${format(range.from, 'MMM dd')} - ${format(range.to, 'MMM dd')}`,
        value: 'custom',
        start: startOfDay(range.from),
        end: endOfDay(range.to)
      }
      onChange(customTimeRange)
      setIsCustomPopoverOpen(false)
    }
  }

  const isPresetSelected = presets.some(preset => preset.value === value.value)

  return (
    <div className={cn("flex items-center space-x-2", className)}>
      <Select 
        value={isPresetSelected ? value.value : 'custom'} 
        onValueChange={handlePresetSelect}
      >
        <SelectTrigger className="w-40">
          <Clock className="h-4 w-4 mr-2" />
          <SelectValue placeholder="Select time range" />
        </SelectTrigger>
        <SelectContent>
          {presets.map((preset) => (
            <SelectItem key={preset.value} value={preset.value}>
              {preset.label}
            </SelectItem>
          ))}
          <SelectItem value="custom">Custom Range</SelectItem>
        </SelectContent>
      </Select>

      <Popover open={isCustomPopoverOpen} onOpenChange={setIsCustomPopoverOpen}>
        <PopoverTrigger asChild>
          <Button 
            variant="outline" 
            size="sm"
            className={cn(
              "justify-start text-left font-normal",
              !value.start && "text-muted-foreground"
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4" />
            {value.start ? (
              value.end ? (
                <>
                  {format(value.start, "LLL dd, y")} -{" "}
                  {format(value.end, "LLL dd, y")}
                </>
              ) : (
                format(value.start, "LLL dd, y")
              )
            ) : (
              <span>Pick a date range</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            className="rounded-md border"
          />
          <div className="p-3 border-t">
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>Quick ranges:</span>
              <div className="flex space-x-1">
                {[7, 30, 90].map((days) => (
                  <Button
                    key={days}
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-xs"
                    onClick={() => {
                      const end = new Date()
                      const start = addDays(end, -days)
                      handleCustomDateSelect({ from: start, to: end })
                    }}
                  >
                    {days}d
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>

      <div className="text-xs text-muted-foreground">
        {value.start && value.end && (
          <span>
            {Math.ceil((value.end.getTime() - value.start.getTime()) / (1000 * 60 * 60 * 24))} days
          </span>
        )}
      </div>
    </div>
  )
}