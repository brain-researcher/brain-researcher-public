export const locales = ['en', 'zh', 'ja', 'fr', 'es', 'de'] as const;
export type Locale = typeof locales[number];
export const defaultLocale: Locale = 'en';

// Re-export for backward compatibility
export { locales as localesList };