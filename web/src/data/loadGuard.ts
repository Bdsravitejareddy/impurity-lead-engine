export const DEFAULT_QUERY_TIMEOUT_MS = 10_000

export type LoadWithTimeoutOptions = {
  timeoutMs?: number
  diagnostics?: string[]
  onDiagnostic?: (code: string) => void
}

function report(code: string, options: LoadWithTimeoutOptions) {
  options.diagnostics?.push(code)
  options.onDiagnostic?.(code)
  if (typeof console !== 'undefined' && typeof console.warn === 'function') console.warn(code)
}

export async function loadWithTimeout<T>(
  name: string,
  request: (signal: AbortSignal) => PromiseLike<T> | T,
  options: LoadWithTimeoutOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_QUERY_TIMEOUT_MS
  const controller = new AbortController()
  let timeout: ReturnType<typeof setTimeout> | undefined
  const operation = Promise.resolve().then(() => request(controller.signal))
  const deadline = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => {
      controller.abort()
      const error = new Error(`supabase_query_timeout:${name}`)
      report(`supabase_query_timeout:${name}`, options)
      reject(error)
    }, timeoutMs)
  })
  try {
    return await Promise.race([operation, deadline])
  } catch (error) {
    if (error instanceof Error && error.message === `supabase_query_timeout:${name}`) throw error
    report(`supabase_query_failed:${name}`, options)
    throw new Error(`supabase_query_failed:${name}`)
  } finally {
    if (timeout) clearTimeout(timeout)
  }
}

export function createSingleFlight<T>(loader: () => Promise<T>) {
  let active: Promise<T> | null = null
  return {
    run() {
      if (active) return active
      const next = loader()
      active = next
      next.finally(() => {
        if (active === next) active = null
      }).catch(() => undefined)
      return next
    },
  }
}
