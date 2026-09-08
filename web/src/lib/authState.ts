export type AuthView = 'loading' | 'dashboard' | 'login'

export function authView(authLoading: boolean, session: unknown): AuthView {
  if (authLoading) return 'loading'
  return session ? 'dashboard' : 'login'
}
