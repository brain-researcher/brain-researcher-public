type NodeRef = { id: string; label: string }

type Props = {
  parents: NodeRef[]
  childConcepts: NodeRef[]
}

export default function ParentsChildren({ parents, childConcepts }: Props) {
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="p-4 border border-gray-200 rounded-lg bg-white">
        <div className="font-semibold text-sm mb-2">Parents</div>
        {parents.length === 0 ? (
          <div className="text-sm text-gray-500">None</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {parents.map((p) => (
              <span key={p.id} className="px-2 py-1 text-xs bg-gray-100 rounded">
                {p.label}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="p-4 border border-gray-200 rounded-lg bg-white">
        <div className="font-semibold text-sm mb-2">Children</div>
        {childConcepts.length === 0 ? (
          <div className="text-sm text-gray-500">None</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {childConcepts.map((c) => (
              <span key={c.id} className="px-2 py-1 text-xs bg-gray-100 rounded">
                {c.label}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
