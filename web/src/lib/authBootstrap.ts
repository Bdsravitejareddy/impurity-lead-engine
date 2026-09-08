export type AuthClient = {
  auth: {
    getSession: () => Promise<{ data: { session: unknown | null }; error?: unknown | null }>
    setSession: (tokens: { access_token: string; refresh_token: string }) => Promise<{ data: { session: unknown | null }; error?: unknown | null }>
    onAuthStateChange: (callback: (event: string, session: unknown | null) => void) => { data: { subscription: { unsubscribe: () => void } } }
  }
}

export type AuthBootstrapState = { session: unknown | null; loading: boolean; error?: string }

function errorCategory(error: unknown): string {
  if (error && typeof error === 'object') {
    const value = error as { code?: unknown; name?: unknown }
    if (typeof value.code === 'string' && value.code) return value.code
    if (typeof value.name === 'string' && value.name) return value.name
  }
  return 'session_initialization_failed'
}

export function bootstrapAuth(client: AuthClient, onState: (state: AuthBootstrapState) => void) {
  let active = true
  let initialized = false
  let observedSession: unknown | null = null
  onState({ session: null, loading: true })
  const { data: { subscription } } = client.auth.onAuthStateChange((event, session) => {
    if (!active) return
    if (session || event === 'SIGNED_OUT') observedSession = session
    onState({ session: session || observedSession, loading: !initialized && event !== 'SIGNED_IN' && event !== 'SIGNED_OUT' })
  })
  const ready = client.auth.getSession().then(async ({ data, error }) => {
    if (error) throw error
    if (!active) return data.session
    initialized = true
    let resolvedSession = data.session || observedSession
    if (!resolvedSession && typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
      const accessToken = params.get('access_token')
      const refreshToken = params.get('refresh_token')
      if (accessToken && refreshToken) {
        const recovered = await client.auth.setSession({ access_token: accessToken, refresh_token: refreshToken })
        if (recovered.error) throw recovered.error
        resolvedSession = recovered.data.session
        if (resolvedSession) window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`)
      }
    }
    onState({ session: resolvedSession, loading: false })
    return resolvedSession
  }).catch((error) => {
    if (active) { initialized = true; onState({ session: null, loading: false, error: errorCategory(error) }) }
    throw error
  })
  return { ready, unsubscribe: () => { active = false; subscription.unsubscribe() } }
}
