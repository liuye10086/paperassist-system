export type ArtifactSubmission = Readonly<{ key: string; body: string }>

export function createArtifactSubmission(body: unknown): ArtifactSubmission {
  return Object.freeze({ key: crypto.randomUUID(), body: JSON.stringify(body) })
}

export class ArtifactRequestError extends Error {
  status: number
  constructor(text: string, status: number) { super(text); this.status = status }
}

// A server failure or transport loss may occur after the task was accepted.
export function isExplicitRejection(cause: unknown) {
  return cause instanceof ArtifactRequestError && cause.status >= 400 && cause.status < 500 && cause.status !== 408
}

export function isArtifactState(value: unknown, artifact: 'figure' | 'explanation'): boolean {
  if (!value || typeof value !== 'object') return false
  const state = value as Record<string, unknown>
  if (state.task != null) {
    if (typeof state.task !== 'object') return false
    const task = state.task as Record<string, unknown>
    if (typeof task.id !== 'string' || !Number.isInteger(task.revision)
      || !['queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'].includes(String(task.status))) return false
  }
  return typeof state.is_current === 'boolean' && (state.current_revision === null || typeof state.current_revision === 'number')
    && Object.hasOwn(state, artifact) && (state[artifact] === null || typeof state[artifact] === 'object')
    && Object.hasOwn(state, 'job') && (state.job === null || typeof state.job === 'object')
}
