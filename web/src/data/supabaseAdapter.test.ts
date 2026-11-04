import { describe, expect, it } from 'vitest'
import { paged } from './supabaseAdapter'

function fakeTable(total: number) {
  const calls: { orders: string[]; from: number; to: number }[] = []
  const build = () => {
    const orders: string[] = []
    const query = {
      order(key: string) { orders.push(key); return query },
      async range(from: number, to: number) {
        calls.push({ orders, from, to })
        const data = Array.from({ length: Math.max(0, Math.min(total, to + 1) - from) }, (_, i) => ({ id: from + i }))
        return { data, error: null }
      },
    }
    return query
  }
  return { build, calls }
}

describe('paged supabase reads', () => {
  it('reads past the 1,000-row response cap', async () => {
    const table = fakeTable(2_345)
    const result = await paged(table.build)(new AbortController().signal)
    expect(result.data).toHaveLength(2_345)
    expect(table.calls.map(call => [call.from, call.to])).toEqual([[0, 999], [1_000, 1_999], [2_000, 2_999]])
    expect(table.calls.every(call => call.orders.includes('id'))).toBe(true)
  })

  it('stops after one request when the table fits in a page', async () => {
    const table = fakeTable(12)
    const result = await paged(table.build, ['opportunity_id', 'contact_id'])(new AbortController().signal)
    expect(result.data).toHaveLength(12)
    expect(table.calls).toHaveLength(1)
    expect(table.calls[0].orders).toEqual(['opportunity_id', 'contact_id'])
  })

  it('returns the error instead of partial rows', async () => {
    const build = () => { const query: any = { order: () => query, range: async () => ({ data: null, error: { message: 'permission denied' } }) }; return query }
    const result = await paged(build)(new AbortController().signal)
    expect(result).toEqual({ data: null, error: { message: 'permission denied' } })
  })
})
