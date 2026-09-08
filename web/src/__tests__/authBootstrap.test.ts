import { describe, expect, it, vi } from 'vitest'
import { bootstrapAuth } from '../lib/authBootstrap'

function client(session: unknown | null) {
  let listener: ((event: string, value: unknown | null) => void) | undefined
  return {
    auth: {
      onAuthStateChange: vi.fn((cb: typeof listener) => { listener = cb; return { data: { subscription: { unsubscribe: vi.fn() } } } }),
      getSession: vi.fn(async () => ({ data: { session } })),
      setSession: vi.fn(async () => ({ data: { session } })),
    },
    emit: (event: string, value: unknown | null) => listener?.(event, value),
  }
}

describe('auth bootstrap', () => {
  it('keeps unresolved sessions on loading UI', async () => {
    const c = client(null); const loading: boolean[] = []
    const boot = bootstrapAuth(c, state => loading.push(state.loading))
    expect(loading.at(-1)).toBe(true); await boot.ready; expect(loading.at(-1)).toBe(false); boot.unsubscribe()
  })
  it('accepts an OAuth SIGNED_IN event before getSession resolves', async () => {
    const c = client(null); const states: any[] = []; const boot = bootstrapAuth(c, state => states.push(state)); const session = { user: { id: 'google-user' } }
    c.emit('SIGNED_IN', session); expect(states.at(-1)).toEqual({ session, loading: false }); await boot.ready
    expect(states.at(-1)).toEqual({ session, loading: false }); boot.unsubscribe()
  })
  it('returns to login on SIGNED_OUT', () => {
    const c = client({ user: { id: 'x' } }); const states: any[] = []; const boot = bootstrapAuth(c, state => states.push(state)); c.emit('SIGNED_OUT', null)
    expect(states.at(-1)).toEqual({ session: null, loading: false }); boot.unsubscribe()
  })

  it('recovers a callback fragment through Supabase setSession when storage is empty', async () => {
    const originalWindow = (globalThis as any).window
    const session = { user: { id: 'google-user' } }
    const c = client(null)
    c.auth.setSession = vi.fn(async () => ({ data: { session } }))
    ;(globalThis as any).window = { location: { hash: '#access_token=access&refresh_token=refresh', pathname: '/', search: '' }, history: { state: null, replaceState: vi.fn() } }
    const states: any[] = []; const boot = bootstrapAuth(c, state => states.push(state)); await boot.ready
    expect(c.auth.setSession).toHaveBeenCalledWith({ access_token: 'access', refresh_token: 'refresh' })
    expect(states.at(-1)).toEqual({ session, loading: false })
    boot.unsubscribe(); (globalThis as any).window = originalWindow
  })
})
