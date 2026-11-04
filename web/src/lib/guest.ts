// Shared read-only guest account. Its password lives only in Supabase Auth;
// the guest_read_only migration blocks its writes and must use the same email.
export const GUEST_USERNAME = 'guest'
export const GUEST_EMAIL = 'guest@svak-intelligence.pages.dev'

// The sign-in form accepts an email, or the username "Guest" for the guest account.
export function signInEmail(identifier: string): string {
  const value = identifier.trim()
  return value.toLowerCase() === GUEST_USERNAME ? GUEST_EMAIL : value
}

export function isGuestEmail(email: string | null | undefined): boolean {
  return String(email || '').trim().toLowerCase() === GUEST_EMAIL
}
