import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSingleFlight, loadWithTimeout } from './loadGuard'

afterEach(() => vi.restoreAllMocks())

describe('bounded Supabase loading', () => {
  it('returns a successful query result and records no timeout', async () => {
    const diagnostics: string[] = []
    await expect(loadWithTimeout('opportunities', async () => ({ data: [1], error: null }), { timeoutMs: 20, diagnostics })).resolves.toEqual({ data: [1], error: null })
    expect(diagnostics).toEqual([])
  })

  it('rejects a failed query with a safe named diagnostic', async () => {
    const diagnostics: string[] = []
    await expect(loadWithTimeout('signals', async () => { throw new Error('secret SQL and jwt must not escape') }, { timeoutMs: 20, diagnostics })).rejects.toThrow('supabase_query_failed:signals')
    expect(diagnostics).toEqual(['supabase_query_failed:signals'])
  })

  it('aborts and rejects a permanently pending query at the deadline', async () => {
    const diagnostics: string[] = []
    let aborted = false
    const pending = loadWithTimeout('research_claims', signal => new Promise(() => signal.addEventListener('abort', () => { aborted = true })), { timeoutMs: 10, diagnostics })
    await expect(pending).rejects.toThrow('supabase_query_timeout:research_claims')
    expect(aborted).toBe(true)
    expect(diagnostics).toEqual(['supabase_query_timeout:research_claims'])
  })

  it('allows a retry after a timed-out attempt succeeds', async () => {
    let attempts = 0
    const run = () => loadWithTimeout('contacts', async () => {
      attempts += 1
      if (attempts === 1) return new Promise(() => {})
      return { data: ['contact'], error: null }
    }, { timeoutMs: 5 })
    await expect(run()).rejects.toThrow('supabase_query_timeout:contacts')
    await expect(run()).resolves.toEqual({ data: ['contact'], error: null })
  })
})

describe('single-flight loading', () => {
  it('does not start overlapping requests and permits a later retry', async () => {
    let calls = 0
    let resolveFirst: ((value: string) => void) | undefined
    const loader = createSingleFlight(() => {
      calls += 1
      if (calls > 1) return Promise.resolve('retry')
      return new Promise<string>(resolve => { resolveFirst = resolve })
    })
    const first = loader.run()
    const second = loader.run()
    expect(second).toBe(first)
    expect(calls).toBe(1)
    resolveFirst?.('done')
    await expect(first).resolves.toBe('done')
    await expect(loader.run()).resolves.toBe('retry')
    expect(calls).toBe(2)
  })
})
