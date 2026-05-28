"use client"

import { useEffect, useState } from "react"
import Link from "next/link"

import { NavigationWrapper } from "@/components/navigation/navigation-wrapper"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { extractErrorCode, planForError } from "@/lib/errors"

type FileItem = {
  id?: string
  file_id?: string
  file_name?: string
  size_bytes?: number
  created_at?: string
}

export default function VaultFilesPage() {
  const [files, setFiles] = useState<FileItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorAction, setErrorAction] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        setError(null)
        setErrorAction(null)
        setLoading(true)
        const res = await fetch("/api/files", { signal: controller.signal, cache: "no-store" })
        if (!res.ok) {
          let body: any = null
          try {
            body = await res.clone().json()
          } catch {
            /* ignore */
          }
          const code = extractErrorCode(body)
          const plan = planForError(code)
          const detail = (body && (body.detail || body.error)) || res.statusText || "Failed to load files"
          setError(detail)
          setErrorAction(plan.fallbackAction || null)
        } else {
          const data = await res.json()
          const list = Array.isArray(data) ? data : data.files || []
          setFiles(list)
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setError(err.message || "Failed to load files")
        }
      } finally {
        setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [])

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 space-y-4">
          <Alert>
            <AlertTitle>Vault · Files</AlertTitle>
            <AlertDescription>
              Files live in Vault. Legacy links under <code>/files</code> redirect here.
            </AlertDescription>
          </Alert>

          <header className="mb-2">
            <h1 className="text-2xl font-semibold tracking-tight">Files</h1>
            <p className="text-sm text-muted-foreground">Your uploaded files via Agent.</p>
          </header>

          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
              {error}
              {errorAction === "retry" && (
                <div className="mt-3">
                  <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
                    Retry
                  </Button>
                </div>
              )}
              {errorAction === "login" && (
                <div className="mt-3 text-sm">
                  <Link
                    className="text-primary underline"
                    href="/auth/login?callbackUrl=%2Fvault%2Ffiles"
                  >
                    Login to continue
                  </Link>
                </div>
              )}
            </div>
          )}

          {!loading && !error && files.length === 0 && (
            <div className="rounded-lg border bg-card p-6 text-center text-muted-foreground">
              No files yet. Upload via chat or CLI: <code>br files upload path/to/file</code>
            </div>
          )}

          {!loading && !error && files.length > 0 && (
            <div className="divide-y rounded-lg border bg-card">
              {files.map((f) => {
                const id = f.id || f.file_id || ""
                return (
                  <div key={id} className="flex items-center justify-between px-4 py-3">
                    <div className="min-w-0">
                      <div className="font-medium">{f.file_name || id}</div>
                      <div className="text-xs text-muted-foreground">
                        {f.size_bytes ? `${(f.size_bytes / 1024).toFixed(1)} KB` : "size unknown"}
                      </div>
                    </div>
                    <Link
                      href={`/api/files/${id}`}
                      className="text-sm text-primary underline hover:opacity-80"
                    >
                      Download
                    </Link>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </NavigationWrapper>
  )
}
