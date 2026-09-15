import { afterEach, describe, expect, it, vi } from 'vitest'

const loadLocalData = vi.fn()
const loadSupabaseData = vi.fn()
let configured = true

vi.mock('./localAdapter', () => ({ loadLocalData }))
vi.mock('./supabaseAdapter', () => ({ loadSupabaseData }))
vi.mock('./supabase', () => ({ get hasSupabaseConfig() { return configured }, get supabase() { return configured ? {} : null } }))

afterEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  configured = true
  vi.unstubAllEnvs()
})

async function importAdapter() {
  return import('./adapter')
}

describe('data source selection', () => {
  it('uses the configured Supabase adapter by default', async () => {
    vi.stubEnv('VITE_DATA_MODE', '')
    loadSupabaseData.mockResolvedValue({ metrics: { qualified_ge_50: 51 } })
    const { loadData } = await importAdapter()

    await expect(loadData()).resolves.toEqual({ data: { metrics: { qualified_ge_50: 51 } }, source: 'supabase' })
    expect(loadSupabaseData).toHaveBeenCalledOnce()
    expect(loadLocalData).not.toHaveBeenCalled()
  })

  it('uses explicit local mode for development/demo data', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'local')
    loadLocalData.mockResolvedValue({ leads: [] })
    const { loadData } = await importAdapter()

    await expect(loadData()).resolves.toEqual({ data: { leads: [] }, source: 'local' })
    expect(loadLocalData).toHaveBeenCalledOnce()
    expect(loadSupabaseData).not.toHaveBeenCalled()
  })

  it('fails visibly when production Supabase configuration is missing', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'production')
    configured = false
    const { loadData } = await importAdapter()

    await expect(loadData()).rejects.toThrow('production_supabase_not_configured')
    expect(loadLocalData).not.toHaveBeenCalled()
  })

  it('propagates Supabase query errors without loading local data', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'production')
    loadSupabaseData.mockRejectedValue(new Error('supabase_query_failed'))
    const { loadData } = await importAdapter()

    await expect(loadData()).rejects.toThrow('supabase_query_failed')
    expect(loadLocalData).not.toHaveBeenCalled()
  })
})
