import Link from 'next/link'
import { fetchConcept, fetchConceptEvidence } from '@/lib/kg-api'
import EvidenceGroups from '@/components/kg/EvidenceGroups'
import ParentsChildren from '@/components/kg/ParentsChildren'

export const revalidate = 0

type Props = { params: { id: string } }

export default async function ConceptDetailPage({ params }: Props) {
  const concept = await fetchConcept(params.id)
  const evidence = await fetchConceptEvidence(params.id, ['statmaps'])

  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-500">Anchored on ONVOC</p>
          <h1 className="text-3xl font-semibold">{concept.label}</h1>
          <p className="text-sm text-gray-500">{concept.definition || 'No definition available.'}</p>
          {concept.synonyms?.length ? (
            <p className="text-xs text-gray-400 mt-1">Synonyms: {concept.synonyms.join(', ')}</p>
          ) : null}
        </div>
        <Link
          href="/concepts"
          className="text-sm text-blue-600 hover:text-blue-700 underline decoration-blue-400"
        >
          All Concepts
        </Link>
      </div>

      <ParentsChildren parents={concept.parents} childConcepts={concept.children} />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Evidence</h2>
          <span className="text-xs text-gray-500">
            Showing stat maps; other sources will appear as they’re ingested.
          </span>
        </div>
        <EvidenceGroups groups={evidence.groups} />
      </div>
    </div>
  )
}
