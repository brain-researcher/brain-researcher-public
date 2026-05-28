'use client'

import { useEffect, useState } from 'react'

type FeedbackListItem = {
  id: string
  stored_at: string
  message: string
}

type FeedbackDetail = {
  id: string
  stored_at: string
  message: string
}

export default function FeedbackAdminPage() {
  const [items, setItems] = useState<FeedbackDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true)
        setError(null)

        const listResp = await fetch('/api/feedback?limit=50')
        if (!listResp.ok) throw new Error(`List failed: ${listResp.status}`)
        const listData: { submissions: FeedbackListItem[] } = await listResp.json()

        const details = await Promise.all(
          listData.submissions.map(async (item) => {
            try {
              const detailResp = await fetch(`/api/feedback/${item.id}`)
              if (!detailResp.ok) throw new Error('detail fetch failed')
              const detail: FeedbackDetail = await detailResp.json()
              return detail
            } catch {
              return { ...item, message: item.message }
            }
          })
        )

        setItems(details)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load feedback')
      } finally {
        setLoading(false)
      }
    }

    run()
  }, [])

  return (
    <div className="mx-auto max-w-4xl p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Feedback Inbox</h1>
        <p className="text-sm text-muted-foreground">
          Recent submissions from the in-app feedback widget (latest 50).
        </p>
      </div>

      {loading && <div className="text-sm text-muted-foreground">Loading…</div>}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {!loading && !error && items.length === 0 && (
        <div className="text-sm text-muted-foreground">No feedback yet.</div>
      )}

      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="border rounded-lg p-4 shadow-sm bg-card">
            <div className="flex justify-between items-center gap-2 mb-2">
              <div className="font-mono text-xs text-muted-foreground">{item.id}</div>
              <div className="text-xs text-muted-foreground">
                {new Date(item.stored_at).toLocaleString()}
              </div>
            </div>
            <p className="text-sm whitespace-pre-line break-words">{item.message || '(no message stored)'}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

