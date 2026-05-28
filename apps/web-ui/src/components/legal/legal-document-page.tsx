import Link from 'next/link'

import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

interface LegalSection {
  title: string
  paragraphs: string[]
}

interface LegalDocumentPageProps {
  eyebrow: string
  title: string
  lastUpdated: string
  summary: string
  intro: string[]
  sections: LegalSection[]
}

export function LegalDocumentPage({
  eyebrow,
  title,
  lastUpdated,
  summary,
  intro,
  sections,
}: LegalDocumentPageProps) {
  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-slate-50">
        <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 bg-slate-900 px-6 py-8 text-white sm:px-8">
              <p className="text-sm font-medium uppercase tracking-[0.2em] text-slate-300">
                {eyebrow}
              </p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                {title}
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-300">{summary}</p>
              <p className="mt-4 text-sm text-slate-400">Last updated {lastUpdated}</p>
            </div>

            <div className="px-6 py-8 sm:px-8">
              <div className="space-y-4 text-sm leading-7 text-slate-700">
                {intro.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>

              <div className="mt-10 space-y-8">
                {sections.map((section) => (
                  <section
                    key={section.title}
                    className="rounded-xl border border-slate-200 bg-slate-50/80 p-5"
                  >
                    <h2 className="text-lg font-semibold text-slate-900">{section.title}</h2>
                    <div className="mt-3 space-y-3 text-sm leading-7 text-slate-700">
                      {section.paragraphs.map((paragraph) => (
                        <p key={paragraph}>{paragraph}</p>
                      ))}
                    </div>
                  </section>
                ))}
              </div>

              <section className="mt-10 rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-slate-900">Questions</h2>
                <p className="mt-3 text-sm leading-7 text-slate-700">
                  If you have questions about these policies or want help with your account,
                  contact{' '}
                  <a
                    href="mailto:support@brain-researcher.com"
                    className="font-medium text-primary underline"
                  >
                    support@brain-researcher.com
                  </a>
                  .
                </p>
                <div className="mt-5 flex flex-wrap gap-3">
                  <Link
                    href="/auth/signup"
                    className="inline-flex items-center rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800"
                  >
                    Create account
                  </Link>
                  <Link
                    href="/auth/login"
                    className="inline-flex items-center rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                  >
                    Sign in
                  </Link>
                </div>
              </section>
            </div>
          </div>
        </div>
      </div>
    </NavigationWrapper>
  )
}
