import type { Metadata } from 'next'

import { LegalDocumentPage } from '@/components/legal/legal-document-page'

export const metadata: Metadata = {
  title: 'Terms of Service | Brain Researcher',
  description: 'Terms of Service for the Brain Researcher web application.',
}

const sections = [
  {
    title: 'Using Brain Researcher',
    paragraphs: [
      'You may use Brain Researcher to explore research questions, browse datasets, draft analysis plans, and manage reproducible workflows. You are responsible for the accuracy of your account information and for keeping your credentials secure.',
      'You agree not to misuse the service, interfere with other users, attempt unauthorized access, or use the platform in a way that violates applicable law, dataset licenses, or institutional policy.',
    ],
  },
  {
    title: 'Research Outputs and Decisions',
    paragraphs: [
      'Brain Researcher provides software assistance, not professional, medical, legal, or regulatory advice. Model-generated suggestions, summaries, and workflow recommendations should be reviewed by a qualified human before being relied on for research, publication, or operational decisions.',
      'You remain responsible for validating methods, interpreting results, and deciding whether an analysis is appropriate for your scientific or organizational use case.',
    ],
  },
  {
    title: 'Your Data and Content',
    paragraphs: [
      'You are responsible for ensuring that you have the rights and permissions needed to upload prompts, datasets, notes, and other materials you use with the service.',
      'If you work with third-party datasets, you must follow the license, access, privacy, and consent requirements that apply to those materials. Brain Researcher may integrate with external services, and their terms can also apply to the parts of the workflow they handle.',
    ],
  },
  {
    title: 'Service Availability',
    paragraphs: [
      'The platform may change over time, including feature updates, model changes, maintenance windows, and beta functionality. We may suspend or limit access when needed to protect the service, investigate abuse, or comply with legal obligations.',
      'We aim to operate the service reliably, but we do not guarantee uninterrupted availability or error-free output.',
    ],
  },
  {
    title: 'Updates to These Terms',
    paragraphs: [
      'We may update these terms as the product evolves. Material updates will be reflected on this page by changing the effective date shown above.',
    ],
  },
]

export default function TermsPage() {
  return (
    <LegalDocumentPage
      eyebrow="Legal"
      title="Terms of Service"
      lastUpdated="March 23, 2026"
      summary="These terms describe the basic rules for using the Brain Researcher web application and related services."
      intro={[
        'By creating an account, accessing the web app, or using Brain Researcher services, you agree to these terms.',
        'This page is intended to give users a clear product-level view of how the service should be used. If you need clarification for a specific institutional or contractual requirement, contact us before relying on the service.',
      ]}
      sections={sections}
    />
  )
}
