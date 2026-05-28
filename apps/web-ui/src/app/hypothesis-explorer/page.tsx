import { redirect } from 'next/navigation'

type SearchParams = Record<string, string | string[] | undefined>

function toSearchString(searchParams: SearchParams): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(searchParams)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'string' && item.trim()) {
          params.append(key, item)
        }
      }
      continue
    }
    if (typeof value === 'string' && value.trim()) {
      params.set(key, value)
    }
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

export default function HypothesisExplorerLegacyPage({
  searchParams = {},
}: {
  searchParams?: SearchParams
}) {
  redirect(`/hypothesis${toSearchString(searchParams)}`)
}
