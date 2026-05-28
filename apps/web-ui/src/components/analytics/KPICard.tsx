'use client'

import React from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown, Minus, Target } from 'lucide-react'
import { KPICardData } from '@/types/analytics'
import { cn } from '@/lib/utils'

interface KPICardProps {
  data: KPICardData
  className?: string
  showTarget?: boolean
}

export function KPICard({ data, className, showTarget = false }: KPICardProps) {
  const isGoodWhenUp = data.isGoodWhenUp ?? true

  const formatValue = (value: number | string, format?: string, unit?: string) => {
    if (typeof value === 'string') return value

    let formatted = value.toString()
    
    switch (format) {
      case 'percentage':
        formatted = `${value.toFixed(1)}%`
        break
      case 'currency':
        formatted = new Intl.NumberFormat('en-US', {
          style: 'currency',
          currency: 'USD'
        }).format(value)
        break
      case 'time':
        // Convert minutes to hours and minutes
        const hours = Math.floor(value / 60)
        const minutes = Math.round(value % 60)
        formatted = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
        break
      case 'number':
      default:
        if (value >= 1000000) {
          formatted = `${(value / 1000000).toFixed(1)}M`
        } else if (value >= 1000) {
          formatted = `${(value / 1000).toFixed(1)}K`
        } else {
          formatted = value.toLocaleString()
        }
    }

    return unit ? `${formatted}${unit}` : formatted
  }

  const getTrendIcon = (trend: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up':
        return <TrendingUp className="h-3 w-3" />
      case 'down':
        return <TrendingDown className="h-3 w-3" />
      default:
        return <Minus className="h-3 w-3" />
    }
  }

  const getTrendColor = (trend: 'up' | 'down' | 'stable') => {
    if (trend === 'stable') {
      return 'text-gray-600 bg-gray-50 dark:text-gray-400 dark:bg-gray-900/20'
    }

    const isUp = trend === 'up'
    const isGood = isGoodWhenUp ? isUp : !isUp

    return isGood
      ? 'text-green-600 bg-green-50 dark:text-green-400 dark:bg-green-900/20'
      : 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-900/20'
  }

  const getTargetProgress = () => {
    if (!data.target || typeof data.value !== 'number') return 0

    if (data.target === 0) return data.value === 0 ? 100 : 0

    if (isGoodWhenUp) {
      return Math.min((data.value / data.target) * 100, 100)
    }

    if (data.value <= 0) return 100
    return Math.min((data.target / data.value) * 100, 100)
  }

  const isTargetMet = () => {
    if (!data.target || typeof data.value !== 'number') return false

    return isGoodWhenUp ? data.value >= data.target : data.value <= data.target
  }

  return (
    <Card className={cn("h-full", className)}>
      <CardContent className="p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-muted-foreground">
              {data.title}
            </h3>
            <div className="text-2xl font-bold">
              {formatValue(data.value, data.format, data.unit)}
            </div>
            {data.subtitle && (
              <p className="text-xs text-muted-foreground">
                {data.subtitle}
              </p>
            )}
          </div>
          
          {data.color && (
            <div 
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: data.color }}
            />
          )}
        </div>

        <div className="space-y-3">
          {/* Trend indicator */}
          <div className="flex items-center justify-between">
            <Badge 
              variant="secondary" 
              className={cn("text-xs", getTrendColor(data.trend.trend))}
            >
              {getTrendIcon(data.trend.trend)}
              <span className="ml-1">
                {data.trend.changePercentage > 0 ? '+' : ''}
                {data.trend.changePercentage.toFixed(1)}%
              </span>
            </Badge>
            
            <span className="text-xs text-muted-foreground">
              vs previous period
            </span>
          </div>

          {/* Absolute change */}
          <div className="text-xs text-muted-foreground">
            {data.trend.change > 0 ? '+' : ''}
            {formatValue(data.trend.change, data.format, data.unit)} 
            {' from '}
            {formatValue(data.trend.previous, data.format, data.unit)}
          </div>

          {/* Target progress */}
          {showTarget && data.target && typeof data.value === 'number' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground flex items-center">
                  <Target className="h-3 w-3 mr-1" />
                  Target: {formatValue(data.target, data.format, data.unit)}
                </span>
                <span className={cn(
                  "font-medium",
                  isTargetMet() ? "text-green-600" : "text-orange-600"
                )}>
                  {getTargetProgress().toFixed(0)}%
                </span>
              </div>
              
              <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                <div
                  className={cn(
                    "h-2 rounded-full transition-all duration-300",
                    isTargetMet() ? "bg-green-600" : "bg-orange-500"
                  )}
                  style={{ width: `${getTargetProgress()}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
