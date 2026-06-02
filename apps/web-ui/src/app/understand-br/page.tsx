import type { Metadata } from 'next'
import Image from 'next/image'
import Link from 'next/link'
import {
  ArrowRight,
  BookOpen,
  Brain,
  CheckCircle2,
  ExternalLink,
  FileText,
  GitBranch,
  Network,
  Plug,
  Search,
  XCircle,
} from 'lucide-react'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'

export const metadata: Metadata = {
  title: 'Understand BR | Brain Researcher',
  description:
    'A short visual explanation of how Brain Researcher turns neuroscience questions into reviewable, evidence-linked workflows.',
}

const CODEWIKI_URL = 'https://deepwiki.com/zjc062/brain_researcher'

const storySteps = [
  {
    label: 'Step 1',
    title: 'Start with a messy research question',
    body: 'A neuroscience question usually arrives with unclear datasets, fragile assumptions, and many possible analysis paths.',
    image: '/understand-br/0.png',
    alt: 'Illustrated opening panel for a messy research question',
  },
  {
    label: 'Step 2',
    title: 'Organize the question',
    body: 'BR turns the question into a structured intent: what evidence is needed, what data could support it, and what needs review.',
    image: '/understand-br/1.png',
    alt: 'Illustrated panel for organizing a research question',
  },
  {
    label: 'Step 3',
    title: 'Connect evidence and resources',
    body: 'The system links papers, datasets, brain concepts, tools, and prior runs so the plan is not just a prompt.',
    image: '/understand-br/2.png',
    alt: 'Illustrated panel for evidence and resource connections',
  },
  {
    label: 'Step 4',
    title: 'Build a reviewable workflow',
    body: 'BR proposes a plan with visible assumptions, candidate methods, expected inputs, and handoff boundaries.',
    image: '/understand-br/3.png',
    alt: 'Illustrated panel for building a workflow',
  },
  {
    label: 'Step 5',
    title: 'Hand it to the right surface',
    body: 'The same work can move into Hub, Studio, MCP, Cursor, Codex, Claude Code, or a more controlled runtime.',
    image: '/understand-br/4.png',
    alt: 'Illustrated panel for handoff to execution surfaces',
  },
  {
    label: 'Step 6',
    title: 'Review the result, not just the answer',
    body: 'The researcher checks evidence, report artifacts, assumptions, and failure modes before treating a result as useful.',
    image: '/understand-br/5.png',
    alt: 'Illustrated panel for reviewing a result',
  },
]

const productSurfaces = [
  {
    title: 'Datasets',
    href: '/datasets',
    icon: Search,
    body: 'Find research datasets and inspect readiness before choosing an analysis path.',
  },
  {
    title: 'Workflows',
    href: '/library',
    icon: GitBranch,
    body: 'Start from curated analysis workflows instead of rebuilding every plan from scratch.',
  },
  {
    title: 'Knowledge Graph',
    href: '/kg',
    icon: Network,
    body: 'Use graph-backed concepts, evidence, papers, tasks, datasets, and tools to pressure-test a plan.',
  },
  {
    title: 'MCP',
    href: '/mcp/setup',
    icon: Plug,
    body: 'Connect BR to the coding agents and IDEs where research work already happens.',
  },
  {
    title: 'Hub / Studio',
    href: '/hub',
    icon: Brain,
    body: 'Use a browser workspace for notebooks, runs, review context, and research activity.',
  },
  {
    title: 'Demos',
    href: '/demos',
    icon: FileText,
    body: 'Inspect concrete case reports and evidence bundles before starting your own workflow.',
  },
]

const isItems = [
  'A planning, evidence, and workflow handoff layer for neuroscience research.',
  'A way to keep datasets, methods, reports, and agents connected through one research context.',
  'A review surface where assumptions and execution boundaries stay visible.',
]

const isNotItems = [
  'Not a guarantee that a scientific conclusion is correct.',
  'Not a replacement for researcher judgment, peer review, or dataset access rules.',
  'Not a claim that every workflow is fully executable in every runtime today.',
]

export default function UnderstandBrainResearcherPage() {
  return (
    <NavigationWrapper>
      <main className="min-h-screen bg-slate-50 text-slate-950">
        <section className="border-b border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-6 py-14">
            <div className="max-w-3xl space-y-7">
              <div className="inline-flex items-center rounded-full border border-slate-200 px-3 py-1 text-xs font-medium uppercase text-slate-600">
                Understand BR
              </div>

              <div className="space-y-4">
                <h1 className="text-4xl font-semibold text-slate-950 sm:text-6xl">
                  From question to reviewable research workflow
                </h1>
                <p className="max-w-2xl text-lg leading-8 text-slate-600">
                  Brain Researcher turns a neuroscience question into an evidence-linked plan,
                  a workflow handoff, and a reportable trail that a researcher can inspect.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <Button asChild size="lg">
                  <Link href="/demos">
                    View demos
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link href="/mcp/setup">Set up MCP</Link>
                </Button>
              </div>

              <div className="grid max-w-2xl gap-3 text-sm text-slate-600 sm:grid-cols-3">
                <div className="border-l-2 border-blue-500 pl-3">Question</div>
                <div className="border-l-2 border-emerald-500 pl-3">Evidence</div>
                <div className="border-l-2 border-amber-500 pl-3">Handoff</div>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-14">
          <div className="max-w-3xl space-y-3">
            <div className="text-xs font-medium uppercase text-slate-500">
              Mental model
            </div>
            <h2 className="text-3xl font-semibold text-slate-950">
              Question to evidence to workflow to review
            </h2>
            <p className="text-slate-600">
              The storyboard below is the simplest way to read BR: it is not just a chat box,
              and it is not just a notebook. It is the connective layer between research intent,
              evidence, methods, execution surfaces, and human review.
            </p>
          </div>

          <div className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {storySteps.map((step) => (
              <article
                key={step.label}
                className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
              >
                <div className="aspect-[1055/1491] bg-slate-100">
                  <Image
                    src={step.image}
                    alt={step.alt}
                    width={1055}
                    height={1491}
                    className="h-full w-full object-cover"
                  />
                </div>
                <div className="space-y-2 p-5">
                  <div className="text-xs font-medium uppercase text-slate-500">
                    {step.label}
                  </div>
                  <h3 className="text-lg font-semibold text-slate-950">{step.title}</h3>
                  <p className="text-sm leading-6 text-slate-600">{step.body}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-6 py-14">
            <div className="max-w-3xl space-y-3">
              <div className="text-xs font-medium uppercase text-slate-500">
                What BR contains
              </div>
              <h2 className="text-3xl font-semibold text-slate-950">
                One research context across multiple surfaces
              </h2>
              <p className="text-slate-600">
                Each surface has a narrower job. Together they keep the research question,
                evidence, datasets, workflows, and agents aligned.
              </p>
            </div>

            <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {productSurfaces.map((surface) => {
                const Icon = surface.icon
                return (
                  <Link
                    key={surface.title}
                    href={surface.href}
                    className="group rounded-lg border border-slate-200 bg-slate-50 p-5 transition-colors hover:border-slate-300 hover:bg-white"
                  >
                    <div className="flex items-start gap-4">
                      <div className="rounded-md border border-slate-200 bg-white p-2 text-slate-700">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div className="space-y-1">
                        <h3 className="font-semibold text-slate-950 group-hover:underline">
                          {surface.title}
                        </h3>
                        <p className="text-sm leading-6 text-slate-600">{surface.body}</p>
                      </div>
                    </div>
                  </Link>
                )
              })}
            </div>
          </div>
        </section>

        <section className="mx-auto grid max-w-7xl gap-6 px-6 py-14 lg:grid-cols-2">
          <div className="rounded-lg border border-emerald-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium uppercase text-emerald-700">
              <CheckCircle2 className="h-4 w-4" />
              BR is
            </div>
            <ul className="space-y-4 text-sm leading-6 text-slate-700">
              {isItems.map((item) => (
                <li key={item} className="flex gap-3">
                  <CheckCircle2 className="mt-1 h-4 w-4 flex-none text-emerald-600" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border border-rose-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium uppercase text-rose-700">
              <XCircle className="h-4 w-4" />
              BR is not
            </div>
            <ul className="space-y-4 text-sm leading-6 text-slate-700">
              {isNotItems.map((item) => (
                <li key={item} className="flex gap-3">
                  <XCircle className="mt-1 h-4 w-4 flex-none text-rose-600" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-6 py-12">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-center">
              <div className="space-y-3">
                <div className="text-xs font-medium uppercase text-slate-500">
                  Next step
                </div>
                <h2 className="text-3xl font-semibold text-slate-950">
                  Move from understanding to inspecting
                </h2>
                <p className="max-w-2xl text-slate-600">
                  Start with public case reports, open the hosted workspace, or connect BR to the
                  agent environment where you already work.
                </p>
              </div>

              <div className="flex flex-col gap-3">
                <Button asChild>
                  <Link href="/demos">View demos</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/hub">Open Hub</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/mcp/setup">Set up MCP</Link>
                </Button>
              </div>
            </div>

            <div className="mt-10 flex flex-col gap-3 border-t border-slate-200 pt-6 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                <span>For implementation details, read the code map.</span>
              </div>
              <a
                href={CODEWIKI_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 font-medium text-slate-950 underline underline-offset-4 hover:text-blue-700"
              >
                Open CodeWiki
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>
          </div>
        </section>
      </main>
    </NavigationWrapper>
  )
}
