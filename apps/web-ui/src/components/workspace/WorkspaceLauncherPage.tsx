import Link from "next/link"
import type { ReactNode } from "react"

import { NavigationWrapper } from "@/components/navigation/navigation-wrapper"

const workspaceUrl = '/hub'

const cards = [
  {
    title: "Hosted Workspace",
    eyebrow: "Managed",
    body:
      "Open the hosted Marimo workspace at /hub. This is the canonical managed path: per-user notebook UI, paired coding agent workflow, and BR MCP over HTTP.",
    ctaLabel: "Open Workspace",
    href: workspaceUrl,
    external: false,
  },
  {
    title: "Local Docker",
    eyebrow: "Self-managed",
    body:
      "Use your coding agent as the primary assistant and connect it to Brain Researcher MCP over stdio or Docker stdio. Keep files, notebooks, and runtime local.",
    ctaLabel: "Open Docs",
    href: "/docs",
    external: false,
  },
  {
    title: "HPC",
    eyebrow: "Self-managed",
    body:
      "Work from a login node or cluster-facing dev environment. Use a coding agent with BR MCP over stdio, and route heavy runs through Neurodesk and Slurm recipes.",
    ctaLabel: "Open Docs",
    href: "/docs",
    external: false,
  },
]

function CtaLink(props: {
  href: string
  label: string
  external?: boolean
}) {
  const className =
    "inline-flex items-center rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-900 transition hover:border-slate-900 hover:bg-slate-50"

  if (props.external) {
    return (
      <a className={className} href={props.href} rel="noreferrer" target="_blank">
        {props.label}
      </a>
    )
  }

  return (
    <Link className={className} href={props.href}>
      {props.label}
    </Link>
  )
}

type WorkspaceLauncherPageProps = {
  footer?: ReactNode
}

export function WorkspaceLauncherPage({ footer }: WorkspaceLauncherPageProps) {
  return (
    <NavigationWrapper>
      <main className="min-h-[calc(100dvh-4rem)] bg-[radial-gradient(circle_at_top_left,_rgba(15,23,42,0.05),_transparent_35%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)]">
        <div className="mx-auto flex max-w-6xl flex-col gap-12 px-6 py-16 md:px-10">
          <section className="grid gap-8 lg:grid-cols-[1.4fr_0.9fr] lg:items-end">
            <div className="space-y-5">
              <div className="inline-flex items-center rounded-full border border-slate-300/80 bg-white/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-600">
                Brain Researcher Workspace
              </div>
              <div className="space-y-4">
                <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 md:text-6xl">
                  Studio is now the workspace launcher, not the notebook UI.
                </h1>
                <p className="max-w-3xl text-base leading-7 text-slate-700 md:text-lg">
                  The hosted product path now enters the managed Marimo workspace at
                  <code className="mx-1 rounded bg-slate-100 px-1 py-0.5 text-sm">/hub</code>.
                  Self-managed users stay in their coding agent and connect to the same
                  Brain Researcher MCP intelligence layer with a different transport.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <CtaLink href={workspaceUrl} label="Launch Hosted Workspace" />
                <CtaLink href="/docs" label="View Deployment Docs" />
              </div>
            </div>

            <aside className="rounded-[2rem] border border-slate-200/80 bg-white/85 p-6 shadow-[0_20px_80px_-40px_rgba(15,23,42,0.4)] backdrop-blur">
              <div className="space-y-3">
                <div className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Canonical Paths
                </div>
                <div className="space-y-3 text-sm text-slate-700">
                  <p>
                    Hosted cloud: <span className="font-medium text-slate-950">Marimo at /hub + paired agent workflow + BR MCP over HTTP</span>
                  </p>
                  <p>
                    Local Docker: <span className="font-medium text-slate-950">coding agent + BR MCP over stdio / Docker stdio</span>
                  </p>
                  <p>
                    HPC: <span className="font-medium text-slate-950">coding agent + BR MCP over stdio, heavy execution via Neurodesk / Slurm recipes</span>
                  </p>
                </div>
              </div>
            </aside>
          </section>

          <section className="grid gap-5 lg:grid-cols-3">
            {cards.map((card) => (
              <article
                key={card.title}
                className="flex h-full flex-col justify-between rounded-[1.75rem] border border-slate-200/80 bg-white/90 p-6 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.45)]"
              >
                <div className="space-y-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    {card.eyebrow}
                  </div>
                  <div className="space-y-2">
                    <h2 className="text-2xl font-semibold text-slate-950">{card.title}</h2>
                    <p className="text-sm leading-6 text-slate-700">{card.body}</p>
                  </div>
                </div>
                <div className="mt-8">
                  <CtaLink external={card.external} href={card.href} label={card.ctaLabel} />
                </div>
              </article>
            ))}
          </section>

          {footer ? <div className="pt-2">{footer}</div> : null}
        </div>
      </main>
    </NavigationWrapper>
  )
}
