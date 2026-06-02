import type { MetadataRoute } from 'next'

const PUBLIC_ROUTES = [
  '/',
  '/understand-br',
  '/datasets',
  '/datasets/explorer',
  '/resources',
  '/docs',
  '/demos',
  '/studio/plan-preview',
  '/auth/login',
  '/auth/signup',
  '/auth/forgot',
]

export default function sitemap(): MetadataRoute.Sitemap {
  const siteUrl = (
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.NEXT_PUBLIC_APP_URL ||
    'https://brain-researcher.com'
  ).replace(/\/$/, '')

  return PUBLIC_ROUTES.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: new Date(),
    changeFrequency: route === '/' ? 'weekly' : 'monthly',
    priority: route === '/' ? 1 : 0.7,
  }))
}
