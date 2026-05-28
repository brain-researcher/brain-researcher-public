'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { ChevronDown, Plus } from 'lucide-react'

import { useAuthSync } from '@/components/auth/auth-sync-provider'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getSupabaseClient, isSupabaseEnabled } from '@/lib/supabase/client'

const WORKSPACE_COOKIE = 'br_workspace_id'

type WorkspaceRow = {
  id: string
  name?: string | null
  slug?: string | null
  [key: string]: unknown
}

function slugify(value: string): string {
  const base = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `${base || 'workspace'}-${suffix}`
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const parts = document.cookie.split(';').map((p) => p.trim())
  for (const part of parts) {
    if (!part) continue
    const eq = part.indexOf('=')
    if (eq <= 0) continue
    const key = part.slice(0, eq).trim()
    if (key !== name) continue
    return part.slice(eq + 1).trim() || null
  }
  return null
}

function writeCookie(name: string, value: string): void {
  if (typeof document === 'undefined') return
  const parts: string[] = [`${name}=${value}`]
  parts.push('Path=/')
  parts.push('SameSite=Lax')
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    parts.push('Secure')
  }
  document.cookie = parts.join('; ')
}

export function WorkspaceSwitcher() {
  const router = useRouter()
  const { isAuthenticated } = useAuthSync()
  const supabaseEnabled = isSupabaseEnabled()
  const supabase = supabaseEnabled ? getSupabaseClient() : null

  const [workspaces, setWorkspaces] = React.useState<WorkspaceRow[]>([])
  const [selected, setSelected] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const loadWorkspaces = React.useCallback(async () => {
    if (!supabase) return
    setLoading(true)
    setError(null)
    try {
      const { data, error: supaError } = await supabase.from('workspaces').select('*').limit(50)
      if (supaError) throw supaError

      const rows = (data ?? []) as WorkspaceRow[]
      setWorkspaces(rows)

      const cookieWorkspace = readCookie(WORKSPACE_COOKIE)
      const normalizedCookie = cookieWorkspace?.trim() || null
      const found =
        normalizedCookie && rows.some((w) => String(w.id) === String(normalizedCookie))
          ? normalizedCookie
          : null
      const nextSelected = found || (rows[0]?.id ? String(rows[0].id) : null)

      setSelected(nextSelected)
      if (nextSelected && nextSelected !== normalizedCookie) {
        writeCookie(WORKSPACE_COOKIE, nextSelected)
        router.refresh()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workspaces')
    } finally {
      setLoading(false)
    }
  }, [router, supabase])

  React.useEffect(() => {
    if (!supabaseEnabled || !supabase) return
    if (!isAuthenticated) return
    void loadWorkspaces()
  }, [isAuthenticated, loadWorkspaces, supabase, supabaseEnabled])

  const createWorkspace = React.useCallback(async () => {
    if (!supabase) return
    const name = typeof window !== 'undefined' ? window.prompt('Workspace name') : null
    if (!name || !name.trim()) return

    setLoading(true)
    setError(null)
    try {
      const trimmedName = name.trim()
      let created: WorkspaceRow | null = null

      for (let attempt = 0; attempt < 3; attempt++) {
        const slug = slugify(trimmedName)
        const { data, error: supaError } = await supabase
          .from('workspaces')
          .insert({ name: trimmedName, slug })
          .select('*')
          .single()
        if (!supaError) {
          created = (data ?? null) as WorkspaceRow | null
          break
        }

        const code = (supaError as { code?: string }).code
        if (code === '23505') continue
        throw new Error(supaError.message)
      }

      if (!created?.id) {
        throw new Error('Failed to create workspace (slug conflict)')
      }

      await loadWorkspaces()
      writeCookie(WORKSPACE_COOKIE, String(created.id))
      setSelected(String(created.id))
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workspace')
    } finally {
      setLoading(false)
    }
  }, [loadWorkspaces, router, supabase])

  if (!supabaseEnabled || !isAuthenticated) return null

  return (
    <div className="hidden md:flex items-center gap-2">
      <Select
        value={selected ?? undefined}
        onValueChange={(value) => {
          setSelected(value)
          writeCookie(WORKSPACE_COOKIE, value)
          router.refresh()
        }}
        disabled={loading}
      >
        <SelectTrigger className="h-9 w-44">
          <SelectValue placeholder={loading ? 'Loading…' : 'Select workspace'} />
          <ChevronDown className="h-4 w-4 opacity-50" />
        </SelectTrigger>
        <SelectContent>
          {workspaces.length ? (
            workspaces.map((ws) => (
              <SelectItem key={String(ws.id)} value={String(ws.id)}>
                {String(ws.name || ws.id)}
              </SelectItem>
            ))
          ) : (
            <SelectItem disabled value="__empty">
              No workspaces
            </SelectItem>
          )}
        </SelectContent>
      </Select>

      <Button
        type="button"
        size="icon"
        variant="outline"
        onClick={createWorkspace}
        disabled={loading}
        aria-label="Create workspace"
      >
        <Plus className="h-4 w-4" />
      </Button>

      {error ? <span className="text-xs text-red-600">{error}</span> : null}
    </div>
  )
}
