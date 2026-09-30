import { captureProjectAccess, invalidateProjectAccess } from './projectAccess'

let generation = 0
let csrfToken: string | null = null
const listeners = new Set<() => void>()
const cookieChangeListeners = new Set<() => void>()
const sessionChangeListeners = new Set<() => void>()

export function onApiSessionChanged(listener: () => void) {
  sessionChangeListeners.add(listener)
  return () => { sessionChangeListeners.delete(listener) }
}

export function captureApiSession(): () => void {
  const captured = generation
  return () => {
    if (captured !== generation) throw new DOMException('会话已改变', 'AbortError')
  }
}

export function onSessionCookieChanged(listener: () => void) {
  cookieChangeListeners.add(listener)
  return () => { cookieChangeListeners.delete(listener) }
}

export function setApiSession(token: string) {
  generation++
  invalidateProjectAccess()
  csrfToken = token
  sessionChangeListeners.forEach(listener => listener())
}

export function clearApiSession() {
  generation++
  invalidateProjectAccess()
  csrfToken = null
  sessionChangeListeners.forEach(listener => listener())
}

export function onSessionExpired(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

// Responses and their asynchronously consumed bodies belong to their originating session.
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const requestGeneration = generation
  const projectAccess = captureProjectAccess(input)
  const changesCookie = input === '/api/v1/auth/login' || input === '/api/v1/auth/logout'
  let cookieChangeReported = false
  const reportCookieChange = () => {
    if (!changesCookie || cookieChangeReported) return
    cookieChangeReported = true
    cookieChangeListeners.forEach(listener => listener())
  }
  const check = () => {
    if (init.signal?.aborted || requestGeneration !== generation) {
      // Fetch has already applied Set-Cookie, even when its payload is obsolete.
      reportCookieChange()
      throw new DOMException('会话已改变', 'AbortError')
    }
    projectAccess.check()
  }
  check()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes((init.method ?? 'GET').toUpperCase())) {
    headers.set('X-PaperAssist-Client', 'web')
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(input, { ...init, headers, credentials: 'same-origin' })
  check()
  if (response.status === 401 && input !== '/api/v1/auth/login') {
    const wasAuthenticated = csrfToken !== null
    clearApiSession()
    if (wasAuthenticated) listeners.forEach(listener => listener())
    return response
  }
  if (response.status === 404 && /^\/api\/v1\/projects\/[^/?#]+(?:[/?#]|$)/.test(input)) {
    check()
    const body = await response.clone().json().catch(() => null)
    check()
    if (body?.detail?.code === 'project_not_found') projectAccess.unavailable()
  }
  const protect = (source: Response): Response => new Proxy(source, {
    get(target, property) {
      const value = Reflect.get(target, property, target)
      if (typeof value !== 'function') return value
      if (property === 'clone') return () => { check(); return protect(target.clone()) }
      if (['json', 'text', 'blob', 'arrayBuffer', 'formData', 'bytes'].includes(String(property))) {
        return async (...args: unknown[]) => {
          check()
          let result: unknown
          try {
            result = await value.apply(target, args)
          } catch (cause) {
            // A successful auth response may have set the cookie even if its body fails.
            if (target.ok || requestGeneration !== generation || init.signal?.aborted) reportCookieChange()
            throw cause
          }
          check()
          return result
        }
      }
      return value.bind(target)
    },
  })
  return protect(response)
}
