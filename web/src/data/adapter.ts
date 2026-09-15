import { loadLocalData } from './localAdapter'
import { loadSupabaseData } from './supabaseAdapter'
import { hasSupabaseConfig, supabase } from './supabase'

export type DataSource = 'supabase' | 'local'

export async function loadData() {
  if (import.meta.env.VITE_DATA_MODE === 'local') {
    return { data: await loadLocalData(), source: 'local' as const }
  }
  if (!hasSupabaseConfig || !supabase) throw new Error('production_supabase_not_configured')
  try {
    return { data: await loadSupabaseData(), source: 'supabase' as const }
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'unknown_error'
    throw new Error(`production_supabase_query_failed:${reason}`)
  }
}
