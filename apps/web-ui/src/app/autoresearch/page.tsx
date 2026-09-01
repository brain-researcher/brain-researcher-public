import type { Metadata } from 'next'
import { Suspense } from 'react'

import { AutoresearchExperience } from '@/components/autoresearch/autoresearch-experience'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'

export const metadata: Metadata = {
  title: 'BR Autoresearch | Brain Researcher',
  description:
    'A public call for researchers to propose scientific questions for BR Autoresearch exploration.',
}

export const dynamic = 'force-dynamic'

export default function AutoresearchPage() {
  const proposalDestination = process.env.AUTORESEARCH_PROPOSAL_URL?.trim() || undefined

  return (
    <NavigationWrapper>
      <Suspense
        fallback={
          <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:px-8">
            <p className="text-sm text-gray-600">Loading the research landscape.</p>
          </section>
        }
      >
        <AutoresearchExperience proposalDestination={proposalDestination} />
      </Suspense>
    </NavigationWrapper>
  )
}
