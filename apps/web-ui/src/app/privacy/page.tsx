import type { Metadata } from 'next'

import { LegalDocumentPage } from '@/components/legal/legal-document-page'

export const metadata: Metadata = {
  title: 'Privacy Policy | Brain Researcher',
  description: 'Privacy Policy for the Brain Researcher web application.',
}

const sections = [
  {
    title: 'Information We Process',
    paragraphs: [
      'When you create or use an account, we may process account identifiers such as your name, email address, authentication metadata, and workspace-related settings.',
      'When you use the product, we may also process prompts, uploaded materials, workflow inputs and outputs, usage events, and system logs needed to operate, secure, debug, and improve the service.',
    ],
  },
  {
    title: 'Why We Use Information',
    paragraphs: [
      'We use information to provide Brain Researcher features, authenticate users, store and retrieve workspaces, support collaboration, monitor reliability, investigate abuse, and communicate important service updates.',
      'If you opt in to product communications, we may also use your contact information to send updates and research-related announcements.',
    ],
  },
  {
    title: 'Sharing and Service Providers',
    paragraphs: [
      'Brain Researcher may rely on infrastructure providers and integrated model or platform services to deliver functionality. Information may be processed by those providers when needed to operate the product.',
      'We may also disclose information when required to comply with law, enforce platform rules, or protect the security of the service and its users.',
    ],
  },
  {
    title: 'Retention and Security',
    paragraphs: [
      'We retain information for as long as it is reasonably needed to operate the service, meet legal obligations, resolve disputes, and support reproducibility or account recovery workflows.',
      'We use technical and organizational safeguards intended to reduce unauthorized access or misuse, but no online system can guarantee absolute security.',
    ],
  },
  {
    title: 'Your Choices',
    paragraphs: [
      'You can contact us to request help with access, correction, deletion, or questions about how your account data is being handled.',
      'You can opt out of non-essential product emails at any time by using the unsubscribe mechanism in those messages or by contacting support.',
    ],
  },
]

export default function PrivacyPage() {
  return (
    <LegalDocumentPage
      eyebrow="Legal"
      title="Privacy Policy"
      lastUpdated="March 23, 2026"
      summary="This page explains the main categories of information Brain Researcher processes and how that information is used."
      intro={[
        'Brain Researcher is built for research workflows, so privacy expectations matter. This summary explains the main product-level practices that apply when you use the web app and related services.',
        'If your use case involves regulated data, institutional review requirements, or a separate agreement, make sure those requirements are satisfied before uploading or processing sensitive material.',
      ]}
      sections={sections}
    />
  )
}
