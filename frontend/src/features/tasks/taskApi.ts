import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import { apiFetch } from '../../shared/api/client'
import { apiError, safeError } from '../../shared/i18n'

export class TaskRequestError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) { super(message); this.status = status; this.code = code }
}

export function taskErrorMessage(issue: unknown, fallback: string, customerView: boolean, conflictMessage?: string) {
  const code = issue instanceof TaskRequestError ? issue.code : issue
  if (customerView && (code === 'source_conflict' || code === 'task_source_conflict')) {
    return '本次任务使用的资料或版本与记录不一致。请重新读取任务，核对所选资料和版本。如果仍有问题，请联系客服。'
  }
  if (issue instanceof TaskRequestError && issue.status === 409 && conflictMessage) return conflictMessage
  return typeof issue === 'string' ? apiError({ code: issue }, fallback) : safeError(issue, fallback)
}

function responseCode(value: unknown) {
  if (!value || typeof value !== 'object') return
  const detail = 'detail' in value ? value.detail : value
  if (detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string') return detail.code
}
export async function taskRequest<T>(url: string, controller: AbortController, valid: (value: unknown) => value is T,
  fallback: string, init?: RequestInit, timeoutMs = STANDARD_REQUEST_TIMEOUT_MS): Promise<T> {
  let timer = 0
  try {
    return await Promise.race([
      apiFetch(url, { ...init, signal: controller.signal }).then(async response => {
        const value: unknown = await response.json().catch(() => null)
        if (!response.ok) throw new TaskRequestError(apiError(value, fallback), response.status, responseCode(value))
        if (!valid(value)) throw new Error(fallback)
        return value
      }),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => { reject(new TaskRequestError(fallback, 408)); controller.abort() }, timeoutMs)
      }),
    ])
  } finally { window.clearTimeout(timer) }
}
