"use client"

import { useState } from 'react'
import { Button } from './button'
import { useToast } from '@/hooks/use-toast'
import { Copy, Check } from 'lucide-react'

interface CopyButtonProps {
  content: string
  label?: string
  className?: string
  variant?: 'default' | 'outline' | 'ghost' | 'secondary'
  size?: 'default' | 'sm' | 'lg' | 'icon'
}

export function CopyButton({
  content,
  label = 'Copy',
  className,
  variant = 'outline',
  size = 'sm'
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      toast({
        title: 'Copied!',
        description: 'Content copied to clipboard',
        duration: 2000
      })

      // Reset copied state after 2 seconds
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      toast({
        title: 'Failed to copy',
        description: 'Please try again',
        variant: 'destructive',
        duration: 3000
      })
    }
  }

  return (
    <Button
      onClick={handleCopy}
      variant={variant}
      size={size}
      className={className}
      disabled={copied}
    >
      {copied ? (
        <>
          <Check className="h-4 w-4 mr-1" />
          Copied
        </>
      ) : (
        <>
          <Copy className="h-4 w-4 mr-1" />
          {label}
        </>
      )}
    </Button>
  )
}
