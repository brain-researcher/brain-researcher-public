import { Badge } from './badge'
import { Star } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FamilyChipProps {
  family: string
  count?: number
  isPreferred?: boolean
  className?: string
  variant?: 'default' | 'secondary' | 'outline' | 'destructive'
}

export function FamilyChip({
  family,
  count,
  isPreferred = false,
  className,
  variant = 'secondary'
}: FamilyChipProps) {
  return (
    <Badge
      variant={isPreferred ? 'default' : variant}
      className={cn(
        'flex items-center gap-1',
        isPreferred && 'bg-blue-600 text-white hover:bg-blue-700',
        className
      )}
    >
      {isPreferred && <Star className="h-3 w-3 fill-current" />}
      <span>{family}</span>
      {count !== undefined && (
        <span className="opacity-75">({count})</span>
      )}
    </Badge>
  )
}
