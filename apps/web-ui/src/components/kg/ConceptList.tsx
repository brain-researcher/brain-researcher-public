import Link from 'next/link'
import ConceptSearch from './ConceptSearch'
import type { ConceptListItem } from '@/lib/kg-api'

type Props = {
  query: string
  concepts: ConceptListItem[]
}

export default function ConceptList({ query, concepts }: Props) {
  return (
    <div className="space-y-4">
      <ConceptSearch initialQuery={query} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {concepts.map((c) => (
          <Link
            key={c.id}
            href={`/concepts/${encodeURIComponent(c.id)}`}
            className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors bg-white shadow-sm"
          >
            <div className="text-sm text-gray-500 uppercase tracking-wide">{c.category || 'Concept'}</div>
            <div className="text-lg font-semibold leading-tight">{c.label}</div>
            <div className="text-xs text-gray-400 mt-1">{c.id}</div>
            <div className="flex flex-wrap gap-2 mt-3 text-xs text-gray-600">
              <span className="px-2 py-1 bg-gray-100 rounded">statmaps {c.counts.statmaps}</span>
              <span className="px-2 py-1 bg-gray-100 rounded">coords {c.counts.coords}</span>
              <span className="px-2 py-1 bg-gray-100 rounded">datasets {c.counts.datasets}</span>
              <span className="px-2 py-1 bg-gray-100 rounded">papers {c.counts.papers}</span>
            </div>
          </Link>
        ))}
        {concepts.length === 0 && (
          <div className="col-span-full text-sm text-gray-500">No concepts match your search.</div>
        )}
      </div>
    </div>
  )
}
