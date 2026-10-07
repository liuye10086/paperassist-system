type Scope = { valid: boolean; onUnavailable: () => void }
const scopes = new Map<string, Scope>()

export function watchProjectAccess(projectId: string, onUnavailable: () => void): () => void {
  const previous = scopes.get(projectId)
  if (previous) previous.valid = false
  const scope = { valid: true, onUnavailable }
  scopes.set(projectId, scope)
  return () => {
    scope.valid = false
    if (scopes.get(projectId) === scope) scopes.delete(projectId)
  }
}

// Keep invalid registrations until their owner disposes or replaces them.
export function invalidateProjectAccess() {
  scopes.forEach(scope => { scope.valid = false })
}

export function captureProjectAccess(input: string): { check(): void; unavailable(): void } {
  const match = /^\/api\/v1\/projects\/([^/?#]+)(?:[/?#]|$)/.exec(input)
  let projectId: string | undefined
  try { projectId = match ? decodeURIComponent(match[1]) : undefined } catch { /* malformed paths have no registration */ }
  const scope = projectId === undefined ? undefined : scopes.get(projectId)
  return {
    check() {
      if (scope && !scope.valid) throw new DOMException('项目访问实例已失效', 'AbortError')
    },
    unavailable() {
      if (!scope?.valid) return
      scope.valid = false
      scope.onUnavailable()
    },
  }
}
