import { ArrowUpRight } from 'lucide-react'

import type { AgendaDirection } from '@/content/autoresearch'

interface AgendaDirectionDetailProps {
  direction: AgendaDirection
  programTitle: string
  onUseQuestion: (question: string, programTitle: string) => void
}

export function AgendaDirectionDetail({
  direction,
  programTitle,
  onUseQuestion,
}: AgendaDirectionDetailProps) {
  return (
    <article
      className="min-w-0 border-y border-gray-200 bg-white px-5 py-6 sm:px-7"
      aria-labelledby={`agenda-direction-${direction.id}`}
    >
      <div className="border-b border-gray-200 pb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
          Research direction
        </p>
        <h4
          id={`agenda-direction-${direction.id}`}
          className="mt-2 text-2xl font-semibold tracking-tight text-gray-950"
        >
          {direction.title}
        </h4>
      </div>

      <dl className="grid gap-5 py-5 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
            What changed
          </dt>
          <dd className="mt-2 text-sm leading-6 text-gray-700">{direction.changed}</dd>
        </div>
        <div className="border-t border-gray-200 pt-5 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
          <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
            What remains open
          </dt>
          <dd className="mt-2 text-sm leading-6 text-gray-700">{direction.open}</dd>
        </div>
      </dl>

      <section className="border-t border-gray-200 py-5" aria-labelledby={`anchors-${direction.id}`}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h5 id={`anchors-${direction.id}`} className="text-sm font-semibold text-gray-950">
            Selected anchor papers
          </h5>
          <p className="text-xs text-gray-500">Selected examples, not an exhaustive review.</p>
        </div>
        <ul className="mt-3 divide-y divide-gray-200 border-y border-gray-200">
          {direction.anchors.map((anchor) => (
            <li key={`${anchor.url}-${anchor.citation}`}>
              <a
                href={anchor.url}
                target="_blank"
                rel="noreferrer"
                className="group flex min-h-11 items-start justify-between gap-3 py-3 text-sm text-gray-700 outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
              >
                <span className="min-w-0">
                  <span className="block font-medium text-gray-950 group-hover:underline">
                    {anchor.title}
                  </span>
                  <span className="mt-1 block text-xs text-gray-500">
                    {anchor.citation}
                    {anchor.venue ? `, ${anchor.venue}` : ''}
                    <span className="sr-only">, opens an external site</span>
                  </span>
                </span>
                <ArrowUpRight aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-gray-500" />
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className="border-t border-gray-200 py-5" aria-labelledby={`questions-${direction.id}`}>
        <h5 id={`questions-${direction.id}`} className="text-sm font-semibold text-gray-950">
          Questions BR could start from
        </h5>
        <ol className="mt-3 divide-y divide-gray-200 border-y border-gray-200">
          {direction.questions.map((question, index) => (
            <li key={question.title} className="grid gap-3 py-4 sm:grid-cols-[2.25rem_minmax(0,1fr)_auto] sm:items-start">
              <span className="font-mono text-xs text-gray-500">{String(index + 1).padStart(2, '0')}</span>
              <p className="text-sm leading-6 text-gray-800">{question.title}</p>
              <button
                type="button"
                onClick={() => onUseQuestion(question.title, programTitle)}
                className="min-h-11 text-left text-sm font-medium text-gray-950 underline decoration-gray-400 underline-offset-4 hover:decoration-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 sm:text-right"
                aria-label={`Use starting question: ${question.title}`}
              >
                Use as a starting point
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-gray-200 pt-5" aria-labelledby={`entry-${direction.id}`}>
        <h5 id={`entry-${direction.id}`} className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
          Where BR can begin
        </h5>
        <p className="mt-2 text-sm leading-6 text-gray-700">{direction.br_entry}</p>
      </section>
    </article>
  )
}
