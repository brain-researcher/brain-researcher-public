'use client';

import { useState, useTransition } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { ChevronDown, Globe } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';

const languages = [
  { code: 'en', name: 'English', label: 'EN' },
  { code: 'es', name: 'Spanish', label: 'ES' },
  { code: 'fr', name: 'French', label: 'FR' },
  { code: 'de', name: 'German', label: 'DE' },
  { code: 'zh', name: 'Chinese', label: 'ZH' },
  { code: 'ja', name: 'Japanese', label: 'JA' },
] as const;

export function LanguageSwitcher() {
  const router = useRouter();
  const pathname = usePathname();
  const locale = useLocale();
  const [isPending, startTransition] = useTransition();
  
  const currentLanguage = languages.find(lang => lang.code === locale) || languages[0];

  const handleLanguageChange = (newLocale: string) => {
    startTransition(() => {
      // Remove the current locale from the pathname
      const pathnameWithoutLocale = pathname.replace(`/${locale}`, '') || '/';
      // Navigate to the new locale
      router.push(`/${newLocale}${pathnameWithoutLocale}`);
      
      // Store language preference
      if (typeof window !== 'undefined') {
        localStorage.setItem('preferred-locale', newLocale);
      }
    });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-2 text-sm font-medium"
          disabled={isPending}
        >
          <Globe className="h-4 w-4 mr-2" />
          <span className="hidden sm:inline">
            {currentLanguage.name}
          </span>
          <span className="sm:hidden">
            {currentLanguage.label}
          </span>
          <ChevronDown className="h-3 w-3 ml-1" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        {languages.map((language) => (
          <DropdownMenuItem
            key={language.code}
            onClick={() => handleLanguageChange(language.code)}
            className="flex items-center gap-2 cursor-pointer"
          >
            <span className="text-xs font-semibold">{language.label}</span>
            <span>{language.name}</span>
            {language.code === locale && (
              <span className="ml-auto text-xs text-muted-foreground">✓</span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
