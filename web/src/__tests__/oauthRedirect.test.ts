import { describe, expect, it } from 'vitest'
import { oauthRedirectUrl } from '../lib/oauthRedirect'

describe('OAuth redirect URL', () => {
  it('uses the production origin on Cloudflare Pages', () => {
    expect(oauthRedirectUrl('https://svak-intelligence.pages.dev', 'svak-intelligence.pages.dev')).toBe('https://svak-intelligence.pages.dev')
  })
  it('preserves the current origin for local development', () => {
    expect(oauthRedirectUrl('http://localhost:5174', 'localhost')).toBe('http://localhost:5174')
  })
})
