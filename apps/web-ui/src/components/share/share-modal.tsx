'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'

type ShareLevel = 'summary' | 'full'

type ShareModalProps = {
  analysisId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

const EXPIRATION_OPTIONS = [
  { label: '7 days', hours: 24 * 7 },
  { label: '30 days', hours: 24 * 30 },
  { label: '24 hours', hours: 24 },
]

export function ShareModal({ analysisId, open, onOpenChange }: ShareModalProps) {
  const { toast } = useToast()
  const [shareLevel, setShareLevel] = useState<ShareLevel>('summary')
  const [expiresInHours, setExpiresInHours] = useState<number>(24 * 7)
  const [shareToken, setShareToken] = useState<string>('')
  const [revocable, setRevocable] = useState(false)
  const [shareUrl, setShareUrl] = useState<string>('')
  const [shareLoading, setShareLoading] = useState(false)
  const [revokeLoading, setRevokeLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setShareToken('')
    setRevocable(false)
    setShareUrl('')
    setShareLoading(false)
    setRevokeLoading(false)
  }, [open, analysisId])

  const expirationLabel = useMemo(
    () => EXPIRATION_OPTIONS.find((opt) => opt.hours === expiresInHours)?.label ?? `${expiresInHours}h`,
    [expiresInHours],
  )

  const createShareLink = useCallback(async () => {
    if (!analysisId) return ''
    setShareLoading(true)
    try {
      const res = await fetch(`/api/analyses/${encodeURIComponent(analysisId)}/share`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          expires_in_hours: expiresInHours,
          share_level: shareLevel,
        }),
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || res.statusText || `HTTP ${res.status}`)
      }

      const payload = (await res.json().catch(() => null)) as any
      const token: string = String(payload?.share_token ?? payload?.shareToken ?? '').trim()
      const canRevoke = Boolean(payload?.revocable)
      const sharePath = String(payload?.share_path ?? payload?.sharePath ?? '').trim()
      // Prefer resolving absolute URLs on the client so we don't depend on server-side
      // origin inference (which can be incorrect behind proxies/containers).
      const url: string =
        (sharePath && typeof window !== 'undefined'
          ? `${window.location.origin}${sharePath.startsWith('/') ? sharePath : `/${sharePath}`}`
          : '') ||
        payload?.share_url ||
        ''

      if (!url) {
        throw new Error('Share link was not returned.')
      }

      if (token) {
        setShareToken(token)
      }
      setRevocable(canRevoke)
      setShareUrl(url)
      return url
    } finally {
      setShareLoading(false)
    }
  }, [analysisId, expiresInHours, shareLevel])

  const copyLink = useCallback(async () => {
    try {
      const url = shareUrl || (await createShareLink())
      if (!url) return
      await navigator.clipboard.writeText(url)
      toast({
        title: 'Share link copied',
        description: 'Anyone with the link can view this Result Package (read-only).',
        duration: 2500,
      })
    } catch (err) {
      toast({
        title: 'Failed to copy share link',
        description: err instanceof Error ? err.message : String(err),
        variant: 'destructive',
        duration: 4000,
      })
    }
  }, [createShareLink, shareUrl, toast])

  const revokeLink = useCallback(async () => {
    if (!shareToken) return
    if (typeof window !== 'undefined') {
      const ok = window.confirm('Revoke this share link? Anyone with the link will lose access immediately.')
      if (!ok) return
    }
    setRevokeLoading(true)
    try {
      const res = await fetch(`/api/share/${encodeURIComponent(shareToken)}`, { method: 'DELETE' })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || res.statusText || `HTTP ${res.status}`)
      }
      setShareToken('')
      setRevocable(false)
      setShareUrl('')
      toast({
        title: 'Access revoked',
        description: 'The share link has been revoked.',
        duration: 2500,
      })
    } catch (err) {
      toast({
        title: 'Failed to revoke access',
        description: err instanceof Error ? err.message : String(err),
        variant: 'destructive',
        duration: 4000,
      })
    } finally {
      setRevokeLoading(false)
    }
  }, [shareToken, toast])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Share Result Package</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          <div className="space-y-2">
            <Label>Share level</Label>
            <RadioGroup value={shareLevel} onValueChange={(value) => setShareLevel(value as ShareLevel)}>
              <label className="flex items-start gap-3 rounded-lg border p-3">
                <RadioGroupItem value="summary" />
                <div className="space-y-1">
                  <div className="text-sm font-medium">Summary package (recommended)</div>
                  <div className="text-sm text-muted-foreground">
                    Includes summary, charts, and methods (no raw logs by default).
                  </div>
                </div>
              </label>
              <label className="flex items-start gap-3 rounded-lg border p-3">
                <RadioGroupItem value="full" />
                <div className="space-y-1">
                  <div className="text-sm font-medium">Full evidence bundle</div>
                  <div className="text-sm text-muted-foreground">
                    Includes all outputs. May include logs and larger files.
                  </div>
                </div>
              </label>
            </RadioGroup>
          </div>

          <div className="space-y-2">
            <Label>Expiration</Label>
            <Select
              value={String(expiresInHours)}
              onValueChange={(value) => setExpiresInHours(Number(value))}
            >
              <SelectTrigger className="h-9">
                <SelectValue placeholder={expirationLabel} />
              </SelectTrigger>
              <SelectContent>
                {EXPIRATION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.hours} value={String(opt.hours)}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Link</Label>
            <div className="flex gap-2">
              <Input value={shareUrl} readOnly placeholder="Generate a link to share…" />
              <Button
                type="button"
                onClick={() => void copyLink()}
                disabled={shareLoading}
              >
                {shareLoading ? 'Working…' : 'Copy'}
              </Button>
            </div>
            <div className="text-xs text-muted-foreground">
              This link is public to anyone with it. Keep it private and revoke if needed.
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!shareToken || !revocable || shareLoading || revokeLoading}
              onClick={() => void revokeLink()}
            >
              {revokeLoading ? 'Revoking…' : 'Revoke Access'}
            </Button>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
