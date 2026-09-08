import { loadLocalData } from './localAdapter'
import { loadSupabaseData } from './supabaseAdapter'
import { hasSupabaseConfig, supabase } from './supabase'

export async function loadData() {
  if (hasSupabaseConfig && supabase) {
    try { return { data: await loadSupabaseData(), source: 'supabase' as const } } catch { /* local fallback is intentional */ }
  }
  return { data: await loadLocalData(), source: 'local' as const }
}
