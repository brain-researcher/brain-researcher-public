import type { EvidenceGroups as Groups, StatMapEvidence } from '@/lib/kg-api'

type Props = { groups: Groups }

const Section = ({
  title,
  items,
  render,
}: {
  title: string
  items: any[]
  render: (item: any, idx: number) => JSX.Element
}) => (
  <div className="border border-gray-200 rounded-lg bg-white">
    <div className="px-4 py-3 border-b border-gray-100 font-semibold text-sm">{title}</div>
    <div className="divide-y divide-gray-100">
      {items.length === 0 ? (
        <div className="px-4 py-3 text-sm text-gray-500">No items yet.</div>
      ) : (
        items.map(render)
      )}
    </div>
  </div>
)

export default function EvidenceGroups({ groups }: Props) {
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Section
        title="Stat Maps"
        items={groups.statmaps}
        render={(m: StatMapEvidence, i) => (
          <div key={i} className="px-4 py-3 text-sm">
            <div className="font-medium">{m.contrast || m.map_id}</div>
            <div className="text-xs text-gray-500">
              {m.space || 'space?'} {m.atlas ? `• ${m.atlas}` : ''}{' '}
              {m.url ? (
                <a className="text-blue-600 hover:underline" href={m.url}>
                  download
                </a>
              ) : null}
            </div>
          </div>
        )}
      />
      <Section title="Coordinates" items={groups.coords} render={(c, i) => (
        <div key={i} className="px-4 py-3 text-sm text-gray-500">Coordinates not ingested yet.</div>
      )} />
      <Section title="Time Series" items={groups.timeseries} render={(t, i) => (
        <div key={i} className="px-4 py-3 text-sm text-gray-500">Time series not ingested yet.</div>
      )} />
      <Section title="Datasets" items={groups.datasets} render={(d, i) => (
        <div key={i} className="px-4 py-3 text-sm text-gray-500">Datasets not ingested yet.</div>
      )} />
      <Section title="Papers" items={groups.papers} render={(p, i) => (
        <div key={i} className="px-4 py-3 text-sm text-gray-500">Papers not ingested yet.</div>
      )} />
    </div>
  )
}
