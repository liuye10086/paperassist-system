import { apiFetch } from '../../shared/api/client'
import { apiError } from '../../shared/i18n'

export class TaskRequestError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
export async function taskRequest<T>(url: string, controller: AbortController, valid: (value: unknown) => value is T,
  fallback: string, init?: RequestInit): Promise<T> {
  let timer = 0
  try {
    return await Promise.race([
      apiFetch(url, { ...init, signal: controller.signal }).then(async response => {
        const value: unknown = await response.json().catch(() => null)
        if (!response.ok) throw new TaskRequestError(apiError(value, fallback), response.status)
        if (!valid(value)) throw new Error(fallback)
        return value
      }),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => { controller.abort(); reject(new Error(fallback)) }, 15_000)
      }),
    ])
  } finally { window.clearTimeout(timer) }
}
