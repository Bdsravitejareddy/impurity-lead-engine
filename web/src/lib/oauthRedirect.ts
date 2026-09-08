const PRODUCTION_ORIGIN = 'https://svak-intelligence.pages.dev'

export function oauthRedirectUrl(origin: string, hostname: string): string {
  return hostname === 'svak-intelligence.pages.dev' ? PRODUCTION_ORIGIN : origin
}
