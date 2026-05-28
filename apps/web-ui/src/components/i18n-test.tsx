'use client';

import { useTranslations, useLocale } from 'next-intl';

export function I18nTest() {
  const t = useTranslations('navigation');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  
  return (
    <div className="p-4 bg-gray-100 rounded-lg">
      <h3 className="font-bold mb-2">i18n Test Component</h3>
      <div className="space-y-1 text-sm">
        <p><strong>Current locale:</strong> {locale}</p>
        <p><strong>Chat (nav):</strong> {t('chat')}</p>
        <p><strong>Dashboard (nav):</strong> {t('dashboard')}</p>
        <p><strong>Settings (common):</strong> {tCommon('settings')}</p>
        <p><strong>Loading (common):</strong> {tCommon('loading')}</p>
      </div>
    </div>
  );
}