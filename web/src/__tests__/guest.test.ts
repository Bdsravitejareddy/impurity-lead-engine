import { describe, expect, it } from 'vitest'
import { GUEST_EMAIL, isGuestEmail, signInEmail } from '../lib/guest'

describe('guest sign-in', () => {
  it('maps the Guest username to the guest account in any case', () => {
    expect(signInEmail('Guest')).toBe(GUEST_EMAIL)
    expect(signInEmail('  guest ')).toBe(GUEST_EMAIL)
  })

  it('passes real email addresses through unchanged', () => {
    expect(signInEmail('analyst@example.com')).toBe('analyst@example.com')
  })

  it('recognizes the guest session', () => {
    expect(isGuestEmail(GUEST_EMAIL.toUpperCase())).toBe(true)
    expect(isGuestEmail('analyst@example.com')).toBe(false)
    expect(isGuestEmail(null)).toBe(false)
  })
})
