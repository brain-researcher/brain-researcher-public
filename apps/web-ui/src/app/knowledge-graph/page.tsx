import { redirect } from 'next/navigation'

type SearchParams = Record<string, string | string[] | undefined>

function toSearchParams(searchParams: SearchParams) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(searchParams)) {
    if (value === undefined) continue
    if (Array.isArray(value)) {
      value.forEach((entry) => search.append(key, entry))
    } else {
      search.set(key, value)
    }
  }
  return search
}

export default function KnowledgeGraphRedirect({
  searchParams,
}: {
  searchParams: SearchParams
}) {
  const query = toSearchParams(searchParams).toString()
  redirect(`/kg${query ? `?${query}` : ''}`)
}

export const dynamic = 'force-dynamic'
