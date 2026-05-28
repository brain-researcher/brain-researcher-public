import Link from 'next/link'
import { fetchConcepts } from '@/lib/kg-api'
import ConceptList from '@/components/kg/ConceptList'

export const revalidate = 0

export default async function ConceptsPage({ searchParams }: { searchParams?: { q?: string } }) {
  const q = searchParams?.q || ''
  const concepts = await fetchConcepts({ q, limit: 100 })

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">ONVOC Concepts</h1>
          <p className="text-sm text-gray-500">Browse the ontology and jump into evidence.</p>
        </div>
        <Link
          href="/"
          className="text-sm text-blue-600 hover:text-blue-700 underline decoration-blue-400"
        >
          Back to home
        </Link>
      </div>

      <ConceptList query={q} concepts={concepts} />
    </div>
  )
}
