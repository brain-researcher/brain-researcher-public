import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import NextDynamic from 'next/dynamic'
import Script from 'next/script'
import { Providers } from '@/components/providers'
import { NextIntlClientProvider } from 'next-intl'
import { getMessages } from 'next-intl/server'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
})

// Dynamically import KeyboardShortcuts to avoid SSR issues
const KeyboardShortcuts = NextDynamic(
  () => import('@/components/keyboard/KeyboardShortcuts'),
  { ssr: false }
)

const PUBLIC_RUNTIME_KEYS = [
  'NEXT_PUBLIC_AGENT_API',
  'NEXT_PUBLIC_BR_KG_API',
  'NEXT_PUBLIC_BR_KG_API',
  'NEXT_PUBLIC_NICLIP_API',
  'NEXT_PUBLIC_WS_URL',
  'NEXT_PUBLIC_USE_API_PROXY',
  'ORCHESTRATOR_HOST',
  'ORCHESTRATOR_PORT',
  'AGENT_HOST',
  'AGENT_PORT',
  'KG_HOST',
  'KG_PORT',
  'BR_KG_HOST',
  'BR_KG_PORT',
  'NICLIP_HOST',
  'NICLIP_PORT',
  'WEB_UI_HOST',
  'WEB_UI_PORT',
  'HTTP_PROTOCOL',
  'WS_PROTOCOL',
] as const

const serializeRuntimeEnv = () => {
  const env = PUBLIC_RUNTIME_KEYS.reduce<Record<string, string>>((acc, key) => {
    const value = process.env[key]
    if (value) {
      acc[key] = value
    }
    return acc
  }, {})

  return `window.__ENV = Object.assign(window.__ENV || {}, ${JSON.stringify(env).replace(/</g, '\\u003c')});`
}

export const metadata: Metadata = {
  title: 'Brain Researcher',
  description: 'AI-native neuroimaging research assistant for reproducible analysis.',
  icons: {
    icon: [
      { url: '/favicon.svg', type: 'image/svg+xml' },
    ],
    shortcut: ['/favicon.svg'],
  },
}

export const dynamic = 'force-dynamic'

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const messages = await getMessages()
  const runtimeEnvScript = serializeRuntimeEnv()

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <Script id="runtime-env" strategy="beforeInteractive">
          {runtimeEnvScript}
        </Script>
      </head>
      <body className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased`}>
        {/* Skip link for keyboard users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only fixed top-2 left-2 z-50 rounded bg-blue-600 px-3 py-2 text-white shadow"
        >
          Skip to main content
        </a>
        <Providers>
          <NextIntlClientProvider messages={messages}>
            <main id="main-content" tabIndex={-1} role="main">
              {children}
            </main>
            {/* Global keyboard shortcuts component */}
            <KeyboardShortcuts />
          </NextIntlClientProvider>
        </Providers>
      </body>
    </html>
  )
}
