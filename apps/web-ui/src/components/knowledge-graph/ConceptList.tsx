export type Concept = { id: string; label: string; category?: string | null }

type Props = {
  concepts: Concept[]
  selectedId: string | null
  onSelect: (id: string) => void
  searchQuery: string
  setSearchQuery: (v: string) => void
}

export function ConceptList({ concepts, selectedId, onSelect, searchQuery, setSearchQuery }: Props) {
  const filtered = concepts.filter((c) => c.label.toLowerCase().includes(searchQuery.trim().toLowerCase()))

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3">
      <div className="text-sm font-semibold mb-2">ONVOC Concepts</div>
      <div className="relative mb-2">
        <input
          type="text"
          placeholder="Search concepts"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-3 pr-3 py-2 w-full border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black"
        />
      </div>
      <div className="max-h-[70vh] overflow-y-auto divide-y divide-gray-100">
        {filtered.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`w-full text-left py-2 px-2 rounded hover:bg-gray-50 ${selectedId === c.id ? 'bg-gray-100 font-semibold' : ''}`}
          >
            <div className="text-sm">{c.label}</div>
            {c.category && <div className="text-xs text-gray-500">{c.category}</div>}
          </button>
        ))}
      </div>
    </div>
  )
}
