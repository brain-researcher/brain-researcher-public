import { getRequestConfig } from 'next-intl/server'

// Minimal static-locale config; locale-based routing can be added later.
export default getRequestConfig(async () => {
  const locale = 'en'
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  }
})
