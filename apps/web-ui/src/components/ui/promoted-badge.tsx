import { Badge } from './badge'
import { Star } from 'lucide-react'
import { cn } from '@/lib/utils'

interface PromotedBadgeProps {
  className?: string
  showIcon?: boolean
  label?: string
}

export function PromotedBadge({
  className,
  showIcon = true,
  label = 'Promoted'
}: PromotedBadgeProps) {
  return (
    <Badge
      variant="default"
      className={cn(
        'bg-gradient-to-r from-yellow-500 to-amber-600 text-white border-0',
        'hover:from-yellow-600 hover:to-amber-700',
        'shadow-sm',
        className
      )}
    >
      {showIcon && <Star className="h-3 w-3 mr-1 fill-current" />}
      {label}
    </Badge>
  )
}
