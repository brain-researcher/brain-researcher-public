import { redirect } from 'next/navigation'

type SearchParams = Record<string, string | string[] | undefined>

function toSearchString(searchParams: SearchParams): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(searchParams)) {
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, v)
    } else if (typeof value === 'string') {
      params.set(key, value)
    }
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export default function KnowledgeGraphExploreRedirectPage({
  searchParams,
}: {
  searchParams: SearchParams
}) {
  redirect(`/kg${toSearchString(searchParams)}`)
}
