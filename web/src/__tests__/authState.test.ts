import { describe, expect, it } from 'vitest'
import { authView } from '../lib/authState'

describe('auth lifecycle view', () => {
  it('keeps unresolved sessions on loading UI', () => expect(authView(true, null)).toBe('loading'))
  it('shows dashboard after authenticated session resolves', () => expect(authView(false, { user: {} })).toBe('dashboard'))
  it('shows login after unauthenticated session resolves', () => expect(authView(false, null)).toBe('login'))
  it('supports SIGNED_IN and SIGNED_OUT state transitions', () => {
    expect(authView(false, { user: { id: 'x' } })).toBe('dashboard')
    expect(authView(false, null)).toBe('login')
  })
})
