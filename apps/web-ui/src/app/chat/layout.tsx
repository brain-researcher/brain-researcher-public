import type { ReactNode } from 'react'
import { NextIntlClientProvider } from 'next-intl'
import { getMessages } from 'next-intl/server'

export const dynamic = 'force-dynamic'

export default async function ChatLayout({ children }: { children: ReactNode }) {
  const messages = await getMessages()

  return <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>
}

