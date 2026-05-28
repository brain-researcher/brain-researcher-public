 'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useState, useEffect } from 'react'

type Props = { initialQuery?: string }

export default function ConceptSearch({ initialQuery = '' }: Props) {
  const router = useRouter()
  const params = useSearchParams()
  const [value, setValue] = useState(initialQuery)

  // keep input in sync when navigating back/forward
  useEffect(() => {
    const q = params.get('q') || ''
    setValue(q)
  }, [params])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const qs = new URLSearchParams()
    if (value.trim()) qs.set('q', value.trim())
    router.push(`/concepts${qs.toString() ? `?${qs.toString()}` : ''}`)
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-2">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search ONVOC concepts…"
        className="w-full border border-gray-300 rounded-lg px-3 py-2 shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
      <button
        type="submit"
        className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 transition-colors"
      >
        Search
      </button>
    </form>
  )
}
