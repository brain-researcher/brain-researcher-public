import { createClient, type SupabaseClient } from '@supabase/supabase-js'

let supabaseClient: SupabaseClient | null = null

export const resolveSupabaseUrl = () =>
  process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL || ''

export const resolveSupabaseAnonKey = () =>
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY ||
  process.env.SUPABASE_ANON_KEY ||
  process.env.SUPABASE_PUBLISHABLE_DEFAULT_KEY ||
  ''

export const isSupabaseEnabled = () => {
  const url = resolveSupabaseUrl()
  const key = resolveSupabaseAnonKey()
  return Boolean(url && key)
}

export function getSupabaseClient(): SupabaseClient | null {
  if (!isSupabaseEnabled()) {
    return null
  }
  if (!supabaseClient) {
    supabaseClient = createClient(resolveSupabaseUrl(), resolveSupabaseAnonKey())
  }
  return supabaseClient
}
